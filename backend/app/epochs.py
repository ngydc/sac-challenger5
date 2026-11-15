"""Epoch maps: for one sky position, one averaged image per observing epoch and per detector, and from
those an epoch RGB and a difference image per detector.

Docs used (CLAUDE.md rule):
- docs/spherex/user-guide-data-access.md       SIA2 collections, directory layout of calibration products
- docs/spherex/irsa-cutout-service.md          cutouts keep the parent image's orientation, HTTP 500 = outside
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

Everything is cached as files under backend/cache/ (layout: see "cache layout" below): the five test
targets permanently, other positions temporarily. Only `run` talks to IRSA; `status`, `bundle_meta`, `load_png`
and `spectrum` read files only.
"""
from __future__ import annotations

import functools
import io
import json
import logging
import os
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import httpx
import numpy as np
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

from . import spherex
from .service import PIXEL_SCALE_ARCSEC, WORKERS, ApiError, TargetSpec

log = logging.getLogger("spherex.epochs")

# --- settings -------------------------------------------------------------------------------
DEFAULT_FOV_DEG = 0.08  # THE default field of view of the epoch maps (API default and precompute both use this)
EPOCH_GAP_DAYS = float(os.environ.get("SPHEREX_EPOCH_GAP_DAYS", "30"))  # a longer gap between images starts a new epoch
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
STATUS_STALE_S = 180.0  # a "running" status file not updated for this long belongs to a dead process
SKY_FRACTION = 0.1  # the darkest 10 % of the field count as sky (see `dark_sky`)
REPROJ_VERSION = 1  # bump when `reproject_cutout` changes: cached reprojections are then redone
PIPELINE_VERSION = 8  # bump when anything after the reprojection changes: products are then redone

# Flags that make a pixel unusable here, by NAME (bit numbers come from each file's FLAGS header).
# Chosen from Table 16 of the Explanatory Supplement: everything described as unusable, erroneous, saturated
# or an artifact. Deliberately not included: SOURCE (set on most pixels), FULLSAMPLE's neighbours etc. are
# not flags; HALO ("caution recommended") and CROSSTALK (percent-level) are kept; GHOST_FPA and GHOST_EXT
# are described as unused / in development.
BAD_FLAG_NAMES = ("TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "DICHROIC", "MISSING_DATA", "HOT", "COLD",
                  "FULLSAMPLE", "PHANMISS", "NONLINEAR", "PERSIST", "OUTLIER", "GHOST", "STREAK", "BLOOM",
                  "SNOWBALL", "SATELLITE_HALO")
SATURATION_FLAG = "OVERFLOW"  # Table 16: "overflow threshold reached", about half of full-well saturation

CACHE_ROOT = Path(os.environ.get("SPHEREX_CACHE_DIR", Path(__file__).resolve().parents[1] / "cache"))
warnings.filterwarnings("ignore", message=".*All-NaN slice.*")
warnings.filterwarnings("ignore", message=".*Mean of empty slice.*")


# --- small helpers --------------------------------------------------------------------------
def spec_for(ra: str | float, dec: str | float, fov: float | None) -> TargetSpec:
    return TargetSpec.build(str(ra), str(dec), DEFAULT_FOV_DEG if fov is None else fov, None, None, None)


# --- cache layout ---------------------------------------------------------------------------
# <cache>/examples/<target>/   the five challenge test targets: permanent, never cleaned up
# <cache>/temp/<target>/       every other position: removed after TEMP_TTL_HOURS without use, and oldest
#                              first when the temp cache grows beyond TEMP_MAX_MB (see `cleanup_temp`)
# <target> = ra<deg>_dec<deg>_fov<deg>, so a result is found by target and field of view. Inside:
#   target.json, search.json, status.json
#   cutouts/<obs_id>-<detector>.fits            raw data: every cutout of every detector and epoch
#   reproj/<reproj key>/<obs_id>-<detector>.npz one exposure on the common grid: image, variance, channel per
#                                               pixel (mask = NaN), with wavelength, time, flags as metadata
#   products/<kind>/<parameter key>/            results of one kind of computation with one set of parameters
#       params.json                             the parameters behind the key, readable
#       (kind "epochmaps":) meta.json, channels_<det>.npz (maps per channel and epoch), bundle_<id>.npz,
#       frame_*.png, rgb_*.png, diff_*.png, spectrum/x<x>_y<y>.json
# A new kind of computation gets its own products/<kind>/ and reads cutouts/ or reproj/: no new download.
EXAMPLE_MATCH_DEG = 1e-4  # a position this close to a test target's position counts as that example
TEMP_TTL_HOURS = float(os.environ.get("SPHEREX_TEMP_CACHE_TTL_HOURS", "72"))
TEMP_MAX_MB = float(os.environ.get("SPHEREX_TEMP_CACHE_MAX_MB", "2000"))


