import { Component, effect, inject, signal } from '@angular/core';
import { ViewerState } from '../../core/services/viewer-state.service';

/** F4: one search box for object names and coordinates (sent on submit, not on every key). */
@Component({
  selector: 'app-search-bar',
  templateUrl: './search-bar.html',
  styleUrl: './search-bar.scss',
})
export class SearchBar {
  protected readonly s = inject(ViewerState);
  protected readonly text = signal('');

  constructor() {
    // Show what was searched (e.g. when it came from the page URL or an example button).
    effect(() => this.text.set(this.s.query()));
  }

  protected submit(e: Event): void {
    e.preventDefault();
    this.s.search(this.text());
  }
}
