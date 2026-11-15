"""Migration: copy the raw data of the OLD epoch-map file cache (backend/cache/examples/, used until 2026-11-15)
into the database, so it is not downloaded again. Since then the deep analysis reads its cutouts and calibration
files from the database itself (app/analysis_jobs.py); its new results live in backend/cache/analysis/.

    cd backend
    python -m scripts.import_examples [path/to/cache] [--all]

- examples/<target>/cutouts/<frame_id>.fits   -> cutout. The cache key is the SHA-1 of the cutout URL, rebuilt
                                                 from search.json (access_url) and target.json (centre, size)
                                                 exactly as app/service.py does, so /api/image.png finds them.
- examples/<target>/cutouts/<frame_id>.outside -> cutout with status 'outside'
- calib/<s3 key>                               -> calibration files (only the ones not stored yet)
Only targets whose status.json says "done" are imported, unless --all is given.
The old reprojections and products are not used any more; delete backend/cache/examples/ afterwards.
Safe to run twice.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app import db, spherex
from app.core import TargetSpec, frame_id


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else Path(__file__).resolve().parents[1] / "cache"
    store = db.store

    for target in sorted((root / "examples").iterdir()):
        try:
            info = json.loads((target / "target.json").read_text())
            state = json.loads((target / "status.json").read_text()).get("state")
            records = json.loads((target / "search.json").read_text())["records"]
        except (OSError, ValueError, KeyError) as err:
            print(f"{target.name}: skipped ({err})")
            continue
        name = info.get("example", target.name)
        if state != "done" and "--all" not in sys.argv:
            print(f"{name}: skipped (state {state!r}, not finished)")
            continue
        spec = TargetSpec.build(str(info["ra"]), str(info["dec"]), info["fov"], None, None, None)
        new = had = outside = missing = 0
        for raw in records:
            rec = spherex.ImageRecord(**raw)
            url = spherex.cutout_url(rec, spec.center, spec.cutout_size)
            key = spherex.cutout_key(url)
            path = target / "cutouts" / f"{frame_id(rec)}.fits"
            if path.exists():
                if store.cutout(key) is None:
                    store.put_cutout(key, url, path.read_bytes())
                    new += 1
                else:
                    had += 1
            elif path.with_suffix(".outside").exists():
                store.put_cutout_failure(key, url, "outside", "view is outside this image")
                outside += 1
            else:
                missing += 1
        print(f"{name}: {new} cutouts imported, {had} already stored, {outside} outside, {missing} without a file")

    n_cal = 0
    for path in sorted((root / "calib").rglob("*.fits")):
        key = path.relative_to(root / "calib").as_posix()
        if store.calibration(key) is None:
            store.put_calibration(key, path.read_bytes())
            n_cal += 1
    print(f"{n_cal} calibration files imported")
    store.close()


if __name__ == "__main__":
    main()
