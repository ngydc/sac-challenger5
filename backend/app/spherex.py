"""SPHEREx data access: search (SIA2), filter, cutout download and per-frame processing.

Written from these files in docs/spherex/:
- user-guide-data-access.md        SIA2 collections, `access_url`, astroquery as the recommended client
- irsa-cutout-service.md           `center`/`size` rules (degrees by default), clipping at edges,
                                   HTTP 500 when fully outside, cutouts are NOT north-up
- tutorial-intro-spectral-images.md  spectral WCS: WCS(header, fobj=hdul, key="W") then .sip = None;
                                   flag names from MSKNnnnn header keywords; ZODI not subtracted
- tutorial-spectral-image-cutouts.md remote reads can be slow, retry transient errors
- explanatory-supplement-extracts.md Table 16 (which flags mean "not usable")

Nothing here hard-codes release names, pixel scales or flag bit numbers: collections come from
IRSA's collection list, the pixel scale from the image WCS, flag bits from each FITS header.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import random
import time
import warnings
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning
from reproject import reproject_interp

log = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=FITSFixedWarning)
logging.getLogger("astropy").setLevel(logging.ERROR)

CACHE_DIR = Path(os.environ.get("SPHEREX_CACHE_DIR", Path(__file__).resolve().parents[1] / "cache" / "cutouts"))

# Collections we never want for time-series images: the All-Sky Cube has no time axis, and the
# deep-field collections only add extra images in a few regions (opt in with include_deep=True).
EXCLUDE_COLLECTION_PARTS = ("cube",)
DEEP_PART = "deep"

# Flags treated as "pixel unusable" (Table 16: NONFUNC/HOT/COLD are "not usable for science",
# TRANSIENT marks cosmic-ray hits). Looked up by NAME in each file's header, never by bit number.
# SOURCE is deliberately absent: it is set on most pixels (intro notebook).
BAD_FLAG_NAMES = ("NONFUNC", "HOT", "COLD", "TRANSIENT")

# HDUs kept in the cache. The PSF/EPSF extension is ~96% of a cutout's bytes and not needed for display.
KEEP_HDUS = ("IMAGE", "FLAGS", "VARIANCE", "ZODI", "WCS-WAVE")


# --------------------------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------------------------
@dataclass
class ImageRecord:
    """One spectral image (one detector, one exposure) as returned by SIA2."""

    obs_id: str
    detector: str  # "D1" .. "D6", parsed from energy_bandpassname "SPHEREx-D<n>"
    collection: str
    t_mid_mjd: float  # middle of the exposure, MJD
    access_url: str
    s_region: str
    edge_margin_deg: float = float("nan")  # distance target -> nearest image edge (negative = outside)


def spherex_collections(include_deep: bool = False) -> list[str]:
    """Ask IRSA which SPHEREx SIA2 collections exist, so new releases are picked up automatically."""
    from astroquery.ipac.irsa import Irsa

    names = [str(c) for c in Irsa.list_collections(servicetype="SIA", filter="spherex")["collection"]]
    keep = [n for n in names if not any(p in n for p in EXCLUDE_COLLECTION_PARTS)]
    if not include_deep:
        keep = [n for n in keep if DEEP_PART not in n]
    return sorted(keep)


def search(coord: SkyCoord, collections: Iterable[str], radius_deg: float = 0.001) -> list[ImageRecord]:
    """SIA2 search: every spectral image whose footprint contains the position."""
    from astroquery.ipac.irsa import Irsa

    records: list[ImageRecord] = []
    for coll in collections:
        table = Irsa.query_sia(pos=(coord, radius_deg * u.deg), collection=coll)
        for row in table:
            band = str(row["energy_bandpassname"])
            records.append(
                ImageRecord(
                    obs_id=str(row["obs_id"]),
                    detector=band.split("-")[-1],
                    collection=coll,
                    t_mid_mjd=(float(row["t_min"]) + float(row["t_max"])) / 2,
                    access_url=str(row["access_url"]),
                    s_region=str(row["s_region"]),
                )
            )
    return dedupe(records)


def dedupe(records: list[ImageRecord]) -> list[ImageRecord]:
    """Keep one record per (obs_id, detector). Today releases don't overlap; a future
    reprocessing might. The later access_url sorts last (it contains version and processing date)."""
    best: dict[tuple[str, str], ImageRecord] = {}
    for r in sorted(records, key=lambda r: r.access_url):
        best[(r.obs_id, r.detector)] = r
    return sorted(best.values(), key=lambda r: r.t_mid_mjd)


# --------------------------------------------------------------------------------------------
# Filter
# --------------------------------------------------------------------------------------------
def edge_margin_deg(coord: SkyCoord, s_region: str) -> float:
    """Angular distance from `coord` to the nearest edge of the image footprint (degrees).
    Positive inside the footprint, negative outside. Uses a tangent-plane projection, which is
    accurate enough for a ~3.5 degree image."""
    nums = []
    for tok in s_region.split():
        try:
            nums.append(float(tok))
        except ValueError:
            pass  # "POLYGON", "ICRS"
    pts = np.radians(np.array(nums).reshape(-1, 2))
    a0, d0 = np.radians(coord.ra.deg), np.radians(coord.dec.deg)
    a, d = pts[:, 0], pts[:, 1]
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    x = np.cos(d) * np.sin(a - a0) / cosc
    y = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    poly = np.degrees(np.column_stack([x, y]))
    if np.allclose(poly[0], poly[-1]):
        poly = poly[:-1]

    inside = False
    dists = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        if (p[1] > 0) != (q[1] > 0) and 0 < p[0] + (0 - p[1]) * (q[0] - p[0]) / (q[1] - p[1]):
            inside = not inside
        seg = q - p
        t = np.clip(-(p @ seg) / (seg @ seg), 0, 1)
        dists.append(np.hypot(*(p + t * seg)))
    return float(min(dists)) * (1 if inside else -1)


def filter_records(
    records: list[ImageRecord],
    coord: SkyCoord,
    detectors: Iterable[str] | None = None,
    min_edge_margin_deg: float = 0.0,
    t_range_mjd: tuple[float, float] | None = None,
) -> list[ImageRecord]:
    """Cheap, pre-download filters: detector, distance from the image edge, time window."""
    dets = set(detectors) if detectors else None
    out = []
    for r in records:
        if dets and r.detector not in dets:
            continue
        if t_range_mjd and not (t_range_mjd[0] <= r.t_mid_mjd <= t_range_mjd[1]):
            continue
        r.edge_margin_deg = edge_margin_deg(coord, r.s_region)
        if r.edge_margin_deg < min_edge_margin_deg:
            continue
        out.append(r)
    return out


def group_seasons(records: list[ImageRecord], gap_days: float = 30.0) -> list[list[ImageRecord]]:
    """Split time-sorted records into observing seasons: a gap longer than `gap_days` starts a new one.
    (Team measurement: a position is revisited in seasons roughly six months apart.)"""
    seasons: list[list[ImageRecord]] = []
    for r in sorted(records, key=lambda r: r.t_mid_mjd):
        if not seasons or r.t_mid_mjd - seasons[-1][-1].t_mid_mjd > gap_days:
            seasons.append([])
        seasons[-1].append(r)
    return seasons


# --------------------------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------------------------
class OutsideImageError(Exception):
    """IRSA returned HTTP 500: the cutout does not overlap the image (irsa-cutout-service.md)."""


def cutout_url(record: ImageRecord, center: SkyCoord, size_deg: float) -> str:
    # No units -> degrees for both center (RA,Dec) and size (irsa-cutout-service.md).
    return f"{record.access_url}?center={center.ra.deg:.7f},{center.dec.deg:.7f}&size={size_deg:.5f}"


def cutout_path(record: ImageRecord, center: SkyCoord, size_deg: float) -> Path:
    """Where the cached (PSF-stripped) copy of this cutout lives. Deterministic, so callers can
    check `.exists()` to know whether a download is needed. The URL contains the file version and
    processing date, so a reprocessed image gets a new path and a cached copy never goes stale."""
    return CACHE_DIR / f"{hashlib.sha1(cutout_url(record, center, size_deg).encode()).hexdigest()}.fits"


def fetch_cutout_hdul(
    record: ImageRecord, center: SkyCoord, size_deg: float, client: httpx.Client, retries: int = 6
) -> fits.HDUList:
    """Download (or load from cache) a cutout, with the PSF extension removed.

    IRSA rate-limits: after a request it often answers `503 Server busy, retry later.` (measured
    2026-11-14: with 6 parallel workers ~30% of cutouts hit this). So a 503 waits and retries with
    exponential backoff (or the server's Retry-After), instead of failing after a few seconds."""
    url = cutout_url(record, center, size_deg)
    path = cutout_path(record, center, size_deg)
    if path.exists():
        return fits.open(path)

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.get(url)
            if resp.status_code == 500:
                raise OutsideImageError(url)
            if resp.status_code == 503:
                last_err = RuntimeError("503 Server busy")
                wait = float(resp.headers.get("Retry-After", min(5 * 2**attempt, 60)))
                time.sleep(wait + random.random() * 2)
                continue
            resp.raise_for_status()
            break
        except OutsideImageError:
            raise
        except (httpx.HTTPError, OSError) as err:  # transient: timeouts, dropped connections, other 5xx
            last_err = err
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"cutout failed after {retries} attempts: {url}") from last_err

    with fits.open(io.BytesIO(resp.content)) as full:
        kept = fits.HDUList([full[0].copy()] + [full[name].copy() for name in KEEP_HDUS if name in full])
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    kept.writeto(path, overwrite=True)
    return kept


