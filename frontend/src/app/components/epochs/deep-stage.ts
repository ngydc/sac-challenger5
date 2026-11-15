import { Component, inject } from '@angular/core';
import { EpochsStore } from '../../core/services/epochs-store.service';
import { ViewerState } from '../../core/services/viewer-state.service';
import { BundleTile } from './bundle-tile';

/** The stage while Deep Analysis is open: the difference pictures instead of the slider picture. */
@Component({
  selector: 'app-deep-stage',
  imports: [BundleTile],
  template: `
    <div class="deep-stage">
      @if (d.showing() && d.position(); as pos) {
        <p class="hint">
          <b>Difference = latest pass minus first.</b> Blue: brighter now. Red: brighter before.
          White: unchanged. A red and a blue spot side by side: the object moved from red to blue. A
          search aid, not a measurement. Click a picture to enlarge it.
        </p>
        <div class="tiles" [class.single]="d.group() === 'all'">
          @for (b of d.bundles(); track b.id) {
            <app-bundle-tile
              [bundle]="b"
              [position]="pos"
              [version]="d.version()"
              [width]="d.result()?.grid?.width ?? 47"
              [height]="d.result()?.grid?.height ?? 47"
              (open)="d.openDetail(b.id)"
            />
          }
          @if (d.running()) {
            <div class="tile pending">
              <span class="spinner"></span>
              <p class="muted small">
                @if (d.group() === 'all') {
                  The combined picture comes after the last detector.
                } @else {
                  More detectors are being computed…
                }
              </p>
            </div>
          }
        </div>
      } @else {
        <div class="deep-empty">
          <h2>Deep Analysis</h2>
          @if (!viewer.resolved()) {
            <p>
              Search for an object first. Deep Analysis then shows what changed at that spot between
              SPHEREx's passes.
            </p>
          } @else {
            <p>
              Shows what changed at
              <b>{{ viewer.resolved()?.target?.name ?? 'this position' }}</b> between SPHEREx's
              passes: stars that moved, brightened or faded.
            </p>
            @if (d.checking() && !d.status()) {
              <p class="muted">
                <span class="spinner inline"></span> Checking whether it has been analysed…
              </p>
            } @else if (d.status()?.status === 'not_computed' || d.status()?.status === 'error') {
              <p class="muted">
                This spot has not been analysed yet. Start the deep analysis in the panel on the
                right: it downloads data from NASA's archive and takes tens of minutes.
              </p>
            }
          }
        </div>
      }
    </div>
  `,
})
export class DeepStage {
  protected readonly d = inject(EpochsStore);
  protected readonly viewer = inject(ViewerState);
}