@functools.lru_cache(maxsize=4096)
def example_of(spec: TargetSpec):
    """The challenge test target this position belongs to (app/presets.py), or None."""
    from . import presets, resolver

    for p in presets.PRESETS:
        r = resolver.resolve(p.name)  # a preset: answered locally, no network
        if abs(r.dec - spec.dec) < EXAMPLE_MATCH_DEG and \
                abs((r.ra - spec.ra + 180) % 360 - 180) * np.cos(np.radians(spec.dec)) < EXAMPLE_MATCH_DEG:
            return p
    return None


def _dir(spec: TargetSpec) -> Path:
    tier = "examples" if example_of(spec) is not None else "temp"
    return CACHE_ROOT / tier / f"ra{spec.ra:.6f}_dec{spec.dec:+.6f}_fov{spec.fov_deg:.5f}"


def params_key(params: dict) -> str:
    import hashlib

    return hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]


def reproj_params() -> dict:
    return {"reproj_version": REPROJ_VERSION, "bad_flags": list(BAD_FLAG_NAMES), "pixel_scale_arcsec": PIXEL_SCALE_ARCSEC}


def epochmap_params() -> dict:
    """Everything that changes the epoch maps. A different value gives a different products directory."""
    return {"pipeline_version": PIPELINE_VERSION, "reproj": reproj_params(), "epoch_gap_days": EPOCH_GAP_DAYS,
            "outlier": [OUTLIER_MIN_N, OUTLIER_SIGMA, OUTLIER_REL], "sky_fraction": SKY_FRACTION,
            "spike": [SPIKE_MIN_CHANNELS, SPIKE_SIGMA, SPIKE_REL],
            "channel_min_field_fraction": CHANNEL_MIN_FIELD_FRACTION, "epoch_min_channel_fraction": EPOCH_MIN_CHANNEL_FRACTION,
            "diff": [DIFF_CLIP_SIGMA, DIFF_RELATIVE_FLOOR], "stretch_hi_percentile": STRETCH_HI_PERCENTILE}


def product_dir(spec: TargetSpec, kind: str, params: dict) -> Path:
    """Where the results of one kind of computation with one set of parameters live (created with params.json)."""
    d = _dir(spec) / "products" / kind / params_key(params)
    if not (d / "params.json").exists():
        _write_json(d / "params.json", params)
    return d


def _products(spec: TargetSpec) -> Path:
    return _dir(spec) / "products" / "epochmaps" / params_key(epochmap_params())


def _reproj_dir(spec: TargetSpec) -> Path:
    return _dir(spec) / "reproj" / params_key(reproj_params())


def _touch(spec: TargetSpec) -> None:
    """Remember that this position was used (the temp cache expires by last use)."""
    d = _dir(spec)
    if d.exists():
        (d / ".used").touch()


