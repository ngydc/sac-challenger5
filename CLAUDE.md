# CLAUDE.md

## Rules for SPHEREx work
- Before writing code that touches SPHEREx data, read the relevant file in `docs/spherex/` (index at the end) and say which one you used.
- Never guess FITS headers, keyword names, units, flag bits or wavelength conventions. Take them from the docs or from a real file's header. If neither is available, say so.
- If the docs don't cover something, say "the docs don't cover this". Don't fill the gap from memory. `docs/RESOURCES.md` and `docs/PROJECT_OVERVIEW.md` are team notes, not official sources.
- Where official sources disagree, see `docs/spherex/source-discrepancies.md` and read the value from the real file.
- Don't hard-code release names, pipeline versions, band edges or file paths: they change between releases. Read them from SIA2 results or headers.
- The user is new to SPHEREx. Explain each step in plain terms and define astronomy jargon the first time it appears.

## SPHEREx essentials
Everything below comes from `docs/spherex/`; the file to read for detail is in brackets.

**What it measures** [`user-guide-overview.md`, `paper-*.md`]
- NASA space telescope, launched March 2025. Maps the whole sky at 0.75-5.0 µm as low-resolution spectra (102 channels = 6 detectors x 17), with deeper "Deep Fields" at the ecliptic poles. Four all-sky surveys in a nominal 25-month mission.
- Detectors D1-D6 = bands 1-6, each 2040 x 2040 pixels, 6.15" per pixel, about 3.5° wide. Nominal ranges (µm): D1 0.75-1.09, D2 1.10-1.62, D3 1.63-2.41, D4 2.42-3.82, D5 3.83-4.41, D6 4.42-5.00. Sources differ slightly on the edges.
- **Wavelength changes across every image** (linear variable filters): one exposure is not one colour, each pixel has its own wavelength. D1+D4, D2+D5, D3+D6 see the same sky area at once.

**Releases** [`user-guide-data-releases.md`]
- QR1 (Jul 2025) is retired. QR2 (Oct 2025) reprocessed QR1 with much better calibration (PSF, gain). Never combine QR1 and QR2 files.
- **Use DR1 + QR3 for new work.** They supersede QR2 and form one uniformly processed set. DR1 (Nov 2026) = Surveys 1+2 reprocessed; QR3 (weekly since Sept 2026) = Surveys 3+4.
- QR2 is no longer searchable (download only until Feb 2027). Be careful mixing QR2 with DR1/QR3.

**File format** [`user-guide-data-products.md`, `tutorial-intro-spectral-images.md`]
- Main product: Level 2 spectral image, a multi-extension FITS (MEF), about 67-70 MB, one per detector per pointing (not all 6 always present). Primary HDU has no data but holds `VERSION`.
- Extensions: `IMAGE` (MJy/sr, zodiacal light NOT subtracted), `FLAGS` (per-pixel bit map), `VARIANCE` ((MJy/sr)^2), `ZODI` (model background, MJy/sr), `EPSF` (DR1/QR3 PSF table; QR2 has `PSF`), `WCS-WAVE` (wavelength lookup table, visualization only; for science use `CWAVE`/`CBAND` in the Spectral WCS product).
- Filename: `level2_<ObsID>D<det>_spx_l2b-v<ver>-<year-dayofyear>.fits`; ObsID = planning period + large slew + small slew (1-4).
- WCS: `WCS(header)` for sky; `WCS(header, fobj=hdulist, key="W")` then `.sip = None` for (wavelength, bandwidth). FITS pixels are 1-based, astropy 0-based.
- Flags: list them from the `FLAGS` header (`MSKN####`/`MSKD####`); table in `explanatory-supplement-extracts.md`. `SOURCE` (bit 21) is set on most pixels, so "any flag set" is not a bad-pixel test. `IMAGE` can contain NaN.
- Cutouts: `IMAGE`, `FLAGS`, `VARIANCE`, `ZODI` are cropped and `WCS-WAVE` adjusted, but the PSF extension is kept whole. Axes follow the parent exposure (not north-up). Not gzipped. `center`/`size` default to degrees. Parameters in `irsa-cutout-service.md`.

