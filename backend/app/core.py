"""Basics every part of the backend shares: the target (position, field of view, motion), the error type
of the API, and the constants that define frames and visits. No I/O here, so any module can import it.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

from . import presets

PIXEL_SCALE_ARCSEC = 6.15  # SPHEREx pixel size (docs/spherex/user-guide-data-products.md; header measures 6.15)
CUTOUT_FACTOR = 1.45  # cutout side / view side: images are rotated vs north, a square this much larger always
#                      fills the north-up view (needs sqrt(2) at worst; IRSA's cost barely depends on size)
FOV_MIN, FOV_MAX = 0.01, 0.30  # degrees
VISIT_GAP_DAYS = 30.0  # a gap longer than this between images starts a new visit (observing season)


class ApiError(Exception):
    """An error with an HTTP status and a stable machine-readable code (see docs/API.md)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# --- target ---------------------------------------------------------------------------------
def parse_coord(ra: str, dec: str) -> tuple[float, float]:
    """RA/Dec as decimal degrees ("269.452", "4.6934") or sexagesimal ("17h57m48.5s", "+04d41m36s",
    "17:57:48.5"). Returns degrees."""
    ra, dec = str(ra).strip(), str(dec).strip()
    try:
        return float(ra), float(dec)
    except ValueError:
        pass
    try:
        c = SkyCoord(f"{ra} {dec}", unit=(u.hourangle, u.deg))
    except Exception as err:
        raise ApiError(400, "bad_coordinates", f"cannot read RA/Dec '{ra}' '{dec}': {err}") from err
    return float(c.ra.deg), float(c.dec.deg)


@dataclass(frozen=True)
class TargetSpec:
    """What the user is looking at: a sky position, a field of view and (optionally) the object's motion."""

    ra: float  # deg, centre of the view (fixed on the sky)
    dec: float
    fov_deg: float
    pmra: float | None = None  # mas/yr incl. cos(dec); with pmdec and pm_epoch, makes the predicted position move
    pmdec: float | None = None
    pm_epoch: float | None = None  # decimal year at which (ra, dec) is the object's position

    @staticmethod
    def build(ra: str, dec: str, fov: float, pmra: float | None, pmdec: float | None,
              pm_epoch: float | None) -> "TargetSpec":
        r, d = parse_coord(ra, dec)
        if not (0 <= r < 360 or r == 360) or not (-90 <= d <= 90):
            raise ApiError(400, "bad_coordinates", f"RA must be 0-360 deg and Dec -90..90 deg, got {r}, {d}")
        if not (FOV_MIN <= fov <= FOV_MAX):
            raise ApiError(400, "bad_fov", f"fov must be {FOV_MIN}-{FOV_MAX} degrees, got {fov}")
        if len({pmra is None, pmdec is None, pm_epoch is None}) != 1:
            raise ApiError(400, "bad_motion", "pmra, pmdec and pm_epoch must be given together, or not at all")
        return TargetSpec(round(r % 360.0, 6), round(d, 6), round(fov, 5), pmra, pmdec, pm_epoch)

    @property
    def key(self) -> str:
        """Identifies the view (position, fov, motion): used for the frames shown."""
        raw = f"{self.ra:.6f},{self.dec:.6f},{self.fov_deg:.5f},{self.pmra},{self.pmdec},{self.pm_epoch}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    @property
    def coverage_key(self) -> str:
        """Identifies the search (position and motion, NOT fov): one coverage serves every fov."""
        raw = f"{self.ra:.6f},{self.dec:.6f},{self.pmra},{self.pmdec},{self.pm_epoch}"
        return "p" + hashlib.sha1(raw.encode()).hexdigest()[:11]

    @property
    def edge_margin_deg(self) -> float:
        """Smallest distance of the view centre from an image edge so the whole view lies inside the image
        (half the diagonal of the view: images are rotated against north)."""
        return self.fov_deg / 2 * math.sqrt(2)

    @property
    def center(self) -> SkyCoord:
        return SkyCoord(self.ra * u.deg, self.dec * u.deg)

    @property
    def cutout_size(self) -> float:
        return round(self.fov_deg * CUTOUT_FACTOR, 5)

    @property
    def n_pix(self) -> int:
        return int(math.ceil(self.fov_deg * 3600 / PIXEL_SCALE_ARCSEC))

    def at(self, mjd: float) -> SkyCoord:
        """Where the target is predicted to be at time `mjd` (the view centre if no motion was given)."""
        if self.pmra is None:
            return self.center
        years = (mjd - presets.epoch_to_mjd(self.pm_epoch)) / 365.25
        ra, dec = presets.propagate(self.ra, self.dec, self.pmra, self.pmdec, years)
        return SkyCoord(ra * u.deg, dec * u.deg)


def frame_id(record) -> str:
    """'<obs_id>-<detector>', e.g. '2025W35_2A_0611_1-D2' (any object with obs_id and detector)."""
    return f"{record.obs_id}-{record.detector}"


def split_frame_id(fid: str) -> tuple[str, str]:
    obs_id, sep, det = fid.rpartition("-")
    if not sep or not obs_id or not (len(det) == 2 and det[0] == "D" and det[1].isdigit()):
        raise ApiError(400, "bad_frame_id", f"frame id must look like '2025W35_2A_0611_1-D2', got '{fid}'")
    return obs_id, det


def iso(mjd: float) -> str:
    return Time(mjd, format="mjd").isot[:19] + "Z"