def cleanup_temp() -> list[str]:
    """Remove expired positions from the TEMP cache, then the least recently used ones until it fits
    TEMP_MAX_MB. Never looks outside <cache>/temp, so the examples cannot be touched. Returns what was removed."""
    import shutil

    root = CACHE_ROOT / "temp"
    if not root.is_dir():
        return []
    entries = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        st = _read_json(d / "status.json")
        if st and st.get("state") == "running" and time.time() - st.get("updated", 0) < STATUS_STALE_S:
            continue  # being computed right now
        used = max((p.stat().st_mtime for p in (d / ".used", d / "status.json") if p.exists()), default=d.stat().st_mtime)
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        entries.append((used, size, d))
    removed = []
    total = sum(e[1] for e in entries)
    for used, size, d in sorted(entries, key=lambda e: e[0]):  # least recently used first
        if time.time() - used > TEMP_TTL_HOURS * 3600 or total > TEMP_MAX_MB * 1e6:
            shutil.rmtree(d, ignore_errors=True)
            total -= size
            removed.append(d.name)
    if removed:
        log.info("temp cache: removed %s", removed)
    return removed


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(json.dumps(data, indent=1, allow_nan=False, default=_json_default), encoding="utf-8")
    os.replace(tmp, path)


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(type(o))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _num(x, digits: int = 6):
    """A float for JSON: None instead of NaN/inf."""
    x = float(x)
    return round(x, digits) if np.isfinite(x) else None


def iso_date(mjd: float) -> str:
    return Time(mjd, format="mjd").iso[:10]


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
class FileCalibCache:
    """Calibration files on disk under <cache>/calib/<s3 key> (implements spherex.CalibrationCache)."""

    def __init__(self, root: Path | None = None):
        self.root = root or CACHE_ROOT / "calib"

    def calibration(self, s3_key: str) -> bytes | None:
        p = self.root / s3_key
        return p.read_bytes() if p.exists() else None

    def put_calibration(self, s3_key: str, data: bytes) -> None:
        p = self.root / s3_key
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)


def load_channels(release: str, client: httpx.Client, cache: FileCalibCache | None = None) -> dict:
    """The Spectral Channels calibration product of a release (newest version in the public bucket):
    {"map": CHANNEL_MAP (2040 x 2040, channel index per detector pixel), "nchan": NCHAN,
     "rows": SPECTRAL_CHANNELS table as a list of dicts, "file": s3 key}."""
    cache = cache or FileCalibCache()
    resp = client.get(spherex.S3_BUCKET_URL, params={"list-type": "2", "prefix": f"{release}/spectral_channels/"})
    resp.raise_for_status()
    keys = sorted(k for k in spherex._xml_values(resp.text, "Key") if k.endswith(".fits"))
    if not keys:
        raise FileNotFoundError(f"no spectral channels file for release {release}")
    data = cache.calibration(keys[-1])
    if data is None:
        data = client.get(f"{spherex.S3_BUCKET_URL}/{keys[-1]}").raise_for_status().content
        cache.put_calibration(keys[-1], data)
    with fits.open(io.BytesIO(data)) as h:
        table = h["SPECTRAL_CHANNELS"].data
        rows = [{name: table[name][i].item() for name in table.names} for i in range(len(table))]
        return {"map": h["CHANNEL_MAP"].data.copy(), "nchan": int(h[0].header["NCHAN"]), "rows": rows, "file": keys[-1]}


# --- per cutout: mask, reproject, channel per pixel --------------------------------------------
def frame_id(r: spherex.ImageRecord) -> str:
    return f"{r.obs_id}-{r.detector}"


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


