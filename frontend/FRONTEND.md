# Frontend: Challenger5

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
  └── Angular app (Challenger5)
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
    index.html             page shell, title "Challenger5", favicon.svg
    main.ts                bootstraps the App with appConfig
    styles.scss            global styles and color tokens (dark theme)
    app/
      app.ts/.html/.scss   app shell: header with title, <main> with router outlet
      app.config.ts        providers: error listeners, router, HttpClient (fetch)
      app.routes.ts        '' → Home (lazy), '**' → redirect to ''
      core/
        api.config.ts      API_BASE_URL = '/api'
        examples.ts        the five example targets (start page and search suggestions)
        models/            api.models.ts: types of the backend responses
        services/          api.service.ts (all /api calls, picture cache, loaded/pending frame ids), viewer-state.service.ts (shared signals), history.service.ts (past searches, localStorage)
        utils/             frames.ts: pickFrame, bands, frames of a season (+ spec)
      pages/
        home/              layout: full-screen stage, brand/home button, search, HUD, menu buttons and drawer with tabs, keyboard shortcuts
      components/
        viewer/            F1: the start page (slogan), the picture, predicted-position ring, loading/progress/error states
        search-bar/        F4: one search box for names and coordinates, with suggestions (F10)
        logo/              the CHALLENGER5 mark; with [spin] it is the loading indicator (F12)
        history-panel/     F10: menu tab with all past searches
        about-panel/       F11: menu tab explaining SPHEREx, the data and the citation
        control-panel/     F2/F3: band chips, sliders, playback, frame details, settings
        frame-plot/        SVG plot of all images of the band (season x wavelength), click to jump
  public/                  static assets (favicon.svg: same drawing as the logo component)
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
| F9 | Start page with slogan; the brand (top left) is the home button | done |
| F10 | Search suggestions (last 3 searches + 5 examples) and History tab | done |
| F11 | "About SPHEREx" tab | done |
| F12 | Loading indicator in the app's look (the logo with a turning orbit) | done |
| F13 | Live "loaded" state of the dots in the frame plot | done |
| F14 | Deep Analysis drawer: difference pictures per detector / all combined, status and compute on click, explanation, spectrum, metadata | done |

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

### F9-F13 (added 2026-11-15)

- **F9 Start page / home:** the idle screen shows the logo, the slogan and the example targets. Clicking the brand (`ViewerState.reset()`) forgets the target, clears the page URL and returns there.
- **F10 Suggestions and history:** while the search box has the focus it lists the last 3 searches and always the 5 examples (arrow keys + Enter, Esc closes). `HistoryService` stores successful searches (max 50, newest first, no duplicates) in `localStorage` under `challenger5.history`. The History tab lists them all; click to search again, ✕ removes one.
- **F11 About SPHEREx:** mission facts, what the tool does, the data and links, known limits, the required acknowledgement and DOIs. Text and links are taken from `docs/spherex/`; update it when the releases in use change.
- **Menu tabs:** the buttons at the bottom right (About SPHEREx, History, Controls) each open the drawer on their tab; the drawer stays on the right, so the stage stays on the left. A new tab = one entry in `TABS` (`home.ts`) plus a `@case` in the drawer. The buttons are a labelled stack on a wide stage and an icon row otherwise, so they never cover the picture.
- **F12 Loader:** `<app-logo [spin]="true">` is used for the search button, the lookup/coverage panel, the first image and (small, top right of the picture) a frame that takes longer than 0.7 s.
- **No dimming while loading:** the shown picture stays untouched until the next one has arrived; it is then swapped at once.
- **F13 Live dots:** a dot is green when its image is loaded and pulses amber while it loads. `ViewerState.cacheOf(frame)` combines what this page loaded or is loading (`ApiService.loaded` / `pending`, immediate) with a `/coverage` refresh every 2 s while downloads run and every 8 s otherwise (paused while the browser tab is hidden).

### F5: Responsive web design

- The app works on desktop, tablet and phone.
- The visualization always uses the available space and keeps its aspect ratio.
- On small screens the slider menu opens as an overlay or bottom sheet instead of a side bar; controls are large enough for touch.
- Sliders and the search bar must work with mouse, touch and keyboard.

### F14: Deep Analysis (difference pictures)

A second drawer on the main page, opened with its own **Deep Analysis** button in the menu dock (between History and Controls) (side drawer from 900 px, bottom sheet below; only one of the two drawers is open at a time). Built against `docs/API_EPOCHS.md` (`/api/config`, `/api/epochs`, `/api/compute`, `/api/diff`, `/api/spectrum`).

- **What it shows:** only the difference pictures (latest minus first epoch), **per detector** (default) or **all combined**. While the drawer is open, the stage shows the difference tiles instead of the slider picture and the slider HUD and keys are off. Click a tile to enlarge it with its metadata; click a pixel for its spectrum per epoch.
- **Position:** the object searched on the main page (`GET /api/resolve` result), with the epoch maps' own field of view (`default_fov` from `/api/config`), because that is what the precomputed results use. For the five test targets this hits the precomputed cache.
- **Only the start button computes.** Opening the drawer calls `GET /api/epochs`. A computed result (e.g. the five examples) or a computation already running is shown at once, without a button. Otherwise the drawer shows **"Start deep analysis (downloads data)"** with a notice that it takes tens of minutes; that click calls `POST /api/compute`, then the drawer polls every 4 s, shows progress and the remaining time (measured rate after 60 s, before that the documented ~20 images/min) and the stage adds each detector as it is ready.
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
- **Deep-space theme:** near-black blue background with a CSS starfield and nebula glow (`.sky`), glass panels (`.glass`), an indigo/cyan/violet accent gradient (`--grad`). Colors are CSS variables in [`styles.scss`](src/styles.scss) (`--bg`, `--fg`, `--muted`, `--border`, `--accent*`, `--ready`, ...). New colors are added there as variables, not hard-coded in components. `--no-data` and `--masked` match the colours the backend paints into the pictures; do not restyle them.
- Fonts (self-hosted via `@fontsource-variable/*`, registered in `angular.json`, so no request to a font CDN): **Space Grotesk** for headings and the brand (`--font-display`), **Inter** for text (`--font-body`), **JetBrains Mono** for numbers and identifiers (`--font-mono`, class `.num`).
- Motion is small and functional (twinkling stars, loader, hover glow) and switched off with `prefers-reduced-motion`.
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
| 2026-11-15 | Renamed to Challenger5, new logo/favicon and deep-space design. Added F9-F13: start page with slogan and home button, search suggestions and History tab, About SPHEREx tab, logo loader, live frame-plot dots. The picture is no longer dimmed while the next one loads. |
| 2026-11-15 | F14 Deep Analysis drawer (difference pictures) as its own button in the menu dock; the slider viewer stays the main page. |
