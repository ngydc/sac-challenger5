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
 * Linear: evenly spaced round values. Asinh: 0, ±1·10^k first, then ±2 and ±5·10^k where there is room; if
 * that gives fewer than three labels (a narrow, zoomed range), evenly spaced round values as on a linear axis.
 */
export function yTicks(lo: number, hi: number, sc: YScale, heightPx: number, minGapPx = 16): YTick[] {
  const span = hi - lo;
  if (!(span > 0) || !(heightPx > 0)) return [];
  const px = (t: number) => (t / span) * heightPx;
  const accept = (cands: number[], label: (v: number) => string = fmtTick): YTick[] => {
    const out: YTick[] = [];
    for (const v of cands) {
      const t = toAxis(v, sc);
      if (t < lo || t > hi) continue;
      if (out.some((o) => o.value === v || Math.abs(px(o.t) - px(t)) < minGapPx)) continue;
      out.push({ value: v, t, label: label(v) });
    }
    return out.sort((a, b) => a.t - b.t);
  };
  const withZero = (ticks: number[]) => (lo <= 0 && hi >= 0 ? [0, ...ticks] : ticks);

  if (sc.kind === 'linear') {
    const n = Math.max(2, Math.min(6, Math.floor(heightPx / (minGapPx * 2.5))));
    return accept(withZero(denseTicks(lo, hi, n)), stepLabel);
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
  const coarse = accept([0, ...signed(1), ...signed(5), ...signed(2)]);
  if (coarse.length >= 3) return coarse;
  // A narrow range (e.g. one detector zoomed in) has too few of those: use evenly spaced round values instead.
  // Over a narrow range asinh is close to linear, so they are also close to evenly spaced on the axis.
  const n = Math.max(2, Math.min(6, Math.floor(heightPx / (minGapPx * 2.5))));
  const fine = accept(withZero(denseTicks(vLo, vHi, n)), stepLabel);
  return fine.length > coarse.length ? fine : coarse;
}

/** niceTicks inside [lo, hi]; twice as dense if that gives fewer than three (the caller still keeps labels apart). */
function denseTicks(lo: number, hi: number, n: number): number[] {
  const inside = (ts: number[]) => ts.filter((t) => t >= lo && t <= hi);
  const ticks = inside(niceTicks(lo, hi, n));
  return ticks.length >= 3 ? ticks : inside(niceTicks(lo, hi, n * 2));
}

/** Label of a round tick from niceTicks: exact (it is already rounded), so close ticks never look alike. */
const stepLabel = (v: number) => String(+v.toPrecision(10));

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

// ---------------------------------------------------------------------------------------------- epoch colours

/**
 * Colours on the dark surface (validated categorical set, dataviz reference palette, dark column).
 * `later`/`earlier` match the difference picture (blue = brighter later, red = brighter earlier).
 * `others` are kept clearly apart from both: no orange or pink next to the red, no second blue.
 * `sequence` is the plain order used when there is no pair (unchanged from before).
 */
export const EPOCH_COLOURS = {
  later: '#3987e5',
  earlier: '#e66767',
  others: ['#199e70', '#c98500', '#9085e9'],
  sequence: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#0ca30c', '#9085e9', '#e66767'],
} as const;

/**
 * later / earlier: the two epochs the picture compares. other: any further epoch while there is a pair.
 * plain: there is no pair (no picture, or its epochs are not in the spectrum), so no epoch has a meaning.
 */
export type EpochRole = 'later' | 'earlier' | 'other' | 'plain';

export interface EpochStyle {
  epoch: number;
  role: EpochRole;
  colour: string;
}

/** The two epochs a difference picture compares, as global epoch indices (`DiffPair.first/last.epoch`). */
export interface EpochPair {
  first: number;
  last: number;
}

/**
 * Role and colour of every epoch of a spectrum (`Spectrum.epochs[].index`, in that order), for the pair of the
 * picture. The pair's indices and the spectrum's are the same global epoch indices (backend: both index the
 * result's `epochs`), so they are compared directly. A pair counts only if both epochs are in the list and
 * differ; otherwise every epoch is `plain` and coloured by position, as before. Other epochs are coloured by
 * their rank among the non-pair epochs, so each keeps its colour as long as the pair stays the same.
 */
export function epochStyles(epochs: readonly number[], pair: EpochPair | null): EpochStyle[] {
  const ok = !!pair && pair.first !== pair.last && epochs.includes(pair.first) && epochs.includes(pair.last);
  if (!ok)
    return epochs.map((epoch, i) => ({
      epoch,
      role: 'plain',
      colour: EPOCH_COLOURS.sequence[i % EPOCH_COLOURS.sequence.length],
    }));
  // `last` is the later epoch by definition (backend: first < last); compare anyway so a swapped pair stays honest.
  const later = Math.max(pair!.first, pair!.last);
  const earlier = Math.min(pair!.first, pair!.last);
  let k = 0;
  return epochs.map((epoch) => {
    if (epoch === later) return { epoch, role: 'later', colour: EPOCH_COLOURS.later };
    if (epoch === earlier) return { epoch, role: 'earlier', colour: EPOCH_COLOURS.earlier };
    return { epoch, role: 'other', colour: EPOCH_COLOURS.others[k++ % EPOCH_COLOURS.others.length] };
  });
}

/** True if the styles have a pair (some epoch is `later`). */
export function hasPair(styles: readonly EpochStyle[]): boolean {
  return styles.some((s) => s.role === 'later');
}

/**
 * The epochs to draw: without a pair every epoch; with one the pair always, plus the other epochs the user
 * switched on (`shown`). Order as in `styles`.
 */
export function visibleEpochs(styles: readonly EpochStyle[], shown: ReadonlySet<number>): number[] {
  return styles
    .filter((s) => s.role !== 'other' || shown.has(s.epoch))
    .map((s) => s.epoch);
}

/**
 * The user's switched-on epochs after the pair changed: an epoch that is now part of the pair is dropped (it
 * is always visible; if it later becomes an "other" epoch again it starts hidden, like every other epoch).
 * Without a pair nothing is dropped (all epochs are visible then anyway), so the choice survives a step without
 * a picture. Returns the same set if nothing changed.
 */
export function keepShown(shown: ReadonlySet<number>, styles: readonly EpochStyle[]): ReadonlySet<number> {
  const pair = new Set(styles.filter((s) => s.role === 'later' || s.role === 'earlier').map((s) => s.epoch));
  const next = new Set([...shown].filter((e) => !pair.has(e)));
  return next.size === shown.size ? shown : next;
}

/** Drawing rank (higher = drawn later = on top): other epochs below, then the earlier and the later one. */
export function drawRank(role: EpochRole): number {
  return role === 'later' ? 3 : role === 'earlier' ? 2 : 1;
}

/** Short words for a role, for the legend and tooltips (colour is never the only cue). */
export function roleText(role: EpochRole): string {
  switch (role) {
    case 'later':
      return 'later epoch of the picture';
    case 'earlier':
      return 'earlier epoch of the picture';
    case 'other':
      return 'not in the picture';
    default:
      return '';
  }
}

// ---------------------------------------------------------------------------------------------- detector view

/** What the chart shows: every detector, or one of them (its name as in the answer, e.g. "D4"). */
export type DetectorPick = 'all' | string;

export interface DetectorChoice {
  detector: string;
  band: DetectorBand;
  /** False if no channel of this detector has a finite value in any epoch at this pixel (null = not measured). */
  hasData: boolean;
}

/**
 * The detectors the user can pick, in wavelength order (from detectorBands, so nothing is hard-coded), each
 * marked whether it has at least one measured value at this pixel.
 */
export function detectorChoices(channels: readonly SpectrumChannel[]): DetectorChoice[] {
  const measured = new Set<string>();
  for (const c of channels)
    if (isFiniteNumber(c.wavelength_um) && c.epochs.some((e) => isFiniteNumber(e.value)))
      measured.add(c.detector);
  return detectorBands(channels).map((band) => ({
    detector: band.detector,
    band,
    hasData: measured.has(band.detector),
  }));
}

/**
 * The pick to keep after new data arrived (another pixel): the same detector if it has values there, else
 * 'all'.
 */
export function keepPick(pick: DetectorPick, channels: readonly SpectrumChannel[]): DetectorPick {
  if (pick === 'all') return 'all';
  return detectorChoices(channels).some((c) => c.detector === pick && c.hasData) ? pick : 'all';
}

export interface SpectrumView {
  /** The detector shown, or 'all'. A pick that cannot be shown (unknown, or no values) falls back to 'all'. */
  pick: DetectorPick;
  /** Channels to draw (lines, points); for 'all' every channel. */
  channels: readonly SpectrumChannel[];
  /** Stripes to draw: every band for 'all', the picked one otherwise. */
  bands: DetectorBand[];
  /** x range (µm). */
  x: [number, number];
  /** y range on the TRANSFORMED axis (the given scale), the visible epochs together. */
  y: [number, number];
}

/** yDomain of the visible epochs; all epochs if those have nothing here (so the axis never collapses). */
function visibleDomain(
  channels: readonly SpectrumChannel[],
  sc: YScale,
  includeZero: boolean,
  epochs: readonly number[] | undefined,
): [number, number] | null {
  return (
    (epochs ? yDomain(channels, sc, { includeZero, epochs }) : null) ?? yDomain(channels, sc, { includeZero })
  );
}

/**
 * The chart view for a pick, shared by every chart that follows the detector picker (spectrum, later the
 * difference chart):
 * - 'all': every channel; y range includes zero.
 * - one detector: only its channels and stripe, x over its band, y fitted to its values alone (zero NOT forced
 *   in, so small differences between epochs fill the height).
 * The scale (and with it the asinh parameter s, from all channels of the pixel) is passed in unchanged, so
 * switching views changes only the window, never the shape of the curves. `fallbackX` is used without bands.
 * `epochs`: only these epochs set the y range (hidden ones do not); omitted = all. If they have no values in
 * the view, all epochs are used.
 */
export function spectrumView(
  channels: readonly SpectrumChannel[],
  pick: DetectorPick,
  sc: YScale,
  fallbackX: [number, number] = [0.7, 5.1],
  epochs?: readonly number[],
): SpectrumView {
  const all = detectorBands(channels);
  const choice = pick === 'all' ? undefined : detectorChoices(channels).find((c) => c.detector === pick);
  if (choice?.hasData) {
    const own = channels.filter((c) => c.detector === choice.detector);
    return {
      pick: choice.detector,
      channels: own,
      bands: [choice.band],
      x: xDomain([choice.band]) ?? fallbackX,
      y: visibleDomain(own, sc, false, epochs) ?? [0, 1],
    };
  }
  return {
    pick: 'all',
    channels,
    bands: all,
    x: xDomain(all) ?? fallbackX,
    y: visibleDomain(channels, sc, true, epochs) ?? [0, 1],
  };
}
