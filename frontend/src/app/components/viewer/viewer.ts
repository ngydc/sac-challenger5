import { Component, computed, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ViewerState } from '../../core/services/viewer-state.service';
import { ColourStore } from '../../core/services/colour-store.service';
import { EXAMPLES } from '../../core/examples';
import { Logo } from '../logo/logo';

/** F1: the start page, then the frame, as large as the screen allows, with the predicted-position ring and status overlays. */
@Component({
  selector: 'app-viewer',
  imports: [DatePipe, Logo],
  templateUrl: './viewer.html',
  styleUrl: './viewer.scss',
})
export class Viewer {
  protected readonly s = inject(ViewerState);
  protected readonly c = inject(ColourStore);
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

  /** Colour mode: the ring at the season's predicted position (same grid and convention as the frames: y from the bottom). */
  protected readonly colourRing = computed(() => {
    const xy = this.c.epoch()?.target_xy;
    const g = this.c.grid();
    if (!this.s.showRing() || !xy || !g || xy[0] == null || xy[1] == null) return null;
    const left = ((xy[0] + 0.5) / g.width) * 100;
    const top = ((g.height - 1 - xy[1] + 0.5) / g.height) * 100;
    if (left < 0 || left > 100 || top < 0 || top > 100) return null;
    return { left, top, d: Math.max(4, (5 / g.width) * 100) };
  });

  protected readonly colourAlt = computed(() => {
    const e = this.c.epoch();
    const when = e?.start && e?.end ? `${e.start.slice(0, 10)} to ${e.end.slice(0, 10)}` : 'this season';
    return `SPHEREx colour picture, ${when}: every infrared wavelength combined, short wavelengths blue, long ones red, grey = masked pixels`;
  });

  protected readonly progress = computed(() => {
    const p = this.s.coverage()?.progress;
    return p && p.total ? Math.round((p.located / p.total) * 100) : null;
  });
}
