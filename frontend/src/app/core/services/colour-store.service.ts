import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { EpochsApi } from './epochs-api.service';
import { AnalysisStatusService } from './analysis-status.service';
import { ViewerState } from './viewer-state.service';
import { ToastService } from './toast.service';
import { friendly } from './epochs-store.service';
import { targetQuery } from './api.service';
import { fmtDuration } from '../utils/format';
import { AnalysisStatus, ColourEpoch } from '../models/epochs.models';
import { Target } from '../models/api.models';

/** Unlike the shared `busy`, a refresh does not count: the old colour pictures stay valid and are shown meanwhile. */
const computing = (s: AnalysisStatus | null) => !!s && (s.state === 'queued' || s.state === 'running');

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
  private readonly toasts = inject(ToastService);

  /** The shared state of the viewer's target; null while this store's own start request is still in flight. */
  readonly status = computed<AnalysisStatus | null>(() => {
    const t = this.viewer.target();
    const s = t ? this.analysis.status(t)() : null;
    return this.starting() && !computing(s) ? null : s;
  });
  readonly error = signal<string | null>(null);

  private readonly starting = signal(false);
  private generation = 0;
  private key = '';
  private readonly preloaded = new Set<string>();
  /** The target last checked for an already computed colour picture. */
  private autoKey = '';
  /** The target whose computation the user started with the button: its completion is announced. */
  private readonly requestedKey = signal('');

  readonly colour = computed(() => this.status()?.result?.colour ?? null);
  readonly running = computed(() => computing(this.status()));
  /** Changes when the analysis was recomputed with new images: part of the URL, so the new picture loads. */
  readonly version = computed(() => this.status()?.result?.images_key ?? '');
  readonly grid = computed(() => this.status()?.result?.grid ?? null);
  readonly queued = computed(() => this.status()?.state === 'queued');
  /** Progress as the Deep Analysis panel shows it: stage, done / total images, time left, detectors ready. */
  readonly progress = computed(() => {
    const p = this.status()?.progress;
    const t = this.viewer.target();
    if (!p || !t) return null;
    const left = this.analysis.remainingS(t)();
    return {
      ...p,
      pct: p.total > 0 ? Math.round((100 * p.done) / p.total) : 0,
      eta: left === null ? null : fmtDuration(left),
    };
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
    // Once a target is shown in Mono, ask whether its colour picture is already computed (asking starts nothing):
    // the Controls' compute button needs to know, and if the user has not chosen a mode, an existing picture
    // switches the view to Colour (colour by default).
    effect(() => {
      const t = this.viewer.target();
      if (this.viewer.phase() !== 'ready' || !t || this.viewer.mode() === 'colour') return;
      untracked(() => void this.colourIfComputed(t));
    });
    // A computation started with the button has finished while Mono is shown: say so, and offer the picture.
    effect(() => {
      const key = this.requestedKey();
      const t = this.viewer.target();
      if (!key || !t || targetQuery(t) !== key || !this.colour() || this.running()) return;
      untracked(() => {
        this.requestedKey.set('');
        if (this.viewer.mode() === 'colour') return;
        this.toasts.show({
          title: 'Colour image is ready.',
          text: 'Every wavelength of each season in one picture.',
          action: { label: 'Show Colour', run: () => this.viewer.setMode('colour') },
        });
      });
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

  /** The Controls' button: starts the computation of this target's colour pictures; the view stays as it is. */
  compute(): void {
    const t = this.viewer.target();
    if (!t || this.running()) return;
    this.requestedKey.set(targetQuery(t));
    this.key = '';
    void this.load(t);
  }

  /** After an error: ask again (a failed analysis is restarted by the backend after 30 s). */
  retry(): void {
    const t = this.viewer.target();
    if (!t) return;
    this.key = '';
    void this.load(t);
  }

  private async colourIfComputed(t: Target): Promise<void> {
    const key = targetQuery(t);
    if (key === this.autoKey) return; // asked already for this target (or the user went back to Mono)
    this.autoKey = key;
    try {
      const s = await this.analysis.check(t);
      const now = this.viewer.target();
      if (!now || targetQuery(now) !== key || !s.result?.colour?.usable_epochs.length) return;
      if (!this.viewer.autoColour()) return;
      this.toasts.show({
        title: 'Switched to colour view.',
        text: 'Colour image was already computed.',
        action: { label: 'Back to Mono', run: () => this.viewer.setMode('single') },
      });
    } catch {
      /* no answer: the view simply stays in Mono */
    }
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
