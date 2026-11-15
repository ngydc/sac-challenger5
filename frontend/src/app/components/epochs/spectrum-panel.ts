import {
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { Position, Spectrum } from '../../core/models/epochs.models';
import { EpochsApi } from '../../core/services/epochs-api.service';
import { friendly } from '../../core/services/epochs-store.service';
import { fmtDate } from '../../core/utils/format';
import {
  SpecPoint,
  asinhScale,
  bandTitle,
  detectorBands,
  labelRows,
  niceTicks,
  spectrumSeries,
  toAxis,
  xDomain,
  yDomain,
  yScale,
  yTicks,
} from '../../core/utils/spectrum';

/** Categorical series colours for the dark surface (validated set, dataviz reference palette, dark column). */
const SERIES = [
  '#3987e5',
  '#d95926',
  '#199e70',
  '#c98500',
  '#d55181',
  '#0ca30c',
  '#9085e9',
  '#e66767',
];
/** Chart height in px; the width follows the panel (so text keeps its size on narrow screens). */
const H = 260;
/** Margins: the top one holds the detector labels (two rows if they would overlap). */
const M = { l: 46, r: 10, t: 34, b: 34 };
/** Rough width of a detector label ("D1") at 10px. */
const labelWidth = (s: string) => s.length * 6.5;

let uid = 0;

/**
 * Spectrum of one clicked pixel (GET /api/analysis/spectrum), one line per epoch. Only draws: scale, detector
 * bands, line segments and ticks come from core/utils/spectrum.ts.
 */
@Component({
  selector: 'app-spectrum-panel',
  template: `
    <section class="spectrum" aria-live="polite">
      <header class="spec-head">
        <div>
          <h3>Spectrum at the clicked pixel</h3>
          <p class="muted small">
            Pixel x {{ x() }}, y {{ y() }} · how bright this spot is at each infrared wavelength,
            one line per epoch. Compare the lines: if they differ, the spot changed.
          </p>
        </div>
        <button type="button" class="btn icon" aria-label="Close spectrum" (click)="closed.emit()">
          ✕
        </button>
      </header>

      @if (loading()) {
        <p class="muted"><span class="spinner inline"></span> Loading the spectrum…</p>
      } @else if (err()) {
        <p class="warn">{{ err() }}</p>
      } @else if (data(); as d) {
        @if (drawn().length === 0) {
          <p class="muted">
            No measurements at this pixel (it has no data, for example a saturated centre).
          </p>
        } @else {
          <div class="spec-bar">
            <ul class="legend">
              @for (s of drawn(); track s.epoch) {
                <li><span class="sw line" [style.background]="s.colour"></span>{{ s.label }}</li>
              }
            </ul>
            <fieldset class="seg scale">
              <legend class="sr-only">Brightness axis</legend>
              <label class="btn" [class.active]="scale().kind === 'linear'">
                <input
                  type="radio"
                  class="sr-only"
                  [name]="radio"
                  [checked]="scale().kind === 'linear'"
                  (change)="want.set('linear')"
                />Linear
              </label>
              <label
                class="btn"
                [class.active]="scale().kind === 'asinh'"
                [class.off]="s() === null"
                [attr.title]="
                  s() === null
                    ? 'Not available here: this pixel has no noise estimate to scale by.'
                    : 'Spreads out small values and squeezes large ones, so faint and bright parts both show.'
                "
              >
                <input
                  type="radio"
                  class="sr-only"
                  [name]="radio"
                  [checked]="scale().kind === 'asinh'"
                  [disabled]="s() === null"
                  (change)="want.set('asinh')"
                />Asinh
              </label>
            </fieldset>
          </div>

          <div class="chart-box" #box>
            <svg
              [attr.viewBox]="'0 0 ' + w() + ' ' + H"
              [attr.width]="w()"
              [attr.height]="H"
              class="chart"
              role="img"
              [attr.aria-label]="'Brightness against wavelength for ' + drawn().length + ' epochs'"
              (mouseleave)="hover.set(null)"
            >
              @for (b of bands(); track b.detector; let i = $index) {
                <rect
                  class="band"
                  [class.alt]="i % 2 === 1"
                  [attr.x]="xs(b.x0)"
                  [attr.width]="xs(b.x1) - xs(b.x0)"
                  [attr.y]="M.t"
                  [attr.height]="H - M.t - M.b"
                >
                  <title>{{ b.title }}</title>
                </rect>
                @if (b.row >= 0) {
                  <text
                    class="band-label"
                    [attr.x]="(xs(b.x0) + xs(b.x1)) / 2"
                    [attr.y]="M.t - 6 - (1 - b.row) * 13"
                    text-anchor="middle"
                  >
                    <title>{{ b.title }}</title>
                    {{ b.detector }}
                  </text>
                }
              }
              @for (t of yTicks(); track t.value) {
                <line
                  class="grid"
                  [class.zero]="t.value === 0"
                  [attr.x1]="M.l"
                  [attr.x2]="w() - M.r"
                  [attr.y1]="ys(t.t)"
                  [attr.y2]="ys(t.t)"
                />
                <text class="tick" [attr.x]="M.l - 6" [attr.y]="ys(t.t) + 4" text-anchor="end">
                  {{ t.label }}
                </text>
              }
              @for (t of xTicks(); track t) {
                <text class="tick" [attr.x]="xs(t)" [attr.y]="H - M.b + 15" text-anchor="middle">
                  {{ t }}
                </text>
              }
              <text class="axis" [attr.x]="(M.l + w() - M.r) / 2" [attr.y]="H - 4" text-anchor="middle">
                wavelength (µm)
              </text>
              <text
                class="axis"
                [attr.transform]="'translate(11 ' + (M.t + (H - M.b)) / 2 + ') rotate(-90)'"
                text-anchor="middle"
              >
                {{ d.unit ?? '' }}
              </text>

              @for (s of drawn(); track s.epoch) {
                @for (seg of s.paths; track $index) {
                  <polyline
                    [attr.points]="seg"
                    fill="none"
                    [attr.stroke]="s.colour"
                    stroke-width="1.25"
                    stroke-linejoin="round"
                  />
                }
              }
              @for (s of drawn(); track s.epoch) {
                @for (p of s.points; track $index) {
                  <circle [attr.cx]="xs(p.wl)" [attr.cy]="yv(p.value)" r="2" [attr.fill]="s.colour" />
                }
              }
              @if (hovered(); as h) {
                <circle
                  class="hl"
                  [attr.cx]="xs(h.p.wl)"
                  [attr.cy]="yv(h.p.value)"
                  r="5"
                  [attr.fill]="h.colour"
                />
              }
              <!-- invisible, larger hit areas on top so the small points stay easy to hover -->
              @for (s of drawn(); track s.epoch; let si = $index) {
                @for (p of s.points; track $index; let pi = $index) {
                  <circle
                    class="hit"
                    [attr.cx]="xs(p.wl)"
                    [attr.cy]="yv(p.value)"
                    r="7"
                    (mouseenter)="hover.set({ si, pi })"
                  >
                    <title>
                      {{ s.label }} · {{ p.detector }}/{{ p.channel }} · {{ p.wl }} µm: {{ p.value }}
                      {{ d.unit }}{{ p.sigma !== null ? ' ± ' + p.sigma : '' }}
                    </title>
                  </circle>
                }
              }
            </svg>
          </div>
          <p class="muted small">
            Shaded stripes: the six detectors D1–D6 (hover a label for its range). Each detector is
            calibrated and observed separately, so a jump at a stripe border may not be real; lines
            are not joined across borders or across missing channels.
            @if (scale().kind === 'asinh') {
              Asinh axis: small values near zero are spread out and large ones squeezed, so faint and
              bright parts both show; the labels give the real values.
            }
          </p>
          <p class="muted small">
            Dates are the middle of each epoch across all detectors. Value:
            {{ d.value_definition }}. Negative values are normal on empty sky (noise around zero).
            Hover a point for its value.
          </p>
          <details class="table-view">
            <summary>Show as table</summary>
            <div class="scroll-x">
              <table>
                <thead>
                  <tr>
                    <th>Channel</th>
                    <th>µm</th>
                    @for (s of drawn(); track s.epoch) {
                      <th>{{ s.label }}</th>
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (c of d.channels; track c.detector + c.channel) {
                    <tr>
                      <td>{{ c.detector }}/{{ c.channel }}</td>
                      <td>{{ c.wavelength_um }}</td>
                      @for (s of drawn(); track s.epoch) {
                        <td>{{ valueOf(c.epochs, s.epoch) }}</td>
                      }
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </details>
        }
      }
    </section>
  `,
})
export class SpectrumPanel {
  private readonly api = inject(EpochsApi);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);
  readonly position = input.required<Position>();
  readonly x = input.required<number>();
  /** Picture row from the TOP, as clicked. */
  readonly y = input.required<number>();
  /** Picture height in pixels (the API counts rows from the bottom; see EpochsApi.spectrum). */
  readonly height = input.required<number>();
  readonly closed = output<void>();

  protected readonly H = H;
  protected readonly M = M;
  protected readonly radio = `spec-scale-${++uid}`;
  protected readonly data = signal<Spectrum | null>(null);
  protected readonly loading = signal(false);
  protected readonly err = signal<string | null>(null);
  /** The axis the user asked for; `scale` falls back to linear when asinh has no usable `s`. */
  protected readonly want = signal<'linear' | 'asinh'>('asinh');
  protected readonly hover = signal<{ si: number; pi: number } | null>(null);
  /** Chart width in px, measured from the panel. */
  protected readonly w = signal(640);
  private readonly box = viewChild<ElementRef<HTMLElement>>('box');

  /** Asinh scale parameter of this pixel, from all its channels and epochs. */
  protected readonly s = computed(() => {
    const d = this.data();
    return d ? asinhScale(d.channels) : null;
  });
  protected readonly scale = computed(() => yScale(this.want(), this.s()));

  private readonly series = computed(() => {
    const d = this.data();
    if (!d) return [];
    return spectrumSeries(d).map((e, i) => ({
      ...e,
      label: fmtDate(d.epochs[i].time),
      colour: SERIES[i % SERIES.length],
    }));
  });

  private readonly xRange = computed<[number, number]>(
    () => xDomain(detectorBands(this.data()?.channels ?? [])) ?? [0.7, 5.1],
  );
  private readonly yRange = computed<[number, number]>(
    () => yDomain(this.data()?.channels ?? [], this.scale()) ?? [0, 1],
  );

  /** Epochs with at least one point, with their line segments as SVG point lists. */
  protected readonly drawn = computed(() =>
    this.series()
      .filter((s) => s.points.length > 0)
      .map((s) => ({
        ...s,
        paths: s.segments
          .filter((seg) => seg.length > 1)
          .map((seg) => seg.map((p) => `${this.xs(p.wl)},${this.yv(p.value)}`).join(' ')),
      })),
  );

  protected readonly bands = computed(() => {
    const bands = detectorBands(this.data()?.channels ?? []);
    const centres = bands.map((b) => (this.xs(b.x0) + this.xs(b.x1)) / 2);
    const rows = labelRows(
      centres,
      bands.map((b) => labelWidth(b.detector)),
    );
    return bands.map((b, i) => ({ ...b, title: bandTitle(b), row: rows[i] }));
  });

  protected readonly hovered = computed(() => {
    const h = this.hover();
    const s = h && this.drawn()[h.si];
    const p: SpecPoint | undefined = s?.points[h!.pi];
    return s && p ? { p, colour: s.colour } : null;
  });

  protected readonly xTicks = computed(() => {
    const [a, b] = this.xRange();
    const n = Math.max(3, Math.min(8, Math.floor((this.w() - M.l - M.r) / 60)));
    return niceTicks(a, b, n).filter((t) => t >= a && t <= b);
  });
  protected readonly yTicks = computed(() =>
    yTicks(...this.yRange(), this.scale(), H - M.t - M.b, 18),
  );

  protected xs = (v: number) => {
    const [a, b] = this.xRange();
    return +(M.l + ((v - a) / (b - a)) * (this.w() - M.l - M.r)).toFixed(1);
  };
  /** y position of a transformed axis value. */
  protected ys = (t: number) => {
    const [a, b] = this.yRange();
    return +(H - M.b - ((t - a) / (b - a)) * (H - M.t - M.b)).toFixed(1);
  };
  /** y position of a real value (MJy/sr). */
  protected yv = (v: number) => this.ys(toAxis(v, this.scale()));

  protected valueOf(eps: { epoch: number; value: number | null }[], i: number): string {
    const v = eps.find((e) => e.epoch === i)?.value;
    return v === null || v === undefined ? '–' : String(v);
  }

  constructor() {
    effect((onCleanup) => {
      const p = this.position();
      const x = this.x();
      const y = this.y();
      const height = this.height();
      const ctl = new AbortController();
      onCleanup(() => ctl.abort());
      this.loading.set(true);
      this.err.set(null);
      this.hover.set(null);
      this.reveal();
      this.api
        .spectrum(p, x, y, height, ctl.signal)
        .then((d) => {
          this.data.set(d);
          this.reveal(); // the chart makes the panel taller: check again once it is drawn
        })
        .catch((e) => {
          if (!ctl.signal.aborted) this.err.set(friendly(e));
        })
        .finally(() => {
          if (!ctl.signal.aborted) this.loading.set(false);
        });
    });

    // The chart is as wide as its box, so labels keep their size and spacing on narrow screens.
    const ro = new ResizeObserver(([e]) => {
      const cw = Math.floor(e.contentRect.width);
      if (cw > 0 && cw !== this.w()) this.w.set(Math.max(260, cw));
    });
    effect(() => {
      const el = this.box()?.nativeElement;
      ro.disconnect();
      if (el) ro.observe(el);
    });
    inject(DestroyRef).onDestroy(() => ro.disconnect());
  }

  /**
   * Scroll the panel into view (top first) if it is not completely visible, e.g. below the picture on a phone.
   * Runs after a click and again once the chart is drawn. Beside the picture on a wide screen nothing moves.
   */
  private reveal(): void {
    afterNextRender(
      () => {
        const el = this.host.nativeElement;
        const r = el.getBoundingClientRect();
        const scroller = el.closest('dialog') ?? document.documentElement;
        const view = scroller.getBoundingClientRect();
        const top = Math.max(view.top, 0);
        const bottom = Math.min(view.bottom, window.innerHeight);
        if (r.top < top || r.bottom > bottom) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      },
      { injector: this.injector },
    );
  }
}
