import { Component, computed, inject } from '@angular/core';
import { ViewerState } from '../../core/services/viewer-state.service';

/**
 * The "About SPHEREx" tab of the menu: what the mission is, what this tool does with its data,
 * where the data comes from and how to cite it. Facts and links are from the official pages
 * saved in docs/spherex/ (user-guide-overview, irsa-mission-page, irsa-dr1-overview,
 * irsa-quick-release-overview).
 */
@Component({
  selector: 'app-about-panel',
  templateUrl: './about-panel.html',
  styleUrl: './about-panel.scss',
})
export class AboutPanel {
  private readonly s = inject(ViewerState);

  /** The data collections the images of the current target come from (read from the data). */
  protected readonly collections = computed(() => [...new Set(this.s.frames().map((f) => f.release))].sort());
}
