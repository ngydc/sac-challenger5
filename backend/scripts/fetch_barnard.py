"""Test run of the SPHEREx data pipeline on Barnard's Star.

What it does, step by step:
  1. Ask IRSA which SPHEREx collections exist (picks up new releases automatically).
  2. Search all of them (SIA2) for images containing Barnard's Star.
  3. Filter: one detector, target safely inside the image.
  4. Group the images into observing seasons (~6 months apart).
  5. Download cutouts (cached in the backend's Postgres database, app/db.py), compute the wavelength at the star.
  6. Resample every cutout to the same north-up grid and median-stack each season.
  7. Measure where the star is in each season and compare with where its known proper motion
     says it should be. If the pipeline is right, the two agree to a fraction of a pixel.

Outputs go to backend/out/barnard/: a blink GIF of the season stacks, a contact sheet of single
frames, and summary.json.

Needs the cache database: `docker compose up -d db` from the repo root.
Run from the backend/ folder:
    python -m scripts.fetch_barnard                # defaults: detector D2, 0.05 deg field
    python -m scripts.fetch_barnard --detector D6 --size 0.08 --max-per-season 10
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, spherex  # noqa: E402

# Barnard's Star, from SIMBAD (see docs/PROJECT_OVERVIEW.md section 3). ICRS, epoch J2000.
RA_J2000, DEC_J2000 = 269.4520769586187, 4.693364966576667
PMRA_COSDEC, PMDEC = -801.551, 10362.394  # mas/yr
J2000_MJD = 51544.5


def position_at(mjd: float) -> SkyCoord:
    """Linear proper-motion propagation (fine over decades for this purpose)."""
    years = (mjd - J2000_MJD) / 365.25
    dec = DEC_J2000 + PMDEC * years / 3.6e6
    ra = RA_J2000 + PMRA_COSDEC * years / 3.6e6 / np.cos(np.radians(DEC_J2000))
    return SkyCoord(ra * u.deg, dec * u.deg)


def iso(mjd: float) -> str:
    return Time(mjd, format="mjd").iso[:16]


def centroid(img: np.ndarray, x0: float, y0: float, half: int = 7) -> tuple[float, float]:
    """Star position from a 2D Gaussian + constant fit in a box around (x0, y0).
    Masked (NaN) pixels are skipped, so a saturated or partly masked core doesn't bias the
    result: the fit is pinned down by the unsaturated wings."""
    from astropy.modeling import fitting, models

    ix, iy = int(round(x0)), int(round(y0))
    y_lo, y_hi = max(iy - half, 0), min(iy + half + 1, img.shape[0])
    x_lo, x_hi = max(ix - half, 0), min(ix + half + 1, img.shape[1])
    box = img[y_lo:y_hi, x_lo:x_hi]
    yy, xx = np.mgrid[y_lo:y_hi, x_lo:x_hi]
    ok = np.isfinite(box)
    bg = float(np.nanmedian(img))
    model = models.Gaussian2D(np.nanmax(box) - bg, x0, y0, 2, 2) + models.Const2D(bg)
    fit = fitting.LevMarLSQFitter()(model, xx[ok], yy[ok], box[ok])
    return float(fit.x_mean_0.value), float(fit.y_mean_0.value)


def pick_evenly(items: list, n: int) -> list:
    if len(items) <= n:
        return items
    idx = np.linspace(0, len(items) - 1, n).round().astype(int)
    return [items[i] for i in idx]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detector", default="D2", help="D1..D6 (default D2, 1.1-1.6 um)")
    ap.add_argument("--size", type=float, default=0.05, help="field of view in degrees (default 0.05 = 3 arcmin)")
    ap.add_argument("--max-per-season", type=int, default=8, help="cutouts downloaded per season")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "out" / "barnard"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1-2. Search ------------------------------------------------------------------------------
    collections = spherex.spherex_collections()
    print(f"[1] SPHEREx collections at IRSA: {collections}")
    now = position_at(Time.now().mjd)
    records = spherex.search(now, collections)
    print(f"[2] SIA2: {len(records)} images contain the star  ({time.time() - t0:.0f}s)")

    # 3. Filter --------------------------------------------------------------------------------
    margin = args.size / 2 * np.sqrt(2)  # whole cutout inside the image
    recs = spherex.filter_records(records, now, detectors=[args.detector], min_edge_margin_deg=margin)
    print(f"[3] after filter (detector {args.detector}, >= {margin:.3f} deg from the edge): {len(recs)}")
    if not recs:
        sys.exit("nothing to fetch")

    # 4. Seasons -------------------------------------------------------------------------------
    seasons = spherex.group_seasons(recs)
    print(f"[4] {len(seasons)} seasons:")
    for s in seasons:
        print(f"      {iso(s[0].t_mid_mjd)[:10]} .. {iso(s[-1].t_mid_mjd)[:10]}  {len(s):3d} images  ({s[0].collection})")

    # The field centre is the star's position at the middle of the data, so it drifts across the frame.
    center = position_at(np.mean([r.t_mid_mjd for r in recs]))
    chosen = [r for s in seasons for r in pick_evenly(s, args.max_per_season)]

    # 5. Fetch ---------------------------------------------------------------------------------
    t1 = time.time()
    frames, failures = spherex.fetch_frames(chosen, center, args.size, position_at, cache=db.store)
    print(f"[5] fetched {len(frames)}/{len(chosen)} cutouts in {time.time() - t1:.0f}s; {len(failures)} failed")
    for r, err in failures:
        print(f"      FAILED {r.obs_id} {r.detector}: {err[:120]}")
    if not frames:
        sys.exit("no frames")

    # 6. Common grid + stacks ------------------------------------------------------------------
    scale = spherex.native_pixel_scale_deg(frames[0])
    grid, shape = spherex.north_up_wcs(center, args.size, scale)
    aligned = [spherex.reproject_frame(f, grid, shape) for f in frames]
    print(f"[6] common grid {shape[0]}x{shape[1]} px at {scale * 3600:.2f}\"/px (from the image WCS)")

    season_of = {id(r): i for i, s in enumerate(seasons) for r in s}
    stacks = []
    for i, s in enumerate(seasons):
        imgs = [a for a, f in zip(aligned, frames) if season_of[id(f.record)] == i]
        fr = [f for f in frames if season_of[id(f.record)] == i]
        if imgs:
            stacks.append((i, spherex.stack(imgs), fr))

    # 7. Check the motion ----------------------------------------------------------------------
    print("[7] star position per season stack (measured vs. predicted from proper motion):")
    print(f"      {'season':10s} {'n':>2s} {'wavelengths (um)':>17s} {'offset from prediction':>24s}")
    summary = {"detector": args.detector, "size_deg": args.size, "collections": collections,
               "pixel_scale_arcsec": scale * 3600, "seasons": [], "frames": [], "failures": len(failures)}
    measured = []
    for i, img, fr in stacks:
        mjd = float(np.mean([f.record.t_mid_mjd for f in fr]))
        pred = position_at(mjd)
        px, py = (float(v) for v in grid.world_to_pixel(pred))
        cx, cy = centroid(img, px, py)
        meas = grid.pixel_to_world(cx, cy)
        dra, ddec = pred.spherical_offsets_to(meas)
        off = np.hypot(dra.to(u.arcsec).value, ddec.to(u.arcsec).value)
        wls = [f.wavelength_um for f in fr]
        measured.append((mjd, meas))
        print(f"      {iso(mjd)[:10]} {len(fr):2d} {min(wls):8.3f}-{max(wls):.3f}   {off:5.2f}\" = {off / (scale * 3600):.2f} px")
        summary["seasons"].append({"date": iso(mjd), "n_frames": len(fr), "pred_xy": [px, py],
                                   "meas_xy": [cx, cy], "offset_arcsec": off,
                                   "wavelength_um": [min(wls), max(wls)]})
    if len(measured) > 1:
        (m0, p0), (m1, p1) = measured[0], measured[-1]
        moved = p0.separation(p1).to(u.arcsec).value
        expect = np.hypot(PMRA_COSDEC, PMDEC) / 1000 * (m1 - m0) / 365.25
        print(f"      moved {moved:.1f}\" between first and last season; proper motion predicts {expect:.1f}\"")
        summary["moved_arcsec"], summary["expected_arcsec"] = moved, expect

    for f in frames:
        summary["frames"].append({"obs_id": f.record.obs_id, "time": iso(f.record.t_mid_mjd),
                                  "collection": f.record.collection, "wavelength_um": f.wavelength_um,
                                  "flags_at_target": f.flags_at_target, "version": f.version})
    (out / "summary.json").write_text(json.dumps(summary, indent=1))

    # Pictures -----------------------------------------------------------------------------------
    render(stacks, frames, aligned, grid, out, args.detector)
    print(f"done in {time.time() - t0:.0f}s -> {out}")


def render(stacks, frames, aligned, grid, out: Path, det: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    from astropy.visualization import AsinhStretch, ImageNormalize, PercentileInterval

    # One stretch for all season stacks, so brightness differences are real (CLAUDE.md: consistent stretch).
    allpix = np.concatenate([s.ravel() for _, s, _ in stacks])
    norm = ImageNormalize(allpix[np.isfinite(allpix)], interval=PercentileInterval(99.5), stretch=AsinhStretch(0.05))

    fig, ax = plt.subplots(figsize=(4, 4.4))
    ax.set_axis_off()
    im = ax.imshow(stacks[0][1], origin="lower", cmap="gray", norm=norm, interpolation="nearest")
    mark = ax.plot([], [], "o", mfc="none", mec="red", ms=14)[0]
    title = ax.set_title("")

    def draw(k):
        _, img, fr = stacks[k]
        mjd = float(np.mean([f.record.t_mid_mjd for f in fr]))
        x, y = grid.world_to_pixel(position_at(mjd))
        im.set_data(img)
        mark.set_data([x], [y])
        title.set_text(f"Barnard's Star  {det}  {iso(mjd)[:10]}\n{len(fr)} frames stacked, red = predicted")
        return im, mark, title

    FuncAnimation(fig, draw, frames=len(stacks)).save(out / "blink_seasons.gif", writer=PillowWriter(fps=1.5))
    plt.close(fig)

    cols = 8
    rows = int(np.ceil(len(frames) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 1.5, rows * 1.75), squeeze=False)
    for ax in axes.flat:
        ax.set_axis_off()
    for ax, f, a in zip(axes.flat, frames, aligned):
        ax.imshow(a, origin="lower", cmap="gray", norm=norm, interpolation="nearest")
        ax.set_title(f"{iso(f.record.t_mid_mjd)[:10]}\n{f.wavelength_um:.3f} um", fontsize=6)
    fig.suptitle(f"Barnard's Star, {det}: single frames, north up, same stretch", fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "frames.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
