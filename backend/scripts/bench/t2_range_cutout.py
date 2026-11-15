"""Test 2: cutouts built from HTTP range requests (app/cutout.py, a prototype of it when measured) instead of
IRSA's cutout service.

Part A, correctness: for 2 images, compare our cutout with IRSA's cutout of the same image, centre and
size: header keywords, IMAGE/ZODI/FLAGS pixels, wavelength at the target, and the final north-up frame
the app shows (spherex.process + reproject, the same code path as service.aligned_frame).
Part B, speed: 9 other images, from the S3 copy (1 and 8 workers) and from IRSA's file server with
range requests (3 workers, the app's IRSA limit), with request counts, bytes and 503s.

Run from backend/:  .venv\\Scripts\\python -m scripts.bench.t2_range_cutout
"""
from __future__ import annotations

import io
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from app import spherex
from app.service import PIXEL_SCALE_ARCSEC
from scripts.bench import common
from app.cutout import Stats, range_cutout

SPEC = common.SPEC


def aligned(data: bytes, rec) -> tuple[np.ndarray, float]:
    with fits.open(io.BytesIO(data)) as h:
        frame = spherex.process(h, rec, SPEC.center)
    grid, shape = spherex.north_up_wcs(SPEC.center, SPEC.fov_deg, PIXEL_SCALE_ARCSEC / 3600)
    return spherex.reproject_frame(frame, grid, shape, raw=True), frame.wavelength_um


def correctness(client: httpx.Client) -> list[dict]:
    out = []
    for rec in common.records(2, offset=3):
        irsa = spherex.download_irsa_cutout(rec, SPEC.center, SPEC.cutout_size, client)
        st = Stats()
        mine = range_cutout(rec.access_url, SPEC.center, SPEC.cutout_size, client, stats=st)
        a, b = fits.open(io.BytesIO(irsa)), fits.open(io.BytesIO(mine))
        # where IRSA's box starts relative to ours (both headers are shifted copies of the same CRPIX1)
        dx = round(b["IMAGE"].header["CRPIX1"] - a["IMAGE"].header["CRPIX1"])
        dy = round(b["IMAGE"].header["CRPIX2"] - a["IMAGE"].header["CRPIX2"])
        res = {"frame": f"{rec.obs_id}-{rec.detector}", "irsa_shape": a["IMAGE"].data.shape,
               "our_shape": b["IMAGE"].data.shape, "box_offset_px (irsa - ours)": (dx, dy)}
        for ext in ("IMAGE", "ZODI", "FLAGS", "VARIANCE"):
            A, B = a[ext].data, b[ext].data
            # overlap: pixel (i, j) of IRSA's cutout is pixel (i + dy, j + dx) of ours
            ys, xs = slice(max(0, -dy), min(A.shape[0], B.shape[0] - dy)), slice(max(0, -dx), min(A.shape[1], B.shape[1] - dx))
            Ao = A[ys, xs]
            Bo = B[ys.start + dy:ys.stop + dy, xs.start + dx:xs.stop + dx]
            same = np.array_equal(Ao, Bo, equal_nan=True) if ext != "FLAGS" else np.array_equal(Ao, Bo)
            res[f"{ext}_identical_on_overlap"] = bool(same)
            res[f"{ext}_overlap_px"] = int(Ao.size)
        # headers: every key IRSA has in IMAGE must match ours, CRPIX after the box offset
        bad = []
        for ext in ("IMAGE", "FLAGS", "VARIANCE", "ZODI"):
            ha, hb = a[ext].header, b[ext].header
            for k in ha:
                if k in ("NAXIS1", "NAXIS2", "CHECKSUM", "DATASUM", "") or k.startswith(("XTENSION", "PCOUNT", "GCOUNT", "COMMENT", "HISTORY")):
                    continue
                if k not in hb:
                    bad.append(f"{ext}:{k} missing")
                    continue
                va, vb = ha[k], hb[k]
                if k.startswith("CRPIX1"):
                    vb = vb - dx
                elif k.startswith("CRPIX2"):
                    vb = vb - dy
                if isinstance(va, float) or isinstance(vb, float):
                    if not np.isclose(float(va), float(vb)):
                        bad.append(f"{ext}:{k} {va} vs {vb}")
                elif str(va) != str(vb):
                    bad.append(f"{ext}:{k} {va!r} vs {vb!r}")
        res["header_mismatches"] = bad[:10]
        res["n_header_mismatches"] = len(bad)
        # what the user sees
        fa, wa = aligned(irsa, rec)
        fb, wb = aligned(mine, rec)
        both = np.isfinite(fa) & np.isfinite(fb)
        res["wavelength_um irsa / ours"] = (round(wa, 6), round(wb, 6))
        res["aligned_frame_max_abs_diff_MJy_sr"] = float(np.nanmax(np.abs(fa - fb)[both])) if both.any() else None
        res["aligned_frame_rel_rms"] = float(np.sqrt(np.mean((fa - fb)[both] ** 2)) / np.std(fa[both]))
        res["aligned_frame_nan_px irsa / ours"] = (int((~np.isfinite(fa)).sum()), int((~np.isfinite(fb)).sum()))
        res["bytes irsa (PSF dropped) / ours"] = (len(irsa), len(mine))
        out.append(res)
        print(res)
    return out


