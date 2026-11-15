import { Injectable } from '@angular/core';
import { API_BASE_URL } from '../api.config';
import { EpochsConfig, EpochsStatus, Position, Spectrum } from '../models/epochs.models';
import { ResolveResponse } from '../models/api.models';
import { ApiError } from './api.service';

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

const pos = (p: Position, extra: Record<string, string | number> = {}) =>
  new URLSearchParams(
    Object.entries({ ra: p.ra, dec: p.dec, fov: p.fov, ...extra }).map(([k, v]) => [k, String(v)]),
  ).toString();

/** All calls of the epoch-maps API (docs/API_EPOCHS.md). Only `compute` makes the backend talk to IRSA. */
@Injectable({ providedIn: 'root' })
export class EpochsApi {
  config(): Promise<EpochsConfig> {
    return fetch(`${API_BASE_URL}/config`).then((r) => json<EpochsConfig>(r));
  }

  /** Turns "RA Dec" (sexagesimal or decimal) or a name into decimal degrees. */
  resolve(q: string, signal?: AbortSignal): Promise<ResolveResponse> {
    return fetch(`${API_BASE_URL}/resolve?${new URLSearchParams({ q })}`, { signal }).then((r) =>
      json<ResolveResponse>(r),
    );
  }

  /** Status and metadata. Never starts a computation. */
  status(p: Position, signal?: AbortSignal): Promise<EpochsStatus> {
    return fetch(`${API_BASE_URL}/epochs?${pos(p)}`, { signal, cache: 'no-store' }).then((r) =>
      json<EpochsStatus>(r),
    );
  }

  /** Starts the computation (202). Does nothing on the backend if it is already running or cached. */
  compute(p: Position): Promise<EpochsStatus> {
    return fetch(`${API_BASE_URL}/compute?${pos(p)}`, { method: 'POST' }).then((r) =>
      json<EpochsStatus>(r),
    );
  }

  spectrum(p: Position, x: number, y: number, signal?: AbortSignal): Promise<Spectrum> {
    return fetch(`${API_BASE_URL}/spectrum?${pos(p, { x, y })}`, { signal }).then((r) =>
      json<Spectrum>(r),
    );
  }

  diffUrl(p: Position, bundle: string, v = ''): string {
    return `${API_BASE_URL}/diff?${pos(p, { bundle, v })}`;
  }
}
