"""Backend logic behind the API (app/api.py): what is available for a target, and getting frames.

Docs used (CLAUDE.md rule): docs/spherex/user-guide-data-access.md (SIA2 collections, cutouts),
irsa-cutout-service.md (center/size in degrees, cutouts follow the parent image axes, HTTP 500 =
outside the image), tutorial-intro-spectral-images.md (spectral WCS), explanatory-supplement-extracts.md
(flag table). Measurements behind the design: docs/DATA_COVERAGE.md.

Design in one paragraph: the API never waits on IRSA by default. `coverage` runs search + wavelength
lookup in a background thread and is polled. Pixel data is fetched by a small pool of worker threads
(IRSA answers 503 when hit harder) from a priority queue (0 = a user is waiting; a higher number is kept
free for background prefetching, which the MVP API does not offer yet). Fetched cutouts are cached on
disk by spherex.py and never go stale (the URL contains the file version).
"""
from __future__ import annotations

import hashlib
import io
import itertools
import json
import logging
import math
import os
import queue
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import asdict, dataclass, field

import httpx
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time

from . import presets, spherex

log = logging.getLogger("spherex.service")

# --- settings -------------------------------------------------------------------------------
PIXEL_SCALE_ARCSEC = 6.15  # SPHEREx pixel size (docs/spherex/user-guide-data-products.md; header measures 6.15)
CUTOUT_FACTOR = 1.45  # cutout side / view side: images are rotated vs north, a square this much larger always
#                      fills the north-up view (needs sqrt(2) at worst; IRSA's cost barely depends on size)
FOV_MIN, FOV_MAX = 0.01, 0.30  # degrees
VISIT_GAP_DAYS = 30.0  # a gap longer than this between images starts a new visit (observing season)
WORKERS = int(os.environ.get("SPHEREX_WORKERS", "3"))  # parallel requests to IRSA (it rate-limits)
COVERAGE_TTL_S = 3600.0  # re-search after this long, so new weekly data appears
REFRESH_RETRY_S = 120.0  # a failed refresh is retried after this long (the old data keeps being served)
ERROR_RETRY_S = 15.0  # a failed first build is retried after this long
STATE_DIR = spherex.CACHE_DIR.parent / "coverage"  # saved search results (backend/cache/coverage/)
FAIL_COOLDOWN_S = 20.0  # after a failed download, don't hit IRSA again for this long
SEARCH_RETRIES = 4  # IRSA's search service returns 502 now and then
MAX_PIXELS_CACHE = 256  # aligned frames kept in memory


class ApiError(Exception):
    """An error with an HTTP status and a stable machine-readable code (see docs/API.md)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# --- target ---------------------------------------------------------------------------------
def parse_coord(ra: str, dec: str) -> tuple[float, float]:
    """RA/Dec as decimal degrees ("269.452", "4.6934") or sexagesimal ("17h57m48.5s", "+04d41m36s",
    "17:57:48.5"). Returns degrees."""
    ra, dec = str(ra).strip(), str(dec).strip()
    try:
        return float(ra), float(dec)
    except ValueError:
        pass
    try:
        c = SkyCoord(f"{ra} {dec}", unit=(u.hourangle, u.deg))
    except Exception as err:
        raise ApiError(400, "bad_coordinates", f"cannot read RA/Dec '{ra}' '{dec}': {err}") from err
    return float(c.ra.deg), float(c.dec.deg)


@dataclass(frozen=True)
class TargetSpec:
    """What the user is looking at: a sky position, a field of view and (optionally) the object's motion."""

    ra: float  # deg, centre of the view (fixed on the sky)
    dec: float
    fov_deg: float
    pmra: float | None = None  # mas/yr incl. cos(dec); with pmdec and pm_epoch, makes the predicted position move
    pmdec: float | None = None
    pm_epoch: float | None = None  # decimal year at which (ra, dec) is the object's position

    @staticmethod
    def build(ra: str, dec: str, fov: float, pmra: float | None, pmdec: float | None,
              pm_epoch: float | None) -> "TargetSpec":
        r, d = parse_coord(ra, dec)
        if not (0 <= r < 360 or r == 360) or not (-90 <= d <= 90):
            raise ApiError(400, "bad_coordinates", f"RA must be 0-360 deg and Dec -90..90 deg, got {r}, {d}")
        if not (FOV_MIN <= fov <= FOV_MAX):
            raise ApiError(400, "bad_fov", f"fov must be {FOV_MIN}-{FOV_MAX} degrees, got {fov}")
        if len({pmra is None, pmdec is None, pm_epoch is None}) != 1:
            raise ApiError(400, "bad_motion", "pmra, pmdec and pm_epoch must be given together, or not at all")
        return TargetSpec(round(r % 360.0, 6), round(d, 6), round(fov, 5), pmra, pmdec, pm_epoch)

    @property
    def key(self) -> str:
        raw = f"{self.ra:.6f},{self.dec:.6f},{self.fov_deg:.5f},{self.pmra},{self.pmdec},{self.pm_epoch}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    @property
    def center(self) -> SkyCoord:
        return SkyCoord(self.ra * u.deg, self.dec * u.deg)

    @property
    def cutout_size(self) -> float:
        return round(self.fov_deg * CUTOUT_FACTOR, 5)

    @property
    def n_pix(self) -> int:
        return int(math.ceil(self.fov_deg * 3600 / PIXEL_SCALE_ARCSEC))

    def at(self, mjd: float) -> SkyCoord:
        """Where the target is predicted to be at time `mjd` (the view centre if no motion was given)."""
        if self.pmra is None:
            return self.center
        years = (mjd - presets.epoch_to_mjd(self.pm_epoch)) / 365.25
        ra, dec = presets.propagate(self.ra, self.dec, self.pmra, self.pmdec, years)
        return SkyCoord(ra * u.deg, dec * u.deg)


