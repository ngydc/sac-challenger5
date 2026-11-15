"""Offline tests of the deep analysis as a job (app/analysis_jobs.py) and its API (app/analysis_api.py).

A fake service stands in for app/service.py: a fixed coverage, a cutout store that answers at once (or when
released), and records which downloads were asked for at which priority. The reprojection is faked too (its
maths is tested in test_analysis.py), so these tests are about where data comes from and goes to, the job
states, and the HTTP contract.
"""
from __future__ import annotations

import io
import os
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from app import analysis, analysis_api, analysis_jobs, spherex
from app.core import TargetSpec, frame_id
from app.main import app
from app.service import PRIORITY_ANALYSIS

H = W = 21  # grid of fov 0.03 deg at 6.15 arcsec per pixel
C = 3  # channels per detector
FOV = 0.035
Q = {"ra": "10.0", "dec": "20.0", "fov": str(FOV)}
SPEC = TargetSpec.build(Q["ra"], Q["dec"], FOV, None, None, None)


def record(i: int, epoch: int) -> spherex.ImageRecord:
    return spherex.ImageRecord(f"E{epoch}_{i}", "D1", "spherex_dr1", 60000.0 + 180 * epoch + i,
                               f"https://irsa.invalid/ibe/data/spherex/dr1/f{epoch}_{i}.fits", "", 1.0)


def coverage_records(n_epochs: int = 3) -> dict:
    return {frame_id(r): r for e in range(n_epochs) for i in range(C) for r in [record(i, e)]}


def cutout_bytes() -> bytes:
    """Only opened and checked for VARIANCE; the reprojection itself is faked."""
    buf = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.zeros((2, 2), np.float32), name="IMAGE"),
                  fits.ImageHDU(np.ones((2, 2), np.float32), name="VARIANCE")]).writeto(buf)
    return buf.getvalue()


class FakeService:
    def __init__(self, records: dict):
        self.records = records
        self.asked: list[tuple[str, int]] = []  # (frame id, priority) of every download requested
        self.gate: threading.Event | None = None  # when set: downloads wait for it
        self.db = None
        self.http = None

    def coverage(self, spec, all_images=False):
        return SimpleNamespace(state="ready", message=None, records=dict(self.records), collections=["spherex_dr1"],
                               data_as_of=1.7e9, located=len(self.records), total=len(self.records))

    def ensure_cutout(self, spec, rec, priority):
        self.asked.append((frame_id(rec), priority))
        if self.gate is None:
            return None  # "already stored"
        fut: Future = Future()
        gate = self.gate
        threading.Thread(target=lambda: (gate.wait(5), fut.set_result(None)), daemon=True).start()
        return fut

    def cutout_data(self, spec, rec):
        return cutout_bytes()


def star(amp: float, x0: float = 10.0, y0: float = 6.0) -> np.ndarray:
    y, x = np.mgrid[0:H, 0:W]
    return amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / 4.0)


def fake_reproject(hdul, rec, spec, channel_map):
    """Exposure i of epoch e covers channel i+1 everywhere; the star brightens in the last epoch."""
    epoch, i = int(rec.obs_id[1]), int(rec.obs_id.split("_")[1])
    amp = 200.0 if epoch == 2 else 100.0
    meta = {"frame_id": frame_id(rec), "file": rec.access_url.rsplit("/", 1)[-1], "detector": rec.detector,
            "collection": rec.collection, "mjd": rec.t_mid_mjd, "wavelength_um": 1.0, "bandwidth_um": 0.02,
            "flags_near_target": [], "saturated": False, "version": "7", "bunit": "MJy/sr", "background": 0.0,
            "valid_fraction": 1.0, "median_variance": 0.01, "flagged_pixels": {}, "cutout_pixels": 4}
    return {"img": (star(amp) + np.random.default_rng(i + 10 * epoch).normal(0, 0.1, (H, W))).astype(np.float32),
            "var": np.full((H, W), 0.01, np.float32), "chan": np.full((H, W), i + 1, np.int16), "meta": meta}


