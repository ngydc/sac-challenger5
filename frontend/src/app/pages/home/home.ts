import { Component, HostListener, OnInit, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ViewerState } from '../../core/services/viewer-state.service';
import { Viewer } from '../../components/viewer/viewer';
import { SearchBar } from '../../components/search-bar/search-bar';
import { ControlPanel } from '../../components/control-panel/control-panel';

/** Main page: the full-screen viewer, a floating search bar, a small HUD and the collapsible menu. */
@Component({
  selector: 'app-home',
  imports: [Viewer, SearchBar, ControlPanel, DatePipe, DecimalPipe],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class Home implements OnInit {
  protected readonly s = inject(ViewerState);
  protected readonly menuOpen = signal(false);

  ngOnInit(): void {
    this.s.initFromUrl();
  }

  protected toggleFullscreen(): void {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen?.();
  }

  /** ← → season, ↑ ↓ next image in the season, space blink, M menu, Esc close menu. */
  @HostListener('document:keydown', ['$event'])
  protected onKey(e: KeyboardEvent): void {
    const el = e.target as HTMLElement;
    if (e.ctrlKey || e.metaKey || e.altKey || el.closest('input, select, textarea')) return;
    if (e.key === ' ' && el.closest('button')) return; // let space press the focused button
    const ready = this.s.phase() === 'ready';
    switch (e.key) {
      case 'ArrowLeft':
      case 'ArrowRight':
        if (!ready) return;
        this.s.stop();
        this.s.stepVisit(e.key === 'ArrowLeft' ? -1 : 1);
        break;
      case 'ArrowUp':
      case 'ArrowDown':
        if (!ready) return;
        this.s.stop();
        this.s.stepFrame(e.key === 'ArrowDown' ? -1 : 1);
        break;
      case ' ':
        if (!ready) return;
        this.s.toggle('time');
        break;
      case 'm':
      case 'M':
        this.menuOpen.update((v) => !v);
        break;
      case 'Escape':
        this.menuOpen.set(false);
        break;
      default:
        return;
    }
    e.preventDefault();
  }
}
