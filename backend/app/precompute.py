"""Compute the epoch maps of the five challenge test targets, so the API answers for them from the cache.

Only what is missing is computed: a target whose result is complete is skipped, and cached cutouts and
reprojections are reused. Runs at start-up through docker-compose (service `precompute`).

    python -m app.precompute                 # all five
    python -m app.precompute --targets r_dra,barnard
    python -m app.precompute --refresh       # search IRSA again (new weekly data)

The positions are the ones `GET /api/resolve` returns for these names (moving objects are propagated to the
current year), and the field of view is epochs.DEFAULT_FOV_DEG, so the frontend's requests hit the cache.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from . import epochs, presets, resolver


def spec_of(preset: presets.Preset):
    r = resolver.resolve(preset.name)  # a preset: answered locally, no network
    return epochs.spec_for(r.ra, r.dec, None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=",".join(p.key for p in presets.PRESETS))
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per cutout otherwise
    failed = 0
    for key in args.targets.split(","):
        p = presets.find_preset(key)
        if p is None:
            print(f"unknown target {key!r}")
            failed += 1
            continue
        spec = spec_of(p)
        if epochs.is_complete(spec) and not args.refresh:
            print(f"{p.name}: cached ({spec.ra}, {spec.dec}, fov {spec.fov_deg})", flush=True)
            continue
        t0 = time.time()
        print(f"{p.name}: computing ({spec.ra}, {spec.dec}, fov {spec.fov_deg}) ...", flush=True)
        try:
            meta = epochs.run(spec, args.refresh)
        except Exception as err:  # noqa: BLE001 - go on with the next target
            print(f"{p.name}: FAILED: {err}", flush=True)
            failed += 1
            continue
        print(f"{p.name}: done in {time.time() - t0:.0f} s, {meta['n_images']} images, {len(meta['epochs'])} epochs, "
              f"{len(meta['failed'])} failed ({meta['failed_retryable']} to retry), "
              f"modes: {{{', '.join(b['id'] + ': ' + b['mode'] for b in meta['bundles'])}}}", flush=True)
        failed += 1 if meta["failed_retryable"] else 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
