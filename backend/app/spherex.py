"""SPHEREx data access: search (SIA2), filter, cutout download and per-frame processing.

Written from these files in docs/spherex/:
- user-guide-data-access.md        SIA2 collections, `access_url`, astroquery as the recommended client
- irsa-cutout-service.md           `center`/`size` rules (degrees by default), clipping at edges,
                                   HTTP 500 when fully outside, cutouts are NOT north-up
- tutorial-intro-spectral-images.md  spectral WCS: WCS(header, fobj=hdul, key="W") then .sip = None;
                                   flag names from MSKNnnnn header keywords; ZODI not subtracted
- tutorial-spectral-image-cutouts.md remote reads can be slow, retry transient errors
- explanatory-supplement-extracts.md Table 16 (which flags mean "not usable")
- irsa-cloud-access.md               the S3 copy; SIA2's `cloud_access` column says where each file is there
- docs/FETCH_SPEED.md (team)         measurements behind the download strategy and footprint locating

Nothing here hard-codes release names, pixel scales or flag bit numbers: collections come from
IRSA's collection list, the pixel scale from the image WCS, flag bits from each FITS header.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import random
import threading
import time
import warnings
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning
from reproject import reproject_interp

from .cutout import FileLayout, NoRangeSupport, OutsideImageError, Stats, range_cutout  # noqa: F401 - re-exported

log = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=FITSFixedWarning)
logging.getLogger("astropy").setLevel(logging.ERROR)

# Collections we never want for time-series images: the All-Sky Cube has no time axis, and the
# deep-field collections only add extra images in a few regions (opt in with include_deep=True).
EXCLUDE_COLLECTION_PARTS = ("cube",)
DEEP_PART = "deep"

# Flags treated as "pixel unusable" (Table 16: NONFUNC/HOT/COLD are "not usable for science",
# TRANSIENT marks cosmic-ray hits). Looked up by NAME in each file's header, never by bit number.
# SOURCE is deliberately absent: it is set on most pixels (intro notebook).
BAD_FLAG_NAMES = ("NONFUNC", "HOT", "COLD", "TRANSIENT")

# HDUs kept in a stored cutout: everything but the PSF/EPSF extension (~96% of an IRSA cutout's bytes, not
# needed). process() reads IMAGE/FLAGS/ZODI/WCS-WAVE, the epoch maps (app/analysis.py) also VARIANCE.
# Cutouts made from byte ranges (app/cutout.py) contain exactly these.
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
    cloud_url: str = ""  # the same file on S3, from SIA2's `cloud_access` column ("" = not known)


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
                    cloud_url=cloud_url(row["cloud_access"]) if "cloud_access" in table.colnames else "",
                )
            )
    return dedupe(records)


def cloud_url(cloud_access) -> str:
    """HTTPS URL of the S3 copy from SIA2's `cloud_access` value, e.g. {"aws": {"bucket_name": ...,
    "key": ..., "region": ...}} (format seen in real SIA2 results, 2026-11-14). "" if missing or unreadable."""
    try:
        aws = json.loads(str(cloud_access))["aws"]
        return f"https://{aws['bucket_name']}.s3.{aws['region']}.amazonaws.com/{aws['key']}"
    except (ValueError, KeyError, TypeError):
        return ""


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
class CutoutCache(Protocol):
    """Where downloaded cutouts are kept, keyed by cutout_key(url) (app/db.py's Store implements this)."""

    def cutout(self, key: str) -> bytes | None: ...
    def put_cutout(self, key: str, url: str, data: bytes) -> None: ...


def cutout_url(record: ImageRecord, center: SkyCoord, size_deg: float) -> str:
    # No units -> degrees for both center (RA,Dec) and size (irsa-cutout-service.md).
    return f"{record.access_url}?center={center.ra.deg:.7f},{center.dec.deg:.7f}&size={size_deg:.5f}"


def cutout_key(url: str) -> str:
    """Cache key of a cutout: SHA-1 of its URL. The URL contains the file version and processing date,
    so a reprocessed image gets a new key and a stored copy never goes stale."""
    return hashlib.sha1(url.encode()).hexdigest()


# At most this many requests to IRSA at a time, across all threads (it answers 503 when hit harder).
IRSA_SLOTS = threading.BoundedSemaphore(int(os.environ.get("SPHEREX_IRSA_WORKERS", "3")))


class LayoutCache(Protocol):
    """Where FileLayouts (app/cutout.py) are kept, keyed by the image's access_url (app/db.py's Store)."""

    def file_layout(self, url: str) -> bytes | None: ...
    def put_file_layout(self, url: str, data: bytes) -> None: ...


def download_cutout(record: ImageRecord, center: SkyCoord, size_deg: float, client: httpx.Client,
                    retries: int = 6, layouts: LayoutCache | None = None) -> bytes:
    """A cutout as FITS bytes (IMAGE, FLAGS, VARIANCE, ZODI, WCS-WAVE; no PSF), identical to what IRSA's cutout service
    returns for cutout_url(record, center, size_deg), so both share one cache key.

    Sources, fastest first (docs/FETCH_SPEED.md): our own cutout from byte ranges of the S3 copy (~1 s, no rate
    limit seen); the same from IRSA's file server (only the needed columns); IRSA's cutout service (6-12 s).
    A cutout outside the image raises OutsideImageError at once; any other failure moves on to the next source.

    With `layouts`, where each part of the file sits is remembered after the first cutout of an image, so later
    cutouts of it (another fov, a pan, a nearby target) need one round of requests instead of five. The S3 and
    IRSA copies are the same file, so one layout serves both (range_cutout re-checks the file size every time)."""
    layout = None
    if layouts is not None:
        try:
            stored = layouts.file_layout(record.access_url)
            layout = FileLayout.loads(stored) if stored else None
        except Exception:  # noqa: BLE001 - no layout cache: read the headers as usual
            log.exception("could not read the stored file layout")

    def attempt(url: str, multirange: bool) -> bytes:
        st = Stats()
        data = range_cutout(url, center, size_deg, client, stats=st, multirange=multirange, layout=layout)
        if layouts is not None and st.layout is not None and not st.layout_reused:
            try:
                layouts.put_file_layout(record.access_url, st.layout.dumps())
            except Exception:  # noqa: BLE001 - the cutout itself is fine
                log.exception("could not store the file layout")
        return data

    problems = []
    if record.cloud_url:
        try:
            return attempt(record.cloud_url, False)
        except OutsideImageError:
            raise
        except Exception as err:  # noqa: BLE001 - e.g. a file that is not on S3 yet (404)
            problems.append(f"S3: {type(err).__name__}: {str(err)[:120]}")
    with IRSA_SLOTS:
        try:
            return attempt(record.access_url, True)
        except OutsideImageError:
            raise
        except Exception as err:  # noqa: BLE001
            problems.append(f"IRSA file: {type(err).__name__}: {str(err)[:120]}")
        log.warning("range cutout failed (%s), using IRSA's cutout service", "; ".join(problems))
        return download_irsa_cutout(record, center, size_deg, client, retries)


def download_irsa_cutout(record: ImageRecord, center: SkyCoord, size_deg: float, client: httpx.Client,
                         retries: int = 6) -> bytes:
    """Download a cutout from IRSA's cutout service; FITS bytes with the PSF extension removed (~4% of the size).

    IRSA rate-limits: after a request it often answers `503 Server busy, retry later.` (measured
    2026-11-14: with 6 parallel workers ~30% of cutouts hit this). So a 503 waits and retries with
    exponential backoff (or the server's Retry-After), instead of failing after a few seconds."""
    url = cutout_url(record, center, size_deg)
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
        buf = io.BytesIO()
        kept.writeto(buf)
    return buf.getvalue()


def fetch_cutout_hdul(record: ImageRecord, center: SkyCoord, size_deg: float, client: httpx.Client) -> fits.HDUList:
    """Download a cutout (PSF removed) and open it. Not cached; the API caches through app/db.py."""
    return fits.open(io.BytesIO(download_cutout(record, center, size_deg, client)))


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
    workers: int = 8,  # requests to IRSA itself are limited separately (IRSA_SLOTS)
    cache: "CutoutCache | None" = None,
) -> tuple[list[Frame], list[tuple[ImageRecord, str]]]:
    """Fetch and process cutouts in parallel. `target_at(mjd)` gives the target position at an
    epoch (so moving targets get the right wavelength and flags). With a `cache` (app/db.py's Store),
    each cutout is downloaded only once, shared with the API. Returns (frames, failures)."""

    def one(rec: ImageRecord, client: httpx.Client):
        try:
            url = cutout_url(rec, center, size_deg)
            key = cutout_key(url)
            data = cache.cutout(key) if cache else None
            if data is None:
                data = download_cutout(rec, center, size_deg, client,
                                       layouts=cache if hasattr(cache, "file_layout") else None)
                if cache:
                    cache.put_cutout(key, url, data)
            with fits.open(io.BytesIO(data)) as hdul:
                return process(hdul, rec, target_at(rec.t_mid_mjd)), None
        except Exception as err:  # keep going; report failures to the caller
            return None, f"{type(err).__name__}: {err}"

    with httpx.Client(timeout=180, follow_redirects=True) as client, ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda r: one(r, client), records))
    frames = [f for f, _ in results if f is not None]
    failures = [(r, e) for r, (f, e) in zip(records, results) if f is None]
    return sorted(frames, key=lambda f: f.record.t_mid_mjd), failures


