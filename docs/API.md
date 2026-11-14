# Backend API for the frontend (MVP)

Written for: the frontend developers. Three endpoints are all the MVP needs. The code is in `backend/app/` (`api.py` has the endpoints and schemas, `resolver.py` the name lookup, `service.py` the data logic).

**Live reference:** start the backend and open **http://localhost:8000/docs** (Swagger UI with "Try it out" buttons and every parameter described) or `/openapi.json` (to generate TypeScript types, e.g. `npx openapi-typescript http://localhost:8000/openapi.json -o src/app/core/api.types.ts`). This page explains how the endpoints fit together and how to build the sliders on them.

Start the backend: from `backend/`, `.venv\Scripts\python -m uvicorn app.main:app --port 8000` (or `docker compose up`). The Angular dev server and nginx forward `/api/*` to it (`frontend/proxy.conf.mjs`, `nginx.conf`), so call relative URLs such as `/api/coverage`.

---

## 1. The idea

SPHEREx images any position on the sky several times, at different times and in different wavelengths. The tool shows those images as a series the user can scrub through, to spot things that move or change.

| Word | Meaning |
|---|---|
| **Target** | Where to look: `ra`, `dec`, a field of view `fov` (degrees) and, for moving objects, a proper motion (`pmra`, `pmdec`, `pm_epoch`). The view is **fixed on the sky**: stars stay still, a moving object moves through the picture. |
| **Visit** | One observing season. The telescope revisits a position about every six months, so a position has only a few visits (3 for Barnard's Star). The **time slider** has one stop per visit. |
| **Frame** | One picture: one camera (detector D1 to D6) at one time. Each frame has a `wavelength_um`, the wavelength **at the target's position** in that image. |
| **Wavelength slider** | One continuous axis from the shortest to the longest wavelength (0.74 to 5.0 µm), **across all six detectors**. The user never picks a detector. |

**Blink** = keep the wavelength, step the time slider through the visits. Anything that moved jumps; anything that changed brightness blinks.

## 2. The three calls

```
user types "Barnard's Star"  or  "17h57m48.5s +04d41m36s"
        |
        v   GET /api/resolve?q=...                       -> target (ra, dec, fov, pm...)  + warnings
        |
        v   GET /api/coverage?ra=&dec=&fov=&pm...        -> poll until state == "ready"
        |                                                   gives: visits[] (time slider), wavelength_range_um
        |                                                   (wavelength slider), frames[] (every picture)
        v   build the sliders
        |
        v   on every slider move:
            pick the frame of that visit nearest to the wavelength          (in the frontend, no request)
            GET /api/frames/{id}/image.png?ra=&dec=&fov=&pm...              -> a PNG, show it
```

| # | Endpoint | Purpose | Typical time |
|---|---|---|---|
| 1 | `GET /api/resolve?q=` | A name or coordinates become a target. | instant for the 5 test targets and coordinates, about 1 s for other names |
| 2 | `GET /api/coverage` | What exists here. Poll until `ready`. | instant for a position seen before; 50 to 125 s the first time |
| 3 | `GET /api/frames/{id}/image.png` | One picture. | about 0.1 s if cached; about 12 s if it must be downloaded first |

The **target parameters** (`ra, dec, fov, pmra, pmdec, pm_epoch`) must be sent **unchanged on every call** for that target: they are part of what a frame is. Keep them in one object and build the query string from it (helper in section 5).

Every error has one shape, `{"error": {"code": "...", "message": "..."}}` (section 6).

---

## 3. Endpoint reference

### 3.1 `GET /api/resolve?q=<text>`

One search box for both names and coordinates. Call it when the user **submits**, not on every keystroke.

| Parameter | |
|---|---|
| `q` (required) | What the user typed. |

**Coordinates** are two numbers (degrees: `269.452 4.693`, `269.452, 4.693`) or sexagesimal (`17h57m48.5s +04d41m36s`, `17:57:48.5 +04:41:36`, `17 57 48.5 +04 41 36`, `08h55m10.831s -07d14m42.53s`). RA is read as **hours only when written in sexagesimal**. Typed coordinates have no proper motion: the view stays exactly there.

**Names** are matched first against the five challenge targets (so `WISE 0855`, `R Dra`, `eps Ind B`, `GJ 699` work, whatever the case, spacing or punctuation), then looked up in SIMBAD through CDS's name service. Not supported: comets and asteroids (SIMBAD does not know them).

For objects with a **proper motion**, the returned position is moved from the catalogue (J2000) to 1 January of the current year, so the object sits near the middle of recent images. Barnard's Star has moved 4.5 arcmin since J2000, more than half of the default field of view. `warnings` tells you.

```json
{
  "query": "Barnard's Star",
  "kind": "preset",
  "target": {
    "ra": 269.446269, "dec": 4.768204, "fov": 0.08,
    "pmra": -801.551, "pmdec": 10362.394, "pm_epoch": 2026.0,
    "name": "Barnard's Star",
    "note": "Nearby star with the largest known proper motion (10.4 arcsec/yr). Saturated in several bands."
  },
  "warnings": ["The catalogue position is 4.5 arcmin away from where this object is in 2026; it was moved using its proper motion."]
}
```

| Field | Meaning |
|---|---|
| `kind` | `coordinates` (typed position), `preset` (one of the five challenge targets, matched locally, works offline), `name` (found by the name service). |
| `target.ra, dec, fov` | Centre and width of the view. `fov` is a suggestion (0.08° = 4.8 arcmin = 47 pixels; 0.2 for Epsilon Indi B so its host star is in view). The user may change it (0.01 to 0.3). |
| `target.pmra, pmdec, pm_epoch` | Proper motion (mas/yr, `pmra` includes cos(dec)) and the year the position is valid for. **`null` when there is no motion**: pass them on as they are. They move the predicted-position marker, never the view. |
| `target.name` | The name as the user typed it (`null` for coordinates). |
| `target.note` | A remark. For the five targets a description; for other names the SIMBAD identifier if it differs (typing `Vega` gives `SIMBAD identifier: alf Lyr`). |
| `warnings` | Texts worth showing. May be empty. |

Typed coordinates:
```json
{"query": "08h55m10.831s -07d14m42.53s", "kind": "coordinates",
 "target": {"ra": 133.795129, "dec": -7.245147, "fov": 0.08, "pmra": null, "pmdec": null, "pm_epoch": null, "name": null, "note": null},
 "warnings": []}
```

| Status | `error.code` | When |
|---|---|---|
| 400 | `bad_query` | `q` empty or longer than 120 characters. |
| 400 | `bad_coordinates` | Looks like coordinates but out of range (RA 0 to 360, Dec −90 to 90). |
| 404 | `name_not_found` | Nobody knows this name (also e.g. `Pluto`: not a catalogue star). Suggest checking the spelling or typing coordinates. |
| 502 | `resolver_unavailable` | The name service did not answer. Coordinates and the five test targets still work. |

### 3.2 `GET /api/coverage`

What SPHEREx data exists for a target: the data behind the sliders.

| Parameter | |
|---|---|
| `ra`, `dec` (required) | Decimal degrees, or sexagesimal. Use the values from `/api/resolve`. |
| `fov` | Field of view in degrees, 0.01 to 0.3 (default 0.08). |
| `pmra`, `pmdec`, `pm_epoch` | Give **all three or none**. Omit them when the resolve result has `null`. |

The first call starts the lookup in the background and returns immediately. **Poll every 1.5 s until `state` is `ready`.** It always returns HTTP 200 for valid input; trouble with the data source shows in `state`/`message`, so the polling loop stays simple.

```json
{
  "target": {"ra": 269.446269, "dec": 4.768204, "fov": 0.08, "pmra": -801.551, "pmdec": 10362.394, "pm_epoch": 2026.0},
  "state": "ready",
  "message": null,
  "progress": {"located": 350, "total": 350},
  "grid": {"width": 47, "height": 47, "pixel_scale_arcsec": 6.15, "center_ra": 269.446269, "center_dec": 4.768204,
           "orientation": "north up, east left; pixel row 0 is the south edge"},
  "visits": [
    {"index": 0, "start": "2025-08-15", "end": "2025-10-01", "n_frames": 117, "target": {"ra": 269.446339, "dec": 4.767298}},
    {"index": 1, "start": "2026-03-11", "end": "2026-05-05", "n_frames": 118, "target": {"ra": 269.44621,  "dec": 4.768965}},
    {"index": 2, "start": "2026-08-16", "end": "2026-09-22", "n_frames": 115, "target": {"ra": 269.446118, "dec": 4.770144}}
  ],
  "wavelength_range_um": [0.741, 5.0012],
  "frames": [
    {"id": "2025W35_1A_0432_4-D1", "visit": 0, "detector": "D1", "wavelength_um": 0.7494, "bandwidth_um": 0.0173,
     "time": "2025-08-27T05:07:00Z", "release": "spherex_dr1", "cache": "ready"},
    "... 349 more, sorted by (visit, wavelength_um)"
  ]
}
```

| Field | Meaning |
|---|---|
| `state` | `searching` (looking up which images cover the position) · `locating` (working out each image's wavelength; `progress` counts up) · `ready` · `error` (see `message`; the backend retries by itself after about 15 s, so **keep polling** and show the message). |
| `message` | Reason for an `error`, or a notice that the list could not be refreshed and is the last known one. |
| `visits[]` | The time slider's stops. `target` is the predicted object position in the middle of that visit, only with proper motion (use it to re-centre the view or draw the track). |
| `wavelength_range_um` | The wavelength slider's range, `[min, max]`. `null` until ready. |
| `frames[]` | Every picture, sorted by `(visit, wavelength_um)`. Empty until `ready` (handle "no data here" too). |
| `frames[].id` | Use in the image URL. |
| `frames[].detector` | D1 to D6. Informational; don't make the user pick it. |
| `frames[].wavelength_um` / `bandwidth_um` | Wavelength at the target in this image, and the width of the band there. |
| `frames[].cache` | `ready` (instant) · `fetching` / `queued` (being downloaded) · `failed` (a recent download failed) · `outside` (the view lies outside this image, never available) · `missing` (not requested yet). You never need to wait for `ready` before asking for an image; use it to draw which positions on the sliders are instant. |
| `grid` | Size of every picture at `scale=1`. All frames use the same grid, so stars line up between frames. |

**Choosing the frame for a slider position (visit `v`, wavelength `w`)** is done in the frontend with the list you have, no request needed:

```ts
function pickFrame(frames: Frame[], visit: number, w: number): { frame: Frame; exact: boolean } | null {
  let best: Frame | null = null;
  for (const f of frames) {
    if (f.visit !== visit) continue;
    if (!best || Math.abs(f.wavelength_um - w) < Math.abs(best.wavelength_um - w)) best = f;
  }
  if (!best) return null;                                       // no image at all in this visit
  return { frame: best, exact: Math.abs(best.wavelength_um - w) <= 2 * best.bandwidth_um };
}
```
When `exact` is false there is **no real frame at that wavelength in that visit**. Show the nearest with a notice ("nearest: 3.9 µm"), or grey that position out. This does happen: most visits cover almost every wavelength, but not all (the mission start, partly processed visits; the newest visit of an object may be missing).

### 3.3 `GET /api/frames/{id}/image.png`

One frame as a PNG, north up, east left. `{id}` is `frames[].id`.

| Parameter | Default | |
|---|---|---|
| `ra, dec, fov, pmra, pmdec, pm_epoch` | | **The same target parameters as for the coverage request.** |
| `mask` | `true` | Draw flagged bad pixels dark red. `false` shows their raw values (a saturated star core then shows bright instead of as a hole). |
| `vmin`, `vmax` | per frame | Brightness drawn as black / white (MJy/sr). Give **both or neither** (else 400 `bad_stretch`). See "Brightness". |
| `scale` | `1` | Integer upscale 1 to 16 (nearest neighbour). The picture is 47 px wide by default; use `8`, or CSS `image-rendering: pixelated`. |
| `wait` | `20` | Seconds to wait if the frame must be downloaded first (0 to 60). `0` = never wait. |

**Responses**

- **200**: the PNG, plus headers describing the frame:

| Header | Meaning |
|---|---|
| `X-Frame-Id` | The id. |
| `X-Wavelength-Um`, `X-Bandwidth-Um` | Wavelength at the target, and band width. (Within 0.001 µm of the coverage list's value.) |
| `X-Time-Utc` | Middle of the exposure. |
| `X-Flags-At-Target` | Quality flags on the target's pixel, e.g. `OVERFLOW,BLOOM` (saturated). Empty if none. |
| `X-Target-X`, `X-Target-Y` | Predicted target position in pixels: X from the left edge, **Y from the bottom** (row 0 = south). In picture coordinates the position is `(X, height - 1 - Y)`, times `scale`, plus half a pixel to centre. May lie outside the picture; then the object is out of view. |
| `X-Image-Size` | Width and height at `scale=1`. |
| `X-Stretch-Min`, `X-Stretch-Max` | The brightness range this picture was drawn with. |

- **202**: still being downloaded after `wait` seconds. Body `{"status": "fetching", "frame_id": "...", "retry_after_s": 3}` and a `Retry-After` header. The download continues in the background: ask again after the delay.
- **404** `outside_image` (permanent, don't retry) · `unknown_frame` (no such image for this target) · **502** `upstream_error` (IRSA failed; retry later).

Colours: grey = brightness (asinh scale), **dark red** = masked bad pixel, **slate blue** = no data (outside the image).

**Speed.** Cached frames answer in about 0.1 s (10 ms if shown recently). Others are downloaded from IRSA first, about 12 s, and the backend downloads three at a time (IRSA rate-limits). You may request many frames at once: three frames requested together took 11.8 s in our test, the same as one. **When the wavelength slider settles, request the frames of all visits at that wavelength together (the blink set).** That also fills the cache, so scrubbing afterwards is instant.

**Brightness.** Without `vmin`/`vmax` every frame is scaled on its own, which **hides brightness changes between visits**, a problem for variable stars (RW Aurigae, R Draconis are test targets for exactly that). For a blink, draw all frames of the blink set with one range:

1. Request the frames. Read `X-Stretch-Min`/`X-Stretch-Max` from the first.
2. Request them again with those values as `vmin`/`vmax` (now cached, so it is instant).

Don't reuse a range across detectors: their brightness differs a lot.

The response depends only on the URL, so the browser may cache it (`Cache-Control: max-age=3600`).

---

## 4. Suggested behaviour

| Situation | What to do |
|---|---|
| Coverage is `searching`/`locating` | Show a progress bar from `progress` (`located / total`). It can take a minute or two the first time. |
| Coverage `error` | Show `message`, keep polling; the backend retries. |
| Slider moves | Debounce about 150 ms. Cancel the previous request with `AbortController`. Keep the previous picture on screen (dimmed) until the new one arrives. |
| Wavelength slider settles | Request the blink set (the frame of each visit at that wavelength) in parallel. |
| `202` | Retry after `Retry-After` seconds. |
| `exact == false` | Show a notice with the nearest wavelength, or disable that position. |
| `X-Flags-At-Target` contains `OVERFLOW` | The object is saturated: offer the `mask` toggle (otherwise its core is a hole). |
| Target has proper motion | Draw a ring at `X-Target-X/Y`. |
| Before a demo | Open the five test targets once and scrub through them so their frames are cached; then the demo is instant. |

Suggested page URL (not an API matter): `?q=Barnard%27s%20Star&fov=0.08&visit=1&wl=4.2`, so a link recreates the view (call resolve with `q` on load).

---

## 5. TypeScript

Types (or generate them from `/openapi.json`):

```ts
export interface Target { ra: number; dec: number; fov: number; pmra: number | null; pmdec: number | null; pm_epoch: number | null }
export interface ResolveResponse {
  query: string; kind: 'coordinates' | 'preset' | 'name';
  target: Target & { name: string | null; note: string | null }; warnings: string[];
}
export interface Frame {
  id: string; visit: number; detector: string; wavelength_um: number; bandwidth_um: number; time: string; release: string;
  cache: 'ready' | 'fetching' | 'queued' | 'failed' | 'outside' | 'missing';
}
export interface Visit { index: number; start: string; end: string; n_frames: number; target: { ra: number; dec: number } | null }
export interface Coverage {
  target: Target; state: 'searching' | 'locating' | 'ready' | 'error'; message: string | null;
  progress: { located: number; total: number };
  grid: { width: number; height: number; pixel_scale_arcsec: number; center_ra: number; center_dec: number; orientation: string };
  visits: Visit[]; wavelength_range_um: [number, number] | null; frames: Frame[];
}
```

Calls:

```ts
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}
const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
  const t = setTimeout(resolve, ms);
  signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('aborted', 'AbortError')); });
});
async function json<T>(r: Response): Promise<T> {
  const body = await r.json();
  if (!r.ok) throw new ApiError(r.status, body.error.code, body.error.message);
  return body;
}

// the six target parameters, plus any extras; null values are left out (the API wants all three motion fields or none)
function query(t: Target, extra: Record<string, string | number | boolean | undefined> = {}): string {
  const p = new URLSearchParams();
  const all = { ra: t.ra, dec: t.dec, fov: t.fov, pmra: t.pmra, pmdec: t.pmdec, pm_epoch: t.pm_epoch, ...extra };
  for (const [k, v] of Object.entries(all)) if (v !== null && v !== undefined) p.set(k, String(v));
  return p.toString();
}

export const resolve = (q: string) => fetch(`/api/resolve?${new URLSearchParams({ q })}`).then(r => json<ResolveResponse>(r));

export async function loadCoverage(t: Target, onUpdate: (c: Coverage) => void, signal?: AbortSignal): Promise<Coverage> {
  for (;;) {
    const c = await fetch(`/api/coverage?${query(t)}`, { signal }).then(r => json<Coverage>(r));
    onUpdate(c);                                  // progress bar / error message
    if (c.state === 'ready') return c;
    await sleep(1500, signal);                    // 'error' is retried by the backend: keep polling
  }
}

export interface Picture {
  url: string; wavelength: number; time: string; flags: string[];
  target: { x: number; y: number }; size: number; stretch: [number, number];
}
export async function loadFrame(
  t: Target, f: Frame, o: { vmin?: number; vmax?: number; mask?: boolean; scale?: number; signal?: AbortSignal } = {},
): Promise<Picture> {
  const fixed = o.vmin !== undefined && o.vmax !== undefined ? { vmin: o.vmin, vmax: o.vmax } : {};
  const qs = query(t, { scale: o.scale ?? 8, mask: o.mask ?? true, wait: 20, ...fixed });
  for (;;) {
    const r = await fetch(`/api/frames/${f.id}/image.png?${qs}`, { signal: o.signal });
    if (r.status === 202) { await sleep((Number(r.headers.get('Retry-After')) || 3) * 1000, o.signal); continue; }
    if (!r.ok) { const b = await r.json(); throw new ApiError(r.status, b.error.code, b.error.message); }
    const h = r.headers;
    return {
      url: URL.createObjectURL(await r.blob()),   // call URL.revokeObjectURL(url) when the picture is no longer shown
      wavelength: Number(h.get('X-Wavelength-Um')), time: h.get('X-Time-Utc')!,
      flags: (h.get('X-Flags-At-Target') ?? '').split(',').filter(Boolean),
      target: { x: Number(h.get('X-Target-X')), y: Number(h.get('X-Target-Y')) },
      size: Number(h.get('X-Image-Size')),
      stretch: [Number(h.get('X-Stretch-Min')), Number(h.get('X-Stretch-Max'))],
    };
  }
}
```

The blink set with one fixed brightness range (all downloads run in parallel; the second pass is instant):

```ts
export async function loadBlinkSet(t: Target, frames: Frame[], signal?: AbortSignal): Promise<Picture[]> {
  const first = await Promise.all(frames.map(f => loadFrame(t, f, { signal })));    // downloads in parallel, each on its own scale
  const [vmin, vmax] = first[0].stretch;
  first.forEach(p => URL.revokeObjectURL(p.url));
  return Promise.all(frames.map(f => loadFrame(t, f, { vmin, vmax, signal })));    // now cached: instant, same brightness scale
}
```

Marker ring on a picture shown at `scale`: `cx = (p.target.x + 0.5) * scale`, `cy = (p.size - 1 - p.target.y + 0.5) * scale`.

---

## 6. Errors

```json
{"error": {"code": "bad_fov", "message": "fov must be 0.01-0.3 degrees, got 5.0"}}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_query` | `q` is empty or too long. |
| 400 | `bad_coordinates` | Coordinates unreadable or out of range. |
| 400 | `bad_fov` | `fov` outside 0.01 to 0.3. |
| 400 | `bad_motion` | `pmra`, `pmdec`, `pm_epoch` not given together. |
| 400 | `bad_stretch` | Only one of `vmin`/`vmax`. |
| 400 | `bad_frame_id` | The id is not of the form `2025W35_2A_0611_1-D2`. |
| 404 | `name_not_found` | Resolve: nobody knows the name. |
| 404 | `unknown_frame` | No such image for this target. |
| 404 | `outside_image` | The view lies outside this image. Permanent. |
| 422 | `invalid_request` | A required parameter is missing or has the wrong type. |
| 502 | `resolver_unavailable` | The name service did not answer. |
| 502 | `upstream_error` / `irsa_unavailable` | IRSA failed or is down. Retry later. |
| 202 | (not an error) | The frame is still downloading: see the image endpoint. |

---

## 7. What to expect from the data

- **Few visits.** 3 to 4 per position so far (R Draconis, near the ecliptic pole, has more; its seasons merge into long ones). A visit is a run of images with no gap longer than 30 days.
- **Not every wavelength in every visit** (see `exact`). Frames of one visit at different wavelengths were taken up to a few weeks apart.
- **Bright stars are saturated** (Barnard's Star in several bands): the core carries `OVERFLOW`/`BLOOM` and, with `mask=true`, shows as a hole.
- **Pixels are 6.15″**: Barnard's Star shifts only about 1.7 pixels per year, so a blink shows small motions. Use a small field of view and scale up.
- **IRSA is the bottleneck.** About 12 s per uncached frame, and its services are sometimes unavailable for minutes (we saw `502` errors). The backend retries and caches everything it gets; coverage lists are saved on disk and survive restarts.
- More data: `docs/DATA_COVERAGE.md`.

## 8. Not in the MVP (can be added later)

Raw pixel values for client-side drawing, prefetching, a status endpoint, a credits/acknowledgement endpoint (put the acknowledgement text in the page footer for now), co-added and difference images, per-pixel quality flags, Gaia/WISE overlays, spectra, short target keys for embedding, comets and asteroids. Ideas for each are in the earlier design notes; none is needed for "enter a target, scrub through time and wavelength".

Known limits of the current implementation: frames and coverage lists are cached as files in `backend/cache/` (in Docker this folder is not a volume yet, so a container rebuild empties it); each (position, `fov`) is cached separately, so two users looking at slightly different coordinates do not share frames.
