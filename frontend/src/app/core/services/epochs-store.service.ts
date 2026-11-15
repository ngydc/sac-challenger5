import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { EpochsApi } from './epochs-api.service';
import { ViewerState } from './viewer-state.service';
import { Bundle, EpochsConfig, EpochsStatus, Position } from '../models/epochs.models';
import { EXAMPLES, Example } from '../examples';

export type Group = 'detector' | 'all';

const POLL_MS = 4000;
/** docs/API_EPOCHS.md: "IRSA delivers about 20 cutouts per minute". Used until a rate has been measured. */
const FALLBACK_IMAGES_PER_S = 20 / 60;
const EXPLAINER_KEY = 'spherex-blink.deep-explainer-open';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const same = (a: Position | null, b: Position | null) =>
  !!a && !!b && a.ra === b.ra && a.dec === b.dec && a.fov === b.fov;

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v === '1';
  } catch {
    return fallback;
  }
}

/**
 * State of the "Deep Analysis" panel: the difference pictures of the epoch maps (docs/API_EPOCHS.md)
 * for the object searched on the main page.
 *
 * Rule: opening the panel asks for the status (GET /api/epochs). Computed results (e.g. the examples) and
 * running computations are shown at once. Only `showImages()`, the user's "Start deep analysis" click,
 * calls POST /api/compute, because that downloads hundreds of images and takes tens of minutes.
 */
@Injectable({ providedIn: 'root' })
export class EpochsStore {
  private readonly api = inject(EpochsApi);
  private readonly viewer = inject(ViewerState);

  /** The panel is open: the stage shows the difference pictures instead of the slider picture. */
  readonly open = signal(false);
  readonly config = signal<EpochsConfig | null>(null);
  readonly position = signal<Position | null>(null);
  readonly status = signal<EpochsStatus | null>(null);
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
  readonly running = computed(() => this.status()?.status === 'running');
  readonly version = computed(() => this.result()?.searched_at ?? '');

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

  get defaultFov(): number {
    return this.config()?.default_fov ?? this.status()?.default_fov ?? 0.08;
  }

  constructor() {
    // Follow the object searched on the main page while the panel is open. Its position is the one
    // GET /api/resolve returned, which for the five test targets is exactly the precomputed one. The field
    // of view is the epoch maps' own default (GET /api/config): that is what the precomputed results use.
    effect(() => {
      const t = this.viewer.resolved()?.target;
      const open = this.open();
      const cfg = this.config();
      if (!open || !t || !cfg) return;
      untracked(() => void this.setPosition({ ra: t.ra, dec: t.dec, fov: cfg.default_fov }));
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

  /** Opens or closes the panel; the first opening loads the config and the example positions. */
  toggle(open = !this.open()): void {
    this.open.set(open);
    if (open && !this.started) {
      this.started = true;
      void this.loadConfig();
      void this.loadExamples();
    }
    if (!open) this.closeDetail();
  }

  private async loadConfig(): Promise<void> {
    try {
      this.config.set(await this.api.config());
    } catch (e) {
      this.started = false;
      this.error.set(friendly(e));
    }
  }

  private async loadExamples(): Promise<void> {
    const out: Record<string, { ra: number; dec: number }> = {};
    await Promise.all(
      EXAMPLES.map(async (e) => {
        try {
          const r = await this.api.resolve(e.name);
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
      if (s.status === 'cached' || s.status === 'running') this.showing.set(true);
      if (s.status === 'running') void this.poll(gen);
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
    if (s.status === 'cached' || s.status === 'running') {
      this.showing.set(true);
      return;
    }
    this.starting.set(true);
    const gen = ++this.generation;
    try {
      const started = await this.api.compute(p);
      if (gen !== this.generation) return;
      this.status.set(started);
      this.showing.set(true);
      if (started.status === 'running') void this.poll(gen);
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
    while (gen === this.generation && this.status()?.status === 'running') {
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

  private measureRate(s: EpochsStatus): void {
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