def frame_id(record: spherex.ImageRecord) -> str:
    return f"{record.obs_id}-{record.detector}"


def split_frame_id(fid: str) -> tuple[str, str]:
    obs_id, sep, det = fid.rpartition("-")
    if not sep or not obs_id or not (len(det) == 2 and det[0] == "D" and det[1].isdigit()):
        raise ApiError(400, "bad_frame_id", f"frame id must look like '2025W35_2A_0611_1-D2', got '{fid}'")
    return obs_id, det


def iso(mjd: float) -> str:
    return Time(mjd, format="mjd").isot[:19] + "Z"


# --- job queue ------------------------------------------------------------------------------
class JobQueue:
    """Worker threads taking jobs lowest priority number first (0 = user is waiting, 1 = prefetch)."""

    def __init__(self, workers: int):
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        for i in range(workers):
            threading.Thread(target=self._run, name=f"irsa-worker-{i}", daemon=True).start()

    def submit(self, priority: int, fn) -> Future:
        fut: Future = Future()
        self._q.put((priority, next(self._seq), fut, fn))
        return fut

    def _run(self) -> None:
        while True:
            _, _, fut, fn = self._q.get()
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn())
            except BaseException as err:  # noqa: BLE001 - delivered to whoever waits on the future
                fut.set_exception(err)

    def __len__(self) -> int:
        return self._q.qsize()


