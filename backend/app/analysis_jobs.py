"""Deep analysis (epoch maps) as a job of the backend: where its inputs come from, where its results go, and
how many run at once. The computation itself is app/analysis.py; the HTTP API is app/analysis_api.py.

Inputs come from the same places the viewer uses (app/service.py), so nothing is searched or downloaded twice:
- the images: the position's coverage (SIA2 search, stored in Postgres, refreshed hourly);
- the cutouts: the Postgres cutout store, fetched through the shared download queue at the lowest priority
  (a frame a user is waiting for, and the viewer's prefetch, go first); the cache key is the same, so a
  cutout fetched by either feature serves both;
- the Spectral Channels calibration file: the shared calibration store (spherex.load_calibration).

Results are derived, large and only read here, so they stay files (git-ignored), one folder per position and
field of view:

    <SPHEREX_CACHE_DIR>/analysis/<tier>/ra<deg>_dec<deg>_fov<deg>/
        latest.json                          which products folder to serve, and whether it is complete
        .used                                touched on every read (the temp tier expires by last use)
        reproj/<reproj key>/<frame>.npz      one exposure on the common grid (image, variance, channel per pixel)
        products/<params key>/<images key>/  meta.json, channels_<det>.npz, bundle_<id>.npz, the PNGs (diff_<id>_s<k>.png = step k), spectrum/

<tier> is "examples" for the five challenge test targets (kept) and "temp" for every other position (removed
after TEMP_TTL_HOURS without use, least recently used first above TEMP_MAX_MB). <params key> changes when the
computation changes, <images key> when the coverage finds new images: a recomputation writes a new folder and
latest.json switches to it only when it is complete, so the previous result stays visible meanwhile.

At most MAX_JOBS analyses run at once; the others wait ("queued"). State lives in memory: after a restart a
position is either complete on disk ("ready") or not started ("idle"); restarting it reuses everything stored.
"""
from __future__ import annotations

import functools
import hashlib
import io
import json
import logging
import os
import shutil
import threading
import time
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.time import Time

from . import analysis, presets, resolver, spherex
from .core import PIXEL_SCALE_ARCSEC, VISIT_GAP_DAYS, ApiError, TargetSpec, frame_id, iso
from .service import PRIORITY_ANALYSIS
from .service import service as _service

log = logging.getLogger("spherex.analysis")

CACHE_ROOT = Path(os.environ.get("SPHEREX_CACHE_DIR", Path(__file__).resolve().parents[1] / "cache")) / "analysis"
TEMP_TTL_HOURS = float(os.environ.get("SPHEREX_TEMP_CACHE_TTL_HOURS", "72"))
TEMP_MAX_MB = float(os.environ.get("SPHEREX_TEMP_CACHE_MAX_MB", "2000"))
MAX_JOBS = int(os.environ.get("SPHEREX_ANALYSIS_JOBS", "2"))  # analyses computed at the same time
PROCESS_THREADS = 4  # per job: cutouts reprojected in parallel while the downloads continue
COVERAGE_WAIT_S = 600.0  # give up if the position's coverage is not ready after this long
DOWNLOAD_WAIT_S = 900.0  # give up on one cutout after this long (the queue may be busy with users)
ERROR_RETRY_S = 30.0  # a failed analysis is started again by a request only after this long
WARM_RETRIES, WARM_RETRY_S = 6, 300.0  # start-up precompute: try a failed test target again this often, this far apart
EXAMPLE_MATCH_DEG = 1e-4  # a position this close to a test target's position counts as that example


# --- small helpers --------------------------------------------------------------------------
def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(json.dumps(data, indent=1, allow_nan=False, default=_json_default), encoding="utf-8")
    _replace(tmp, path)


def _replace(src: Path, dst: Path) -> None:
    """os.replace, retried briefly: on Windows it fails while another thread has `dst` open for reading."""
    for attempt in range(50):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.02)


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(type(o))


def _read_json(path: Path):
    for attempt in range(50):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        except PermissionError:  # Windows: the file is being replaced at this moment (see _replace)
            if attempt == 49:
                raise
            time.sleep(0.02)


def _save_npz(path: Path, **arrays) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + f".part{os.getpid()}-{threading.get_ident()}.npz")
    np.savez_compressed(tmp, **arrays)
    _replace(tmp, path)


