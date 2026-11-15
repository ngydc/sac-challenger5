import { Component, HostListener, OnInit, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ViewerState } from '../../core/services/viewer-state.service';
import { Viewer } from '../../components/viewer/viewer';
import { SearchBar } from '../../components/search-bar/search-bar';
import { ControlPanel } from '../../components/control-panel/control-panel';
import { EpochsStore } from '../../core/services/epochs-store.service';
import { DeepPanel } from '../../components/epochs/deep-panel';
import { DeepStage } from '../../components/epochs/deep-stage';
import { BundleDetail } from '../../components/epochs/bundle-detail';

/** Main page: the full-screen viewer, a floating search bar, a small HUD and the collapsible menu. */
@Component({
  selector: 'app-home',
  imports: [Viewer, SearchBar, ControlPanel, DeepPanel, DeepStage, BundleDetail, DatePipe, DecimalPipe],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class Home implements OnInit {
  protected readonly s = inject(ViewerState);
  protected readonly menuOpen = signal(false);
  /** Deep Analysis: its own drawer; while open, the stage shows the difference pictures. */
  protected readonly deep = inject(EpochsStore);

  ngOnInit(): void {
    this.s.initFromUrl();
  }

  /** Only one drawer is open at a time. */
  protected toggleMenu(): void {
    const open = !this.menuOpen();
    this.menuOpen.set(open);
    if (open) this.deep.toggle(false);
  }

  protected toggleDeep(): void {
    const open = !this.deep.open();
    this.deep.toggle(open);
    if (open) {
      this.menuOpen.set(false);
      this.s.stop();
    }
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
    // While Deep Analysis is open the slider picture is hidden, so its keys do nothing.
    const ready = this.s.phase() === 'ready' && !this.deep.open();
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
        this.toggleMenu();
        break;
      case 'Escape':
        this.menuOpen.set(false);
        this.deep.toggle(false);
        break;
      default:
        return;
    }
    e.preventDefault();
  }
}
