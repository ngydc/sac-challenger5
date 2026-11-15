import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { EpochsApi } from './epochs-api.service';
import { ApiService } from './api.service';
import { ViewerState } from './viewer-state.service';
import { AnalysisStatus, Bundle, Position } from '../models/epochs.models';
import { EXAMPLES, Example } from '../examples';

export type Group = 'detector' | 'all';

const POLL_MS = 4000;
/** Measured 2026-11-15 (docs/FETCH_SPEED.md): about 3 images per second. Used until a rate has been measured. */
const FALLBACK_IMAGES_PER_S = 3;
const EXPLAINER_KEY = 'spherex-blink.deep-explainer-open';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const same = (a: Position | null, b: Position | null) =>
  !!a &&
  !!b &&
  a.ra === b.ra &&
  a.dec === b.dec &&
  a.fov === b.fov &&
  a.pmra === b.pmra &&
  a.pmdec === b.pmdec &&
  a.pm_epoch === b.pm_epoch;
const busy = (s: AnalysisStatus | null) =>
  !!s && (s.state === 'queued' || s.state === 'running' || s.refreshing);

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v === '1';
  } catch {
    return fallback;
  }
}

/**
 * State of the "Deep Analysis" panel: the difference pictures of the epoch maps (docs/API_ANALYSIS.md) for
 * the view on the main page (the same target, field of view and proper motion as the slider picture).
 *
 * Rule: opening the panel asks for the state only (GET /api/analysis?start=false). Computed results (e.g. the
 * examples) and running computations are shown at once. Only `showImages()`, the user's "Start deep analysis"
 * click, starts a computation (GET /api/analysis), because it may download a few hundred images.
 */
@Injectable({ providedIn: 'root' })
export class EpochsStore {
  private readonly api = inject(EpochsApi);
  private readonly mainApi = inject(ApiService);
  private readonly viewer = inject(ViewerState);

  /** The panel is open: the stage shows the difference pictures instead of the slider picture. */
  readonly open = signal(false);
  readonly position = signal<Position | null>(null);
  readonly status = signal<AnalysisStatus | null>(null);
  readonly checking = signal(false);
  readonly starting = signal(false);
  readonly error = signal<string | null>(null);
  /** True once the user asked for the pictures of this position. */
  readonly showing = signal(false);
  readonly group = signal<Group>('detector');
  readonly explainerOpen = signal(readFlag(EXPLAINER_KEY, true));
  /** Bundle shown enlarged. */
  readonly detail = signal<string | null>(null);
  /** Clicked pixel (PNG coordinates at scale 1) for the spectrum. */
  readonly pick = signal<{ x: number; y: number } | null>(null);
  /** Positions the backend precomputed for the examples (GET /api/resolve of their names). */
  readonly examplePositions = signal<Record<string, { ra: number; dec: number }>>({});

  private generation = 0;
  private samples: { t: number; done: number }[] = [];
  private readonly rate = signal<number | null>(null);
  private started = false;

  readonly result = computed(() => this.status()?.result ?? null);
  /** Queued, being computed, or a complete result being recomputed with new images. */
  readonly running = computed(() => busy(this.status()));
  /** Changes when the result was recomputed: part of the picture URLs, so new pictures load. */
  readonly version = computed(() => this.result()?.images_key ?? '');

  /** Bundles of the selected grouping, in the backend's order. */
  readonly bundles = computed<Bundle[]>(() => {
    const kind = this.group() === 'all' ? 'all' : 'detector';
    return (this.result()?.bundles ?? []).filter((b) => b.kind === kind);
  });

  readonly detailBundle = computed<Bundle | null>(() => {
    const id = this.detail();
    return (id && this.result()?.bundles.find((b) => b.id === id)) || null;
  });

  readonly activeExample = computed<Example | null>(() => {
    const p = this.position();
    if (!p) return null;
    const map = this.examplePositions();
    return (
      EXAMPLES.find((e) => {
        const q = map[e.name];
        return q && Math.abs(q.ra - p.ra) < 1e-4 && Math.abs(q.dec - p.dec) < 1e-4;
      }) ?? null
    );
  });

  /** Remaining time of a running computation, in seconds (null while the archive is being searched). */
  readonly remainingS = computed(() => {
    const pr = this.status()?.progress;
    if (!pr || pr.total <= 0) return null;
    return (pr.total - pr.done) / (this.rate() ?? FALLBACK_IMAGES_PER_S);
  });

