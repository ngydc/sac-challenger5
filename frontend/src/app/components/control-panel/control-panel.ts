import { Component, computed, inject } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { Stretch, ViewerState } from '../../core/services/viewer-state.service';
import { framesOfVisit } from '../../core/utils/frames';
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

  /** Position of the shown image among the season's images, sorted by wavelength (for the step buttons). */
  protected readonly frameIndex = computed(() => {
    const list = framesOfVisit(this.s.frames(), this.s.visit());
    const id = this.s.pick()?.frame.id;
    return { i: list.findIndex((f) => f.id === id), n: list.length };
  });

  /** The arrow buttons under the sliders: one step, and stop playback so the step is not overwritten. */
  protected stepVisit(d: number): void {
    this.s.stop();
    this.s.stepVisit(d);
  }

  protected stepFrame(d: number): void {
    this.s.stop();
    this.s.stepFrame(d);
  }
}
