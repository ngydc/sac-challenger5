import { Injectable } from '@angular/core';
import { API_BASE_URL } from '../api.config';
import { AnalysisStatus, Position, Spectrum } from '../models/epochs.models';
import { ApiError, targetQuery } from './api.service';

async function json<T>(r: Response): Promise<T> {
  if (r.ok) return r.json();
  let code = 'http_error';
  let message = `The server answered ${r.status} ${r.statusText}.`;
  try {
    const body = await r.json();
    code = body?.error?.code ?? code;
    message = body?.error?.message ?? message;
  } catch {
    /* not JSON */
  }
  throw new ApiError(r.status, code, message);
}

/**
 * All calls of the deep-analysis API (docs/API_ANALYSIS.md). They take the same target as the viewer
 * (position, field of view and proper motion), so both look at the same view and share the backend's data.
 */
@Injectable({ providedIn: 'root' })
export class EpochsApi {
  /** State and result. Starts nothing. */
  status(p: Position, signal?: AbortSignal): Promise<AnalysisStatus> {
    return fetch(`${API_BASE_URL}/analysis?${targetQuery(p, { start: false })}`, {
      signal,
      cache: 'no-store',
    }).then((r) => json<AnalysisStatus>(r));
  }

  /** Starts the analysis if needed (nothing happens if it is complete or already running) and reports it. */
  start(p: Position): Promise<AnalysisStatus> {
    return fetch(`${API_BASE_URL}/analysis?${targetQuery(p)}`, { cache: 'no-store' }).then((r) =>
      json<AnalysisStatus>(r),
    );
  }

  /**
   * Spectrum of one pixel. `yFromTop` is the picture row from the top (as clicked); the API counts rows
   * from the bottom (south), like the viewer's X-Target-Y, so it is converted here.
   */
  spectrum(p: Position, x: number, yFromTop: number, height: number, signal?: AbortSignal): Promise<Spectrum> {
    const y = height - 1 - yFromTop;
    return fetch(`${API_BASE_URL}/analysis/spectrum?${targetQuery(p, { x, y })}`, { signal }).then((r) =>
      json<Spectrum>(r),
    );
  }

  /**
   * `v` (e.g. the result's images_key) changes the URL when the analysis was recomputed, so the page loads the
   * new picture; the backend ignores it and revalidates pictures with an ETag.
   */
  diffUrl(p: Position, bundle: string, v = ''): string {
    return `${API_BASE_URL}/analysis/${encodeURIComponent(bundle)}/diff.png?${targetQuery(p, { v: v || undefined })}`;
  }
}
