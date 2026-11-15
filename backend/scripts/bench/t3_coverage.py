"""Test 3: the coverage lookup (first visit of a target: 50-125 s today, docs/API.md).

Today: list collections -> SIA2 search, one collection after the other -> read each image's IMAGE header
from IRSA with range requests (8 workers) -> look the target pixel up in the CWAVE map (Spectral WCS
calibration file, loaded from Postgres, 12 files of 32 MB).

A, collection list and SIA2: one search per collection, one after the other vs. all at once.
   Also records what SIA2's `cloud_access` column looks like (is the S3 key = on-premises path?).
B, header reads: 40 images from IRSA (8 workers, today) vs. the S3 copy (8 and 32 workers).
C, no header reads at all (offline, no network): predict the target pixel from the image footprint
   polygon SIA2 already returns (`s_region`, 4 corners), compare with the header-WCS pixel the app
   stored for all images of both cached targets, and convert the pixel error into a wavelength error
   with the CWAVE map.
D, calibration maps: time to list S3, read a 32 MB file from Postgres and parse it.

Run from backend/:  .venv\\Scripts\\python -m scripts.bench.t3_coverage
"""
from __future__ import annotations

import dataclasses
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
from astropy.io import fits

from app import db, spherex
from scripts.bench import common

SPEC = common.SPEC


# --- A ---------------------------------------------------------------------------------------
def sia2() -> dict:
    from astroquery.ipac.irsa import Irsa
    import astropy.units as u

    with common.Timer() as t:
        cols = spherex.spherex_collections()
    res = {"collections": cols, "list_collections_s": round(t.s, 2)}

    def one(coll):
        t0 = time.perf_counter()
        table = Irsa.query_sia(pos=(SPEC.center, 0.001 * u.deg), collection=coll)
        return coll, time.perf_counter() - t0, table

    with common.Timer() as t:
        seq = [one(c) for c in cols]
    res["sequential_s"] = round(t.s, 2)
    res["sequential_per_collection_s"] = {c: round(s, 2) for c, s, _ in seq}
    res["rows"] = {c: len(tab) for c, _, tab in seq}
    with common.Timer() as t, ThreadPoolExecutor(len(cols)) as ex:
        par = list(ex.map(one, cols))
    res["parallel_s"] = round(t.s, 2)
    res["parallel_per_collection_s"] = {c: round(s, 2) for c, s, _ in par}
    # cloud_access: does its S3 key match the on-premises path?
    table = seq[0][2]
    if "cloud_access" in table.colnames and len(table):
        ca = str(table["cloud_access"][0])
        res["cloud_access_example"] = ca
        try:
            key = json.loads(ca)["aws"]["key"]
            res["s3_key_equals_path_after_spherex"] = all(
                json.loads(str(row["cloud_access"]))["aws"]["key"] == str(row["access_url"]).split("/ibe/data/spherex/")[1]
                for row in table)
            res["s3_key_example"] = key
        except Exception as err:  # noqa: BLE001
            res["cloud_access_parse_error"] = str(err)
    print(json.dumps(res, indent=1))
    return res


# --- B ---------------------------------------------------------------------------------------
def headers() -> list[dict]:
    recs = common.records(400)[230:350]  # images no other test touched (IRSA's disk cache stays cold)
    samples = {"IRSA, 8 workers (today)": (recs[0:40], False, 8),
               "S3, 8 workers": (recs[40:80], True, 8),
               "S3, 32 workers": (recs[80:120], True, 32)}
    out = []
    with httpx.Client(timeout=120, follow_redirects=True, limits=httpx.Limits(max_connections=40)) as client:
        for label, (rs, use_s3, workers) in samples.items():
            def one(r, use_s3=use_s3):
                rr = dataclasses.replace(r, access_url=common.s3_url(r)) if use_s3 else r
                t0 = time.perf_counter()
                try:
                    spherex.fetch_image_header(rr, client)
                    return time.perf_counter() - t0, None
                except Exception as err:  # noqa: BLE001
                    return None, str(err)[:120]

            t0 = time.perf_counter()
            with ThreadPoolExecutor(workers) as ex:
                res = list(ex.map(one, rs))
            wall = time.perf_counter() - t0
            ok = [s for s, e in res if s is not None]
            row = {"label": label, "n": len(rs), "wall_s": round(wall, 2), "per_header_s": common.summary(ok),
                   "errors": [e for _, e in res if e], "headers_per_s": round(len(ok) / wall, 1),
                   "projected_s_for_350_images": round(350 / (len(ok) / wall), 1)}
            print(row)
            out.append(row)
    return out


# --- C ---------------------------------------------------------------------------------------
def _gnomonic(ra, dec, ra0, dec0):
    a, d, a0, d0 = map(np.radians, (ra, dec, ra0, dec0))
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    x = np.cos(d) * np.sin(a - a0) / cosc
    y = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    return np.degrees(x), np.degrees(y)


def _homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """3x3 projective map taking the 4 src points to the 4 dst points (DLT)."""
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y, -u], [0, 0, 0, x, y, 1, -v * x, -v * y, -v]]
    _, _, vt = np.linalg.svd(np.array(A))
    return vt[-1].reshape(3, 3)


def predict_pixel(s_region: str, ra: float, dec: float, order: tuple[int, ...], n: int = 2040) -> tuple[float, float]:
    nums = [float(t) for t in s_region.split() if t.replace(".", "", 1).replace("-", "", 1).isdigit()]
    pts = np.array(nums).reshape(-1, 2)[:4]
    ra0, dec0 = pts[:, 0].mean(), pts[:, 1].mean()  # fine away from RA=0 (both test targets are)
    px, py = _gnomonic(pts[:, 0], pts[:, 1], ra0, dec0)
    corners = np.array([[-0.5, -0.5], [n - 0.5, -0.5], [n - 0.5, n - 0.5], [-0.5, n - 0.5]])[list(order)]
    H = _homography(np.column_stack([px, py]), corners)
    tx, ty = _gnomonic(ra, dec, ra0, dec0)
    u, v, w = H @ np.array([tx, ty, 1.0])
    return u / w, v / w


