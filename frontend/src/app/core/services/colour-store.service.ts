import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { EpochsApi } from './epochs-api.service';
import { AnalysisStatusService } from './analysis-status.service';
import { ViewerState } from './viewer-state.service';
import { friendly } from './epochs-store.service';
import { targetQuery } from './api.service';
import { AnalysisStatus, ColourEpoch } from '../models/epochs.models';
import { Target } from '../models/api.models';

const busy = (s: AnalysisStatus | null) => !!s && (s.state === 'queued' || s.state === 'running');

/**
 * The colour view: every wavelength of one season in one picture (GET /api/analysis/colour/{epoch}.png,
 * docs/API_ANALYSIS.md). The pictures are part of the deep analysis, so they share its computation and storage.
 *
 * Switching the viewer to colour is the user's request for these pictures: if the position has no analysis yet, it is
 * started here (a new position takes about 2 minutes; the five test targets are computed at backend start-up).
 * The state and its polling belong to AnalysisStatusService, shared with the Deep Analysis panel.
 */
@Injectable({ providedIn: 'root' })
export class ColourStore {
  private readonly api = inject(EpochsApi);
  private readonly analysis = inject(AnalysisStatusService);
  private readonly viewer = inject(ViewerState);

  /** The shared state of the viewer's target; null while this store's own start request is still in flight. */
  readonly status = computed<AnalysisStatus | null>(() => {
    const t = this.viewer.target();
    const s = t ? this.analysis.status(t)() : null;
    return this.starting() && !busy(s) ? null : s;
  });
  readonly error = signal<string | null>(null);

  private readonly starting = signal(false);
  private generation = 0;
  private key = '';
  private readonly preloaded = new Set<string>();

  readonly colour = computed(() => this.status()?.result?.colour ?? null);
  readonly running = computed(() => busy(this.status()));
  /** Changes when the analysis was recomputed with new images: part of the URL, so the new picture loads. */
  readonly version = computed(() => this.status()?.result?.images_key ?? '');
  readonly grid = computed(() => this.status()?.result?.grid ?? null);
  readonly progress = computed(() => {
    const p = this.status()?.progress;
    return p && p.total > 0 ? Math.round((100 * p.done) / p.total) : null;
  });

  /**
   * The colour epoch of the viewer's current season, matched by date: both group the same images by gaps of more
   * than 30 days, but matching by date cannot go wrong if one list has a season the other lacks.
   */
  readonly epoch = computed<ColourEpoch | null>(() => {
    const c = this.colour();
    const v = this.viewer.visits()[this.viewer.visit()];
    if (!c || !v) return null;
    return c.epochs.find((e) => !!e.start && !!e.end && e.start <= v.end && e.end >= v.start) ?? null;
  });

  readonly url = computed(() => {
    const e = this.epoch();
    const t = this.viewer.target();
    return e?.usable && t ? this.api.colourUrl(t, e.index, this.version()) : null;
  });

  constructor() {
    // Follow the viewer's target while colour is shown.
    effect(() => {
      const t = this.viewer.target();
      const on = this.viewer.mode() === 'colour' && this.viewer.phase() === 'ready';
      if (!on || !t) return;
      untracked(() => void this.load(t));
    });
    // Load every season's picture in the background, so blinking is instant.
    effect(() => {
      const c = this.colour();
      const t = this.viewer.target();
      const v = this.version();
      if (!c || !t || this.viewer.mode() !== 'colour') return;
      for (const e of c.usable_epochs) {
        const u = this.api.colourUrl(t, e, v);
        if (this.preloaded.has(u)) continue;
        this.preloaded.add(u);
        new Image().src = u;
      }
    });
  }

  /** After an error: ask again (a failed analysis is restarted by the backend after 30 s). */
  retry(): void {
    const t = this.viewer.target();
    if (!t) return;
    this.key = '';
    void this.load(t);
  }

  private async load(t: Target): Promise<void> {
    const key = targetQuery(t);
    if (key === this.key && (this.starting() || this.colour() || this.running())) return;
    const gen = ++this.generation;
    this.key = key;
    this.error.set(null);
    this.starting.set(true);
    try {
      // The shared service polls while it is computed; the colour pictures come last, after every detector.
      await this.analysis.start(t);
    } catch (e) {
      if (gen === this.generation) this.error.set(friendly(e));
    } finally {
      if (gen === this.generation) this.starting.set(false);
    }
  }
}