# --------------------------------------------------------------------------------------------
# Where the target falls on the detector, and its wavelength there, WITHOUT downloading pixels
#
# The wavelength of a pixel is a property of the detector + filter, not of the pointing
# (tutorial-intro-spectral-images.md), so it is looked up in the per-detector CWAVE/CBAND maps of the
# Spectral WCS calibration product (user-guide-data-products.md: "for science analysis, use CWAVE and
# CBAND"). The target's pixel comes from the image footprint SIA2 already returned (`s_region`), checked
# against a few real headers; see locate_on_detector.
# --------------------------------------------------------------------------------------------
S3_BUCKET_URL = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com"  # irsa-cloud-access.md
CALIB_LIST_TTL_S = 3600.0  # list the calibration directory of a release again after this long


class CalibrationCache(Protocol):
    """Where downloaded calibration files are kept (app/db.py's Store implements this). It may also offer
    `calibration_digest(s3_key)`, the content hash, so a file already in memory is not loaded again."""

    def calibration(self, s3_key: str) -> bytes | None: ...
    def put_calibration(self, s3_key: str, data: bytes) -> None: ...


def release_of(record: ImageRecord) -> str:
    """Release directory ("dr1", "qr3", ...) taken from the access_url path, not hard-coded."""
    return record.access_url.split("/spherex/")[1].split("/")[0]


