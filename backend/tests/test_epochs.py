"""Offline tests of the epoch-map pipeline (app/epochs.py) with synthetic data. Nothing talks to IRSA.
The important one: a CONSTANT star with a steep spectrum must not look changed when the epochs cover
different spectral channels or have different numbers of exposures.
Run from backend/:  .venv/bin/python -m pytest tests/test_epochs.py -q"""
from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import epochs
from app.main import app

H = W = 21
C = 4
SPECTRUM = np.array([1.0, 2.0, 4.0, 8.0])  # steep: each channel twice as bright as the one before


def star(amp: float, x0: float = 10.0, y0: float = 10.0) -> np.ndarray:
    y, x = np.mgrid[0:H, 0:W]
    return amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / 4.0)


def cube(n_epochs: int, missing: dict[int, list[int]], rng, amp=None, shift=None):
    """(E, C, H, W) channel images of one star; `missing[e]` = channels without data in epoch e."""
    I = np.full((n_epochs, C, H, W), np.nan, np.float32)
    V = np.full_like(I, np.nan)
    N = np.zeros(I.shape, np.uint8)
    for e in range(n_epochs):
        for c in range(C):
            if c in missing.get(e, []):
                continue
            a = 100 * SPECTRUM[c] * (amp[e] if amp else 1.0)
            I[e, c] = star(a, 10.0 + (shift[e] if shift else 0.0)) + rng.normal(0, 0.1, (H, W))
            V[e, c] = 0.01
            N[e, c] = 1
    return I, V, N


def info():
    return [{"detector": "D1", "channel": c + 1, "wavelength_um": 1 + 0.1 * c, "wl_min_um": 0.95 + 0.1 * c,
             "wl_max_um": 1.05 + 0.1 * c} for c in range(C)]


def exposures(n_epochs):
    return [{"epoch": e, "mjd": 60000.0 + 180 * e + k, "wavelength_um": 1.0, "saturated": False, "file": f"f{e}{k}.fits",
             "bunit": "MJy/sr"} for e in range(n_epochs) for k in range(2)]


def rgba(png: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(png)).convert("RGBA"))


def test_pick_rgb():
    assert epochs.pick_rgb([])["mode"] == "no_data"
    assert epochs.pick_rgb([1.0]) == {"mode": "one_epoch", "red": 0, "green": 0, "blue": 0}
    assert epochs.pick_rgb([1.0, 2.0]) == {"mode": "two_epochs", "red": 0, "green": 1, "blue": 1}
    # green = the epoch closest in time to the middle between first and last, not the middle of the list
    assert epochs.pick_rgb([0.0, 10.0, 20.0, 95.0, 100.0]) == {"mode": "three_epochs", "red": 0, "green": 2, "blue": 4}


def test_constant_steep_star_stays_white_with_unequal_channel_coverage():
    rng = np.random.default_rng(1)
    I, V, N = cube(3, {1: [3]}, rng)  # the middle epoch lacks the brightest channel
    meta, arr, pngs = epochs.make_bundle("D1", "detector", I, V, N, info(), [], exposures(3))
    assert meta["mode"] == "three_epochs" and meta["usable_epochs"] == [0, 1, 2]
    assert [c["channel"] for c in meta["channels"]] == [1, 2, 3]  # channel 4 is left out of EVERY epoch
    B = arr["image"]
    peak = B[:, 10, 10]
    assert np.allclose(peak, peak[0], rtol=0.01), peak  # a naive mean over the channels would differ by ~60 %
    naive = np.nanmean(I[:, :, 10, 10], axis=1)
    assert abs(naive[1] / naive[0] - 1) > 0.3  # ... as this shows
    px = rgba(pngs["rgb_D1.png"])[H - 1 - 10, 10]
    assert max(px[:3]) - min(px[:3]) <= 3 and px[3] == 255  # white/grey, not coloured
    assert abs(arr["diff"][10, 10]) < 1  # no difference at the star
    assert any("D1/4" in g for g in meta["gaps"])


