"""TEMPORARY exploration tool: what do the frames of one target look like in every band?

Builds, for one target, every cutout of every detector (D1..D6 = the six wavelength bands), aligns
them on one north-up grid and writes
  viewer.html        self-contained page: detector tabs, a TIME slider (observing season) and a
                     WAVELENGTH slider, a clickable coverage map, blink / sweep buttons
  frames_D1..D6.png  contact sheet per band: one row per season, frames ordered by wavelength
  summary.json

The final API will look different; this is only to see what the data looks like.
Uses the same pipeline as fetch_barnard.py (app/spherex.py), nothing new about the data format.

Needs the cache database: `docker compose up -d db` from the repo root.
Run from backend/:
    .venv\\Scripts\\python -m scripts.explore_bands                     # Barnard's Star, all bands
    .venv\\Scripts\\python -m scripts.explore_bands --target R_Dra --size 0.1
    .venv\\Scripts\\python -m scripts.explore_bands --max-per-group 8   # fewer downloads
Then open backend/out/explore_<target>/viewer.html in a browser.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import numpy as np
from astropy.time import Time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, spherex  # noqa: E402
from scripts.survey_coverage import TARGETS, mover  # noqa: E402

DETECTORS = [f"D{i}" for i in range(1, 7)]


def iso(mjd: float) -> str:
    return Time(mjd, format="mjd").iso[:16]


def pick_evenly(items: list, n: int) -> list:
    if n <= 0 or len(items) <= n:
        return items
    return [items[i] for i in np.linspace(0, len(items) - 1, n).round().astype(int)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default="Barnard", choices=list(TARGETS))
    ap.add_argument("--size", type=float, default=0.08, help="field of view in degrees (default 0.08)")
    ap.add_argument("--detectors", default=",".join(DETECTORS))
    ap.add_argument("--max-per-group", type=int, default=0, help="cap on images per detector and season (0 = all)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    name, ra, dec, pmra, pmdec = TARGETS[args.target]
    at = mover(ra, dec, pmra, pmdec)
    out = Path(args.out or Path(__file__).resolve().parents[1] / "out" / f"explore_{args.target}")
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. search + cheap filters ----------------------------------------------------------------
    collections = spherex.spherex_collections()
    now = at(Time.now().mjd)
    records = spherex.search(now, collections)
    margin = args.size / 2 * np.sqrt(2)  # the whole cutout must lie inside the image
    recs = spherex.filter_records(records, now, detectors=args.detectors.split(","), min_edge_margin_deg=margin)
    seasons = spherex.group_seasons(recs)
    season_of = {id(r): i for i, s in enumerate(seasons) for r in s}
    print(f"{name}: {len(records)} images found, {len(recs)} kept, {len(seasons)} seasons")

    chosen = []
    for s in seasons:
        for d in args.detectors.split(","):
            chosen += pick_evenly([r for r in s if r.detector == d], args.max_per_group)
    print(f"downloading {len(chosen)} cutouts (cached ones are reused)...")

    # 2. fetch (one retry pass: downloads fail intermittently) ----------------------------------
    center = at(np.mean([r.t_mid_mjd for r in recs]))
    frames, failures = spherex.fetch_frames(chosen, center, args.size, at, cache=db.store)
    if failures:
        print(f"  retrying {len(failures)} failed downloads")
        more, failures = spherex.fetch_frames([r for r, _ in failures], center, args.size, at, cache=db.store)
        frames = sorted(frames + more, key=lambda f: f.record.t_mid_mjd)
    for r, err in failures:
        print(f"  FAILED {r.obs_id} {r.detector}: {err[:100]}")
    print(f"  {len(frames)} frames ready ({time.time() - t0:.0f}s)")

    # 3. one common north-up grid ---------------------------------------------------------------
    scale = spherex.native_pixel_scale_deg(frames[0])
    grid, shape = spherex.north_up_wcs(center, args.size, scale)
    aligned = [spherex.reproject_frame(f, grid, shape) for f in frames]  # bad pixels = NaN
    aligned_raw = [spherex.reproject_frame(f, grid, shape, raw=True) for f in frames]  # nothing masked

    # 4. outputs --------------------------------------------------------------------------------
    payload = build_payload(name, args, frames, aligned, aligned_raw, seasons, season_of, grid, shape, scale, at)
    (out / "viewer.html").write_text(HTML.replace("__DATA__", json.dumps(payload, separators=(",", ":"))), encoding="utf-8")
    contact_sheets(frames, aligned, season_of, len(seasons), name, out)
    (out / "summary.json").write_text(json.dumps({
        "target": name, "size_deg": args.size, "collections": collections, "pixel_scale_arcsec": scale * 3600,
        "grid": list(shape), "seasons": [{"start": iso(s[0].t_mid_mjd), "end": iso(s[-1].t_mid_mjd)} for s in seasons],
        "frames_per_detector": {d: sum(f.record.detector == d for f in frames) for d in DETECTORS},
        "failed_downloads": len(failures)}, indent=1))
    print(f"done in {time.time() - t0:.0f}s -> {out / 'viewer.html'}")


def build_payload(name, args, frames, aligned, aligned_raw, seasons, season_of, grid, shape, scale, at) -> dict:
    dets = {}
    for d in sorted({f.record.detector for f in frames}):
        items = []
        for f, a, ar in zip(frames, aligned, aligned_raw):
            if f.record.detector != d:
                continue
            # a pixel is "bad" on the aligned grid if it is NaN once masked but has a value unmasked
            bad = np.isnan(a) & np.isfinite(ar)
            tx, ty = (float(v) for v in grid.world_to_pixel(at(f.record.t_mid_mjd)))
            items.append({
                "s": season_of[id(f.record)], "mjd": round(f.record.t_mid_mjd, 5), "date": iso(f.record.t_mid_mjd),
                "wl": round(f.wavelength_um, 4), "bw": round(f.bandwidth_um, 4), "obs": f.record.obs_id,
                "coll": f.record.collection, "ver": f.version,
                # SOURCE (bit 21) is set on nearly every pixel (CLAUDE.md), so it says nothing here.
                "flags": [x for x in f.flags_at_target if x != "SOURCE"],
                "tx": round(tx, 2), "ty": round(ty, 2),
                "d": base64.b64encode(ar.astype("<f4").tobytes()).decode("ascii"),  # unmasked pixels
                "m": base64.b64encode(np.packbits(bad.ravel()).tobytes()).decode("ascii"),  # bad-pixel bits
            })
        items.sort(key=lambda x: (x["s"], x["wl"]))
        dets[d] = {"frames": items}
    return {
        "target": name, "size_deg": args.size, "pixel_scale_arcsec": round(scale * 3600, 3), "n": shape[0],
        "seasons": [{"start": iso(s[0].t_mid_mjd)[:10], "end": iso(s[-1].t_mid_mjd)[:10]} for s in seasons],
        "bad_flags": list(spherex.BAD_FLAG_NAMES),
        "detectors": dets,
    }


def contact_sheets(frames, aligned, season_of, n_seasons, name, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from astropy.visualization import AsinhStretch, ImageNormalize, PercentileInterval

    for d in sorted({f.record.detector for f in frames}):
        items = [(season_of[id(f.record)], f, a) for f, a in zip(frames, aligned) if f.record.detector == d]
        rows = sorted({s for s, _, _ in items})
        ncol = max(sum(1 for s, _, _ in items if s == r) for r in rows)
        pix = np.concatenate([a.ravel() for _, _, a in items])
        norm = ImageNormalize(pix[np.isfinite(pix)], interval=PercentileInterval(99.5), stretch=AsinhStretch(0.1))
        fig, axes = plt.subplots(len(rows), ncol, figsize=(ncol * 1.15, len(rows) * 1.45), squeeze=False)
        for ax in axes.flat:
            ax.set_axis_off()
        for ri, r in enumerate(rows):
            for ci, (_, f, a) in enumerate(sorted((x for x in items if x[0] == r), key=lambda x: x[1].wavelength_um)):
                ax = axes[ri, ci]
                ax.imshow(a, origin="lower", cmap="gray", norm=norm, interpolation="nearest")
                ax.set_title(f"{f.wavelength_um:.2f}", fontsize=5, pad=1)
                if ci == 0:
                    ax.text(-0.08, 0.5, iso(f.record.t_mid_mjd)[:7], transform=ax.transAxes, fontsize=6,
                            rotation=90, va="center", ha="right")
        fig.suptitle(f"{name}, {d}: one row per season, frames ordered by wavelength (µm), same stretch",
                     fontsize=8, x=0.01, ha="left")
        fig.tight_layout()
        fig.savefig(out / f"frames_{d}.png", dpi=110)
        plt.close(fig)


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SPHEREx band explorer</title>
<style>
:root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:#e4e3df;--card:#f3f2ef;--warn:#b25b00;
--d1:#2a78d6;--d2:#eb6834;--d3:#1baf7a;--d4:#eda100;--d5:#e87ba4;--d6:#008300}
@media (prefers-color-scheme:dark){:root{--bg:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--line:#383835;--card:#242422;--warn:#f0a050;
--d1:#3987e5;--d2:#d95926;--d3:#199e70;--d4:#c98500;--d5:#d55181;--d6:#0ca30c}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}
h1{font-size:18px;margin:0 0 2px}.sub{color:var(--ink2);margin:0 0 12px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tab{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:6px 12px;border-radius:6px;cursor:pointer;font:inherit}
.tab[aria-selected=true]{border-color:var(--c);box-shadow:inset 0 -3px 0 var(--c);font-weight:600}
.tab small{color:var(--ink2);display:block;font-weight:400}
.layout{display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start}
.view{flex:0 0 auto;width:min(480px,92vw)}canvas#img{width:min(480px,92vw);aspect-ratio:1;image-rendering:pixelated;border:1px solid var(--line);background:#000;display:block}
.panel{flex:1 1 360px;min-width:300px;max-width:640px}
.row{margin:0 0 14px}.row label{display:flex;justify-content:space-between;gap:8px;margin-bottom:4px}
.row label b{font-weight:600}.row label span{color:var(--ink2);text-align:right}
input[type=range]{width:100%}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
button.b{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:6px 10px;border-radius:6px;cursor:pointer;font:inherit}
button.b[aria-pressed=true]{outline:2px solid var(--ink2)}
.info{background:var(--card);border-radius:8px;padding:10px 12px;margin-bottom:14px;min-height:5.5em}
.info .warn{color:var(--warn);font-weight:600}.info div{color:var(--ink2)}.info b{color:var(--ink)}
canvas#cov{width:100%;height:230px;border:1px solid var(--line);border-radius:6px;cursor:pointer;display:block}
.opts{display:flex;gap:14px;flex-wrap:wrap;color:var(--ink2);margin-bottom:12px}
.hint{color:var(--ink2);font-size:12px;margin-top:6px}
</style></head><body>
<h1 id="title"></h1><p class="sub" id="sub"></p>
<div class="tabs" id="tabs" role="tablist"></div>
<div class="layout">
  <div class="view"><canvas id="img" width="400" height="400"></canvas>
    <div class="hint" id="hint"></div></div>
  <div class="panel">
    <div class="row"><label><b>Time (observing season)</b><span id="tlabel"></span></label>
      <input type="range" id="t" min="0" max="0" step="1" aria-label="time"></div>
    <div class="row"><label><b>Wavelength</b><span id="wlabel"></span></label>
      <input type="range" id="w" min="0" max="1000" step="1" aria-label="wavelength"></div>
    <div class="btns">
      <button class="b" id="playT" aria-pressed="false">&#9654; blink through time</button>
      <button class="b" id="playW" aria-pressed="false">&#9654; sweep wavelength</button>
    </div>
    <div class="info" id="info"></div>
    <div class="opts">
      <label>stretch <select id="stretch"><option value="band">fixed for this band</option><option value="frame">per frame</option></select></label>
      <label><input type="checkbox" id="mask" checked> mask bad pixels</label>
      <label><input type="checkbox" id="marker" checked> predicted position</label>
    </div>
    <canvas id="cov" width="640" height="230"></canvas>
    <div class="hint">Each dot = one image (x: season, y: wavelength at the target). Click a dot to jump to it. Keys: &larr; &rarr; time, &uarr; &darr; next frame in the season.</div>
  </div>
</div>
<script>
const D = __DATA__;
const N = D.n, COLORS = {D1:'--d1',D2:'--d2',D3:'--d3',D4:'--d4',D5:'--d5',D6:'--d6'};
const $ = id => document.getElementById(id);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const dets = Object.keys(D.detectors).sort();
let det = dets[0], season = 0, wl = 0, cur = null, timer = null;

// decode frames once
for (const d of dets) for (const f of D.detectors[d].frames) {
  const bin = atob(f.d), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  f.px = new Float32Array(u8.buffer); delete f.d;
  const mb = atob(f.m); f.bad = new Uint8Array(N * N);                 // bits packed MSB first (numpy packbits)
  for (let i = 0; i < N * N; i++) f.bad[i] = (mb.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1;
  delete f.m;
}
const bandInfo = {};
for (const d of dets) { const fr = D.detectors[d].frames, w = fr.map(f => f.wl);
  bandInfo[d] = {min: Math.min(...w), max: Math.max(...w)}; }

// The stretch is always computed from GOOD pixels only (finite and not flagged bad), so switching the mask on or off
// changes which pixels are shown but never the brightness scale. Flagged pixels shown unmasked clip to white.
function goodValues(frames) { const a = [];
  for (const g of frames) for (let i = 0; i < g.px.length; i++) if (Number.isFinite(g.px[i]) && !g.bad[i]) a.push(g.px[i]);
  return a.sort((x, y) => x - y); }
const lohi = a => a.length ? [a[Math.floor(.02 * a.length)], a[Math.min(a.length - 1, Math.floor(.997 * a.length))]] : [0, 1];
const bandStretch = {};
function stretchFor(d, f) {
  if ($('stretch').value === 'frame') return lohi(goodValues([f]));
  if (!bandStretch[d]) bandStretch[d] = lohi(goodValues(D.detectors[d].frames));
  return bandStretch[d];
}
const asinh = Math.asinh, A = 0.1, norm = asinh(1 / A);

function framesOf(d, s) { return D.detectors[d].frames.filter(f => f.s === s); }
function nearest(d, s, w) { let best = null, bd = 1e9;
  for (const f of framesOf(d, s)) { const e = Math.abs(f.wl - w); if (e < bd) { bd = e; best = f; } }
  return best ? {f: best, dw: bd} : null; }
const wlValue = () => bandInfo[det].min + (+$('w').value / 1000) * (bandInfo[det].max - bandInfo[det].min);

const off = document.createElement('canvas'); off.width = off.height = N;
function draw() {
  const r = nearest(det, season, wlValue()); cur = r ? r.f : null;
  const ctx = $('img').getContext('2d'); const W = $('img').width;
  ctx.imageSmoothingEnabled = false; ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, W);
  const info = $('info');
  if (!cur) { info.innerHTML = '<span class="warn">No frame in this season for this band.</span>'; drawCov(); labels(); return; }
  const [lo, hi] = stretchFor(det, cur), o = off.getContext('2d'), im = o.createImageData(N, N), maskOn = $('mask').checked;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const j = (N - 1 - y) * N + x, v = cur.px[j], k = (y * N + x) * 4;   // row 0 of the data is the bottom
    if (maskOn && cur.bad[j]) { im.data[k] = 110; im.data[k+1] = 30; im.data[k+2] = 30; im.data[k+3] = 255; continue; }   // masked: dark red
    if (!Number.isFinite(v)) { im.data[k] = 50; im.data[k+1] = 55; im.data[k+2] = 70; im.data[k+3] = 255; continue; }       // no data: slate
    const t = Math.min(1, Math.max(0, (v - lo) / (hi - lo))), g = 255 * asinh(t / A) / norm;
    im.data[k] = im.data[k+1] = im.data[k+2] = g; im.data[k+3] = 255;
  }
  o.putImageData(im, 0, 0); ctx.drawImage(off, 0, 0, W, W);
  if ($('marker').checked) { const s = W / N; ctx.strokeStyle = '#ff3b30'; ctx.lineWidth = 2; ctx.beginPath();
    ctx.arc((cur.tx + .5) * s, (N - 1 - cur.ty + .5) * s, 2.2 * s, 0, 7); ctx.stroke(); }
  const tol = 2 * cur.bw, far = r.dw > tol;
  info.innerHTML = (far ? `<span class="warn">No frame at this wavelength in this season; showing the nearest, ${r.dw.toFixed(3)} µm away.</span><br>` : '') +
    `<b>${cur.wl.toFixed(3)} µm</b> (bandwidth ${cur.bw.toFixed(3)}) &middot; ${cur.date} UTC` +
    `<div>${cur.obs} &middot; ${cur.coll} &middot; pipeline ${cur.ver}</div>` +
    `<div>flags at the target: ${cur.flags.length ? cur.flags.join(', ') : 'none'}</div>`;
  drawCov(); labels();
  try { history.replaceState(null, '', `#det=${det}&t=${season}&w=${cur.wl.toFixed(3)}&mask=${$('mask').checked ? 1 : 0}`); } catch (e) {}
}
function labels() {
  const s = D.seasons[season];
  $('tlabel').textContent = `season ${season + 1} of ${D.seasons.length}: ${s.start} … ${s.end}  (${framesOf(det, season).length} frames)`;
  $('wlabel').textContent = cur ? `${wlValue().toFixed(3)} µm  (band ${bandInfo[det].min.toFixed(2)}–${bandInfo[det].max.toFixed(2)})` : '';
}
let dots = [];
function drawCov() {
  const c = $('cov'), g = c.getContext('2d'), W = c.width, H = c.height, pad = {l: 44, r: 8, t: 8, b: 20};
  g.clearRect(0, 0, W, H); g.font = '11px system-ui'; g.fillStyle = css('--ink2'); g.strokeStyle = css('--line');
  const ns = D.seasons.length, cw = (W - pad.l - pad.r) / ns, b = bandInfo[det];
  const Y = w => H - pad.b - (w - b.min) / (b.max - b.min || 1) * (H - pad.t - pad.b - 10) - 5;
  for (let i = 0; i < ns; i++) { const x0 = pad.l + i * cw; g.strokeRect(x0, pad.t, cw, H - pad.t - pad.b);
    if (i === season) { g.globalAlpha = .12; g.fillStyle = css(COLORS[det]); g.fillRect(x0, pad.t, cw, H - pad.t - pad.b); g.globalAlpha = 1; g.fillStyle = css('--ink2'); }
    g.fillText(D.seasons[i].start.slice(0, 7), x0 + 4, H - 6); }
  for (let k = 0; k <= 4; k++) { const w = b.min + k / 4 * (b.max - b.min); g.fillText(w.toFixed(2), 2, Y(w) + 4); }
  dots = [];
  for (const f of D.detectors[det].frames) { const sf = framesOf(det, f.s), m0 = Math.min(...sf.map(x => x.mjd)), m1 = Math.max(...sf.map(x => x.mjd));
    const x = pad.l + f.s * cw + 8 + (m1 > m0 ? (f.mjd - m0) / (m1 - m0) : .5) * (cw - 16), y = Y(f.wl);
    dots.push({x, y, f}); g.beginPath(); g.arc(x, y, 3, 0, 7); g.fillStyle = css(COLORS[det]); g.fill();
    g.lineWidth = 1; g.strokeStyle = css('--bg'); g.stroke(); }
  if (cur) { const d = dots.find(q => q.f === cur); if (d) { g.beginPath(); g.arc(d.x, d.y, 7, 0, 7); g.lineWidth = 2; g.strokeStyle = css('--ink'); g.stroke(); } }
}
$('cov').addEventListener('click', e => { const r = $('cov').getBoundingClientRect(), sx = $('cov').width / r.width;
  const x = (e.clientX - r.left) * sx, y = (e.clientY - r.top) * sx; let best = null, bd = 1e9;
  for (const d of dots) { const e2 = (d.x - x) ** 2 + (d.y - y) ** 2; if (e2 < bd) { bd = e2; best = d; } }
  if (best) select(best.f.s, best.f.wl); });

function select(s, w) { season = s; $('t').value = s;
  const b = bandInfo[det]; $('w').value = Math.round((w - b.min) / (b.max - b.min || 1) * 1000); draw(); }
function setDet(d) { det = d; stop();
  document.querySelectorAll('.tab').forEach(t => t.setAttribute('aria-selected', t.dataset.d === d));
  $('t').max = D.seasons.length - 1; $('t').value = season = Math.min(season, D.seasons.length - 1);
  if (!framesOf(d, season).length) { const f = D.detectors[d].frames[0]; season = f.s; $('t').value = season; }
  $('w').value = Math.min(1000, Math.max(0, +$('w').value)); draw(); }
function stop() { clearInterval(timer); timer = null; $('playT').setAttribute('aria-pressed', false); $('playW').setAttribute('aria-pressed', false); }
$('playT').onclick = () => { if (timer) return stop(); $('playT').setAttribute('aria-pressed', true);
  timer = setInterval(() => { let s = season, n = D.seasons.length;
    for (let i = 1; i <= n; i++) { const c = (season + i) % n, r = nearest(det, c, wlValue()); if (r && r.dw <= 2 * r.f.bw) { s = c; break; } }
    season = s; $('t').value = s; draw(); }, 700); };
$('playW').onclick = () => { if (timer) return stop(); $('playW').setAttribute('aria-pressed', true);
  timer = setInterval(() => step(1, true), 350); };
function step(dir, wrap) { const fr = framesOf(det, season); if (!fr.length) return;
  let i = fr.indexOf(cur); i = i < 0 ? 0 : i + dir; if (i >= fr.length) i = wrap ? 0 : fr.length - 1; if (i < 0) i = 0; select(season, fr[i].wl); }
$('t').oninput = e => { season = +e.target.value; draw(); };
$('w').oninput = draw; $('stretch').onchange = draw; $('marker').onchange = draw; $('mask').onchange = draw;
addEventListener('keydown', e => { if (e.key === 'ArrowLeft') { season = Math.max(0, season - 1); $('t').value = season; draw(); }
  else if (e.key === 'ArrowRight') { season = Math.min(D.seasons.length - 1, season + 1); $('t').value = season; draw(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); step(1); } else if (e.key === 'ArrowDown') { e.preventDefault(); step(-1); } });
addEventListener('resize', draw);

$('title').textContent = `${D.target}: SPHEREx frames by band`;
$('sub').textContent = `${D.size_deg}° field, ${D.pixel_scale_arcsec}″ pixels, north up. ${dets.reduce((n, d) => n + D.detectors[d].frames.length, 0)} frames.`;
for (const d of dets) { const b = document.createElement('button'); b.className = 'tab'; b.dataset.d = d; b.style.setProperty('--c', css(COLORS[d]));
  b.setAttribute('role', 'tab'); b.innerHTML = `${d}<small>${bandInfo[d].min.toFixed(2)}–${bandInfo[d].max.toFixed(2)} µm &middot; ${D.detectors[d].frames.length}</small>`;
  b.onclick = () => setDet(d); $('tabs').appendChild(b); }
// state can be given in the URL, e.g. viewer.html#det=D5&t=1&w=4.2  (band, season index from 0, wavelength in µm)
const H = new URLSearchParams(location.hash.slice(1));
if (dets.includes(H.get('det'))) det = H.get('det');
if (H.has('t')) season = Math.max(0, Math.min(D.seasons.length - 1, +H.get('t')));
if (H.get('mask') === '0') $('mask').checked = false;
$('hint').innerHTML = `<b>dark red</b> = masked pixel (flag ${D.bad_flags.join(', ')} set; untick "mask bad pixels" to see the raw values) &middot; ` +
  `<b>slate</b> = no data &middot; <b>red ring</b> = where proper motion predicts the target`;
setDet(det);
if (H.has('w')) select(season, +H.get('w'));
</script></body></html>
"""


if __name__ == "__main__":
    main()