def make_bundle(bundle_id: str, kind: str, I: np.ndarray, V: np.ndarray, N: np.ndarray, chan_info: list[dict],
                epochs: list[dict], exposures: list[dict]) -> tuple[dict, dict[str, np.ndarray], dict[str, bytes]]:
    """Bundle channels into one image per epoch and build the products.

    I, V, N: (E, C, H, W) per epoch and channel (step 7a). chan_info: one dict per channel (detector, channel,
    wavelengths). epochs: the request's epochs. exposures: reprojection metadata of every contributing exposure.
    Returns (metadata, arrays to store, PNG files by name)."""
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
        meta.update({"rgb": None, "diff": None, "channels": [], "wavelength_um": None, "gaps": _gaps(meta, None)})
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

    meta["diff"] = None
    if len(usable) >= 2:
        first, last = usable[0], usable[-1]
        # (last - first) / uncertainty. The uncertainty has two parts:
        #  - the propagated variance, times an empirical factor s^2 that makes the pixel-to-pixel scatter of
        #    source-free pixels 1 (this replaces an exact variance propagation through the reprojection). It is
        #    measured on the difference minus its 5x5 median, so that a smooth change (the halo of a variable
        #    star that fills the field, as around R Draconis) is not mistaken for noise;
        #  - DIFF_RELATIVE_FLOOR times the pixel's brightness (see the setting).
        from scipy.ndimage import median_filter

        delta, dv = B[last] - B[first], BV[last] + BV[first]
        z0 = delta / np.sqrt(dv)
        smooth = median_filter(np.where(np.isfinite(z0), z0, 0.0), size=5, mode="nearest")
        _, scale = clipped_stats((z0 - smooth)[sky])
        med, _ = clipped_stats(delta[sky])
        if np.isfinite(scale) and scale > 0 and np.isfinite(med):
            brightness = (np.abs(B[last]) + np.abs(B[first])) / 2
            z = (delta - med) / np.sqrt(scale**2 * dv + (DIFF_RELATIVE_FLOOR * brightness) ** 2)
            arrays["diff"] = z.astype(np.float32)
            pngs[f"diff_{bundle_id}.png"] = _png(diff_rgba(z, valid & np.isfinite(z)))
            meta["diff"] = {"first": {"epoch": first, "time": ep_meta[first]["time"]},
                            "last": {"epoch": last, "time": ep_meta[last]["time"]},
                            "definition": "(last - first) / combined uncertainty; the noise part is scaled so that the pixel-to-pixel scatter of source-free pixels is 1. "
                                          f"The uncertainty includes {100 * DIFF_RELATIVE_FLOOR:.0f} % of the pixel's brightness "
                                          "(unchanged stars differ that much between epochs)",
                            "relative_floor": DIFF_RELATIVE_FLOOR,
                            "empirical_scale": _num(scale, 4), "clip_sigma": DIFF_CLIP_SIGMA,
                            "colours": "blue = brighter in the last epoch, red = fainter (brighter in the first), white = unchanged"}

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


# --- the pipeline -----------------------------------------------------------------------------
class Progress:
    """Status file of a running computation; readable by any process (API server, precompute)."""

    def __init__(self, spec: TargetSpec):
        self.path = _dir(spec) / "status.json"
        self.data = {"state": "running", "stage": "searching", "done": 0, "total": 0, "bundles_ready": [],
                     "message": None, "started": time.time(), "updated": time.time(), "pid": os.getpid()}
        self._last = 0.0
        self._lock = threading.Lock()
        self.write(force=True)

    def write(self, force: bool = False, **kw) -> None:
        with self._lock:
            self.data.update(kw)
            self.data["updated"] = time.time()
            if force or time.time() - self._last > 1.0:
                self._last = time.time()
                _write_json(self.path, self.data)

    def step(self) -> None:
        with self._lock:
            self.data["done"] += 1
        self.write()


def _collections() -> list[str]:
    """The SPHEREx SIA2 collections to search: IRSA's own list (new releases appear by themselves). The last
    list is kept in a file and used when IRSA's list service is down. SPHEREX_COLLECTIONS (comma-separated)
    overrides both."""
    env = os.environ.get("SPHEREX_COLLECTIONS")
    if env:
        return [c.strip() for c in env.split(",") if c.strip()]
    path = CACHE_ROOT / "collections.json"
    try:
        names = spherex.spherex_collections()
        _write_json(path, {"collections": names, "fetched_at": time.time()})
        return names
    except Exception as err:  # noqa: BLE001
        saved = _read_json(path)
        if saved and saved.get("collections"):
            log.warning("IRSA collection list unavailable (%s), using the last known one", str(err)[:80])
            return saved["collections"]
        raise


def _search(spec: TargetSpec) -> dict:
    last: Exception | None = None
    for attempt in range(5):  # IRSA's search answers 502 now and then
        try:
            cols = _collections()
            recs = spherex.search(spec.center, cols)
            break
        except Exception as err:  # noqa: BLE001
            last = err
            log.warning("search failed (attempt %d): %s", attempt + 1, str(err)[:120])
            time.sleep(5 * 2**attempt)
    else:
        raise ApiError(502, "irsa_unavailable", f"IRSA search failed: {str(last)[:160]}")
    recs = spherex.filter_records(recs, spec.center, min_edge_margin_deg=0.0)  # the target is inside the image
    return {"collections": cols, "searched_at": time.time(), "records": [asdict(r) for r in recs]}


