import { Bundle, DiffPair } from '../models/epochs.models';

/** The selected difference: null = "Total" (last minus first usable epoch), a number = that step. */
export type StepChoice = number | null;

/** Number of steps of a bundle (0 for results computed before steps existed). */
export function stepsOf(b: Bundle): number {
  return b.diff_steps?.length ?? 0;
}

/** The epochs the bundle's picture compares for this choice, or null if it has no picture for it. */
export function diffPair(b: Bundle, step: StepChoice): DiffPair | null {
  if (step == null) return b.diff;
  const s = b.diff_steps?.find((x) => x.step === step);
  return s && s.available !== false ? s : null;
}

/** Button label of a step: step 0 compares the 1st and 2nd usable pass. */
export function stepLabel(step: StepChoice): string {
  return step == null ? 'Total' : `${step + 1}→${step + 2}`;
}

/** Why a bundle shows no picture for this choice, as a short sentence for the tile. */
export function missingText(b: Bundle, step: StepChoice): string {
  const what = b.kind === 'all' ? 'The combined picture' : 'This detector';
  const n = stepsOf(b);
  if (step == null || n === 0) {
    return `No difference picture: ${what.charAt(0).toLowerCase() + what.slice(1)} has fewer than two usable epochs here.`;
  }
  if (step >= n) return `${what} has only ${n} ${n === 1 ? 'step' : 'steps'}.`;
  return `${what} has no picture for this step: its difference could not be computed.`;
}
