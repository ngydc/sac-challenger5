import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { Location } from '@angular/common';
import { ApiError, ApiService, isAbort } from './api.service';
import { Coverage, Frame, ImageOptions, Picture, ResolveResponse, Target } from '../models/api.models';
import { bandsOf, framesOfVisit, pickFrame } from '../utils/frames';

export type Stretch = 'fixed' | 'frame';
export type Phase = 'idle' | 'resolving' | 'coverage' | 'ready' | 'failed';
export type Playing = 'time' | 'wavelength' | null;

const DEBOUNCE_MS = 150;
const BLINK_MS = 800;
const SWEEP_MS = 350;

/**
 * Shared view state (search result, coverage, slider positions, settings, current picture).
 * Viewer, sliders and search all read and write it, so they stay in sync.
 */
@Injectable({ providedIn: 'root' })
export class ViewerState {
  private readonly api = inject(ApiService);
  private readonly location = inject(Location);

  // ---- search and coverage -------------------------------------------------------------------
  readonly query = signal('');
  readonly resolved = signal<ResolveResponse | null>(null);
  readonly fov = signal(0.08);
  readonly coverage = signal<Coverage | null>(null);
  readonly phase = signal<Phase>('idle');
  /** Error of the search or coverage step (shown instead of the picture). */
  readonly error = signal<string | null>(null);

  readonly target = computed<Target | null>(() => {
    const r = this.resolved();
    if (!r) return null;
    const { ra, dec, pmra, pmdec, pm_epoch } = r.target;
    return { ra, dec, fov: this.fov(), pmra, pmdec, pm_epoch };
  });
  readonly hasMotion = computed(() => this.resolved()?.target.pmra != null);

  readonly frames = computed<Frame[]>(() => this.coverage()?.frames ?? []);
  readonly visits = computed(() => this.coverage()?.visits ?? []);
  readonly range = computed(() => this.coverage()?.wavelength_range_um ?? null);
  readonly bands = computed(() => bandsOf(this.frames()));

  // ---- slider positions and settings ---------------------------------------------------------
  readonly visit = signal(0);
  readonly wavelength = signal(0);
  /** Off by default (raw values), as in the reference design; the API's default is on. */
  readonly mask = signal(false);
  readonly showRing = signal(true);
  readonly stretch = signal<Stretch>('fixed');
  readonly playing = signal<Playing>(null);

  readonly pick = computed(() => pickFrame(this.frames(), this.visit(), this.wavelength()));
  readonly band = computed(() => {
    const d = this.pick()?.frame.detector;
    return this.bands().find((b) => b.detector === d) ?? null;
  });

  // ---- current picture -----------------------------------------------------------------------
  readonly picture = signal<Picture | null>(null);
  readonly loading = signal(false);
  readonly imageError = signal<string | null>(null);

  private searchCtrl?: AbortController;
  private showCtrl?: AbortController;
  private prefetchCtrl?: AbortController;
  private prefetchKey = '';
  private debounce?: ReturnType<typeof setTimeout>;
  private timer?: ReturnType<typeof setInterval>;
  private initial: { visit?: number; wl?: number } = {};

  constructor() {
    // Load the picture whenever the frame, the target or a drawing setting changes.
    effect(() => {
      const pick = this.pick();
      const t = this.target();
      const opts = { mask: this.mask(), stretch: this.stretch() };
      if (this.phase() !== 'ready' || !t) return;
      clearTimeout(this.debounce);
      untracked(() => {
        if (!pick) {
          this.imageError.set('No image in this season.');
          return;
        }
        this.debounce = setTimeout(() => this.show(t, pick.frame, opts.mask, opts.stretch), DEBOUNCE_MS);
      });
    });

    // Keep the page URL shareable: ?q=...&fov=...&visit=...&wl=...
    effect(() => {
      const q = this.resolved()?.query;
      if (!q) return;
      const p = new URLSearchParams({ q, fov: String(this.fov()) });
      if (this.phase() === 'ready') {
        p.set('visit', String(this.visit()));
        p.set('wl', this.wavelength().toFixed(3));
      }
      this.location.replaceState(window.location.pathname, p.toString());
    });
  }