# --------------------------------------------------------------------------------------------
# Process
# --------------------------------------------------------------------------------------------
@dataclass
class Frame:
    """One processed cutout: background-subtracted image plus what we know about it."""

    record: ImageRecord
    image: np.ndarray  # IMAGE - ZODI in MJy/sr, unusable pixels set to NaN
    raw: np.ndarray  # the same, nothing masked
    bad: np.ndarray  # bool: True where one of BAD_FLAG_NAMES is set
    wcs: WCS
    wavelength_um: float  # at the target position (WCS-WAVE, visualization accuracy)
    bandwidth_um: float
    target_xy: tuple[float, float]  # 0-based pixel position of the target in this cutout
    flags_at_target: list[str] = field(default_factory=list)
    version: str = ""


def _flag_bits(flags_header: fits.Header) -> dict[str, int]:
    """Map flag NAME -> bit number from the MSKNnnnn keywords (tutorial-intro-spectral-images.md)."""
    return {str(flags_header[k]).strip(): int(k[4:]) for k in flags_header["MSKN*"]}


def process(hdul: fits.HDUList, record: ImageRecord, target: SkyCoord) -> Frame:
    img_hdr = hdul["IMAGE"].header
    raw = hdul["IMAGE"].data.astype(np.float64) - hdul["ZODI"].data  # ZODI is not pre-subtracted
    flags = hdul["FLAGS"].data.astype(np.int64)
    bits = _flag_bits(hdul["FLAGS"].header)

    bad_mask = np.zeros_like(flags, dtype=bool)
    for name in BAD_FLAG_NAMES:
        if name in bits:
            bad_mask |= (flags & (1 << bits[name])) != 0
    image = raw.copy()
    image[bad_mask] = np.nan

    wcs = WCS(img_hdr)
    x, y = (float(v) for v in wcs.world_to_pixel(target))

    spectral = WCS(img_hdr, fobj=hdul, key="W")
    spectral.sip = None  # required for the spectral WCS (tutorial-intro-spectral-images.md)
    wl, bw = spectral.pixel_to_world(x, y)

    ix, iy = int(round(x)), int(round(y))
    at_target = []
    if 0 <= iy < flags.shape[0] and 0 <= ix < flags.shape[1]:
        at_target = [n for n, b in sorted(bits.items(), key=lambda kv: kv[1]) if flags[iy, ix] & (1 << b)]

    return Frame(
        record=record,
        image=image,
        raw=raw,
        bad=bad_mask,
        wcs=wcs,
        wavelength_um=float(wl.to(u.um).value),
        bandwidth_um=float(bw.to(u.um).value),
        target_xy=(x, y),
        flags_at_target=at_target,
        version=str(hdul[0].header.get("VERSION", "")),
    )