def preset_specs() -> list[TargetSpec]:
    """The five challenge test targets, exactly as the frontend asks for them: the position GET /api/resolve
    returns (moved to the current year), its field of view and its proper motion."""
    out = []
    for p in presets.PRESETS:
        r = resolver.resolve(p.name)  # a preset: answered locally, no network
        out.append(TargetSpec.build(str(r.ra), str(r.dec), r.fov, r.pmra, r.pmdec, r.pm_epoch))
    return out


@functools.lru_cache(maxsize=1)
def _preset_positions() -> tuple[tuple[float, float], ...]:
    return tuple((s.ra, s.dec) for s in preset_specs())


def is_example(spec: TargetSpec) -> bool:
    """True for the five challenge test targets (their results are kept for good)."""
    return any(abs(dec - spec.dec) < EXAMPLE_MATCH_DEG and
               abs((ra - spec.ra + 180) % 360 - 180) * np.cos(np.radians(spec.dec)) < EXAMPLE_MATCH_DEG
               for ra, dec in _preset_positions())


def images_key(records: list[spherex.ImageRecord]) -> str:
    """Identifies the set of images a result was computed from (new weekly data -> new key)."""
    return hashlib.sha1(",".join(sorted(frame_id(r) for r in records)).encode()).hexdigest()[:10]


# --- in-memory state of a running analysis ----------------------------------------------------
@dataclass
class Job:
    spec: TargetSpec
    state: str = "queued"  # queued | running | error
    stage: str = "waiting for a free slot"
    done: int = 0
    total: int = 0
    bundles_ready: list[str] = field(default_factory=list)
    message: str | None = None
    updated: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def step(self) -> None:
        with self.lock:
            self.done += 1
            self.updated = time.time()


