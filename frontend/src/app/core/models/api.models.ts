/**
 * Response types of the backend API (docs/API.md, backend/app/api.py).
 * Can be regenerated from the live schema:
 *   npx openapi-typescript http://localhost:8000/openapi.json -o src/app/core/models/api.types.ts
 */

/** Where to look. Sent unchanged with every coverage and image request. */
export interface Target {
  ra: number;
  dec: number;
  fov: number;
  pmra: number | null;
  pmdec: number | null;
  pm_epoch: number | null;
}

export interface ResolvedTarget extends Target {
  name: string | null;
  note: string | null;
}

export interface ResolveResponse {
  query: string;
  kind: 'coordinates' | 'preset' | 'name';
  target: ResolvedTarget;
  warnings: string[];
}

export type FrameCache = 'ready' | 'fetching' | 'queued' | 'failed' | 'outside' | 'missing';

export interface Frame {
  id: string;
  visit: number;
  detector: string;
  wavelength_um: number;
  bandwidth_um: number;
  time: string;
  release: string;
  cache: FrameCache;
}

export interface Visit {
  index: number;
  start: string;
  end: string;
  n_frames: number;
  target: { ra: number; dec: number } | null;
}

export interface Grid {
  width: number;
  height: number;
  pixel_scale_arcsec: number;
  center_ra: number;
  center_dec: number;
  orientation: string;
}

export interface Coverage {
  target: Target;
  state: 'searching' | 'locating' | 'ready' | 'error';
  message: string | null;
  progress: { located: number; total: number };
  grid: Grid;
  visits: Visit[];
  wavelength_range_um: [number, number] | null;
  frames: Frame[];
}

/** One loaded frame image plus the metadata from its response headers. */
export interface Picture {
  frameId: string;
  /** Object URL of the PNG blob. */
  url: string;
  wavelength: number;
  bandwidth: number;
  time: string;
  flags: string[];
  /** Predicted target position in pixels: x from the left, y from the bottom (row 0 = south). */
  target: { x: number; y: number };
  size: number;
  stretch: [number, number];
}

export interface ImageOptions {
  vmin?: number;
  vmax?: number;
  mask?: boolean;
}
