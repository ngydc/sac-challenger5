import { Component, computed, input } from '@angular/core';
import { Bundle } from '../../core/models/epochs.models';
import { fmtDate } from '../../core/utils/format';
import { StepChoice, diffPair, missingText } from '../../core/utils/diff-steps';

/**
 * Legend of one bundle's difference picture: colour bar and the two compared epochs. The epochs are chosen
 * per bundle by the backend (its usable epochs), so every tile has its own dates, also for the same step.
 * `step`: null = Total (`bundle.diff`), k = step k (`bundle.diff_steps`).
 */
@Component({
  selector: 'app-epoch-legend',
  template: `
    @if (pair(); as p) {
      <div
        class="diffbar"
        role="img"
        [attr.aria-label]="
          'Colour scale: red = brighter in the earlier epoch, white = unchanged, blue = brighter in the later one; ends at ' +
          clip() +
          ' times the noise'
        "
      >
        <span class="bar"></span>
        <span class="ends"
          ><span>brighter {{ total() ? 'before' : 'earlier' }}</span
          ><span>brighter {{ total() ? 'now' : 'later' }}</span></span
        >
      </div>
      <p class="legend-note">{{ date(p.first.time) }} → {{ date(p.last.time) }}</p>
    } @else if (total()) {
      <p class="legend-note">A difference needs at least two epochs. {{ bundle().note }}</p>
    } @else {
      <p class="legend-note">{{ missing() }}</p>
    }
  `,
})
export class EpochLegend {
  readonly bundle = input.required<Bundle>();
  readonly step = input<StepChoice>(null);
  protected readonly date = fmtDate;
  protected readonly total = computed(() => this.step() == null);
  protected readonly pair = computed(() => diffPair(this.bundle(), this.step()));
  protected readonly missing = computed(() => missingText(this.bundle(), this.step()));
  /** The scale is the same for Total and every step. */
  protected readonly clip = computed(() => this.bundle().diff?.clip_sigma ?? '');
}
