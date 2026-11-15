import { Target } from './api.models';

/**
 * Response types of the deep-analysis API (docs/API_ANALYSIS.md, backend/app/analysis_api.py).
 * Only fields the frontend reads are typed; field names are exactly the backend's.
 */

/** idle: not computed. queued: waiting for a free slot. running: being computed. ready: complete. */
export type AnalysisState = 'idle' | 'queued' | 'running' | 'ready' | 'error';
export type BundleMode = 'three_epochs' | 'two_epochs' | 'one_epoch' | 'no_data';

export interface Progress {
  stage: string;
  done: number;
  total: number;
  bundles_ready: string[];
}

export interface AnalysisStatus {
  target: Target;
  state: AnalysisState;
  /** A complete result is being recomputed with newly found images; the old one is shown meanwhile. */
  refreshing: boolean;
  progress: Progress | null;
  message: string | null;
  /** The five test targets: kept for good. Other positions: removed after temp_ttl_hours without use. */
  kept: boolean;
  temp_ttl_hours: number;
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
  /** Identifies the set of images the result was computed from; changes when new data was added. */
  images_key: string;
  grid: { width: number; height: number; pixel_scale_arcsec: number; orientation: string };
  epochs: Epoch[];
  bundles: Bundle[];
  collections: string[];
  searched_at: string;
  n_images: number;
  failed: { reason: string }[];
  failed_retryable: number;
  /** The colour pictures (/colour/{epoch}.png); null/missing until every detector is done (PIPELINE_VERSION 10 on). */
  colour?: Colour | null;
}

/** One spectral channel and the colour it adds to the colour pictures. */
export interface PaletteChannel {
  detector: string;
  channel: number;
  wavelength_um: number | null;
  wl_min_um: number | null;
  wl_max_um: number | null;
  /** #rrggbb */
  colour: string;
}

export interface ColourEpoch {
  index: number;
  /** False: this epoch covers too few wavelengths, no colour picture. */
  usable: boolean;
  start: string | null;
  end: string | null;
  time: string | null;
  /** One entry per palette channel: whether this epoch has it. */
  channels_covered: boolean[];
  n_channels: number;
  /** Share of the covered pixels that are masked (saturated or flagged). */
  masked_fraction: number | null;
  covered_fraction: number | null;
  /** Predicted target position in pixels at the epoch's median time: x from the left, y from the bottom. */
  target_xy?: [number | null, number | null];
}

/** Every wavelength of one epoch in one picture: short wavelengths blue, long ones red. */
export interface Colour {
  palette: PaletteChannel[];
  /** Colour of masked pixels, #rrggbb. */
  mask_colour: string;
  usable_epochs: number[];
  epochs: ColourEpoch[];
  note: string;
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

/** The two epochs a difference picture compares. */
export interface DiffPair {
  first: { epoch: number; time: string };
  last: { epoch: number; time: string };
}

/**
 * One step difference: the k-th pair of NEIGHBOURING usable epochs of this bundle (epochs it cannot use are
 * skipped, so the same step can cover different dates in different bundles). Picture: /steps/{step}.png.
 */
export interface DiffStep extends DiffPair {
  step: number;
  /** False: the pair exists but its difference could not be computed (no picture). */
  available?: boolean;
}

export interface Bundle {
  id: string;
  kind: 'detector' | 'all';
  detectors: string[];
  mode: BundleMode;
  note: string;
  usable_epochs: number[];
  rgb: { red: RgbChoice; green: RgbChoice; blue: RgbChoice } | null;
  /** "Total": last minus first usable epoch. */
  diff:
    | (DiffPair & {
        clip_sigma: number;
        definition: string;
        colours: string;
      })
    | null;
  /** Differences of neighbouring usable epochs (backend PIPELINE_VERSION 9 on; missing in older results). */
  diff_steps?: DiffStep[];
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

/** The view the analysis is about: the viewer's target (position, field of view, proper motion). */
export type Position = Target;
