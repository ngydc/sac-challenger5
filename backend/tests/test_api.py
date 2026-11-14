"""Offline tests of the MVP API contract (docs/API.md). Nothing here talks to IRSA or the name service:
coverage comes from a saved file, frames are synthetic, name lookups are faked.
Run from backend/:  .venv\\Scripts\\python -m pytest tests -q"""
from __future__ import annotations

import io
import threading
from concurrent.futures import Future

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import presets, resolver, spherex
from app import service as svc
from app.main import app
from app.service import AlignedFrame, ApiError, TargetSpec

client = TestClient(app)
POS = dict(ra="269.446", dec="4.768", fov="0.08")


def rec(obs: str, det: str, mjd: float) -> spherex.ImageRecord:
    return spherex.ImageRecord(obs_id=obs, detector=det, collection="spherex_dr1", t_mid_mjd=mjd,
                               access_url=f"https://example.invalid/ibe/data/spherex/dr1/{obs}{det}.fits", s_region="")


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    """Empty service state, with the saved-coverage folder and cutout cache redirected to a temp dir."""
    monkeypatch.setattr(svc, "STATE_DIR", tmp_path / "coverage")
    monkeypatch.setattr(spherex, "CACHE_DIR", tmp_path / "cutouts")
    monkeypatch.setattr(svc.service, "_cov", {})
    monkeypatch.setattr(svc.service, "_inflight", {})
    monkeypatch.setattr(svc.service, "_failures", {})
    return tmp_path


def seed_coverage(spec: TargetSpec) -> list[spherex.ImageRecord]:
    """Save a finished coverage to disk, as a previous visit would have done: 2 visits, 3 detectors."""
    recs = [rec("A_1", "D1", 60900.0), rec("A_2", "D2", 60900.1), rec("A_3", "D5", 60900.2),
            rec("B_1", "D1", 61100.0), rec("B_2", "D2", 61100.1)]
    wls = {"A_1-D1": 0.9, "A_2-D2": 1.3, "A_3-D5": 4.2, "B_1-D1": 0.95, "B_2-D2": 1.35}
    cov = svc.Coverage(spec, state="ready", collections=["spherex_dr1"], data_as_of=1.7e9)
    cov.records = {svc.frame_id(r): r for r in recs}
    cov.exposures = [spherex.Exposure(r, 10.0, 20.0, wls[svc.frame_id(r)], 0.03) for r in recs]
    svc.service._index_visits(cov, recs)
    svc.service._save(cov)
    return recs


# --- target parameters -----------------------------------------------------------------------
@pytest.mark.parametrize("ra,dec", [("269.452", "4.693"), ("17h57m48.5s", "+04d41m36s"), ("17:57:48.5", "+4:41:36")])
def test_parse_coord_accepts_degrees_and_sexagesimal(ra, dec):
    r, d = svc.parse_coord(ra, dec)
    assert r == pytest.approx(269.452, abs=0.002) and d == pytest.approx(4.693, abs=0.002)


@pytest.mark.parametrize("kw,code", [
    (dict(ra="abc", dec="4", fov=0.08, pmra=None, pmdec=None, pm_epoch=None), "bad_coordinates"),
    (dict(ra="10", dec="95", fov=0.08, pmra=None, pmdec=None, pm_epoch=None), "bad_coordinates"),
    (dict(ra="10", dec="4", fov=5.0, pmra=None, pmdec=None, pm_epoch=None), "bad_fov"),
    (dict(ra="10", dec="4", fov=0.08, pmra=3.0, pmdec=None, pm_epoch=None), "bad_motion"),
    (dict(ra="10", dec="4", fov=0.08, pmra=3.0, pmdec=4.0, pm_epoch=None), "bad_motion"),  # pm_epoch is required with the motion
])
def test_target_validation(kw, code):
    with pytest.raises(ApiError) as e:
        TargetSpec.build(**kw)
    assert e.value.code == code and e.value.status == 400