def _fetch_and_reproject(spec: TargetSpec, rec: spherex.ImageRecord, client: httpx.Client, channel_map: np.ndarray) -> dict:
    """Cutout (cached as a FITS file) -> reprojected arrays (cached as .npz). Returns the exposure's metadata,
    or {"failed": reason}."""
    out = _reproj_dir(spec) / f"{frame_id(rec)}.npz"
    if out.exists():
        with np.load(out) as z:
            return json.loads(str(z["meta"]))
    fpath = _dir(spec) / "cutouts" / f"{frame_id(rec)}.fits"  # raw data, kept (without the PSF table)
    if fpath.with_suffix(".outside").exists():
        return {"failed": "outside", "frame_id": frame_id(rec)}
    if not fpath.exists():
        try:
            data = spherex.download_cutout(rec, spec.center, spec.cutout_size, client)
        except spherex.OutsideImageError:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.with_suffix(".outside").touch()
            return {"failed": "outside", "frame_id": frame_id(rec)}
        except Exception as err:  # noqa: BLE001 - retried by the next compute
            return {"failed": f"download: {str(err)[:150]}", "frame_id": frame_id(rec), "retry": True}
        fpath.parent.mkdir(parents=True, exist_ok=True)
        tmp = fpath.with_suffix(f".part{threading.get_ident()}")
        tmp.write_bytes(data)
        os.replace(tmp, fpath)
    try:
        with fits.open(fpath) as hdul:
            res = reproject_cutout(hdul, rec, spec, channel_map)
    except Exception as err:  # noqa: BLE001
        log.exception("processing %s failed", fpath)
        return {"failed": f"processing: {str(err)[:150]}", "frame_id": frame_id(rec)}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + f".part{threading.get_ident()}.npz")
    np.savez_compressed(tmp, img=res["img"], var=res["var"], chan=res["chan"], meta=json.dumps(res["meta"]))
    os.replace(tmp, out)
    return res["meta"]


def _load_reproj(spec: TargetSpec, fid: str):
    with np.load(_reproj_dir(spec) / f"{fid}.npz") as z:
        return z["img"].astype(np.float64), z["var"].astype(np.float64), z["chan"]


def average_detector(spec: TargetSpec, exposures: list[dict], n_epochs: int, nchan: int, shape: tuple[int, int]):
    """Step 7a for one detector, from the cached reprojections: (I, V, N) of shape (epochs, channels, H, W),
    the sky pixels used, the number of rejected outliers, the exposures that contributed, and the dropped ones."""
    I = np.full((n_epochs, nchan) + shape, np.nan, np.float32)
    V = np.full_like(I, np.nan)
    N = np.zeros(I.shape, np.uint8)
    rejected = 0
    dropped = []
    # per-exposure sky level (IMAGE - ZODI leaves an offset that differs from exposure to exposure):
    # the median over ONE set of sky pixels, the same for every exposure and epoch of the detector
    usable_x = [x for x in exposures if x["background"] is not None and x["median_variance"]]
    arrs = {x["frame_id"]: _load_reproj(spec, x["frame_id"]) for x in usable_x}
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


def is_complete(spec: TargetSpec) -> bool:
    meta = _read_json(_products(spec) / "meta.json")
    return bool(meta and meta.get("complete") and meta.get("pipeline_version") == PIPELINE_VERSION
                and not meta.get("failed_retryable"))


