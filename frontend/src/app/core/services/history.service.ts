import { Injectable, computed, signal } from '@angular/core';

export interface HistoryEntry {
  /** What the user typed (and what is searched again on click). */
  query: string;
  /** Name the backend resolved it to, if any. */
  name: string | null;
  ra: number;
  dec: number;
  /** When it was last searched (ms since 1970). */
  at: number;
}

const KEY = 'challenger5.history';
const MAX = 50;

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/**
 * The user's successful searches, newest first, kept in this browser (localStorage).
 * Searching the same thing again moves it to the top instead of adding a duplicate.
 */
@Injectable({ providedIn: 'root' })
export class HistoryService {
  readonly entries = signal<HistoryEntry[]>(read());
  /** The three newest, for the search box. */
  readonly recent = computed(() => this.entries().slice(0, 3));

  add(e: Omit<HistoryEntry, 'at'>, at = Date.now()): void {
    this.save([{ ...e, at }, ...this.entries().filter((x) => !same(x.query, e.query))].slice(0, MAX));
  }

  remove(query: string): void {
    this.save(this.entries().filter((x) => !same(x.query, query)));
  }

  clear(): void {
    this.save([]);
  }

  private save(list: HistoryEntry[]): void {
    this.entries.set(list);
    try {
      localStorage.setItem(KEY, JSON.stringify(list));
    } catch {
      // Storage blocked or full: the history still works for this session.
    }
  }
}

function read(): HistoryEntry[] {
  try {
    const list: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    if (!Array.isArray(list)) return [];
    return list.filter((e) => typeof e?.query === 'string' && typeof e?.at === 'number').slice(0, MAX);
  } catch {
    return [];
  }
}
