"""Turn what the user typed into a target: coordinates, or the name of an object.

Order (see docs/API.md, GET /api/resolve):
  1. coordinates   "269.452 4.693", "17h57m48.5s +04d41m36s", "08h55m10.831s -07d14m42.53s"
  2. local names   the five challenge targets and their usual spellings (app/presets.py)
  3. Sesame        CDS's name resolver (SIMBAD first): position, proper motion, and the official name

For objects with a proper motion the position is moved from the catalogue epoch (J2000) to the start
of the current year, so a moving star sits near the middle of recent images (Barnard's Star has moved
4.6 arcmin since J2000, more than half of a default field of view).
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import quote

import astropy.units as u
import httpx
from astropy.coordinates import SkyCoord

from . import presets
from .service import ApiError

# Tried in order; the first that answers wins. (The main CDS host redirects to another mirror and has
# been unavailable at times, so the Harvard mirror goes first.)
SESAME_MIRRORS = [
    "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame",
    "https://cds.unistra.fr/cgi-bin/nph-sesame",
]
SESAME_TIMEOUT_S = 10.0
MAX_QUERY_LEN = 120
DEFAULT_FOV = 0.08
MOVED_WARNING_ARCMIN = 0.2  # tell the user when the position was moved by more than this (12 arcsec)


@dataclass
class Resolved:
    kind: str  # coordinates | preset | name
    name: str | None
    ra: float
    dec: float
    fov: float
    pmra: float | None = None
    pmdec: float | None = None
    pm_epoch: float | None = None
    note: str | None = None
    warnings: list[str] = field(default_factory=list)


def parse_coordinate_pair(text: str) -> tuple[float, float] | None:
    """(ra, dec) in degrees if `text` is a pair of coordinates, None if it is not (so it may be a name).

    Two plain numbers are degrees. RA is read as hours only when written in sexagesimal (with h m s or
    colons or spaces), as in the challenge text ("08h55m10.831s -07d14m42.53s")."""
    t = re.sub(r"\s+", " ", text.replace(",", " ")).strip()
    parts = t.split(" ")
    ra = dec = None
    if len(parts) == 2:
        try:
            ra, dec = float(parts[0]), float(parts[1])
        except ValueError:
            pass
    if ra is None:
        if not re.search(r"\d", t) or not re.search(r"[:hHdDmMsS°]| .* .* ", t):
            return None
        try:
            c = SkyCoord(t, unit=(u.hourangle, u.deg))
        except Exception:  # noqa: BLE001 - not a coordinate, so probably a name such as "M 31"
            return None
        ra, dec = float(c.ra.deg), float(c.dec.deg)
    if not (0 <= ra <= 360) or not (-90 <= dec <= 90):
        raise ApiError(400, "bad_coordinates", f"RA must be 0-360 degrees (or 0-24 h) and Dec -90 to 90, got {ra:g}, {dec:g}")
    return ra % 360.0, dec


def _clean_name(oname: str) -> str:
    """SIMBAD's main identifier without its type prefix: "NAME Barnard's star" -> "Barnard's star"."""
    return re.sub(r"\s+", " ", re.sub(r"^(NAME|\*\*|\*|V\*)\s+", "", oname.strip())).strip()


def sesame(name: str) -> dict | None:
    """Look the name up. Returns {name, ra, dec, pmra, pmdec} (J2000, pm may be None) or None if nobody knows
    it. Raises resolver_unavailable only if no mirror answered."""
    last: Exception | None = None
    for base in SESAME_MIRRORS:
        try:
            r = httpx.get(f"{base}/-ox/SNV?{quote(name, safe='')}", timeout=SESAME_TIMEOUT_S, follow_redirects=True)
            r.raise_for_status()
            if len(r.content) > 200_000:
                raise ValueError("answer too large")
            root = ET.fromstring(r.text)
        except Exception as err:  # noqa: BLE001 - try the next mirror
            last = err
            continue
        for res in root.iter("Resolver"):
            if res.findtext("jradeg"):
                def num(path: str) -> float | None:
                    try:
                        return float(res.findtext(path))
                    except (TypeError, ValueError):
                        return None

                return {"name": _clean_name(res.findtext("oname") or name), "ra": num("jradeg"), "dec": num("jdedeg"),
                        "pmra": num("pm/pmRA"), "pmdec": num("pm/pmDE")}
        return None  # the service answered: unknown name
    raise ApiError(502, "resolver_unavailable", f"the name service did not answer ({str(last)[:100]}); try coordinates instead")


def _moved(ra0: float, dec0: float, ra1: float, dec1: float) -> float:
    """Distance between two positions in arcminutes (small-angle)."""
    return math.hypot((ra1 - ra0) * math.cos(math.radians(dec0)), dec1 - dec0) * 60


def _with_motion(r: Resolved, ra: float, dec: float, pmra: float | None, pmdec: float | None) -> Resolved:
    """Fill in the position, moved to the view epoch if the object has a proper motion."""
    if pmra is None or pmdec is None:
        r.ra, r.dec = ra, dec  # no motion known: fixed on the sky
        return r
    year = presets.view_epoch()
    r.ra, r.dec = presets.propagate(ra, dec, pmra, pmdec, year - presets.J2000_YEAR)
    r.pmra, r.pmdec, r.pm_epoch = pmra, pmdec, year
    arcmin = _moved(ra, dec, r.ra, r.dec)
    if arcmin >= MOVED_WARNING_ARCMIN:
        r.warnings.append(f"The catalogue position is {arcmin:.1f} arcmin away from where this object is in {year:.0f}; "
                          f"it was moved using its proper motion.")
    return r


def resolve(query: str) -> Resolved:
    q = (query or "").strip()
    if not q:
        raise ApiError(400, "bad_query", "q is empty: type a name or coordinates")
    if len(q) > MAX_QUERY_LEN:
        raise ApiError(400, "bad_query", f"q is longer than {MAX_QUERY_LEN} characters")

    pair = parse_coordinate_pair(q)
    if pair is not None:
        return Resolved("coordinates", None, round(pair[0], 6), round(pair[1], 6), DEFAULT_FOV)

    preset = presets.find_preset(q)
    if preset is not None:
        r = Resolved("preset", preset.name, 0.0, 0.0, preset.fov_deg, note=preset.note)
        r = _with_motion(r, preset.ra_j2000, preset.dec_j2000, preset.pmra, preset.pmdec)
        r.ra, r.dec = round(r.ra, 6), round(r.dec, 6)
        return r

    found = sesame(q)
    if found is None:
        raise ApiError(404, "name_not_found", f"no object called '{q}' was found. Check the spelling, or type coordinates")
    # show the name the user typed ("Vega"), not SIMBAD's official one ("alf Lyr"), which is kept in the note
    note = None if presets.normalize(found["name"]) == presets.normalize(q) else f"SIMBAD identifier: {found['name']}"
    r = _with_motion(Resolved("name", q, 0.0, 0.0, DEFAULT_FOV, note=note), found["ra"], found["dec"], found["pmra"], found["pmdec"])
    r.ra, r.dec = round(r.ra, 6), round(r.dec, 6)
    return r