def run(spec: TargetSpec, refresh: bool = False) -> dict:
    """The whole pipeline for one position. Blocking; the only function here that talks to IRSA.
    Cached pieces (search result, cutouts, reprojections) are reused; `refresh` searches IRSA again."""
    cleanup_temp()
    d = _dir(spec)
    prog = Progress(spec)
    try:
        ex = example_of(spec)
        _write_json(d / "target.json", {"ra": spec.ra, "dec": spec.dec, "fov": spec.fov_deg,
                                        "example": ex.name if ex else None, "tier": d.parent.name})
        d = None  # from here on: _dir(spec) for raw data, `out` for results
        out = product_dir(spec, "epochmaps", epochmap_params())
        search = None if refresh else _read_json(_dir(spec) / "search.json")
        if search is None:
            search = _search(spec)
            _write_json(_dir(spec) / "search.json", search)
        fields = spherex.ImageRecord.__dataclass_fields__
        records = [spherex.ImageRecord(**{k: r[k] for k in fields}) for r in search["records"]]
        seasons = spherex.group_seasons(records, EPOCH_GAP_DAYS)
        epoch_of = {frame_id(r): e for e, s in enumerate(seasons) for r in s}
        epochs = []
        for e, s in enumerate(seasons):
            t = [r.t_mid_mjd for r in s]
            epochs.append({"index": e, "start": iso_time(min(t)), "end": iso_time(max(t)),
                           "time": iso_time(float(np.median(t))), "n_images": len(s),
                           "images_per_detector": {det: sum(1 for r in s if r.detector == det)
                                                   for det in sorted({r.detector for r in s})}})
        grid, shape = spherex.north_up_wcs(spec.center, spec.fov_deg, PIXEL_SCALE_ARCSEC / 3600)
        meta = {
            "pipeline_version": PIPELINE_VERSION, "complete": False,
            "target": {"ra": spec.ra, "dec": spec.dec, "fov": spec.fov_deg},
            "grid": {"width": shape[1], "height": shape[0], "pixel_scale_arcsec": PIXEL_SCALE_ARCSEC,
                     "orientation": "north up, east left; PNG pixel (0, 0) is the north-east corner"},
            "collections": search["collections"], "searched_at": iso_time(Time(search["searched_at"], format="unix").mjd),
            "n_images": len(records), "epoch_gap_days": EPOCH_GAP_DAYS, "epochs": epochs,
            "bad_flags": list(BAD_FLAG_NAMES), "bundles": [], "failed": [], "failed_retryable": 0,
        }
        prog.write(force=True, total=len(records), stage="calibration")

        with httpx.Client(timeout=180, follow_redirects=True, limits=httpx.Limits(max_connections=WORKERS * 2)) as client:
            channels = {rel: load_channels(rel, client) for rel in sorted({spherex.release_of(r) for r in records})}
            nchans = {c["nchan"] for c in channels.values()}
            if len(nchans) > 1:
                raise RuntimeError(f"releases disagree on the number of channels: {nchans}")
            nchan = nchans.pop() if nchans else 0
            meta["channel_files"] = sorted({c["file"] for c in channels.values()})
            rows = next(iter(channels.values()))["rows"] if channels else []

            def chan_info(det: str) -> list[dict]:
                by = {(int(r["DETECTOR"]), int(r["SUBCHAN"])): r for r in rows}
                n = int(det.lstrip("D"))
                return [{"detector": det, "channel": c, "wavelength_um": _num(by[(n, c)]["WAVELENGTH"], 4),
                         "wl_min_um": _num(by[(n, c)]["WL_MIN"], 4), "wl_max_um": _num(by[(n, c)]["WL_MAX"], 4)}
                        for c in range(1, nchan + 1)]

            meta["channel_table"] = [c for det in sorted({r.detector for r in records}) for c in chan_info(det)]
            cubes = {}
            all_exposures: list[dict] = []
            for det in sorted({r.detector for r in records}):  # one detector after the other, each released when done
                prog.write(force=True, stage=f"{det}: downloading and aligning")
                recs = [r for r in records if r.detector == det]

                def one(r: spherex.ImageRecord) -> dict:
                    res = _fetch_and_reproject(spec, r, client, channels[spherex.release_of(r)]["map"])
                    prog.step()
                    return res

                with ThreadPoolExecutor(WORKERS) as ex:
                    results = list(ex.map(one, recs))
                exposures = []
                for r, res in zip(recs, results):
                    if "failed" in res:
                        meta["failed"].append({"frame_id": res["frame_id"], "reason": res["failed"]})
                        meta["failed_retryable"] += 1 if res.get("retry") else 0
                    else:
                        exposures.append({**res, "epoch": epoch_of[frame_id(r)]})
                prog.write(force=True, stage=f"{det}: averaging")
                I, V, N, sky, rejected, exposures, dropped = average_detector(spec, exposures, len(seasons), nchan, shape)
                meta["failed"] += dropped
                np.savez_compressed(out / f"channels_{det}.npz", image=I, variance=V, n=N, sky=sky)
                cubes[det] = (I, V, N)
                all_exposures += exposures
                _store_bundle(spec, meta, det, "detector", I, V, N, chan_info(det), epochs, exposures,
                              extra={"outliers_rejected": rejected})
                prog.write(force=True, bundles_ready=[b["id"] for b in meta["bundles"]])

            if cubes:
                prog.write(force=True, stage="all detectors: averaging")
                dets = sorted(cubes)
                _store_bundle(spec, meta, "all", "all", *(np.concatenate([cubes[k][i] for k in dets], axis=1) for i in range(3)),
                              [c for k in dets for c in chan_info(k)], epochs, all_exposures)
        meta["complete"] = True
        meta["computed_at"] = iso_time(Time.now().mjd)
        _write_json(out / "meta.json", meta)
        prog.write(force=True, state="done", stage="done", bundles_ready=[b["id"] for b in meta["bundles"]])
        return meta
    except Exception as err:  # noqa: BLE001
        log.exception("epoch maps for %s failed", spec.key)
        prog.write(force=True, state="error", message=getattr(err, "message", str(err))[:300])
        raise


