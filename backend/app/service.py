"""Backend logic behind the API (app/api.py): what is available for a target, and getting frames.

Docs used (CLAUDE.md rule): docs/spherex/user-guide-data-access.md (SIA2 collections, cutouts),
irsa-cutout-service.md (center/size in degrees, cutouts follow the parent image axes, HTTP 500 =
outside the image), tutorial-intro-spectral-images.md (spectral WCS), explanatory-supplement-extracts.md
(flag table). Measurements behind the design: docs/DATA_COVERAGE.md.

Design in one paragraph: the API never waits on IRSA by default. `coverage` runs search + wavelength
lookup in a background thread and is polled; it is stored per POSITION (+ motion), and each request filters
it for its own field of view, so zooming needs no new lookup. Pixel data is fetched by a pool of worker
threads from a priority queue (0 = a user is waiting, 1 = background prefetch). Cutouts are made from byte
ranges of the S3 copy (app/cutout.py), so many can run at once; requests to IRSA itself stay limited
(spherex.IRSA_SLOTS, it answers 503 when hit harder). As soon as a coverage is ready, every frame of the
requested view is prefetched; a user's request for a queued frame moves it to the front. Fetched cutouts are
stored in Postgres (app/db.py, schema in app/schema.sql) together with the search results and calibration
files, and never go stale (the URL contains the file version). Only reprojected frames are kept in memory.
Measurements behind these choices: docs/FETCH_SPEED.md.
"""
from __future__ import annotations

import io
import itertools
import logging
import math
import os
import queue
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import asdict, dataclass, field, fields

import httpx
import numpy as np
from astropy.io import fits

from . import db, spherex
from .core import (  # noqa: F401 - re-exported: older code imports these from here
    CUTOUT_FACTOR, FOV_MAX, FOV_MIN, PIXEL_SCALE_ARCSEC, VISIT_GAP_DAYS, ApiError, TargetSpec, frame_id, iso,
    parse_coord, split_frame_id,
)

log = logging.getLogger("spherex.service")

# --- settings -------------------------------------------------------------------------------
WORKERS = int(os.environ.get("SPHEREX_WORKERS", "8"))  # parallel cutout downloads (mostly S3; IRSA itself is
#                                                       capped separately by spherex.IRSA_SLOTS)
PREFETCH = os.environ.get("SPHEREX_PREFETCH", "1") != "0"  # fetch every frame of a view once its coverage is ready
PRIORITY_USER, PRIORITY_PREFETCH, PRIORITY_ANALYSIS = 0, 1, 2  # lower runs first; only prefetch may be cancelled
COVERAGE_TTL_S = 3600.0  # re-search after this long, so new weekly data appears
REFRESH_RETRY_S = 120.0  # a failed refresh is retried after this long (the old data keeps being served)
ERROR_RETRY_S = 15.0  # a failed first build is retried after this long
COLLECTIONS_TTL_S = 3600.0  # ask IRSA for its collection list again after this long
FAIL_COOLDOWN_S = 20.0  # after a failed download, don't hit IRSA again for this long
SEARCH_RETRIES = 4  # IRSA's search service returns 502 now and then
MAX_ALIGNED_BYTES = int(os.environ.get("SPHEREX_FRAME_CACHE_MB", "256")) * 1_000_000  # aligned frames in memory
#   (~20 KB per frame at fov 0.08, ~250 KB at fov 0.3; a count limit was smaller than one target's 350 frames)
RECORD_FIELDS = [f.name for f in fields(spherex.ImageRecord)]


# --- job queue ------------------------------------------------------------------------------
class JobQueue:
    """Worker threads taking jobs lowest priority number first (0 = user is waiting, 1 = prefetch)."""

    def __init__(self, workers: int):
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        for i in range(workers):
            threading.Thread(target=self._run, name=f"irsa-worker-{i}", daemon=True).start()

    def submit(self, priority: int, fn, fut: Future | None = None) -> Future:
        """Queue `fn`. Passing the Future of a job that is still queued queues it again with a better priority:
        whichever entry a worker takes first runs it, the other entry is skipped."""
        fut = fut if fut is not None else Future()
        self._q.put((priority, next(self._seq), fut, fn))
        return fut

    def _run(self) -> None:
        while True:
            _, _, fut, fn = self._q.get()
            try:
                if not fut.set_running_or_notify_cancel():
                    continue  # cancelled
            except RuntimeError:  # already running or done through another queue entry
                continue
            try:
                fut.set_result(fn())
            except BaseException as err:  # noqa: BLE001 - delivered to whoever waits on the future
                fut.set_exception(err)

    def __len__(self) -> int:
        return self._q.qsize()


