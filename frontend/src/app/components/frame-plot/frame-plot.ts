import { Component, computed, inject } from '@angular/core';
import { ViewerState } from '../../core/services/viewer-state.service';
import { Frame } from '../../core/models/api.models';

const W = 400;
const H = 200;
const M = { l: 36, r: 8, t: 10, b: 22 };

interface Dot {
  f: Frame;
  x: number;
  y: number;
  label: string;
}

/**
 * Every image of the current band: x = season (spread by date inside it), y = wavelength at the
 * target. Clicking a dot jumps to that image.
 */
@Component({
  selector: 'app-frame-plot',
  templateUrl: './frame-plot.html',
  styleUrl: './frame-plot.scss',
})
export class FramePlot {
  protected readonly s = inject(ViewerState);
  protected readonly W = W;
  protected readonly H = H;
  protected readonly M = M;

  private readonly colW = computed(() => (W - M.l - M.r) / Math.max(1, this.s.visits().length));

  private readonly yRange = computed<[number, number]>(() => {
    const b = this.s.band();
    if (!b) return this.s.range() ?? [0, 1];
    const pad = Math.max(0.01, (b.max - b.min) * 0.04);
    return [b.min - pad, b.max + pad];
  });

  private y(w: number): number {
    const [lo, hi] = this.yRange();
    return M.t + (1 - (w - lo) / (hi - lo || 1)) * (H - M.t - M.b);
  }

  protected readonly columns = computed(() =>
    this.s.visits().map((v, i) => ({ x: M.l + i * this.colW(), label: v.start.slice(0, 7), index: v.index })),
  );

  protected readonly ticks = computed(() => {
    const [lo, hi] = this.yRange();
    return [0, 0.25, 0.5, 0.75, 1].map((k) => {
      const w = lo + k * (hi - lo);
      return { y: this.y(w), label: w.toFixed(2) };
    });
  });

  protected readonly dots = computed<Dot[]>(() => {
    const det = this.s.band()?.detector;
    const visits = this.s.visits();
    const cw = this.colW();
    return this.s
      .frames()
      .filter((f) => f.detector === det && f.cache !== 'outside')
      .map((f) => {
        const v = visits[f.visit];
        const t0 = Date.parse(v.start);
        const span = Date.parse(v.end) + 86_400_000 - t0;
        const rel = span > 0 ? (Date.parse(f.time) - t0) / span : 0.5;
        return {
          f,
          x: M.l + f.visit * cw + 8 + Math.min(1, Math.max(0, rel)) * (cw - 16),
          y: this.y(f.wavelength_um),
          label: `${f.wavelength_um.toFixed(3)} µm · ${f.time.slice(0, 10)}`,
        };
      });
  });

  protected readonly current = computed(() => {
    const id = this.s.pick()?.frame.id;
    return this.dots().find((d) => d.f.id === id) ?? null;
  });

  protected readonly colX = computed(() => M.l + this.s.visit() * this.colW());
  protected readonly colWidth = this.colW;
}