  /** Reads ?q= (or ?ra=&dec=), ?fov=, ?visit=, ?wl= from the page URL and starts the search. */
  initFromUrl(): void {
    const p = new URLSearchParams(window.location.search);
    const q = p.get('q') ?? (p.has('ra') && p.has('dec') ? `${p.get('ra')} ${p.get('dec')}` : null);
    const num = (k: string) => (p.has(k) && !isNaN(Number(p.get(k))) ? Number(p.get(k)) : undefined);
    this.initial = { visit: num('visit'), wl: num('wl') };
    if (q) this.search(q, num('fov'));
  }

  // ---- search --------------------------------------------------------------------------------
  async search(q: string, fov?: number): Promise<void> {
    q = q.trim();
    if (!q) return;
    this.stop();
    this.searchCtrl?.abort();
    const ctrl = (this.searchCtrl = new AbortController());
    this.query.set(q);
    this.phase.set('resolving');
    this.error.set(null);
    try {
      const r = await this.api.resolve(q, ctrl.signal);
      this.resolved.set(r);
      this.fov.set(fov ?? r.target.fov);
      await this.loadCoverage(ctrl);
    } catch (e) {
      if (isAbort(e)) return;
      this.phase.set('failed');
      this.error.set(messageOf(e));
    }
  }

  /** New field of view: the frames are different, so the coverage is loaded again. */
  setFov(fov: number): void {
    if (!this.resolved() || !(fov >= 0.01 && fov <= 0.3) || fov === this.fov()) return;
    this.fov.set(fov);
    this.initial = { visit: this.visit(), wl: this.wavelength() };
    this.searchCtrl?.abort();
    const ctrl = (this.searchCtrl = new AbortController());
    this.loadCoverage(ctrl).catch((e) => {
      if (isAbort(e)) return;
      this.phase.set('failed');
      this.error.set(messageOf(e));
    });
  }

  private async loadCoverage(ctrl: AbortController): Promise<void> {
    const t = this.target()!;
    this.stop();
    this.phase.set('coverage');
    this.coverage.set(null);
    this.picture.set(null);
    this.imageError.set(null);
    this.api.clearPictures();
    const c = await this.api.loadCoverage(t, (c) => this.coverage.set(c), ctrl.signal);
    if (!c.frames.length || !c.wavelength_range_um) {
      this.phase.set('failed');
      this.error.set('SPHEREx has no images of this position yet.');
      return;
    }
    const [lo, hi] = c.wavelength_range_um;
    const { visit, wl } = this.initial;
    this.initial = {};
    this.visit.set(visit !== undefined && visit >= 0 && visit < c.visits.length ? visit : 0);
    this.wavelength.set(wl !== undefined && wl >= lo && wl <= hi ? wl : (lo + hi) / 2);
    this.showRing.set(this.hasMotion());
    this.phase.set('ready');
  }

  // ---- navigation ----------------------------------------------------------------------------
  setVisit(v: number): void {
    const n = this.visits().length;
    if (n) this.visit.set(Math.min(n - 1, Math.max(0, v)));
  }

  stepVisit(d: number, wrap = false): void {
    const n = this.visits().length;
    if (!n) return;
    const v = this.visit() + d;
    this.visit.set(wrap ? (v + n) % n : Math.min(n - 1, Math.max(0, v)));
  }

  setWavelength(w: number): void {
    const r = this.range();
    if (r) this.wavelength.set(Math.min(r[1], Math.max(r[0], w)));
  }

  /** Next/previous frame of the current season by wavelength. */
  stepFrame(d: number, wrap = false): void {
    const list = framesOfVisit(this.frames(), this.visit());
    if (!list.length) return;
    const cur = this.pick()?.frame;
    let i = cur ? list.findIndex((f) => f.id === cur.id) : -1;
    i += d;
    if (wrap) i = (i + list.length) % list.length;
    else i = Math.min(list.length - 1, Math.max(0, i));
    this.wavelength.set(list[i].wavelength_um);
  }

  jumpTo(f: Frame): void {
    this.visit.set(f.visit);
    this.wavelength.set(f.wavelength_um);
  }

