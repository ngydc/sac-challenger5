"""Cutouts built from HTTP range requests, instead of IRSA's cutout service.

Measured 2026-11-14 (docs/FETCH_SPEED.md, backend/scripts/bench/t2_range_cutout.py): ~1 s per cutout from the S3
copy instead of 6.5-12 s from IRSA's cutout service (which streams the whole 4 MB PSF extension we drop), no 503s,
and the result is bit-identical to IRSA's cutout (same pixel box, pixels, header keywords, wavelength).

How (layout read from the headers at run time, never hard-coded; the docs don't cover byte layouts):
- IMAGE, VARIANCE and ZODI are plain images stored row by row, so the rows of a cutout are ONE byte range.
- FLAGS is tile-compressed with one tile per image row, so its rows are one range of the table's heap, found
  through the row descriptors; astropy's public reader decompresses a small table built from those rows.
- IRSA's cutout only changes NAXIS1/2 and shifts every CRPIX1*/CRPIX2* keyword (sky, "A" and "W" WCS) by the
  cutout origin (irsa-cutout-service.md describes cutouts; the keyword changes were compared on real files).
  WCS-WAVE is kept whole here; with the shifted CRPIXnW it gives the same wavelengths.
- Produced HDUs: PRIMARY, IMAGE, FLAGS, ZODI, WCS-WAVE (what spherex.process() needs). VARIANCE (unused) and
  the PSF extension are never downloaded.

Two phases. Finding where everything sits (read_layout) takes four requests one after another, because each
header's position depends on the size of the part before it (FLAGS compresses differently in every file);
it was ~0.75 s of the ~1 s a cutout from S3 takes. The result, a FileLayout, never changes for a file (its URL
contains the version), so callers can store it and pass it back: a later cutout of the same file (another fov,
a pan, a nearby target) then needs ONE round of three parallel requests. A stored layout is only trusted if
the file still has the same total size (every reply states it); otherwise it is read again.

Servers: the S3 copy answers single range requests (206). IRSA's file server (nginx) also answers multi-range
requests (several ranges in one request, `multipart/byteranges`), so from IRSA only the needed columns of each
row are read. S3 does NOT support multi-range: it answers 200 with the whole 62 MB file. Every reply is
therefore checked for 206 before its body is read, so a server that ignores the Range header never makes us
download a whole file.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import math
import random
import re
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields

import httpx
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales

log = logging.getLogger(__name__)

BLOCK = 2880  # FITS block size (FITS standard)
END_CARD = b"END" + b" " * 77
CHUNK = 65536  # one header read; every SPHEREx header seen so far fits (largest: IMAGE, 23 KB)
MAX_RANGES_PER_REQUEST = 128  # keeps the Range header well below nginx's default 8 KB header limit
BITPIX_DTYPE = {-32: ">f4", -64: ">f8", 32: ">i4", 16: ">i2", 8: ">u1"}


class OutsideImageError(Exception):
    """The requested cutout does not overlap the image (IRSA's cutout service answers HTTP 500 then)."""


class NoRangeSupport(Exception):
    """The server ignored the Range header (or a multi-range request); nothing was downloaded."""


class StaleLayout(Exception):
    """A stored FileLayout does not fit the file the server has (different total size)."""


@dataclass
class FileLayout:
    """Where everything a cutout needs sits in one file, plus the headers it copies. ~70 KB; ~26 KB compressed
    (the FLAGS row index, 8 bytes per image row, barely compresses)."""

    size: int  # total file size in bytes, checked on every use
    primary: str  # header texts (FITS cards)
    image_header: str
    image_data: int  # byte offset of the IMAGE pixels
    flags_header: str
    flags_desc: bytes  # FLAGS row descriptors: (byte count, heap offset) per image row, big-endian int32
    flags_heap: int  # byte offset of the FLAGS heap
    zodi_header: str
    zodi_data: int
    wcs_wave: bytes  # the whole WCS-WAVE HDU (header + data)

    FORMAT = 1  # bump when the fields change: stored layouts of another format are ignored

    def dumps(self) -> bytes:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d = {k: base64.b64encode(v).decode("ascii") if isinstance(v, bytes) else v for k, v in d.items()}
        return zlib.compress(json.dumps({"format": self.FORMAT, **d}).encode("utf-8"), 6)

    @classmethod
    def loads(cls, data: bytes) -> "FileLayout | None":
        """None if `data` is unreadable or from another format version."""
        try:
            d = json.loads(zlib.decompress(data))
            if d.pop("format", None) != cls.FORMAT:
                return None
            for name in ("flags_desc", "wcs_wave"):
                d[name] = base64.b64decode(d[name])
            return cls(**d)
        except (ValueError, TypeError, KeyError, zlib.error):
            return None


@dataclass
class Stats:
    """What one cutout cost (for the benchmarks in scripts/bench/), and the layout it used."""

    requests: int = 0
    bytes: int = 0
    n503: int = 0
    round_trips: int = 0  # sequential steps (requests within one step run in parallel)
    t_meta: float = 0.0  # seconds spent reading the layout (0 when a stored one was used)
    t_data: float = 0.0  # seconds spent on the pixel data
    box: tuple[int, int, int, int] | None = None  # (x0, y0, nx, ny), 0-based, in the parent image
    layout: FileLayout | None = None  # the layout used (read now, or passed in)
    layout_reused: bool = False  # True if a passed-in layout was valid and used
    log: list = field(default_factory=list)


def _pad(n: int) -> int:
    return -(-n // BLOCK) * BLOCK


def _total_size(content_range: bytes | str) -> int | None:
    """Total file size from a Content-Range value like 'bytes 0-99/61948800'."""
    cr = content_range.decode("ascii") if isinstance(content_range, bytes) else content_range
    total = cr.rsplit("/", 1)[-1].strip() if "/" in cr else "*"
    return int(total) if total.isdigit() else None


class Ranged:
    """Range requests against one URL. 503 -> wait and retry (as for IRSA's cutouts); other 5xx and network
    errors are retried a few times; 4xx (e.g. a file not on S3 yet) fails at once so the caller can fall back.
    `size` is the file's total size as the server reported it."""

    def __init__(self, url: str, client: httpx.Client, stats: Stats, retries: int = 5):
        self.url, self.client, self.stats, self.retries = url, client, stats, retries
        self.size: int | None = None

    def _fetch(self, spec: str, multipart: bool) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                with self.client.stream("GET", self.url, headers={"Range": spec}) as resp:
                    self.stats.requests += 1
                    if resp.status_code == 503:
                        self.stats.n503 += 1
                        last = RuntimeError("503 Server busy")
                        time.sleep(float(resp.headers.get("Retry-After", min(5 * 2**attempt, 60))) + random.random())
                        continue
                    if resp.status_code >= 500:
                        last = RuntimeError(f"HTTP {resp.status_code}")
                        time.sleep(1 + attempt)
                        continue
                    if resp.status_code >= 400:
                        raise httpx.HTTPStatusError(f"HTTP {resp.status_code} for {self.url}", request=resp.request, response=resp)
                    ctype = resp.headers.get("content-type", "")
                    if resp.status_code != 206 or (multipart and "multipart/byteranges" not in ctype):
                        raise NoRangeSupport(f"{resp.status_code} {ctype} from {self.url}")  # body never read
                    resp.read()
                    self.stats.bytes += len(resp.content)
                    total = _total_size(resp.headers.get("content-range", ""))
                    if total is not None:
                        self.size = total
                    return resp
            except (httpx.TransportError, OSError) as err:  # timeouts, dropped connections
                last = err
                time.sleep(1 + attempt)
        raise RuntimeError(f"range request failed after {self.retries} attempts: {self.url}") from last

    def get(self, start: int, end: int | None = None) -> bytes:
        """Bytes [start, end], inclusive. start < 0 means the last -start bytes of the file."""
        return self._fetch(f"bytes={start}" if start < 0 else f"bytes={start}-{end}", multipart=False).content

    def get_many(self, ranges: list[tuple[int, int]]) -> list[bytes]:
        """Several inclusive ranges in ONE request (multipart/byteranges). IRSA only, see the module docstring."""
        if len(ranges) == 1:
            return [self.get(*ranges[0])]
        resp = self._fetch("bytes=" + ",".join(f"{a}-{b}" for a, b in ranges), multipart=True)
        boundary = resp.headers["content-type"].split("boundary=")[1].strip('"').encode()
        parts: dict[int, bytes] = {}
        for part in resp.content.split(b"--" + boundary)[1:]:
            if part.startswith(b"--"):
                break
            head, _, body = part.partition(b"\r\n\r\n")
            cr = next(ln for ln in head.split(b"\r\n") if ln.lower().startswith(b"content-range")).split(b":", 1)[1].strip()
            a, b = cr.split(b" ")[-1].split(b"/")[0].split(b"-")
            parts[int(a)] = body[: int(b) - int(a) + 1]
            total = _total_size(cr)
            if total is not None:
                self.size = total
        try:
            return [parts[a] for a, _ in ranges]
        except KeyError as err:  # a server may merge neighbouring ranges; take the plain path instead
            raise NoRangeSupport(f"multipart reply did not contain range {err}") from err


def _parse_header(buf: bytes, off: int = 0) -> tuple[fits.Header, int] | None:
    """Header starting at buf[off]: (header, padded size), or None if its END card is not in `buf` yet."""
    pos = off
    while pos + 80 <= len(buf):
        if buf[pos:pos + 80] == END_CARD:
            size = _pad(pos + 80 - off)
            return fits.Header.fromstring(buf[off:off + size].decode("ascii")), size
        pos += 80
    return None


def _header_at(r: Ranged, off: int, buf: bytes | None = None) -> tuple[fits.Header, int, bytes]:
    """Header at file offset `off`: (header, header size, the bytes read from `off`)."""
    buf = buf if buf is not None else r.get(off, off + CHUNK - 1)
    while (parsed := _parse_header(buf)) is None:
        buf += r.get(off + len(buf), off + len(buf) + CHUNK - 1)
    return parsed[0], parsed[1], buf


def _data_size(h: fits.Header) -> int:
    if h["NAXIS"] == 0:
        return 0
    n = math.prod(h[f"NAXIS{i}"] for i in range(1, h["NAXIS"] + 1))
    return abs(h["BITPIX"]) // 8 * h.get("GCOUNT", 1) * (n + h.get("PCOUNT", 0))


def _shift_crpix(h: fits.Header, x0: int, y0: int, nx: int, ny: int) -> fits.Header:
    """What IRSA's cutout does to a header: new size, every CRPIX1*/CRPIX2* moved by the cutout origin."""
    h = h.copy()
    h["NAXIS1"], h["NAXIS2"] = nx, ny
    for k in list(h.keys()):
        if re.fullmatch(r"CRPIX1[A-Z]?", k):
            h[k] = h[k] - x0
        elif re.fullmatch(r"CRPIX2[A-Z]?", k):
            h[k] = h[k] - y0
    for k in ("CHECKSUM", "DATASUM"):  # no longer valid for the cut data
        h.remove(k, ignore_missing=True)
    return h


def pixel_box(img_header: fits.Header, center: SkyCoord, size_deg: float) -> tuple[int, int, int, int]:
    """0-based (x0, y0, nx, ny) of a square of `size_deg` around `center`, clipped to the image. This matched
    IRSA's own box exactly in the comparison (t2_range_cutout.py part A)."""
    w = WCS(img_header)
    x, y = (float(v) for v in w.world_to_pixel(center))
    n = int(math.ceil(size_deg / float(np.mean(proj_plane_pixel_scales(w.celestial)))))
    x0, y0 = int(round(x - (n - 1) / 2)), int(round(y - (n - 1) / 2))
    width, height = img_header["NAXIS1"], img_header["NAXIS2"]
    x1, y1 = min(width, x0 + n), min(height, y0 + n)
    x0, y0 = max(0, x0), max(0, y0)
    if x1 <= x0 or y1 <= y0:
        raise OutsideImageError(f"cutout of {size_deg} deg at {center.to_string()} is outside the image")
    return x0, y0, x1 - x0, y1 - y0


def read_layout(r: Ranged, pool: ThreadPoolExecutor) -> FileLayout:
    """Walk the headers: four requests one after another (the end of the file is read alongside the first)."""
    st = r.stats
    t0 = time.perf_counter()
    tail_f = pool.submit(r.get, -CHUNK)
    # step 1: PRIMARY + IMAGE headers
    head = r.get(0, CHUNK - 1)
    parsed = _parse_header(head)
    if parsed is None:
        raise RuntimeError(f"no primary header in the first {CHUNK} bytes of {r.url}")
    prim_h, prim_n = parsed
    img_h, img_n, _ = _header_at(r, prim_n, head[prim_n:])
    if img_h.get("EXTNAME") != "IMAGE":
        raise RuntimeError(f"first extension is {img_h.get('EXTNAME')!r}, not IMAGE")
    img_data = prim_n + img_n

    # step 2: FLAGS header + row descriptors
    flags_off = img_data + _pad(_data_size(img_h))
    flags_h, flags_n, buf = _header_at(r, flags_off)
    if flags_h.get("EXTNAME") != "FLAGS":
        raise RuntimeError(f"second extension is {flags_h.get('EXTNAME')!r}, not FLAGS")
    if not (flags_h.get("ZIMAGE") and flags_h.get("TFIELDS") == 1 and str(flags_h["TFORM1"]).startswith("1P")
            and flags_h.get("ZTILE2") == 1 and flags_h.get("ZNAXIS1") == flags_h.get("ZTILE1")
            and flags_h["NAXIS2"] == img_h["NAXIS2"]):
        raise RuntimeError("FLAGS is not compressed with one tile per row; this layout is not supported")
    desc_len = flags_h["NAXIS1"] * flags_h["NAXIS2"]
    while len(buf) < flags_n + desc_len:
        buf += r.get(flags_off + len(buf), flags_off + len(buf) + CHUNK - 1)

    # steps 3 and 4: VARIANCE header (only for its size), then ZODI header
    var_off = flags_off + flags_n + _pad(_data_size(flags_h))
    var_h, var_n, _ = _header_at(r, var_off)
    zodi_off = var_off + var_n + _pad(_data_size(var_h))
    zodi_h, zodi_n, _ = _header_at(r, zodi_off)
    if (var_h.get("EXTNAME"), zodi_h.get("EXTNAME")) != ("VARIANCE", "ZODI"):
        raise RuntimeError(f"unexpected HDU order: {var_h.get('EXTNAME')}, {zodi_h.get('EXTNAME')}")
    if (zodi_h["NAXIS1"], zodi_h["NAXIS2"], zodi_h["BITPIX"]) != (img_h["NAXIS1"], img_h["NAXIS2"], img_h["BITPIX"]):
        raise RuntimeError("ZODI and IMAGE differ in shape or type")

    # WCS-WAVE from the end of the file (file sizes are multiples of 2880, so block starts are known)
    tail = tail_f.result()
    tail_start = r.size - len(tail)
    wave = None
    for pos in range((-tail_start) % BLOCK, len(tail), BLOCK):
        if tail[pos:pos + 9] == b"XTENSION=":
            found = _parse_header(tail, pos)
            if found and found[0].get("EXTNAME") == "WCS-WAVE":
                wh, wn = found
                wave = tail[pos:pos + wn + _pad(_data_size(wh))]
                break
    if wave is None:
        raise RuntimeError(f"WCS-WAVE not found in the last {CHUNK} bytes")
    st.round_trips += 4
    st.t_meta = time.perf_counter() - t0
    return FileLayout(
        size=r.size, primary=prim_h.tostring(), image_header=img_h.tostring(), image_data=img_data,
        flags_header=flags_h.tostring(), flags_desc=bytes(buf[flags_n:flags_n + desc_len]),
        flags_heap=flags_off + flags_n + flags_h.get("THEAP", desc_len),
        zodi_header=zodi_h.tostring(), zodi_data=zodi_off + zodi_n, wcs_wave=wave)


def cut(r: Ranged, pool: ThreadPoolExecutor, lay: FileLayout, center: SkyCoord, size_deg: float,
        box: tuple[int, int, int, int] | None, multirange: bool) -> bytes:
    """One round of three parallel requests (IMAGE rows, FLAGS rows, ZODI rows), then assemble the cutout.
    Raises StaleLayout if the server's file is not the one `lay` describes."""
    st = r.stats
    t0 = time.perf_counter()
    img_h, flags_h = fits.Header.fromstring(lay.image_header), fits.Header.fromstring(lay.flags_header)
    zodi_h = fits.Header.fromstring(lay.zodi_header)
    x0, y0, nx, ny = box or pixel_box(img_h, center, size_deg)
    st.box = (x0, y0, nx, ny)
    width = img_h["NAXIS1"]
    px_bytes = abs(img_h["BITPIX"]) // 8
    row_bytes = width * px_bytes

    def rows_of(data_off: int) -> tuple[bytes, bool]:
        """Rows y0..y0+ny of an image: (bytes, True) = only columns x0..x0+nx, (bytes, False) = whole rows."""
        if multirange and nx < width:
            ranges = [(data_off + y * row_bytes + x0 * px_bytes, data_off + y * row_bytes + (x0 + nx) * px_bytes - 1)
                      for y in range(y0, y0 + ny)]
            try:
                parts: list[bytes] = []
                for i in range(0, len(ranges), MAX_RANGES_PER_REQUEST):
                    parts += r.get_many(ranges[i:i + MAX_RANGES_PER_REQUEST])
                return b"".join(parts), True
            except NoRangeSupport as err:
                log.info("multi-range refused (%s), reading whole rows", err)
        return r.get(data_off + y0 * row_bytes, data_off + (y0 + ny) * row_bytes - 1), False

    desc = np.frombuffer(lay.flags_desc, dtype=">i4").reshape(-1, 2)  # (byte count, heap offset)
    rows = desc[y0:y0 + ny]
    h_lo, h_hi = int(rows[:, 1].min()), int((rows[:, 0] + rows[:, 1]).max())
    img_f = pool.submit(rows_of, lay.image_data)
    zodi_f = pool.submit(rows_of, lay.zodi_data)
    heap = r.get(lay.flags_heap + h_lo, lay.flags_heap + h_hi - 1)
    img_res, zodi_res = img_f.result(), zodi_f.result()
    st.round_trips += 1
    st.t_data = time.perf_counter() - t0
    if r.size != lay.size:
        raise StaleLayout(f"{r.url}: file is {r.size} bytes, the stored layout says {lay.size}")

    dtype = BITPIX_DTYPE[img_h["BITPIX"]]

    def as_image(result: tuple[bytes, bool]) -> np.ndarray:
        data, cols_only = result
        arr = np.frombuffer(data, dtype=dtype).reshape(ny, -1)
        return arr if cols_only else arr[:, x0:x0 + nx]

    img, zodi = as_image(img_res), as_image(zodi_res)

    # FLAGS: a small compressed table with only these rows, decompressed by astropy's public reader
    sub_h = flags_h.copy()
    sub_h["NAXIS2"], sub_h["ZNAXIS2"], sub_h["PCOUNT"] = ny, ny, h_hi - h_lo
    sub_h.remove("THEAP", ignore_missing=True)
    sub_desc = rows.copy()
    sub_desc[:, 1] -= h_lo
    table = sub_desc.astype(">i4").tobytes() + heap
    raw = sub_h.tostring().encode("ascii") + table + b"\0" * (_pad(len(table)) - len(table))
    with fits.open(io.BytesIO(fits.PrimaryHDU().header.tostring().encode("ascii") + raw)) as f:
        flags = np.asarray(f[1].data)[:, x0:x0 + nx].astype(np.int32)
        flags_img_h = f[1].header.copy()

    out = fits.HDUList([
        fits.PrimaryHDU(header=fits.Header.fromstring(lay.primary)),
        fits.ImageHDU(img, header=_shift_crpix(img_h, x0, y0, nx, ny)),
        fits.ImageHDU(flags, header=_shift_crpix(flags_img_h, x0, y0, nx, ny)),
        fits.ImageHDU(zodi, header=_shift_crpix(zodi_h, x0, y0, nx, ny)),
        fits.BinTableHDU.fromstring(lay.wcs_wave),
    ])
    buf_out = io.BytesIO()
    out.writeto(buf_out)
    return buf_out.getvalue()


def range_cutout(url: str, center: SkyCoord, size_deg: float, client: httpx.Client,
                 box: tuple[int, int, int, int] | None = None, stats: Stats | None = None,
                 multirange: bool = False, layout: FileLayout | None = None) -> bytes:
    """FITS bytes (PRIMARY, IMAGE, FLAGS, ZODI, WCS-WAVE) of a cutout of the file at `url`.

    `layout`: a FileLayout of this file from an earlier cutout (stats.layout returns the one used, so callers
    can store it); skips the four header requests. If the file turns out different, the layout is read again.
    `multirange=True` reads only the needed columns of the IMAGE/ZODI rows (IRSA; falls back to whole rows if
    the server says no). `box` forces a pixel box (x0, y0, nx, ny). Raises OutsideImageError if the cutout
    does not overlap the image, NoRangeSupport or another error if the server can't be used."""
    st = stats if stats is not None else Stats()
    r = Ranged(url, client, st)
    pool = ThreadPoolExecutor(3, thread_name_prefix="range")
    try:
        if layout is not None:
            try:
                data = cut(r, pool, layout, center, size_deg, box, multirange)
                st.layout, st.layout_reused = layout, True
                return data
            except StaleLayout as err:
                log.warning("stored layout no longer fits, reading it again: %s", err)
        st.layout = read_layout(r, pool)
        return cut(r, pool, st.layout, center, size_deg, box, multirange)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