class AnalysisService:
    def __init__(self, svc, root: Path | None = None, max_jobs: int = MAX_JOBS):
        self.svc = svc  # app/service.py's Service: coverage, cutout store, download queue, HTTP client
        self.root = root or CACHE_ROOT
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}  # target folder name -> job (queued, running, or failed)
        self._pool = ThreadPoolExecutor(max_jobs, thread_name_prefix="analysis")

    # -- where things are ----------------------------------------------------------------------
    def target_dir(self, spec: TargetSpec) -> Path:
        tier = "examples" if is_example(spec) else "temp"
        return self.root / tier / f"ra{spec.ra:.6f}_dec{spec.dec:+.6f}_fov{spec.fov_deg:.5f}"

    def _reproj_dir(self, spec: TargetSpec) -> Path:
        return self.target_dir(spec) / "reproj" / analysis.params_key(analysis.reproj_params())

    def latest(self, spec: TargetSpec) -> tuple[Path | None, dict | None]:
        """The products folder to serve and its metadata (complete, or partial while a first run is going on);
        (None, None) if there is nothing, or only results of an older computation."""
        pointer = _read_json(self.target_dir(spec) / "latest.json")
        if not pointer:
            return None, None
        d = self.target_dir(spec) / "products" / pointer["dir"]
        meta = _read_json(d / "meta.json")
        if not meta or meta.get("pipeline_version") != analysis.PIPELINE_VERSION:
            return None, None
        return d, meta

    # -- reading (no IRSA) -----------------------------------------------------------------------
    def status(self, spec: TargetSpec, start: bool = False) -> dict:
        """State, progress and the result's metadata. With `start`, an analysis that is missing (or failed more
        than ERROR_RETRY_S ago, or computed from fewer images than the coverage now has) is started."""
        tdir = self.target_dir(spec)
        if tdir.exists():
            (tdir / ".used").touch()
        _, meta = self.latest(spec)
        complete = bool(meta and meta.get("complete"))
        with self._lock:
            job = self._jobs.get(tdir.name)
            if start:
                if job is None or (job.state == "error" and time.time() - job.updated > ERROR_RETRY_S):
                    if not complete or self._outdated(spec, meta):
                        job = self._start(spec)
        busy = job is not None and job.state in ("queued", "running")
        if complete:
            state = "ready"  # also while it is recomputed with new images (refreshing): the old result is served
        elif busy:
            state = job.state
        elif job is not None and job.state == "error":
            state = "error"
        else:
            state = "idle"
        progress = None
        if busy:
            progress = {"stage": job.stage, "done": job.done, "total": job.total, "bundles_ready": list(job.bundles_ready)}
        return {"state": state, "refreshing": complete and busy,
                "message": job.message if job is not None and job.state == "error" else None, "progress": progress,
                "kept": is_example(spec), "temp_ttl_hours": TEMP_TTL_HOURS,
                "result": meta if (complete or state in ("queued", "running")) else None}

    def _outdated(self, spec: TargetSpec, meta: dict | None) -> bool:
        """A complete result computed from another set of images than the coverage has now (new weekly data)."""
        if not meta:
            return False
        cov = self.svc.coverage(spec, all_images=True)
        return cov.state == "ready" and bool(cov.records) and images_key(list(cov.records.values())) != meta.get("images_key")

    def bundle(self, spec: TargetSpec, bundle_id: str) -> dict:
        _, meta = self.latest(spec)
        if not meta:
            raise ApiError(409, "not_ready", "nothing is computed for this position yet: GET /api/analysis starts it")
        for b in meta["bundles"]:
            if b["id"] == bundle_id:
                return b
        ready = [b["id"] for b in meta["bundles"]]
        raise ApiError(404, "unknown_bundle", f"bundle '{bundle_id}' is not available (yet); available: {ready}")

    def picture(self, spec: TargetSpec, name: str) -> Path:
        d, _ = self.latest(spec)
        path = d / name if d else None
        if path is None or not path.exists():
            raise ApiError(404, "no_data", "this picture does not exist for this position and bundle")
        return path

    def spectrum(self, spec: TargetSpec, x: int, y: int) -> dict:
        """Per channel and epoch: the averaged value of one pixel. x from the left (east), y from the BOTTOM
        (south), as everywhere else in the API (row 0 of the grid is the south edge)."""
        d, meta = self.latest(spec)
        if not meta:
            raise ApiError(409, "not_ready", "nothing is computed for this position yet: GET /api/analysis starts it")
        W, H = meta["grid"]["width"], meta["grid"]["height"]
        if not (0 <= x < W and 0 <= y < H):
            raise ApiError(400, "bad_pixel", f"x must be 0..{W - 1} and y 0..{H - 1}")
        stored = d / "spectrum" / f"x{x}_y{y}.json"  # computed once per complete result, then only read
        if meta.get("complete"):
            hit = _read_json(stored)
            if hit is not None:
                return hit
        table = {(c["detector"], c["channel"]): c for c in meta.get("channel_table", [])}
        out, unit = [], None
        for b in meta["bundles"]:
            path = d / f"channels_{b['id']}.npz"
            if b["kind"] != "detector" or not path.exists():
                continue
            unit = unit or (b.get("stretch") or {}).get("unit")
            with np.load(path) as z:
                I, V, N = z["image"][:, :, y, x], z["variance"][:, :, y, x], z["n"][:, :, y, x]
            for c in range(I.shape[1]):
                ci = table.get((b["id"], c + 1), {})
                out.append({"detector": b["id"], "channel": c + 1, "wavelength_um": ci.get("wavelength_um"),
                            "wl_min_um": ci.get("wl_min_um"), "wl_max_um": ci.get("wl_max_um"),
                            "epochs": [{"epoch": e, "value": analysis._num(I[e, c]),
                                        "sigma": analysis._num(np.sqrt(V[e, c])) if np.isfinite(V[e, c]) else None,
                                        "n": int(N[e, c])} for e in range(I.shape[0])]})
        result = {"x": x, "y": y, "unit": unit,
                  "value_definition": "IMAGE - ZODI, minus each exposure's sky level (median over the darkest pixels of the field)",
                  "epochs": [{"index": e["index"], "time": e["time"], "start": e["start"], "end": e["end"]} for e in meta["epochs"]],
                  "channels": out}
        if meta.get("complete"):
            _write_json(stored, result)
        return result

    # -- running ---------------------------------------------------------------------------------
    def _start(self, spec: TargetSpec) -> Job:
        """Queue an analysis (caller holds self._lock)."""
        job = Job(spec)
        self._jobs[self.target_dir(spec).name] = job
        self._pool.submit(self._run_job, job)
        return job

    def _run_job(self, job: Job) -> None:
        job.state, job.stage, job.updated = "running", "looking up the images", time.time()
        try:
            self.run(job)
            with self._lock:
                self._jobs.pop(self.target_dir(job.spec).name, None)  # done: from now on read from disk
        except Exception as err:  # noqa: BLE001
            log.exception("analysis of %s failed", job.spec.key)
            job.state, job.message, job.updated = "error", getattr(err, "message", str(err))[:300], time.time()

    def _coverage(self, job: Job):
        t0 = time.time()
        while True:
            cov = self.svc.coverage(job.spec, all_images=True)
            if cov.state == "ready":
                return cov
            if cov.state == "error":
                raise ApiError(502, "irsa_unavailable", cov.message or "the image search failed")
            if time.time() - t0 > COVERAGE_WAIT_S:
                raise ApiError(504, "timeout", "the image search did not finish in time")
            job.stage = f"looking up the images ({cov.located}/{cov.total})" if cov.total else "looking up the images"
            time.sleep(0.5)

    def run(self, job: Job) -> dict:
        """The whole analysis of one position. Blocking; downloads go through the shared queue."""
        spec = job.spec
        self.cleanup_temp()
        cov = self._coverage(job)
        records = sorted(cov.records.values(), key=lambda r: r.t_mid_mjd)
        if not records:
            raise ApiError(404, "no_images", "SPHEREx has no images of this position yet")
        tdir = self.target_dir(spec)
        ikey = images_key(records)
        pkey = analysis.params_key(analysis.epochmap_params())
        out = tdir / "products" / pkey / ikey
        _write_json(out / "params.json", analysis.epochmap_params())
        _, previous = self.latest(spec)
        first_run = not (previous and previous.get("complete"))

        seasons = spherex.group_seasons(records, VISIT_GAP_DAYS)
        epoch_of = {frame_id(r): e for e, s in enumerate(seasons) for r in s}
        epochs = analysis.epochs_of(seasons)
        grid, shape = spherex.north_up_wcs(spec.center, spec.fov_deg, PIXEL_SCALE_ARCSEC / 3600)
        meta = {
            "pipeline_version": analysis.PIPELINE_VERSION, "complete": False, "images_key": ikey,
            "target": {"ra": spec.ra, "dec": spec.dec, "fov": spec.fov_deg},
            "grid": {"width": shape[1], "height": shape[0], "pixel_scale_arcsec": PIXEL_SCALE_ARCSEC,
                     "orientation": "north up, east left; pixel row 0 is the south edge"},
            "collections": cov.collections, "searched_at": _iso_unix(cov.data_as_of),
            "n_images": len(records), "epoch_gap_days": VISIT_GAP_DAYS, "epochs": epochs,
            "bad_flags": list(analysis.BAD_FLAG_NAMES), "bundles": [], "failed": [], "failed_retryable": 0,
        }

        job.stage, job.total = "loading the spectral channel definition", len(records)
        channels = {}
        for rel in sorted({spherex.release_of(r) for r in records}):
            keys = spherex.calibration_keys(self.svc.http, rel, "spectral_channels")
            if not keys:
                raise FileNotFoundError(f"no spectral channels file for release {rel}")
            channels[rel] = {**spherex.load_calibration(self.svc.http, self.svc.db, keys[-1], "spectral_channels",
                                                         analysis.parse_channels), "file": keys[-1]}
        nchans = {c["nchan"] for c in channels.values()}
        if len(nchans) > 1:
            raise RuntimeError(f"releases disagree on the number of channels: {nchans}")
        nchan = nchans.pop()
        rows = next(iter(channels.values()))["rows"]
        meta["channel_files"] = sorted({c["file"] for c in channels.values()})
        dets = sorted({r.detector for r in records})
        meta["channel_table"] = [c for det in dets for c in analysis.channel_table(rows, det, nchan)]

        # queue every download now (detector after detector), then work through them as they arrive
        rdir = self._reproj_dir(spec)
        pending: dict[str, Future | None] = {}
        failed_early: dict[str, tuple[str, bool]] = {}
        for det in dets:
            for r in (r for r in records if r.detector == det):
                fid = frame_id(r)
                if (rdir / f"{fid}.npz").exists():
                    continue
                try:
                    pending[fid] = self.svc.ensure_cutout(spec, r, PRIORITY_ANALYSIS)
                except ApiError as err:  # outside the image, or a download that failed seconds ago
                    failed_early[fid] = (err.code, err.code != "outside_image")

        cubes, all_exposures = {}, []
        with ThreadPoolExecutor(PROCESS_THREADS, thread_name_prefix="analysis-reproj") as ex:
            for det in dets:
                job.stage = f"{det}: downloading and aligning"
                recs = [r for r in records if r.detector == det]
                results = list(ex.map(lambda r: self._exposure(job, r, pending, failed_early, rdir,
                                                               channels[spherex.release_of(r)]["map"]), recs))
                exposures = []
                for r, res in zip(recs, results):
                    if "failed" in res:
                        meta["failed"].append({"frame_id": res["frame_id"], "reason": res["failed"]})
                        meta["failed_retryable"] += 1 if res.get("retry") else 0
                    else:
                        exposures.append({**res, "epoch": epoch_of[frame_id(r)]})
                job.stage = f"{det}: averaging"
                I, V, N, sky, rejected, exposures, dropped = analysis.average_detector(
                    exposures, functools.partial(_load_reproj, rdir), len(seasons), nchan, shape)
                meta["failed"] += dropped
                _save_npz(out / f"channels_{det}.npz", image=I, variance=V, n=N, sky=sky)
                cubes[det] = (I, V, N)
                all_exposures += exposures
                self._store_bundle(out, meta, det, "detector", I, V, N, analysis.channel_table(rows, det, nchan),
                                   epochs, exposures, {"outliers_rejected": rejected})
                job.bundles_ready = [b["id"] for b in meta["bundles"]]
                if first_run:  # nothing complete to show yet: show what is ready
                    _write_json(tdir / "latest.json", {"dir": f"{pkey}/{ikey}", "complete": False})

        if cubes:
            job.stage = "all detectors: averaging"
            all_info = [c for k in dets for c in analysis.channel_table(rows, k, nchan)]
            I_all, V_all, N_all = (np.concatenate([cubes[k][i] for k in dets], axis=1) for i in range(3))
            self._store_bundle(out, meta, "all", "all", I_all, V_all, N_all, all_info, epochs, all_exposures)
            job.stage = "all detectors: colour pictures"
            cmeta, _, pngs = analysis.colour_composite(I_all, V_all, N_all, all_info, epochs)
            for ce in cmeta["epochs"]:  # predicted target position at the epoch's median time, as the viewer's X-Target-X/Y
                if ce.get("time"):
                    tx, ty = grid.world_to_pixel(spec.at(Time(ce["time"]).mjd))
                    ce["target_xy"] = [analysis._num(tx, 2), analysis._num(ty, 2)]
            for name, data in pngs.items():
                (out / name).write_bytes(data)
            meta["colour"] = cmeta
            _write_json(out / "meta.json", meta)
            del I_all, V_all, N_all
        meta["complete"] = True
        meta["computed_at"] = _iso_unix(time.time())
        _write_json(out / "meta.json", meta)
        _write_json(tdir / "latest.json", {"dir": f"{pkey}/{ikey}", "complete": True})
        for old in (tdir / "products").glob("*/*"):  # earlier results of this position
            if old.is_dir() and old != out:
                shutil.rmtree(old, ignore_errors=True)
        log.info("analysis of %s done: %d images, %d failed", spec.key, len(records), len(meta["failed"]))
        return meta

    def _exposure(self, job: Job, rec: spherex.ImageRecord, pending: dict, failed_early: dict, rdir: Path,
                  channel_map: np.ndarray) -> dict:
        """One cutout: the cached reprojection, or wait for the download and reproject it. Returns the
        exposure's metadata, or {"failed": reason, "frame_id", "retry"}."""
        fid = frame_id(rec)
        try:
            out = rdir / f"{fid}.npz"
            if out.exists():
                with np.load(out) as z:
                    return json.loads(str(z["meta"]))
            if fid in failed_early:
                reason, retry = failed_early[fid]
                return {"failed": reason, "frame_id": fid, "retry": retry}
            for attempt in range(2):
                fut = pending.get(fid) if attempt == 0 else self.svc.ensure_cutout(job.spec, rec, PRIORITY_ANALYSIS)
                try:
                    if fut is not None:
                        fut.result(timeout=DOWNLOAD_WAIT_S)
                    break
                except CancelledError:  # cancelled as somebody's stale prefetch before we joined: ask again
                    continue
            data = self.svc.cutout_data(job.spec, rec)
            if data is None:
                return {"failed": "download: not stored", "frame_id": fid, "retry": True}
            with fits.open(io.BytesIO(data)) as hdul:
                if "VARIANCE" not in hdul:
                    return {"failed": "stored cutout has no VARIANCE extension", "frame_id": fid, "retry": False}
                res = analysis.reproject_cutout(hdul, rec, job.spec, channel_map)
            _save_npz(out, img=res["img"], var=res["var"], chan=res["chan"], meta=json.dumps(res["meta"]))
            return res["meta"]
        except spherex.OutsideImageError:
            return {"failed": "outside", "frame_id": fid}
        except ApiError as err:
            return {"failed": err.code, "frame_id": fid, "retry": err.code != "outside_image"}
        except Exception as err:  # noqa: BLE001 - one bad cutout must not stop the analysis
            log.exception("processing %s failed", fid)
            return {"failed": f"processing: {str(err)[:150]}", "frame_id": fid, "retry": True}
        finally:
            job.step()

    def _store_bundle(self, out: Path, meta: dict, bundle_id: str, kind: str, I, V, N, chan_info, epochs, exposures,
                      extra: dict | None = None) -> None:
        bmeta, arrays, pngs = analysis.make_bundle(bundle_id, kind, I, V, N, chan_info, epochs, exposures)
        bmeta.update(extra or {})
        for name, data in pngs.items():
            (out / name).write_bytes(data)
        keep = {k: v for k, v in arrays.items() if not k.startswith(analysis.STEP_ARRAY_PREFIX)}  # only the PNGs are served
        if keep:
            _save_npz(out / f"bundle_{bundle_id}.npz", **keep)
        meta["bundles"] = [b for b in meta["bundles"] if b["id"] != bundle_id] + [bmeta]
        _write_json(out / "meta.json", meta)

    # -- housekeeping ----------------------------------------------------------------------------
    def cleanup_temp(self) -> list[str]:
        """Remove positions of the temp tier unused for TEMP_TTL_HOURS, then the least recently used ones until
        the tier fits TEMP_MAX_MB. Never touches the examples tier or a position being computed."""
        root = self.root / "temp"
        if not root.is_dir():
            return []
        with self._lock:
            busy = {name for name, j in self._jobs.items() if j.state in ("queued", "running")}
        entries = []
        for d in root.iterdir():
            if not d.is_dir() or d.name in busy:
                continue
            used = max((p.stat().st_mtime for p in (d / ".used", d / "latest.json") if p.exists()), default=d.stat().st_mtime)
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            entries.append((used, size, d))
        removed, total = [], sum(e[1] for e in entries)
        for used, size, d in sorted(entries, key=lambda e: e[0]):  # least recently used first
            if time.time() - used > TEMP_TTL_HOURS * 3600 or total > TEMP_MAX_MB * 1e6:
                shutil.rmtree(d, ignore_errors=True)
                total -= size
                removed.append(d.name)
        if removed:
            log.info("analysis temp cache: removed %s", removed)
        return removed

    def warm(self, specs: list[TargetSpec] | None = None, retries: int = 0, retry_s: float = WARM_RETRY_S) -> None:
        """Start the analysis of the test targets (or `specs`) unless it is complete and current. Their coverage
        is looked up on the way, and the viewer's prefetch fills the shared cutout store for their default view.
        With `retries`, waits until they are done and starts the failed ones again (IRSA is down now and then),
        up to `retries` times, `retry_s` apart."""
        todo = list(specs) if specs is not None else preset_specs()
        for attempt in range(retries + 1):
            for spec in todo:
                try:
                    self.status(spec, start=True)
                except Exception:  # noqa: BLE001 - e.g. database down: try the next one
                    log.exception("could not start the analysis of %s", spec.key)
            if attempt == retries:
                return
            while any(self.status(s)["state"] in ("queued", "running") for s in todo):
                time.sleep(5)
            todo = [s for s in todo if self.status(s)["state"] != "ready"]
            if not todo:
                return
            log.warning("precompute: %d target(s) not ready, trying again in %.0f s", len(todo), retry_s)
            time.sleep(retry_s)


def _load_reproj(rdir: Path, fid: str):
    with np.load(rdir / f"{fid}.npz") as z:
        return z["img"].astype(np.float64), z["var"].astype(np.float64), z["chan"]


def _iso_unix(t: float) -> str | None:
    """Unix time as UTC ISO text (MJD 40587 is 1970-01-01)."""
    return iso(t / 86400 + 40587) if t else None


jobs = AnalysisService(_service)