def _store_bundle(spec: TargetSpec, meta: dict, bundle_id: str, kind: str, I, V, N, chan_info, epochs, exposures,
                  extra: dict | None = None) -> None:
    d = product_dir(spec, "epochmaps", epochmap_params())
    bmeta, arrays, pngs = make_bundle(bundle_id, kind, I, V, N, chan_info, epochs, exposures)
    bmeta.update(extra or {})
    for name, data in pngs.items():
        (d / name).write_bytes(data)
    if arrays:
        np.savez_compressed(d / f"bundle_{bundle_id}.npz", **arrays)
    meta["bundles"] = [b for b in meta["bundles"] if b["id"] != bundle_id] + [bmeta]
    _write_json(d / "meta.json", meta)  # released: the API serves this bundle from now on


# --- starting and reading (the API uses only these) ---------------------------------------------
_threads: dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()


def _running(spec: TargetSpec) -> dict | None:
    st = _read_json(_dir(spec) / "status.json")
    if st and st.get("state") == "running" and time.time() - st.get("updated", 0) < STATUS_STALE_S:
        return st
    return None


def start(spec: TargetSpec, refresh: bool = False) -> dict:
    """Start the computation in the background unless it is running or already complete."""
    with _threads_lock:
        if _running(spec) is None and (refresh or not is_complete(spec)):
            Progress(spec)  # mark as running before the thread starts, so the answer below already says so
            t = threading.Thread(target=_run_quiet, args=(spec, refresh), daemon=True, name=f"epochs-{spec.key}")
            _threads[spec.key] = t
            t.start()
    return status(spec)


def _run_quiet(spec: TargetSpec, refresh: bool) -> None:
    try:
        run(spec, refresh)
    except Exception:  # noqa: BLE001 - already logged and written to the status file
        pass


def status(spec: TargetSpec) -> dict:
    """What is known about this position, from files only."""
    _touch(spec)
    meta = _read_json(_products(spec) / "meta.json")
    if meta and meta.get("pipeline_version") != PIPELINE_VERSION:
        meta = None
    st = _read_json(_dir(spec) / "status.json")
    run_st = _running(spec)
    if run_st:
        state = "running"
    elif meta and meta.get("complete"):
        state = "cached"
    elif st and st.get("state") == "error":
        state = "error"
    else:
        state = "not_computed"
    progress = None
    if run_st:
        progress = {k: run_st[k] for k in ("stage", "done", "total", "bundles_ready")}
    return {"status": state, "progress": progress, "message": st.get("message") if st and state == "error" else None,
            "default_fov": DEFAULT_FOV_DEG, "target": {"ra": spec.ra, "dec": spec.dec, "fov": spec.fov_deg},
            "cache": "example (permanent)" if example_of(spec) else f"temporary (removed after {TEMP_TTL_HOURS:g} h without use)",
            "result": meta}


