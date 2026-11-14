"""The five challenge test targets, known to the resolver (app/resolver.py) by their usual names.

They are matched locally, before any web lookup, for two reasons: the lookup service does not know
every spelling used in the challenge ("WISE 0855-0714" is not found, "WISE J085510.83-071442.5" is),
and they must work even if the name service is down.

Positions and proper motions are from SIMBAD, as recorded in docs/PROJECT_OVERVIEW.md section 3
(ICRS, epoch J2000; proper motion in mas/yr, pmra already multiplied by cos(dec)).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from astropy.time import Time

J2000_YEAR = 2000.0


@dataclass(frozen=True)
class Preset:
    key: str
    name: str  # display name
    ra_j2000: float  # deg
    dec_j2000: float  # deg
    pmra: float  # mas/yr, includes cos(dec)
    pmdec: float  # mas/yr
    note: str
    fov_deg: float = 0.08
    aliases: tuple[str, ...] = ()  # other spellings people type (matching ignores case, spaces and punctuation)


PRESETS: list[Preset] = [
    Preset("barnard", "Barnard's Star", 269.4520769586187, 4.693364966576667, -801.551, 10362.394,
           "Nearby star with the largest known proper motion (10.4 arcsec/yr). Saturated in several bands.",
           aliases=("Barnard Star", "GJ 699")),
    Preset("eps_indi_b", "Epsilon Indi B", 331.04414658852124, -56.782844195116105, 3981.977, -2466.832,
           "Brown dwarf pair (unresolved at 6 arcsec pixels). Its host star is 6.7 arcmin away, so a field of view of 0.2 shows both.",
           fov_deg=0.2, aliases=("eps Indi B", "eps Ind B", "Epsilon Ind B")),
    Preset("wise0855", "WISE 0855-0714", 133.81890825, -7.247048000000001, -8123.7, 673.2,
           "Fast-moving brown dwarf, the coldest known (8.2 arcsec/yr). Expect it in the long-wavelength bands.",
           aliases=("WISE 0855", "WISE J0855-0714", "WISE J085510.83-071442.5", "WISEA J085510.74-071442.5")),
    Preset("rw_aur", "RW Aurigae", 76.95652603458333, 30.401438173888888, 7.23, -20.33,
           "Variable young star. Static: test brightness changes, not motion.", aliases=("RW Aur",)),
    Preset("r_dra", "R Draconis", 248.16761083295, 66.75497941722, -20.643, 6.149,
           "Mira-type variable star. Static: test brightness changes. Near the ecliptic pole, so lots of data.",
           aliases=("R Dra",)),
]


def normalize(text: str) -> str:
    """Case, spaces and punctuation do not matter when matching names: "Barnard's  star" == "barnards star"."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


_BY_NAME: dict[str, Preset] = {normalize(n): p for p in PRESETS for n in (p.name, p.key, *p.aliases)}


def find_preset(text: str) -> Preset | None:
    return _BY_NAME.get(normalize(text))


def view_epoch() -> float:
    """The date positions of moving objects are given for: 1 January of the current year (2026.0 in 2026).
    Constant for a whole year, so cached frames stay valid, and at most a year away from the newest images."""
    return float(datetime.now(timezone.utc).year)


def propagate(ra: float, dec: float, pmra: float, pmdec: float, years: float) -> tuple[float, float]:
    """Linear proper-motion propagation: new (ra, dec) in degrees after `years`."""
    new_dec = dec + pmdec * years / 3.6e6
    new_ra = ra + pmra * years / 3.6e6 / math.cos(math.radians(dec))
    return new_ra % 360.0, new_dec


def epoch_to_mjd(epoch_year: float) -> float:
    return float(Time(epoch_year, format="jyear").mjd)