# --- coverage -------------------------------------------------------------------------------
@dataclass
class Coverage:
    spec: TargetSpec
    state: str = "searching"  # searching | locating | ready | error
    message: str | None = None
    collections: list[str] = field(default_factory=list)
    records: dict[str, spherex.ImageRecord] = field(default_factory=dict)  # frame_id -> record (after search)
    exposures: list[spherex.Exposure] = field(default_factory=list)  # located images, time order
    visits: list[list[spherex.ImageRecord]] = field(default_factory=list)  # one list of images per visit
    visit_of: dict[str, int] = field(default_factory=dict)  # frame_id -> visit index
    located: int = 0
    total: int = 0
    failed_locate: int = 0
    refreshing: bool = False
    started: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    data_as_of: float = 0.0  # when the search results were obtained from IRSA
    next_refresh: float = 0.0  # when to look for new data again


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
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cov: dict[str, Coverage] = {}
        self._jobs = JobQueue(WORKERS)
        self._inflight: dict[str, Future] = {}
        self._failures: dict[str, tuple[float, str, str]] = {}  # cutout key -> (time, kind, message)
        self._aligned: OrderedDict[tuple, AlignedFrame] = OrderedDict()
        self._collections: tuple[float, list[str]] | None = None
        self._client = httpx.Client(timeout=180, follow_redirects=True, limits=httpx.Limits(max_connections=WORKERS * 2))

    # -- search ------------------------------------------------------------------------------
    def collections(self) -> list[str]:
        """SPHEREx SIA2 collections IRSA currently lists (new releases appear by themselves). The last
        successful answer is kept on disk, so an IRSA outage doesn't stop us."""
        with self._lock:
            if self._collections and time.time() - self._collections[0] < 3600:
                return self._collections[1]
        path = STATE_DIR / "collections.json"
        try:
            names = self._retry(spherex.spherex_collections, "listing collections")
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(names))
        except ApiError:
            if not path.exists():
                raise
            names = json.loads(path.read_text())
            log.warning("IRSA collection list unavailable, using the last known one: %s", names)
        with self._lock:
            self._collections = (time.time(), names)
        return names

    # -- persisted coverage (survives restarts and IRSA outages) ---------------------------
    @staticmethod
    def _state_path(spec: TargetSpec):
        return STATE_DIR / f"coverage-{spec.key}.json"

    def _save(self, cov: "Coverage") -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved": cov.data_as_of, "collections": cov.collections, "failed_locate": cov.failed_locate,
                "records": [asdict(r) for r in cov.records.values()],
                "exposures": [{"id": frame_id(e.record), "x": e.x, "y": e.y, "wl": e.wavelength_um, "bw": e.bandwidth_um}
                              for e in cov.exposures],
            }
            tmp = self._state_path(cov.spec).with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self._state_path(cov.spec))
        except Exception:  # noqa: BLE001 - persistence is an optimisation, never fatal
            log.exception("could not save coverage")

    def _load(self, spec: TargetSpec) -> "Coverage | None":
        path = self._state_path(spec)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            recs = [spherex.ImageRecord(**r) for r in data["records"]]
            by_id = {frame_id(r): r for r in recs}
            cov = Coverage(spec, state="ready", collections=data["collections"], records=by_id,
                           failed_locate=data.get("failed_locate", 0), data_as_of=data["saved"])
            cov.exposures = [spherex.Exposure(by_id[e["id"]], e["x"], e["y"], e["wl"], e["bw"]) for e in data["exposures"]]
            self._index_visits(cov, recs)
            cov.located = cov.total = len(recs)
            cov.next_refresh = data["saved"] + COVERAGE_TTL_S
            return cov
        except Exception:  # noqa: BLE001
            log.exception("ignoring unreadable saved coverage %s", path)
            return None

    @staticmethod
    def _index_visits(cov: "Coverage", recs: list[spherex.ImageRecord]) -> None:
        cov.visits = spherex.group_seasons(recs, VISIT_GAP_DAYS)
        cov.visit_of = {frame_id(r): i for i, v in enumerate(cov.visits) for r in v}

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
        cols = self.collections()
        recs = self._retry(lambda: spherex.search(spec.center, cols), "search")
        # keep only images where the whole view lies inside the image (half-diagonal from the edge)
        recs = spherex.filter_records(recs, spec.center, min_edge_margin_deg=spec.fov_deg / 2 * math.sqrt(2))
        return cols, recs

    # -- coverage ----------------------------------------------------------------------------
    def coverage(self, spec: TargetSpec) -> Coverage:
        """The current knowledge about `spec`. Starts a background build the first time (and after errors
        or when the data is older than COVERAGE_TTL_S); callers poll until state == "ready"."""
        with self._lock:
            cov = self._cov.get(spec.key)
            now = time.time()
            if cov is None:
                saved = self._load(spec)  # an earlier visit (or before a restart): show it at once
                if saved is not None:
                    cov = self._cov[spec.key] = saved
            if cov is None or (cov.state == "error" and now - cov.updated > ERROR_RETRY_S):
                cov = self._cov[spec.key] = Coverage(spec)
                threading.Thread(target=self._build, args=(cov, None), daemon=True, name=f"cov-{spec.key}").start()
            elif cov.state == "ready" and not cov.refreshing and now >= cov.next_refresh:
                cov.refreshing = True  # look for new data in the background, keep serving what we have
                threading.Thread(target=self._build, args=(Coverage(spec), cov), daemon=True, name=f"cov-{spec.key}").start()
            return cov

    def _build(self, cov: Coverage, replaces: Coverage | None) -> None:
        def progress(done: int, total: int) -> None:
            cov.located, cov.total, cov.updated = done, total, time.time()

        try:
            cov.state = "searching"
            cov.collections, recs = self._search(cov.spec)
            cov.records = {frame_id(r): r for r in recs}
            self._index_visits(cov, recs)
            cov.total = len(recs)
            cov.state = "locating"
            cov.updated = time.time()
            exps, failed = spherex.locate_on_detector(recs, cov.spec.at, workers=8, on_progress=progress)
            cov.exposures, cov.failed_locate = exps, len(failed)
            cov.state, cov.updated = "ready", time.time()
            cov.data_as_of = cov.updated
            cov.next_refresh = cov.updated + COVERAGE_TTL_S
            self._save(cov)
            if replaces is not None:
                with self._lock:
                    self._cov[cov.spec.key] = cov
            log.info("coverage %s ready: %d images, %d visits", cov.spec.key, len(exps), len(cov.visits))
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
        """Resolve a frame id to its image. Normally known from the coverage; after a restart the
        search is simply run again."""
        obs_id, det = split_frame_id(fid)
        cov = self._cov.get(spec.key)
        if cov and fid in cov.records:
            return cov.records[fid]
        _, recs = self._search(spec)
        for r in recs:
            if frame_id(r) == fid:
                return r
        raise ApiError(404, "unknown_frame", f"no image {fid} covers this position/field of view")

    # -- frame state -------------------------------------------------------------------------
    def frame_state(self, spec: TargetSpec, record: spherex.ImageRecord) -> str:
        """ready | fetching | queued | failed | outside | missing"""
        path = spherex.cutout_path(record, spec.center, spec.cutout_size)
        if path.exists():
            return "ready"
        key = path.name
        with self._lock:
            fut = self._inflight.get(key)
            if fut is not None and not fut.done():
                return "fetching" if fut.running() else "queued"
            fail = self._failures.get(key)
        if fail:
            if fail[1] == "outside":
                return "outside"
            if time.time() - fail[0] < FAIL_COOLDOWN_S:
                return "failed"
        return "missing"

    def ensure_cutout(self, spec: TargetSpec, record: spherex.ImageRecord, priority: int) -> Future | None:
        """Make sure the cutout is (being) fetched. Returns None if already cached, else the pending Future
        (shared by everyone asking for the same cutout)."""
        path = spherex.cutout_path(record, spec.center, spec.cutout_size)
        if path.exists():
            return None
        key = path.name
        with self._lock:
            fut = self._inflight.get(key)
            if fut is not None and not fut.done():
                return fut
            fail = self._failures.get(key)
            if fail and fail[1] == "outside":
                raise ApiError(404, "outside_image", "the requested field is outside this image")
            if fail and time.time() - fail[0] < FAIL_COOLDOWN_S:
                raise ApiError(502, "upstream_error", f"recent download failed, retry later: {fail[2]}")

            def job() -> None:
                with spherex.fetch_cutout_hdul(record, spec.center, spec.cutout_size, self._client):
                    pass

            fut = self._jobs.submit(priority, job)
            self._inflight[key] = fut

            def done(f: Future, key=key) -> None:
                with self._lock:
                    self._inflight.pop(key, None)
                    exc = f.exception()
                    if exc is None:
                        self._failures.pop(key, None)
                    elif isinstance(exc, spherex.OutsideImageError):
                        self._failures[key] = (time.time(), "outside", "outside image")
                    else:
                        self._failures[key] = (time.time(), "error", str(exc)[:200])

            fut.add_done_callback(done)
            return fut

    # -- pixels ------------------------------------------------------------------------------
    def aligned_frame(self, spec: TargetSpec, record: spherex.ImageRecord) -> AlignedFrame:
        """Read the cached cutout and put it on the view's north-up grid (~40 ms). Cutout must be cached."""
        ck = (spec.key, frame_id(record))
        with self._lock:
            hit = self._aligned.get(ck)
            if hit is not None:
                self._aligned.move_to_end(ck)
                return hit
        path = spherex.cutout_path(record, spec.center, spec.cutout_size)
        with fits.open(path) as hdul:
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
            self._aligned[ck] = af
            while len(self._aligned) > MAX_PIXELS_CACHE:
                self._aligned.popitem(last=False)
        return af

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
