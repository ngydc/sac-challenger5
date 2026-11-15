import { Component, inject } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ViewerState } from '../../core/services/viewer-state.service';
import { HistoryService } from '../../core/services/history.service';

/** "5 min ago" for recent times, the date for older ones. */
export function ago(at: number, now = Date.now()): string {
  const min = Math.floor((now - at) / 60_000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min} min ago`;
  if (min < 24 * 60) return `${Math.floor(min / 60)} h ago`;
  if (min < 7 * 24 * 60) return `${Math.floor(min / (24 * 60))} d ago`;
  return new Date(at).toISOString().slice(0, 10);
}

/** The History tab of the menu: every past search of this browser, newest first; click to run it again. */
@Component({
  selector: 'app-history-panel',
  imports: [DecimalPipe],
  templateUrl: './history-panel.html',
  styleUrl: './history-panel.scss',
})
export class HistoryPanel {
  protected readonly s = inject(ViewerState);
  protected readonly history = inject(HistoryService);
  protected readonly ago = ago;
}
