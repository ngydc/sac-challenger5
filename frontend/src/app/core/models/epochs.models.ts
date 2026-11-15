/**
 * Response types of the epoch-maps API (docs/API_EPOCHS.md, backend/app/epochs_api.py, backend/app/epochs.py).
 * Only fields the frontend reads are typed; field names are exactly the backend's.
 */

export interface EpochsConfig {
  default_fov: number;
  fov_min: number;
  fov_max: number;
}

export type EpochsStatusKind = 'cached' | 'not_computed' | 'running' | 'error';
export type BundleMode = 'three_epochs' | 'two_epochs' | 'one_epoch' | 'no_data';

export interface Progress {
  stage: string;
  done: number;
  total: number;
  bundles_ready: string[];
}

export interface EpochsStatus {
  status: EpochsStatusKind;
  progress: Progress | null;
  message: string | null;
  default_fov: number;
  target: { ra: number; dec: number; fov: number };
  cache: string;
  result: EpochsResult | null;
}

export interface Epoch {
  index: number;
  start: string;
  end: string;
  time: string;
  n_images: number;
}

export interface EpochsResult {
  complete: boolean;
  grid: { width: number; height: number; pixel_scale_arcsec: number; orientation: string };
  epochs: Epoch[];
  bundles: Bundle[];
  collections: string[];
  searched_at: string;
  n_images: number;
  failed: { reason: string }[];
  failed_retryable: number;
}

export interface RgbChoice {
  epoch: number;
  time: string;
  start: string;
  end: string;
}

export interface BundleEpoch {
  index: number;
  usable: boolean;
  n_images: number;
  start: string | null;
  end: string | null;
  time: string | null;
  span_days: number | null;
  epoch_start: string;
  epoch_end: string;
  wavelength_at_target_um: { min: number; max: number } | null;
  saturated_images: number;
  files: string[];
}

export interface Bundle {
  id: string;
  kind: 'detector' | 'all';
  detectors: string[];
  mode: BundleMode;
  note: string;
  usable_epochs: number[];
  rgb: { red: RgbChoice; green: RgbChoice; blue: RgbChoice } | null;
  diff: {
    first: { epoch: number; time: string };
    last: { epoch: number; time: string };
    clip_sigma: number;
    definition: string;
    colours: string;
  } | null;
  wavelength_um: { min: number; max: number };
  epochs: BundleEpoch[];
  stretch: { kind: string; black: number; white: number; noise: number; unit: string } | null;
  covered_fraction: number;
  gaps: string[];
}

export interface SpectrumChannel {
  detector: string;
  channel: number;
  wavelength_um: number | null;
  wl_min_um: number | null;
  wl_max_um: number | null;
  epochs: { epoch: number; value: number | null; sigma: number | null; n: number }[];
}

export interface Spectrum {
  x: number;
  y: number;
  unit: string | null;
  value_definition: string;
  epochs: { index: number; time: string; start: string; end: string }[];
  channels: SpectrumChannel[];
}

/** The position the page is about: decimal degrees as the backend resolved them. */
export interface Position {
  ra: number;
  dec: number;
  fov: number;
}
