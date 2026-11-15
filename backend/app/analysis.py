"""Epoch maps, the computation: for one sky position, one averaged image per observing epoch and detector, and
from those an epoch RGB and a difference image per detector. Pure functions: no network, no files, no threads.
Fetching, storing and job control are in app/analysis_jobs.py; the HTTP API is app/analysis_api.py.

An "epoch" here is the same as a "visit" of the viewer: images grouped by core.VISIT_GAP_DAYS.

Docs used (CLAUDE.md rule):
- docs/spherex/user-guide-data-products.md     HDUs and units, Spectral Channels product
- docs/spherex/tutorial-intro-spectral-images.md  spectral WCS, flag names from MSKNnnnn keywords
- docs/spherex/tutorial-psf-in-cutouts.md      CRPIX1A/CRPIX2A: cutout pixel -> parent image pixel
- docs/spherex/explanatory-supplement-extracts.md  Table 16 (meaning of each flag)
HDU and column names of the Spectral Channels file (CHANNEL_MAP, SPECTRAL_CHANNELS, NCHAN) were read from
the real file's headers; the docs only describe its content in words.

Why two averaging steps: every pixel of a SPHEREx image has its own wavelength, and a sky position is
measured only once or twice per spectral channel per epoch (measured for R Draconis, scripts/epoch_coverage.py).
Averaging a whole detector naively would mix the wavelengths differently in each epoch, and a constant star
with a steep spectrum would look changed. So: (a) average per channel and epoch, (b) average the channels with
weights that are the same in every epoch, using only channels that every compared epoch has.
"""
from __future__ import annotations

import hashlib
import io
import json
import warnings
from collections.abc import Callable

import numpy as np
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

from . import spherex
from .core import PIXEL_SCALE_ARCSEC, VISIT_GAP_DAYS, TargetSpec, frame_id

# --- settings -------------------------------------------------------------------------------
OUTLIER_MIN_N = 3  # outlier rejection needs at least this many contributions to a pixel
OUTLIER_SIGMA = 3.0  # reject contributions further than this from the median ...
OUTLIER_REL = 0.2  # ... where sigma^2 = variance + (OUTLIER_REL * median)^2: single exposures of a star differ by
#                    more than their noise (the PSF is undersampled), and those are not outliers
SPIKE_MIN_CHANNELS = 5  # with at least this many channels of one detector at a pixel, single-channel spikes are dropped:
SPIKE_SIGMA = 5.0  # a channel further than SPIKE_SIGMA * its sigma + SPIKE_REL * |median of the channels| from that
SPIKE_REL = 2.0  # median. Most channels have one exposure, so a cosmic-ray hit or bad pixel that the flags missed
#                  cannot be rejected in step 7a; but a real source is seen in all channels of a detector, a hit in one.
CHANNEL_MIN_FIELD_FRACTION = 0.5  # a channel counts as covered in an epoch if it has data on this share of the field
EPOCH_MIN_CHANNEL_FRACTION = 0.5  # an epoch is usable for a bundle if it covers this share of the bundle's channels
DIFF_CLIP_SIGMA = 8.0  # the difference image's colour scale ends at +- this many sigma
DIFF_RELATIVE_FLOOR = 0.15  # the difference's uncertainty includes this fraction of the pixel's brightness. Measured
#                             (Barnard's Star field, D1 and D2, 2026-11-14): pixels of UNCHANGED field stars differ
#                             by 11-16 % (robust sigma) between epochs, because the PSF is undersampled and most
#                             channels have a single exposure. Without this term every bright star looks changed.
STRETCH_HI_PERCENTILE = 99.7
SKY_FRACTION = 0.1  # the darkest 10 % of the field count as sky (see `dark_sky`)
REPROJ_VERSION = 1  # bump when `reproject_cutout` changes: cached reprojections are then redone
PIPELINE_VERSION = 11  # 11: colour composites (10 was a development state without them). Bump when anything after the reprojection changes: products are then redone

# Colour composite (see `colour_composite`): every wavelength of one epoch in one picture.
# The ramp gives each channel a colour by its position in log(wavelength) between the shortest and the longest
# channel: blue (short) -> cyan -> green -> yellow -> red (long). Anchors are (position 0..1, (r, g, b)).
COLOUR_RAMP = ((0.0, (0.05, 0.2, 1.0)), (0.3, (0.0, 0.75, 0.95)), (0.5, (0.3, 1.0, 0.3)), (0.7, (1.0, 0.8, 0.0)),
               (1.0, (1.0, 0.08, 0.0)))
COLOUR_MIN_CHANNEL_FRACTION = 0.5  # an epoch gets a colour picture if it covers this share of all channels
COLOUR_HOLE_SIZE = 15  # px: holes up to about this size inside a channel's footprint count as masked pixels
COLOUR_MIN_WEIGHT = 0.35  # a pixel is masked if a colour (r, g or b) has less than this share of its expected data.
#                          Measured on the test targets (2026-11-15): moderately bright stars lose 10-30 % of their
#                          channels to flags (SUR_ERROR, TRANSIENT, ...) without a visible colour error; 0.7 masked
#                          about 10 % of the field, 0.35 keeps those stars and still masks saturated cores.
COLOUR_BALANCE_PERCENTILE = 98.0  # white balance on the pixels brighter than this percentile (the stars)
COLOUR_CHROMA_SIGMA = (2.0, 8.0)  # colour fades in between these brightnesses (in noise sigma): sky noise stays grey
COLOUR_MASK_RGB = (88, 90, 100)  # masked pixels (saturated or flagged in a channel this epoch should have)

