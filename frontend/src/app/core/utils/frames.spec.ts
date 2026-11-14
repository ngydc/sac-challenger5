import { Frame } from '../models/api.models';
import { bandsOf, framesOfVisit, pickFrame } from './frames';

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