def test_brightening_and_motion_are_seen():
    rng = np.random.default_rng(2)
    I, V, N = cube(3, {}, rng, amp=[1.0, 1.0, 2.0])
    meta, arr, pngs = epochs.make_bundle("D1", "detector", I, V, N, info(), [], exposures(3))
    assert arr["diff"][10, 10] > 3  # twice as bright in the last epoch: clearly positive
    px = rgba(pngs["rgb_D1.png"])[H - 1 - 10, 10]
    assert px[2] > px[0]  # the last epoch is blue
    d = rgba(pngs["diff_D1.png"])[H - 1 - 10, 10]
    assert d[2] > d[0]  # brighter = blue in the difference image (as the latest epoch in the RGB)

    I, V, N = cube(2, {}, rng, shift=[0.0, 1.0])  # the star moves one pixel to +x between two epochs
    meta, arr, _ = epochs.make_bundle("D1", "detector", I, V, N, info(), [], exposures(2))
    assert meta["mode"] == "two_epochs"
    assert arr["diff"][10, 8] < -5 and arr["diff"][10, 13] > 5  # a dipole


def test_no_coverage_is_transparent_and_weak_epochs_are_dropped():
    rng = np.random.default_rng(3)
    I, V, N = cube(3, {0: [1, 2, 3]}, rng)  # epoch 0 has only 1 of 4 channels: not usable
    I[1, :, :, :3], N[1, :, :, :3] = np.nan, 0  # epoch 1 has no data in the three leftmost columns
    meta, arr, pngs = epochs.make_bundle("D1", "detector", I, V, N, info(), [], exposures(3))
    assert meta["usable_epochs"] == [1, 2] and meta["mode"] == "two_epochs"
    assert meta["rgb"]["red"]["epoch"] == 1 and meta["rgb"]["green"]["epoch"] == 2 and meta["diff"]["first"]["epoch"] == 1
    for name in ("rgb_D1.png", "diff_D1.png", "frame_D1_e2.png"):
        a = rgba(pngs[name])
        assert (a[:, :3, 3] == 0).all() and (a[:, 3:, 3] == 255).all(), name  # also in epoch 2, which has the data
    assert "frame_D1_e0.png" not in pngs

    I, V, N = cube(1, {}, rng)
    meta, _, pngs = epochs.make_bundle("D1", "detector", I, V, N, info(), [], exposures(1))
    assert meta["mode"] == "one_epoch" and meta["diff"] is None and "rgb_D1.png" in pngs
    I, V, N = cube(1, {0: [0, 1, 2, 3]}, rng)
    meta, _, pngs = epochs.make_bundle("D1", "detector", I, V, N, info(), [], exposures(1))
    assert meta["mode"] == "no_data" and meta["rgb"] is None and not pngs


def test_combine_channels_rejects_outliers_and_keeps_star_unbiased():
    X = np.full((4, 3, 3), 10.0)
    X[2, 1, 1] = 500.0  # a cosmic-ray hit in one of four exposures
    V = np.ones_like(X)
    Cmap = np.ones(X.shape, int)
    I, VV, N, rej = epochs.combine_channels(X, V, Cmap, np.ones(4), nchan=2)
    assert rej == 1 and N[0, 1, 1] == 3 and abs(I[0, 1, 1] - 10) < 1e-6
    assert N[1].sum() == 0 and np.isnan(I[1]).all()  # channel 2 saw nothing
    # two exposures only: nothing can be rejected, the mean is the plain mean (one weight per exposure,
    # although the brighter one has the larger variance)
    X2 = np.stack([np.full((3, 3), 100.0), np.full((3, 3), 140.0)])
    V2 = np.stack([np.full((3, 3), 1.0), np.full((3, 3), 4.0)])
    I, _, N, rej = epochs.combine_channels(X2, V2, np.ones(X2.shape, int), np.ones(2), nchan=1)
    assert rej == 0 and np.allclose(I[0], 120.0)


