import { Component, ElementRef, computed, effect, inject, viewChild } from '@angular/core';
import { EpochsApi } from '../../core/services/epochs-api.service';
import { EpochsStore } from '../../core/services/epochs-store.service';
import { bundleTitle, fmtDate, fmtRange, fmtUm } from '../../core/utils/format';
import { diffPair, missingText, stepLabel } from '../../core/utils/diff-steps';
import { SkyImage } from './sky-image';
import { EpochLegend } from './epoch-legend';
import { SpectrumPanel } from './spectrum-panel';

/** The enlarged difference picture of one bundle with its metadata; a click on a pixel opens its spectrum. */
@Component({
  selector: 'app-bundle-detail',
  imports: [SkyImage, EpochLegend, SpectrumPanel],
  template: `
    <dialog
      #dlg
      class="detail"
      (close)="s.closeDetail()"
      (click)="backdrop($event)"
      aria-labelledby="detail-title"
    >
      <div class="detail-inner">
        @if (s.detailBundle(); as b) {
          <header class="detail-head">
            <div>
              <h2 id="detail-title">
                {{ title() }} <span class="muted">· {{ wl() }}</span>
                @if (s.diffStep() !== null) {
                  <span class="muted">· step {{ label() }}</span>
                }
              </h2>
            </div>
            <button type="button" class="btn icon" aria-label="Close" (click)="dlg.close()">
              ✕
            </button>
          </header>

          <div class="detail-body">
            <div class="detail-pic">
              @if (src(); as src) {
                <app-sky-image
                  [src]="src"
                  [width]="grid().width"
                  [height]="grid().height"
                  [pickable]="true"
                  [marker]="s.pick()"
                  (picked)="s.pick.set($event)"
                  [alt]="title() + ' enlarged'"
                />
                <p class="muted small">
                  North is up, east is left. Click any pixel to see its spectrum.
                </p>
              } @else {
                <div class="tile-none hatch big">
                  @if (s.diffStep() === null) {
                    <p>A difference needs at least two usable epochs. {{ b.note }}</p>
                  } @else {
                    <p>{{ missing() }}</p>
                  }
                </div>
              }
              <app-epoch-legend [bundle]="b" [step]="s.diffStep()" />
              <p class="hint">
                A search aid, not a measurement: it shows where something may have changed.
                @if (s.diffStep() === null) {
                  Blue = brighter in the latest epoch, red = brighter in the first,
                } @else {
                  This step compares one pass with the one before it. Blue = brighter in the later
                  pass, red = brighter in the earlier one,
                }
                white = unchanged. A moving object leaves red where it was and blue where it went.
              </p>
            </div>

            <dl class="meta">
              <dt>Time span</dt>
              <dd>{{ span() }}</dd>
              <dt>Images</dt>
              <dd>
                {{ nImages() }} images in {{ used().length }}
                {{ used().length === 1 ? 'epoch' : 'epochs' }}
              </dd>
              <dt>Wavelength</dt>
              <dd>{{ wl() }} ({{ b.detectors.join(', ') }})</dd>
              <dt>Coverage</dt>
              <dd>
                {{ (b.covered_fraction * 100).toFixed(0) }} % of the field has data in every
                compared epoch
              </dd>
              <dt>Epochs</dt>
              <dd>
                <ul class="plain">
                  @for (e of used(); track e.index) {
                    <li>
                      <b>{{ fmtRange(e.start, e.end) }}</b>: {{ e.n_images }} images
                      @if (e.span_days !== null) {
                        over {{ e.span_days.toFixed(0) }} days
                      }
                      @if (e.saturated_images) {
                        · centre too bright (saturated) in {{ e.saturated_images }}
                      }
                    </li>
                  }
                </ul>
              </dd>
              @if (b.gaps.length) {
                <dt>Notes</dt>
                <dd>
                  <ul class="plain">
                    @for (g of b.gaps; track $index) {
                      <li>{{ g }}</li>
                    }
                  </ul>
                </dd>
              }
              <dt>Files</dt>
              <dd>
                @for (e of used(); track e.index) {
                  <details class="files">
                    <summary>{{ fmtDate(e.time) }}: {{ e.files.length }} files</summary>
                    <ul>
                      @for (f of e.files; track f) {
                        <li>{{ f }}</li>
                      }
                    </ul>
                  </details>
                }
              </dd>
            </dl>
          </div>

          @if (s.pick(); as p) {
            @if (s.position(); as pos) {
              <app-spectrum-panel
                [position]="pos"
                [x]="p.x"
                [y]="p.y"
                [height]="grid().height"
                (closed)="s.pick.set(null)"
              />
            }
          }
        }
      </div>
    </dialog>
  `,
})
export class BundleDetail {
  protected readonly s = inject(EpochsStore);
  private readonly api = inject(EpochsApi);
  private readonly dlg = viewChild.required<ElementRef<HTMLDialogElement>>('dlg');

  protected readonly fmtDate = fmtDate;
  protected readonly fmtRange = fmtRange;
  protected readonly title = computed(() => {
    const b = this.s.detailBundle();
    return b ? bundleTitle(b) : '';
  });
  protected readonly wl = computed(() => fmtUm(this.s.detailBundle()?.wavelength_um));
  protected readonly grid = computed(() => this.s.result()?.grid ?? { width: 47, height: 47 });
  protected readonly used = computed(() =>
    (this.s.detailBundle()?.epochs ?? []).filter((e) => e.usable),
  );
  protected readonly nImages = computed(() => this.used().reduce((n, e) => n + e.n_images, 0));
  protected readonly span = computed(() => {
    const u = this.used();
    return u.length ? fmtRange(u[0].start, u[u.length - 1].end) : '–';
  });
  protected readonly src = computed(() => {
    const b = this.s.detailBundle();
    const p = this.s.position();
    if (!b || !p) return null;
    const step = this.s.diffStep();
    return diffPair(b, step) ? this.api.diffUrl(p, b.id, this.s.version(), step) : null;
  });
  protected readonly label = computed(() => stepLabel(this.s.diffStep()));
  protected readonly missing = computed(() => {
    const b = this.s.detailBundle();
    return b ? missingText(b, this.s.diffStep()) : '';
  });

  constructor() {
    effect(() => {
      const el = this.dlg().nativeElement;
      if (this.s.detail() && !el.open) el.showModal();
      if (!this.s.detail() && el.open) el.close();
    });
  }

  /** A click on the dark backdrop (outside the dialog box) closes it. */
  protected backdrop(e: MouseEvent): void {
    if (e.target === this.dlg().nativeElement) this.dlg().nativeElement.close();
  }
}
