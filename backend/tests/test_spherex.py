"""Offline tests of the data access in app/cutout.py and app/spherex.py (no IRSA, no S3, no database).

A small synthetic file with the HDU layout of a real SPHEREx spectral image (docs/FETCH_SPEED.md: IMAGE,
FLAGS tile-compressed one row per tile, VARIANCE, ZODI, EPSF, WCS-WAVE) is served by a fake HTTP server that
answers range requests like IRSA's nginx (multi-range allowed) or like S3 (multi-range -> whole file).
Run from backend/:  .venv\\Scripts\\python -m pytest tests -q"""
from __future__ import annotations

import io

import httpx
import numpy as np
import pytest
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from app import cutout, spherex

N = 300  # detector size of the synthetic file (real: 2040)
SCALE = 6.15 / 3600  # deg per pixel


def sky_wcs(n: int = N) -> WCS:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [150.0, 2.0]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cd = np.array([[-np.cos(0.4), np.sin(0.4)], [np.sin(0.4), np.cos(0.4)]]) * SCALE  # rotated, like real images
    return w


def synthetic_file() -> tuple[bytes, dict[str, np.ndarray]]:
    rng = np.random.default_rng(3)
    image = rng.normal(5, 1, (N, N)).astype(np.float32)
    zodi = np.linspace(1, 2, N * N, dtype=np.float32).reshape(N, N)
    flags = rng.integers(0, 2**22, (N, N)).astype(np.int32)
    variance = rng.normal(1, 0.1, (N, N)).astype(np.float32)
    hdr = sky_wcs().to_header()
    hdr["CRPIX1W"], hdr["CRPIX2W"] = 1.0, 1.0  # a second WCS whose CRPIX must move with the cutout
    hdus = fits.HDUList([
        fits.PrimaryHDU(header=fits.Header([("VERSION", "7.0.test")])),
        fits.ImageHDU(image, header=hdr, name="IMAGE"),
        fits.CompImageHDU(flags, compression_type="RICE_1", tile_shape=(1, N), name="FLAGS",
                          header=fits.Header([("MSKN0021", "SOURCE")])),
        fits.ImageHDU(variance, name="VARIANCE"),
        fits.ImageHDU(zodi, header=hdr, name="ZODI"),
        fits.BinTableHDU.from_columns([fits.Column("psf", "E", array=np.zeros(20000, np.float32))], name="EPSF"),
        fits.BinTableHDU.from_columns([fits.Column("X", "3J", array=np.zeros((1, 3), np.int32))], name="WCS-WAVE"),
    ])
    buf = io.BytesIO()
    hdus.writeto(buf)
    return buf.getvalue(), {"IMAGE": image, "ZODI": zodi, "FLAGS": flags, "VARIANCE": variance}


FILE, ARRAYS = synthetic_file()


