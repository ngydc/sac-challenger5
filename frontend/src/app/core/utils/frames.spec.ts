import { Frame } from '../models/api.models';
import { bandsOf, framesOfVisit, pickFrame, ringPosition } from './frames';

const f = (id: string, visit: number, detector: string, w: number, cache: Frame['cache'] = 'ready'): Frame => ({
  id,
  visit,
  detector,
  wavelength_um: w,
  bandwidth_um: 0.02,
  time: '2025-08-27T05:07:00Z',
  release: 'spherex_dr1',
  cache,
});

const frames = [
  f('a', 0, 'D1', 0.75),
  f('b', 0, 'D1', 0.9),
  f('c', 0, 'D4', 3.0, 'outside'),
  f('d', 1, 'D4', 2.9),
  f('e', 1, 'D1', 0.8),
];

describe('pickFrame', () => {
  it('picks the nearest frame of the visit and says whether it is exact', () => {
    expect(pickFrame(frames, 0, 0.91)).toEqual({ frame: frames[1], exact: true });
    expect(pickFrame(frames, 1, 1.5)?.frame.id).toBe('e');
    expect(pickFrame(frames, 1, 1.5)?.exact).toBe(false);
  });

  it('skips frames whose image does not cover the view', () => {
    expect(pickFrame(frames, 0, 3.0)?.frame.id).toBe('b');
  });

  it('returns null for a visit without frames', () => {
    expect(pickFrame(frames, 5, 1)).toBeNull();
  });
});

describe('bandsOf / framesOfVisit', () => {
  it('derives each detector range from the data, sorted by wavelength', () => {
    expect(bandsOf(frames).map((b) => [b.detector, b.min, b.max, b.count])).toEqual([
      ['D1', 0.75, 0.9, 3],
      ['D4', 2.9, 3.0, 2],
    ]);
  });

  it('lists a visit by wavelength without outside frames', () => {
    expect(framesOfVisit(frames, 1).map((x) => x.id)).toEqual(['e', 'd']);
    expect(framesOfVisit(frames, 0).map((x) => x.id)).toEqual(['a', 'b']);
  });
});

describe('ringPosition', () => {
  it('centres the ring on the pixel centre and flips y (the backend counts from the bottom)', () => {
    const r = ringPosition(9.5, 0, 20, 10)!;
    expect(r.left).toBeCloseTo(50.0, 6); // (9.5 + 0.5) / 20
    expect(r.top).toBeCloseTo(95.0, 6); // (10 - 1 - 0 + 0.5) / 10 = bottom row
    expect(r.d).toBe(25); // 5 / 20 of the width
  });

  it('keeps a minimum diameter of 4 % on wide pictures', () => {
    expect(ringPosition(50, 50, 200, 200)?.d).toBe(4);
  });

  it('returns null outside the picture', () => {
    expect(ringPosition(-1, 5, 20, 20)).toBeNull();
    expect(ringPosition(5, 25, 20, 20)).toBeNull();
    expect(ringPosition(25, 5, 20, 20)).toBeNull();
  });
});
