import { Spectrum, SpectrumChannel } from '../models/epochs.models';
import {
  LINEAR,
  asinhScale,
  bandTitle,
  detectorBands,
  epochSeries,
  fromAxis,
  labelRows,
  median,
  spectrumSeries,
  toAxis,
  xDomain,
  yDomain,
  yScale,
  yTicks,
} from './spectrum';
// Real answers of GET /api/analysis/spectrum (Barnard's Star, 2026-11-15): a pixel on the star's wing
// (x 26, y 26 from the bottom) and one on empty sky (x 40, y 8).
import starJson from './fixtures/spectrum-star.json';
import skyJson from './fixtures/spectrum-empty-sky.json';

const star = starJson as Spectrum;
const sky = skyJson as Spectrum;

type Ep = { value: number | null; sigma?: number | null };
const ch = (
  detector: string,
  channel: number,
  wl: number | null,
  eps: Ep[],
  edges: [number | null, number | null] = [wl === null ? null : wl - 0.01, wl === null ? null : wl + 0.01],
): SpectrumChannel => ({
  detector,
  channel,
  wavelength_um: wl,
  wl_min_um: edges[0],
  wl_max_um: edges[1],
  epochs: eps.map((e, i) => ({ epoch: i, value: e.value, sigma: e.sigma ?? null, n: 1 })),
});

describe('asinh scale parameter', () => {
  it('is 3 × the median sigma over all epochs and detectors', () => {
    const chans = [
      ch('D1', 1, 1, [{ value: 1, sigma: 0.01 }, { value: 2, sigma: 0.02 }]),
      ch('D2', 1, 2, [{ value: 1, sigma: 0.03 }, { value: null, sigma: null }]),
    ];
    expect(asinhScale(chans)).toBeCloseTo(0.06);
  });

  it('ignores sigmas that are zero, negative or not finite', () => {
    const chans = [ch('D1', 1, 1, [{ value: 1, sigma: 0 }, { value: 1, sigma: -1 }, { value: 1, sigma: NaN }, { value: 1, sigma: 0.1 }])];
    expect(asinhScale(chans)).toBeCloseTo(0.3);
  });

  it('gives about 0.075 for a real empty-sky pixel', () => {
    const s = asinhScale(sky.channels)!;
    expect(s).toBeGreaterThan(0.05);
    expect(s).toBeLessThan(0.1);
  });

  it('falls back to 1.4826 × MAD of the values without usable sigmas', () => {
    const chans = [ch('D1', 1, 1, [{ value: 1 }, { value: 2 }, { value: 3 }, { value: 4 }, { value: 100 }])];
    // median 3, deviations 2,1,0,1,97 → MAD 1
    expect(asinhScale(chans)).toBeCloseTo(1.4826);
  });

  it('is null when neither works (all equal or nothing measured); the chart then stays linear', () => {
    expect(asinhScale([ch('D1', 1, 1, [{ value: 5 }, { value: 5 }])])).toBeNull();
    expect(asinhScale([ch('D1', 1, 1, [{ value: null }])])).toBeNull();
    expect(yScale('asinh', null)).toEqual(LINEAR);
    expect(yScale('asinh', 0.1)).toEqual({ kind: 'asinh', s: 0.1 });
    expect(yScale('linear', 0.1)).toEqual(LINEAR);
  });
});

describe('transformation', () => {
  it('is linear near zero, logarithmic far away, odd, and invertible', () => {
    const sc = { kind: 'asinh', s: 0.1 } as const;
    expect(toAxis(0.001, sc)).toBeCloseTo(0.01, 4);
    expect(toAxis(-2, sc)).toBeCloseTo(-toAxis(2, sc));
    expect(toAxis(100, sc) - toAxis(10, sc)).toBeCloseTo(Math.log(10), 2);
    for (const v of [-3, -0.02, 0, 0.5, 42]) expect(fromAxis(toAxis(v, sc), sc)).toBeCloseTo(v, 9);
    expect(toAxis(7, LINEAR)).toBe(7);
  });
});

