import { Component, computed, input } from '@angular/core';
import { Bundle } from '../../core/models/epochs.models';
import { fmtDate } from '../../core/utils/format';

/**
 * Legend of one bundle's difference picture: colour bar and the two compared epochs. The epochs are
 * chosen per detector by the backend, so every tile has its own dates (from `bundle.diff`).
 */
@Component({
  selector: 'app-epoch-legend',
  template: `
    @if (bundle().diff; as d) {
      <div
        class="diffbar"
        role="img"
        [attr.aria-label]="
          'Colour scale: red = brighter in the first epoch, white = unchanged, blue = brighter in the last; ends at ' +
          d.clip_sigma +
          ' times the noise'
        "
      >
        <span class="bar"></span>
        <span class="ends"><span>brighter before</span><span>brighter now</span></span>
      </div>
      <p class="legend-note">{{ firstDate() }} → {{ lastDate() }}</p>
    } @else {
      <p class="legend-note">A difference needs at least two epochs. {{ bundle().note }}</p>
    }
  `,
})
export class EpochLegend {
  readonly bundle = input.required<Bundle>();
  protected readonly firstDate = computed(() => fmtDate(this.bundle().diff?.first.time));
  protected readonly lastDate = computed(() => fmtDate(this.bundle().diff?.last.time));
}
