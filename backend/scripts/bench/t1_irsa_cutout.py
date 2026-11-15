"""Test 1: IRSA's cutout service, the way the app uses it today (baseline).

A, where the time goes: 4 cutouts one after another at the app's default size; time to first byte
   (IRSA making the cutout) vs. transfer time, bytes, 503 answers.
B, does size matter: 2 images x 3 sizes (0.03, 0.116 = app default, 0.435 deg = largest fov x 1.45).
C, parallelism: 9 images with 3 workers (the app's setting) and 9 other images with 6 workers.

Requests use the same backoff as spherex.download_cutout (503 -> wait 5, 10, 20 s ... or Retry-After).
About 30 cutout requests in total. Run from backend/:  .venv\\Scripts\\python -m scripts.bench.t1_irsa_cutout
"""
from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app import spherex
from scripts.bench import common

SPEC = common.SPEC


def fetch(rec, size: float, client: httpx.Client, retries: int = 6) -> dict:
    """One cutout with timing split into: waiting for the first byte, and downloading the body."""
    url = spherex.cutout_url(rec, SPEC.center, size)
    n503, waited = 0, 0.0
    t_start = time.perf_counter()
    for attempt in range(retries):
        t0 = time.perf_counter()
        with client.stream("GET", url) as resp:
            ttfb = time.perf_counter() - t0
            body = resp.read()
            t_body = time.perf_counter() - t0 - ttfb
        if resp.status_code == 503:
            n503 += 1
            w = float(resp.headers.get("Retry-After", min(5 * 2**attempt, 60))) + random.random() * 2
            waited += w
            time.sleep(w)
            continue
        resp.raise_for_status()
        return {"frame": f"{rec.obs_id}-{rec.detector}", "size_deg": size, "ttfb_s": round(ttfb, 2),
                "body_s": round(t_body, 2), "total_s": round(time.perf_counter() - t_start, 2),
                "bytes": len(body), "n503": n503, "backoff_wait_s": round(waited, 1), "ok": True}
    return {"frame": f"{rec.obs_id}-{rec.detector}", "size_deg": size, "ok": False, "n503": n503,
            "total_s": round(time.perf_counter() - t_start, 2)}


def run_parallel(recs, workers: int, client: httpx.Client) -> dict:
    t0 = time.perf_counter()
    lock, log = threading.Lock(), []

    def one(r):
        res = fetch(r, SPEC.cutout_size, client)
        with lock:
            log.append(res)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, recs))
    wall = time.perf_counter() - t0
    ok = [r for r in log if r["ok"]]
    res = {"workers": workers, "n": len(recs), "ok": len(ok), "wall_s": round(wall, 1),
           "n503": sum(r["n503"] for r in log), "backoff_wait_s": round(sum(r.get("backoff_wait_s", 0) for r in log), 1),
           "per_cutout_total_s": common.summary([r["total_s"] for r in ok]),
           "throughput_cutouts_per_min": round(60 * len(ok) / wall, 1), "items": log}
    print(f"workers={workers}: {len(ok)}/{len(recs)} ok in {wall:.1f}s, {res['n503']} x 503, "
          f"{res['throughput_cutouts_per_min']} cutouts/min")
    return res


def main() -> None:
    recs = common.records(30, offset=2)  # disjoint from the samples of t2 (offsets 1 and 3)
    with httpx.Client(timeout=180, follow_redirects=True, limits=httpx.Limits(max_connections=12)) as client:
        print("== A: sequential, app default size", SPEC.cutout_size)
        seq = []
        for r in recs[0:4]:
            seq.append(fetch(r, SPEC.cutout_size, client))
            print(seq[-1])
        print("\n== B: size")
        sizes = []
        for r in recs[4:6]:
            for s in (0.435, 0.03, 0.116):
                sizes.append(fetch(r, s, client))
                print(sizes[-1])
        print("\n== C: parallel")
        par = [run_parallel(recs[6:15], 3, client), run_parallel(recs[15:24], 6, client)]
    common.save("t1_irsa_cutout", {"sequential": seq, "sequential_summary": {
        k: common.summary([x[k] for x in seq if x["ok"]]) for k in ("ttfb_s", "body_s", "total_s", "bytes")},
        "size": sizes, "parallel": par})


if __name__ == "__main__":
    main()