describe('y domain', () => {
  it('uses all epochs together, includes zero and pads', () => {
    const chans = [ch('D1', 1, 1, [{ value: 1 }, { value: 9 }])];
    const [lo, hi] = yDomain(chans, LINEAR)!;
    expect(lo).toBeLessThan(0);
    expect(hi).toBeGreaterThan(9);
  });

  it('keeps both signs of an empty-sky pixel in range', () => {
    const sc = yScale('asinh', asinhScale(sky.channels));
    const [lo, hi] = yDomain(sky.channels, sc)!;
    const vals = sky.channels.flatMap((c) => c.epochs.map((e) => e.value)).filter((v) => v !== null) as number[];
    expect(lo).toBeLessThan(toAxis(Math.min(...vals), sc));
    expect(hi).toBeGreaterThan(toAxis(Math.max(...vals), sc));
    expect(Math.min(...vals)).toBeLessThan(0);
  });

  it('gives a usable range for identical values and null for nothing', () => {
    const same = [ch('D1', 1, 1, [{ value: 3 }, { value: 3 }])];
    const [lo, hi] = yDomain(same, LINEAR, { includeZero: false })!;
    expect(hi - lo).toBeGreaterThan(0);
    expect(lo).toBeLessThan(3);
    expect(hi).toBeGreaterThan(3);
    const zeros = [ch('D1', 1, 1, [{ value: 0 }, { value: 0 }])];
    const [zl, zh] = yDomain(zeros, LINEAR)!;
    expect(zh - zl).toBeGreaterThan(0);
    expect(yDomain([ch('D1', 1, 1, [{ value: null }])], LINEAR)).toBeNull();
  });

  it('can be limited to a subset of channels (zoom) without changing s', () => {
    const s = asinhScale(star.channels)!;
    const sc = yScale('asinh', s);
    const d6 = star.channels.filter((c) => c.detector === 'D6');
    const all = yDomain(star.channels, sc)!;
    const sub = yDomain(d6, sc, { includeZero: false })!;
    expect(sub[1] - sub[0]).toBeLessThan(all[1] - all[0]);
    expect(asinhScale(star.channels)).toBe(s);
  });
});

describe('y ticks', () => {
  const H = 200;
  it('are labelled in real values, include zero, and do not overlap (asinh, bright star)', () => {
    const sc = yScale('asinh', asinhScale(star.channels));
    const [lo, hi] = yDomain(star.channels, sc)!;
    const ticks = yTicks(lo, hi, sc, H);
    expect(ticks.map((t) => t.label)).toContain('0');
    expect(ticks.map((t) => t.label)).toContain('10');
    expect(ticks.map((t) => t.label)).toContain('1');
    for (const t of ticks) expect(t.t).toBeCloseTo(toAxis(t.value, sc));
    const px = ticks.map((t) => ((t.t - lo) / (hi - lo)) * H);
    for (let i = 1; i < px.length; i++) expect(px[i] - px[i - 1]).toBeGreaterThanOrEqual(16);
  });

  it('show negative and positive values on empty sky', () => {
    const sc = yScale('asinh', asinhScale(sky.channels));
    const [lo, hi] = yDomain(sky.channels, sc)!;
    const vals = yTicks(lo, hi, sc, H).map((t) => t.value);
    expect(vals.some((v) => v < 0)).toBe(true);
    expect(vals.some((v) => v > 0)).toBe(true);
    expect(vals).toContain(0);
  });

  it('are round and evenly spaced on a linear axis', () => {
    const ticks = yTicks(-0.5, 10, LINEAR, H);
    expect(ticks.map((t) => t.value)).toEqual([0, 2.5, 5, 7.5, 10]);
  });

  it('stay apart in a short chart', () => {
    const sc = { kind: 'asinh', s: 0.075 } as const;
    const ticks = yTicks(toAxis(-1, sc), toAxis(100, sc), sc, 80);
    const px = ticks.map((t) => (t.t / (toAxis(100, sc) - toAxis(-1, sc))) * 80);
    for (let i = 1; i < px.length; i++) expect(px[i] - px[i - 1]).toBeGreaterThanOrEqual(16);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
  });
});

