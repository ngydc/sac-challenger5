"""Export and import of the cache (app/cache_transfer.py) against a real Postgres. Skipped when no database is
reachable. Two throw-away schemas play the two machines, so real cached data is not touched."""
from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from app import cache_transfer as ct
from app import db

TAG = uuid.uuid4().hex[:8]
SRC, DST = f"test_xfer_src_{TAG}", f"test_xfer_dst_{TAG}"
TARGET = {"ra": 269.446, "dec": 4.768, "fov_deg": None, "pmra": None, "pmdec": None, "pm_epoch": None}


def url_for(schema: str) -> str:
    sep = "&" if "?" in db.DATABASE_URL else "?"
    return f"{db.DATABASE_URL}{sep}options=-csearch_path%3D{schema}"


def image(fid: str) -> dict:
    obs, _, det = fid.rpartition("-")
    return {"frame_id": fid, "obs_id": obs, "detector": det, "collection": "spherex_dr1", "t_mid_mjd": 60900.0,
            "access_url": f"https://example.invalid/{fid}.fits", "s_region": "POLYGON ICRS 1 2 3 4",
            "edge_margin_deg": 0.5, "x": 10.0, "y": 20.0, "wavelength_um": 1.3, "bandwidth_um": 0.03,
            "cloud_url": ""}


@pytest.fixture(scope="module")
def stores():
    try:
        with psycopg.connect(db.DATABASE_URL, connect_timeout=3, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA {SRC}")
            conn.execute(f"CREATE SCHEMA {DST}")
    except psycopg.OperationalError as err:
        pytest.skip(f"no database: {err}")
    src, dst = db.Store(url_for(SRC), max_size=2), db.Store(url_for(DST), max_size=2)
    yield src, dst
    src.close()
    dst.close()
    with psycopg.connect(db.DATABASE_URL, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA {SRC} CASCADE")
        conn.execute(f"DROP SCHEMA {DST} CASCADE")


@pytest.fixture(scope="module")
def archive(stores, tmp_path_factory) -> Path:
    src, _ = stores
    src.save_collections(["spherex_dr1", "spherex_qr3"])
    src.save_coverage("k1", TARGET, ["spherex_dr1"], 0, 1.7e9, [image("A_1-D1"), image("A_1-D2")])
    src.save_coverage("k2", TARGET, ["spherex_dr1"], 0, 1.7e9, [image("B_1-D1")])
    src.put_cutout("c1", "u1", b"\x00FITS-one\xff")
    src.put_cutout_failure("c2", "u2", "error", "503")
    src.put_file_layout("https://example.invalid/A_1-D1.fits", b"layout")
    src.put_calibration("dr1/spectral_wcs/x.fits", b"calibration bytes")
    analysis = tmp_path_factory.mktemp("analysis_src")
    (analysis / "examples" / "target_a" / "products").mkdir(parents=True)
    (analysis / "examples" / "target_a" / "latest.json").write_text('{"complete": true}')
    out = tmp_path_factory.mktemp("archive") / "cache.tar.gz"
    ct.export_cache(out, url=url_for(SRC), analysis_dir=analysis, say=lambda *_: None)
    return out


def test_import_into_an_empty_database_is_an_exact_copy(stores, archive, tmp_path):
    _, dst = stores
    assert ct.is_empty(url_for(DST))
    ct.import_cache(archive, url=url_for(DST), analysis_dir=tmp_path, say=lambda *_: None)
    assert not ct.is_empty(url_for(DST))
    assert dst.collections()[0] == ["spherex_dr1", "spherex_qr3"]
    assert [i["frame_id"] for i in dst.load_coverage("k1")["images"]] == ["A_1-D1", "A_1-D2"]
    assert [i["frame_id"] for i in dst.load_coverage("k2")["images"]] == ["B_1-D1"]
    assert dst.cutout("c1") == b"\x00FITS-one\xff"
    assert dst.cutout_states(["c2"])["c2"][0] == "error"
    assert dst.file_layout("https://example.invalid/A_1-D1.fits") == b"layout"
    assert dst.calibration("dr1/spectral_wcs/x.fits") == b"calibration bytes"
    assert (tmp_path / "examples" / "target_a" / "latest.json").read_text() == '{"complete": true}'


def test_importing_again_changes_nothing_and_keeps_local_work(stores, archive, tmp_path):
    _, dst = stores
    # local work that must survive: a newer search result with fewer images, and a failure the archive can fill in
    dst.save_coverage("k1", TARGET, ["spherex_dr1"], 0, 1.9e9, [image("A_1-D1")])
    dst.put_cutout_failure("c1", "u1", "error", "local failure")
    (tmp_path / "examples" / "target_a").mkdir(parents=True)
    (tmp_path / "examples" / "target_a" / "latest.json").write_text("local")
    ct.import_cache(archive, url=url_for(DST), analysis_dir=tmp_path, say=lambda *_: None)
    assert [i["frame_id"] for i in dst.load_coverage("k1")["images"]] == ["A_1-D1"]  # newer local one kept
    assert dst.cutout("c1") == b"\x00FITS-one\xff"  # a downloaded cutout beats a failure record
    assert (tmp_path / "examples" / "target_a" / "latest.json").read_text() == "local"  # existing folder kept


def test_replace_makes_an_exact_copy(stores, archive, tmp_path):
    _, dst = stores
    ct.import_cache(archive, replace=True, url=url_for(DST), analysis_dir=tmp_path, say=lambda *_: None)
    assert [i["frame_id"] for i in dst.load_coverage("k1")["images"]] == ["A_1-D1", "A_1-D2"]
    assert (tmp_path / "examples" / "target_a" / "latest.json").read_text() == '{"complete": true}'


def test_seed_only_fills_an_empty_database(stores, archive, tmp_path):
    with psycopg.connect(db.DATABASE_URL, autocommit=True) as conn:
        conn.execute(f"TRUNCATE {SRC}.coverage, {SRC}.cutout CASCADE")
    assert ct.seed_if_empty(str(archive), url=url_for(SRC), analysis_dir=tmp_path) is True
    assert ct.seed_if_empty(str(archive), url=url_for(SRC), analysis_dir=tmp_path) is False  # not empty any more
    assert ct.seed_if_empty(None, url=url_for(SRC)) is False  # nothing configured


def test_seed_never_raises(stores, tmp_path):
    with psycopg.connect(db.DATABASE_URL, autocommit=True) as conn:
        conn.execute(f"TRUNCATE {SRC}.coverage, {SRC}.cutout CASCADE")
    assert ct.seed_if_empty(str(tmp_path / "missing.tar.gz"), url=url_for(SRC)) is False