ROWS = [{"DETECTOR": 1, "SUBCHAN": c, "WAVELENGTH": 0.8 + 0.05 * c, "WL_MIN": 0.78 + 0.05 * c, "WL_MAX": 0.82 + 0.05 * c}
        for c in range(1, C + 1)]


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    svc = FakeService(coverage_records())
    jobs = analysis_jobs.AnalysisService(svc, root=tmp_path, max_jobs=2)
    monkeypatch.setattr(analysis_api, "jobs", jobs)
    monkeypatch.setattr(analysis, "reproject_cutout", fake_reproject)
    monkeypatch.setattr(spherex, "calibration_keys", lambda client, rel, product: [f"{rel}/{product}/v1/x.fits"])
    monkeypatch.setattr(spherex, "load_calibration",
                        lambda client, cache, key, kind, parse: {"map": None, "nchan": C, "rows": ROWS})
    return svc, jobs, TestClient(app)


def wait_ready(c: TestClient, params=Q, timeout=10.0) -> dict:
    t0 = time.time()
    while True:
        d = c.get("/api/analysis", params={**params, "start": "false"}).json()
        if d["state"] in ("ready", "error") and not d["refreshing"]:
            return d
        assert time.time() - t0 < timeout, d
        time.sleep(0.05)


def test_start_false_only_reports(setup):
    svc, jobs, c = setup
    d = c.get("/api/analysis", params={**Q, "start": "false"}).json()
    assert d["state"] == "idle" and d["result"] is None and d["progress"] is None and svc.asked == []
    assert d["target"] == {"ra": 10.0, "dec": 20.0, "fov": FOV, "pmra": None, "pmdec": None, "pm_epoch": None}
    assert d["kept"] is False


def test_analysis_uses_the_shared_store_and_serves_the_pictures(setup):
    svc, jobs, c = setup
    d = c.get("/api/analysis", params=Q).json()  # start=true is the default
    assert d["state"] in ("queued", "running")
    d = wait_ready(c)
    r = d["result"]
    assert d["state"] == "ready" and r["complete"] and r["n_images"] == 3 * C and len(r["epochs"]) == 3
    assert [b["id"] for b in r["bundles"]] == ["D1", "all"] and r["bundles"][0]["mode"] == "three_epochs"
    assert r["grid"]["orientation"].endswith("row 0 is the south edge")
    # every cutout came through the shared queue, at the analysis priority (below user and prefetch)
    assert sorted(svc.asked) == sorted((fid, PRIORITY_ANALYSIS) for fid in svc.records)

    diff = c.get("/api/analysis/D1/diff.png", params=Q)
    assert diff.status_code == 200 and diff.headers["content-type"] == "image/png" and diff.headers["etag"]
    again = c.get("/api/analysis/D1/diff.png", params=Q, headers={"If-None-Match": diff.headers["etag"]})
    assert again.status_code == 304
    assert c.get("/api/analysis/D1/rgb.png", params=Q).status_code == 200
    assert c.get("/api/analysis/all/epochs/2.png", params=Q).status_code == 200
    assert c.get("/api/analysis/D1/epochs/9.png", params=Q).json()["error"]["code"] == "no_data"
    assert c.get("/api/analysis/D5/diff.png", params=Q).json()["error"]["code"] == "unknown_bundle"
    assert c.get("/api/analysis/X9/diff.png", params=Q).status_code == 422
    other = {**Q, "ra": "11.0"}
    assert c.get("/api/analysis/D1/diff.png", params=other).json()["error"]["code"] == "not_ready"

    # spectrum: y counts from the SOUTH edge, like the viewer's X-Target-Y (the star sits at grid row 6)
    sp = c.get("/api/analysis/spectrum", params={**Q, "x": 10, "y": 6}).json()
    assert len(sp["channels"]) == C and sp["channels"][0]["wavelength_um"] == 0.85
    vals = [e["value"] for e in sp["channels"][0]["epochs"]]
    assert vals[2] == pytest.approx(200, rel=0.02) and vals[0] == pytest.approx(100, rel=0.02)
    far = c.get("/api/analysis/spectrum", params={**Q, "x": 10, "y": H - 1 - 6}).json()
    assert abs(far["channels"][0]["epochs"][0]["value"]) < 5
    assert c.get("/api/analysis/spectrum", params={**Q, "x": 99, "y": 0}).json()["error"]["code"] == "bad_pixel"