describe('detector bands', () => {
  it('cover D1–D6 of a real answer, borders halfway between neighbouring channel edges', () => {
    const bands = detectorBands(sky.channels);
    expect(bands.map((b) => b.detector)).toEqual(['D1', 'D2', 'D3', 'D4', 'D5', 'D6']);
    const d1 = sky.channels.filter((c) => c.detector === 'D1');
    const d2 = sky.channels.filter((c) => c.detector === 'D2');
    const d1Last = d1.reduce((a, b) => (b.wavelength_um! > a.wavelength_um! ? b : a));
    const d2First = d2.reduce((a, b) => (b.wavelength_um! < a.wavelength_um! ? b : a));
    expect(bands[0].x1).toBeCloseTo((d1Last.wl_max_um! + d2First.wl_min_um!) / 2);
    expect(bands[1].x0).toBe(bands[0].x1);
    expect(bands[0].x0).toBe(Math.min(...d1.map((c) => c.wl_min_um!)));
    for (let i = 1; i < bands.length; i++) expect(bands[i].x0).toBe(bands[i - 1].x1);
    expect(bandTitle(bands[3])).toBe('D4: 2.44–3.77 µm') // first channel centre 2.445;
  });

  it('take first and last channel by wavelength, not by JSON order, and skip channels without one', () => {
    const chans = [
      ch('D2', 1, 2.0, [{ value: 1 }]),
      ch('D1', 2, 1.2, [{ value: 1 }]),
      ch('D1', 9, null, [{ value: 1 }]),
      ch('D1', 1, 1.0, [{ value: 1 }]),
      ch('D2', 2, 2.4, [{ value: 1 }]),
    ];
    const bands = detectorBands(chans);
    expect(bands.map((b) => b.detector)).toEqual(['D1', 'D2']);
    expect(bands[0]).toMatchObject({ x0: 0.99, wlFirst: 1.0, wlLast: 1.2 });
    expect(bands[0].x1).toBeCloseTo((1.21 + 1.99) / 2);
    expect(bands[1].x1).toBeCloseTo(2.41);
    expect(xDomain(bands)).toEqual([0.99, bands[1].x1]);
    expect(xDomain([bands[1]])).toEqual([bands[1].x0, bands[1].x1]);
  });

  it('include a detector that has channels but no values at this pixel', () => {
    const chans = [ch('D1', 1, 1, [{ value: 1 }]), ch('D2', 1, 2, [{ value: null }])];
    expect(detectorBands(chans).map((b) => b.detector)).toEqual(['D1', 'D2']);
  });
});

describe('label rows', () => {
  it('keep labels in one row when they fit and move overlapping ones down', () => {
    expect(labelRows([10, 40, 70], [14, 14, 14])).toEqual([0, 0, 0]);
    expect(labelRows([10, 20, 30], [14, 14, 14])).toEqual([0, 1, 0]);
    expect(labelRows([10, 11, 12], [14, 14, 14])).toEqual([0, 1, -1]);
  });
});

describe('line segments', () => {
  it('break at a missing value and never bridge it', () => {
    const chans = [
      ch('D1', 1, 1.0, [{ value: 1 }]),
      ch('D1', 2, 1.1, [{ value: null }]),
      ch('D1', 3, 1.2, [{ value: 3 }]),
      ch('D1', 4, 1.3, [{ value: NaN }]),
      ch('D1', 5, 1.4, [{ value: 5 }]),
      ch('D1', 6, 1.5, [{ value: 6 }]),
    ];
    const s = epochSeries(chans, 0);
    expect(s.segments.map((seg) => seg.map((p) => p.channel))).toEqual([[1], [3], [5, 6]]);
    expect(s.points).toHaveLength(4);
  });

  it('never cross a detector border and sort by wavelength within a detector', () => {
    const chans = [
      ch('D2', 2, 2.1, [{ value: 4 }]),
      ch('D1', 2, 1.1, [{ value: 2 }]),
      ch('D2', 1, 2.0, [{ value: 3 }]),
      ch('D1', 1, 1.0, [{ value: 1 }]),
    ];
    const s = epochSeries(chans, 0);
    expect(s.segments.map((seg) => seg.map((p) => `${p.detector}/${p.channel}`))).toEqual([
      ['D1/1', 'D1/2'],
      ['D2/1', 'D2/2'],
    ]);
  });

  it('on real data: every segment stays within one detector, no point has a null value', () => {
    for (const sp of [star, sky]) {
      const all = spectrumSeries(sp);
      expect(all).toHaveLength(sp.epochs.length);
      for (const e of all) {
        for (const seg of e.segments) expect(new Set(seg.map((p) => p.detector)).size).toBe(1);
        for (const p of e.points) expect(Number.isFinite(p.value)).toBe(true);
      }
      const measured = sp.channels.flatMap((c) => c.epochs).filter((e) => e.value !== null).length;
      expect(all.reduce((n, e) => n + e.points.length, 0)).toBe(measured);
    }
  });
});

describe('median', () => {
  it('handles odd, even and empty lists', () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(median([])).toBeNaN();
  });
});