# Flags that make a pixel unusable here, by NAME (bit numbers come from each file's FLAGS header).
# Chosen from Table 16 of the Explanatory Supplement: everything described as unusable, erroneous, saturated
# or an artifact. Deliberately not included: SOURCE (set on most pixels), FULLSAMPLE's neighbours etc. are
# not flags; HALO ("caution recommended") and CROSSTALK (percent-level) are kept; GHOST_FPA and GHOST_EXT
# are described as unused / in development.
BAD_FLAG_NAMES = ("TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "DICHROIC", "MISSING_DATA", "HOT", "COLD",
                  "FULLSAMPLE", "PHANMISS", "NONLINEAR", "PERSIST", "OUTLIER", "GHOST", "STREAK", "BLOOM",
                  "SNOWBALL", "SATELLITE_HALO")
SATURATION_FLAG = "OVERFLOW"  # Table 16: "overflow threshold reached", about half of full-well saturation

warnings.filterwarnings("ignore", message=".*All-NaN slice.*")
warnings.filterwarnings("ignore", message=".*Mean of empty slice.*")


# --- parameters, helpers ---------------------------------------------------------------
def params_key(params: dict) -> str:
    """Short hash of a parameter set: results computed with other parameters live under another key."""
    return hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]


def reproj_params() -> dict:
    return {"reproj_version": REPROJ_VERSION, "bad_flags": list(BAD_FLAG_NAMES), "pixel_scale_arcsec": PIXEL_SCALE_ARCSEC}


def epochmap_params() -> dict:
    """Everything that changes the epoch maps. A different value gives a different products directory."""
    return {"pipeline_version": PIPELINE_VERSION, "reproj": reproj_params(), "epoch_gap_days": VISIT_GAP_DAYS,
            "outlier": [OUTLIER_MIN_N, OUTLIER_SIGMA, OUTLIER_REL], "sky_fraction": SKY_FRACTION,
            "spike": [SPIKE_MIN_CHANNELS, SPIKE_SIGMA, SPIKE_REL],
            "channel_min_field_fraction": CHANNEL_MIN_FIELD_FRACTION, "epoch_min_channel_fraction": EPOCH_MIN_CHANNEL_FRACTION,
            "diff": [DIFF_CLIP_SIGMA, DIFF_RELATIVE_FLOOR], "stretch_hi_percentile": STRETCH_HI_PERCENTILE,
            "colour": [COLOUR_RAMP, COLOUR_MIN_CHANNEL_FRACTION, COLOUR_HOLE_SIZE, COLOUR_MIN_WEIGHT,
                       COLOUR_BALANCE_PERCENTILE, COLOUR_CHROMA_SIGMA, COLOUR_MASK_RGB]}


def _num(x, digits: int = 6):
    """A float for JSON: None instead of NaN/inf."""
    x = float(x)
    return round(x, digits) if np.isfinite(x) else None


def iso_time(mjd: float) -> str:
    return Time(mjd, format="mjd").isot[:19] + "Z"


def clipped_stats(x: np.ndarray, k: float = 3.0, iters: int = 8) -> tuple[float, float]:
    """Median and robust sigma (1.4826 * MAD) after iteratively dropping values further than k sigma."""
    x = x[np.isfinite(x)]
    if x.size < 20:
        return float("nan"), float("nan")
    med, sig = float(np.median(x)), 0.0
    for _ in range(iters):
        med = float(np.median(x))
        sig = 1.4826 * float(np.median(np.abs(x - med)))
        keep = np.abs(x - med) <= k * sig
        if sig == 0 or keep.all():
            break
        x = x[keep]
    return med, sig


def dark_sky(img: np.ndarray, frac: float = SKY_FRACTION) -> np.ndarray:
    """The source-free pixels of a field: the darkest `frac` of the valid pixels of the (median-smoothed) image.

    A sigma-clipped median is not enough here: a bright star's halo can fill the whole field (R Draconis),
    and then "most pixels" are not sky. The darkest pixels are the emptiest sky the field has. The same set
    of pixels is used for every exposure and epoch, so whatever is left of a halo there is removed equally.
    Smoothing first makes the choice follow real structure instead of single-pixel noise."""
    from scipy.ndimage import median_filter

    valid = np.isfinite(img)
    if valid.sum() < 50:
        return np.zeros(img.shape, bool)
    sm = median_filter(np.where(valid, img, np.inf), size=5, mode="nearest")
    sm[~valid | ~np.isfinite(sm)] = np.nan
    return valid & (sm <= np.nanpercentile(sm, 100 * frac))

# --- calibration: the official channel definition ---------------------------------------------
def parse_channels(data: bytes) -> dict:
    """The Spectral Channels calibration file: {"map": CHANNEL_MAP (channel index per detector pixel),
    "nchan": NCHAN, "rows": the SPECTRAL_CHANNELS table as a list of dicts}."""
    with fits.open(io.BytesIO(data)) as h:
        table = h["SPECTRAL_CHANNELS"].data
        rows = [{name: table[name][i].item() for name in table.names} for i in range(len(table))]
        return {"map": h["CHANNEL_MAP"].data.copy(), "nchan": int(h[0].header["NCHAN"]), "rows": rows}


def channel_table(rows: list[dict], detector: str, nchan: int) -> list[dict]:
    """One entry per channel of a detector: detector, channel (1-based), wavelength_um, wl_min_um, wl_max_um."""
    by = {(int(r["DETECTOR"]), int(r["SUBCHAN"])): r for r in rows}
    n = int(detector.lstrip("D"))
    return [{"detector": detector, "channel": c, "wavelength_um": _num(by[(n, c)]["WAVELENGTH"], 4),
             "wl_min_um": _num(by[(n, c)]["WL_MIN"], 4), "wl_max_um": _num(by[(n, c)]["WL_MAX"], 4)}
            for c in range(1, nchan + 1)]


def epochs_of(seasons: list[list[spherex.ImageRecord]]) -> list[dict]:
    """Summary of each epoch (= visit): index, start, end, representative time (median), image counts."""
    out = []
    for e, s in enumerate(seasons):
        t = [r.t_mid_mjd for r in s]
        out.append({"index": e, "start": iso_time(min(t)), "end": iso_time(max(t)),
                    "time": iso_time(float(np.median(t))), "n_images": len(s),
                    "images_per_detector": {det: sum(1 for r in s if r.detector == det)
                                            for det in sorted({r.detector for r in s})}})
    return out


