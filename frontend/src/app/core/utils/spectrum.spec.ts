import { Spectrum, SpectrumChannel } from '../models/epochs.models';
import {
  EPOCH_COLOURS,
  LINEAR,
  asinhScale,
  drawRank,
  epochStyles,
  hasPair,
  keepShown,
  roleText,
  visibleEpochs,
  bandTitle,
  detectorBands,
  detectorChoices,
  keepPick,
  spectrumView,
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

describe('detector picker', () => {
  it('lists the detectors of the answer in wavelength order and marks those without values', () => {
    const chans = [
      ch('D2', 1, 2, [{ value: null }, { value: NaN }]),
      ch('D1', 1, 1, [{ value: null }, { value: 1 }]),
      ch('D3', 1, 3, [{ value: 4 }]),
    ];
    expect(detectorChoices(chans).map((c) => [c.detector, c.hasData])).toEqual([
      ['D1', true],
      ['D2', false],
      ['D3', true],
    ]);
  });

  it('uses whatever detectors the answer has (no hard-coded list)', () => {
    const chans = [ch('X9', 1, 7, [{ value: 1 }]), ch('A', 1, 0.5, [{ value: 2 }])];
    expect(detectorChoices(chans).map((c) => c.detector)).toEqual(['A', 'X9']);
  });

  it('has values in every detector of the real star and empty-sky pixels', () => {
    for (const sp of [star, sky]) expect(detectorChoices(sp.channels).every((c) => c.hasData)).toBe(true);
  });

  it('keeps the pick on another pixel only if the detector has values there', () => {
    const here = [ch('D1', 1, 1, [{ value: 1 }]), ch('D2', 1, 2, [{ value: 2 }])];
    const there = [ch('D1', 1, 1, [{ value: 1 }]), ch('D2', 1, 2, [{ value: null }])];
    expect(keepPick('D2', here)).toBe('D2');
    expect(keepPick('D2', there)).toBe('all');
    expect(keepPick('D7', here)).toBe('all');
    expect(keepPick('all', there)).toBe('all');
  });
});

describe('spectrum view', () => {
  const sc = yScale('asinh', asinhScale(star.channels));

  it("'all' shows every channel and band, with zero in the y range", () => {
    const v = spectrumView(star.channels, 'all', sc);
    expect(v.pick).toBe('all');
    expect(v.channels).toHaveLength(star.channels.length);
    expect(v.bands).toEqual(detectorBands(star.channels));
    expect(v.x).toEqual(xDomain(detectorBands(star.channels)));
    expect(v.y).toEqual(yDomain(star.channels, sc));
    expect(v.y[0]).toBeLessThanOrEqual(0);
  });

  it('one detector: only its channels, x over its band, y from its values without forcing zero', () => {
    const v = spectrumView(star.channels, 'D4', sc);
    const d4 = star.channels.filter((c) => c.detector === 'D4');
    const band = detectorBands(star.channels).find((b) => b.detector === 'D4')!;
    expect(v.pick).toBe('D4');
    expect(v.channels.every((c) => c.detector === 'D4')).toBe(true);
    expect(v.channels).toHaveLength(d4.length);
    expect(v.bands).toEqual([band]);
    expect(v.x).toEqual([band.x0, band.x1]);
    const vals = d4.flatMap((c) => c.epochs.map((e) => e.value)).filter((x) => x !== null) as number[];
    expect(v.y[0]).toBeGreaterThan(0); // bright star: zero is left out
    expect(v.y[0]).toBeLessThan(toAxis(Math.min(...vals), sc));
    expect(v.y[1]).toBeGreaterThan(toAxis(Math.max(...vals), sc));
  });

  it('does not change the scale: the same value lands at the same transformed position in every view', () => {
    const s = asinhScale(star.channels);
    for (const det of ['all', 'D1', 'D6']) spectrumView(star.channels, det, sc);
    expect(asinhScale(star.channels)).toBe(s);
    expect(sc).toEqual({ kind: 'asinh', s });
  });

  it('falls back to all for a detector without values or an unknown one', () => {
    const chans = [ch('D1', 1, 1, [{ value: 1 }]), ch('D2', 1, 2, [{ value: null }])];
    expect(spectrumView(chans, 'D2', LINEAR).pick).toBe('all');
    expect(spectrumView(chans, 'nope', LINEAR).pick).toBe('all');
  });

  it('gives a usable range for one valid value or identical values', () => {
    const one = [ch('D1', 1, 1, [{ value: 5 }, { value: null }]), ch('D1', 2, 1.1, [{ value: null }])];
    const same = [ch('D1', 1, 1, [{ value: 2 }, { value: 2 }]), ch('D1', 2, 1.1, [{ value: 2 }])];
    for (const chans of [one, same])
      for (const s of [LINEAR, { kind: 'asinh', s: 0.1 } as const]) {
        const v = spectrumView(chans, 'D1', s);
        expect(v.pick).toBe('D1');
        expect(v.y[1] - v.y[0]).toBeGreaterThan(0);
        expect(v.x[1] - v.x[0]).toBeGreaterThan(0);
        expect(yTicks(...v.y, s, 200).length).toBeGreaterThanOrEqual(2);
      }
  });

  it('gives an empty-sky detector both signs and a fallback x range without channels', () => {
    const sk = yScale('asinh', asinhScale(sky.channels));
    const v = spectrumView(sky.channels, 'D1', sk);
    expect(v.y[0]).toBeLessThan(0);
    expect(v.y[1]).toBeGreaterThan(0);
    expect(spectrumView([], 'all', LINEAR)).toMatchObject({ pick: 'all', x: [0.7, 5.1], y: [0, 1] });
  });
});

describe('y ticks in a zoomed detector', () => {
  it('label a narrow asinh range with at least three distinct, ordered values (bright star, every detector)', () => {
    const sc = yScale('asinh', asinhScale(star.channels));
    for (const det of detectorChoices(star.channels)) {
      const v = spectrumView(star.channels, det.detector, sc);
      const ticks = yTicks(...v.y, sc, 192, 18);
      expect(ticks.length).toBeGreaterThanOrEqual(3);
      expect(new Set(ticks.map((t) => t.label)).size).toBe(ticks.length);
      for (let i = 1; i < ticks.length; i++) expect(ticks[i].value).toBeGreaterThan(ticks[i - 1].value);
    }
  });

  it('keep labels distinct when the range is very narrow on a linear axis', () => {
    const ticks = yTicks(150.01, 150.05, LINEAR, 192, 18);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(new Set(ticks.map((t) => t.label)).size).toBe(ticks.length);
  });
});

describe('epoch colours for the picture pair', () => {
  const idx = star.epochs.map((e) => e.index); // [0, 1, 2]

  it('colours the later epoch blue and the earlier red; the third epoch gets another colour (Total 0→2)', () => {
    const st = epochStyles(idx, { first: 0, last: 2 });
    expect(st.map((s) => s.role)).toEqual(['earlier', 'other', 'later']);
    expect(st[2].colour).toBe(EPOCH_COLOURS.later);
    expect(st[0].colour).toBe(EPOCH_COLOURS.earlier);
    expect(st[1].colour).toBe(EPOCH_COLOURS.others[0]);
    expect(hasPair(st)).toBe(true);
  });

  it('follows a step: 1→2 makes epoch 0 the other one', () => {
    const st = epochStyles(idx, { first: 1, last: 2 });
    expect(st.map((s) => s.role)).toEqual(['other', 'earlier', 'later']);
  });

  it('never gives other epochs the pair colours, and keeps them apart from each other', () => {
    const st = epochStyles([0, 1, 2, 3, 4, 5], { first: 2, last: 4 });
    const others = st.filter((s) => s.role === 'other').map((s) => s.colour);
    for (const c of others) expect([EPOCH_COLOURS.later, EPOCH_COLOURS.earlier]).not.toContain(c);
    expect(new Set(others.slice(0, EPOCH_COLOURS.others.length)).size).toBe(Math.min(others.length, EPOCH_COLOURS.others.length));
  });

  it('keeps an other epoch\'s colour for the same pair, whatever the pixel', () => {
    const a = epochStyles(star.epochs.map((e) => e.index), { first: 0, last: 2 });
    const b = epochStyles(sky.epochs.map((e) => e.index), { first: 0, last: 2 });
    expect(a).toEqual(b);
  });

  it('falls back to the plain order without a usable pair (none, same epoch twice, epoch not in the answer)', () => {
    for (const pair of [null, { first: 1, last: 1 }, { first: 0, last: 7 }]) {
      const st = epochStyles(idx, pair);
      expect(st.every((s) => s.role === 'plain')).toBe(true);
      expect(st.map((s) => s.colour)).toEqual(EPOCH_COLOURS.sequence.slice(0, 3));
      expect(hasPair(st)).toBe(false);
    }
  });

  it('with only two epochs gives just blue and red, nothing to switch on', () => {
    const st = epochStyles([0, 1], { first: 0, last: 1 });
    expect(st.map((s) => s.role)).toEqual(['earlier', 'later']);
    expect(visibleEpochs(st, new Set())).toEqual([0, 1]);
  });

  it('draws other epochs first and the pair on top', () => {
    const st = epochStyles(idx, { first: 0, last: 2 });
    const order = [...st].sort((a, b) => drawRank(a.role) - drawRank(b.role)).map((s) => s.role);
    expect(order).toEqual(['other', 'earlier', 'later']);
  });

  it('names every role in words (colour is never the only cue)', () => {
    expect(roleText('later')).toMatch(/later/);
    expect(roleText('earlier')).toMatch(/earlier/);
    expect(roleText('plain')).toBe('');
  });
});

describe('visible epochs', () => {
  const idx = star.epochs.map((e) => e.index);

  it('hides other epochs until switched on; the pair is always visible', () => {
    const st = epochStyles(idx, { first: 0, last: 2 });
    expect(visibleEpochs(st, new Set())).toEqual([0, 2]);
    expect(visibleEpochs(st, new Set([1]))).toEqual([0, 1, 2]);
  });

  it('shows every epoch without a pair', () => {
    expect(visibleEpochs(epochStyles(idx, null), new Set())).toEqual([0, 1, 2]);
  });

  it('drops a switched-on epoch that joins the pair, so it starts hidden when it leaves again', () => {
    const shown = new Set([1]);
    const step = epochStyles(idx, { first: 1, last: 2 });
    const kept = keepShown(shown, step);
    expect([...kept]).toEqual([]);
    expect(visibleEpochs(epochStyles(idx, { first: 0, last: 2 }), kept)).toEqual([0, 2]);
  });

  it('keeps the choice when the pair does not touch it, or when there is no pair', () => {
    const shown = new Set([1]);
    expect(keepShown(shown, epochStyles(idx, { first: 0, last: 2 }))).toBe(shown);
    expect(keepShown(shown, epochStyles(idx, null))).toBe(shown);
  });
});

describe('y range of the visible epochs', () => {
  it('lets only visible epochs set the y range; s stays from all data', () => {
    // A hidden epoch with a much brighter value must not stretch the axis.
    const chans = [
      ch('D1', 1, 1.0, [{ value: 1 }, { value: 100 }, { value: 2 }]),
      ch('D1', 2, 1.1, [{ value: 1.5 }, { value: 120 }, { value: 2.5 }]),
    ];
    const all = spectrumView(chans, 'all', LINEAR);
    const vis = spectrumView(chans, 'all', LINEAR, undefined, [0, 2]);
    expect(all.y[1]).toBeGreaterThan(100);
    expect(vis.y[1]).toBeLessThan(3);
    const zoom = spectrumView(chans, 'D1', LINEAR, undefined, [0, 2]);
    expect(zoom.y[1]).toBeLessThan(3);
    expect(zoom.y[0]).toBeGreaterThan(0.5);
  });

  it('falls back to all epochs when the visible ones have no values in the view', () => {
    const chans = [ch('D1', 1, 1.0, [{ value: null }, { value: 5 }]), ch('D1', 2, 1.1, [{ value: null }, { value: 6 }])];
    const v = spectrumView(chans, 'all', LINEAR, undefined, [0]);
    expect(v.y[1]).toBeGreaterThan(5);
  });

  it('a star epoch without values (epoch 2 in D1) still gives a range from the visible ones', () => {
    const sc = yScale('asinh', asinhScale(star.channels));
    const v = spectrumView(star.channels, 'all', sc, undefined, [0, 2]);
    expect(v.y[1]).toBeGreaterThan(v.y[0]);
  });
});
