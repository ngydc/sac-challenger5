import { TestBed } from '@angular/core/testing';
import { EpochsStore } from './epochs-store.service';
import { AnalysisStatus, Bundle } from '../models/epochs.models';

const ref = (epoch: number) => ({ epoch, time: '2026-01-01T00:00:00Z' });
const bundle = (id: string, kind: 'detector' | 'all', steps: number): Bundle =>
  ({
    id,
    kind,
    diff: steps ? { first: ref(0), last: ref(steps), clip_sigma: 8, definition: '', colours: '' } : null,
    diff_steps: Array.from({ length: steps }, (_, k) => ({ step: k, first: ref(k), last: ref(k + 1) })),
  }) as Bundle;
const status = (bundles: Bundle[]) =>
  ({ state: 'ready', refreshing: false, result: { images_key: 'k', bundles } }) as unknown as AnalysisStatus;

describe('EpochsStore step choice', () => {
  beforeEach(() => TestBed.resetTestingModule());

  it('counts the steps of the shown grouping and falls back to Total when a step is out of reach', () => {
    const s = TestBed.inject(EpochsStore);
    s.status.set(status([bundle('D1', 'detector', 3), bundle('D2', 'detector', 1), bundle('all', 'all', 2)]));
    expect(s.stepCount()).toBe(3);
    s.diffStep.set(2);
    TestBed.tick();
    expect(s.diffStep()).toBe(2); // D2 has no step 2: only its tile says so, the choice stays

    s.group.set('all'); // two steps there: step 2 cannot be reached
    TestBed.tick();
    expect(s.stepCount()).toBe(2);
    expect(s.diffStep()).toBeNull();

    s.diffStep.set(1);
    s.status.set(status([bundle('all', 'all', 1)])); // one step only: the buttons are hidden
    TestBed.tick();
    expect(s.showSteps()).toBe(false);
    expect(s.diffStep()).toBeNull();
  });
});
