import { Spectrum, SpectrumChannel } from '../models/epochs.models';

/*
 * Pure helpers for the pixel spectrum chart (components/epochs/spectrum-panel.ts).
 *
 * Everything takes plain channel lists, so a caller can pass all channels or only a subset (e.g. one detector)
 * and get the x range, detector bands, line segments and y limits for exactly that subset. The y scale
 * parameter `s` is computed separately (asinhScale, from all data of the pixel) and passed in, so a zoomed view
 * keeps the same transformation as the full one.
 */

/** A number that can be drawn: not null, not NaN, not ±Infinity. */
export function isFiniteNumber(v: number | null | undefined): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

export function median(xs: readonly number[]): number {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// ---------------------------------------------------------------------------------------------- y scale

/** How values are mapped to the y axis. `asinh`: T(I) = asinh(I / s); `linear`: T(I) = I. */
export type YScale = { kind: 'linear' } | { kind: 'asinh'; s: number };

export const LINEAR: YScale = { kind: 'linear' };

/**
 * The asinh scale parameter of one pixel, from ALL its channels and epochs (never per epoch or detector, so
 * real brightness differences survive):
 *   s = 3 × median of the sigmas that are finite and > 0;
 *   without such sigmas: s = 1.4826 × MAD of the finite values (MAD = median absolute deviation from the median);
 *   null if that is not positive and finite either (the chart then stays linear).
 */
export function asinhScale(channels: readonly SpectrumChannel[]): number | null {
  const sigmas: number[] = [];
  const values: number[] = [];
  for (const c of channels)
    for (const e of c.epochs) {
      if (isFiniteNumber(e.sigma) && e.sigma > 0) sigmas.push(e.sigma);
      if (isFiniteNumber(e.value)) values.push(e.value);
    }
  if (sigmas.length) {
    const s = 3 * median(sigmas);
    if (Number.isFinite(s) && s > 0) return s;
  }
  if (!values.length) return null;
  const m = median(values);
  const mad = 1.4826 * median(values.map((v) => Math.abs(v - m)));
  return Number.isFinite(mad) && mad > 0 ? mad : null;
}

/** The scale for a requested kind; asinh without a usable `s` falls back to linear. */
export function yScale(kind: 'linear' | 'asinh', s: number | null): YScale {
  return kind === 'asinh' && isFiniteNumber(s) && s > 0 ? { kind: 'asinh', s } : LINEAR;
}

/** Value (MJy/sr) → position on the transformed axis. */
export function toAxis(v: number, sc: YScale): number {
  return sc.kind === 'asinh' ? Math.asinh(v / sc.s) : v;
}

/** Position on the transformed axis → value (MJy/sr). */
export function fromAxis(t: number, sc: YScale): number {
  return sc.kind === 'asinh' ? Math.sinh(t) * sc.s : t;
}

/**
 * Y limits on the TRANSFORMED axis for the finite values of the given channels (all epochs together, never one
 * per epoch). Zero is included unless `includeZero` is false (a zoom may leave it out), and 5 % padding is added.
 * Identical values still give a usable range. Returns null if there is nothing to draw.
 */
export function yDomain(
  channels: readonly SpectrumChannel[],
  sc: YScale,
  opts: { includeZero?: boolean; epochs?: readonly number[] } = {},
): [number, number] | null {
  const ts: number[] = [];
  for (const c of channels)
    for (const e of c.epochs)
      if (isFiniteNumber(e.value) && (!opts.epochs || opts.epochs.includes(e.epoch)))
        ts.push(toAxis(e.value, sc));
  if (!ts.length) return null;
  if (opts.includeZero ?? true) ts.push(0);
  let lo = Math.min(...ts);
  let hi = Math.max(...ts);
  if (hi - lo <= 0) {
    // All values equal (and zero left out, or all zero): a band around them.
    const half = Math.abs(lo) * 0.1 || 1;
    return [lo - half, hi + half];
  }
  const pad = (hi - lo) * 0.05;
  lo -= pad;
  hi += pad;
  return [lo, hi];
}

// ---------------------------------------------------------------------------------------------- ticks

/** "Nice" round values between lo and hi (1, 2, 2.5, 5 × 10^k steps). */
export function niceTicks(lo: number, hi: number, n = 5): number[] {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) out.push(+t.toPrecision(10));
  return out;
}