def multirange(client: httpx.Client) -> dict:
    """Part M: IRSA only, read just the needed columns (multipart/byteranges). Checked against the
    whole-row version on one image, then timed on 18 new images."""
    every = common.records(400)  # all images in time order; the other tests use the first ~120
    rec = every[199]
    whole = range_cutout(rec.access_url, SPEC.center, SPEC.cutout_size, client)
    cols = range_cutout(rec.access_url, SPEC.center, SPEC.cutout_size, client, multirange=True)
    a, b = fits.open(io.BytesIO(whole)), fits.open(io.BytesIO(cols))
    same = all(np.array_equal(a[e].data, b[e].data, equal_nan=e != "FLAGS") for e in ("IMAGE", "ZODI", "FLAGS", "VARIANCE"))
    print("multi-range cutout identical to whole-row cutout:", same)
    recs = every[200:218]
    items = [(r.access_url, r) for r in recs]
    runs = [timed_run("IRSA multi-range, 3 workers", items[0:9], 3, client, multirange=True),
            timed_run("IRSA multi-range, 8 workers", items[9:18], 8, client, multirange=True)]
    return {"identical_to_whole_rows": same, "runs": runs}


def timed_run(label: str, urls_recs, workers: int, client: httpx.Client, multirange: bool = False) -> dict:
    stats: list[Stats] = []
    times: list[float] = []
    errors: list[str] = []

    def one(item):
        url, rec = item
        st = Stats()
        t = time.perf_counter()
        try:
            range_cutout(url, SPEC.center, SPEC.cutout_size, client, stats=st, multirange=multirange)
        except Exception as err:  # noqa: BLE001
            errors.append(f"{type(err).__name__}: {err}"[:200])
            return
        times.append(time.perf_counter() - t)
        stats.append(st)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, urls_recs))
    wall = time.perf_counter() - t0
    res = {"label": label, "workers": workers, "n": len(urls_recs), "wall_s": round(wall, 2),
           "per_cutout_s": common.summary(times), "meta_s": common.summary([s.t_meta for s in stats]),
           "data_s": common.summary([s.t_data for s in stats]),
           "requests_per_cutout": common.summary([s.requests for s in stats]),
           "kB_per_cutout": common.summary([s.bytes / 1000 for s in stats]),
           "n503": sum(s.n503 for s in stats), "errors": errors,
           "throughput_cutouts_per_min": round(60 * len(times) / wall, 1)}
    print(f"{label:38s} wall {wall:6.1f}s  per cutout median {res['per_cutout_s'].get('median')}s  "
          f"{res['requests_per_cutout'].get('median')} req  {res['kB_per_cutout'].get('median')} kB  503s={res['n503']}  errors={len(errors)}")
    return res


def speed(client: httpx.Client) -> list[dict]:
    recs = common.records(36, offset=1)
    s3 = [(common.s3_url(r), r) for r in recs]
    irsa = [(r.access_url, r) for r in recs]
    return [
        timed_run("S3 range, 1 worker", s3[0:9], 1, client),
        timed_run("S3 range, 8 workers", s3[9:18], 8, client),
        timed_run("S3 range, 8 workers, same imgs (warm)", s3[9:18], 8, client),
        timed_run("IRSA file range, 3 workers", irsa[18:27], 3, client),
        timed_run("IRSA file range, 8 workers", irsa[27:36], 8, client),
    ]


def main() -> None:
    import json
    import sys

    parts = sys.argv[1] if len(sys.argv) > 1 else "ABM"
    path = common.OUT / "t2_range_cutout.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    res["view"] = {"ra": SPEC.ra, "dec": SPEC.dec, "fov": SPEC.fov_deg, "cutout_size_deg": SPEC.cutout_size}
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    with httpx.Client(timeout=120, follow_redirects=True, limits=limits) as client:
        if "A" in parts:
            print("== A: correctness vs IRSA cutouts")
            res["correctness"] = correctness(client)
        if "B" in parts:
            print("\n== B: speed (9 images per run, disjoint samples)")
            res["speed"] = speed(client)
        if "M" in parts:
            print("\n== M: IRSA multi-range (only the needed columns)")
            res["multirange"] = multirange(client)
    common.save("t2_range_cutout", res)


if __name__ == "__main__":
    main()