# --- per cutout: mask, reproject, channel per pixel --------------------------------------------
def reproject_cutout(hdul: fits.HDUList, record: spherex.ImageRecord, spec: TargetSpec, channel_map: np.ndarray) -> dict:
    """One cutout on the request's north-up grid. Returns arrays (H, W): img (IMAGE - ZODI, NaN where unusable),
    var, chan (official channel index of the detector pixel that saw this sky pixel, -1 outside), and `meta`."""
    from scipy.ndimage import map_coordinates

    hdr = hdul["IMAGE"].header
    img = hdul["IMAGE"].data.astype(np.float64) - hdul["ZODI"].data  # zodiacal light is not pre-subtracted
    var = hdul["VARIANCE"].data.astype(np.float64)
    flags = hdul["FLAGS"].data.astype(np.int64)
    bits = spherex._flag_bits(hdul["FLAGS"].header)  # name -> bit, from this file's own header

    bad = ~np.isfinite(img) | ~np.isfinite(var) | (var <= 0)
    flagged = {}
    for name in BAD_FLAG_NAMES:
        if name in bits:
            m = (flags & (1 << bits[name])) != 0
            flagged[name] = int(m.sum())
            bad |= m

    grid, shape = spherex.north_up_wcs(spec.center, spec.fov_deg, PIXEL_SCALE_ARCSEC / 3600)
    gy, gx = np.mgrid[0 : shape[0], 0 : shape[1]]
    wcs = WCS(hdr)
    px, py = wcs.world_to_pixel(grid.pixel_to_world(gx, gy))  # 0-based cutout pixel of every grid pixel (SIP included)
    px, py = np.asarray(px, float), np.asarray(py, float)
    coords = np.array([py, px])
    out_img = map_coordinates(np.where(bad, np.nan, img), coords, order=1, mode="constant", cval=np.nan)
    out_var = map_coordinates(np.where(bad, np.nan, var), coords, order=1, mode="constant", cval=np.nan)

    # channel of the PARENT detector pixel (tutorial-psf-in-cutouts.md: x_parent = 1 + x_cutout - CRPIX1A, 0-based)
    ix = np.rint(px + 1 - hdr["CRPIX1A"]).astype(int)
    iy = np.rint(py + 1 - hdr["CRPIX2A"]).astype(int)
    inside = (ix >= 0) & (ix < channel_map.shape[1]) & (iy >= 0) & (iy < channel_map.shape[0])
    chan = np.full(shape, -1, np.int16)
    chan[inside] = channel_map[iy[inside], ix[inside]]

    # at the target (= grid centre): wavelength from the spectral WCS, flags within one pixel
    tx, ty = (float(v) for v in wcs.world_to_pixel(spec.center))
    wl = bw = float("nan")
    near: list[str] = []
    jx, jy = int(round(tx)), int(round(ty))
    if 0 <= jy < flags.shape[0] and 0 <= jx < flags.shape[1]:
        spectral = WCS(hdr, fobj=hdul, key="W")
        spectral.sip = None  # required for the spectral WCS (tutorial-intro-spectral-images.md)
        w, b = spectral.pixel_to_world(tx, ty)
        wl, bw = float(w.to("um").value), float(b.to("um").value)
        box = flags[max(jy - 1, 0) : jy + 2, max(jx - 1, 0) : jx + 2]
        near = [n for n, b_ in sorted(bits.items(), key=lambda kv: kv[1]) if n != "SOURCE" and np.any(box & (1 << b_))]

    valid = np.isfinite(out_img) & np.isfinite(out_var)
    bg, _ = clipped_stats(out_img[valid])
    meta = {
        "frame_id": frame_id(record), "file": record.access_url.rsplit("/", 1)[-1], "detector": record.detector,
        "collection": record.collection, "mjd": record.t_mid_mjd, "wavelength_um": _num(wl), "bandwidth_um": _num(bw),
        "flags_near_target": near, "saturated": SATURATION_FLAG in near, "version": str(hdul[0].header.get("VERSION", "")),
        "bunit": str(hdr.get("BUNIT", "")), "background": _num(bg), "valid_fraction": _num(valid.mean(), 4),
        "median_variance": _num(np.median(out_var[valid])) if valid.any() else None,
        "flagged_pixels": flagged, "cutout_pixels": int(flags.size),
    }
    return {"img": out_img.astype(np.float32), "var": out_var.astype(np.float32), "chan": chan, "meta": meta}


# --- step 7a: per channel and epoch -----------------------------------------------------------
def combine_channels(X: np.ndarray, V: np.ndarray, C: np.ndarray, W: np.ndarray, nchan: int):
    """Average exposures per spectral channel. X, V, C: (n, H, W) image, variance, channel index; W: (n,) weight
    of each exposure. Returns I, VV (nchan, H, W; NaN where nothing contributed), N (contributions), n_rejected.

    The weight is ONE number per exposure (1 / its median variance), not per pixel: SPHEREx's variance includes
    the source's own photon noise, so per-pixel inverse-variance weights would favour the exposures in which a
    star happened to be fainter and bias it low, by an amount that depends on how many exposures an epoch has."""
    n, H, Wd = X.shape
    I = np.full((nchan, H, Wd), np.nan, np.float32)
    VV = np.full((nchan, H, Wd), np.nan, np.float32)
    N = np.zeros((nchan, H, Wd), np.uint8)
    rejected = 0
    good = np.isfinite(X) & np.isfinite(V) & (V > 0) & (W[:, None, None] > 0)
    for c in range(1, nchan + 1):
        m = good & (C == c)
        if not m.any():
            continue
        cnt = m.sum(0)
        if (cnt >= OUTLIER_MIN_N).any():
            med = np.nanmedian(np.where(m, X, np.nan), axis=0)
            tol = OUTLIER_SIGMA * np.sqrt(np.where(m, V, 0) + (OUTLIER_REL * med) ** 2)
            rej = m & (cnt >= OUTLIER_MIN_N) & (np.abs(X - med) > tol)
            rejected += int(rej.sum())
            m &= ~rej
        w = m * W[:, None, None]
        sw = w.sum(0)
        ok = sw > 0
        I[c - 1][ok] = ((w * np.where(m, X, 0)).sum(0)[ok] / sw[ok]).astype(np.float32)
        VV[c - 1][ok] = ((w**2 * np.where(m, V, 0)).sum(0)[ok] / sw[ok] ** 2).astype(np.float32)
        N[c - 1] = m.sum(0)
    return I, VV, N, rejected