export interface YTick {
  /** Real value in MJy/sr (what the label says). */
  value: number;
  /** Position on the transformed axis. */
  t: number;
  label: string;
}

/** Short label for a tick value: 0, 0.05, 0.1, 1, 10, 150 … */
export function fmtTick(v: number): string {
  if (v === 0) return '0';
  return String(+v.toPrecision(Math.abs(v) >= 1 ? 3 : 2));
}

/**
 * Y ticks for a transformed range [lo, hi] (axis units) drawn `heightPx` tall: positions on the transformed
 * axis, labels in real MJy/sr. Labels are at least `minGapPx` apart. Zero comes first if it is in range.
 * Linear: evenly spaced round values. Asinh: 0, ±1·10^k first, then ±2 and ±5·10^k where there is room.
 */
export function yTicks(lo: number, hi: number, sc: YScale, heightPx: number, minGapPx = 16): YTick[] {
  const span = hi - lo;
  if (!(span > 0) || !(heightPx > 0)) return [];
  const px = (t: number) => (t / span) * heightPx;
  const accept = (cands: number[]): YTick[] => {
    const out: YTick[] = [];
    for (const v of cands) {
      const t = toAxis(v, sc);
      if (t < lo || t > hi) continue;
      if (out.some((o) => o.value === v || Math.abs(px(o.t) - px(t)) < minGapPx)) continue;
      out.push({ value: v, t, label: fmtTick(v) });
    }
    return out.sort((a, b) => a.t - b.t);
  };

  if (sc.kind === 'linear') {
    const n = Math.max(2, Math.min(6, Math.floor(heightPx / (minGapPx * 2.5))));
    const ticks = niceTicks(lo, hi, n);
    return accept(lo <= 0 && hi >= 0 ? [0, ...ticks] : ticks);
  }

  const vLo = fromAxis(lo, sc);
  const vHi = fromAxis(hi, sc);
  const maxAbs = Math.max(Math.abs(vLo), Math.abs(vHi));
  if (!(maxAbs > 0)) return accept([0]);
  // Decades from about s/100 (anything smaller sits on top of zero) up to the largest value.
  const kMin = Math.floor(Math.log10(sc.s / 100));
  const kMax = Math.ceil(Math.log10(maxAbs));
  const decades: number[] = [];
  for (let k = kMax; k >= kMin; k--) decades.push(10 ** k);
  const signed = (m: number) =>
    decades.flatMap((d) => [+(m * d).toPrecision(6), +(-m * d).toPrecision(6)]);
  // Priority: zero, then powers of ten (largest first, so the overall scale is always labelled), then 2× and 5×.
  return accept([0, ...signed(1), ...signed(5), ...signed(2)]);
}

// ---------------------------------------------------------------------------------------------- detectors

export interface DetectorBand {
  detector: string;
  /** Background stripe on the x axis (µm): halfway to the neighbours, outer channel edges at the ends. */
  x0: number;
  x1: number;
  /** Centre wavelengths of its first and last channel (µm), for the label's tooltip. */
  wlFirst: number;
  wlLast: number;
}

function channelEdges(c: SpectrumChannel): [number, number] {
  const w = c.wavelength_um as number;
  return [isFiniteNumber(c.wl_min_um) ? c.wl_min_um : w, isFiniteNumber(c.wl_max_um) ? c.wl_max_um : w];
}

/**
 * One band per detector that has channels with a wavelength (values do not matter: a detector without data at
 * this pixel still gets its stripe), sorted by wavelength. "First" and "last" channel are taken by wavelength,
 * not by JSON order. The border between two neighbours is halfway between the upper edge of the lower one's
 * last channel and the lower edge of the upper one's first channel. Nothing is hard-coded: a new release with
 * other band edges just works.
 */