def png_pixel(resp, x: int, y: int) -> np.ndarray:
    """RGBA of grid pixel (x, y), y counted from the south edge (PNG row 0 is the north edge)."""
    from PIL import Image

    return np.array(Image.open(io.BytesIO(resp.content)).convert("RGBA"))[H - 1 - y, x]


def test_step_pictures_show_a_brightness_change_back_and_forth(setup, monkeypatch):
    svc, jobs, c = setup

    def blink(hdul, rec, spec, channel_map):  # the star is bright, faint, bright again in the three epochs
        out = fake_reproject(hdul, rec, spec, channel_map)
        epoch = int(rec.obs_id[1])
        out["img"] = (out["img"] - star(200.0 if epoch == 2 else 100.0) + star([100.0, 40.0, 100.0][epoch])).astype(np.float32)
        return out

    monkeypatch.setattr(analysis, "reproject_cutout", blink)
    c.get("/api/analysis", params=Q)
    b = next(b for b in wait_ready(c)["result"]["bundles"] if b["id"] == "D1")
    assert [(s["step"], s["first"]["epoch"], s["last"]["epoch"], s["available"]) for s in b["diff_steps"]] == \
           [(0, 0, 1, True), (1, 1, 2, True)]

    total, s0 = c.get("/api/analysis/D1/diff.png", params=Q), c.get("/api/analysis/D1/steps/0.png", params=Q)
    assert s0.status_code == 200 and s0.headers["content-type"] == "image/png" and s0.headers["etag"]
    assert s0.content != total.content
    assert min(png_pixel(total, 10, 6)[:3]) > 200  # last minus first: nearly white at the star
    red = png_pixel(s0, 10, 6)
    assert red[0] > red[2] + 50  # step 0: brighter in the earlier epoch = red
    blue = png_pixel(c.get("/api/analysis/D1/steps/1.png", params=Q), 10, 6)
    assert blue[2] > blue[0] + 50
    assert c.get("/api/analysis/all/steps/1.png", params=Q).status_code == 200
    missing = c.get("/api/analysis/D1/steps/2.png", params=Q)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "no_data"
    assert "[0, 1]" in missing.json()["error"]["message"]
    assert c.get("/api/analysis/D1/steps/-1.png", params=Q).status_code == 422


def test_a_finished_analysis_is_not_redone_and_survives_a_restart(setup, tmp_path):
    svc, jobs, c = setup
    c.get("/api/analysis", params=Q)
    wait_ready(c)
    n = len(svc.asked)
    assert c.get("/api/analysis", params=Q).json()["state"] == "ready" and len(svc.asked) == n  # nothing started
    restarted = analysis_jobs.AnalysisService(svc, root=tmp_path)  # a backend restart: memory empty, files kept
    st = restarted.status(SPEC)
    assert st["state"] == "ready" and st["result"]["complete"]


def test_new_images_recompute_while_the_old_result_stays_visible(setup):
    svc, jobs, c = setup
    c.get("/api/analysis", params=Q)
    old = wait_ready(c)["result"]
    svc.records = coverage_records(4)  # the archive has a new epoch now
    svc.gate = threading.Event()  # hold the new downloads
    d = c.get("/api/analysis", params=Q).json()
    assert d["state"] == "ready" and d["refreshing"] is True and d["progress"] is not None
    d = c.get("/api/analysis", params={**Q, "start": "false"}).json()
    assert d["result"]["images_key"] == old["images_key"] and d["result"]["complete"]  # still the old one
    assert c.get("/api/analysis/D1/diff.png", params=Q).status_code == 200
    svc.gate.set()
    new = wait_ready(c)["result"]
    assert new["images_key"] != old["images_key"] and len(new["epochs"]) == 4
    folders = list((jobs.target_dir(SPEC) / "products").glob("*/*"))
    assert len(folders) == 1  # the old result was removed once the new one was complete