  constructor() {
    // Follow the view of the main page while the panel is open: the same target as the slider picture
    // (position from GET /api/resolve, its field of view, its proper motion). For the five test targets with
    // their default field of view that is exactly what the backend precomputed.
    effect(() => {
      const t = this.viewer.target();
      const open = this.open();
      if (!open || !t) return;
      untracked(() => void this.setPosition(t));
    });
    effect(() => {
      const open = this.explainerOpen();
      try {
        localStorage.setItem(EXPLAINER_KEY, open ? '1' : '0');
      } catch {
        /* storage blocked: the default applies next time */
      }
    });
  }

  /** Opens or closes the panel; the first opening loads the example positions. */
  toggle(open = !this.open()): void {
    this.open.set(open);
    if (open && !this.started) {
      this.started = true;
      void this.loadExamples();
    }
    if (!open) this.closeDetail();
  }

  private async loadExamples(): Promise<void> {
    const out: Record<string, { ra: number; dec: number }> = {};
    await Promise.all(
      EXAMPLES.map(async (e) => {
        try {
          const r = await this.mainApi.resolve(e.name);
          out[e.name] = { ra: r.target.ra, dec: r.target.dec };
        } catch {
          /* then that example is simply not recognised */
        }
      }),
    );
    this.examplePositions.set(out);
  }

  /** Asks for the status only. */
  async setPosition(p: Position): Promise<void> {
    if (same(p, this.position()) && this.status()) return;
    const gen = ++this.generation;
    this.showing.set(false);
    this.status.set(null);
    this.closeDetail();
    this.error.set(null);
    this.position.set(p);
    this.checking.set(true);
    try {
      const s = await this.api.status(p);
      if (gen !== this.generation) return;
      this.status.set(s);
      // Already computed (e.g. the examples) or being computed: show it at once, nothing new is computed.
      // Only an uncomputed position waits for the user to start the (slow) analysis.
      if (s.state === 'ready' || busy(s)) this.showing.set(true);
      if (busy(s)) void this.poll(gen);
    } catch (e) {
      if (gen === this.generation) this.error.set(friendly(e));
    } finally {
      if (gen === this.generation) this.checking.set(false);
    }
  }

  /** "Start deep analysis": starts the computation (or shows what already exists). */
  async showImages(): Promise<void> {
    const p = this.position();
    const s = this.status();
    if (!p || !s) return;
    this.error.set(null);
    if (s.state === 'ready' || busy(s)) {
      this.showing.set(true);
      return;
    }
    this.starting.set(true);
    const gen = ++this.generation;
    try {
      const started = await this.api.start(p);
      if (gen !== this.generation) return;
      this.status.set(started);
      this.showing.set(true);
      if (busy(started)) void this.poll(gen);
    } catch (e) {
      this.error.set(friendly(e));
    } finally {
      this.starting.set(false);
    }
  }

  /** Polls the status while the backend computes; bundles appear one detector at a time. */
  private async poll(gen: number): Promise<void> {
    this.samples = [];
    this.rate.set(null);
    while (gen === this.generation && busy(this.status())) {
      await sleep(POLL_MS);
      if (gen !== this.generation) return;
      const p = this.position();
      if (!p) return;
      try {
        const s = await this.api.status(p);
        if (gen !== this.generation) return;
        this.status.set(s);
        this.measureRate(s);
      } catch {
        /* a missed poll is retried */
      }
    }
  }

  private measureRate(s: AnalysisStatus): void {
    const pr = s.progress;
    if (!pr || pr.total <= 0) return;
    this.samples.push({ t: Date.now() / 1000, done: pr.done });
    const first = this.samples[0];
    const last = this.samples[this.samples.length - 1];
    const dt = last.t - first.t;
    if (dt >= 60 && last.done > first.done) this.rate.set((last.done - first.done) / dt);
  }

  openDetail(id: string): void {
    this.pick.set(null);
    this.detail.set(id);
  }

  closeDetail(): void {
    this.detail.set(null);
    this.pick.set(null);
  }
}

export function friendly(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  if (/Failed to fetch|NetworkError|Load failed/i.test(msg)) {
    return 'The server is not reachable right now. Please try again in a moment.';
  }
  return msg.charAt(0).toUpperCase() + msg.slice(1);
}