ORDERS = [tuple((k + i) % 4 for i in range(4)) for k in range(4)] + \
         [tuple((k - i) % 4 for i in range(4)) for k in range(4)]


def footprint_locate() -> dict:
    store = db.store
    with store._connection() as conn:  # noqa: SLF001 - benchmark reads the cache directly
        rows = conn.execute("""SELECT c.ra, c.dec, i.frame_id, i.detector, i.access_url, i.s_region, i.x, i.y,
                                      i.wavelength_um FROM coverage_image i JOIN coverage c USING (target_key)
                               WHERE i.x IS NOT NULL AND c.pmra IS NULL""").fetchall()
    # which corner of the polygon is pixel (0,0)? pick the ordering that fits best overall
    errs = {}
    for o in ORDERS:
        e = [np.hypot(*(np.array(predict_pixel(r["s_region"], r["ra"], r["dec"], o)) - (r["x"], r["y"]))) for r in rows[:50]]
        errs[o] = float(np.median(e))
    best = min(errs, key=errs.get)
    pred = np.array([predict_pixel(r["s_region"], r["ra"], r["dec"], best) for r in rows])
    true = np.array([(r["x"], r["y"]) for r in rows])
    d = pred - true
    dist = np.hypot(d[:, 0], d[:, 1])
    # per-image check that the same ordering is best everywhere
    consistent = sum(min(ORDERS, key=lambda o: np.hypot(*(np.array(predict_pixel(r["s_region"], r["ra"], r["dec"], o)) - (r["x"], r["y"])))) == best
                     for r in rows[::10])
    # wavelength error: CWAVE at the predicted pixel vs. at the true pixel
    maps: dict[str, np.ndarray] = {}
    with httpx.Client(timeout=120) as client:
        sm = spherex.SpectralMaps(client, store)
        dwl, rel = [], []
        for r, (px, py) in zip(rows, pred):
            rel_ = spherex.release_of(spherex.ImageRecord("", r["detector"], "", 0, r["access_url"], ""))
            cw, cb = sm.get(rel_, r["detector"])
            ix, iy, jx, jy = int(round(px)), int(round(py)), int(round(r["x"])), int(round(r["y"]))
            if 0 <= ix < 2040 and 0 <= iy < 2040 and 0 <= jx < 2040 and 0 <= jy < 2040:
                dwl.append(abs(float(cw[iy, ix]) - float(cw[jy, jx])))
                rel.append(dwl[-1] / float(cb[jy, jx]))
    res = {"n_images": len(rows), "best_corner_order": best, "median_err_px_by_order": {str(k): round(v, 1) for k, v in errs.items()},
           "same_order_best_for": f"{consistent}/{len(rows[::10])} checked images",
           "pixel_error_px": {"median": round(float(np.median(dist)), 2), "p90": round(float(np.percentile(dist, 90)), 2),
                              "max": round(float(dist.max()), 2), "mean_dx": round(float(d[:, 0].mean()), 2),
                              "mean_dy": round(float(d[:, 1].mean()), 2)},
           "wavelength_error_um": {"median": round(float(np.median(dwl)), 5), "p90": round(float(np.percentile(dwl, 90)), 5),
                                   "max": round(float(np.max(dwl)), 5)},
           "wavelength_error_in_bandwidths": {"median": round(float(np.median(rel)), 4), "max": round(float(np.max(rel)), 4)}}
    print(json.dumps(res, indent=1))
    return res


# --- D ---------------------------------------------------------------------------------------
def calibration() -> dict:
    store = db.store
    with httpx.Client(timeout=120) as client:
        sm = spherex.SpectralMaps(client, store)
        with common.Timer() as t_list:
            key = sm._key("dr1", "D3")  # noqa: SLF001
        with common.Timer() as t_db:
            data = store.calibration(key)
        with common.Timer() as t_parse:
            with fits.open(io.BytesIO(data)) as h:
                h["CWAVE"].data.astype(np.float32), h["CBAND"].data.astype(np.float32)
    with store._connection() as conn:  # noqa: SLF001
        dup = conn.execute("SELECT count(*) AS n, count(DISTINCT md5(data)) AS uniq, sum(octet_length(data)) AS b FROM calibration_file").fetchone()
    res = {"s3_list_s": round(t_list.s, 2), "db_read_32MB_s": round(t_db.s, 2), "parse_s": round(t_parse.s, 2),
           "per_build_cost_s (12 maps, today)": round(12 * (t_list.s + t_db.s + t_parse.s), 1),
           "files_stored": dup["n"], "distinct_contents": dup["uniq"], "stored_MB": round(dup["b"] / 1e6)}
    print(res)
    return res


PARTS = {"C": ("footprint_locate", footprint_locate), "D": ("calibration", calibration),
         "A": ("sia2", sia2), "B": ("headers", headers)}


def main() -> None:
    import sys

    parts = sys.argv[1] if len(sys.argv) > 1 else "CDAB"  # e.g. `CD` = only the offline parts
    path = common.OUT / "t3_coverage.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    for p in parts:
        name, fn = PARTS[p]
        print(f"\n== {p}: {name}")
        res[name] = fn()
    common.save("t3_coverage", res)


if __name__ == "__main__":
    main()