  // ---- playback ------------------------------------------------------------------------------
  toggle(mode: Exclude<Playing, null>): void {
    if (this.playing() === mode) return this.stop();
    this.stop();
    if (this.phase() !== 'ready') return;
    this.playing.set(mode);
    this.timer =
      mode === 'time'
        ? setInterval(() => this.stepVisit(1, true), BLINK_MS)
        : setInterval(() => this.stepFrame(1, true), SWEEP_MS);
  }

  stop(): void {
    clearInterval(this.timer);
    this.playing.set(null);
  }

  // ---- picture loading -----------------------------------------------------------------------
  /**
   * Shows frame `f`. With the fixed stretch, every season's frame at this wavelength (the blink
   * set) is drawn with the brightness range of the first one, so brightness changes stay visible.
   */
  private async show(t: Target, f: Frame, mask: boolean, stretch: Stretch): Promise<void> {
    this.showCtrl?.abort();
    const ctrl = (this.showCtrl = new AbortController());
    const blinkSet = this.blinkSet(f.wavelength_um);
    const ref = blinkSet[0] ?? f;
    const auto: ImageOptions = { mask };
    const fixedOpts = (p: Picture): ImageOptions => ({ mask, vmin: p.stretch[0], vmax: p.stretch[1] });

    try {
      this.imageError.set(null);
      let pic: Picture | undefined;
      if (stretch === 'frame') {
        pic = this.api.cached(t, f, auto);
      } else {
        const refPic = this.api.cached(t, ref, auto);
        pic = refPic && this.api.cached(t, f, fixedOpts(refPic));
      }
      if (pic) {
        this.picture.set(pic);
        this.loading.set(false);
      } else {
        this.loading.set(true);
        // Start the downloads of the whole blink set now, so blinking is instant afterwards.
        this.prefetch(t, blinkSet, auto);
        if (stretch === 'frame') {
          this.setPicture(await this.api.loadFrame(t, f, auto, ctrl.signal), ctrl);
        } else {
          const [own, refPic] = await Promise.all([
            this.api.loadFrame(t, f, auto, ctrl.signal),
            this.api.loadFrame(t, ref, auto, ctrl.signal),
          ]);
          // Show the frame on its own scale at once, then on the common scale (instant: cached).
          if (own.frameId !== refPic.frameId) this.setPicture(own, ctrl, true);
          this.setPicture(await this.api.loadFrame(t, f, fixedOpts(refPic), ctrl.signal), ctrl);
        }
      }
      if (stretch === 'fixed') {
        const refPic = this.api.cached(t, ref, auto);
        if (refPic) this.prefetch(t, blinkSet, fixedOpts(refPic));
      }
    } catch (e) {
      if (isAbort(e) || ctrl.signal.aborted) return;
      this.loading.set(false);
      this.imageError.set(messageOf(e));
    }
  }

  private setPicture(p: Picture, ctrl: AbortController, stillLoading = false): void {
    if (ctrl.signal.aborted) return;
    this.picture.set(p);
    this.loading.set(stillLoading);
  }

  /** The frame of every season nearest to wavelength `w`. */
  private blinkSet(w: number): Frame[] {
    return this.visits()
      .map((v) => pickFrame(this.frames(), v.index, w)?.frame)
      .filter((f): f is Frame => !!f);
  }

  /** Loads the given frames in the background; a new wavelength cancels the previous prefetch. */
  private prefetch(t: Target, frames: Frame[], o: ImageOptions): void {
    const key = `${frames.map((f) => f.id).join()}|${JSON.stringify(o)}`;
    if (key === this.prefetchKey) return;
    this.prefetchKey = key;
    this.prefetchCtrl?.abort();
    const ctrl = (this.prefetchCtrl = new AbortController());
    for (const f of frames) this.api.loadFrame(t, f, o, ctrl.signal).catch(() => undefined);
  }
}

export function messageOf(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'outside_image') return 'The view lies outside this image.';
    return e.message;
  }
  if (e instanceof TypeError) return 'The backend cannot be reached. Is it running?';
  return e instanceof Error ? e.message : String(e);
}
