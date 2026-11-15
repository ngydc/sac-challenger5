"""Step 0 of the epoch-map pipeline: measure before building.

Question: is a fixed sky position observed about ONCE per spectral channel per epoch, and do all
epochs cover the same channels? The per-detector bundling of the epoch maps depends on the answer.

For one target (default R Draconis) this prints
  (a) the number of images per epoch and detector,
  (b) which spectral channels are covered at the target position in which epoch,
and writes
  (c) a plot of time against wavelength at the target position,
  plus a CSV with one row per image.

No pixel data is downloaded: per image only the IMAGE header (HTTP range request), then two lookups
at the target's detector pixel:
  wavelength  CWAVE map of the Spectral WCS calibration product
  channel     CHANNEL_MAP of the Spectral Channels calibration product (the official channel
              definition; HDU and column names were read from the real file's headers)

Docs used: docs/spherex/user-guide-data-access.md (SIA2, directory layout of calibration products),
docs/spherex/user-guide-data-products.md (Spectral WCS and Spectral Channels products).
The docs say the channel index runs 0-18 and the file's primary header says NCHAN = 17 "standard
channels per detector". The docs do not say what index 0 and 18 mean; here they are reported
separately as "outside the standard channels".

Run from backend/:  .venv/bin/python -m scripts.epoch_coverage [--target r_dra] [--gap-days 30]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import httpx
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app import epochs, presets, spherex  # noqa: E402

COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]  # D1..D6, as in survey_coverage


def iso(mjd: float) -> str:
    return Time(mjd, format="mjd").iso[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="r_dra", help="preset key or name (app/presets.py)")
    ap.add_argument("--gap-days", type=float, default=30.0, help="a gap longer than this starts a new epoch")
    ap.add_argument("--out", default=str(BACKEND / "out" / "epochs_step0"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = epochs.FileCalibCache()  # backend/cache/calib/, git-ignored

    p = presets.find_preset(args.target)
    if p is None:
        sys.exit(f"unknown target {args.target!r}")

    def at(mjd: float) -> SkyCoord:  # proper motion applied to each image's date
        ra, dec = presets.propagate(p.ra_j2000, p.dec_j2000, p.pmra, p.pmdec, Time(mjd, format="mjd").jyear - presets.J2000_YEAR)
        return SkyCoord(ra * u.deg, dec * u.deg)

    collections = spherex.spherex_collections()
    print(f"target: {p.name}   collections (from IRSA's list): {collections}")
    recs = spherex.search(at(Time.now().mjd), collections)
    print(f"SIA2 hits: {len(recs)}   per collection: {dict(Counter(r.collection for r in recs))}")
    for r in recs:
        r.edge_margin_deg = spherex.edge_margin_deg(at(r.t_mid_mjd), r.s_region)
    exps, failed = spherex.locate_on_detector(recs, at, calib_cache=cache)
    print(f"located on detector: {len(exps)}, failed: {len(failed)}")
    for r, err in failed[:5]:
        print(f"   failed {r.obs_id} {r.detector}: {err[:120]}")

    # channel index at the target pixel, from the release's own Spectral Channels file
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        chan_files = {rel: epochs.load_channels(rel, client, cache) for rel in {spherex.release_of(e.record) for e in exps}}
    nchan = {c["nchan"] for c in chan_files.values()}
    assert len(nchan) == 1, f"releases disagree on NCHAN: {nchan}"
    nchan = nchan.pop()
    rows = []
    for e in exps:
        cmap = chan_files[spherex.release_of(e.record)]["map"]
        ix, iy = int(round(e.x)), int(round(e.y))
        inside = 0 <= iy < cmap.shape[0] and 0 <= ix < cmap.shape[1]
        rows.append({"e": e, "chan": int(cmap[iy, ix]) if inside else -1})

    # epochs: split the time-sorted list at gaps longer than --gap-days (all detectors together)
    seasons = spherex.group_seasons([r["e"].record for r in rows], args.gap_days)
    epoch_of = {id(rec): i for i, s in enumerate(seasons) for rec in s}
    for r in rows:
        r["epoch"] = epoch_of[id(r["e"].record)]
    dets = sorted({r["e"].record.detector for r in rows})
    n_ep = len(seasons)

    times = np.array(sorted(r["e"].record.t_mid_mjd for r in rows))
    gaps = np.diff(times)
    print(f"\ngaps between consecutive images longer than 5 days (epoch threshold {args.gap_days:g} d):")
    for i in np.argsort(gaps)[::-1]:
        if gaps[i] > 5:
            print(f"   {gaps[i]:6.1f} d   {iso(times[i])} -> {iso(times[i + 1])}" + ("   <- epoch boundary" if gaps[i] > args.gap_days else ""))

    print("\n(a) images per epoch and detector")
    print(f"   {'epoch':3s} {'time span':24s} {'days':>5s} " + " ".join(f"{d:>4s}" for d in dets) + "   total")
    for i, s in enumerate(seasons):
        c = Counter(rec.detector for rec in s)
        print(f"   E{i + 1:<2d} {iso(s[0].t_mid_mjd)} .. {iso(s[-1].t_mid_mjd)} {s[-1].t_mid_mjd - s[0].t_mid_mjd:5.0f} "
              + " ".join(f"{c.get(d, 0):4d}" for d in dets) + f"   {len(s):5d}")

    print(f"\n(b) images per spectral channel at the target position (official CHANNEL_MAP, standard channels 1..{nchan})")
    print("    one character per channel: '.' = not covered, digit = number of images, '+' = 10 or more;")
    print("    'out' = images where the target pixel has channel index 0 or 18 (outside the standard channels);")
    print("    'days' = time between the first and last image of that detector in that epoch")
    counts = np.zeros((n_ep, len(dets), nchan + 2), dtype=int)  # index = channel 0..nchan+1
    for r in rows:
        if r["chan"] >= 0:
            counts[r["epoch"], dets.index(r["e"].record.detector), r["chan"]] += 1
    for di, d in enumerate(dets):
        print(f"   {d}  " + "".join(str(c % 10) for c in range(1, nchan + 1)) + "   covered  out  days")
        for ei in range(n_ep):
            std = counts[ei, di, 1 : nchan + 1]
            t = [r["e"].record.t_mid_mjd for r in rows if r["epoch"] == ei and r["e"].record.detector == d]
            span = f"{max(t) - min(t):5.0f}" if t else "    -"
            line = "".join("." if c == 0 else (str(c) if c < 10 else "+") for c in std)
            print(f"     E{ei + 1} {line}   {np.count_nonzero(std):2d}/{nchan}   {counts[ei, di, 0] + counts[ei, di, nchan + 1]:3d} {span}")
        common = np.all(counts[:, di, 1 : nchan + 1] > 0, axis=0)
        print("     all " + "".join("x" if c else "." for c in common) + f"   {common.sum():2d}/{nchan}  channels covered in every epoch")

    std = counts[:, :, 1 : nchan + 1].ravel()
    print(f"\nhypothesis 'about once per channel per epoch': images per (epoch, detector, channel), {std.size} cells")
    for label, sel in (("0", std == 0), ("1", std == 1), ("2", std == 2), ("3-5", (std >= 3) & (std <= 5)), ("6+", std >= 6)):
        print(f"   {label:>3s} images: {sel.sum():4d} cells ({100 * sel.mean():4.1f} %)")
    print(f"   median {np.median(std):.0f}, mean {std.mean():.2f}, max {std.max()}")
    for ei in range(n_ep):
        s = counts[ei, :, 1 : nchan + 1].ravel()
        print(f"   E{ei + 1}: median {np.median(s):.0f}, mean {s.mean():.2f}, cells with 3+ images {100 * (s >= 3).mean():.0f} %, empty {100 * (s == 0).mean():.0f} %")

    with open(out / f"coverage_{p.key}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["epoch", "obs_id", "detector", "collection", "time_utc", "mjd", "x_det", "y_det", "channel",
                    "wavelength_um", "bandwidth_um", "edge_margin_deg", "access_url"])
        for r in rows:
            e, rec = r["e"], r["e"].record
            w.writerow([r["epoch"] + 1, rec.obs_id, rec.detector, rec.collection, Time(rec.t_mid_mjd, format="mjd").iso[:19],
                        f"{rec.t_mid_mjd:.5f}", f"{e.x:.1f}", f"{e.y:.1f}", r["chan"], f"{e.wavelength_um:.4f}",
                        f"{e.bandwidth_um:.4f}", f"{rec.edge_margin_deg:.3f}", rec.access_url])

    plot(rows, seasons, dets, p.name, args.gap_days, out / f"time_wavelength_{p.key}.png")
    print(f"\n-> {out}")


def plot(rows, seasons, dets, name, gap_days, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    ink, muted, grid = "#0b0b0b", "#52514e", "#e4e3df"
    dt = lambda mjd: Time(mjd, format="mjd").datetime  # noqa: E731
    fig, ax = plt.subplots(figsize=(13, 6.5))
    for i, s in enumerate(seasons):
        ax.axvspan(dt(s[0].t_mid_mjd - 1), dt(s[-1].t_mid_mjd + 1), color="#f1f0ec", zorder=0)
        ax.annotate(f"epoch {i + 1}\n{iso(s[0].t_mid_mjd)} to {iso(s[-1].t_mid_mjd)}\n{len(s)} images",
                    xy=(dt((s[0].t_mid_mjd + s[-1].t_mid_mjd) / 2), 1.01), xycoords=("data", "axes fraction"),
                    ha="center", va="bottom", fontsize=8, color=muted)
    for d in dets:
        pts = [(dt(r["e"].record.t_mid_mjd), r["e"].wavelength_um) for r in rows
               if r["e"].record.detector == d and np.isfinite(r["e"].wavelength_um)]
        t, w = zip(*pts)
        ax.scatter(t, w, s=14, color=COLORS[int(d[1:]) - 1], edgecolors="#fcfcfb", linewidths=0.5, zorder=3)
        ax.annotate(d, xy=(1.005, float(np.median(w))), xycoords=("axes fraction", "data"), fontsize=9,
                    color=COLORS[int(d[1:]) - 1], va="center", fontweight="bold")
    ax.set_ylabel("wavelength at the target position (µm)", fontsize=9, color=muted)
    ax.set_yscale("log")
    ticks = [0.75, 1, 1.5, 2, 2.5, 3, 4, 5]
    ax.set_yticks(ticks, [f"{v:g}" for v in ticks])
    ax.minorticks_off()
    ax.grid(axis="y", color=grid, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(grid)
    ax.tick_params(colors=muted, labelsize=8)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.suptitle(f"{name}: when SPHEREx observed it, and at which wavelength  (one dot = one image; "
                 f"shaded = epochs split at gaps > {gap_days:g} days)", x=0.01, ha="left", fontsize=11, color=ink)
    fig.patch.set_facecolor("#fcfcfb")
    fig.tight_layout(rect=(0, 0, 0.98, 0.9))
    fig.savefig(path, dpi=130, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
