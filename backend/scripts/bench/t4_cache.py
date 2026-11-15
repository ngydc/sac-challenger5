"""Test 4: the local side of caching (no IRSA traffic).

A, serving a frame that is already cached: Postgres read -> FITS parse + process -> 2x reproject ->
   PNG (optimize=True as today, vs. False), for 20 stored cutouts. Shows whether local work matters.
B, cache reuse when the view changes. Today a cutout's key is its exact URL (centre + size), so any pan
   or zoom misses the cache and re-downloads every frame. Alternative: store a larger "tile" per image,
   centred on a grid point and sized from a few size classes, and cut every view out of it locally.
   Geometry only: hit or miss for typical view changes, and stored bytes per frame.
C, Postgres storage: does TOAST compress the stored cutouts?
D, calibration maps in memory: 32 MB per (release, detector) as float32. Error if kept as float16 or
   downsampled 4x (so all 6 detectors fit in a few MB and never need reloading).

Run from backend/:  .venv\\Scripts\\python -m scripts.bench.t4_cache
"""
from __future__ import annotations

import io
import json
import math
import time

import httpx
import numpy as np
from astropy.io import fits

from app import db, service, spherex
from scripts.bench import common

SPEC = common.SPEC


# --- A ---------------------------------------------------------------------------------------
def hot_path() -> dict:
    store = db.store
    with store._connection() as conn:  # noqa: SLF001
        keys = [r["cache_key"] for r in conn.execute(
            "SELECT cache_key FROM cutout WHERE status='ready' ORDER BY cache_key LIMIT 20").fetchall()]
    recs = {spherex.cutout_key(spherex.cutout_url(r, SPEC.center, SPEC.cutout_size)): r for r in common.records(400)}
    t = {k: [] for k in ("db_read", "parse_process", "reproject_x2", "png_optimize", "png_plain", "png_optimize_x8", "png_plain_x8")}
    grid, shape = spherex.north_up_wcs(SPEC.center, SPEC.fov_deg, service.PIXEL_SCALE_ARCSEC / 3600)
    n = 0
    for key in keys:
        rec = recs.get(key) or common.records(1)[0]  # any record works for timing (only metadata differs)
        with common.Timer() as a:
            data = store.cutout(key)
        with common.Timer() as b:
            with fits.open(io.BytesIO(data)) as h:
                frame = spherex.process(h, rec, SPEC.center)
        with common.Timer() as c:
            masked = spherex.reproject_frame(frame, grid, shape)
            raw = spherex.reproject_frame(frame, grid, shape, raw=True)
        af = service.AlignedFrame("x", rec, masked.astype(np.float32), raw.astype(np.float32),
                                  np.isnan(masked) & np.isfinite(raw), (0, 0), 1, 1, [], "")
        timings = {}
        for label, opt, scale in (("png_optimize", True, 1), ("png_plain", False, 1),
                                  ("png_optimize_x8", True, 8), ("png_plain_x8", False, 8)):
            t0 = time.perf_counter()
            render(af, opt, scale)
            timings[label] = time.perf_counter() - t0
        t["db_read"].append(a.s); t["parse_process"].append(b.s); t["reproject_x2"].append(c.s)
        for k, v in timings.items():
            t[k].append(v)
        n += 1
    res = {k: common.summary([x * 1000 for x in v]) for k, v in t.items()}
    res["unit"] = "ms"
    res["frames"] = n
    print(json.dumps(res, indent=1))
    return res


def render(af, optimize: bool, scale: int) -> bytes:
    """service.render_png with the PNG `optimize` switch exposed."""
    from PIL import Image

    lo, hi = service.display_range(af, None, None)
    tt = np.clip((np.nan_to_num(af.raw, nan=lo) - lo) / (hi - lo), 0, 1)
    gray = (255 * np.arcsinh(tt / 0.1) / np.arcsinh(1 / 0.1)).astype(np.uint8)
    rgb = np.stack([gray] * 3, axis=-1)[::-1]
    img = Image.fromarray(np.ascontiguousarray(rgb), "RGB")
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=optimize)
    return buf.getvalue()


# --- B ---------------------------------------------------------------------------------------
GRID_DEG = 0.05  # tile centres on a 0.05 deg grid (in the tangent plane of the grid cell)
SIZE_CLASSES = (0.08, 0.15, 0.30)  # fov classes; FOV_MAX = 0.30


def tile_for(ra: float, dec: float, fov: float) -> tuple:
    """(grid ra, grid dec, tile size) holding any view of `fov` centred within half a grid cell."""
    cls = next(c for c in SIZE_CLASSES if fov <= c + 1e-9)
    gdec = round(dec / GRID_DEG) * GRID_DEG
    gra_step = GRID_DEG / max(math.cos(math.radians(gdec)), 1e-3)
    gra = round(ra / gra_step) * gra_step
    size = cls * service.CUTOUT_FACTOR + GRID_DEG * math.sqrt(2)  # covers the worst-case offset from the grid point
    return round(gra, 6), round(gdec, 6), round(size, 4)