# --- step 7b-9: bundle channels, background, products ------------------------------------------
def pick_rgb(times: list[float]) -> dict:
    """Which usable epochs go into red/green/blue. `times` = representative time of each usable epoch, sorted.
    Returns positions into `times`."""
    n = len(times)
    if n == 0:
        return {"mode": "no_data", "red": None, "green": None, "blue": None}
    if n == 1:
        return {"mode": "one_epoch", "red": 0, "green": 0, "blue": 0}
    if n == 2:
        return {"mode": "two_epochs", "red": 0, "green": 1, "blue": 1}
    mid = (times[0] + times[-1]) / 2
    g = min(range(1, n - 1), key=lambda i: abs(times[i] - mid))
    return {"mode": "three_epochs", "red": 0, "green": g, "blue": n - 1}


MODE_NOTES = {
    "three_epochs": "Three epochs: the first is red, the one closest to the middle in time is green, the last is blue.",
    "two_epochs": "Only two epochs: the first is red, the second is green and blue (cyan).",
    "one_epoch": "Only one epoch: greyscale image, no comparison over time is possible.",
    "no_data": "No epoch covers this position well enough with this detector: no image.",
}


def asinh_stretch(x: np.ndarray, sigma: float, hi: float) -> np.ndarray:
    """0..1 for display. Sky background (0) is black, noise stays dark, `hi` is white."""
    a = float(np.clip(3 * sigma / hi, 0.003, 0.5))
    t = np.clip(np.nan_to_num(x, nan=0.0) / hi, 0, 1)
    return np.arcsinh(t / a) / np.arcsinh(1 / a)


def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgba[::-1], "RGBA").save(buf, "PNG", optimize=True)  # grid row 0 is south; PNG row 0 is the top
    return buf.getvalue()


def _rgba(channels: list[np.ndarray], valid: np.ndarray) -> np.ndarray:
    out = np.zeros(valid.shape + (4,), np.uint8)
    for i, ch in enumerate(channels):
        out[..., i] = np.where(valid, np.rint(255 * ch), 0)
    out[..., 3] = np.where(valid, 255, 0)  # no coverage -> transparent, not black
    return out


def diff_rgba(z: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Sign-true colours: brighter in the last epoch = blue, fainter = red, unchanged = white. Same convention as the
    epoch RGB (red = earliest, blue = latest): a moving star leaves red where it was and blue where it is now."""
    from matplotlib import colormaps

    t = np.clip(np.nan_to_num(z, nan=0.0) / DIFF_CLIP_SIGMA, -1, 1) * 0.5 + 0.5
    out = np.rint(255 * colormaps["RdBu"](t)).astype(np.uint8)
    out[..., 3] = np.where(valid, 255, 0)
    out[~valid, :3] = 0
    return out


STEP_ARRAY_PREFIX = "diff_s"  # make_bundle's arrays "diff_s0", "diff_s1", ...: the step differences


def pair_difference(B: np.ndarray, BV: np.ndarray, sky: np.ndarray, a: int, b: int) -> tuple[np.ndarray | None, float]:
    """(epoch b - epoch a) / uncertainty, for two usable epochs a < b of a bundle. B, BV: (E, H, W) background-
    subtracted bundle images and their variances; sky: the bundle's source-free pixels. Returns (z as float32, the
    empirical scale), or (None, scale) when the noise cannot be measured.

    The uncertainty has two parts:
     - the propagated variance, times an empirical factor s^2 that makes the pixel-to-pixel scatter of source-free
       pixels 1 (this replaces an exact variance propagation through the reprojection). It is measured per pair on
       the difference minus its 5x5 median, so that a smooth change (the halo of a variable star that fills the
       field, as around R Draconis) is not mistaken for noise;
     - DIFF_RELATIVE_FLOOR times the pixel's brightness (see the setting)."""
    from scipy.ndimage import median_filter

    delta, dv = B[b] - B[a], BV[b] + BV[a]
    z0 = delta / np.sqrt(dv)
    smooth = median_filter(np.where(np.isfinite(z0), z0, 0.0), size=5, mode="nearest")
    _, scale = clipped_stats((z0 - smooth)[sky])
    med, _ = clipped_stats(delta[sky])
    if not (np.isfinite(scale) and scale > 0 and np.isfinite(med)):
        return None, scale
    brightness = (np.abs(B[b]) + np.abs(B[a])) / 2
    z = (delta - med) / np.sqrt(scale**2 * dv + (DIFF_RELATIVE_FLOOR * brightness) ** 2)
    return z.astype(np.float32), scale


