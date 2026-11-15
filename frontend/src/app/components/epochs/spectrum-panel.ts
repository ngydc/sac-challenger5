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
import { DiffPair, Position, Spectrum } from '../../core/models/epochs.models';
import { EpochsApi } from '../../core/services/epochs-api.service';
import { friendly } from '../../core/services/epochs-store.service';
import { fmtDate } from '../../core/utils/format';
import {
  DetectorChoice,
  DetectorPick,
  EpochRole,
  SpecPoint,
  asinhScale,
  bandTitle,
  detectorChoices,
  drawRank,
  epochStyles,
  hasPair,
  keepPick,
  keepShown,
  roleText,
  visibleEpochs,
  labelRows,
  niceTicks,
  spectrumSeries,
  spectrumView,
  toAxis,
  yScale,
  yTicks,
} from '../../core/utils/spectrum';

/** Chart height in px; the width follows the panel (so text keeps its size on narrow screens). */
const H = 260;
/** Margins: the top one holds the detector labels (two rows if they would overlap). */
const M = { l: 46, r: 10, t: 34, b: 34 };
/** Rough width of a detector label ("D1") at 10px. */
const labelWidth = (s: string) => s.length * 6.5;
/** Below this chart width the detector picker is a dropdown instead of a row of buttons. */
const NARROW = 400;

let uid = 0;

