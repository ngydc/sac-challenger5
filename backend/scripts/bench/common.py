"""Shared helpers for the benchmarks: a fixed, real sample of images and timing/report utilities.

The sample comes from the coverage the backend already stored for Barnard's Star at the default view
(ra 269.446, dec 4.768, fov 0.08; docs/API.md), so no IRSA search is needed to pick images and every
test uses the same images, the same view and the same cutout size as the running app.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from app import db
from app.service import TargetSpec
from app import spherex

OUT = Path(__file__).resolve().parents[2] / "out" / "bench"
SPEC = TargetSpec.build("269.446", "4.768", 0.08, None, None, None)  # Barnard's Star, default view


def records(n: int, offset: int = 0) -> list[spherex.ImageRecord]:
    """`n` images of the stored coverage, spread over time and detectors (every k-th image).
    Different `offset`s give disjoint samples, so one test never re-requests another test's images."""
    # the coverage stored when the benchmarks were first run (older key, included the fov), else the current one
    data = db.store.load_coverage(SPEC.key) or db.store.load_coverage(SPEC.coverage_key)
    if data is None:
        raise SystemExit("no stored coverage for ra 269.446, dec 4.768: call /api/coverage for it once")
    fields = {f for f in spherex.ImageRecord.__dataclass_fields__}
    recs = [spherex.ImageRecord(**{k: v for k, v in img.items() if k in fields}) for img in data["images"]]
    step = max(1, len(recs) // (n * 4))
    return recs[offset::step][:n]


def s3_url(record: spherex.ImageRecord) -> str:
    """The S3 copy of an image: from SIA2's `cloud_access` column when the record has it, else (older stored
    records) the bucket from docs/spherex/irsa-cloud-access.md plus the on-premises path after '/spherex/',
    which t3_coverage showed to be the same key."""
    return record.cloud_url or f"{spherex.S3_BUCKET_URL}/{record.access_url.split('/ibe/data/spherex/')[1]}"


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.s = time.perf_counter() - self.t0


def summary(values: list[float]) -> dict:
    v = sorted(values)
    if not v:
        return {"n": 0}
    return {"n": len(v), "median": round(statistics.median(v), 3), "min": round(v[0], 3), "max": round(v[-1], 3),
            "mean": round(statistics.fmean(v), 3)}


def save(name: str, result: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nresults -> {path}")
    return path