def make_bundle(bundle_id: str, kind: str, I: np.ndarray, V: np.ndarray, N: np.ndarray, chan_info: list[dict],
                epochs: list[dict], exposures: list[dict]) -> tuple[dict, dict[str, np.ndarray], dict[str, bytes]]:
    """Bundle channels into one image per epoch and build the products.

    I, V, N: (E, C, H, W) per epoch and channel (step 7a). chan_info: one dict per channel (detector, channel,
    wavelengths). epochs: the request's epochs. exposures: reprojection metadata of every contributing exposure.
    Returns (metadata, arrays, PNG files by name). The arrays "diff_s<k>" (step differences) are for tests and
    scripts; the job layer does not store them, nothing reads them back."""
    E, C, H, W = I.shape
    have = N > 0
    covered = have.reshape(E, C, -1).mean(-1) >= CHANNEL_MIN_FIELD_FRACTION  # (E, C)
    usable = [e for e in range(E) if covered[e].sum() > 0 and covered[e].sum() >= EPOCH_MIN_CHANNEL_FRACTION * C]

    def chan_label(c: int) -> dict:
        return {"detector": chan_info[c]["detector"], "channel": chan_info[c]["channel"]}

    ep_meta = []
    for e in range(E):
        exps = [x for x in exposures if x["epoch"] == e]
        t = sorted(x["mjd"] for x in exps)
        wl = [x["wavelength_um"] for x in exps if x["wavelength_um"] is not None]
        ep_meta.append({
            "index": e, "usable": e in usable, "n_images": len(exps),
            "epoch_start": epochs[e]["start"] if e < len(epochs) else None,  # of the whole epoch (all detectors)
            "epoch_end": epochs[e]["end"] if e < len(epochs) else None,
            "start": iso_time(t[0]) if t else None, "end": iso_time(t[-1]) if t else None,
            "time": iso_time(float(np.median(t))) if t else None, "span_days": _num(t[-1] - t[0], 2) if t else None,
            "channels_covered": [chan_label(c) for c in range(C) if covered[e, c]],
            "channels_missing": [chan_label(c) for c in range(C) if not covered[e, c]],
            "wavelength_at_target_um": {"min": _num(min(wl), 4), "max": _num(max(wl), 4)} if wl else None,
            "saturated_images": sum(1 for x in exps if x["saturated"]),
            "files": sorted(x["file"] for x in exps),
        })
    meta: dict = {"id": bundle_id, "kind": kind, "detectors": sorted({c["detector"] for c in chan_info}),
                  "epochs": ep_meta, "usable_epochs": usable}
    arrays: dict[str, np.ndarray] = {}
    pngs: dict[str, bytes] = {}
    choice = pick_rgb([Time(ep_meta[e]["time"]).mjd for e in usable])
    meta["mode"], meta["note"] = choice["mode"], MODE_NOTES[choice["mode"]]
    if not usable:
        meta.update({"rgb": None, "diff": None, "diff_steps": [], "channels": [], "wavelength_um": None, "gaps": _gaps(meta, None)})
        return meta, arrays, pngs

    # channels that EVERY usable epoch has at a pixel; the same set and the same (equal) weights in all epochs
    common = np.all(have[usable], axis=0)  # (C, H, W)
    # single-channel spikes: compare each channel with the median of its detector's channels at that pixel and
    # epoch; a channel that fails in ANY usable epoch is dropped at that pixel in EVERY epoch
    spike = np.zeros_like(common)
    for det in sorted({c["detector"] for c in chan_info}):
        g = np.array([c["detector"] == det for c in chan_info])
        enough = common[g].sum(0) >= SPIKE_MIN_CHANNELS
        for e in usable:
            Ig = np.where(common[g], I[e][g], np.nan)
            med = np.nanmedian(Ig, axis=0)
            tol = SPIKE_SIGMA * np.sqrt(V[e][g]) + SPIKE_REL * np.abs(med)
            spike[g] |= common[g] & enough & (np.abs(Ig - med) > tol)
    common &= ~spike
    meta["spikes_rejected"] = int(spike.sum())
    K = common.sum(0)  # channels per pixel
    valid = K > 0
    Kd = np.where(valid, K, 1)
    B = np.full((E, H, W), np.nan, np.float32)
    BV = np.full((E, H, W), np.nan, np.float32)
    BN = np.zeros((E, H, W), np.uint16)
    for e in usable:
        B[e] = np.where(valid, np.where(common, I[e], 0).sum(0) / Kd, np.nan)
        BV[e] = np.where(valid, np.where(common, V[e], 0).sum(0) / Kd**2, np.nan)
        BN[e] = np.where(common, N[e], 0).sum(0)

    # step 8: residual background per epoch image = median over source-free pixels (one common set of pixels)
    sky = dark_sky(np.nanmean(B[usable], axis=0)) & valid
    sigmas = []
    for e in usable:
        bg, sig = clipped_stats(B[e][sky])
        if np.isfinite(bg):
            B[e] -= bg
        ep_meta[e]["background"], ep_meta[e]["noise"] = _num(bg), _num(sig)
        sigmas.append(sig)
    sigma = float(np.nanmax(sigmas)) if np.any(np.isfinite(sigmas)) else float("nan")

    # step 9: ONE stretch for all epochs of the bundle
    vals = B[usable][:, valid]
    hi = float(np.nanpercentile(vals, STRETCH_HI_PERCENTILE)) if vals.size else float("nan")
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = float(np.nanstd(vals)) if vals.size else 1.0
    if not np.isfinite(hi) or hi < 10 * sigma:
        hi = 10 * sigma
    S = {e: asinh_stretch(B[e], sigma, hi) for e in usable}
    for e in usable:
        pngs[f"frame_{bundle_id}_e{e}.png"] = _png(_rgba([S[e]] * 3, valid))
    r, g, b = (usable[choice[k]] for k in ("red", "green", "blue"))
    pngs[f"rgb_{bundle_id}.png"] = _png(_rgba([S[r], S[g], S[b]], valid))
    meta["rgb"] = {k: {"epoch": e, "time": ep_meta[e]["time"], "start": ep_meta[e]["start"], "end": ep_meta[e]["end"]}
                   for k, e in (("red", r), ("green", g), ("blue", b))}

    def ref(e: int) -> dict:
        return {"epoch": e, "time": ep_meta[e]["time"]}

    # "Total": last minus first usable epoch (the default picture)
    meta["diff"] = None
    if len(usable) >= 2:
        first, last = usable[0], usable[-1]
        z, scale = pair_difference(B, BV, sky, first, last)
        if z is not None:
            arrays["diff"] = z
            pngs[f"diff_{bundle_id}.png"] = _png(diff_rgba(z, valid & np.isfinite(z)))
            meta["diff"] = {"first": ref(first), "last": ref(last),
                            "definition": "(last - first) / combined uncertainty; the noise part is scaled so that the pixel-to-pixel scatter of source-free pixels is 1. "
                                          f"The uncertainty includes {100 * DIFF_RELATIVE_FLOOR:.0f} % of the pixel's brightness "
                                          "(unchanged stars differ that much between epochs)",
                            "relative_floor": DIFF_RELATIVE_FLOOR,
                            "empirical_scale": _num(scale, 4), "clip_sigma": DIFF_CLIP_SIGMA,
                            "colours": "blue = brighter in the last epoch, red = fainter (brighter in the first), white = unchanged"}

    # steps: each pair of NEIGHBOURING usable epochs (an unusable epoch in between is skipped), same colour scale.
    # Step k keeps its number even if its difference cannot be computed ("available": false).
    meta["diff_steps"] = []
    for k, (a, b) in enumerate(zip(usable, usable[1:])):
        z, scale = pair_difference(B, BV, sky, a, b)
        step = {"step": k, "first": ref(a), "last": ref(b), "available": z is not None,
                "empirical_scale": _num(scale, 4) if z is not None else None}
        if z is not None:
            arrays[f"{STEP_ARRAY_PREFIX}{k}"] = z  # for tests and scripts; not stored (see analysis_jobs._store_bundle)
            pngs[f"diff_{bundle_id}_s{k}.png"] = _png(diff_rgba(z, valid & np.isfinite(z)))
        meta["diff_steps"].append(step)

    used = [c for c in range(C) if common[c].any()]
    meta["channels"] = [chan_info[c] for c in used]
    meta["channels_excluded"] = [chan_label(c) for c in range(C) if c not in used]
    meta["wavelength_um"] = ({"min": _num(min(chan_info[c]["wl_min_um"] for c in used), 4),
                              "max": _num(max(chan_info[c]["wl_max_um"] for c in used), 4)} if used else None)
    meta["stretch"] = {"kind": "asinh", "black": 0.0, "white": _num(hi), "noise": _num(sigma),
                       "unit": next((x["bunit"] for x in exposures if x.get("bunit")), None)}
    meta["n"] = {"per_epoch": {str(e): {"min": int(BN[e][valid].min()), "median": _num(np.median(BN[e][valid]), 1),
                                        "max": int(BN[e][valid].max())} for e in usable if valid.any()},
                 "channels_per_pixel": {"min": int(K[valid].min()), "median": _num(np.median(K[valid]), 1),
                                        "max": int(K[valid].max())} if valid.any() else None}
    meta["covered_fraction"] = _num(valid.mean(), 4)
    meta["gaps"] = _gaps(meta, float(valid.mean()))
    arrays.update({"image": B, "variance": BV, "n": BN, "channels_per_pixel": K.astype(np.uint8), "sky": sky})
    return meta, arrays, pngs


