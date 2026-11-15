import { Injectable, Signal, WritableSignal, inject, signal } from '@angular/core';
import { EpochsApi } from './epochs-api.service';
import { targetQuery } from './api.service';
import { AnalysisStatus, Position } from '../models/epochs.models';

/** How often a queued or running computation is asked for its state. */
export const POLL_MS = 4000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Queued, being computed, or a complete result being recomputed with new images. */
export const busy = (s: AnalysisStatus | null | undefined): boolean =>
  !!s && (s.state === 'queued' || s.state === 'running' || s.refreshing);

interface Entry {
  readonly target: Position;
  readonly status: WritableSignal<AnalysisStatus | null>;
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
      e = { target, status: signal<AnalysisStatus | null>(null), polling: false, sent: 0, applied: 0 };
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
    void this.poll(e);
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
