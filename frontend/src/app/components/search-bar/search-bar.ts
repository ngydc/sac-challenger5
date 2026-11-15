import { Component, ElementRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { ViewerState } from '../../core/services/viewer-state.service';
import { HistoryService } from '../../core/services/history.service';
import { EXAMPLES } from '../../core/examples';
import { Logo } from '../logo/logo';

interface Suggestion {
  query: string;
  recent: boolean;
  /** True for the first entry of its group (it gets the group heading). */
  first: boolean;
}

/**
 * F4: one search box for object names and coordinates (sent on submit, not on every key).
 * While it has the focus it offers the last three searches and the five example targets.
 */
@Component({
  selector: 'app-search-bar',
  imports: [Logo],
  templateUrl: './search-bar.html',
  styleUrl: './search-bar.scss',
})
export class SearchBar {
  protected readonly s = inject(ViewerState);
  private readonly history = inject(HistoryService);
  private readonly input = viewChild.required<ElementRef<HTMLInputElement>>('q');

  protected readonly text = signal('');
  protected readonly open = signal(false);
  /** Suggestion marked with the arrow keys; -1 = none (Enter then searches the typed text). */
  protected readonly marked = signal(-1);

  protected readonly suggestions = computed<Suggestion[]>(() => [
    ...this.history.recent().map((e, i) => ({ query: e.query, recent: true, first: i === 0 })),
    ...EXAMPLES.map((e, i) => ({ query: e.name, recent: false, first: i === 0 })),
  ]);

  constructor() {
    // Show what was searched (e.g. when it came from the page URL or an example button).
    effect(() => this.text.set(this.s.query()));
  }

  protected submit(e: Event): void {
    e.preventDefault();
    const pick = this.suggestions()[this.marked()];
    this.run(pick ? pick.query : this.text());
  }

  protected run(q: string): void {
    if (!q.trim()) return;
    this.text.set(q);
    this.close();
    this.input().nativeElement.blur();
    this.s.search(q);
  }

  protected show(): void {
    this.open.set(true);
  }

  protected close(): void {
    this.open.set(false);
    this.marked.set(-1);
  }

  /** Closes the list when the focus leaves the search box (not when it moves inside it). */
  protected onFocusOut(e: FocusEvent): void {
    const form = e.currentTarget as HTMLElement;
    if (!form.contains(e.relatedTarget as Node | null)) this.close();
  }

  protected onKey(e: KeyboardEvent): void {
    const n = this.suggestions().length;
    if (e.key === 'Escape') {
      if (this.open()) e.stopPropagation();
      this.close();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!this.open()) return this.show();
      const d = e.key === 'ArrowDown' ? 1 : -1;
      // Cycles through -1 (the typed text) and the n suggestions.
      this.marked.update((i) => ((i + 1 + d + n + 1) % (n + 1)) - 1);
    }
  }
}
