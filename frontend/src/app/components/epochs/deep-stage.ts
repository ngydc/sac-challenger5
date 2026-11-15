import { Component, computed, inject } from '@angular/core';
import { EpochsStore } from '../../core/services/epochs-store.service';
import { ViewerState } from '../../core/services/viewer-state.service';
import { BundleTile } from './bundle-tile';
import { StepChoice, stepLabel } from '../../core/utils/diff-steps';

/** The stage while Deep Analysis is open: the difference pictures instead of the slider picture. */
@Component({
  selector: 'app-deep-stage',
  imports: [BundleTile],
  template: `
    <div class="deep-stage">
      @if (d.showing() && d.position(); as pos) {
        @if (d.showSteps()) {
          <div class="step-bar">
            <fieldset class="seg steps">
              <legend class="sr-only">Which difference to show</legend>
              @for (o of options(); track o.label) {
                <label class="btn" [class.active]="d.diffStep() === o.step">
                  <input
                    type="radio"
                    class="sr-only"
                    name="diff-step"
                    [checked]="d.diffStep() === o.step"
                    (change)="d.diffStep.set(o.step)"
                  />
                  <span class="num" aria-hidden="true">{{ o.label }}</span>
                  <span class="sr-only">{{ o.spoken }}</span>
                </label>
              }
            </fieldset>
            <p class="muted small">
              Total = latest minus first pass. 1→2 = each picture's first to second usable pass,
              and so on. Detectors can miss a pass, so check the dates under each picture.
            </p>
          </div>
        }
        <p class="hint">
          @if (d.diffStep() === null) {
            <b>Difference = latest pass minus first.</b> Blue: brighter now. Red: brighter before.
          } @else {
            <b>Difference = this pass minus the previous one.</b> Blue: brighter in the later pass.
            Red: brighter in the earlier one.
          }
          White: unchanged. A red and a blue spot side by side: the object moved from red to blue. A
          search aid, not a measurement. Click a picture to enlarge it.
        </p>
        <div class="tiles" [class.single]="d.group() === 'all'">
          @for (b of d.bundles(); track b.id) {
            <app-bundle-tile
              [bundle]="b"
              [position]="pos"
              [version]="d.version()"
              [step]="d.diffStep()"
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
            } @else if (d.status()?.state === 'idle' || d.status()?.state === 'error') {
              <p class="muted">
                This spot has not been analysed yet. Start the deep analysis in the panel on the
                right: it uses data from NASA's archive and takes about two minutes.
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
  /** Total, then one button per step (up to the most steps any shown bundle has). */
  protected readonly options = computed<{ step: StepChoice; label: string; spoken: string }[]>(() => [
    { step: null, label: stepLabel(null), spoken: 'Total, latest minus first pass' },
    ...Array.from({ length: this.d.stepCount() }, (_, k) => ({
      step: k,
      label: stepLabel(k),
      spoken: `Pass ${k + 1} to ${k + 2}`,
    })),
  ]);
}
