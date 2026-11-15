import { Component, computed, inject, input, output } from '@angular/core';
import { Bundle, Position } from '../../core/models/epochs.models';
import { EpochsApi } from '../../core/services/epochs-api.service';
import { bundleTitle, fmtUm } from '../../core/utils/format';
import { SkyImage } from './sky-image';
import { EpochLegend } from './epoch-legend';

/** One bundle's difference picture as a tile: title with wavelength range, picture (click to enlarge), legend. */
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
          <p>No difference picture: this detector has fewer than two usable epochs here.</p>
        </div>
      }
      <app-epoch-legend [bundle]="bundle()" />
    </article>
  `,
})
export class BundleTile {
  private readonly api = inject(EpochsApi);
  readonly bundle = input.required<Bundle>();
  readonly position = input.required<Position>();
  readonly version = input('');
  readonly width = input(47);
  readonly height = input(47);
  readonly open = output<void>();

  protected readonly title = computed(() => bundleTitle(this.bundle()));
  protected readonly wl = computed(() => fmtUm(this.bundle().wavelength_um));
  protected readonly src = computed(() => {
    const b = this.bundle();
    return b.diff ? this.api.diffUrl(this.position(), b.id, this.version()) : null;
  });
  protected readonly alt = computed(() => `Difference picture of ${this.title()}, ${this.wl()}`);
}
