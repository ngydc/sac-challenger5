import { Component, computed, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ViewerState } from '../../core/services/viewer-state.service';

/** Example searches shown on the start screen (the challenge's test targets). */
const EXAMPLES = ["Barnard's Star", 'Epsilon Indi B', 'WISE 0855', 'RW Aurigae', 'R Draconis'];

/** F1: the frame, as large as the screen allows, with the predicted-position ring and status overlays. */
@Component({
  selector: 'app-viewer',
  imports: [DatePipe],
  templateUrl: './viewer.html',
  styleUrl: './viewer.scss',
})
export class Viewer {
  protected readonly s = inject(ViewerState);
  protected readonly examples = EXAMPLES;

  protected readonly aspect = computed(() => {
    const g = this.s.coverage()?.grid;
    return g ? `${g.width} / ${g.height}` : '1 / 1';
  });

  /** Ring position in % of the picture (header Y counts from the bottom). */
  protected readonly ring = computed(() => {
    const p = this.s.picture();
    if (!p || !this.s.showRing() || !p.size || isNaN(p.target.x)) return null;
    const left = ((p.target.x + 0.5) / p.size) * 100;
    const top = ((p.size - 1 - p.target.y + 0.5) / p.size) * 100;
    if (left < 0 || left > 100 || top < 0 || top > 100) return null;
    return { left, top, d: Math.max(4, (5 / p.size) * 100) };
  });

  protected readonly progress = computed(() => {
    const p = this.s.coverage()?.progress;
    return p && p.total ? Math.round((p.located / p.total) * 100) : null;
  });
}
