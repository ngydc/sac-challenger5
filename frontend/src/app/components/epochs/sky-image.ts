import { Component, computed, effect, input, output, signal } from '@angular/core';

/**
 * One backend picture, drawn pixel-sharp on a hatched background: transparent pixels (no data) show the
 * hatching, never black. With `pickable`, a click reports the PNG pixel at scale 1 (x from the left,
 * y from the top), which is what GET /api/spectrum expects.
 */
@Component({
  selector: 'app-sky-image',
  template: `
    <div
      class="sky hatch"
      [class.pickable]="pickable()"
      [style.aspect-ratio]="width() + ' / ' + height()"
      (click)="onClick($event)"
    >
      @if (src(); as s) {
        <img
          [src]="s"
          [alt]="alt()"
          draggable="false"
          (load)="loaded.set(true); failed.set(false)"
          (error)="failed.set(true)"
        />
      }
      @if (!loaded() && !failed()) {
        <span class="spinner" aria-hidden="true"></span>
      }
      @if (failed()) {
        <p class="fail">This picture could not be loaded.</p>
      }
      @if (markerPos(); as m) {
        <span
          class="marker"
          [style.left.%]="m.left"
          [style.top.%]="m.top"
          aria-hidden="true"
        ></span>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .sky {
      position: relative;
      width: 100%;
      overflow: hidden;
      border-radius: 6px;
    }
    .pickable {
      cursor: crosshair;
    }
    img {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      image-rendering: pixelated;
      user-select: none;
    }
    .spinner {
      position: absolute;
      top: calc(50% - 9px);
      left: calc(50% - 9px);
    }
    .fail {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      margin: 0;
      padding: 1rem;
      text-align: center;
      font-size: 0.85rem;
      color: var(--muted);
    }
    .marker {
      position: absolute;
      width: 18px;
      height: 18px;
      margin: -9px 0 0 -9px;
      border: 2px solid #ffe14d;
      border-radius: 50%;
      box-shadow: 0 0 0 1px #000;
      pointer-events: none;
    }
  `,
})
export class SkyImage {
  readonly src = input<string | null>(null);
  readonly alt = input('');
  readonly width = input(47);
  readonly height = input(47);
  readonly pickable = input(false);
  readonly marker = input<{ x: number; y: number } | null>(null);
  readonly picked = output<{ x: number; y: number }>();

  protected readonly loaded = signal(false);
  protected readonly failed = signal(false);
  protected readonly markerPos = computed(() => {
    const m = this.marker();
    return (
      m && { left: ((m.x + 0.5) / this.width()) * 100, top: ((m.y + 0.5) / this.height()) * 100 }
    );
  });

  constructor() {
    // A new picture (other position or bundle) shows the spinner until it has loaded. Blinking between
    // preloaded frames keeps the old picture visible instead, so it does not flicker.
    let first = true;
    effect(() => {
      this.src();
      if (first) {
        first = false;
        return;
      }
      this.failed.set(false);
    });
  }

  protected onClick(e: MouseEvent): void {
    if (!this.pickable()) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * this.width());
    const y = Math.floor(((e.clientY - r.top) / r.height) * this.height());
    if (x >= 0 && y >= 0 && x < this.width() && y < this.height()) this.picked.emit({ x, y });
  }
}
