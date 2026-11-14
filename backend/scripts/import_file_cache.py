"""One-off: copy the old file cache (backend/cache/) into the database, so nothing is downloaded again.

    cd backend
    .venv\\Scripts\\python -m scripts.import_file_cache [path/to/cache]

- cache/calib/<s3 key>        -> calibration_file (keyed by the S3 key, as app/spherex.py looks it up)
- cache/cutouts/<sha1>.fits   -> cutout (the file name already is the cache key: SHA-1 of the cutout URL;
                                 the URL itself was not saved, so it is stored as '')
Search results (cache/coverage/) are not imported; they are rebuilt on the first request.
Safe to run twice. Afterwards the folder can be deleted.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app import db


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "cache"
    store = db.store
    n_cal = n_cut = 0
    for path in sorted((root / "calib").rglob("*.fits")):
        key = path.relative_to(root / "calib").as_posix()
        if store.calibration(key) is None:
            store.put_calibration(key, path.read_bytes())
            n_cal += 1
    for path in sorted((root / "cutouts").glob("*.fits")):
        if store.cutout(path.stem) is None:
            store.put_cutout(path.stem, "", path.read_bytes())
            n_cut += 1
    print(f"imported {n_cal} calibration files and {n_cut} cutouts from {root}")
    store.close()


if __name__ == "__main__":
    main()