def test_frame_id_round_trip_and_rejection():
    assert svc.split_frame_id("2025W35_2A_0611_1-D2") == ("2025W35_2A_0611_1", "D2")
    for bad in ("nonsense", "-D2", "abc-D", "abc-X2"):
        with pytest.raises(ApiError):
            svc.split_frame_id(bad)


# --- resolve: coordinates --------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("269.452 4.693", (269.452, 4.693)),
    ("269.452, 4.693", (269.452, 4.693)),
    ("17h57m48.5s +04d41m36s", (269.452, 4.693)),
    ("17:57:48.5 +04:41:36", (269.452, 4.693)),
    ("17 57 48.5 +04 41 36", (269.452, 4.693)),
    ("08h55m10.831s -07d14m42.53s", (133.7951, -7.2451)),  # the WISE 0855 example from the challenge text
])
def test_coordinates_in_all_common_forms(text, expected):
    ra, dec = resolver.parse_coordinate_pair(text)
    assert ra == pytest.approx(expected[0], abs=0.002) and dec == pytest.approx(expected[1], abs=0.002)


@pytest.mark.parametrize("text", ["Barnard's Star", "WISE 0855", "WISE 0855-0714", "R Dra", "M 31", "GJ 699", "HD 209100", "eps Ind B"])
def test_names_are_not_mistaken_for_coordinates(text):
    assert resolver.parse_coordinate_pair(text) is None


def test_coordinates_out_of_range():
    with pytest.raises(ApiError) as e:
        resolver.parse_coordinate_pair("10 95")
    assert e.value.code == "bad_coordinates"


def test_resolve_typed_coordinates_have_no_motion():
    d = client.get("/api/resolve", params={"q": "08h55m10.831s -07d14m42.53s"}).json()
    t = d["target"]
    assert d["kind"] == "coordinates" and t["name"] is None and t["pmra"] is None and t["pm_epoch"] is None
    assert t["ra"] == pytest.approx(133.7951, abs=1e-3) and t["dec"] == pytest.approx(-7.2451, abs=1e-3) and t["fov"] == 0.08
    assert d["warnings"] == [] and d["query"] == "08h55m10.831s -07d14m42.53s"


# --- resolve: names --------------------------------------------------------------------------
@pytest.mark.parametrize("q", ["Barnard's Star", "barnards star", "BARNARD STAR", "GJ 699", "gj699"])
def test_resolve_local_name_with_motion_moved_to_the_view_epoch(q):
    d = client.get("/api/resolve", params={"q": q}).json()
    t = d["target"]
    year = presets.view_epoch()
    assert d["kind"] == "preset" and t["name"] == "Barnard's Star" and t["pm_epoch"] == year
    assert (t["pmra"], t["pmdec"]) == (-801.551, 10362.394)
    moved = np.hypot((t["ra"] - 269.45208) * np.cos(np.radians(4.69)), t["dec"] - 4.69336) * 60  # arcmin
    assert moved == pytest.approx(10.39 * (year - 2000) / 60, rel=0.02)  # 10.39 arcsec/yr
    assert len(d["warnings"]) == 1 and "arcmin" in d["warnings"][0]


@pytest.mark.parametrize("q,name", [("WISE 0855", "WISE 0855-0714"), ("wise 0855-0714", "WISE 0855-0714"),
                                    ("WISE J085510.83-071442.5", "WISE 0855-0714"), ("r dra", "R Draconis"),
                                    ("RW Aur", "RW Aurigae"), ("eps ind b", "Epsilon Indi B")])
def test_the_challenge_targets_resolve_under_their_usual_spellings(q, name):
    d = client.get("/api/resolve", params={"q": q}).json()
    assert d["kind"] == "preset" and d["target"]["name"] == name and d["target"]["note"]


def test_epsilon_indi_b_suggests_a_wider_field():
    assert client.get("/api/resolve", params={"q": "Epsilon Indi B"}).json()["target"]["fov"] == 0.2


SESAME_XML = """<?xml version="1.0"?><Sesame><Target option="SNV"><name>{q}</name>
<Resolver name="Sc=Simbad"><oid>1</oid>{body}</Resolver></Target></Sesame>"""
FOUND = "<jradeg>10.68470833</jradeg><jdedeg>41.26875</jdedeg><oname>M  31</oname>"
FOUND_PM = ("<jradeg>100.0</jradeg><jdedeg>10.0</jdedeg><oname>NAME Fast star</oname>"
            "<pm><pmRA>-2000.0</pmRA><pmDE>1000.0</pmDE></pm>")


