import { Component, computed, inject } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ColourStore } from '../../core/services/colour-store.service';

/**
 * The colour picture's key: one segment per spectral channel, shortest wavelength (blue) on the left, longest (red)
 * on the right, in the colour that channel adds to the picture. Channels the current season does not have are
 * hatched, so an unusual tint can be traced to missing wavelengths. Plus the swatch of masked pixels.
 */
@Component({
  selector: 'app-colour-legend',
  imports: [DecimalPipe],
  template: `
    @if (c.colour(); as col) {
      <div class="legend" role="img" [attr.aria-label]="label()">
        <div class="bar">
          @for (ch of segments(); track $index) {
            <span [class.missing]="!ch.have" [style.background]="ch.have ? ch.colour : null" [title]="ch.title"></span>
          }
        </div>
        <div class="ticks num">
          <span>{{ range()?.[0] | number: '1.2-2' }}</span>
          <span class="mid">wavelength</span>
          <span>{{ range()?.[1] | number: '1.1-1' }} µm</span>
        </div>
      </div>
      <span class="mask" [title]="'Masked: saturated or flagged in some wavelengths'">
        <i [style.background]="col.mask_colour"></i>masked
      </span>
    }
  `,
  styles: `
    :host {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      min-width: 0;
    }
    .legend {
      display: flex;
      flex-direction: column;
      gap: 3px;
      width: clamp(120px, 22vw, 220px);
    }
    .bar {
      display: flex;
      height: 9px;
      border-radius: 5px;
      overflow: hidden;
      box-shadow: 0 0 0 1px var(--border-strong);

      span {
        flex: 1;
        min-width: 0;
      }
      .missing {
        background: repeating-linear-gradient(135deg, var(--surface-3) 0 2px, var(--surface) 2px 4px);
      }
    }
    .ticks {
      display: flex;
      justify-content: space-between;
      font-size: 0.68rem;
      color: var(--muted);
      line-height: 1;

      .mid {
        letter-spacing: 0.06em;
        text-transform: uppercase;
        font-size: 0.6rem;
      }
    }
    .mask {
      display: flex;
      align-items: center;
      gap: 0.3rem;
      font-size: 0.7rem;
      color: var(--muted);
      white-space: nowrap;

      i {
        width: 10px;
        height: 10px;
        border-radius: 2px;
        box-shadow: 0 0 0 1px var(--border-strong);
      }
    }
    @media (max-width: 640px) {
      .mask {
        display: none;
      }
    }
  `,
})
export class ColourLegend {
  protected readonly c = inject(ColourStore);

  protected readonly segments = computed(() => {
    const col = this.c.colour();
    const have = this.c.epoch()?.channels_covered;
    return (col?.palette ?? []).map((ch, i) => ({
      colour: ch.colour,
      have: have ? have[i] : true,
      title: `${ch.detector} channel ${ch.channel}: ${ch.wavelength_um?.toFixed(2)} µm${have && !have[i] ? ' (missing this season)' : ''}`,
    }));
  });

  protected readonly range = computed<[number, number] | null>(() => {
    const p = this.c.colour()?.palette ?? [];
    const lo = p[0]?.wl_min_um ?? p[0]?.wavelength_um;
    const hi = p[p.length - 1]?.wl_max_um ?? p[p.length - 1]?.wavelength_um;
    return lo != null && hi != null ? [lo, hi] : null;
  });

  protected readonly label = computed(() => {
    const r = this.range();
    const e = this.c.epoch();
    const n = this.c.colour()?.palette.length ?? 0;
    const span = r ? `from ${r[0].toFixed(2)} µm (blue) to ${r[1].toFixed(1)} µm (red)` : 'short (blue) to long (red)';
    return `Colour key: wavelength ${span}.` + (e ? ` This season has ${e.n_channels} of ${n} wavelength channels.` : '');
  });
}
