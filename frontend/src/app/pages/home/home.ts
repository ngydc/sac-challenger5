import { Component, HostListener, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ViewerState } from '../../core/services/viewer-state.service';
import { Viewer } from '../../components/viewer/viewer';
import { SearchBar } from '../../components/search-bar/search-bar';
import { ControlPanel } from '../../components/control-panel/control-panel';
import { HistoryPanel } from '../../components/history-panel/history-panel';
import { AboutPanel } from '../../components/about-panel/about-panel';
import { Logo } from '../../components/logo/logo';

type TabId = 'controls' | 'history' | 'about';

/** The menu's tabs, in the order of their buttons (top to bottom). `icon` is an SVG path (24 px grid). */
const TABS: readonly { id: TabId; label: string; icon: string }[] = [
  { id: 'about', label: 'About SPHEREx', icon: 'M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18zM12 11v6M12 7.5v.5' },
  { id: 'history', label: 'History', icon: 'M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 7v5l3 2' },
  {
    id: 'controls',
    label: 'Controls',
    icon: 'M4 7h10M18 7h2M4 17h4M12 17h8M14 7a2 2 0 1 0 4 0a2 2 0 1 0-4 0M8 17a2 2 0 1 0 4 0a2 2 0 1 0-4 0',
  },
];

/** Main page: the full-screen viewer, the brand/home button, the search bar, a small HUD and the menu with its tabs. */
@Component({
  selector: 'app-home',
  imports: [Viewer, SearchBar, ControlPanel, HistoryPanel, AboutPanel, Logo, DatePipe, DecimalPipe],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class Home implements OnInit {
  protected readonly s = inject(ViewerState);
  protected readonly tabs = TABS;
  protected readonly menuOpen = signal(false);
  protected readonly tab = signal<TabId>('controls');
  protected readonly current = computed(() => TABS.find((t) => t.id === this.tab())!);

  ngOnInit(): void {
    this.s.initFromUrl();
  }

  /** The brand button: back to the start page. */
  protected goHome(): void {
    this.s.reset();
    if (this.tab() === 'controls') this.menuOpen.set(false);
  }

  /** Opens the menu on tab `id`; pressing the button of the open tab closes the menu. */
  protected toggleTab(id: TabId): void {
    if (this.menuOpen() && this.tab() === id) return this.menuOpen.set(false);
    this.tab.set(id);
    this.menuOpen.set(true);
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
