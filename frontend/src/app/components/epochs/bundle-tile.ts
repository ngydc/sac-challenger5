import { Component, computed, inject, input, output } from '@angular/core';
import { Bundle, Position } from '../../core/models/epochs.models';
import { EpochsApi } from '../../core/services/epochs-api.service';
import { bundleTitle, fmtUm } from '../../core/utils/format';
import { StepChoice, diffPair, missingText, stepLabel } from '../../core/utils/diff-steps';
import { SkyImage } from './sky-image';
import { EpochLegend } from './epoch-legend';

/**
 * One bundle's difference picture as a tile: title with wavelength range, picture (click to enlarge), legend.
 * `step` picks the picture: null = Total (last minus first epoch), k = step k of this bundle.
 */
@Component({
  selector: 'app-bundle-tile',
  imports: [SkyImage, EpochLegend],
  template: `
    <article class="tile">
      <header class="tile-head">
        <h3>{{ title() }}</h3>
        <span>{{ wl() }}</span>
      </header>
      @if (src(); as s) {
        <button
          type="button"
          class="tile-img"
          (click)="open.emit()"
          [attr.aria-label]="'Enlarge ' + title()"
        >
          <app-sky-image [src]="s" [width]="width()" [height]="height()" [alt]="alt()" />
          <span class="zoom" aria-hidden="true">⤢</span>
        </button>
      } @else {
        <div class="tile-none hatch">
          <p>{{ missing() }}</p>
        </div>
      }
      <app-epoch-legend [bundle]="bundle()" [step]="step()" />
    </article>
  `,
})
export class BundleTile {
  private readonly api = inject(EpochsApi);
  readonly bundle = input.required<Bundle>();
  readonly position = input.required<Position>();
  readonly version = input('');
  readonly step = input<StepChoice>(null);
  readonly width = input(47);
  readonly height = input(47);
  readonly open = output<void>();

  protected readonly title = computed(() => bundleTitle(this.bundle()));
  protected readonly wl = computed(() => fmtUm(this.bundle().wavelength_um));
  protected readonly src = computed(() => {
    const b = this.bundle();
    const step = this.step();
    return diffPair(b, step) ? this.api.diffUrl(this.position(), b.id, this.version(), step) : null;
  });
  protected readonly missing = computed(() => missingText(this.bundle(), this.step()));
  protected readonly alt = computed(
    () => `Difference picture (${stepLabel(this.step())}) of ${this.title()}, ${this.wl()}`,
  );
}