def fetch_frames(
    records: list[ImageRecord],
    center: SkyCoord,
    size_deg: float,
    target_at: Callable[[float], SkyCoord],
    workers: int = 3,  # IRSA answers 503 "Server busy" when hit harder (see fetch_cutout_hdul)
) -> tuple[list[Frame], list[tuple[ImageRecord, str]]]:
    """Fetch and process cutouts in parallel. `target_at(mjd)` gives the target position at an
    epoch (so moving targets get the right wavelength and flags). Returns (frames, failures)."""

    def one(rec: ImageRecord, client: httpx.Client):
        try:
            with fetch_cutout_hdul(rec, center, size_deg, client) as hdul:
                return process(hdul, rec, target_at(rec.t_mid_mjd)), None
        except Exception as err:  # keep going; report failures to the caller
            return None, f"{type(err).__name__}: {err}"

    with httpx.Client(timeout=180, follow_redirects=True) as client, ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda r: one(r, client), records))
    frames = [f for f, _ in results if f is not None]
    failures = [(r, e) for r, (f, e) in zip(records, results) if f is None]
    return sorted(frames, key=lambda f: f.record.t_mid_mjd), failures


# --------------------------------------------------------------------------------------------
# Wavelength at the target WITHOUT downloading pixels
#
# The wavelength of a pixel is a property of the detector + filter, not of the pointing
# (tutorial-intro-spectral-images.md). So: read only the header of each image (HTTP range
# request, ~26 KB instead of ~65 MB) to get the exact sky->pixel WCS, then look the pixel up
# in the per-detector CWAVE/CBAND maps of the Spectral WCS calibration product
# (user-guide-data-products.md: "for science analysis, use CWAVE and CBAND").
# --------------------------------------------------------------------------------------------
S3_BUCKET_URL = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com"  # irsa-cloud-access.md
CALIB_DIR = CACHE_DIR.parent / "calib"


