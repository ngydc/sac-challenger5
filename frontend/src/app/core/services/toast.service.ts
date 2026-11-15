import { Injectable, signal } from '@angular/core';

export interface Toast {
  id: number;
  title: string;
  text: string;
  /** An optional button, e.g. to undo what the toast reports. */
  action?: { label: string; run: () => void };
}

/** A short message that explains something the page did on its own. One at a time; a new one replaces the old. */
@Injectable({ providedIn: 'root' })
export class ToastService {
  readonly current = signal<Toast | null>(null);
  private timer?: ReturnType<typeof setTimeout>;
  private n = 0;

  show(t: Omit<Toast, 'id'>, ms = 10000): void {
    clearTimeout(this.timer);
    const toast = { ...t, id: ++this.n };
    this.current.set(toast);
    this.timer = setTimeout(() => this.dismiss(toast.id), ms);
  }

  /** Closes the toast (only toast `id`, if given, so a late timer cannot close a newer one). */
  dismiss(id?: number): void {
    if (id !== undefined && this.current()?.id !== id) return;
    clearTimeout(this.timer);
    this.current.set(null);
  }
}