@pytest.fixture
def cached(tmp_path, monkeypatch):
    monkeypatch.setattr(epochs, "CACHE_ROOT", tmp_path)
    spec = epochs.spec_for("10.0", "20.0", None)
    rng = np.random.default_rng(4)
    I, V, N = cube(3, {}, rng, amp=[1.0, 1.0, 2.0])
    grid = {"width": W, "height": H}
    meta = {"pipeline_version": epochs.PIPELINE_VERSION, "complete": True, "grid": grid, "bundles": [],
            "epochs": [{"index": e, "time": "2026-01-01T00:00:00Z", "start": None, "end": None} for e in range(3)],
            "channel_table": info()}
    d = epochs.product_dir(spec, "epochmaps", epochs.epochmap_params())
    np.savez_compressed(d / "channels_D1.npz", image=I, variance=V, n=N)
    epochs._store_bundle(spec, meta, "D1", "detector", I, V, N, info(), [], exposures(3))
    return spec


def test_api_serves_from_cache_without_computing(cached, monkeypatch):
    monkeypatch.setattr(epochs, "run", lambda *a, **k: pytest.fail("a GET endpoint started a computation"))
    c = TestClient(app)
    q = {"ra": "10.0", "dec": "20.0"}
    assert c.get("/api/config").json()["default_fov"] == epochs.DEFAULT_FOV_DEG
    s = c.get("/api/epochs", params=q).json()
    assert s["status"] == "cached" and s["result"]["bundles"][0]["id"] == "D1" and s["default_fov"] == epochs.DEFAULT_FOV_DEG
    assert c.get("/api/epochs", params={"ra": "11.0", "dec": "20.0"}).json()["status"] == "not_computed"

    r = c.get("/api/rgb", params={**q, "bundle": "D1"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.headers["x-epoch-mode"] == "three_epochs"
    assert Image.open(io.BytesIO(r.content)).size == (W, H)
    assert Image.open(io.BytesIO(c.get("/api/rgb", params={**q, "bundle": "D1", "scale": 4}).content)).size == (4 * W, 4 * H)
    facts = c.get("/api/rgb", params={**q, "bundle": "D1", "format": "json"}).json()
    assert facts["mode"] == "three_epochs" and [u["colour"] for u in facts["epochs_used"]] == ["red", "green", "blue"]
    assert facts["wavelength_um"] == {"min": 0.95, "max": 1.35} and facts["detectors"] == ["D1"]

    assert c.get("/api/diff", params={**q, "bundle": "D1"}).status_code == 200
    assert c.get("/api/frame", params={**q, "bundle": "D1", "epoch": 2}).status_code == 200
    assert c.get("/api/frame", params={**q, "bundle": "D1", "epoch": 7}).json()["error"]["code"] == "epoch_not_usable"
    assert c.get("/api/rgb", params={**q, "bundle": "D5"}).json()["error"]["code"] == "unknown_bundle"
    assert c.get("/api/rgb", params={**q, "bundle": "channel"}).json()["error"]["code"] == "no_image_for_channels"
    assert c.get("/api/rgb", params={"ra": "11.0", "dec": "20.0"}).json()["error"]["code"] == "not_computed"

    sp = c.get("/api/spectrum", params={**q, "x": 10, "y": H - 1 - 10}).json()  # the star's pixel
    ch = sp["channels"]
    assert len(ch) == C and ch[3]["wavelength_um"] == 1.3 and len(ch[0]["epochs"]) == 3
    assert ch[3]["epochs"][0]["value"] == pytest.approx(800, rel=0.01) and ch[3]["epochs"][2]["value"] == pytest.approx(1600, rel=0.01)
    assert c.get("/api/spectrum", params={**q, "x": 99, "y": 0}).json()["error"]["code"] == "bad_pixel"


def test_compute_starts_once(tmp_path, monkeypatch):
    monkeypatch.setattr(epochs, "CACHE_ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(epochs, "run", lambda spec, refresh=False: calls.append(spec.key))
    c = TestClient(app)
    r = c.post("/api/compute", params={"ra": "10.0", "dec": "20.0"})
    assert r.status_code == 202 and r.json()["status"] == "running"
    epochs._threads[epochs.spec_for("10.0", "20.0", None).key].join(5)
    assert len(calls) == 1
    assert c.post("/api/compute", params={"ra": "10.0", "dec": "20.0"}).json()["status"] == "running"  # status file is fresh
    assert len(calls) == 1  # not started twice


def test_examples_and_temp_cache_are_separate_and_cleanup_spares_examples(tmp_path, monkeypatch):
    import os
    import time

    from app import precompute, presets

    monkeypatch.setattr(epochs, "CACHE_ROOT", tmp_path)
    example = precompute.spec_of(presets.find_preset("r_dra"))
    other = epochs.spec_for("10.0", "20.0", None)
    assert epochs._dir(example).parent.name == "examples" and epochs._dir(other).parent.name == "temp"
    assert "fov0.08000" in epochs._dir(other).name and epochs._dir(other).name.startswith("ra10.000000_dec+20.000000")
    # a different parameter set gets a different products directory, with the parameters stored next to the results
    a = epochs.product_dir(other, "epochmaps", {"x": 1})
    b = epochs.product_dir(other, "epochmaps", {"x": 2})
    assert a != b and epochs._read_json(a / "params.json") == {"x": 1}

    for spec in (example, other):
        (epochs._dir(spec) / "cutouts").mkdir(parents=True, exist_ok=True)
        (epochs._dir(spec) / "cutouts" / "a.fits").write_bytes(b"x" * 1000)
    assert epochs.cleanup_temp() == []  # fresh and small: nothing to do
    old = time.time() - (epochs.TEMP_TTL_HOURS + 1) * 3600
    for spec in (example, other):
        for f in [epochs._dir(spec), *epochs._dir(spec).rglob("*")]:
            os.utime(f, (old, old))
    assert epochs.cleanup_temp() == [epochs._dir(other).name]  # expired
    assert not epochs._dir(other).exists() and (epochs._dir(example) / "cutouts" / "a.fits").exists()

    (epochs._dir(other) / "cutouts").mkdir(parents=True)
    (epochs._dir(other) / "cutouts" / "a.fits").write_bytes(b"x" * 1000)
    monkeypatch.setattr(epochs, "TEMP_MAX_MB", 0.0005)  # 500 bytes: over the size limit
    assert epochs.cleanup_temp() == [epochs._dir(other).name]
    assert (epochs._dir(example) / "cutouts" / "a.fits").exists()


def test_spectrum_is_stored_after_the_first_request(cached):
    first = epochs.spectrum(cached, 10, 10)
    stored = epochs._products(cached) / "spectrum" / "x10_y10.json"
    assert stored.exists() and epochs.spectrum(cached, 10, 10) == first


def test_single_channel_spike_is_dropped_in_every_epoch():
    rng = np.random.default_rng(5)
    C6 = 6
    I = rng.normal(0, 0.1, (3, C6, H, W)).astype(np.float32) + star(50.0)  # flat spectrum
    V = np.full_like(I, 0.01)
    N = np.ones(I.shape, np.uint8)
    I[2, 4, 5, 5] += 30.0  # a cosmic-ray hit in one channel of the last epoch, on empty sky
    ci = [{"detector": "D1", "channel": c + 1, "wavelength_um": 1.0, "wl_min_um": 0.9, "wl_max_um": 1.1} for c in range(C6)]
    meta, arr, _ = epochs.make_bundle("D1", "detector", I, V, N, ci, [], exposures(3))
    assert meta["spikes_rejected"] == 1 and arr["channels_per_pixel"][5, 5] == C6 - 1
    assert abs(arr["diff"][5, 5]) < 4 and abs(arr["image"][2, 5, 5]) < 0.5  # no false signal
    assert arr["channels_per_pixel"][10, 10] == C6  # the star keeps all its channels
