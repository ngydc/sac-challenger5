import { Component, input } from '@angular/core';

let nextId = 0;

/**
 * The CHALLENGER5 mark: a "5" inside a tilted orbit with one satellite.
 * With `spin` it is the app's loading indicator (the orbit turns around the 5).
 * The same drawing is in public/favicon.svg; change both together.
 */
@Component({
  selector: 'app-logo',
  template: `
    <svg viewBox="0 0 48 48" [attr.width]="size()" [attr.height]="size()" [class.spin]="spin()" aria-hidden="true">
      <defs>
        <linearGradient [attr.id]="id" x1="4" y1="6" x2="44" y2="42" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#4fd8ff" />
          <stop offset=".55" stop-color="#8b9bff" />
          <stop offset="1" stop-color="#c084fc" />
        </linearGradient>
      </defs>
      <g class="orbit">
        <ellipse cx="24" cy="24" rx="21" ry="8.5" transform="rotate(-28 24 24)" fill="none" [attr.stroke]="'url(#' + id + ')'" stroke-width="1.8" />
        <circle cx="42.5" cy="14.1" r="2.6" fill="#fff" />
      </g>
      <path class="five back" [attr.d]="five" />
      <path class="five" [attr.d]="five" />
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
      filter: drop-shadow(0 0 6px rgb(139 155 255 / 0.45));
    }
    .five {
      fill: none;
      stroke: #fff;
      stroke-width: 3.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    /* A dark outline, so the orbit seems to pass behind the 5. */
    .back {
      stroke: var(--bg);
      stroke-width: 8;
    }
    .orbit {
      transform-origin: 24px 24px;
    }
    .spin .orbit {
      animation: c5-orbit 1.5s cubic-bezier(0.55, 0.15, 0.45, 0.85) infinite;
    }
    .spin .five:not(.back) {
      animation: c5-pulse 1.5s ease-in-out infinite;
    }
    @keyframes c5-orbit {
      to {
        transform: rotate(360deg);
      }
    }
    @keyframes c5-pulse {
      50% {
        opacity: 0.55;
      }
    }
  `,
})
export class Logo {
  readonly size = input(32);
  readonly spin = input(false);

  protected readonly id = `c5-grad-${nextId++}`;
  protected readonly five =
    'M30.5 13.5H20.2l-1.5 10c1.9-1.3 3.9-1.9 5.9-1.9 4.7 0 7.4 3 7.4 6.6 0 4-3.1 6.6-7.5 6.6-3.1 0-5.6-1.2-7.2-3.3';
}