class FakeResponse:
    def __init__(self, text: str, status: int = 200):
        self.text, self.content, self.status = text, text.encode(), status

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def fake_sesame(monkeypatch, handler):
    calls = []

    def get(url, **kw):
        calls.append(url)
        return handler(url)

    monkeypatch.setattr(resolver.httpx, "get", get)
    return calls


def test_resolve_a_name_from_the_name_service(monkeypatch):
    calls = fake_sesame(monkeypatch, lambda url: FakeResponse(SESAME_XML.format(q="M31", body=FOUND)))
    d = client.get("/api/resolve", params={"q": "M31"}).json()
    t = d["target"]
    assert d["kind"] == "name" and t["name"] == "M31"  # the name as typed...
    assert t["note"] is None  # ...and SIMBAD's "M  31" is the same name, so nothing to add
    assert (t["ra"], t["dec"]) == (10.684708, 41.26875) and t["pmra"] is None and t["pm_epoch"] is None and d["warnings"] == []
    assert calls[0].endswith("/-ox/SNV?M31")


def test_the_name_as_typed_is_shown_and_the_simbad_identifier_goes_in_the_note(monkeypatch):
    fake_sesame(monkeypatch, lambda url: FakeResponse(SESAME_XML.format(q="Vega", body="<jradeg>279.2</jradeg><jdedeg>38.8</jdedeg><oname>* alf Lyr</oname>")))
    t = client.get("/api/resolve", params={"q": "Vega"}).json()["target"]
    assert t["name"] == "Vega" and t["note"] == "SIMBAD identifier: alf Lyr"


def test_resolve_moves_a_name_with_proper_motion_and_warns(monkeypatch):
    fake_sesame(monkeypatch, lambda url: FakeResponse(SESAME_XML.format(q="x", body=FOUND_PM)))
    d = client.get("/api/resolve", params={"q": "Fast star"}).json()
    t = d["target"]
    years = presets.view_epoch() - 2000
    assert t["name"] == "Fast star" and t["pm_epoch"] == presets.view_epoch() and t["pmra"] == -2000.0
    assert t["dec"] == pytest.approx(10.0 + 1000.0 * years / 3.6e6, abs=1e-5)
    assert "arcmin" in d["warnings"][0]


