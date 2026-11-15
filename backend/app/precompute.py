"""Compute the deep analysis (and with it the coverage and frames) of the five challenge test targets, by hand.

The backend does the same by itself at start-up (app/main.py, SPHEREX_PRECOMPUTE=1), in the background. This
command is for filling the cache without the web server, and it waits until everything is done. It uses the
same code and the same Postgres cache as the backend: run it while the backend is stopped, or the two may
compute the same target at the same time (harmless, but twice the work).

    python -m app.precompute                      # all five
    python -m app.precompute --targets r_dra,barnard

Needs the database (`docker compose up -d db`, or DATABASE_URL).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from . import presets
from .analysis_jobs import jobs, preset_specs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=",".join(p.key for p in presets.PRESETS))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request otherwise
    wanted = set(args.targets.split(","))
    unknown = wanted - {p.key for p in presets.PRESETS}
    if unknown:
        print(f"unknown targets: {sorted(unknown)}")
        return 1
    specs = {p.name: s for p, s in zip(presets.PRESETS, preset_specs()) if p.key in wanted}
    t0 = time.time()
    jobs.warm(list(specs.values()))
    last: dict[str, str] = {}
    while True:
        states = {name: jobs.status(spec) for name, spec in specs.items()}
        for name, st in states.items():
            pr = st["progress"]
            line = st["state"] + (f": {pr['stage']} ({pr['done']}/{pr['total']})" if pr else "")
            if line != last.get(name):
                print(f"{time.time() - t0:6.0f} s  {name}: {line}", flush=True)
                last[name] = line
        if all(st["state"] in ("ready", "error", "idle") for st in states.values()):
            break
        time.sleep(2)
    failed = [name for name, st in states.items() if st["state"] != "ready"]
    for name, st in states.items():
        r = st["result"]
        if r:
            print(f"{name}: {st['state']}, {r['n_images']} images, {len(r['epochs'])} epochs, {len(r['failed'])} not used, "
                  f"modes: {', '.join(b['id'] + ' ' + b['mode'] for b in r['bundles'])}")
        else:
            print(f"{name}: {st['state']} {st['message'] or ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
