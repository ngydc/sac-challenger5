import { Injectable, Signal, WritableSignal, computed, inject, signal } from '@angular/core';
import { EpochsApi } from './epochs-api.service';
import { targetQuery } from './api.service';
import { AnalysisStatus, Position } from '../models/epochs.models';

/** Measured 2026-11-15 (docs/FETCH_SPEED.md): about 3 images per second. Used until a rate has been measured. */
const FALLBACK_IMAGES_PER_S = 3;

/** How often a queued or running computation is asked for its state. */
export const POLL_MS = 4000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Queued, being computed, or a complete result being recomputed with new images. */
export const busy = (s: AnalysisStatus | null | undefined): boolean =>
  !!s && (s.state === 'queued' || s.state === 'running' || s.refreshing);

interface Entry {
  readonly target: Position;
  readonly status: WritableSignal<AnalysisStatus | null>;
  /** Images processed per second, measured over the last minute or more of this computation (null until then). */
  readonly rate: WritableSignal<number | null>;
  readonly remainingS: Signal<number | null>;
  samples: { t: number; done: number }[];
  polling: boolean;
  /** Requests are numbered when sent; an answer older than one already applied is dropped. */
  sent: number;
  applied: number;
}

/**
 * The state of the deep analysis (docs/API_ANALYSIS.md) of each target, shared by everything that needs it: the
 * "Deep Analysis" panel and the viewer's colour mode. The key is the target's query string (position, field of
 * view and proper motion), as on the backend, so the same view is never polled twice, and a computation started by
 * one side shows up at the other at once.
 *
 * `check` asks without starting anything (GET /api/analysis?start=false), `start` starts the computation if
 * needed. Whoever calls `start` decides that; this service never starts anything by itself. While a computation is
 * queued or running (or a result is being refreshed) one loop per target polls it, until it is no longer busy.
 */
@Injectable({ providedIn: 'root' })
export class AnalysisStatusService {
  private readonly api = inject(EpochsApi);
  private readonly entries = new Map<string, Entry>();

  /** The latest known state of `target` (null until the first answer). Read-only; changes as polls arrive. */
  status(target: Position): Signal<AnalysisStatus | null> {
    return this.entry(target).status.asReadonly();
  }

  /** Remaining time of `target`'s running computation in seconds (null when nothing runs or the total is unknown). */
  remainingS(target: Position): Signal<number | null> {
    return this.entry(target).remainingS;
  }

  /** Asks for the state only; rejects if the request fails. */
  check(target: Position): Promise<AnalysisStatus> {
    return this.request(target, false);
  }

  /** Starts the analysis if needed (nothing happens if it is complete or running) and reports it. */
  start(target: Position): Promise<AnalysisStatus> {
    return this.request(target, true);
  }

  /** Stores a state as if the server had sent it (starts polling if it is busy). */
  set(target: Position, status: AnalysisStatus | null): void {
    const e = this.entry(target);
    e.status.set(status);
    void this.poll(e);
  }

  private entry(target: Position): Entry {
    const key = targetQuery(target);
    let e = this.entries.get(key);
    if (!e) {
      const status = signal<AnalysisStatus | null>(null);
      const rate = signal<number | null>(null);
      const remainingS = computed(() => {
        const pr = status()?.progress;
        if (!busy(status()) || !pr || pr.total <= 0) return null;
        return (pr.total - pr.done) / (rate() ?? FALLBACK_IMAGES_PER_S);
      });
      e = { target, status, rate, remainingS, samples: [], polling: false, sent: 0, applied: 0 };
      this.entries.set(key, e);
    }
    return e;
  }

  private async request(target: Position, start: boolean): Promise<AnalysisStatus> {
    const e = this.entry(target);
    const n = ++e.sent;
    const s = await (start ? this.api.start(e.target) : this.api.status(e.target));
    this.apply(e, n, s);
    return s;
  }

  private apply(e: Entry, n: number, s: AnalysisStatus): void {
    if (n < e.applied) return; // a later request was already answered: this one is out of date
    e.applied = n;
    e.status.set(s);
    this.measureRate(e, s);
    void this.poll(e);
  }

  /** The rate is measured from the progress of every answer while the computation runs; a new run starts afresh. */
  private measureRate(e: Entry, s: AnalysisStatus): void {
    const pr = s.progress;
    const last = e.samples[e.samples.length - 1];
    if (!busy(s) || !pr || pr.total <= 0 || (last && pr.done < last.done)) {
      e.samples = [];
      e.rate.set(null);
      if (!busy(s) || !pr || pr.total <= 0) return;
    }
    e.samples.push({ t: Date.now() / 1000, done: pr.done });
    const first = e.samples[0];
    const dt = e.samples[e.samples.length - 1].t - first.t;
    if (dt >= 60 && pr.done > first.done) e.rate.set((pr.done - first.done) / dt);
  }

  /** One loop per target, as long as it is busy. A missed poll is retried. */
  private async poll(e: Entry): Promise<void> {
    if (e.polling || !busy(e.status())) return;
    e.polling = true;
    try {
      while (busy(e.status())) {
        await sleep(POLL_MS);
        const n = ++e.sent;
        try {
          this.apply(e, n, await this.api.status(e.target));
        } catch {
          /* a missed poll is retried */
        }
      }
    } finally {
      e.polling = false;
    }
  }
}
