import { Component, inject } from '@angular/core';
import { ToastService } from '../../core/services/toast.service';

/** Shows ToastService's current message at the top of the page, below the search bar. */
@Component({
  selector: 'app-toast',
  template: `
    <div class="region" role="status" aria-live="polite">
      @if (toasts.current(); as t) {
        <div class="toast glass">
          <div class="body">
            <strong>{{ t.title }}</strong>
            <p>{{ t.text }}</p>
          </div>
          <div class="btns">
            @if (t.action; as a) {
              <button type="button" class="btn" (click)="a.run(); toasts.dismiss(t.id)">{{ a.label }}</button>
            }
            <button type="button" class="btn icon ghost" aria-label="Close the message" (click)="toasts.dismiss(t.id)">✕</button>
          </div>
        </div>
      }
    </div>
  `,
  styles: `
    .region {
      position: fixed;
      top: 76px;
      left: 50%;
      z-index: 50;
      width: min(460px, calc(100% - 32px));
      transform: translateX(-50%);
      pointer-events: none;
    }
    .toast {
      display: flex;
      align-items: flex-start;
      gap: 0.75rem;
      padding: 0.8rem 0.9rem;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius);
      background: var(--overlay);
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
      pointer-events: auto;
      animation: drop 0.25s ease-out both;
    }
    .body {
      flex: 1;
      min-width: 0;

      strong {
        font-family: var(--font-display);
      }
      p {
        margin: 0.25rem 0 0;
        font-size: 0.85rem;
        line-height: 1.45;
        color: var(--muted);
      }
    }
    .btns {
      display: flex;
      flex: none;
      align-items: center;
      gap: 0.3rem;
    }
    @keyframes drop {
      from {
        opacity: 0;
        transform: translateY(-8px);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .toast {
        animation: none;
      }
    }
  `,
})
export class ToastHost {
  protected readonly toasts = inject(ToastService);
}
