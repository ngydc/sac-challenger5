"""What SPHEREx data exists for the five test targets: every image, when, on which detector and
at what wavelength the target was observed.

No pixel data is downloaded. Per image only the header is read (~26 KB, HTTP range request);
the wavelength comes from the per-detector CWAVE map (Spectral WCS calibration product,
~33 MB per detector, downloaded once into backend/cache/calib/). See app/spherex.py.

Outputs (backend/out/coverage/):
  coverage.csv   one row per image (the table view of the chart)
  coverage.png   time vs. wavelength, one panel per target, colour = detector
  printed summary per target and season: images and wavelength coverage per detector

Run from backend/:  .venv\\Scripts\\python -m scripts.survey_coverage [--targets Barnard,R_Dra]
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import spherex  # noqa: E402

# ICRS J2000 position (deg) and proper motion (mas/yr, pmra includes cos dec), from SIMBAD
# (docs/PROJECT_OVERVIEW.md section 3).
TARGETS = {
    "Barnard":  ("Barnard's Star",  269.4520769586187,   4.693364966576667,  -801.551, 10362.394),
    "epsIndB":  ("Epsilon Indi B",  331.04414658852124, -56.782844195116105, 3981.977, -2466.832),
    "WISE0855": ("WISE 0855",       133.81890825,       -7.247048000000001, -8123.7,     673.2),
    "RW_Aur":   ("RW Aurigae",       76.95652603458333,  30.401438173888888,     7.23,    -20.33),
    "R_Dra":    ("R Draconis",      248.16761083295,     66.75497941722,       -20.643,     6.149),
}
J2000_MJD = 51544.5
N_CHANNEL_BINS = 17  # per detector; we approximate channels as equal steps in log(wavelength)
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]  # D1..D6, fixed order


def mover(ra, dec, pmra, pmdec):
    def at(mjd: float) -> SkyCoord:
        yrs = (mjd - J2000_MJD) / 365.25
        return SkyCoord((ra + pmra * yrs / 3.6e6 / np.cos(np.radians(dec))) * u.deg, (dec + pmdec * yrs / 3.6e6) * u.deg)
    return at


def iso(mjd):
    return Time(mjd, format="mjd").iso[:10]


def channel_bins_hit(wls: list[float], lo: float, hi: float) -> int:
    edges = np.geomspace(lo, hi, N_CHANNEL_BINS + 1)
    return len(set(np.clip(np.digitize(wls, edges) - 1, 0, N_CHANNEL_BINS - 1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=",".join(TARGETS))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "out" / "coverage"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    collections = spherex.spherex_collections()
    print(f"collections: {collections}")
    results = {}
    for key in args.targets.split(","):
        name, ra, dec, pmra, pmdec = TARGETS[key]
        at = mover(ra, dec, pmra, pmdec)
        t0 = time.time()
        recs = spherex.search(at(Time.now().mjd), collections)
        for r in recs:
            r.edge_margin_deg = spherex.edge_margin_deg(at(r.t_mid_mjd), r.s_region)
        exps, failed = spherex.locate_on_detector(recs, at)
        results[key] = exps
        print(f"\n=== {name}: {len(recs)} images, {len(exps)} located, {len(failed)} failed ({time.time() - t0:.0f}s)")
        for r, err in failed[:3]:
            print(f"    failed {r.obs_id} {r.detector}: {err[:100]}")
        summarize(exps)

    write_csv(results, out / "coverage.csv")
    plot(results, out / "coverage.png")
    print(f"\n-> {out}")


def summarize(exps: list[spherex.Exposure]):
    # band edges per detector from the data's own CWAVE values (not hard-coded)
    band = {}
    for d in sorted({e.record.detector for e in exps}):
        w = [e.wavelength_um for e in exps if e.record.detector == d and np.isfinite(e.wavelength_um)]
        band[d] = (min(w), max(w)) if w else (np.nan, np.nan)
    seasons = spherex.group_seasons([e.record for e in exps])
    by_rec = {id(e.record): e for e in exps}
    print(f"    {'season':23s} " + " ".join(f"{d:>11s}" for d in band) + "   (images / ~channels of 17)")
    for s in seasons:
        cells = []
        for d in band:
            w = [by_rec[id(r)].wavelength_um for r in s if r.detector == d]
            w = [v for v in w if np.isfinite(v)]
            cells.append(f"{len(w):3d} / {channel_bins_hit(w, *band[d]):2d}" if w else "      -    ")
        print(f"    {iso(s[0].t_mid_mjd)}..{iso(s[-1].t_mid_mjd)[5:]}  " + " ".join(f"{c:>11s}" for c in cells))
    allw = {d: [e.wavelength_um for e in exps if e.record.detector == d and np.isfinite(e.wavelength_um)] for d in band}
    print(f"    {'all seasons':23s} " + " ".join(f"{len(allw[d]):3d} / {channel_bins_hit(allw[d], *band[d]):2d}" for d in band))


def write_csv(results, path):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["target", "obs_id", "detector", "collection", "time_utc", "mjd", "x_det", "y_det",
                    "wavelength_um", "bandwidth_um", "edge_margin_deg", "access_url"])
        for key, exps in results.items():
            for e in exps:
                r = e.record
                w.writerow([key, r.obs_id, r.detector, r.collection, Time(r.t_mid_mjd, format="mjd").iso[:19],
                            f"{r.t_mid_mjd:.5f}", f"{e.x:.1f}", f"{e.y:.1f}", f"{e.wavelength_um:.4f}",
                            f"{e.bandwidth_um:.4f}", f"{r.edge_margin_deg:.3f}", r.access_url])


def plot(results, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    ink, muted, grid = "#0b0b0b", "#52514e", "#e4e3df"
    n = len(results)
    fig, axes = plt.subplots(n, 1, figsize=(11, 2.6 * n), sharex=True, squeeze=False)
    for ax, (key, exps) in zip(axes[:, 0], results.items()):
        for i, d in enumerate([f"D{k}" for k in range(1, 7)]):
            pts = [(Time(e.record.t_mid_mjd, format="mjd").datetime, e.wavelength_um)
                   for e in exps if e.record.detector == d and np.isfinite(e.wavelength_um)]
            if not pts:
                continue
            t, w = zip(*pts)
            ax.scatter(t, w, s=12, color=COLORS[i], edgecolors="#fcfcfb", linewidths=0.6, label=d, zorder=3)
            ax.annotate(d, xy=(1.005, np.median(w)), xycoords=("axes fraction", "data"), fontsize=8, color=muted, va="center")
        ax.set_title(f"{TARGETS[key][0]}  ({len(exps)} images)", loc="left", fontsize=10, color=ink)
        ax.set_ylabel("wavelength (µm)", fontsize=8, color=muted)
        ax.set_ylim(0.6, 5.2)
        ax.grid(axis="y", color=grid, linewidth=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(grid)
        ax.tick_params(colors=muted, labelsize=8)
    axes[0, 0].legend(ncol=6, fontsize=8, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.12))
    axes[-1, 0].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.suptitle("SPHEREx: when each target was observed, and at which wavelength (one dot = one image)",
                 x=0.01, ha="left", fontsize=11, color=ink)
    fig.patch.set_facecolor("#fcfcfb")
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
