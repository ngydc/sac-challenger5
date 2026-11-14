"""The SQL in app/db.py against a real Postgres. Skipped when no database is reachable.
Start one with `docker compose up -d db` (from the repo root), or set DATABASE_URL.
Uses a separate schema (`test_cache`) and drops it afterwards, so real cached data is not touched."""
from __future__ import annotations

import math
import uuid

import psycopg
import pytest

from app import db

SCHEMA = f"test_cache_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def store():
    try:
        with psycopg.connect(db.DATABASE_URL, connect_timeout=3, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA {SCHEMA}")
    except psycopg.OperationalError as err:
        pytest.skip(f"no database: {err}")
    sep = "&" if "?" in db.DATABASE_URL else "?"
    s = db.Store(f"{db.DATABASE_URL}{sep}options=-csearch_path%3D{SCHEMA}", max_size=2)
    yield s
    s.close()
    with psycopg.connect(db.DATABASE_URL, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")


def image(fid: str, mjd: float, located: bool = True) -> dict:
    obs, _, det = fid.rpartition("-")
    return {"frame_id": fid, "obs_id": obs, "detector": det, "collection": "spherex_dr1", "t_mid_mjd": mjd,
            "access_url": f"https://example.invalid/{fid}.fits", "s_region": "POLYGON ICRS 1 2 3 4",
            "edge_margin_deg": 0.5, "x": 10.0 if located else None, "y": 20.0 if located else None,
            "wavelength_um": (float("nan") if fid.endswith("D6") else 1.3) if located else None,
            "bandwidth_um": 0.03 if located else None}


def test_collections(store):
    assert store.collections() is None
    store.save_collections(["spherex_dr1", "spherex_qr3"])
    store.save_collections(["spherex_dr1", "spherex_qr3", "spherex_dr2"])  # replaced, not appended
    names, fetched = store.collections()
    assert names == ["spherex_dr1", "spherex_dr2", "spherex_qr3"] and fetched > 1.7e9


def test_coverage_round_trip_and_replace(store):
    target = {"ra": 269.446, "dec": 4.768, "fov_deg": 0.08, "pmra": None, "pmdec": None, "pm_epoch": None}
    store.save_coverage("k1", target, ["spherex_dr1"], 1, 1.7e9,
                        [image("B_1-D1", 61100.0), image("A_1-D6", 60900.0), image("A_2-D2", 60900.1, located=False)])
    d = store.load_coverage("k1")
    assert d["collections"] == ["spherex_dr1"] and d["failed_locate"] == 1 and d["data_as_of"] == pytest.approx(1.7e9)
    assert [i["frame_id"] for i in d["images"]] == ["A_1-D6", "A_2-D2", "B_1-D1"]  # time order
    assert math.isnan(d["images"][0]["wavelength_um"]) and d["images"][1]["x"] is None
    store.save_coverage("k1", target, ["spherex_dr1", "spherex_qr3"], 0, 1.8e9, [image("C_1-D3", 61300.0)])
    d = store.load_coverage("k1")
    assert [i["frame_id"] for i in d["images"]] == ["C_1-D3"] and d["failed_locate"] == 0
    assert store.load_coverage("nope") is None


def test_cutouts(store):
    assert store.cutout("c1") is None and store.cutout_states(["c1"]) == {}
    store.put_cutout_failure("c1", "u", "error", "503")
    assert store.cutout_states(["c1"])["c1"][0] == "error" and store.cutout("c1") is None
    store.put_cutout("c1", "u", b"\x00FITS\xff")
    assert store.cutout("c1") == b"\x00FITS\xff"
    store.put_cutout_failure("c1", "u", "error", "late failure")  # must not overwrite a stored cutout
    assert store.cutout_states(["c1", "c2"]) == {"c1": ("ready", pytest.approx(store.cutout_states(["c1"])["c1"][1]), None)}
    store.put_cutout_failure("c2", "u", "outside", "outside image")
    assert store.cutout_states(["c2"])["c2"][0] == "outside"


def test_calibration(store):
    assert store.calibration("dr1/spectral_wcs/x.fits") is None
    store.put_calibration("dr1/spectral_wcs/x.fits", b"abc")
    store.put_calibration("dr1/spectral_wcs/x.fits", b"other")  # first one wins
    assert store.calibration("dr1/spectral_wcs/x.fits") == b"abc"