def fetch_image_header(record: ImageRecord, client: httpx.Client, chunk: int = 40_000) -> fits.Header:
    """The IMAGE extension header, read with HTTP range requests: from the S3 copy if known (faster, measured
    in scripts/bench/t3_coverage.py), else, or if that fails, from IRSA."""
    urls = [u for u in (record.cloud_url, record.access_url) if u]
    for i, url in enumerate(urls):
        try:
            return _image_header_from(url, client, chunk)
        except Exception:  # noqa: BLE001
            if i == len(urls) - 1:
                raise
    raise ValueError("record has no URL")


def _image_header_from(url: str, client: httpx.Client, chunk: int) -> fits.Header:
    buf = b""
    while True:
        resp = client.get(url, headers={"Range": f"bytes={len(buf)}-{len(buf) + chunk - 1}"})
        resp.raise_for_status()
        if resp.status_code != 206:
            raise RuntimeError(f"no range support at {url}")
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
            raise ValueError(f"no IMAGE header found in {url}")


# Calibration files (Spectral WCS for the wavelength at the target, Spectral Channels for the epoch maps).
# Process-wide caches, so only the first use after a start needs the database or S3:
# - the S3 listing of a product directory, per release, renewed after CALIB_LIST_TTL_S;
# - each file's parsed content, keyed by the file's content hash: DR1 and QR3 ship byte-identical files
#   under different keys (measured 2026-11-14), so they share one parsed copy.
_calib_lock = threading.Lock()
_calib_keys: dict[tuple[str, str], tuple[float, list[str]]] = {}  # (release, product) -> (listed at, S3 keys)
_calib_digest: dict[str, str] = {}  # S3 key -> sha256 of the file
_calib_parsed: dict[tuple[str, str], object] = {}  # (kind, sha256) -> parsed content


def calibration_keys(client: httpx.Client, release: str, product: str) -> list[str]:
    """S3 keys of the FITS files under <release>/<product>/ (e.g. "dr1", "spectral_channels"), sorted, so the
    newest version sorts last. The directory names follow user-guide-data-products.md; nothing else is assumed."""
    listed = _calib_keys.get((release, product))
    if listed is None or time.time() - listed[0] > CALIB_LIST_TTL_S:
        resp = client.get(S3_BUCKET_URL, params={"list-type": "2", "prefix": f"{release}/{product}/"})
        resp.raise_for_status()
        listed = (time.time(), sorted(k for k in _xml_values(resp.text, "Key") if k.endswith(".fits")))
        _calib_keys[(release, product)] = listed
    return listed[1]


