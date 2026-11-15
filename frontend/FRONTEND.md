# Frontend: SPHEREx Blink

Documentation for the Angular frontend. It covers only the frontend; the backend (FastAPI, IRSA access, caching, image processing) is documented in [`backend/`](../backend/) and the [README](../README.md).

> **Living document.** Features and details will be added and changed during the project. Each feature has an ID (`F1`, `F2`, ...) and a status so changes are easy to track. Update this file when the frontend changes.

## Contents

1. [Purpose](#1-purpose)
2. [Tech stack](#2-tech-stack)
3. [Architecture](#3-architecture)
4. [Features](#4-features)
5. [Interface to the backend](#5-interface-to-the-backend)
6. [Design and UX rules](#6-design-and-ux-rules)
7. [Development](#7-development)
8. [Conventions](#8-conventions)
9. [Open questions](#9-open-questions)
10. [Changelog](#10-changelog)

---

## 1. Purpose

The frontend **visualizes the data the backend delivers**. The backend fetches SPHEREx images from IRSA, processes them and sends ready-to-display images; the frontend shows the image for the selected point in time and wavelength. Moving the time slider steps through the observations of the searched object, so moving or varying objects become visible.

The frontend does **not** talk to IRSA, read FITS files or compute image data. All data comes from the backend via `/api/...`.

The **visualization is the main focus** of the UI: it fills the screen, all controls are secondary and can be hidden.

## 2. Tech stack

Taken from [`package.json`](package.json), [`angular.json`](angular.json) and the Docker files.

| Area | Tool | Version / notes |
|---|---|---|
| Framework | Angular | 22.2 (standalone components, no NgModules) |
| Language | TypeScript | ~6.0 |
| Styles | SCSS | global styles in `src/styles.scss`, one `.scss` per component |
| Reactive data | RxJS | ~7.8 |
| HTTP | Fetch API in `ApiService` | `fetch` instead of `HttpClient`, because the image call needs response headers, a 202 retry loop and `AbortController` (as in `docs/API.md`). `HttpClient` stays provided. |
| Routing | Angular Router | lazy-loaded pages (`loadComponent`) |
| Build / dev server | `@angular/build` (Angular CLI 22.2.7) | application builder, dev server with proxy |
| Unit tests | Vitest 5 + jsdom | run with `ng test` |
| Formatting | Prettier 3.8 | `printWidth: 100`, single quotes, Angular parser for HTML |
| Editor | `.editorconfig` | 2 spaces, UTF-8, single quotes in TS |
| Container (dev) | Node 24 Alpine | `ng serve` with live reload (polling for Windows bind mounts) |
| Container (prod) | nginx 1.28 Alpine | serves the static build, forwards `/api` |
| Runtime requirement | Node.js | 22.22+ or 24.15+ |

No UI component library and no image/astronomy library are installed yet. If one is added (e.g. for sliders or Aladin Lite for overlays), list it here.

## 3. Architecture

### 3.1 Overview

```
Browser
  └── Angular app (SPHEREx Blink)
        ├── App shell (header + <router-outlet>)
        ├── Pages (routed, lazy-loaded)
        │     └── Home  → viewer, slider panel, object search
        ├── Components (reusable UI parts)
        └── Core (app-wide config and services)
              └── API_BASE_URL = '/api'
                     │
                     ▼  relative /api/... calls
        Dev:  Angular dev server proxy (proxy.conf.mjs) ─┐
        Prod: nginx (nginx.conf) ────────────────────────┴─► Backend (FastAPI)
```

The frontend never knows the backend's host. It only calls relative `/api/...` paths:
- **Development:** [`proxy.conf.mjs`](proxy.conf.mjs) forwards `/api` to `http://localhost:8000` (in Docker: `API_TARGET=http://backend:8000`).
- **Production:** [`nginx.conf`](nginx.conf) forwards `/api/` to `http://backend:8000` and falls back to `index.html` for all other paths (Angular routing).

### 3.2 Folder structure

Current state, plus the planned folders (marked *planned*).

```
frontend/
  src/
    index.html             page shell, title "SPHEREx Blink"
    main.ts                bootstraps the App with appConfig
    styles.scss            global styles and color tokens (dark theme)
    app/
      app.ts/.html/.scss   app shell: header with title, <main> with router outlet
      app.config.ts        providers: error listeners, router, HttpClient (fetch)
      app.routes.ts        '' → Home (lazy), '**' → redirect to ''
      core/
        api.config.ts      API_BASE_URL = '/api'
        models/            api.models.ts: types of the backend responses
        services/          api.service.ts (all /api calls, picture cache), viewer-state.service.ts (shared signals)
        utils/             frames.ts: pickFrame, bands, frames of a season (+ spec)
      pages/
        home/              layout: full-screen stage, search, HUD, collapsible menu, keyboard shortcuts
      components/
        viewer/            F1: the picture, predicted-position ring, loading/progress/error states
        search-bar/        F4: one search box for names and coordinates
        control-panel/     F2/F3: band chips, sliders, playback, frame details, settings
        frame-plot/        SVG plot of all images of the band (season x wavelength), click to jump
  public/                  static assets (favicon)
  proxy.conf.mjs           dev proxy for /api
  nginx.conf               prod server config
  Dockerfile               targets: deps, dev, build, prod
```

### 3.3 Architecture rules

- **Standalone components** only; each component has its own `.ts`, `.html` and `.scss`.
- **Pages** (`pages/`) are routed and lazy-loaded; **components** (`components/`) are reusable building blocks without routing.
- **All backend calls go through services in `core/`**, never directly from components, and always use `API_BASE_URL`.
- **Shared state** (searched object, selected point in time, selected wavelength, current image) lives in a service, so viewer, sliders and search stay in sync. Angular signals are the preferred tool for this state; RxJS for HTTP streams.
- **No science logic in the frontend.** Which images form a frame, how they are stretched and colored is decided by the backend. The frontend only sends parameters and displays the result.
- **No hard-coded data values.** Values that depend on the data (which points in time exist for an object, the wavelength in µm of each channel) come from the backend, because they change between SPHEREx releases and between objects.

## 4. Features

Status: **planned** (agreed, not built), **in progress**, **done**. New features get the next free ID.

| ID | Feature | Status |
|---|---|---|
| F1 | Full-screen visualization | done |
| F2 | Time slider (observing seasons of the searched object) | done |
| F3 | Wavelength slider (continuous, in µm, across all detectors) | done |
| F4 | Object search | done |
| F5 | Responsive web design | done |
| F6 | Blink / wavelength sweep playback, keyboard shortcuts | done |
| F7 | Frame details, stretch, mask, predicted-position ring, field of view (in the menu) | done |
| F8 | Shareable page URL (`?q=&fov=&visit=&wl=`) | done |
| F9 | Deep Analysis drawer: difference pictures per detector / all combined, status and compute on click, explanation, spectrum, metadata | done |

F2 and F3 are the two sliders for now. They sit in a **collapsible menu** (e.g. a side drawer or overlay) that is closed or small by default, so the visualization stays the focus. The menu is built so that more controls can be added later.

### F1: Full-screen visualization

- Shows the image from the backend for the **selected point in time (F2)** and **selected wavelength (F3)**.
- The visualization takes up the **whole available screen**; it is the main element of the app. All other UI elements (slider menu, search) are placed on top of it or beside it and must not shrink it permanently.
- Optional: a real full-screen mode via the browser Fullscreen API.
- Shows a loading state while an image is being fetched and an error message if the backend returns no data (the backend can take several seconds per image).

### F2: Time slider

- A slider over the **points in time (observations) available for the searched object**, ordered by observation time.
- Each slider position is one point in time; moving the slider shows the image of that observation in F1.
- Shows the current value as a readable date (and the position, e.g. `3 / 11`).
- The list of points in time comes from the backend after an object search (F4); it differs from object to object and is not hard-coded. The slider is disabled until an object has been searched.

### F3: Wavelength slider

- **Changed (2026-11-14):** not 102 channel steps but one continuous axis in µm, from `coverage.wavelength_range_um` (about 0.74 to 5.0 µm), as the backend API defines it (`docs/API.md` section 1). Every SPHEREx pixel has its own wavelength, so channels are not a useful unit here.
- The frontend picks the frame of the current season nearest to the slider value (`pickFrame`, no request). If none lies within 2 bandwidths, a notice shows the nearest wavelength.
- Band chips D1-D6 above the sliders jump into a detector's range; their ranges and counts come from the data.

**Notes for both sliders:**
- Changes are sent to the backend as parameters; to avoid a request on every pixel of slider movement, requests should be debounced or sent on release.
- Both sliders must work with mouse, touch and keyboard (arrow keys move one step).

### F4: Object search

- A search bar where the user types an object name, e.g. `Barnard's Star`.
- The frontend sends the name to the backend; the **backend** finds the matching coordinates/parameters and returns them.
- The frontend then loads the available points in time for the time slider (F2) and shows the first image in F1.
- Handles "not found" and errors with a clear message. Optional later: suggestions while typing, recent searches.

### F5: Responsive web design

- The app works on desktop, tablet and phone.
- The visualization always uses the available space and keeps its aspect ratio.
- On small screens the slider menu opens as an overlay or bottom sheet instead of a side bar; controls are large enough for touch.
- Sliders and the search bar must work with mouse, touch and keyboard.

### F9: Deep Analysis (difference pictures)

A second drawer on the main page, opened with the **Deep Analysis** button above **Controls** and working the same way (side drawer from 900 px, bottom sheet below; only one of the two drawers is open at a time). Built against `docs/API_ANALYSIS.md` (`GET /api/analysis`, `/api/analysis/{bundle}/diff.png`, `/api/analysis/spectrum`), which takes the same target parameters as the slider picture.

- **What it shows:** only the difference pictures (latest minus first epoch), **per detector** (default) or **all combined**. While the drawer is open, the stage shows the difference tiles instead of the slider picture and the slider HUD and keys are off. Click a tile to enlarge it with its metadata; click a pixel for its spectrum per epoch.
- **Position:** the view of the main page: the same target as the slider picture (`ViewerState.target()`: position from `GET /api/resolve`, its field of view, its proper motion). For the five test targets at their default field of view this hits the backend's precomputed results.
- **Only the start button computes.** Opening the drawer calls `GET /api/analysis?start=false`. A computed result (e.g. the five examples) or a computation already queued or running is shown at once, without a button. Otherwise the drawer shows **"Start deep analysis (downloads data)"** with a notice that it takes about two minutes; that click calls `GET /api/analysis` (which starts it), then the drawer polls every 4 s, shows progress and the remaining time (measured rate after 60 s, before that ~3 images/s) and the stage adds each detector as it is ready. While a complete result is recomputed with new images (`refreshing`), the old pictures stay and the panel says so.
- **Spectrum clicks:** the picture row is counted from the top in the page, and converted to the API's row-from-the-bottom in `EpochsApi.spectrum`.
- **Colours:** red = brighter in the first epoch, blue = brighter in the latest, white = unchanged (backend since `PIPELINE_VERSION` 8). A moving object shows red where it was and blue where it went. No data (transparent) is drawn hatched, never black. The frontend never rescales brightness.
- **Explanation:** collapsible block in the drawer ("?" in the drawer head reopens it), with one sentence per test target from `core/examples.ts` (`seen`, written from the precomputed pictures; update it when they change). Acknowledgement text and release DOIs at the end of the drawer.
- Not in the URL yet (the main page writes `?q=&fov=&visit=&wl=` itself).
- Code: `components/epochs/` (`deep-panel`, `deep-stage`, `bundle-tile`, `bundle-detail`, `spectrum-panel`, `sky-image`, `epoch-legend`, `site-footer`), `core/services/epochs-store.service.ts`, `core/services/epochs-api.service.ts`, `core/models/epochs.models.ts`; shared styles in `src/styles/_epochs.scss`; wiring in `pages/home/`.

### Possible later features

From [`docs/PROJECT_OVERVIEW.md`](../docs/PROJECT_OVERVIEW.md) (sections 3-4). Not decided yet; move them into the table above when they are planned.

- URL parameters for sharing a view (`?ra=...&dec=...&fov=...`)
- Adjustable field of view (FOV)
- Overlays from other surveys (Gaia DR3, WISE, e.g. with Aladin Lite)
- Metadata display (observation dates, flags)
- Difference images / comparing epochs
- Spectrum for a clicked source

## 5. Interface to the backend

Defined in [`docs/API.md`](../docs/API.md) (live reference: `/docs` of the running backend). The frontend uses three calls:

| Needed for | Call | Gives |
|---|---|---|
| F4 | `GET /api/resolve?q=` | the target (`ra, dec, fov, pmra, pmdec, pm_epoch`), note, warnings |
| F2, F3 | `GET /api/coverage?<target>` (polled every 1.5 s until `ready`) | `visits[]` (time slider), `wavelength_range_um` (wavelength slider), `frames[]` |
| F1 | `GET /api/frames/{id}/image.png?<target>&mask=&vmin=&vmax=` | the PNG (47 px, scaled up with CSS `pixelated`) and `X-*` headers (wavelength, time, flags, target pixel, stretch) |

How the frontend uses it:
- **Stretch "same for all seasons"** (default): the blink set (each season's frame at this wavelength) is drawn with the brightness range of the first season's frame, so brightness changes stay visible (needed for RW Aurigae, R Draconis).
- On a new wavelength the whole blink set is requested at once, so blinking afterwards is instant. Loaded pictures are kept in memory for the session.
- Slider changes are debounced (150 ms); a superseded image request is aborted.
- Mask is **off** by default (the reference design); the API's default is on.

Rules:
- All paths start with `/api` (see `API_BASE_URL` in [`core/api.config.ts`](src/app/core/api.config.ts)).
- Response types are written down as TypeScript interfaces in `core/models/`.

## 6. Design and UX rules

- **Visualization first:** controls are secondary and can be collapsed.
- **Dark theme** (suits sky images). Colors are CSS variables in [`styles.scss`](src/styles.scss): `--bg`, `--fg`, `--muted`, `--border`. New colors are added there as variables, not hard-coded in components.
- Font: system font stack (`system-ui`, `Segoe UI`, `Roboto`, ...).
- Clear loading and error states; never a blank screen without explanation.
- Accessible: keyboard operable, visible focus, labels for all sliders and inputs.
- Component styles stay small (build budget: warning at 4 kB, error at 8 kB per component style). Shared styles go into `styles.scss`.

## 7. Development

From the `frontend/` folder:

```bash
npm install
npm start          # dev server at http://localhost:4200, /api is proxied to localhost:8000
npm run build      # production build into dist/frontend/browser
npm run watch      # development build in watch mode
npm test           # unit tests (Vitest)
```

With Docker (from the repository root):

```bash
docker compose up --build                                  # dev server with live reload: http://localhost:4200
docker compose --profile prod up --build frontend-prod     # production build via nginx: http://localhost:8080
```

The frontend starts without the backend, but all `/api` calls fail until the backend runs.

## 8. Conventions

- Component selector prefix: `app-` (from `angular.json`).
- Formatting with Prettier (`.prettierrc`); 2-space indentation (`.editorconfig`).
- Strict TypeScript compiler options (`noImplicitReturns`, `noImplicitOverride`, `noPropertyAccessFromIndexSignature`, ...).
- Unit tests next to the code as `*.spec.ts`.
- Generate new parts with the CLI, e.g. `ng generate component components/viewer`.

## 9. Open questions

- Decided: menu is a side drawer on screens ≥ 900 px (the picture shrinks while it is open) and a bottom sheet below; no UI library (plain Angular + native range inputs).
- Decided: no image at a wavelength in a season → nearest frame plus a notice.

## 10. Changelog

| Date | Change |
|---|---|
| 2026-11-14 | First version: architecture, tech stack, features F1-F5. |
| 2026-11-14 | Video player removed. Sliders reduced to two: time slider (F2) and wavelength slider 1-102 (F3); RGB, band count, RA and Dec sliders removed. |
| 2026-11-14 | Implemented F1-F8 against `docs/API.md`; F3 changed to a continuous µm slider. |
| 2026-11-15 | F9 Deep Analysis drawer (difference pictures) next to Controls; the slider viewer stays the main page. |