**Ways to get data** [`user-guide-data-access.md`, `irsa-cloud-access.md`]
- `astroquery.ipac.irsa` (recommended; `Irsa.query_sia(pos=(coord, radius), collection=[...])`, `Irsa.query_tap`) or `pyvo` for lower-level access.
- SIA2: `https://irsa.ipac.caltech.edu/SIA?COLLECTION=...&POS=circle+RA+Dec+radius`. Collections: `spherex_dr1`, `spherex_dr1_deep`, `spherex_dr1_cube`, `spherex_qr3`, `spherex_qr3_deep`. Result columns include `access_url` and `cloud_access`. SIA2 lags ingestion by about a day; the directories, Data Explorer and certain TAP queries (`spherex.artifact`/`spherex.plane`, see the cutouts notebook) see new data first. Calibration files are not in SIA2.
- Browsable directories: `https://irsa.ipac.caltech.edu/ibe/data/spherex/` (`dr1`, `qr3`, `qr2`), for `wget`/`curl`.
- AWS S3: bucket `nasa-irsa-spherex`, `us-east-1`, prefixes `dr1`/`qr3`/`qr2`, anonymous access (`--no-sign-request`). Cutouts work only on the on-premises copy, not S3.
- Web tools: SPHEREx Data Explorer (`irsa.ipac.caltech.edu/applications/spherex`), Cutout, Mosaic, Spectrophotometry and Source Discovery tools, MOST (moving objects). Links in `irsa-mission-page.md`.
- Remote FITS reads can time out: set `astropy.utils.data.conf.remote_timeout = 120` and retry transient errors (as the notebooks do).

**Known issues and notices** [`explanatory-supplement-extracts.md`, `irsa-psf-header-error.md`]
- QR1/QR2 PSF header error (up to ±5% photometry); fixed Mar 31 2026, marked `+psffix1` in `VERSION`; not in DR1/QR3. Use the ePSF for all images; `VERSION` < 7.0 has `PSF`, >= 7.0 has `EPSF`.
- Atmospheric lines (He 1.083 µm in bands 1-2, aurora) and shuttle glow are NOT subtracted; they cause stripes. Satellite streaks, ghosts, crosstalk, snowballs, `DICHROIC` edge pixels (bands 3-4) are partly masked. In QR2, snowball/bloom/halo masking exists only from planning period 2025W51_1A on.
- Combining QR2 and QR3: calibrations differ; a Flux Corrections product exists for this.

**Acknowledgement and DOI** [`irsa-dr1-overview.md`, `irsa-quick-release-overview.md`]
- Required text: "This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration."
- Cite the DOI of each release used: DR1 spectral images 10.26131/IRSA678, DR1 All-Sky Cube 10.26131/IRSA679, QR3 10.26131/IRSA662, QR2 10.26131/IRSA652, QR1 10.26131/IRSA629.