/** Legend swatch: a solid line, dashed for epochs outside the pair (as drawn in the chart). */
function swatch(colour: string, role: EpochRole): string {
  return role === 'other'
    ? `repeating-linear-gradient(90deg, ${colour} 0 4px, transparent 4px 7px)`
    : colour;
}

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
            one line per epoch.
            @if (paired()) {
              <span class="pair-intro">
                <b class="c-later">Blue</b> and <b class="c-earlier">red</b> are the same two epochs
                as in the picture: where blue lies above red, the spot got brighter (blue in the
                picture).
              </span>
            } @else {
              Compare the lines: if they differ, the spot changed.
            }
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
        @if (!measured()) {
          <p class="muted">
            No measurements at this pixel (it has no data, for example a saturated centre).
          </p>
        } @else {
          <div class="spec-bar">
            @if (narrow()) {
              <label class="det-select">
                <span class="muted small">Show</span>
                <select [value]="pick()" (change)="choose($any($event.target).value)">
                  <option value="all" [selected]="pick() === 'all'">All detectors</option>
                  @for (c of choices(); track c.detector) {
                    <option
                      [value]="c.detector"
                      [disabled]="!c.hasData"
                      [selected]="pick() === c.detector"
                    >
                      {{ c.detector }}{{ c.hasData ? '' : ' (no data here)' }}
                    </option>
                  }
                </select>
              </label>
            } @else {
              <fieldset class="seg scale dets">
                <legend class="sr-only">Detector to show</legend>
                <label
                  class="btn"
                  [class.active]="pick() === 'all'"
                  title="Show the whole spectrum, all detectors"
                >
                  <input
                    type="radio"
                    class="sr-only"
                    [name]="detRadio"
                    [checked]="pick() === 'all'"
                    (change)="choose('all')"
                  />All
                </label>
                @for (c of choices(); track c.detector) {
                  <label
                    class="btn"
                    [class.active]="pick() === c.detector"
                    [class.off]="!c.hasData"
                    [class.shown]="c.detector === highlight()"
                    [attr.title]="choiceTitle(c)"
                  >
                    <input
                      type="radio"
                      class="sr-only"
                      [name]="detRadio"
                      [checked]="pick() === c.detector"
                      [disabled]="!c.hasData"
                      (change)="choose(c.detector)"
                    />{{ c.detector }}
                  </label>
                }
              </fieldset>
            }
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
          @if (empty().length) {
            <p class="muted small">
              {{ empty().join(', ') }}: no measurements at this pixel, so
              {{ empty().length === 1 ? 'it cannot be shown on its own' : 'they cannot be shown on their own' }}.
            </p>
          }
          <ul class="legend" [class.paired]="paired()" aria-label="Epochs">
            @for (s of epochs(); track s.epoch) {
              @if (s.role === 'other') {
                <!-- not in the picture: a switch (native checkbox, so it works with the keyboard) -->
                <li class="extra" [class.off]="!s.visible" [class.none]="s.visible && !inView().has(s.epoch)">
                  <label [attr.title]="s.n ? toggleTitle(s) : s.label + ': no values at this pixel'">
                    <input
                      type="checkbox"
                      [checked]="s.visible"
                      [disabled]="s.n === 0"
                      (change)="toggle(s.epoch)"
                    />
                    <span class="sw line" [style.background]="s.swatch"></span>
                    <span>{{ s.label }}</span>
                    <span class="role">
                      · {{ s.n === 0 ? 'no values here' : s.visible ? 'shown' : 'hidden' }}
                    </span>
                  </label>
                </li>
              } @else {
                <li
                  [class.none]="s.n === 0 || !inView().has(s.epoch)"
                  [attr.title]="
                    s.n === 0
                      ? s.label + ': no values at this pixel'
                      : inView().has(s.epoch)
                        ? (s.roleText ? s.label + ': ' + s.roleText : null)
                        : 'No values from ' + view().pick + ' in this epoch'
                  "
                >
                  <span class="sw line" [style.background]="s.swatch"></span>
                  @if (s.roleText) {
                    <b>{{ s.label }}</b>
                    <span class="role">
                      · {{ s.roleText }}{{ s.n === 0 ? ' · no values here' : '' }}
                    </span>
                  } @else {
                    {{ s.label }}
                  }
                </li>
              }
            }
          </ul>

          <div class="chart-box" #box>
            <svg
              [attr.viewBox]="'0 0 ' + w() + ' ' + H"
              [attr.width]="w()"
              [attr.height]="H"
              class="chart"
              role="img"
              [attr.aria-label]="
                'Brightness against wavelength for ' +
                drawn().length +
                ' epochs' +
                (zoomed() ? ', detector ' + view().pick + ' only' : '')
              "
              (mouseleave)="hover.set(null)"
            >
              @for (b of bands(); track b.detector) {
                <rect
                  class="band"
                  [class.alt]="b.alt"
                  [class.pickable]="b.pickable"
                  [class.shown]="b.shown"
                  [attr.x]="xs(b.x0)"
                  [attr.width]="xs(b.x1) - xs(b.x0)"
                  [attr.y]="M.t"
                  [attr.height]="H - M.t - M.b"
                  (click)="b.pickable && choose(b.detector)"
                >
                  <title>{{ b.title }}</title>
                </rect>
                @if (b.row >= 0) {
                  <text
                    class="band-label"
                    [class.pickable]="b.pickable"
                    [class.shown]="b.shown"
                    [class.empty]="!b.hasData"
                    [attr.x]="(xs(b.x0) + xs(b.x1)) / 2"
                    [attr.y]="M.t - 6 - (1 - b.row) * 13"
                    text-anchor="middle"
                    (click)="b.pickable && choose(b.detector)"
                  >
                    <title>{{ b.title }}</title>
                    {{ zoomed() ? b.title : b.detector }}
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
              @for (t of xTicks(); track $index) {
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
                    [attr.stroke-width]="s.role === 'other' ? 1 : 1.25"
                    [attr.stroke-dasharray]="s.role === 'other' ? '4 3' : null"
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
                      {{ s.label }}{{ s.roleText ? ' (' + s.roleText + ')' : '' }} ·
                      {{ p.detector }}/{{ p.channel }} · {{ p.wl }} µm: {{ p.value }}
                      {{ d.unit }}{{ p.sigma !== null ? ' ± ' + p.sigma : '' }}
                    </title>
                  </circle>
                }
              }
            </svg>
          </div>
          @if (zoomed()) {
            <p class="zoom-note small">
              <span>
                Zoomed in on <b>{{ view().pick }}</b>: the brightness axis is fitted to this
                detector's values only, so heights here cannot be compared with other detectors or
                with the full spectrum.
              </span>
              <button type="button" class="btn" (click)="choose('all')">
                ← Show all detectors
              </button>
            </p>
          } @else {
            <p class="muted small">
              Shaded stripes: the {{ choices().length }} detectors
              {{ choices()[0]?.detector }}–{{ choices()[choices().length - 1]?.detector }} (hover a
              label for its range; click a stripe to zoom in on it). Each detector is calibrated and
              observed separately, so a jump at a stripe border may not be real; lines are not joined
              across borders or across missing channels.
              @if (highlight() && hasChoice(highlight()!)) {
                The brighter stripe, {{ highlight() }}, is the detector of the picture.
              }
            </p>
          }
          @if (paired()) {
            <p class="muted small">
              @if (extras().length) {
                The other {{ extras().length === 1 ? 'epoch is' : 'epochs are' }} hidden at first;
                tick {{ extras().length === 1 ? 'it' : 'them' }} above to add a dashed line.
              }
              The picture averages all channels of
              {{ highlight() ? 'detector ' + highlight() : 'its detectors' }}, so single channels may
              go the other way.
              @if (highlight() && hasChoice(highlight()!) && view().pick !== highlight()) {
                To compare with the picture, zoom in on {{ highlight() }}.
              }
            </p>
          }
          <p class="muted small">
            @if (zoomed()) {
              Lines are not joined across missing channels.
            }
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
                    @for (s of epochs(); track s.epoch) {
                      <th [attr.title]="s.roleText || null">
                        <span class="sw" [style.background]="s.colour" aria-hidden="true"></span>
                        {{ s.label }}
                        @if (s.roleText) {
                          <span class="sr-only">({{ s.roleText }})</span>
                        }
                      </th>
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (c of d.channels; track c.detector + c.channel) {
                    <tr>
                      <td>{{ c.detector }}/{{ c.channel }}</td>
                      <td>{{ c.wavelength_um }}</td>
                      @for (s of epochs(); track s.epoch) {
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
  /** Detector of the picture beside the panel (e.g. "D4"); its stripe is highlighted in the full view. */
  readonly highlight = input<string | null>(null);
  /**
   * The two epochs the picture beside the panel compares (`diffPair(bundle, step)`): the later one is drawn
   * blue, the earlier red, like the picture. null = no picture: every epoch shown, coloured in order.
   */
  readonly pair = input<DiffPair | null>(null);
  readonly closed = output<void>();

  protected readonly H = H;
  protected readonly M = M;
  protected readonly radio = `spec-scale-${++uid}`;
  protected readonly detRadio = `spec-det-${uid}`;
  /** The detector the user picked; starts at 'all' each time the panel opens, kept across pixels. */
  protected readonly pick = signal<DetectorPick>('all');
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

  protected readonly choices = computed(() => detectorChoices(this.data()?.channels ?? []));
  /** Detectors without any value at this pixel (their buttons are disabled). */
  protected readonly empty = computed(() =>
    this.choices()
      .filter((c) => !c.hasData)
      .map((c) => c.detector),
  );
  /** Role (later / earlier / other / plain) and colour of every epoch of the answer, for the picture's pair. */
  private readonly styles = computed(() => {
    const p = this.pair();
    return epochStyles(
      (this.data()?.epochs ?? []).map((e) => e.index),
      p ? { first: p.first.epoch, last: p.last.epoch } : null,
    );
  });
  protected readonly paired = computed(() => hasPair(this.styles()));
  /** Epochs outside the pair the user switched on; kept while the panel is open (also across pixels). */
  private readonly shownExtra = signal<ReadonlySet<number>>(new Set());
  /** Epochs drawn: all without a pair, else the pair plus the switched-on ones. */
  private readonly visible = computed(() => new Set(visibleEpochs(this.styles(), this.shownExtra())));

  /**
   * The window the chart shows (channels, bands, x and y range) for the pick; `s` is not touched by it. With a
   * pair only the visible epochs set the y range.
   */
  protected readonly view = computed(() =>
    spectrumView(
      this.data()?.channels ?? [],
      this.pick(),
      this.scale(),
      undefined,
      this.paired() ? [...this.visible()] : undefined,
    ),
  );
  protected readonly zoomed = computed(() => this.view().pick !== 'all');
  protected readonly narrow = computed(() => this.w() < NARROW);

  /**
   * Legend and table entries. Without a pair: every epoch with at least one point at this pixel (as before).
   * With a pair: every epoch, also one without values here (marked so), with its role.
   */
  protected readonly epochs = computed(() => {
    const d = this.data();
    if (!d) return [];
    const st = this.styles();
    const vis = this.visible();
    const paired = this.paired();
    return spectrumSeries(d)
      .map((e, i) => ({
        epoch: e.epoch,
        n: e.points.length,
        label: fmtDate(d.epochs[i].time),
        colour: st[i].colour,
        role: st[i].role,
        roleText: roleText(st[i].role),
        visible: vis.has(e.epoch),
        swatch: swatch(st[i].colour, st[i].role),
      }))
      .filter((e) => paired || e.n > 0);
  });
  /** At least one epoch has a value at this pixel. */
  protected readonly measured = computed(() => this.epochs().some((e) => e.n > 0));
  /** Other epochs (outside the pair) that have values here, i.e. something to switch on. */
  protected readonly extras = computed(() => this.epochs().filter((e) => e.role === 'other' && e.n > 0));

  /** Visible line series of the channels in view, coloured like the legend; the pair drawn last (on top). */
  private readonly series = computed(() => {
    const d = this.data();
    if (!d) return [];
    const st = this.styles();
    const vis = this.visible();
    return spectrumSeries(d, this.view().channels)
      .map((e, i) => ({
        ...e,
        label: fmtDate(d.epochs[i].time),
        colour: st[i].colour,
        role: st[i].role,
        roleText: roleText(st[i].role),
      }))
      .filter((e) => vis.has(e.epoch))
      .sort((a, b) => drawRank(a.role) - drawRank(b.role));
  });
  /** Epochs that have a point in the current view. */
  protected readonly inView = computed(() => new Set(this.drawn().map((s) => s.epoch)));

  private readonly xRange = computed<[number, number]>(() => this.view().x);
  private readonly yRange = computed<[number, number]>(() => this.view().y);

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
    const v = this.view();
    const zoomed = v.pick !== 'all';
    const all = this.choices();
    const centres = v.bands.map((b) => (this.xs(b.x0) + this.xs(b.x1)) / 2);
    const rows = zoomed
      ? [1] // one stripe across the chart: its label sits in the lower row, next to the plot
      : labelRows(
          centres,
          v.bands.map((b) => labelWidth(b.detector)),
        );
    const hl = this.highlight();
    return v.bands.map((b, i) => {
      const hasData = all.find((c) => c.detector === b.detector)?.hasData ?? false;
      const shown = !zoomed && b.detector === hl;
      const pickable = !zoomed && hasData;
      const title =
        bandTitle(b) +
        (shown ? ' · the picture shows this detector' : '') +
        (!hasData ? ' · no measurements at this pixel' : pickable ? ' · click to zoom in' : '');
      return {
        ...b,
        // Alternate shading by position among ALL detectors, so a stripe keeps its tint when zoomed.
        alt: all.findIndex((c) => c.detector === b.detector) % 2 === 1,
        title,
        row: rows[i],
        hasData,
        shown,
        pickable,
      };
    });
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

  protected choose(pick: DetectorPick): void {
    this.hover.set(null);
    this.pick.set(pick);
  }

  /** Show or hide one epoch outside the pair. */
  protected toggle(epoch: number): void {
    this.hover.set(null);
    this.shownExtra.update((s) => {
      const next = new Set(s);
      if (!next.delete(epoch)) next.add(epoch);
      return next;
    });
  }

  protected toggleTitle(e: { label: string; visible: boolean }): string {
    return `${e.label} is not one of the two epochs in the picture. Click to ${e.visible ? 'hide' : 'show'} its line (dashed).`;
  }

  protected hasChoice(det: string): boolean {
    return this.choices().some((c) => c.detector === det);
  }

  protected choiceTitle(c: DetectorChoice): string {
    if (!c.hasData) return `${c.detector}: no measurements at this pixel, so there is nothing to zoom in on.`;
    const own = c.detector === this.highlight() ? ' (the detector of the picture)' : '';
    return `Zoom in on ${bandTitle(c.band)}${own}`;
  }

  protected valueOf(eps: { epoch: number; value: number | null }[], i: number): string {
    const v = eps.find((e) => e.epoch === i)?.value;
    return v === null || v === undefined ? '–' : String(v);
  }

  constructor() {
    // A new pair (Total ↔ step, other detector): an epoch that joined the pair is dropped from the switched-on
    // ones, so if it leaves the pair later it starts hidden like every other epoch.
    effect(() => {
      const st = this.styles();
      this.shownExtra.update((s) => keepShown(s, st));
    });

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
          // Keep the picked detector on the new pixel if it has values there, else back to the full spectrum.
          this.pick.update((p) => keepPick(p, d.channels));
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
