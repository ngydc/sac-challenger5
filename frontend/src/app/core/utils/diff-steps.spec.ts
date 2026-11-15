import { Bundle } from '../models/epochs.models';
import { diffPair, missingText, stepLabel, stepsOf } from './diff-steps';

const ref = (epoch: number) => ({ epoch, time: `202${epoch}-01-01T00:00:00Z` });
const bundle = (over: Partial<Bundle> = {}): Bundle =>
  ({
    id: 'D1',
    kind: 'detector',
    diff: { first: ref(0), last: ref(3), clip_sigma: 8, definition: '', colours: '' },
    // epoch 1 is not usable for this detector: its steps are 0→2 and 2→3
    diff_steps: [
      { step: 0, first: ref(0), last: ref(2), available: true },
      { step: 1, first: ref(2), last: ref(3), available: false },
    ],
    ...over,
  }) as Bundle;

describe('diff steps', () => {
  it('picks Total for null and the bundle’s own pair for a step, step 0 included', () => {
    expect(diffPair(bundle(), null)?.last.epoch).toBe(3);
    expect(diffPair(bundle(), 0)).toMatchObject({ first: { epoch: 0 }, last: { epoch: 2 } });
  });

  it('has no picture for an unavailable or missing step, and says why', () => {
    expect(diffPair(bundle(), 1)).toBeNull();
    expect(diffPair(bundle(), 2)).toBeNull();
    expect(missingText(bundle(), 2)).toBe('This detector has only 2 steps.');
    expect(missingText(bundle({ kind: 'all' }), 2)).toBe('The combined picture has only 2 steps.');
    expect(missingText(bundle(), 1)).toContain('could not be computed');
  });

  it('works with results from before the steps existed', () => {
    const old = bundle({ diff_steps: undefined });
    expect(stepsOf(old)).toBe(0);
    expect(diffPair(old, null)).not.toBeNull();
    expect(diffPair(old, 0)).toBeNull();
  });

  it('labels the buttons', () => {
    expect([null, 0, 1].map(stepLabel)).toEqual(['Total', '1→2', '2→3']);
  });
});