def test_partial_result_while_a_first_run_is_going_on(setup):
    svc, jobs, c = setup
    svc.gate = threading.Event()
    c.get("/api/analysis", params=Q)
    t0 = time.time()
    while True:
        d = c.get("/api/analysis", params={**Q, "start": "false"}).json()
        if d["progress"] and d["progress"]["stage"].startswith("D1"):
            break
        assert time.time() - t0 < 5
        time.sleep(0.02)
    assert d["state"] == "running" and d["progress"]["total"] == 3 * C
    svc.gate.set()
    assert wait_ready(c)["result"]["complete"]


def test_at_most_max_jobs_run_at_once(tmp_path, monkeypatch):
    svc = FakeService(coverage_records())
    svc.gate = threading.Event()
    jobs = analysis_jobs.AnalysisService(svc, root=tmp_path, max_jobs=1)
    monkeypatch.setattr(analysis, "reproject_cutout", fake_reproject)
    monkeypatch.setattr(spherex, "calibration_keys", lambda *a: ["dr1/spectral_channels/v1/x.fits"])
    monkeypatch.setattr(spherex, "load_calibration", lambda *a: {"map": None, "nchan": C, "rows": ROWS})
    a = SPEC
    b = TargetSpec.build("11.0", "20.0", FOV, None, None, None)
    assert jobs.status(a, start=True)["state"] in ("queued", "running")
    time.sleep(0.2)
    assert jobs.status(b, start=True)["state"] == "queued"  # the only slot is busy
    svc.gate.set()
    t0 = time.time()
    while jobs.status(b)["state"] != "ready":
        assert time.time() - t0 < 10
        time.sleep(0.05)
    assert jobs.status(a)["state"] == "ready"


def test_cleanup_removes_old_temp_results_only(tmp_path):
    jobs = analysis_jobs.AnalysisService(FakeService({}), root=tmp_path)
    temp = jobs.target_dir(SPEC)
    barnard = analysis_jobs.preset_specs()[0]
    kept = jobs.target_dir(barnard)
    assert temp.parent.name == "temp" and kept.parent.name == "examples" and analysis_jobs.is_example(barnard)
    for d in (temp, kept):
        (d / "reproj").mkdir(parents=True)
        (d / "reproj" / "a.npz").write_bytes(b"x" * 1000)
    assert jobs.cleanup_temp() == []
    old = time.time() - (analysis_jobs.TEMP_TTL_HOURS + 1) * 3600
    for d in (temp, kept):
        for f in [d, *d.rglob("*")]:
            os.utime(f, (old, old))
    assert jobs.cleanup_temp() == [temp.name] and not temp.exists() and kept.exists()


def test_the_api_takes_the_viewers_target_parameters():
    params = {p["name"] for p in app.openapi()["paths"]["/api/analysis"]["get"]["parameters"]}
    assert params == {"ra", "dec", "fov", "pmra", "pmdec", "pm_epoch", "start"}
    paths = {p for p in app.openapi()["paths"] if p.startswith("/api/analysis")}
    assert paths == {"/api/analysis", "/api/analysis/spectrum", "/api/analysis/{bundle}/diff.png",
                     "/api/analysis/{bundle}/rgb.png", "/api/analysis/{bundle}/epochs/{epoch}.png",
                     "/api/analysis/{bundle}/steps/{step}.png"}
    for gone in ("/api/config", "/api/epochs", "/api/compute", "/api/rgb", "/api/diff", "/api/frame", "/api/spectrum"):
        assert gone not in app.openapi()["paths"]


def test_precompute_tries_a_failed_target_again(setup, monkeypatch):
    svc, jobs, c = setup
    calls = {"n": 0}
    real = svc.coverage

    def flaky(spec, all_images=False):  # the image search fails the first time (IRSA down), then works
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(state="error", message="IRSA search failed: 502", records={}, collections=[],
                                   data_as_of=0.0, located=0, total=0)
        return real(spec, all_images)

    monkeypatch.setattr(svc, "coverage", flaky)
    monkeypatch.setattr(analysis_jobs, "ERROR_RETRY_S", 0.0)
    jobs.warm([SPEC], retries=2, retry_s=0.01)
    st = jobs.status(SPEC)
    assert st["state"] == "ready" and calls["n"] >= 2
