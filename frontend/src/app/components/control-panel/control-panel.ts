import { Component, computed, inject } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { Stretch, ViewerState } from '../../core/services/viewer-state.service';
import { Band } from '../../core/utils/frames';
import { FramePlot } from '../frame-plot/frame-plot';

/** F2 + F3: the time and wavelength sliders, playback, frame details and display settings. */
@Component({
  selector: 'app-control-panel',
  imports: [DatePipe, DecimalPipe, FramePlot],
  templateUrl: './control-panel.html',
  styleUrl: './control-panel.scss',
})
export class ControlPanel {
  protected readonly s = inject(ViewerState);

  protected readonly visitInfo = computed(() => this.s.visits()[this.s.visit()] ?? null);

  protected readonly timePct = computed(() => {
    const n = this.s.visits().length;
    return n > 1 ? (this.s.visit() / (n - 1)) * 100 : 0;
  });

  protected readonly wlPct = computed(() => {
    const r = this.s.range();
    return r ? ((this.s.wavelength() - r[0]) / (r[1] - r[0])) * 100 : 0;
  });

  protected readonly saturated = computed(() => this.s.picture()?.flags.includes('OVERFLOW') ?? false);

  protected num(e: Event): number {
    return Number((e.target as HTMLInputElement).value);
  }

  protected checked(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  protected setStretch(e: Event): void {
    this.s.stretch.set((e.target as HTMLSelectElement).value as Stretch);
  }

  protected selectBand(b: Band): void {
    // Keep the position inside the band if the user is already there, else go to its middle.
    const w = this.s.wavelength();
    if (w < b.min || w > b.max) this.s.setWavelength((b.min + b.max) / 2);
  }
}
