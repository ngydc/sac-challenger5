import { Injectable, signal } from '@angular/core';
import { API_BASE_URL } from '../api.config';
import { Coverage, Frame, ImageOptions, Picture, ResolveResponse, Target } from '../models/api.models';

/** An error answer of the backend: `{"error": {"code", "message"}}` (docs/API.md section 6). */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError';

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('aborted', 'AbortError'));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      reject(new DOMException('aborted', 'AbortError'));
    });
  });

async function toApiError(r: Response): Promise<ApiError> {
  try {
    const body = await r.json();
    return new ApiError(r.status, body?.error?.code ?? 'http_error', body?.error?.message ?? r.statusText);
  } catch {
    return new ApiError(r.status, 'http_error', `The backend answered ${r.status} ${r.statusText}.`);
  }
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw await toApiError(r);
  return r.json();
}

/** The six target parameters plus extras; null values are left out (motion: all three or none). */
export function targetQuery(t: Target, extra: Record<string, string | number | boolean | undefined> = {}) {
  const p = new URLSearchParams();
  const all = { ra: t.ra, dec: t.dec, fov: t.fov, pmra: t.pmra, pmdec: t.pmdec, pm_epoch: t.pm_epoch, ...extra };
  for (const [k, v] of Object.entries(all)) if (v !== null && v !== undefined) p.set(k, String(v));
  return p.toString();
}

/**
 * All backend calls. Uses fetch (not HttpClient) because the image endpoint needs the response
 * headers, the 202 retry loop and AbortController cancellation, exactly as in docs/API.md section 5.
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  /** Loaded pictures by URL. PNGs are tiny (47 px), so the whole session is kept in memory. */
  private readonly pictures = new Map<string, Picture>();
  /** Running image requests per frame id (one frame can be requested with several stretches at once). */
  private readonly inflight = new Map<string, number>();

  /** Ids of the frames that were loaded in this session: the backend has their data now. */
  readonly loaded = signal<ReadonlySet<string>>(new Set());
  /** Ids of the frames that are being loaded right now. */
  readonly pending = signal<ReadonlySet<string>>(new Set());

  resolve(q: string, signal?: AbortSignal): Promise<ResolveResponse> {
    return fetch(`${API_BASE_URL}/resolve?${new URLSearchParams({ q })}`, { signal }).then((r) =>
      json<ResolveResponse>(r),
    );
  }

  /** Polls /coverage every 1.5 s until `ready`; `error` is retried by the backend, so keep polling. */
  async loadCoverage(t: Target, onUpdate: (c: Coverage) => void, signal?: AbortSignal): Promise<Coverage> {
    for (;;) {
      const c = await fetch(`${API_BASE_URL}/coverage?${targetQuery(t)}`, { signal }).then((r) =>
        json<Coverage>(r),
      );
      onUpdate(c);
      if (c.state === 'ready') return c;
      await sleep(1500, signal);
    }
  }

  /** One /coverage call, to refresh the cache state of the frames of a target that is already shown. */
  coverage(t: Target, signal?: AbortSignal): Promise<Coverage> {
    return fetch(`${API_BASE_URL}/coverage?${targetQuery(t)}`, { signal }).then((r) => json<Coverage>(r));
  }

  imageUrl(t: Target, f: Frame, o: ImageOptions = {}): string {
    const fixed = o.vmin !== undefined && o.vmax !== undefined ? { vmin: o.vmin, vmax: o.vmax } : {};
    const qs = targetQuery(t, { mask: o.mask ?? true, ...fixed });
    return `${API_BASE_URL}/frames/${encodeURIComponent(f.id)}/image.png?${qs}`;
  }

  cached(t: Target, f: Frame, o: ImageOptions = {}): Picture | undefined {
    return this.pictures.get(this.imageUrl(t, f, o));
  }

  /** Loads one frame; retries on 202 (still downloading from IRSA) after `Retry-After`. */
  async loadFrame(t: Target, f: Frame, o: ImageOptions = {}, signal?: AbortSignal): Promise<Picture> {
    const url = this.imageUrl(t, f, o);
    const hit = this.pictures.get(url);
    if (hit) return hit;
    this.track(f.id, 1);
    try {
      return await this.fetchFrame(url, f, signal);
    } finally {
      this.track(f.id, -1);
    }
  }

  private async fetchFrame(url: string, f: Frame, signal?: AbortSignal): Promise<Picture> {
    for (;;) {
      const r = await fetch(`${url}&wait=20`, { signal });
      if (r.status === 202) {
        await sleep((Number(r.headers.get('Retry-After')) || 3) * 1000, signal);
        continue;
      }
      if (!r.ok) throw await toApiError(r);
      const h = r.headers;
      const pic: Picture = {
        frameId: f.id,
        url: URL.createObjectURL(await r.blob()),
        wavelength: Number(h.get('X-Wavelength-Um') ?? f.wavelength_um),
        bandwidth: Number(h.get('X-Bandwidth-Um') ?? f.bandwidth_um),
        time: h.get('X-Time-Utc') ?? f.time,
        flags: (h.get('X-Flags-At-Target') ?? '').split(',').filter(Boolean),
        target: { x: Number(h.get('X-Target-X')), y: Number(h.get('X-Target-Y')) },
        size: Number(h.get('X-Image-Size')),
        stretch: [Number(h.get('X-Stretch-Min')), Number(h.get('X-Stretch-Max'))],
      };
      this.pictures.set(url, pic);
      if (!this.loaded().has(f.id)) this.loaded.update((s) => new Set(s).add(f.id));
      return pic;
    }
  }

  private track(id: string, d: 1 | -1): void {
    const n = (this.inflight.get(id) ?? 0) + d;
    if (n > 0) this.inflight.set(id, n);
    else this.inflight.delete(id);
    if (this.pending().has(id) !== n > 0) this.pending.set(new Set(this.inflight.keys()));
  }

  /** Frees all pictures (call when the target changes). */
  clearPictures(): void {
    for (const p of this.pictures.values()) URL.revokeObjectURL(p.url);
    this.pictures.clear();
    this.loaded.set(new Set());
  }
}