# --- coverage -------------------------------------------------------------------------------
@dataclass
class CoverageView:
    """A Coverage seen with one field of view: only the images that contain the whole view."""

    state: str
    message: str | None
    located: int
    total: int
    records: dict[str, spherex.ImageRecord]  # frame_id -> record
    exposures: list[spherex.Exposure]  # located images, time order
    visits: list[list[spherex.ImageRecord]]  # one list of images per visit
    visit_of: dict[str, int]  # frame_id -> visit index
    collections: list[str] = field(default_factory=list)  # collections searched
    data_as_of: float = 0.0  # when the search results came from IRSA (Unix time)


@dataclass
class Coverage:
    """Everything known about one position (+ motion), for every field of view."""

    spec: TargetSpec  # the first request's; only its position and motion matter
    state: str = "searching"  # searching | locating | ready | error
    message: str | None = None
    collections: list[str] = field(default_factory=list)
    records: dict[str, spherex.ImageRecord] = field(default_factory=dict)  # frame_id -> record, position inside
    exposures: list[spherex.Exposure] = field(default_factory=list)  # located images, time order
    located: int = 0
    total: int = 0
    failed_locate: int = 0
    refreshing: bool = False
    started: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    data_as_of: float = 0.0  # when the search results were obtained from IRSA
    next_refresh: float = 0.0  # when to look for new data again

    def view(self, fov_deg: float) -> CoverageView:
        """Keep the images whose edge is at least half the view's diagonal away from the position (the same
        filter the search used to apply per fov), and group them into visits."""
        margin = fov_deg / 2 * math.sqrt(2)
        recs = [r for r in self.records.values() if r.edge_margin_deg >= margin]
        keep = {frame_id(r) for r in recs}
        visits = spherex.group_seasons(recs, VISIT_GAP_DAYS)
        return CoverageView(
            state=self.state, message=self.message, located=self.located, total=self.total,
            records={frame_id(r): r for r in recs},
            exposures=[e for e in self.exposures if frame_id(e.record) in keep],
            visits=visits, visit_of={frame_id(r): i for i, v in enumerate(visits) for r in v},
            collections=list(self.collections), data_as_of=self.data_as_of)


@dataclass
class AlignedFrame:
    """A frame on the common north-up grid of the view."""

    frame_id: str
    record: spherex.ImageRecord
    image: np.ndarray  # (n, n) float32, bad pixels NaN; row 0 = south
    raw: np.ndarray  # same, nothing masked
    bad: np.ndarray  # (n, n) bool: flagged bad (NONFUNC, HOT, COLD, TRANSIENT)
    target_xy: tuple[float, float]  # 0-based pixel position of the predicted target (may be outside)
    wavelength_um: float
    bandwidth_um: float
    flags_at_target: list[str]
    version: str