export function detectorBands(channels: readonly SpectrumChannel[]): DetectorBand[] {
  const byDet = new Map<string, SpectrumChannel[]>();
  for (const c of channels) {
    if (!isFiniteNumber(c.wavelength_um)) continue;
    const list = byDet.get(c.detector) ?? [];
    list.push(c);
    byDet.set(c.detector, list);
  }
  const raw = [...byDet.entries()]
    .map(([detector, cs]) => {
      cs.sort((a, b) => (a.wavelength_um as number) - (b.wavelength_um as number));
      const first = cs[0];
      const last = cs[cs.length - 1];
      return {
        detector,
        lo: channelEdges(first)[0],
        hi: channelEdges(last)[1],
        wlFirst: first.wavelength_um as number,
        wlLast: last.wavelength_um as number,
      };
    })
    .sort((a, b) => a.wlFirst - b.wlFirst);
  return raw.map((b, i) => ({
    detector: b.detector,
    x0: i === 0 ? b.lo : (raw[i - 1].hi + b.lo) / 2,
    x1: i === raw.length - 1 ? b.hi : (b.hi + raw[i + 1].lo) / 2,
    wlFirst: b.wlFirst,
    wlLast: b.wlLast,
  }));
}

/** The x range (µm) the given bands cover; null without bands. Pass a subset of bands to zoom. */
export function xDomain(bands: readonly DetectorBand[]): [number, number] | null {
  if (!bands.length) return null;
  return [Math.min(...bands.map((b) => b.x0)), Math.max(...bands.map((b) => b.x1))];
}

/** "D4: 2.45–3.77 µm" */
export function bandTitle(b: DetectorBand): string {
  return `${b.detector}: ${b.wlFirst.toFixed(2)}–${b.wlLast.toFixed(2)} µm`;
}

/**
 * Rows for labels centred at `centers` (px, ascending) with the given widths, so none overlap: a label goes into
 * the first row where it keeps `gap` px from the previous label in that row. Returns the row of each label
 * (0 = top), or -1 if it fits in none of `maxRows` rows (then it is left out).
 */
export function labelRows(centers: readonly number[], widths: readonly number[], gap = 4, maxRows = 2): number[] {
  const rightEdge: number[] = [];
  return centers.map((c, i) => {
    const left = c - widths[i] / 2;
    for (let r = 0; r < maxRows; r++) {
      if (rightEdge[r] === undefined || left >= rightEdge[r] + gap) {
        rightEdge[r] = c + widths[i] / 2;
        return r;
      }
    }
    return -1;
  });
}

// ---------------------------------------------------------------------------------------------- lines

export interface SpecPoint {
  detector: string;
  channel: number;
  wl: number;
  value: number;
  sigma: number | null;
}

export interface EpochSeries {
  epoch: number;
  /** Runs of measured channels to connect with a line: one detector each, sorted by wavelength. */
  segments: SpecPoint[][];
  /** All drawable points of this epoch (the segments flattened). */
  points: SpecPoint[];
}

/**
 * Points and line segments of one epoch over the given channels. A line never crosses a detector border and
 * breaks at every channel without a finite value (or without a wavelength): nothing is interpolated or bridged.
 */
export function epochSeries(channels: readonly SpectrumChannel[], epoch: number): EpochSeries {
  const byDet = new Map<string, SpectrumChannel[]>();
  for (const c of channels) {
    const list = byDet.get(c.detector) ?? [];
    list.push(c);
    byDet.set(c.detector, list);
  }
  const segments: SpecPoint[][] = [];
  for (const cs of byDet.values()) {
    // Channels without a wavelength cannot be placed; they still break the line (sorted last, then dropped).
    const sorted = [...cs].sort(
      (a, b) => (a.wavelength_um ?? Infinity) - (b.wavelength_um ?? Infinity),
    );
    let run: SpecPoint[] = [];
    for (const c of sorted) {
      const e = c.epochs.find((x) => x.epoch === epoch);
      if (isFiniteNumber(c.wavelength_um) && e && isFiniteNumber(e.value)) {
        run.push({
          detector: c.detector,
          channel: c.channel,
          wl: c.wavelength_um,
          value: e.value,
          sigma: isFiniteNumber(e.sigma) ? e.sigma : null,
        });
      } else if (run.length) {
        segments.push(run);
        run = [];
      }
    }
    if (run.length) segments.push(run);
  }
  segments.sort((a, b) => a[0].wl - b[0].wl);
  return { epoch, segments, points: segments.flat() };
}

/** epochSeries for every epoch of the spectrum, in its order (epochs without any point included, empty). */
export function spectrumSeries(sp: Spectrum, channels: readonly SpectrumChannel[] = sp.channels): EpochSeries[] {
  return sp.epochs.map((e) => epochSeries(channels, e.index));
}