def release_of(record: ImageRecord) -> str:
    """Release directory ("dr1", "qr3", ...) taken from the access_url path, not hard-coded."""
    return record.access_url.split("/spherex/")[1].split("/")[0]


def fetch_image_header(record: ImageRecord, client: httpx.Client, chunk: int = 40_000) -> fits.Header:
    """The IMAGE extension header, read with HTTP range requests (the server answers 206)."""
    buf = b""
    while True:
        resp = client.get(record.access_url, headers={"Range": f"bytes={len(buf)}-{len(buf) + chunk - 1}"})
        resp.raise_for_status()
        buf += resp.content
        headers, off = [], 0
        while True:  # walk header blocks: primary (no data), then IMAGE
            end = buf.find(b"END" + b" " * 77, off)
            while end != -1 and (end - off) % 80:
                end = buf.find(b"END" + b" " * 77, end + 1)
            if end == -1:
                break
            size = ((end - off) // 2880 + 1) * 2880
            headers.append(fits.Header.fromstring(buf[off : off + size].decode("ascii")))
            off += size
            if len(headers) == 2:
                return headers[1]
        if len(resp.content) < chunk:
            raise ValueError(f"no IMAGE header found in {record.access_url}")


class SpectralMaps:
    """Per-detector CWAVE/CBAND images (2040 x 2040, microns), downloaded once and cached.
    The file for each release and detector is found by listing the public S3 bucket."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self._maps: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}

    def _key(self, release: str, detector: str) -> str:
        n = detector.lstrip("D")
        resp = self.client.get(S3_BUCKET_URL, params={"list-type": "2", "prefix": f"{release}/spectral_wcs/"})
        resp.raise_for_status()
        keys = [k for k in _xml_values(resp.text, "Key") if k.endswith(".fits") and f"/{n}/" in k]
        if not keys:
            raise FileNotFoundError(f"no spectral WCS file for {release} {detector}")
        return sorted(keys)[-1]  # newest version sorts last

    def get(self, release: str, detector: str) -> tuple[np.ndarray, np.ndarray]:
        if (release, detector) not in self._maps:
            key = self._key(release, detector)
            path = CALIB_DIR / key
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with self.client.stream("GET", f"{S3_BUCKET_URL}/{key}") as resp:
                    resp.raise_for_status()
                    with open(path, "wb") as fh:
                        for part in resp.iter_bytes():
                            fh.write(part)
            with fits.open(path) as h:
                self._maps[(release, detector)] = (h["CWAVE"].data.astype(np.float32), h["CBAND"].data.astype(np.float32))
        return self._maps[(release, detector)]


def _xml_values(text: str, tag: str) -> list[str]:
    import re

    return re.findall(rf"<{tag}>([^<]+)</{tag}>", text)


@dataclass
class Exposure:
    """Search result enriched with where the target fell on the detector and at what wavelength."""

    record: ImageRecord
    x: float  # 0-based pixel position of the target on the full detector
    y: float
    wavelength_um: float  # CWAVE at that pixel (NaN if off the detector)
    bandwidth_um: float


def locate_on_detector(
    records: list[ImageRecord],
    target_at: Callable[[float], SkyCoord],
    workers: int = 16,
    on_progress: Callable[[int, int], None] | None = None,  # called as (done, total) after each image
) -> tuple[list[Exposure], list[tuple[ImageRecord, str]]]:
    """For every image: target pixel (exact header WCS) and wavelength there (CWAVE map)."""
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        maps = SpectralMaps(client)
        for rel, det in {(release_of(r), r.detector) for r in records}:
            maps.get(rel, det)  # download maps up front, once

        def one(rec: ImageRecord):
            try:
                hdr = fetch_image_header(rec, client)
                x, y = (float(v) for v in WCS(hdr).world_to_pixel(target_at(rec.t_mid_mjd)))
                cw, cb = maps.get(release_of(rec), rec.detector)
                ix, iy = int(round(x)), int(round(y))
                inside = 0 <= iy < cw.shape[0] and 0 <= ix < cw.shape[1]
                wl = float(cw[iy, ix]) if inside else float("nan")
                bw = float(cb[iy, ix]) if inside else float("nan")
                return Exposure(rec, x, y, wl, bw), None
            except Exception as err:
                return None, f"{type(err).__name__}: {err}"

        done = [0]

        def tracked(rec: ImageRecord):
            out = one(rec)
            done[0] += 1
            if on_progress:
                on_progress(done[0], len(records))
            return out

        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(tracked, records))
    found = [e for e, _ in results if e is not None]
    failed = [(r, err) for r, (e, err) in zip(records, results) if e is None]
    return sorted(found, key=lambda e: e.record.t_mid_mjd), failed


# --------------------------------------------------------------------------------------------
# Common grid and stacking
# --------------------------------------------------------------------------------------------
def native_pixel_scale_deg(frame: Frame) -> float:
    """Pixel scale read from the image WCS (varies slightly across the detector)."""
    from astropy.wcs.utils import proj_plane_pixel_scales

    return float(np.mean(proj_plane_pixel_scales(frame.wcs.celestial)))


def north_up_wcs(center: SkyCoord, size_deg: float, pixel_scale_deg: float) -> tuple[WCS, tuple[int, int]]:
    """A simple tangent-plane grid centred on `center`, north up, east left."""
    n = int(np.ceil(size_deg / pixel_scale_deg))
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [center.ra.deg, center.dec.deg]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-pixel_scale_deg, pixel_scale_deg]
    return w, (n, n)


def reproject_frame(frame: Frame, out_wcs: WCS, shape: tuple[int, int], raw: bool = False) -> np.ndarray:
    """Resample a cutout onto the common north-up grid, so stars line up between frames.
    `raw=True` resamples the unmasked image instead of the one with bad pixels set to NaN."""
    data, _ = reproject_interp((frame.raw if raw else frame.image, frame.wcs), out_wcs, shape_out=shape)
    return data


def stack(images: list[np.ndarray]) -> np.ndarray:
    """Median of aligned images; robust against cosmic rays and artifacts in single frames."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels
        return np.nanmedian(np.stack(images), axis=0)