def server(data: bytes, multirange: bool, honour_range: bool = True, log: list | None = None) -> httpx.Client:
    """A fake file server. multirange=False behaves like S3: several ranges -> 200 with the whole file."""

    def handler(request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("range")
        if log is not None:
            log.append(rng)
        if not rng or not honour_range:
            return httpx.Response(200, content=data)
        specs = rng.removeprefix("bytes=").split(",")
        parts = []
        for spec in specs:
            a, b = spec.split("-")
            if a == "":  # suffix range: the last b bytes
                start, end = len(data) - int(b), len(data) - 1
            else:
                start, end = int(a), min(int(b), len(data) - 1)
            parts.append((start, end))
        cr = lambda s, e: f"bytes {s}-{e}/{len(data)}"  # noqa: E731
        if len(parts) == 1:
            s, e = parts[0]
            return httpx.Response(206, content=data[s:e + 1], headers={"content-range": cr(s, e)})
        if not multirange:
            return httpx.Response(200, content=data)
        body = b""
        for s, e in parts:
            body += f"\r\n--XYZ\r\nContent-Type: application/fits\r\nContent-Range: {cr(s, e)}\r\n\r\n".encode() + data[s:e + 1]
        body += b"\r\n--XYZ--\r\n"
        return httpx.Response(206, content=body, headers={"content-type": "multipart/byteranges; boundary=XYZ"})

    return httpx.Client(transport=httpx.MockTransport(handler))


CENTER = SkyCoord(*sky_wcs().pixel_to_world_values(120.3, 170.8), unit="deg")


@pytest.mark.parametrize("multirange,server_multi", [(False, False), (True, True), (True, False)])
def test_range_cutout_matches_the_parent_file(multirange, server_multi):
    st = cutout.Stats()
    data = cutout.range_cutout("https://x.invalid/f.fits", CENTER, 40 * SCALE, server(FILE, server_multi),
                               stats=st, multirange=multirange)
    x0, y0, nx, ny = st.box
    assert (nx, ny) == (40, 40) and abs(x0 + 19.5 - 120.3) <= 1 and abs(y0 + 19.5 - 170.8) <= 1
    with fits.open(io.BytesIO(data)) as h:
        assert [x.name for x in h] == ["PRIMARY", "IMAGE", "FLAGS", "VARIANCE", "ZODI", "WCS-WAVE"]  # as IRSA's, no PSF
        for name, full in ARRAYS.items():
            np.testing.assert_array_equal(h[name].data, full[y0:y0 + ny, x0:x0 + nx])
        assert h["IMAGE"].header["CRPIX1"] == pytest.approx((N + 1) / 2 - x0)
        assert h["IMAGE"].header["CRPIX2W"] == pytest.approx(1.0 - y0)
        assert h["FLAGS"].header["MSKN0021"] == "SOURCE" and h[0].header["VERSION"] == "7.0.test"
        # the cut WCS still puts the centre at the same sky position
        x, y = WCS(h["IMAGE"].header).world_to_pixel(CENTER)
        assert float(x) == pytest.approx(120.3 - x0, abs=1e-6) and float(y) == pytest.approx(170.8 - y0, abs=1e-6)
    assert st.bytes < len(FILE) / 2  # never the whole file (small synthetic file: the 64 KB header reads weigh a lot)


def test_only_the_needed_columns_are_read_when_the_server_allows_it():
    whole, cols = cutout.Stats(), cutout.Stats()
    cutout.range_cutout("https://x.invalid/f.fits", CENTER, 40 * SCALE, server(FILE, True), stats=whole)
    cutout.range_cutout("https://x.invalid/f.fits", CENTER, 40 * SCALE, server(FILE, True), stats=cols, multirange=True)
    assert cols.bytes < whole.bytes


def test_a_server_ignoring_range_is_refused_without_reading_the_file():
    with pytest.raises(cutout.NoRangeSupport):
        cutout.range_cutout("https://x.invalid/f.fits", CENTER, 0.05, server(FILE, False, honour_range=False))


def test_cutout_outside_the_image():
    far = SkyCoord(150.0 * u.deg, 10.0 * u.deg)
    with pytest.raises(cutout.OutsideImageError):
        cutout.range_cutout("https://x.invalid/f.fits", far, 0.05, server(FILE, True))


def test_cutout_is_clipped_at_the_image_edge():
    st = cutout.Stats()
    edge = SkyCoord(*sky_wcs().pixel_to_world_values(3.0, 150.0), unit="deg")
    cutout.range_cutout("https://x.invalid/f.fits", edge, 40 * SCALE, server(FILE, True), stats=st)
    assert st.box[0] == 0 and st.box[2] < 40 and st.box[3] == 40


# --- download_cutout: which source is used ----------------------------------------------------
def record(cloud: str = "https://bucket.invalid/dr1/f.fits") -> spherex.ImageRecord:
    return spherex.ImageRecord("A_1", "D1", "spherex_dr1", 60900.0, "https://irsa.invalid/ibe/data/spherex/dr1/f.fits",
                               "", 1.0, cloud)


def test_download_prefers_s3_then_irsa_file_then_irsa_cutout_service(monkeypatch):
    calls = []

    def fake_range(url, center, size, client, **kw):
        calls.append(("range", url.split("/")[2], kw.get("multirange", False)))
        if "bucket" in url:
            raise httpx.HTTPStatusError("404", request=None, response=None)  # not on S3 yet
        raise cutout.NoRangeSupport("no")

    monkeypatch.setattr(spherex, "range_cutout", fake_range)
    monkeypatch.setattr(spherex, "download_irsa_cutout", lambda *a, **k: calls.append(("service",)) or b"FITS")
    assert spherex.download_cutout(record(), CENTER, 0.1, None) == b"FITS"
    assert calls == [("range", "bucket.invalid", False), ("range", "irsa.invalid", True), ("service",)]


def test_download_stops_at_outside_and_skips_s3_when_unknown(monkeypatch):
    calls = []

    def outside(url, *a, **k):
        calls.append(url)
        raise cutout.OutsideImageError("x")

    monkeypatch.setattr(spherex, "range_cutout", outside)
    monkeypatch.setattr(spherex, "download_irsa_cutout", lambda *a, **k: pytest.fail("must not be called"))
    with pytest.raises(spherex.OutsideImageError):
        spherex.download_cutout(record(cloud=""), CENTER, 0.1, None)
    assert calls == ["https://irsa.invalid/ibe/data/spherex/dr1/f.fits"]


def test_cloud_url_from_sia2_cloud_access():
    ca = '{"aws": {"bucket_name": "nasa-irsa-spherex", "key":"dr1/level2/x.fits", "region": "us-east-1"}}'
    assert spherex.cloud_url(ca) == "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/level2/x.fits"
    assert spherex.cloud_url("") == spherex.cloud_url("--") == spherex.cloud_url('{"gcp": {}}') == ""


# --- locating the target on the detector ------------------------------------------------------
def footprint(w: WCS, n: int, order=(0, 1, 2, 3)) -> str:
    corners = [(-0.5, -0.5), (n - 0.5, -0.5), (n - 0.5, n - 0.5), (-0.5, n - 0.5)]
    pts = [w.pixel_to_world_values(*corners[i]) for i in order]
    pts.append(pts[0])
    return "POLYGON ICRS " + " ".join(f"{float(a):.10f} {float(d):.10f}" for a, d in pts)


def test_footprint_pixel_recovers_the_pixel_for_an_undistorted_image():
    n = 2040
    w = sky_wcs(n)
    for px, py in [(10.0, 20.0), (1019.5, 1019.5), (2000.2, 33.7)]:
        coord = SkyCoord(*w.pixel_to_world_values(px, py), unit="deg")
        x, y = spherex.footprint_pixel(footprint(w, n), coord, (n, n))
        assert (x, y) == (pytest.approx(px, abs=0.01), pytest.approx(py, abs=0.01))
    assert spherex.footprint_pixel("POLYGON ICRS 1 2 3 4 5 6", CENTER, (n, n)) is None
    assert spherex.footprint_pixel("", CENTER, (n, n)) is None


@pytest.mark.parametrize("order,headers_read", [((0, 1, 2, 3), 3), ((1, 2, 3, 0), 6)])
def test_locate_checks_the_footprint_and_falls_back_to_headers(monkeypatch, order, headers_read):
    n = 2040
    w = sky_wcs(n)
    cwave = np.add.outer(np.zeros(n), np.linspace(0.75, 1.1, n)).astype(np.float32)  # varies along x
    monkeypatch.setattr(spherex.SpectralMaps, "get", lambda self, rel, det: (cwave, cwave * 0 + 0.02))
    reads = []

    def header(rec, client):
        reads.append(rec.obs_id)
        return w.to_header()

    monkeypatch.setattr(spherex, "fetch_image_header", header)
    target = SkyCoord(*w.pixel_to_world_values(1500.0, 400.0), unit="deg")
    recs = [spherex.ImageRecord(f"O_{i}", "D1", "spherex_dr1", 60900.0 + i,
                                "https://irsa.invalid/ibe/data/spherex/dr1/f.fits", footprint(w, n, order), 1.0)
            for i in range(6)]
    exps, failed = spherex.locate_on_detector(recs, lambda mjd: target)
    assert failed == [] and len(reads) == headers_read  # wrong vertex order -> every header is read
    for e in exps:
        assert (e.x, e.y) == (pytest.approx(1500.0, abs=0.05), pytest.approx(400.0, abs=0.05))
        assert e.wavelength_um == pytest.approx(float(cwave[400, 1500]))


# --- stored file layouts --------------------------------------------------------------------
def test_file_layout_survives_storage_and_rejects_other_formats():
    st = cutout.Stats()
    cutout.range_cutout("https://x.invalid/f.fits", CENTER, 40 * SCALE, server(FILE, True), stats=st)
    lay = st.layout
    assert lay is not None and lay.size == len(FILE) and not st.layout_reused
    assert cutout.FileLayout.loads(lay.dumps()) == lay
    assert len(lay.dumps()) < 20_000
    assert cutout.FileLayout.loads(b"garbage") is None
    import json, zlib
    other = json.loads(zlib.decompress(lay.dumps()))
    other["format"] = 999
    assert cutout.FileLayout.loads(zlib.compress(json.dumps(other).encode())) is None


def test_a_stored_layout_needs_one_round_of_three_requests_and_gives_the_same_cutout():
    first, again = cutout.Stats(), cutout.Stats()
    url = "https://x.invalid/f.fits"
    fresh = cutout.range_cutout(url, CENTER, 40 * SCALE, server(FILE, False), stats=first)
    log: list = []
    other_center = SkyCoord(*sky_wcs().pixel_to_world_values(200.0, 60.0), unit="deg")  # a pan: other rows
    reused = cutout.range_cutout(url, other_center, 40 * SCALE, server(FILE, False, log=log), stats=again,
                                 layout=first.layout)
    assert again.layout_reused and len(log) == 4 and again.round_trips == 1 and first.round_trips == 5
    with fits.open(io.BytesIO(reused)) as h:
        x0, y0, nx, ny = again.box
        for name, full in ARRAYS.items():
            np.testing.assert_array_equal(h[name].data, full[y0:y0 + ny, x0:x0 + nx])
    same = cutout.range_cutout(url, CENTER, 40 * SCALE, server(FILE, False), layout=first.layout)
    assert same == fresh  # byte-identical to the cutout made by walking the headers


def test_a_layout_that_does_not_fit_the_file_is_read_again():
    st = cutout.Stats()
    cutout.range_cutout("https://x.invalid/f.fits", CENTER, 40 * SCALE, server(FILE, True), stats=st)
    wrong = cutout.FileLayout(**{**st.layout.__dict__, "size": st.layout.size + 2880})
    again = cutout.Stats()
    data = cutout.range_cutout("https://x.invalid/f.fits", CENTER, 40 * SCALE, server(FILE, True), stats=again,
                               layout=wrong)
    assert not again.layout_reused and again.layout == st.layout
    with fits.open(io.BytesIO(data)) as h:
        x0, y0, nx, ny = again.box
        np.testing.assert_array_equal(h["IMAGE"].data, ARRAYS["IMAGE"][y0:y0 + ny, x0:x0 + nx])


class Layouts:
    def __init__(self):
        self.rows, self.puts = {}, 0

    def file_layout(self, url):
        return self.rows.get(url)

    def put_file_layout(self, url, data):
        self.puts += 1
        self.rows[url] = data


def test_download_cutout_stores_the_layout_under_the_irsa_url_and_reuses_it():
    layouts, log = Layouts(), []
    client = server(FILE, False, log=log)
    rec = record(cloud="https://bucket.invalid/dr1/f.fits")
    first = spherex.download_cutout(rec, CENTER, 40 * SCALE, client, layouts=layouts)
    assert layouts.puts == 1 and list(layouts.rows) == [rec.access_url]
    n_first = len(log)
    second = spherex.download_cutout(rec, CENTER, 40 * SCALE, client, layouts=layouts)
    assert second == first and len(log) - n_first == 4 and layouts.puts == 1  # reused, not stored again