class Service:
    def __init__(self, store: db.Store = db.store) -> None:
        self.db = store  # persistent cache (app/db.py): collections, coverage, cutouts, calibration files
        self._lock = threading.RLock()
        self._cov: dict[str, Coverage] = {}  # coverage_key -> live state, including builds in progress
        self._jobs = JobQueue(WORKERS)
        self._inflight: dict[str, Future] = {}  # cutout key -> running or queued download
        self._job: dict[str, tuple[object, int]] = {}  # cutout key -> (job function, best priority queued)
        self._wanted: set[str] = set()  # cutout keys a user or an analysis asked for (never cancelled as stale prefetch)
        self._prefetch_view: dict[str, str] = {}  # coverage_key -> spec.key of the view being prefetched
        self._prefetch_jobs: dict[str, list[tuple[str, Future]]] = {}  # coverage_key -> its queued downloads
        self._aligned: OrderedDict[tuple, AlignedFrame] = OrderedDict()  # hot frames, in memory only
        self._aligned_bytes = 0
        # each range cutout uses up to 4 connections at once (app/cutout.py)
        self._client = httpx.Client(timeout=180, follow_redirects=True,
                                    limits=httpx.Limits(max_connections=WORKERS * 4, max_keepalive_connections=WORKERS * 4))

    # -- search ------------------------------------------------------------------------------
    def collections(self) -> list[str]:
        """SPHEREx SIA2 collections IRSA currently lists (new releases appear by themselves). Asked again
        after COLLECTIONS_TTL_S; the stored list is used when IRSA is down."""
        stored = self.db.collections()
        if stored and time.time() - stored[1] < COLLECTIONS_TTL_S:
            return stored[0]
        try:
            names = self._retry(spherex.spherex_collections, "listing collections")
        except ApiError:
            if not stored:
                raise
            log.warning("IRSA collection list unavailable, using the last known one: %s", stored[0])
            return stored[0]
        self.db.save_collections(names)
        return names

    # -- persisted coverage (survives restarts and IRSA outages) ---------------------------
    def _save(self, cov: "Coverage") -> None:
        located = {frame_id(e.record): e for e in cov.exposures}
        images = []
        for fid, r in cov.records.items():
            e = located.get(fid)
            images.append({**asdict(r), "frame_id": fid, "x": e.x if e else None, "y": e.y if e else None,
                           "wavelength_um": e.wavelength_um if e else None,
                           "bandwidth_um": e.bandwidth_um if e else None})
        s = cov.spec
        target = {"ra": s.ra, "dec": s.dec, "fov_deg": None, "pmra": s.pmra, "pmdec": s.pmdec, "pm_epoch": s.pm_epoch}
        try:
            self.db.save_coverage(s.coverage_key, target, cov.collections, cov.failed_locate, cov.data_as_of, images)
        except Exception:  # noqa: BLE001 - the coverage is still served from memory
            log.exception("could not save coverage %s", s.coverage_key)

    def _load(self, spec: TargetSpec) -> "Coverage | None":
        data = self.db.load_coverage(spec.coverage_key)
        if data is None:
            return None
        recs, exposures = [], []
        for img in data["images"]:
            r = spherex.ImageRecord(**{f: img[f] for f in RECORD_FIELDS if f in img})
            recs.append(r)
            if img["x"] is not None:
                exposures.append(spherex.Exposure(r, img["x"], img["y"], img["wavelength_um"], img["bandwidth_um"]))
        cov = Coverage(spec, state="ready", collections=data["collections"], records={frame_id(r): r for r in recs},
                       failed_locate=data["failed_locate"], data_as_of=data["data_as_of"])
        cov.exposures = exposures
        cov.located = cov.total = len(recs)
        cov.next_refresh = data["data_as_of"] + COVERAGE_TTL_S
        return cov

    @staticmethod
    def _retry(fn, what: str):
        delay = 4.0
        for attempt in range(SEARCH_RETRIES):
            try:
                return fn()
            except Exception as err:  # IRSA returns 502 now and then
                log.warning("%s failed (attempt %d): %s", what, attempt + 1, str(err)[:120])
                if attempt == SEARCH_RETRIES - 1:
                    raise ApiError(502, "irsa_unavailable", f"IRSA {what} failed: {str(err)[:160]}") from err
                time.sleep(delay)
                delay *= 2

    def _search(self, spec: TargetSpec) -> tuple[list[str], list[spherex.ImageRecord]]:
        """Every image that contains the position, with its distance from the edge (any fov is filtered later)."""
        cols = self.collections()
        recs = self._retry(lambda: spherex.search(spec.center, cols), "search")
        return cols, spherex.filter_records(recs, spec.center, min_edge_margin_deg=0.0)

    # -- coverage ----------------------------------------------------------------------------
    def coverage(self, spec: TargetSpec, all_images: bool = False) -> CoverageView:
        """The current knowledge about `spec`'s position, filtered for its fov. Starts a background build the
        first time (and after errors or when the data is older than COVERAGE_TTL_S); callers poll until
        state == "ready". Once ready, every frame of this view is prefetched in the background.
        `all_images=True` returns every image that contains the position, also where the view would cross the
        image edge (the epoch maps use those too: their pictures simply have no data there)."""
        with self._lock:
            ck = spec.coverage_key
            cov = self._cov.get(ck)
            now = time.time()
            if cov is None:
                saved = self._load(spec)  # an earlier visit (or before a restart): show it at once
                if saved is not None:
                    cov = self._cov[ck] = saved
            if cov is None or (cov.state == "error" and now - cov.updated > ERROR_RETRY_S):
                cov = self._cov[ck] = Coverage(spec)
                threading.Thread(target=self._build, args=(cov, None), daemon=True, name=f"cov-{ck}").start()
            elif cov.state == "ready" and not cov.refreshing and now >= cov.next_refresh:
                cov.refreshing = True  # look for new data in the background, keep serving what we have
                threading.Thread(target=self._build, args=(Coverage(spec), cov), daemon=True, name=f"cov-{ck}").start()
        view = cov.view(spec.fov_deg)
        if view.state == "ready":
            self._start_prefetch(spec, view)
        return cov.view(0.0) if all_images else view

    def _build(self, cov: Coverage, replaces: Coverage | None) -> None:
        def progress(done: int, total: int) -> None:
            cov.located, cov.total, cov.updated = done, total, time.time()

        try:
            cov.state = "searching"
            cov.collections, recs = self._search(cov.spec)
            cov.records = {frame_id(r): r for r in recs}
            cov.total = len(recs)
            cov.state = "locating"
            cov.updated = time.time()
            exps, failed = spherex.locate_on_detector(recs, cov.spec.at, on_progress=progress, calib_cache=self.db)
            cov.exposures, cov.failed_locate = exps, len(failed)
            cov.located = cov.total
            cov.state, cov.updated = "ready", time.time()
            cov.data_as_of = cov.updated
            cov.next_refresh = cov.updated + COVERAGE_TTL_S
            self._save(cov)
            if replaces is not None:
                with self._lock:
                    self._cov[cov.spec.coverage_key] = cov
                    self._prefetch_view.pop(cov.spec.coverage_key, None)  # prefetch the new images too
            log.info("coverage %s ready: %d images, %d not located", cov.spec.coverage_key, len(exps), len(failed))
        except Exception as err:  # noqa: BLE001
            msg = getattr(err, "message", str(err))[:300]
            log.error("coverage build failed: %s", msg)
            if replaces is not None:  # keep serving the old data, try again in a couple of minutes
                replaces.refreshing = False
                replaces.next_refresh = time.time() + REFRESH_RETRY_S
                replaces.message = f"Could not look for new data ({msg}). Showing the data from the last successful lookup."
            else:
                cov.state, cov.message, cov.updated = "error", msg, time.time()

    def record_for(self, spec: TargetSpec, fid: str) -> spherex.ImageRecord:
        """Resolve a frame id to its image (one that contains the whole view): from the coverage in memory or
        in the database, else by searching again."""
        split_frame_id(fid)
        cov = self._cov.get(spec.coverage_key) or self._load(spec)
        if cov is not None:
            hit = cov.view(spec.fov_deg).records.get(fid)
            if hit is not None:
                return hit
        _, recs = self._search(spec)
        for r in recs:
            if frame_id(r) == fid and r.edge_margin_deg >= spec.edge_margin_deg:
                return r
        raise ApiError(404, "unknown_frame", f"no image {fid} covers this position/field of view")

    # -- prefetch ----------------------------------------------------------------------------
    def _start_prefetch(self, spec: TargetSpec, view: CoverageView) -> None:
        """Queue every frame of this view (once per view). A newer view of the same position replaces an older
        one: its queued downloads are cancelled, unless a user asked for them."""
        if not PREFETCH:
            return
        ck = spec.coverage_key
        with self._lock:
            if self._prefetch_view.get(ck) == spec.key:
                return
            self._prefetch_view[ck] = spec.key
            stale = self._prefetch_jobs.pop(ck, [])
            for key, fut in stale:
                if key not in self._wanted:
                    fut.cancel()  # only succeeds while still queued
        threading.Thread(target=self._prefetch, args=(spec, view), daemon=True, name=f"prefetch-{ck}").start()

    def _prefetch(self, spec: TargetSpec, view: CoverageView) -> None:
        recs = [e.record for e in view.exposures if np.isfinite(e.wavelength_um)]
        try:
            states = self.frame_states(spec, recs)
        except Exception:  # noqa: BLE001 - database down: nothing to prefetch into
            log.exception("prefetch: could not read cache states")
            return
        jobs = []
        for r, state in zip(recs, states):
            if state != "missing":
                continue
            try:
                fut = self.ensure_cutout(spec, r, PRIORITY_PREFETCH)
            except Exception:  # noqa: BLE001 - outside / recently failed: skip
                continue
            if fut is not None:
                jobs.append((self._cutout_ref(spec, r)[0], fut))
        with self._lock:
            if self._prefetch_view.get(spec.coverage_key) == spec.key:
                self._prefetch_jobs[spec.coverage_key] = jobs
                log.info("prefetching %d frames for view %s", len(jobs), spec.key)
            else:  # the user moved on while we were queueing
                for key, fut in jobs:
                    if key not in self._wanted:
                        fut.cancel()

    # -- cutouts -----------------------------------------------------------------------------
    @property
    def http(self) -> httpx.Client:
        """The shared HTTP client (connection pool sized for the download workers)."""
        return self._client

    def cutout_data(self, spec: TargetSpec, record: spherex.ImageRecord) -> bytes | None:
        """The stored cutout of `record` for `spec`'s view (FITS bytes), or None if not downloaded."""
        return self.db.cutout(self._cutout_ref(spec, record)[0])

    @staticmethod
    def _cutout_ref(spec: TargetSpec, record: spherex.ImageRecord) -> tuple[str, str]:
        url = spherex.cutout_url(record, spec.center, spec.cutout_size)
        return spherex.cutout_key(url), url

    def frame_states(self, spec: TargetSpec, records: list[spherex.ImageRecord]) -> list[str]:
        """For each record: ready | fetching | queued | failed | outside | missing (one database query)."""
        keys = [self._cutout_ref(spec, r)[0] for r in records]
        stored = self.db.cutout_states(keys)
        out = []
        with self._lock:
            for key in keys:
                fut = self._inflight.get(key)
                status, updated, _ = stored.get(key, (None, 0.0, None))
                if status in ("ready", "outside"):
                    out.append(status)
                elif fut is not None and not fut.done():
                    out.append("fetching" if fut.running() else "queued")
                elif status == "error" and time.time() - updated < FAIL_COOLDOWN_S:
                    out.append("failed")
                else:
                    out.append("missing")
        return out

    def frame_state(self, spec: TargetSpec, record: spherex.ImageRecord) -> str:
        return self.frame_states(spec, [record])[0]

    def _join(self, key: str, fut: Future, priority: int) -> Future:
        """Share a pending download; a user (priority 0) waiting on a queued prefetch moves it to the front.
        Anyone but the prefetch marks it as wanted, so a stale prefetch's cancellation leaves it alone."""
        if priority != PRIORITY_PREFETCH:
            self._wanted.add(key)
        job, queued = self._job.get(key, (None, priority))
        if job is not None and priority < queued and not fut.running():
            self._job[key] = (job, priority)
            self._jobs.submit(priority, job, fut=fut)
        return fut

    def ensure_cutout(self, spec: TargetSpec, record: spherex.ImageRecord, priority: int) -> Future | None:
        """Make sure the cutout is (being) fetched. Returns None if already stored, else the pending Future
        (shared by everyone asking for the same cutout)."""
        key, url = self._cutout_ref(spec, record)
        with self._lock:
            fut = self._inflight.get(key)
            if fut is not None and not fut.done():
                return self._join(key, fut, priority)
        status, updated, message = self.db.cutout_states([key]).get(key, (None, 0.0, None))
        if status == "ready":
            return None
        if status == "outside":
            raise ApiError(404, "outside_image", "the requested field is outside this image")
        if status == "error" and time.time() - updated < FAIL_COOLDOWN_S:
            raise ApiError(502, "upstream_error", f"recent download failed, retry later: {message}")

        with self._lock:
            fut = self._inflight.get(key)
            if fut is not None and not fut.done():
                return self._join(key, fut, priority)

            def job() -> None:
                try:
                    data = spherex.download_cutout(record, spec.center, spec.cutout_size, self._client,
                                                   layouts=self.db)
                except spherex.OutsideImageError:
                    self.db.put_cutout_failure(key, url, "outside", "outside image")
                    raise
                except Exception as err:
                    self.db.put_cutout_failure(key, url, "error", str(err)[:200])
                    raise
                self.db.put_cutout(key, url, data)

            fut = self._jobs.submit(priority, job)
            self._inflight[key] = fut
            self._job[key] = (job, priority)
            if priority != PRIORITY_PREFETCH:
                self._wanted.add(key)

            def done(_f: Future, key=key) -> None:
                with self._lock:
                    if self._inflight.get(key) is _f:
                        self._inflight.pop(key, None)
                        self._job.pop(key, None)
                        self._wanted.discard(key)

            fut.add_done_callback(done)
            return fut

    # -- pixels ------------------------------------------------------------------------------
    def aligned_frame(self, spec: TargetSpec, record: spherex.ImageRecord) -> AlignedFrame:
        """Read the stored cutout and put it on the view's north-up grid (~65 ms). Cutout must be stored."""
        ck = (spec.key, frame_id(record))
        with self._lock:
            hit = self._aligned.get(ck)
            if hit is not None:
                self._aligned.move_to_end(ck)
                return hit
        data = self.db.cutout(self._cutout_ref(spec, record)[0])
        if data is None:
            raise ApiError(409, "not_downloaded", f"frame {frame_id(record)} is not downloaded yet, retry")
        with fits.open(io.BytesIO(data)) as hdul:
            frame = spherex.process(hdul, record, spec.at(record.t_mid_mjd))
        grid, shape = spherex.north_up_wcs(spec.center, spec.fov_deg, PIXEL_SCALE_ARCSEC / 3600)
        masked = spherex.reproject_frame(frame, grid, shape)
        raw = spherex.reproject_frame(frame, grid, shape, raw=True)
        tx, ty = (float(v) for v in grid.world_to_pixel(spec.at(record.t_mid_mjd)))
        af = AlignedFrame(
            frame_id=frame_id(record), record=record, image=masked.astype(np.float32), raw=raw.astype(np.float32),
            bad=np.isnan(masked) & np.isfinite(raw), target_xy=(tx, ty), wavelength_um=frame.wavelength_um,
            bandwidth_um=frame.bandwidth_um,
            # SOURCE (bit 21) is set on nearly every pixel (CLAUDE.md), so it says nothing about quality
            flags_at_target=[f for f in frame.flags_at_target if f != "SOURCE"], version=frame.version,
        )
        with self._lock:
            if ck not in self._aligned:
                self._aligned[ck] = af
                self._aligned_bytes += _nbytes(af)
            while self._aligned_bytes > MAX_ALIGNED_BYTES and len(self._aligned) > 1:
                _, old = self._aligned.popitem(last=False)
                self._aligned_bytes -= _nbytes(old)
        return af


