import { Component, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FOV_MAX, FOV_MIN, Stretch, ViewerState } from '../../core/services/viewer-state.service';
import { framesOfVisit } from '../../core/utils/frames';
import { FramePlot } from '../frame-plot/frame-plot';
import { ColourStore } from '../../core/services/colour-store.service';

/** F2 + F3: the time and wavelength sliders, playback, frame details and display settings. */
@Component({
  selector: 'app-control-panel',
  imports: [DatePipe, DecimalPipe, FramePlot],
  templateUrl: './control-panel.html',
  styleUrl: './control-panel.scss',
})
export class ControlPanel {
  protected readonly s = inject(ViewerState);
  /** The colour pictures of this target: whether they exist or are being computed (for the compute button). */
  protected readonly c = inject(ColourStore);

  /** Colour mode: the picture shows every wavelength, so the wavelength controls are greyed out. */
  protected readonly colour = computed(() => this.s.mode() === 'colour');

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

  protected readonly fovMin = FOV_MIN;
  protected readonly fovMax = FOV_MAX;
  /** Why the typed field of view cannot be used (null while it is valid). Checked on every keystroke. */
  protected readonly fovError = signal<string | null>(null);

  private fovProblem(raw: string): string | null {
    const v = Number(raw);
    if (raw.trim() === '' || isNaN(v)) return 'Enter a number of degrees.';
    if (v < FOV_MIN || v > FOV_MAX) return `Field of view must be between ${FOV_MIN.toFixed(2)}° and ${FOV_MAX.toFixed(2)}°.`;
    return null;
  }

  protected checkFov(e: Event): void {
    this.fovError.set(this.fovProblem((e.target as HTMLInputElement).value));
  }

  /** Applies a valid field of view (Enter or leaving the field); an invalid one is kept in the field, with its message. */
  protected applyFov(e: Event): void {
    const raw = (e.target as HTMLInputElement).value;
    const problem = this.fovProblem(raw);
    this.fovError.set(problem);
    if (!problem) this.s.setFov(Number(raw));
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
