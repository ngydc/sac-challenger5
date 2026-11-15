import { Component, input } from '@angular/core';

/**
 * The CHALLENGER5 mark: one object seen at three epochs (violet, blue, then white with a ring) along its
 * track, between two fixed background stars. That is what the blink viewer reveals: what moves.
 * With `spin` it is the app's loading indicator (the three positions light up one after the other).
 * The same drawing, on a dark tile, is in public/favicon.svg (and the PNGs rendered from it, see src/index.html); change them together.
 */
@Component({
  selector: 'app-logo',
  template: `
    <svg viewBox="0 0 48 48" [attr.width]="size()" [attr.height]="size()" [class.spin]="spin()" aria-hidden="true">
      <circle cx="10" cy="12" r="2" fill="#7d8296" />
      <circle cx="39" cy="39" r="2" fill="#7d8296" />
      <path d="M12 37L33 16" stroke="#3b7cf0" stroke-opacity=".55" stroke-width="4.5" stroke-linecap="round" />
      <circle class="p p1" cx="12" cy="37" r="5" fill="#7c5cff" />
      <circle class="p p2" cx="22" cy="27" r="5.5" fill="#3fa2ff" />
      <circle class="p p3" cx="33" cy="16" r="9.5" fill="none" stroke="#1f5c58" stroke-width="3.5" />
      <circle class="p p3" cx="33" cy="16" r="7" fill="#fff" />
    </svg>
  `,
  styles: `
    :host {
      display: inline-flex;
      flex: none;
    }
    svg {
      display: block;
      overflow: visible;
    }
    .spin .p {
      animation: c5-blink 1.2s ease-in-out infinite;
    }
    .spin .p2 {
      animation-delay: 0.2s;
    }
    .spin .p3 {
      animation-delay: 0.4s;
    }
    @keyframes c5-blink {
      0%,
      100% {
        opacity: 0.3;
      }
      30% {
        opacity: 1;
      }
    }
  `,
})
export class Logo {
  readonly size = input(32);
  readonly spin = input(false);
}
