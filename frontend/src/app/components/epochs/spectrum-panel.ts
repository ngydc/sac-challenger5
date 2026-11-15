import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { Position, Spectrum } from '../../core/models/epochs.models';
import { EpochsApi } from '../../core/services/epochs-api.service';
import { friendly } from '../../core/services/epochs-store.service';
import { fmtDate } from '../../core/utils/format';

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
const W = 640;
const H = 260;
const M = { l: 58, r: 14, t: 12, b: 38 };

interface Pt {
  wl: number;
  v: number;
  s: number | null;
  label: string;
}

function niceTicks(lo: number, hi: number, n = 5): number[] {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step)
    out.push(+t.toPrecision(10));
  return out;
}

/** Spectrum of one clicked pixel, one line per epoch (GET /api/spectrum). */
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
        @if (series().length === 0) {
          <p class="muted">
            No measurements at this pixel (it has no data, for example a saturated centre).
          </p>
        } @else {
          <ul class="legend">
            @for (s of series(); track s.index) {
              <li><span class="sw line" [style.background]="s.colour"></span>{{ s.label }}</li>
            }
          </ul>
          <svg
            [attr.viewBox]="'0 0 ' + W + ' ' + H"
            class="chart"
            role="img"
            [attr.aria-label]="'Brightness against wavelength for ' + series().length + ' epochs'"
          >
            @for (t of yTicks(); track t) {
              <line
                class="grid"
                [attr.x1]="M.l"
                [attr.x2]="W - M.r"
                [attr.y1]="ys(t)"
                [attr.y2]="ys(t)"
              />
              <text class="tick" [attr.x]="M.l - 6" [attr.y]="ys(t) + 4" text-anchor="end">
                {{ t }}
              </text>
            }
            @for (t of xTicks(); track t) {
              <text class="tick" [attr.x]="xs(t)" [attr.y]="H - M.b + 16" text-anchor="middle">
                {{ t }}
              </text>
            }
            <text class="axis" [attr.x]="(M.l + W - M.r) / 2" [attr.y]="H - 4" text-anchor="middle">
              wavelength (µm)
            </text>
            <text
              class="axis"
              [attr.transform]="'translate(14 ' + (M.t + (H - M.b)) / 2 + ') rotate(-90)'"
              text-anchor="middle"
            >
              {{ d.unit ?? '' }}
            </text>
            @for (s of series(); track s.index) {
              <polyline
                [attr.points]="s.path"
                fill="none"
                [attr.stroke]="s.colour"
                stroke-width="2"
                stroke-linejoin="round"
              />
              @for (p of s.pts; track $index) {
                <circle
                  [attr.cx]="xs(p.wl)"
                  [attr.cy]="ys(p.v)"
                  r="4"
                  [attr.fill]="s.colour"
                  stroke="var(--surface)"
                  stroke-width="1.5"
                >
                  <title>
                    {{ s.label }} · {{ p.label }} · {{ p.wl }} µm: {{ p.v }} {{ d.unit
                    }}{{ p.s !== null ? ' ± ' + p.s : '' }}
                  </title>
                </circle>
              }
            }
          </svg>
          <p class="muted small">
            Dates are the middle of each epoch across all detectors. Value:
            {{ d.value_definition }}. Hover a point for its value.
          </p>
          <details class="table-view">
            <summary>Show as table</summary>
            <div class="scroll-x">
              <table>
                <thead>
                  <tr>
                    <th>Channel</th>
                    <th>µm</th>
                    @for (s of series(); track s.index) {
                      <th>{{ s.label }}</th>
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (c of d.channels; track c.detector + c.channel) {
                    <tr>
                      <td>{{ c.detector }}/{{ c.channel }}</td>
                      <td>{{ c.wavelength_um }}</td>
                      @for (s of series(); track s.index) {
                        <td>{{ valueOf(c.epochs, s.index) }}</td>
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
  readonly position = input.required<Position>();
  readonly x = input.required<number>();
  readonly y = input.required<number>();
  readonly closed = output<void>();

  protected readonly W = W;
  protected readonly H = H;
  protected readonly M = M;
  protected readonly data = signal<Spectrum | null>(null);
  protected readonly loading = signal(false);
  protected readonly err = signal<string | null>(null);

  protected readonly series = computed(() => {
    const d = this.data();
    if (!d) return [];
    return d.epochs
      .map((e, i) => {
        const pts: Pt[] = [];
        for (const c of d.channels) {
          const v = c.epochs.find((x) => x.epoch === e.index);
          if (c.wavelength_um !== null && v && v.value !== null) {
            pts.push({
              wl: c.wavelength_um,
              v: v.value,
              s: v.sigma,
              label: `${c.detector}/${c.channel}`,
            });
          }
        }
        pts.sort((a, b) => a.wl - b.wl);
        return {
          index: e.index,
          label: fmtDate(e.time),
          colour: SERIES[i % SERIES.length],
          pts,
          path: '',
        };
      })
      .filter((s) => s.pts.length > 0)
      .map((s) => ({ ...s, path: s.pts.map((p) => `${this.xs(p.wl)},${this.ys(p.v)}`).join(' ') }));
  });

  private readonly xRange = computed<[number, number]>(() => {
    const wl = (this.data()?.channels ?? [])
      .map((c) => c.wavelength_um)
      .filter((w): w is number => w !== null);
    return wl.length ? [Math.min(...wl) - 0.05, Math.max(...wl) + 0.05] : [0.7, 5.1];
  });

  private readonly yRange = computed<[number, number]>(() => {
    const vals: number[] = [];
    for (const c of this.data()?.channels ?? [])
      for (const e of c.epochs) if (e.value !== null) vals.push(e.value);
    if (!vals.length) return [0, 1];
    const t = niceTicks(Math.min(0, ...vals), Math.max(...vals));
    return [Math.min(t[0], Math.min(...vals)), Math.max(t[t.length - 1], Math.max(...vals))];
  });

  protected readonly xTicks = computed(() =>
    niceTicks(...this.xRange(), 6).filter((t) => t >= this.xRange()[0]),
  );
  protected readonly yTicks = computed(() => niceTicks(...this.yRange(), 4));

  protected xs = (v: number) => {
    const [a, b] = this.xRange();
    return +(M.l + ((v - a) / (b - a)) * (W - M.l - M.r)).toFixed(1);
  };
  protected ys = (v: number) => {
    const [a, b] = this.yRange();
    return +(H - M.b - ((v - a) / (b - a)) * (H - M.t - M.b)).toFixed(1);
  };

  protected valueOf(eps: { epoch: number; value: number | null }[], i: number): string {
    const v = eps.find((e) => e.epoch === i)?.value;
    return v === null || v === undefined ? '–' : String(v);
  }

  constructor() {
    effect((onCleanup) => {
      const p = this.position();
      const x = this.x();
      const y = this.y();
      const ctl = new AbortController();
      onCleanup(() => ctl.abort());
      this.loading.set(true);
      this.err.set(null);
      this.api
        .spectrum(p, x, y, ctl.signal)
        .then((d) => this.data.set(d))
        .catch((e) => {
          if (!ctl.signal.aborted) this.err.set(friendly(e));
        })
        .finally(() => {
          if (!ctl.signal.aborted) this.loading.set(false);
        });
    });
  }
}