def test_unknown_name_is_a_404(monkeypatch):
    fake_sesame(monkeypatch, lambda url: FakeResponse('<Sesame><Target><INFO>Nothing found</INFO></Target></Sesame>'))
    r = client.get("/api/resolve", params={"q": "xyzzy"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "name_not_found"


def test_second_mirror_is_used_when_the_first_is_down(monkeypatch):
    def handler(url):
        if url.startswith(resolver.SESAME_MIRRORS[0]):
            raise httpx.ConnectError("down")
        return FakeResponse(SESAME_XML.format(q="M31", body=FOUND))

    calls = fake_sesame(monkeypatch, handler)
    assert client.get("/api/resolve", params={"q": "M31"}).json()["target"]["name"] == "M31"
    assert len(calls) == 2


def test_name_service_down_is_a_502_but_local_names_still_work(monkeypatch):
    def down(url):
        raise httpx.ConnectError("down")

    fake_sesame(monkeypatch, down)
    r = client.get("/api/resolve", params={"q": "M31"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "resolver_unavailable"
    assert client.get("/api/resolve", params={"q": "R Dra"}).status_code == 200  # no web lookup needed


def test_resolve_input_errors():
    assert client.get("/api/resolve", params={"q": "  "}).json()["error"]["code"] == "bad_query"
    assert client.get("/api/resolve", params={"q": "x" * 200}).json()["error"]["code"] == "bad_query"
    r = client.get("/api/resolve")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


# --- the contract is exactly the MVP ---------------------------------------------------------
def test_only_the_three_mvp_endpoints_exist():
    paths = set(app.openapi()["paths"])
    assert paths == {"/api/resolve", "/api/coverage", "/api/frames/{frame_id}/image.png"}
    for gone in ("/api/presets", "/api/status", "/api/frames/A-D1/pixels"):
        assert client.get(gone).status_code == 404
    assert client.post("/api/prefetch", json={}).status_code == 404


def test_errors_share_one_shape():
    for url, status, code in [("/api/coverage?dec=4", 422, "invalid_request"),
                              ("/api/coverage?ra=1&dec=4&fov=9", 400, "bad_fov"),
                              ("/api/coverage?ra=1&dec=4&pmra=3", 400, "bad_motion"),
                              ("/api/frames/nonsense/image.png?ra=1&dec=4", 400, "bad_frame_id")]:
        r = client.get(url)
        assert r.status_code == status and r.json()["error"]["code"] == code, url


# --- coverage --------------------------------------------------------------------------------
def test_coverage_from_saved_state(fresh):
    spec = TargetSpec.build(POS["ra"], POS["dec"], 0.08, None, None, None)
    seed_coverage(spec)
    r = client.get("/api/coverage", params=POS)
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"target", "state", "message", "progress", "grid", "visits", "wavelength_range_um", "frames"}
    assert d["state"] == "ready" and d["progress"] == {"located": 5, "total": 5}
    assert d["target"] == {"ra": 269.446, "dec": 4.768, "fov": 0.08, "pmra": None, "pmdec": None, "pm_epoch": None}
    assert [v["n_frames"] for v in d["visits"]] == [3, 2] and [v["index"] for v in d["visits"]] == [0, 1]
    assert d["wavelength_range_um"] == [0.9, 4.2]
    assert [f["wavelength_um"] for f in d["frames"]][:3] == [0.9, 1.3, 4.2]  # sorted by visit, then wavelength
    assert [f["visit"] for f in d["frames"]] == [0, 0, 0, 1, 1]
    assert set(d["frames"][0]) == {"id", "visit", "detector", "wavelength_um", "bandwidth_um", "time", "release", "cache"}
    assert all(f["cache"] == "missing" for f in d["frames"])
    assert d["grid"]["width"] == d["grid"]["height"] == 47


def test_coverage_gives_the_predicted_target_per_visit_when_motion_is_given(fresh):
    spec = TargetSpec.build(POS["ra"], POS["dec"], 0.08, 100.0, 10000.0, 2026.0)
    seed_coverage(spec)
    d = client.get("/api/coverage", params={**POS, "pmra": 100.0, "pmdec": 10000.0, "pm_epoch": 2026.0}).json()
    t0, t1 = (v["target"] for v in d["visits"])
    assert t1["dec"] > t0["dec"]  # moving north, so later visits are further north
    assert d["target"]["pm_epoch"] == 2026.0


# --- frames ----------------------------------------------------------------------------------
def synthetic_frame(record: spherex.ImageRecord, n: int = 47) -> AlignedFrame:
    rng = np.random.default_rng(1)
    raw = rng.normal(10, 1, (n, n)).astype(np.float32)
    raw[20:23, 20:23] = 500  # a bright "star"
    bad = np.zeros((n, n), bool)
    bad[5, 5] = True
    raw[0, 0] = np.nan  # no data
    img = raw.copy()
    img[bad] = np.nan
    return AlignedFrame(svc.frame_id(record), record, img, raw, bad, (21.5, 21.5), 1.3, 0.03, ["OVERFLOW"], "7.0.5")


def serve_synthetic(monkeypatch):
    monkeypatch.setattr(svc.service, "record_for", lambda spec, fid: rec(fid.rpartition("-")[0], fid.rpartition("-")[2], 60900.0))
    monkeypatch.setattr(svc.service, "ensure_cutout", lambda spec, record, priority: None)
    monkeypatch.setattr(svc.service, "aligned_frame", lambda spec, record: synthetic_frame(record))


def test_image_png_and_headers(fresh, monkeypatch):
    from PIL import Image
    serve_synthetic(monkeypatch)
    r = client.get("/api/frames/A_1-D2/image.png", params={**POS, "scale": 2})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    h = r.headers
    assert h["x-frame-id"] == "A_1-D2" and h["x-wavelength-um"] == "1.3000" and h["x-bandwidth-um"] == "0.0300"
    assert h["x-time-utc"].endswith("Z") and h["x-flags-at-target"] == "OVERFLOW" and h["x-image-size"] == "47"
    assert (h["x-target-x"], h["x-target-y"]) == ("21.50", "21.50") and "max-age" in h["cache-control"]
    assert float(h["x-stretch-min"]) < float(h["x-stretch-max"])
    assert Image.open(io.BytesIO(r.content)).size == (94, 94)


def test_masked_pixels_are_red_unless_mask_is_off(fresh, monkeypatch):
    from PIL import Image
    serve_synthetic(monkeypatch)

    def pic(**kw):
        return np.array(Image.open(io.BytesIO(client.get("/api/frames/A_1-D2/image.png", params={**POS, **kw}).content)))

    masked, unmasked = pic(), pic(mask="false")
    y = 47 - 1 - 5  # row 0 of the data is the bottom row of the picture
    assert tuple(masked[y, 5]) == svc.MASK_RGB and tuple(unmasked[y, 5]) != svc.MASK_RGB
    assert tuple(masked[46, 0]) == svc.NODATA_RGB  # the NaN corner


def test_a_fixed_brightness_range_is_used_and_reported_back(fresh, monkeypatch):
    serve_synthetic(monkeypatch)
    own = client.get("/api/frames/A_1-D2/image.png", params=POS)
    fixed = client.get("/api/frames/A_1-D2/image.png", params={**POS, "vmin": 0, "vmax": 1000})
    assert (fixed.headers["x-stretch-min"], fixed.headers["x-stretch-max"]) == ("0", "1000")
    assert own.headers["x-stretch-max"] != "1000" and own.content != fixed.content
    # reusing the first frame's own range reproduces the first picture exactly
    again = client.get("/api/frames/A_1-D2/image.png", params={**POS, "vmin": own.headers["x-stretch-min"], "vmax": own.headers["x-stretch-max"]})
    assert again.content == own.content


def test_vmin_without_vmax_is_rejected_before_any_download(fresh, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(svc.service, "ensure_cutout", boom)
    r = client.get("/api/frames/A_1-D2/image.png", params={**POS, "vmin": 1})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_stretch"


def test_pending_frame_returns_202_with_retry_after(fresh, monkeypatch):
    monkeypatch.setattr(svc.service, "record_for", lambda spec, fid: rec("A_1", "D2", 60900.0))
    monkeypatch.setattr(svc.service, "ensure_cutout", lambda spec, record, priority: Future())  # never finishes
    r = client.get("/api/frames/A_1-D2/image.png", params={**POS, "wait": "0.1"})
    assert r.status_code == 202 and r.headers["retry-after"] == "3"
    assert r.json()["status"] in ("queued", "fetching", "missing") and r.json()["frame_id"] == "A_1-D2"


def test_outside_image_is_a_404(fresh, monkeypatch):
    fut: Future = Future()
    fut.set_exception(spherex.OutsideImageError("x"))
    monkeypatch.setattr(svc.service, "record_for", lambda spec, fid: rec("A_1", "D2", 60900.0))
    monkeypatch.setattr(svc.service, "ensure_cutout", lambda spec, record, priority: fut)
    r = client.get("/api/frames/A_1-D2/image.png", params=POS)
    assert r.status_code == 404 and r.json()["error"]["code"] == "outside_image"


# --- queue -----------------------------------------------------------------------------------
def test_job_queue_runs_waiting_user_before_background_work():
    q = svc.JobQueue(1)
    gate, order = threading.Event(), []
    first = q.submit(1, lambda: gate.wait(5))  # occupies the only worker
    f_bg = q.submit(1, lambda: order.append("background"))
    f_user = q.submit(0, lambda: order.append("user"))
    gate.set()
    for f in (first, f_bg, f_user):
        f.result(5)
    assert order == ["user", "background"]