def bundle_meta(spec: TargetSpec, bundle_id: str) -> dict:
    meta = _read_json(_products(spec) / "meta.json")
    if not meta or meta.get("pipeline_version") != PIPELINE_VERSION:
        raise ApiError(404, "not_computed", "nothing is computed for this position yet: POST /api/compute first")
    if bundle_id == "channel":
        raise ApiError(400, "no_image_for_channels", "bundle=channel has no pictures; use /api/spectrum for single channels")
    for b in meta["bundles"]:
        if b["id"] == bundle_id:
            return b
    ready = [b["id"] for b in meta["bundles"]]
    raise ApiError(404, "unknown_bundle", f"bundle '{bundle_id}' is not available (yet); available: {ready}")


def load_png(spec: TargetSpec, name: str, scale: int = 1) -> bytes:
    path = _products(spec) / name
    if not path.exists():
        raise ApiError(404, "no_image", "this picture does not exist for this position and bundle")
    data = path.read_bytes()
    if scale > 1:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        img.resize((img.width * scale, img.height * scale), Image.NEAREST).save(buf, "PNG")
        data = buf.getvalue()
    return data


def spectrum(spec: TargetSpec, x: int, y: int) -> dict:
    """Per channel and epoch: the averaged value of one pixel. x, y are PNG pixel coordinates at scale 1
    (x from the left = east, y from the top = north)."""
    meta = _read_json(_products(spec) / "meta.json")
    if not meta or meta.get("pipeline_version") != PIPELINE_VERSION:
        raise ApiError(404, "not_computed", "nothing is computed for this position yet: POST /api/compute first")
    W, H = meta["grid"]["width"], meta["grid"]["height"]
    if not (0 <= x < W and 0 <= y < H):
        raise ApiError(400, "bad_pixel", f"x must be 0..{W - 1} and y 0..{H - 1}")
    stored = _products(spec) / "spectrum" / f"x{x}_y{y}.json"  # computed once, then only read
    if meta.get("complete"):
        hit = _read_json(stored)
        if hit is not None:
            return hit
    row = H - 1 - y
    out = []
    unit = None
    for b in meta["bundles"]:
        if b["kind"] != "detector":
            continue
        path = _products(spec) / f"channels_{b['id']}.npz"
        if not path.exists():
            continue
        unit = unit or (b.get("stretch") or {}).get("unit")
        info = {(c["detector"], c["channel"]): c for c in b.get("channels", [])}
        with np.load(path) as z:
            I, V, N = z["image"][:, :, row, x], z["variance"][:, :, row, x], z["n"][:, :, row, x]
        table = {(c["detector"], c["channel"]): c for c in meta.get("channel_table", [])}
        for c in range(I.shape[1]):
            ci = table.get((b["id"], c + 1)) or info.get((b["id"], c + 1)) or {}
            out.append({"detector": b["id"], "channel": c + 1, "wavelength_um": ci.get("wavelength_um"),
                        "wl_min_um": ci.get("wl_min_um"), "wl_max_um": ci.get("wl_max_um"),
                        "epochs": [{"epoch": e, "value": _num(I[e, c]), "sigma": _num(np.sqrt(V[e, c])) if np.isfinite(V[e, c]) else None,
                                    "n": int(N[e, c])} for e in range(I.shape[0])]})
    result = {"x": x, "y": y, "unit": unit, "value_definition": "IMAGE - ZODI, minus each exposure's sky level (median over the darkest pixels of the field)",
            "epochs": [{"index": e["index"], "time": e["time"], "start": e["start"], "end": e["end"]} for e in meta["epochs"]],
            "channels": out}
    if meta.get("complete"):
        _write_json(stored, result)
    return result