def load_calibration(client: httpx.Client, cache: CalibrationCache | None, key: str, kind: str,
                     parse: Callable[[bytes], object]) -> object:
    """`parse(file bytes)` of the calibration file at S3 `key`, parsed once per process and file content.
    With a `cache` (app/db.py's Store), the file is downloaded only once at all."""
    with _calib_lock:
        digest = _calib_digest.get(key)
        if digest is None and cache is not None and hasattr(cache, "calibration_digest"):
            digest = cache.calibration_digest(key)
        if digest is not None and (kind, digest) in _calib_parsed:
            _calib_digest[key] = digest
            return _calib_parsed[(kind, digest)]
        data = cache.calibration(key) if cache else None
        if data is None:
            resp = client.get(f"{S3_BUCKET_URL}/{key}")
            resp.raise_for_status()
            data = resp.content
            if cache:
                cache.put_calibration(key, data)
        digest = hashlib.sha256(data).hexdigest()
        if (kind, digest) not in _calib_parsed:
            _calib_parsed[(kind, digest)] = parse(data)
        _calib_digest[key] = digest
        return _calib_parsed[(kind, digest)]


def _parse_spectral_wcs(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    with fits.open(io.BytesIO(data)) as h:
        return h["CWAVE"].data.astype(np.float32), h["CBAND"].data.astype(np.float32)


class SpectralMaps:
    """Per-detector CWAVE/CBAND images (microns) from the Spectral WCS product. The file for each release and
    detector is found by listing the public S3 bucket; see calibration_keys and load_calibration for caching."""

    def __init__(self, client: httpx.Client, cache: CalibrationCache | None = None):
        self.client, self.cache = client, cache

    def _key(self, release: str, detector: str) -> str:
        n = detector.lstrip("D")
        keys = [k for k in calibration_keys(self.client, release, "spectral_wcs") if f"/{n}/" in k]
        if not keys:
            raise FileNotFoundError(f"no spectral WCS file for {release} {detector}")
        return keys[-1]  # newest version sorts last

    def get(self, release: str, detector: str) -> tuple[np.ndarray, np.ndarray]:
        return load_calibration(self.client, self.cache, self._key(release, detector), "spectral_wcs",
                                _parse_spectral_wcs)


def _xml_values(text: str, tag: str) -> list[str]:
    import re

    return re.findall(rf"<{tag}>([^<]+)</{tag}>", text)


@dataclass
class Exposure:
    """Search result enriched with where the target fell on the detector and at what wavelength."""

    record: ImageRecord
    x: float  # 0-based pixel position of the target on the full detector (footprint method: within ~8 px)
    y: float
    wavelength_um: float  # CWAVE at that pixel (NaN if off the detector)
    bandwidth_um: float


def _homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """3x3 projective map taking 4 points `src` to 4 points `dst` (direct linear transform)."""
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y, -u], [0, 0, 0, x, y, 1, -v * x, -v * y, -v]]
    return np.linalg.svd(np.array(rows))[2][-1].reshape(3, 3)


def footprint_pixel(s_region: str, coord: SkyCoord, shape: tuple[int, int]) -> tuple[float, float] | None:
    """Detector pixel (0-based x, y) of `coord`, from the image's footprint polygon alone (no download).

    The polygon's 4 corners are projected onto the tangent plane at `coord` and mapped onto the detector's
    corner pixels by a projective transform. That the first vertex is the corner at pixel (0, 0) and the others
    follow in pixel order is OUR MEASUREMENT (576 images, scripts/bench/t3_coverage.py): the docs don't cover
    the vertex order. Measured error vs. the header WCS: median 4.5 px, max 7.5 px, i.e. at most 7% of one
    channel's bandwidth. locate_on_detector checks it against real headers on every lookup.
    None if the polygon is not a quadrilateral."""
    nums = []
    for tok in s_region.split():
        try:
            nums.append(float(tok))
        except ValueError:
            pass  # "POLYGON", "ICRS"
    if not nums or len(nums) % 2:
        return None
    pts = np.array(nums).reshape(-1, 2)
    if len(pts) == 5 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) != 4:
        return None
    a, d = np.radians(pts[:, 0]), np.radians(pts[:, 1])
    a0, d0 = np.radians(coord.ra.deg), np.radians(coord.dec.deg)
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    if np.any(cosc <= 0):
        return None
    px = np.cos(d) * np.sin(a - a0) / cosc
    py = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    h, w = shape
    corners = np.array([[-0.5, -0.5], [w - 0.5, -0.5], [w - 0.5, h - 0.5], [-0.5, h - 0.5]])
    hom = _homography(np.column_stack([px, py]), corners)
    u, v, s = hom @ np.array([0.0, 0.0, 1.0])  # the target is the tangent point (0, 0)
    return float(u / s), float(v / s)


