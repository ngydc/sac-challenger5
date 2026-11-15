import { Frame } from '../models/api.models';

export interface Pick {
  frame: Frame;
  /** False when no frame of this visit lies within 2 bandwidths of the wanted wavelength. */
  exact: boolean;
}

/** The frame of `visit` nearest to wavelength `w` (docs/API.md 3.2). Skips frames outside the view. */
export function pickFrame(frames: readonly Frame[], visit: number, w: number): Pick | null {
  let best: Frame | null = null;
  for (const f of frames) {
    if (f.visit !== visit || f.cache === 'outside') continue;
    if (!best || Math.abs(f.wavelength_um - w) < Math.abs(best.wavelength_um - w)) best = f;
  }
  if (!best) return null;
  return { frame: best, exact: Math.abs(best.wavelength_um - w) <= 2 * best.bandwidth_um };
}

export interface Band {
  detector: string;
  min: number;
  max: number;
  count: number;
}

/** Wavelength range and frame count per detector, taken from the data (never hard-coded). */
export function bandsOf(frames: readonly Frame[]): Band[] {
  const m = new Map<string, Band>();
  for (const f of frames) {
    const b = m.get(f.detector);
    if (!b) m.set(f.detector, { detector: f.detector, min: f.wavelength_um, max: f.wavelength_um, count: 1 });
    else {
      b.min = Math.min(b.min, f.wavelength_um);
      b.max = Math.max(b.max, f.wavelength_um);
      b.count++;
    }
  }
  return [...m.values()].sort((a, b) => a.min - b.min);
}

/** Frames of one visit sorted by wavelength (for ↑/↓ and the wavelength sweep). */
export function framesOfVisit(frames: readonly Frame[], visit: number): Frame[] {
  return frames
    .filter((f) => f.visit === visit && f.cache !== 'outside')
    .sort((a, b) => a.wavelength_um - b.wavelength_um);
}

export interface RingPosition {
  /** Centre, in % of the picture width. */
  left: number;
  /** Centre, in % of the picture height (from the top). */
  top: number;
  /** Diameter, in % of the picture width. */
  d: number;
}

/**
 * Where the predicted-position ring goes, in % of the picture. `x` and `yFromBottom` are pixel coordinates as the
 * backend reports them (0-based, y counting from the bottom/south); the ring is centred on the pixel's centre
 * (+0.5). Null if the position lies outside the picture.
 */
export function ringPosition(x: number, yFromBottom: number, width: number, height: number): RingPosition | null {
  const left = ((x + 0.5) / width) * 100;
  const top = ((height - 1 - yFromBottom + 0.5) / height) * 100;
  if (left < 0 || left > 100 || top < 0 || top > 100) return null;
  return { left, top, d: Math.max(4, (5 / width) * 100) };
}