def ramp_colour(t: float) -> tuple[float, float, float]:
    """The colour of position t (0 = shortest wavelength, 1 = longest) on COLOUR_RAMP, linearly interpolated."""
    t = float(np.clip(t, 0.0, 1.0))
    for (t0, c0), (t1, c1) in zip(COLOUR_RAMP, COLOUR_RAMP[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(float(a + f * (b - a)) for a, b in zip(c0, c1))
    return COLOUR_RAMP[-1][1]


def _hex(rgb) -> str:
    return "#" + "".join(f"{int(round(255 * float(np.clip(v, 0, 1)))):02x}" for v in rgb)


def _filled(have: np.ndarray, size: int) -> np.ndarray:
    """`have` with its small holes closed (dilation, then erosion). The straight edges of a channel's footprint
    stay where they are; holes smaller than about `size` px (a saturated star core, a flagged pixel) are filled.
    Padded with the edge values first, so the picture's border is not eaten."""
    from scipy.ndimage import binary_closing

    r = size // 2 + 1
    p = np.pad(have, r, mode="edge")
    return binary_closing(p, structure=np.ones((size, size), bool))[r:-r, r:-r] | have


def colour_composite(I: np.ndarray, V: np.ndarray, N: np.ndarray, chan_info: list[dict], epochs: list[dict]
                     ) -> tuple[dict, dict[str, np.ndarray], dict[str, bytes]]:
    """Every wavelength of one epoch in one colour picture, for every epoch that covers enough channels.

    I, V, N: (E, C, H, W) per epoch and channel of ALL detectors (step 7a), sky-subtracted per exposure.
    chan_info: one dict per channel (detector, channel, wavelengths). epochs: the request's epochs.

    1. Each channel gets a colour from COLOUR_RAMP by log(wavelength): short = blue, long = red. Each of r, g, b
       is a weighted mean of the channels, the weights normalised so that a spectrum flat in MJy/sr is grey.
    2. Only channels the epoch covers (CHANNEL_MIN_FIELD_FRACTION of the field) are used. Single-channel spikes
       (cosmic-ray hits or bad pixels the flags missed, as in make_bundle) are dropped. A pixel inside a
       channel's footprint without data there was masked by its flags (saturated, hot, cosmic ray, ...; see
       BAD_FLAG_NAMES). Small gaps are bridged by the other channels; if r, g or b loses more than
       1 - COLOUR_MIN_WEIGHT of its expected weight, the pixel is masked (COLOUR_MASK_RGB): its colour would
       be wrong, e.g. a saturated star core would turn red because only the long wavelengths are left.
    3. White balance: r, g, b are scaled so that the brightest pixels (the stars) are white on average.
       Unusual colours then mean an unusual spectrum: red = brighter at long wavelengths than a typical star.
    4. ONE brightness stretch (asinh) for every epoch, on the brightness (r + g + b) / 3; the colour of each
       pixel is kept. Faint pixels fade to grey, so sky noise does not become coloured speckle.
    Returns (metadata, arrays, PNG files by name "colour_e<epoch>.png")."""
    E, C, H, W = I.shape
    wl = np.array([c["wavelength_um"] if c.get("wavelength_um") is not None else
                   0.5 * (c["wl_min_um"] + c["wl_max_um"]) for c in chan_info], float)
    lo, hi_wl = float(np.nanmin(wl)), float(np.nanmax(wl))
    t = (np.log(wl) - np.log(lo)) / max(np.log(hi_wl) - np.log(lo), 1e-9)
    ramp = np.array([ramp_colour(x) for x in t])  # (C, 3): the colour shown for each channel
    weights = ramp / ramp.sum(0)  # each of r, g, b: weights summing to 1 over all channels

    have = (N > 0) & np.isfinite(I)
    covered = have.reshape(E, C, -1).mean(-1) >= CHANNEL_MIN_FIELD_FRACTION  # (E, C)
    # single-channel spikes: further from the median of the detector's channels at that pixel than its noise and
    # SPIKE_REL times that median allow (the same test as make_bundle's); dropped like a flagged pixel
    dets = np.array([c["detector"] for c in chan_info])
    spikes = 0
    for e in range(E):
        for det in np.unique(dets):
            g = dets == det
            h = have[e, g]
            enough = h.sum(0) >= SPIKE_MIN_CHANNELS
            Ig = np.where(h, I[e, g], np.nan)
            med = np.nanmedian(Ig, axis=0)
            with np.errstate(invalid="ignore"):
                spike = h & enough & (np.abs(Ig - med) > SPIKE_SIGMA * np.sqrt(V[e, g]) + SPIKE_REL * np.abs(med))
            spikes += int(spike.sum())
            have[e, g] = h & ~spike
    usable = [e for e in range(E) if covered[e].sum() > 0 and covered[e].sum() >= COLOUR_MIN_CHANNEL_FRACTION * C]

    comp = np.full((E, 3, H, W), np.nan, np.float32)
    masked = np.zeros((E, H, W), bool)
    nodata = np.ones((E, H, W), bool)
    for e in usable:
        cs = np.flatnonzero(covered[e])
        h = have[e, cs]
        fp = np.stack([_filled(h[i], COLOUR_HOLE_SIZE) for i in range(len(cs))])
        w = weights[cs]  # (k, 3)
        expected = np.einsum("kc,khw->chw", w, fp.astype(np.float64))
        got = np.einsum("kc,khw->chw", w, h.astype(np.float64))
        num = np.einsum("kc,khw->chw", w, np.where(h, I[e, cs], 0.0).astype(np.float64))
        nodata[e] = (expected <= 1e-6).any(0)
        frac = np.where(expected > 1e-6, got / np.maximum(expected, 1e-12), 0.0)
        bad = ~nodata[e] & (frac < COLOUR_MIN_WEIGHT).any(0)
        if bad.any():
            from scipy.ndimage import binary_dilation

            bad = binary_dilation(bad, iterations=1) & ~nodata[e]  # the rim of a hole is part-saturated too
        masked[e] = bad
        with np.errstate(invalid="ignore", divide="ignore"):
            comp[e] = np.where(got > 0, num / got, np.nan).astype(np.float32)
        comp[e][:, nodata[e] | bad] = np.nan

    meta: dict = {"spikes_rejected": spikes, "palette": [{"detector": c["detector"], "channel": c["channel"], "wavelength_um": _num(wl[i], 4),
                               "wl_min_um": c.get("wl_min_um"), "wl_max_um": c.get("wl_max_um"), "colour": _hex(ramp[i])}
                              for i, c in enumerate(chan_info)],
                  "mask_colour": _hex(np.array(COLOUR_MASK_RGB) / 255), "usable_epochs": usable, "epochs": []}
    arrays: dict[str, np.ndarray] = {}
    pngs: dict[str, bytes] = {}

    def epoch_meta(e: int) -> dict:
        ep = epochs[e] if e < len(epochs) else {}
        valid = ~nodata[e]
        return {"index": e, "usable": e in usable, "start": ep.get("start"), "end": ep.get("end"), "time": ep.get("time"),
                "channels_covered": [bool(x) for x in covered[e]], "n_channels": int(covered[e].sum()),
                "masked_fraction": _num(masked[e][valid].mean(), 4) if e in usable and valid.any() else None,
                "covered_fraction": _num(valid.mean(), 4) if e in usable else None}

    if not usable:
        meta.update({"epochs": [epoch_meta(e) for e in range(E)], "white_balance": None, "stretch": None,
                      "note": "No epoch covers enough wavelengths for a colour picture."})
        return meta, arrays, pngs

    # sky level per epoch and colour, on one common set of source-free pixels (as in make_bundle, step 8)
    lum = np.nanmean(comp[usable], axis=(0, 1))
    sky = dark_sky(lum)
    for e in usable:
        for k in range(3):
            bg, _ = clipped_stats(comp[e, k][sky])
            if np.isfinite(bg):
                comp[e, k] -= bg

    # white balance on the brightest pixels of every epoch together: the same factors for every epoch
    L = comp[usable].mean(1)  # (U, H, W)
    vals = L[np.isfinite(L)]
    gains = np.ones(3)
    if vals.size >= 50:
        cut = np.percentile(vals, COLOUR_BALANCE_PERCENTILE)
        bright = np.isfinite(L) & (L > cut) & (L > 0)
        if bright.sum() >= 10:
            ratios = [np.median(comp[usable][:, k][bright] / L[bright]) for k in range(3)]
            if all(np.isfinite(r) and r > 0 for r in ratios):
                gains = 1.0 / np.array(ratios)
    comp *= gains[None, :, None, None].astype(np.float32)

    # one stretch for every epoch, on the brightness
    L = comp[usable].mean(1)
    sigmas = [clipped_stats(L[i][sky])[1] for i in range(len(usable))]
    sigma = float(np.nanmax(sigmas)) if np.any(np.isfinite(sigmas)) else float("nan")
    vals = L[np.isfinite(L)]
    white = float(np.percentile(vals, STRETCH_HI_PERCENTILE)) if vals.size else float("nan")
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = float(np.nanstd(vals)) if vals.size else 1.0
    if not np.isfinite(white) or white < 10 * sigma:
        white = 10 * sigma

    lo_c, hi_c = COLOUR_CHROMA_SIGMA
    for e in usable:
        c3 = np.nan_to_num(comp[e], nan=0.0)
        lum_e = c3.mean(0)
        s = asinh_stretch(lum_e, sigma, white)  # 0..1 brightness on screen
        with np.errstate(invalid="ignore", divide="ignore"):
            scale = np.where(lum_e > 0, s / lum_e, 0.0)
        rgb = np.clip(c3 * scale, 0, None)
        chroma = np.clip((lum_e / sigma - lo_c) / (hi_c - lo_c), 0, 1)
        rgb = s + chroma * (rgb - s)  # faint pixels: grey of the same brightness
        top = rgb.max(0)
        rgb = np.where(top > 1, rgb / np.maximum(top, 1e-12), rgb)  # too bright: keep the hue, not clip to white
        out = np.zeros((H, W, 4), np.uint8)
        valid = ~nodata[e]
        for k in range(3):
            out[..., k] = np.where(valid, np.rint(255 * np.clip(rgb[k], 0, 1)), 0)
        out[..., 3] = np.where(valid, 255, 0)  # no data: transparent
        out[masked[e]] = (*COLOUR_MASK_RGB, 255)
        pngs[f"colour_e{e}.png"] = _png(out)
    arrays["colour"] = comp

    meta.update({"epochs": [epoch_meta(e) for e in range(E)], "white_balance": [_num(g, 4) for g in gains],
                 "stretch": {"kind": "asinh", "black": 0.0, "white": _num(white), "noise": _num(sigma)},
                 "note": "Every wavelength of one season in one picture: short wavelengths blue, long ones red, "
                         "balanced so that typical stars are white. One brightness scale for every season. "
                         "Grey pixels are masked (saturated or flagged in some wavelengths); transparent = no data."})
    return meta, arrays, pngs


def _gaps(meta: dict, covered: float | None) -> list[str]:
    """Coverage gaps as plain sentences, for the explanation next to the picture. All from the data."""
    out = []
    for ep in meta["epochs"]:
        start, end = ep["start"] or ep.get("epoch_start"), ep["end"] or ep.get("epoch_end")
        label = f"Epoch {start[:10]} to {end[:10]}" if start else f"Epoch with index {ep['index']}"
        if ep["n_images"] == 0:
            out.append(f"{label}: no images from this detector.")
        elif not ep["usable"]:
            out.append(f"{label}: not used, it covers only {len(ep['channels_covered'])} of "
                       f"{len(ep['channels_covered']) + len(ep['channels_missing'])} spectral channels.")
        elif ep["channels_missing"]:
            miss = ", ".join(f"{c['detector']}/{c['channel']}" for c in ep["channels_missing"])
            out.append(f"{label}: spectral channels without data: {miss}. They are left out of every epoch.")
        if ep["usable"] and ep.get("saturated_images"):
            out.append(f"{label}: the target is saturated in {ep['saturated_images']} of {ep['n_images']} images; "
                       f"saturated pixels are left out (transparent).")
    if covered is not None and covered < 0.999:
        out.append(f"{100 * (1 - covered):.0f} % of the picture has no data in at least one epoch and is transparent.")
    return out



def average_detector(exposures: list[dict], load: Callable[[str], tuple[np.ndarray, np.ndarray, np.ndarray]],
                     n_epochs: int, nchan: int, shape: tuple[int, int]):
    """Step 7a for one detector: (I, V, N) of shape (epochs, channels, H, W), the sky pixels used, the number of
    rejected outliers, the exposures that contributed, and the dropped ones. `exposures` are reproject_cutout
    metadata plus "epoch"; `load(frame_id)` returns that exposure's (img, var, chan) arrays."""
    I = np.full((n_epochs, nchan) + shape, np.nan, np.float32)
    V = np.full_like(I, np.nan)
    N = np.zeros(I.shape, np.uint8)
    rejected = 0
    dropped = []
    # per-exposure sky level (IMAGE - ZODI leaves an offset that differs from exposure to exposure):
    # the median over ONE set of sky pixels, the same for every exposure and epoch of the detector
    usable_x = [x for x in exposures if x["background"] is not None and x["median_variance"]]
    arrs = {x["frame_id"]: load(x["frame_id"]) for x in usable_x}
    sky = np.zeros(shape, bool)
    if usable_x:
        sky = dark_sky(np.nanmedian(np.stack([arrs[x["frame_id"]][0] - x["background"] for x in usable_x]), axis=0))
    for x in usable_x:
        v = arrs[x["frame_id"]][0][sky]
        v = v[np.isfinite(v)]
        x["sky_level"] = _num(np.median(v)) if v.size >= max(20, 0.3 * sky.sum()) else None
        if x["sky_level"] is None:
            dropped.append({"frame_id": x["frame_id"], "reason": "too few sky pixels to measure the background"})
    for e in range(n_epochs):
        ex_e = [x for x in usable_x if x["epoch"] == e and x["sky_level"] is not None]
        if not ex_e:
            continue
        a = [arrs[x["frame_id"]] for x in ex_e]
        X = np.stack([ai[0] - x["sky_level"] for ai, x in zip(a, ex_e)])
        W = np.array([1.0 / x["median_variance"] for x in ex_e])
        I[e], V[e], N[e], rej = combine_channels(X, np.stack([ai[1] for ai in a]), np.stack([ai[2] for ai in a]), W, nchan)
        rejected += rej
    used = [x for x in exposures if x.get("sky_level") is not None]
    return I, V, N, sky, rejected, used, dropped
