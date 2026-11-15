"""Offline tests of the epoch-map computation (app/analysis.py) with synthetic data. Nothing talks to IRSA.
The important one: a CONSTANT star with a steep spectrum must not look changed when the epochs cover
different spectral channels or have different numbers of exposures.
The job layer and the API (app/analysis_jobs.py, app/analysis_api.py) are tested in test_analysis_jobs.py.
Run from backend/:  .venv/Scripts/python -m pytest tests -q"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from app import analysis

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


# Fixed synthetic bundles whose "Total" difference (last - first usable epoch) was stored by the code BEFORE the
# step differences were added (tests/data/diff_total_reference.npz). The total must stay exactly the same.
REFERENCE = Path(__file__).parent / "data" / "diff_total_reference.npz"


def reference_cases() -> dict[str, tuple]:
    """name -> (I, V, N, number of epochs)."""
    return {
        "blink": (*cube(3, {}, np.random.default_rng(1), amp=[1.0, 0.4, 1.0]), 3),
        "gap": (*cube(4, {1: [0, 1, 2]}, np.random.default_rng(2), amp=[1.0, 1.5, 0.5, 1.0]), 4),
        "motion": (*cube(3, {0: [3]}, np.random.default_rng(3), amp=[1.0, 1.0, 2.0], shift=[0.0, 1.5, 3.0]), 3),
        "two": (*cube(2, {}, np.random.default_rng(4), amp=[1.0, 2.0]), 2),
    }


def reference_totals() -> dict[str, np.ndarray]:
    """What is compared: the float array and the decoded pixels of diff_D1.png (not the PNG file bytes)."""
    out = {}
    for name, (I, V, N, n) in reference_cases().items():
        _, arr, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(n))
        out[f"{name}_diff"], out[f"{name}_png"] = arr["diff"], rgba(pngs["diff_D1.png"])
    return out


def test_pick_rgb():
    assert analysis.pick_rgb([])["mode"] == "no_data"
    assert analysis.pick_rgb([1.0]) == {"mode": "one_epoch", "red": 0, "green": 0, "blue": 0}
    assert analysis.pick_rgb([1.0, 2.0]) == {"mode": "two_epochs", "red": 0, "green": 1, "blue": 1}
    # green = the epoch closest in time to the middle between first and last, not the middle of the list
    assert analysis.pick_rgb([0.0, 10.0, 20.0, 95.0, 100.0]) == {"mode": "three_epochs", "red": 0, "green": 2, "blue": 4}


def test_constant_steep_star_stays_white_with_unequal_channel_coverage():
    rng = np.random.default_rng(1)
    I, V, N = cube(3, {1: [3]}, rng)  # the middle epoch lacks the brightest channel
    meta, arr, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(3))
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
    meta, arr, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(3))
    assert arr["diff"][10, 10] > 3  # twice as bright in the last epoch: clearly positive
    px = rgba(pngs["rgb_D1.png"])[H - 1 - 10, 10]
    assert px[2] > px[0]  # the last epoch is blue
    d = rgba(pngs["diff_D1.png"])[H - 1 - 10, 10]
    assert d[2] > d[0]  # brighter = blue in the difference image (as the latest epoch in the RGB)

    I, V, N = cube(2, {}, rng, shift=[0.0, 1.0])  # the star moves one pixel to +x between two epochs
    meta, arr, _ = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(2))
    assert meta["mode"] == "two_epochs"
    assert arr["diff"][10, 8] < -5 and arr["diff"][10, 13] > 5  # a dipole


def test_no_coverage_is_transparent_and_weak_epochs_are_dropped():
    rng = np.random.default_rng(3)
    I, V, N = cube(3, {0: [1, 2, 3]}, rng)  # epoch 0 has only 1 of 4 channels: not usable
    I[1, :, :, :3], N[1, :, :, :3] = np.nan, 0  # epoch 1 has no data in the three leftmost columns
    meta, arr, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(3))
    assert meta["usable_epochs"] == [1, 2] and meta["mode"] == "two_epochs"
    assert meta["rgb"]["red"]["epoch"] == 1 and meta["rgb"]["green"]["epoch"] == 2 and meta["diff"]["first"]["epoch"] == 1
    for name in ("rgb_D1.png", "diff_D1.png", "frame_D1_e2.png"):
        a = rgba(pngs[name])
        assert (a[:, :3, 3] == 0).all() and (a[:, 3:, 3] == 255).all(), name  # also in epoch 2, which has the data
    assert "frame_D1_e0.png" not in pngs

    I, V, N = cube(1, {}, rng)
    meta, _, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(1))
    assert meta["mode"] == "one_epoch" and meta["diff"] is None and "rgb_D1.png" in pngs
    I, V, N = cube(1, {0: [0, 1, 2, 3]}, rng)
    meta, _, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(1))
    assert meta["mode"] == "no_data" and meta["rgb"] is None and not pngs


def test_combine_channels_rejects_outliers_and_keeps_star_unbiased():
    X = np.full((4, 3, 3), 10.0)
    X[2, 1, 1] = 500.0  # a cosmic-ray hit in one of four exposures
    V = np.ones_like(X)
    Cmap = np.ones(X.shape, int)
    I, VV, N, rej = analysis.combine_channels(X, V, Cmap, np.ones(4), nchan=2)
    assert rej == 1 and N[0, 1, 1] == 3 and abs(I[0, 1, 1] - 10) < 1e-6
    assert N[1].sum() == 0 and np.isnan(I[1]).all()  # channel 2 saw nothing
    # two exposures only: nothing can be rejected, the mean is the plain mean (one weight per exposure,
    # although the brighter one has the larger variance)
    X2 = np.stack([np.full((3, 3), 100.0), np.full((3, 3), 140.0)])
    V2 = np.stack([np.full((3, 3), 1.0), np.full((3, 3), 4.0)])
    I, _, N, rej = analysis.combine_channels(X2, V2, np.ones(X2.shape, int), np.ones(2), nchan=1)
    assert rej == 0 and np.allclose(I[0], 120.0)


def test_single_channel_spike_is_dropped_in_every_epoch():
    rng = np.random.default_rng(5)
    C6 = 6
    I = rng.normal(0, 0.1, (3, C6, H, W)).astype(np.float32) + star(50.0)  # flat spectrum
    V = np.full_like(I, 0.01)
    N = np.ones(I.shape, np.uint8)
    I[2, 4, 5, 5] += 30.0  # a cosmic-ray hit in one channel of the last epoch, on empty sky
    ci = [{"detector": "D1", "channel": c + 1, "wavelength_um": 1.0, "wl_min_um": 0.9, "wl_max_um": 1.1} for c in range(C6)]
    meta, arr, _ = analysis.make_bundle("D1", "detector", I, V, N, ci, [], exposures(3))
    assert meta["spikes_rejected"] == 1 and arr["channels_per_pixel"][5, 5] == C6 - 1
    assert abs(arr["diff"][5, 5]) < 4 and abs(arr["image"][2, 5, 5]) < 0.5  # no false signal
    assert arr["channels_per_pixel"][10, 10] == C6  # the star keeps all its channels


def test_total_difference_is_unchanged_by_the_steps():
    """The reference was stored with the code before the step differences existed: compared by value."""
    with np.load(REFERENCE) as ref:
        new = reference_totals()
        assert sorted(ref.files) == sorted(new)
        for k in ref.files:
            assert ref[k].dtype == new[k].dtype and np.array_equal(ref[k], new[k], equal_nan=True), k


def test_steps_show_a_brightness_change_back_and_forth():
    """Bright -> faint -> bright: last minus first is about zero at the star, the steps are not."""
    I, V, N, n = reference_cases()["blink"]
    meta, arr, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(n))
    assert abs(arr["diff"][10, 10]) < 1
    steps = meta["diff_steps"]
    assert [(s["step"], s["first"]["epoch"], s["last"]["epoch"], s["available"]) for s in steps] == \
           [(0, 0, 1, True), (1, 1, 2, True)]
    assert steps[0]["first"] == meta["diff"]["first"] and steps[1]["last"] == meta["diff"]["last"]  # same form
    assert arr["diff_s0"][10, 10] < -3 and arr["diff_s1"][10, 10] > 3  # fainter, then brighter again
    red, blue = rgba(pngs["diff_D1_s0.png"])[H - 1 - 10, 10], rgba(pngs["diff_D1_s1.png"])[H - 1 - 10, 10]
    assert red[0] > red[2] + 50 and blue[2] > blue[0] + 50  # red = brighter in the earlier epoch, blue = in the later
    white = rgba(pngs["diff_D1.png"])[H - 1 - 10, 10]
    assert min(white[:3]) > 200  # the total is nearly white there


def test_steps_join_neighbouring_usable_epochs_across_a_gap():
    I, V, N, n = reference_cases()["gap"]  # epoch 1 covers only 1 of 4 channels: not usable
    meta, arr, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(n))
    assert meta["usable_epochs"] == [0, 2, 3]
    assert [(s["first"]["epoch"], s["last"]["epoch"]) for s in meta["diff_steps"]] == [(0, 2), (2, 3)]
    assert {"diff_D1_s0.png", "diff_D1_s1.png"} <= set(pngs) and "diff_D1_s2.png" not in pngs
    assert meta["diff_steps"][0]["first"]["time"] == meta["epochs"][0]["time"]
    # amplitudes 1.0 -> (1.5, unused) -> 0.5 -> 1.0: fainter, then brighter
    assert arr["diff_s0"][10, 10] < -3 and arr["diff_s1"][10, 10] > 3


def test_two_epochs_give_one_step_equal_to_the_total_and_one_epoch_none():
    I, V, N, n = reference_cases()["two"]
    meta, arr, _ = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(n))
    assert len(meta["diff_steps"]) == 1 and np.array_equal(arr["diff_s0"], arr["diff"], equal_nan=True)
    I, V, N = cube(1, {}, np.random.default_rng(6))
    meta, arr, pngs = analysis.make_bundle("D1", "detector", I, V, N, info(), [], exposures(1))
    assert meta["diff_steps"] == [] and not any(k.startswith("diff_") for k in pngs)


# --- colour composite ---------------------------------------------------------------------------
def colour_case(rng):
    """3 epochs, 10 channels (two detectors) from 0.8 to 4.8 µm on a 41x41 field: four ordinary stars (falling spectrum), one red
    star (rising spectrum), a saturated core in epoch 0, a channel covering only the left part of the field,
    a cosmic-ray-like spike in one channel of epoch 1, and an epoch 2 with too few channels."""
    Hc = Wc = 41
    Cc = 10
    wl = np.geomspace(0.8, 4.8, Cc)
    info8 = [{"detector": f"D{1 + c // 5}", "channel": 1 + c % 5, "wavelength_um": float(w), "wl_min_um": float(w * 0.97),
              "wl_max_um": float(w * 1.03)} for c, w in enumerate(wl)]
    y, x = np.mgrid[0:Hc, 0:Wc]

    def blob(x0, y0, amp):
        return amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / 3.0)

    ordinary = wl ** -1.5 * 400  # a typical star: fainter at long wavelengths
    red = wl ** 1.5 * 40  # brighter at long wavelengths (a cool or dusty object)
    stars = [(8, 8, ordinary), (32, 8, ordinary), (8, 32, ordinary), (32, 32, ordinary), (20, 20, red)]
    I = np.full((3, Cc, Hc, Wc), np.nan, np.float32)
    N = np.zeros(I.shape, np.uint8)
    for e in range(3):
        for c in range(Cc):
            if e == 2 and c >= 3:  # epoch 2: only 3 of 8 channels
                continue
            img = rng.normal(0, 0.05, (Hc, Wc))
            for x0, y0, spec in stars:
                img += blob(x0, y0, spec[c])
            have = np.ones((Hc, Wc), bool)
            if c == 5:
                have[:, 30:] = False  # this channel's strip ends at column 30: a footprint edge, not a hole
            if e == 0 and c < 5:
                have[7:10, 7:10] = False  # saturated core of the star at (8, 8) on the short-wavelength detector
            if e == 1 and c == Cc - 1:
                img[5, 25] += 30  # a spike the flags missed, in the longest channel only
            I[e, c] = np.where(have, img, np.nan)
            N[e, c] = have
    epochs = [{"index": e, "start": f"2025-0{e + 1}-01T00:00:00Z", "end": f"2025-0{e + 1}-20T00:00:00Z",
               "time": f"2025-0{e + 1}-10T00:00:00Z"} for e in range(3)]
    V = np.where(N > 0, 0.05**2, np.nan).astype(np.float32)
    return I, V, N, info8, epochs, Hc


def test_colour_composite_white_stars_red_star_and_masks():
    I, V, N, info8, epochs, Hc = colour_case(np.random.default_rng(5))
    meta, pngs = analysis.colour_composite(I, V, N, info8, epochs)
    assert meta["usable_epochs"] == [0, 1] and sorted(pngs) == ["colour_e0.png", "colour_e1.png"]
    assert not meta["epochs"][2]["usable"] and meta["epochs"][2]["n_channels"] == 3
    assert meta["spikes_rejected"] >= 1
    pal = meta["palette"]
    assert len(pal) == 10 and pal[0]["colour"].startswith("#")
    first, last = (tuple(int(p["colour"][i:i + 2], 16) for i in (1, 3, 5)) for p in (pal[0], pal[-1]))
    assert first[2] > first[0] and last[0] > last[2]  # shortest wavelength blue, longest red

    def px(e, x, y):  # y from the south edge, as everywhere in the analysis
        return rgba(pngs[f"colour_e{e}.png"])[Hc - 1 - y, x].astype(int)

    mask = np.array(analysis.COLOUR_MASK_RGB)
    for e in (0, 1):
        p = px(e, 32, 32)  # an ordinary star: white (balanced), not blue
        assert p[3] == 255 and max(p[:3]) - min(p[:3]) <= 25 and min(p[:3]) > 120, p
        r = px(e, 20, 20)  # the red star: clearly red
        assert r[0] > r[2] + 60, r
        right = px(e, 35, 20)  # beyond channel 5's strip edge: an ordinary pixel, not masked
        assert right[3] == 255 and not np.array_equal(right[:3], mask)
    sp = px(1, 25, 5)  # the spike is gone: dark sky, not a red dot
    assert sp[0] < 60 and abs(int(sp[0]) - int(sp[2])) < 30, sp
    assert np.array_equal(px(0, 8, 8)[:3], mask)  # the saturated core is masked in epoch 0 ...
    assert not np.array_equal(px(1, 8, 8)[:3], mask)  # ... but not in epoch 1
    assert 0 < meta["epochs"][0]["masked_fraction"] < 0.05 and meta["epochs"][1]["masked_fraction"] == 0


def test_colour_composite_no_data_is_transparent_and_too_few_channels_give_nothing():
    I, V, N, info8, epochs, Hc = colour_case(np.random.default_rng(6))
    I[1][:, :, :5] = np.nan  # epoch 1: the left 5 columns have no data at all
    N[1][:, :, :5] = 0
    meta, pngs = analysis.colour_composite(I, V, N, info8, epochs)
    assert rgba(pngs["colour_e1.png"])[20, 2, 3] == 0 and rgba(pngs["colour_e0.png"])[20, 2, 3] == 255
    meta, pngs = analysis.colour_composite(I[2:], V[2:], N[2:], info8, epochs[2:])
    assert meta["usable_epochs"] == [] and pngs == {} and meta["stretch"] is None
