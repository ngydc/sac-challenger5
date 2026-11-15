import { Component, computed, inject } from '@angular/core';
import { EpochsStore, Group } from '../../core/services/epochs-store.service';
import { ViewerState } from '../../core/services/viewer-state.service';
import { EXAMPLES } from '../../core/examples';
import { fmtDate, fmtDuration, fmtRange } from '../../core/utils/format';
import { SiteFooter } from './site-footer';

/**
 * Contents of the "Deep Analysis" drawer: status of the searched object, the button that shows (or
 * creates) the difference pictures, the grouping switch, the explanation and the acknowledgement.
 * The pictures themselves are drawn on the stage (DeepStage).
 */
@Component({
  selector: 'app-deep-panel',
  imports: [SiteFooter],
  template: `
    <div class="deep">
      @if (!viewer.resolved()) {
        <p class="muted">
          Search for an object first (box at the top). Deep Analysis then compares SPHEREx's passes
          over that spot.
        </p>
      } @else {
        @if (d.error(); as e) {
          <p class="warn" role="alert">{{ e }}</p>
        }

        <section class="deep-status" aria-live="polite">
          @if (d.checking() && !d.status()) {
            <p><span class="spinner inline"></span> Checking whether difference pictures exist…</p>
          } @else if (d.status(); as st) {
            @switch (st.status) {
              @case ('cached') {
                <h3><span class="dot ok"></span> Ready</h3>
                <p class="muted small">
                  {{ st.result?.n_images }} images in {{ st.result?.epochs?.length }} epochs are
                  already processed.
                </p>
              }
              @case ('running') {
                <h3><span class="dot busy"></span> Being created</h3>
                @if (progress(); as p) {
                  <div
                    class="bar"
                    role="progressbar"
                    [attr.aria-valuenow]="p.pct"
                    aria-valuemin="0"
                    aria-valuemax="100"
                  >
                    <span [style.width.%]="p.pct"></span>
                  </div>
                  <p class="muted small">
                    {{ p.stage }} · {{ p.done }} / {{ p.total }} images
                    @if (p.eta) {
                      · {{ p.eta }} left
                    }
                    @if (p.bundles_ready.length) {
                      · ready: {{ p.bundles_ready.join(', ') }}
                    }
                  </p>
                }
              }
              @case ('error') {
                <h3><span class="dot bad"></span> The last attempt failed</h3>
                <p class="muted small">{{ st.message }}</p>
              }
              @default {
                <h3><span class="dot"></span> Not analysed yet</h3>
                <p class="muted small">Nobody has run a deep analysis of this spot yet.</p>
              }
            }
            <!-- Only when something has to be computed: cached results and running computations show at once. -->
            @if (st.status === 'not_computed' || st.status === 'error') {
              <button
                type="button"
                class="btn primary big wide"
                [disabled]="d.starting()"
                (click)="d.showImages()"
              >
                @if (d.starting()) {
                  <span class="spinner inline"></span>
                }
                {{
                  st.status === 'error'
                    ? 'Try again (downloads data)'
                    : 'Start deep analysis (downloads data)'
                }}
              </button>
              <p class="takes-time small">
                <b>This takes a while:</b> the server downloads a few hundred images of this spot
                from NASA's archive, which takes tens of minutes. You can keep using the page; the
                first difference picture appears as soon as one detector is done.
              </p>
            }
          }
        </section>

        @if (d.showing()) {
          <div class="seg wide" role="group" aria-label="Detectors">
            @for (g of groups; track g.id) {
              <button
                type="button"
                class="btn"
                [class.active]="d.group() === g.id"
                [attr.aria-pressed]="d.group() === g.id"
                (click)="d.group.set(g.id)"
              >
                {{ g.label }}
              </button>
            }
          </div>

          @if (summary(); as m) {
            <dl class="meta compact">
              <dt>Time span</dt>
              <dd>{{ m.span }}</dd>
              <dt>Images</dt>
              <dd>{{ m.images }} in {{ m.epochs }} epochs</dd>
              <dt>Releases</dt>
              <dd>{{ m.collections }}</dd>
              <dt>Searched</dt>
              <dd>{{ m.searched }}</dd>
            </dl>
          }
        }

        @if (d.explainerOpen()) {
          <section class="explainer" id="deep-explainer" aria-labelledby="deep-explainer-title">
            <header>
              <h3 id="deep-explainer-title">How to read the difference pictures</h3>
              <button type="button" class="btn" (click)="d.explainerOpen.set(false)">Hide</button>
            </header>
            <p>
              Each picture shows the same small patch of sky. SPHEREx, a NASA space telescope,
              passes over every spot about every six months. The picture is the <b>latest</b> pass
              minus the <b>first</b> one: only what changed in between is coloured.
            </p>
            <ul class="read">
              <li>
                <span class="sw" style="background:#f7f7f7"></span
                ><span><b>White:</b> unchanged.</span>
              </li>
              <li>
                <span class="sw" style="background:#2166ac"></span
                ><span><b>Blue:</b> brighter now than in the first pass.</span>
              </li>
              <li>
                <span class="sw" style="background:#b2182b"></span
                ><span><b>Red:</b> brighter before, fainter now.</span>
              </li>
              <li>
                <span class="pair" aria-hidden="true"></span
                ><span
                  ><b>A red and a blue spot side by side:</b> the object <b>moved</b>, from the red
                  spot (where it was) to the blue spot (where it is now).</span
                >
              </li>
              <li>
                <span class="sw hatch"></span
                ><span
                  ><b>Hatched:</b> no data. A blank centre means the star was too bright for the
                  sensor (<b>saturated</b>).</span
                >
              </li>
            </ul>
            <p>
              <b>Why six pictures:</b> SPHEREx has six <b>detectors</b> (light sensors), each seeing
              a different slice of <b>infrared light</b>, light our eyes cannot see. The range is
              written on each picture in µm (micrometres). Some objects, such as cold brown dwarfs
              (failed stars), change or glow mainly in one slice.
            </p>
            <p>
              <b>Be careful:</b> this is a search aid, not a measurement. Small specks are mostly
              noise (random flicker of the sensor). If every star shows the same red–blue pair, the
              pictures are slightly misaligned; that is not motion.
            </p>
            <h4>The examples</h4>
            <ul class="examples">
              @for (e of examples; track e.name) {
                <li [class.current]="d.activeExample()?.name === e.name">
                  <b>{{ e.name }}</b> ({{ e.what }}): {{ e.seen }}
                </li>
              }
            </ul>
          </section>
        }
      }
      <app-site-footer />
    </div>
  `,
})
export class DeepPanel {
  protected readonly d = inject(EpochsStore);
  protected readonly viewer = inject(ViewerState);
  protected readonly examples = EXAMPLES;
  protected readonly groups: { id: Group; label: string }[] = [
    { id: 'detector', label: 'Per detector' },
    { id: 'all', label: 'All combined' },
  ];

  protected readonly progress = computed(() => {
    const p = this.d.status()?.progress;
    if (!p) return null;
    const left = this.d.remainingS();
    return {
      ...p,
      pct: p.total > 0 ? Math.round((100 * p.done) / p.total) : 0,
      eta: left === null ? null : fmtDuration(left),
    };
  });

  protected readonly summary = computed(() => {
    const r = this.d.result();
    if (!r || !r.epochs.length) return null;
    return {
      span: fmtRange(r.epochs[0].start, r.epochs[r.epochs.length - 1].end),
      epochs: r.epochs.length,
      images: r.n_images,
      collections: r.collections.join(', '),
      searched: fmtDate(r.searched_at),
    };
  });
}
