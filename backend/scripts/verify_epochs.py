"""Check the epoch maps of the test targets against real data (reads the cache only, no IRSA).

For each target: a contact sheet (per bundle: every usable epoch, the epoch RGB, the difference image) and
measurements printed and saved as JSON:
  field stars   centroid shift and brightness ratio between the first and last usable epoch, colour in the RGB
                (they must coincide and be white: this tests reprojection and stretch)
  target        saturation (from the flags), centroid per epoch against the proper-motion prediction

Run from backend/ after the analyses exist (the backend computes them at start-up, or `python -m app.precompute`):
    .venv/bin/python -m scripts.verify_epochs [--targets r_dra,barnard]
Outputs: backend/out/epochs_verify/<target>.png and <target>.json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from PIL import Image
from scipy.ndimage import maximum_filter, median_filter
from scipy.optimize import least_squares

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app import presets, spherex  # noqa: E402
from app.analysis_jobs import jobs, preset_specs  # noqa: E402
from app.service import PIXEL_SCALE_ARCSEC  # noqa: E402

STAR_MIN_SNR = 15.0  # field stars used for the alignment test: peak this many sigma above its surroundings
HALF = 3  # fit window half-size in pixels


def fit_star(img: np.ndarray, x0: float, y0: float, half: int = HALF):
    """2D Gaussian fit to the valid pixels of a window around (x0, y0). Returns (x, y, amplitude) or None."""
    ix, iy = int(round(x0)), int(round(y0))
    ys, xs = np.mgrid[iy - half : iy + half + 1, ix - half : ix + half + 1]
    ok = (ys >= 0) & (ys < img.shape[0]) & (xs >= 0) & (xs < img.shape[1])
    ys, xs = ys[ok], xs[ok]
    v = img[ys, xs]
    good = np.isfinite(v)
    if good.sum() < 15:
        return None
    xs, ys, v = xs[good], ys[good], v[good]

    def resid(p):
        a, x, y, s, b = p
        return a * np.exp(-((xs - x) ** 2 + (ys - y) ** 2) / (2 * s**2)) + b - v

    p0 = [float(v.max()), x0, y0, 1.0, float(np.median(v))]
    try:
        r = least_squares(resid, p0, bounds=([0, x0 - half, y0 - half, 0.4, -np.inf], [np.inf, x0 + half, y0 + half, 4.0, np.inf]))
    except Exception:  # noqa: BLE001
        return None
    return (float(r.x[0]), float(r.x[1]), float(r.x[2])) if r.success else None


def checker(h: int, w: int) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w]
    return np.where(((x // 2) + (y // 2)) % 2 == 0, 0.32, 0.42)


def show(ax, png: bytes | None, title: str):
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=7)
    if png is None:
        ax.set_facecolor("#f1f0ec")
        return
    a = np.array(Image.open(io.BytesIO(png)).convert("RGBA")).astype(float) / 255
    bg = checker(*a.shape[:2])[..., None]
    ax.imshow(a[..., :3] * a[..., 3:] + bg * (1 - a[..., 3:]), interpolation="nearest")  # transparent = checkerboard


def verify(key: str, out: Path) -> dict:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = presets.find_preset(key)
    spec = dict(zip((q.key for q in presets.PRESETS), preset_specs()))[p.key]
    d, meta = jobs.latest(spec)
    if not meta:
        print(f"{p.name}: not computed")
        return {}
    grid, shape = spherex.north_up_wcs(spec.center, spec.fov_deg, PIXEL_SCALE_ARCSEC / 3600)
    report = {"target": p.name, "ra": spec.ra, "dec": spec.dec, "complete": meta["complete"], "n_images": meta["n_images"],
              "failed": len(meta["failed"]), "epochs": [(e["start"][:10], e["end"][:10], e["n_images"]) for e in meta["epochs"]],
              "bundles": {}}
    print(f"\n=== {p.name}  ({meta['n_images']} images, {len(meta['failed'])} failed, complete={meta['complete']})")
    for e in meta["epochs"]:
        print(f"   epoch {e['index']}: {e['start'][:10]} .. {e['end'][:10]}  {e['n_images']} images  {e['images_per_detector']}")

    def predicted(time_iso: str) -> tuple[float, float]:
        years = Time(time_iso).jyear - presets.J2000_YEAR
        ra, dec = presets.propagate(p.ra_j2000, p.dec_j2000, p.pmra, p.pmdec, years)
        x, y = grid.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
        return float(x), float(y)

    bundles = meta["bundles"]
    ncol = max([len(b["usable_epochs"]) for b in bundles] + [1]) + 2
    fig, axes = plt.subplots(len(bundles), ncol, figsize=(2.1 * ncol, 2.5 * len(bundles) + 0.4), squeeze=False)
    for row, b in enumerate(bundles):
        bid = b["id"]
        for ax in axes[row]:
            ax.axis("off")
        wl = b["wavelength_um"]
        head = f"{bid}" + (f" {wl['min']:.2f}-{wl['max']:.2f} µm" if wl else "")
        rep: dict = {"mode": b["mode"], "usable_epochs": b["usable_epochs"], "wavelength_um": wl, "gaps": b["gaps"]}
        report["bundles"][bid] = rep
        print(f"\n   [{bid}] {b['mode']}  usable epochs {b['usable_epochs']}  "
              + (f"{wl['min']:.3f}-{wl['max']:.3f} um, {len(b['channels'])} channels, " if wl else "")
              + (f"covered {100 * b['covered_fraction']:.0f} %" if "covered_fraction" in b else ""))
        for g in b["gaps"]:
            print(f"        gap: {g}")
        if not b["usable_epochs"]:
            axes[row][0].axis("on")
            show(axes[row][0], None, f"{head}\nno data")
            continue
        ep = {e["index"]: e for e in b["epochs"]}
        for col, e in enumerate(b["usable_epochs"]):
            axes[row][col].axis("on")
            show(axes[row][col], (d / f"frame_{bid}_e{e}.png").read_bytes(),
                 f"{head}\nepoch {e}: {ep[e]['time'][:10]} ({ep[e]['n_images']} img, {ep[e]['span_days']:.0f} d)")
        axes[row][ncol - 2].axis("on")
        used = "/".join(str(b["rgb"][c]["epoch"]) for c in ("red", "green", "blue"))
        show(axes[row][ncol - 2], (d / f"rgb_{bid}.png").read_bytes(), f"RGB = epochs {used}\n{b['mode']}")
        if b["diff"]:
            axes[row][ncol - 1].axis("on")
            show(axes[row][ncol - 1], (d / f"diff_{bid}.png").read_bytes(),
                 f"difference {b['diff']['last']['epoch']} - {b['diff']['first']['epoch']}\n±{b['diff']['clip_sigma']:g} sigma")

        with np.load(d / f"bundle_{bid}.npz") as z:
            B, diff = z["image"], (z["diff"] if "diff" in z else None)
        first, last = b["usable_epochs"][0], b["usable_epochs"][-1]
        noise = b["stretch"]["noise"]
        rep["saturated_images"] = {e: f"{ep[e]['saturated_images']}/{ep[e]['n_images']}" for e in b["usable_epochs"]}
        print(f"        target saturated (OVERFLOW within 1 px) in images per epoch: {rep['saturated_images']}")

        # the target: centroid per epoch against the proper-motion prediction
        tgt = []
        for e in b["usable_epochs"]:
            px, py = predicted(ep[e]["time"])
            f = fit_star(B[e], px, py, half=4)
            tgt.append({"epoch": e, "time": ep[e]["time"][:10], "predicted": (round(px, 2), round(py, 2)),
                        "measured": (round(f[1], 2), round(f[2], 2)) if f else None, "amplitude": round(f[0], 3) if f else None})
        rep["target"] = tgt
        for t in tgt:
            off = (f"offset {np.hypot(t['measured'][0] - t['predicted'][0], t['measured'][1] - t['predicted'][1]):.2f} px, amplitude {t['amplitude']:.2f}"
                   if t["measured"] else "no fit (too few valid pixels)")
            print(f"        target epoch {t['epoch']} {t['time']}: predicted {t['predicted']}, measured {t['measured']}  {off}")
        ok = [t for t in tgt if t["measured"]]
        if len(ok) >= 2:
            dm = np.subtract(ok[-1]["measured"], ok[0]["measured"]) * PIXEL_SCALE_ARCSEC
            dp = np.subtract(ok[-1]["predicted"], ok[0]["predicted"]) * PIXEL_SCALE_ARCSEC
            rep["target_motion_arcsec"] = {"measured": [round(float(v), 2) for v in dm], "predicted": [round(float(v), 2) for v in dp]}
            print(f"        target motion {ok[0]['time']} -> {ok[-1]['time']} (dx, dy in arcsec; +x = west, +y = north): "
                  f"measured ({dm[0]:+.2f}, {dm[1]:+.2f}), predicted from the catalogue proper motion ({dp[0]:+.2f}, {dp[1]:+.2f})")

        # field stars: peaks of the mean image, away from the target and the edges
        if len(b["usable_epochs"]) < 2 or not noise:
            continue
        mean = np.nanmean(B[b["usable_epochs"]], axis=0)
        filled = np.nan_to_num(mean, nan=0.0)
        contrast = filled - median_filter(filled, size=9)  # above the local surroundings (a bright halo is not a star)
        peak = np.isfinite(mean) & (filled == maximum_filter(filled, size=5)) & (contrast > STAR_MIN_SNR * noise)
        rgb = np.array(Image.open(d / f"rgb_{bid}.png").convert("RGBA"))[::-1]
        tpos = [predicted(ep[e]["time"]) for e in b["usable_epochs"]]
        if diff is not None:  # the difference relative to its surroundings (a variable halo is not the star's doing)
            dloc = median_filter(np.nan_to_num(diff, nan=0.0), size=9)
        stars = []
        for y, x in zip(*np.nonzero(peak)):
            if min(x, y, shape[1] - 1 - x, shape[0] - 1 - y) < HALF + 1 or any(np.hypot(x - tx, y - ty) < 6 for tx, ty in tpos):
                continue
            f0, f1 = fit_star(B[first], x, y), fit_star(B[last], x, y)
            if not f0 or not f1:
                continue
            c = rgb[y, x, :3].astype(int)
            stars.append({"x": int(x), "y": int(y), "snr": round(float(contrast[y, x] / noise)), "dx": f1[1] - f0[1], "dy": f1[2] - f0[2],
                          "ratio": f1[0] / f0[0], "chroma": int(c.max() - c.min()),
                          "diff_peak": float(np.nanmax(np.abs((diff - dloc)[y - 2 : y + 3, x - 2 : x + 3]))) if diff is not None else None})
        rep["field_stars"] = stars
        if stars:
            dx, dy = np.array([s["dx"] for s in stars]), np.array([s["dy"] for s in stars])
            ratio = np.array([s["ratio"] for s in stars])
            print(f"        {len(stars)} field stars (> {STAR_MIN_SNR:g} sigma), epoch {first} -> {last}: "
                  f"mean shift ({dx.mean():+.2f}, {dy.mean():+.2f}) px, largest {np.hypot(dx, dy).max():.2f} px; "
                  f"brightness ratio median {np.median(ratio):.3f} (range {ratio.min():.2f}-{ratio.max():.2f}); "
                  f"RGB colour spread at the peak (0 = white, 255 = pure colour): median {int(np.median([s['chroma'] for s in stars]))}, "
                  f"max {max(s['chroma'] for s in stars)}"
                  + (f"; largest |difference| on a field star relative to its surroundings {max(s['diff_peak'] for s in stars):.1f} sigma" if diff is not None else ""))
        else:
            print(f"        no field stars above {STAR_MIN_SNR:g} sigma")
    fig.suptitle(f"{p.name}: epoch maps (transparent pixels shown as checkerboard; north up, east left)", fontsize=10, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97), h_pad=2.5)
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{p.key}.png", dpi=110)
    plt.close(fig)
    (out / f"{p.key}.json").write_text(json.dumps(report, indent=1, default=float))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=",".join(p.key for p in presets.PRESETS))
    ap.add_argument("--out", default=str(BACKEND / "out" / "epochs_verify"))
    args = ap.parse_args()
    for key in args.targets.split(","):
        verify(key, Path(args.out))
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