FOOTPRINT_CHECKS = 3  # images per lookup whose header is read to check the footprint method
FOOTPRINT_MAX_ERR_PX = 25.0  # worse than this in any check -> read every header instead (measured max: 7.5)


def locate_on_detector(
    records: list[ImageRecord],
    target_at: Callable[[float], SkyCoord],
    workers: int = 16,
    on_progress: Callable[[int, int], None] | None = None,  # called as (done, total)
    calib_cache: CalibrationCache | None = None,
    method: str = "footprint",  # "footprint" (instant, checked) or "header" (one header read per image)
) -> tuple[list[Exposure], list[tuple[ImageRecord, str]]]:
    """For every image: the target's detector pixel and the wavelength there (CWAVE map).

    "footprint": pixel from the SIA2 footprint (footprint_pixel), nothing downloaded per image.
    FOOTPRINT_CHECKS images spread over the list are compared with their real header WCS; if any is off by
    more than FOOTPRINT_MAX_ERR_PX (e.g. because IRSA changed the polygon's vertex order), or no check header
    can be read, every image is located by "header" instead.
    "header": the exact WCS from each image's IMAGE header (HTTP range request, S3 first)."""
    limits = httpx.Limits(max_connections=workers + 4)
    with httpx.Client(timeout=120, follow_redirects=True, limits=limits) as client:
        maps = SpectralMaps(client, calib_cache)
        for rel, det in sorted({(release_of(r), r.detector) for r in records}):
            maps.get(rel, det)  # load maps up front, once

        def lookup(rec: ImageRecord, x: float, y: float) -> Exposure:
            cw, cb = maps.get(release_of(rec), rec.detector)
            ix, iy = int(round(x)), int(round(y))
            inside = 0 <= iy < cw.shape[0] and 0 <= ix < cw.shape[1]
            wl = float(cw[iy, ix]) if inside else float("nan")
            bw = float(cb[iy, ix]) if inside else float("nan")
            return Exposure(rec, x, y, wl, bw)

        def by_header(rec: ImageRecord) -> tuple[Exposure | None, str | None]:
            try:
                hdr = fetch_image_header(rec, client)
                x, y = (float(v) for v in WCS(hdr).world_to_pixel(target_at(rec.t_mid_mjd)))
                return lookup(rec, x, y), None
            except Exception as err:  # noqa: BLE001
                return None, f"{type(err).__name__}: {err}"

        results: list[tuple[Exposure | None, str | None]] = [(None, None)] * len(records)
        todo = list(range(len(records)))
        if method == "footprint" and records:
            pending = []
            for i, rec in enumerate(records):
                shape = maps.get(release_of(rec), rec.detector)[0].shape
                xy = footprint_pixel(rec.s_region, target_at(rec.t_mid_mjd), shape)
                if xy is None:
                    pending.append(i)  # not a quadrilateral: read its header
                else:
                    results[i] = (lookup(rec, *xy), None)
            located = [i for i in range(len(records)) if results[i][0] is not None]
            n_checks = min(FOOTPRINT_CHECKS, len(located))
            picks = sorted({located[int(j)] for j in np.linspace(0, len(located) - 1, n_checks)}) if n_checks else []
            errs, exact_done = [], set()
            if picks:
                with ThreadPoolExecutor(len(picks)) as ex:
                    checks = list(zip(picks, ex.map(lambda i: by_header(records[i]), picks)))
                for i, (exact, _err) in checks:
                    if exact is not None:
                        errs.append(float(np.hypot(exact.x - results[i][0].x, exact.y - results[i][0].y)))
                        results[i] = (exact, None)  # the exact value is known now anyway
                        exact_done.add(i)
            if picks and (not errs or max(errs) > FOOTPRINT_MAX_ERR_PX):
                log.warning("footprint check failed (errors %s px, %d of %d headers read): reading every header",
                            [round(e, 1) for e in errs], len(errs), len(picks))
                todo = [i for i in range(len(records)) if i not in exact_done]
            else:
                log.info("footprint locating: %d images, checked %d, max error %.1f px",
                         len(located), len(errs), max(errs, default=0.0))
                todo = pending

        done = [len(records) - len(todo)]
        if on_progress:
            on_progress(done[0], len(records))

        def tracked(i: int):
            out = by_header(records[i])
            done[0] += 1
            if on_progress:
                on_progress(done[0], len(records))
            return i, out

        with ThreadPoolExecutor(workers) as ex:
            for i, out in ex.map(tracked, todo):
                results[i] = out
    found = [e for e, _ in results if e is not None]
    failed = [(r, err or "not located") for r, (e, err) in zip(records, results) if e is None]
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