def view_reuse() -> dict:
    base = (SPEC.ra, SPEC.dec, SPEC.fov_deg)
    cases = {
        "same view again": base,
        "fov 0.08 -> 0.10": (SPEC.ra, SPEC.dec, 0.10),
        "fov 0.08 -> 0.05": (SPEC.ra, SPEC.dec, 0.05),
        "fov 0.08 -> 0.20": (SPEC.ra, SPEC.dec, 0.20),
        "pan 0.5 arcmin": (SPEC.ra, SPEC.dec + 0.5 / 60, SPEC.fov_deg),
        "pan 2 arcmin": (SPEC.ra + 2 / 60, SPEC.dec, SPEC.fov_deg),
        "coords typed differently (269.4463, 4.7682)": (269.4463, 4.7682, SPEC.fov_deg),
        "Barnard resolved for a different year (moves 10 arcsec/yr)": (SPEC.ra, SPEC.dec + 10.4 / 3600, SPEC.fov_deg),
    }
    cur0 = (round(base[0], 6), round(base[1], 6), round(base[2] * service.CUTOUT_FACTOR, 5))
    tile0 = tile_for(*base)
    rows = {}
    for name, (ra, dec, fov) in cases.items():
        cur = (round(ra, 6), round(dec, 6), round(fov * service.CUTOUT_FACTOR, 5))
        rows[name] = {"today (exact URL)": "hit" if cur == cur0 else "miss",
                      "tile cache": "hit" if tile_for(ra, dec, fov) == tile0 else "miss (new tile)"}
    px = lambda deg: math.ceil(deg * 3600 / service.PIXEL_SCALE_ARCSEC)  # noqa: E731
    sizes = {f"fov <= {c}": {"tile_deg": round(c * service.CUTOUT_FACTOR + GRID_DEG * math.sqrt(2), 3),
                             "tile_px": px(c * service.CUTOUT_FACTOR + GRID_DEG * math.sqrt(2)),
                             "stored_kB (IMAGE+ZODI+FLAGS, 4 B/px)": round(3 * 4 * px(c * service.CUTOUT_FACTOR + GRID_DEG * math.sqrt(2)) ** 2 / 1000)}
             for c in SIZE_CLASSES}
    sizes["today, fov 0.08 (5 HDUs incl. VARIANCE)"] = {"tile_px": px(0.08 * service.CUTOUT_FACTOR), "stored_kB": 118}
    res = {"cases": rows, "storage": sizes, "grid_deg": GRID_DEG}
    print(json.dumps(res, indent=1))
    return res


# --- C ---------------------------------------------------------------------------------------
def toast() -> dict:
    with db.store._connection() as conn:  # noqa: SLF001
        r = conn.execute("""SELECT count(*) n, sum(octet_length(fits)) raw, sum(pg_column_size(fits)) stored
                            FROM cutout WHERE status='ready'""").fetchone()
        data = bytes(conn.execute("SELECT fits FROM cutout WHERE status='ready' LIMIT 1").fetchone()["fits"])
    import zlib

    res = {"cutouts": r["n"], "raw_MB": round(r["raw"] / 1e6, 1), "stored_MB": round(r["stored"] / 1e6, 1),
           "zlib6_ratio_one_cutout": round(len(zlib.compress(data, 6)) / len(data), 3)}
    print(res)
    return res


# --- D ---------------------------------------------------------------------------------------
def calib_compact() -> dict:
    out = {}
    with httpx.Client(timeout=120) as client:
        sm = spherex.SpectralMaps(client, db.store)
        for det in ("D1", "D4", "D6"):
            cw, cb = sm.get("dr1", det)
            ok = np.isfinite(cw)
            f16 = cw.astype(np.float16).astype(np.float32)
            small = cw[::4, ::4]
            up = np.repeat(np.repeat(small, 4, 0), 4, 1)[:cw.shape[0], :cw.shape[1]]
            both = ok & np.isfinite(up)
            out[det] = {"float16_max_err_um": float(np.nanmax(np.abs(f16 - cw)[ok])),
                        "down4_nearest_max_err_um": float(np.nanmax(np.abs(up - cw)[both])),
                        "down4_p99_err_um": float(np.nanpercentile(np.abs(up - cw)[both], 99)),
                        "median_bandwidth_um": float(np.nanmedian(cb)),
                        "MB float32 / float16 / down4": (round(cw.nbytes * 2 / 1e6, 1), round(cw.nbytes / 1e6, 1),
                                                         round(small.nbytes * 2 / 1e6, 2))}
    print(json.dumps(out, indent=1))
    return out


def main() -> None:
    res = {}
    for name, fn in (("hot_path", hot_path), ("view_reuse", view_reuse), ("toast", toast), ("calibration_compact", calib_compact)):
        print(f"\n== {name}")
        res[name] = fn()
    common.save("t4_cache", res)


if __name__ == "__main__":
    main()