def _nbytes(af: AlignedFrame) -> int:
    return af.image.nbytes + af.raw.nbytes + af.bad.nbytes

service = Service()


# --- rendering ------------------------------------------------------------------------------
MASK_RGB = (110, 30, 30)  # bad pixel, masked
NODATA_RGB = (50, 55, 70)  # outside the cutout


def stretch_limits(af: AlignedFrame) -> tuple[float, float]:
    """Default display range: the 2nd to 99.7th percentile of the good pixels of this frame."""
    good = af.raw[np.isfinite(af.raw) & ~af.bad]
    if good.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(good, [2.0, 99.7])
    return float(lo), float(hi if hi > lo else lo + 1.0)


def display_range(af: AlignedFrame, vmin: float | None, vmax: float | None) -> tuple[float, float]:
    """The brightness range a picture is drawn with: the caller's, if both ends are given, else this
    frame's own 2nd-99.7th percentile. Returned to the client (X-Stretch-Min/Max) so it can reuse
    it for other frames and keep the brightness scale fixed."""
    lo, hi = (vmin, vmax) if vmin is not None and vmax is not None else stretch_limits(af)
    return (float(lo), float(hi)) if hi > lo else (float(lo), float(lo) + 1.0)


def render_png(af: AlignedFrame, mask: bool = True, vmin: float | None = None, vmax: float | None = None,
               scale: int = 1) -> bytes:
    """8-bit RGB PNG, north up, east left, asinh stretch. Masked pixels dark red, missing pixels slate."""
    from PIL import Image

    lo, hi = display_range(af, vmin, vmax)
    t = np.clip((np.nan_to_num(af.raw, nan=lo) - lo) / (hi - lo), 0, 1)
    gray = (255 * np.arcsinh(t / 0.1) / np.arcsinh(1 / 0.1)).astype(np.uint8)
    rgb = np.stack([gray] * 3, axis=-1)
    rgb[~np.isfinite(af.raw)] = NODATA_RGB
    if mask:
        rgb[af.bad] = MASK_RGB
    rgb = rgb[::-1]  # row 0 of the data is south; images have row 0 on top
    img = Image.fromarray(rgb, "RGB")
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