## Project
From `docs/PROJECT_OVERVIEW.md` and `README.md`. These are team notes and decisions, not official SPHEREx documentation; items marked (team) are the team's own measurements or plans and are not confirmed by `docs/spherex/`.
- **Team and event:** CHALLENGER5 (Can, Duc, Daniel, Maximilian). NASA Space Apps Challenge 2026, "Planet X and SPHEREx" (Advanced). Event dates Nov 14-15, so build the required MVP first, then optional features.
- **Goal:** a public web tool (no install) that takes sky coordinates (RA/Dec, sexagesimal and ideally decimal degrees), fetches SPHEREx images covering that spot, orders them by observation time and plays them as a short "blink" animation, so moving or varying objects (asteroids, comets, nearby stars, brown dwarfs) stand out. It is the SPHEREx counterpart of WiseView.
- **Acceptance tests (required targets):** Barnard's Star, Epsilon Indi B, WISE 0855 (all three move; catalogue positions are years out of date, so proper motion or a wide field is needed), RW Aurigae and R Draconis (static, test brightness change; the stretch must stay consistent across frames). Positions are in `docs/PROJECT_OVERVIEW.md` section 3.
- **SPHEREx data I use:** Level 2 spectral images from DR1 + QR3 (`spherex_dr1`, `spherex_qr3`, optionally the `_deep` collections), fetched as cutouts around the target. Not QR2. The All-Sky Cube has no time information, so it is at most a background or overview layer (team). Optional overlays: Gaia DR3 and WISE (Aladin Lite).
- **How I get it:** a FastAPI backend searches IRSA (SIA2; TAP only when data from the last day is needed), fetches and caches cutouts, and serves small frames to the frontend. The browser cannot call IRSA directly (team: no CORS headers were seen), so the proxy is required.
- **Environment:** Windows 11. Backend: Python 3.11+, FastAPI, astropy, in `backend/` (tests: `python -m pytest`). Frontend: Angular 22, Node 22.22+ or 24.15+, in `frontend/` (still an empty shell). `docker-compose.yml` runs frontend, backend and Postgres. The backend caches search results, cutouts and calibration files in Postgres (`backend/app/db.py`, schema in `backend/app/schema.sql`), shared by every feature; only the deep analysis's derived results (resampled arrays, pictures) are files under `backend/cache/analysis/`. Script outputs go in `backend/out/` (git-ignored, as is `*.fits`).
- **Backend API (MVP, done):** `GET /api/resolve`, `GET /api/coverage` (polled), `GET /api/frames/{id}/image.png`. Guide for the frontend: `docs/API.md`; measured data per test target: `docs/DATA_COVERAGE.md`.
- **Deep analysis (epoch maps):** `GET /api/analysis` (polled) and its pictures and spectra, with the same target parameters as the viewer; guide `docs/API_ANALYSIS.md`. Computation `backend/app/analysis.py` (pure), jobs and storage `backend/app/analysis_jobs.py` (shared coverage, cutout store and download queue; at most 2 jobs at once), endpoints `backend/app/analysis_api.py`. It also makes one colour picture per season from every wavelength (`/api/analysis/colour/{n}.png`, the viewer's "Colour" mode; frontend `colour-store.service.ts`). The backend computes the five test targets at start-up (`SPHEREX_PRECOMPUTE`). Shared basics (target, errors, constants) are in `backend/app/core.py`.
- **Output and audience:** a well usable public web page with RA/Dec entry, URL parameters (`?ra=...&dec=...&fov=...`) for sharing, and a blink player (play/pause/step). Good unser experience and nice visualization is the primary goal. Optional features in priority order: adjustable field of view, per-detector co-adds, add/subtract images from different epochs, Gaia/WISE overlays, metadata display (flags, dates), on-the-fly spectra, easy updates with new releases (no hard-coded datasets).
- **Decided (team, see `docs/API.md`):** a frame is one image of one detector; the frontend has a time slider (visits, i.e. observing seasons about 6 months apart, split at gaps over 30 days) and one wavelength slider across all detectors. Moving targets: the view stays fixed on the sky and the proper motion only moves a predicted-position marker; named targets are moved from J2000 to the current year. Latency (measured 2026-11-15, `docs/FETCH_SPEED.md`): first coverage lookup about 6 s (stored per position, shared by every fov); cutouts are made from byte ranges of the S3 copy, about 1-3 s each, 8 in parallel, and every frame of a view is prefetched once its coverage is ready (350 frames in about 75 s); IRSA itself (file server, then cutout service) is only the fallback, at most 3 requests at a time (it answers 503 when hit harder); everything cached. Epochs per target: measured in `docs/DATA_COVERAGE.md`.
- **Open questions:** hosting and public access; IRSA's actual rate limit (not measured); the Space Apps judging criteria (not yet checked).

@docs/INDEX.md
