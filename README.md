# Challenger5: Planet X and SPHEREx

A web tool that shows what the [SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html) space telescope saw at any position on the sky, ordered by observation time and wavelength. Step through or play the images and objects that **move** (nearby stars, brown dwarfs, asteroids) or **change brightness** (variable stars) stand out. It is our entry for the NASA Space Apps Challenge 2026, [Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/), and is in the spirit of WiseView for the WISE telescope.

Team CHALLENGER5: Can, Duc, Daniel, Maximilian.

## What it does

- **Search** by name (`Barnard's Star`) or by coordinates (RA/Dec in degrees or sexagesimal). Names of fast-moving objects are moved to where the object is today, using its proper motion.
- **Time and wavelength sliders.** SPHEREx observes every spot on the sky about every six months, each time as a set of narrow infrared colours (0.75 to 5 µm). One slider steps through the observing seasons, the other through the wavelengths. A blink player cycles through either.
- **Adjustable field of view, image options and flags**, and a history of recent searches.
- **Deep analysis (epoch maps).** Averages the images of each observing epoch and detector, and combines the epochs into one colour picture and a difference image: a star that moved shows a colour fringe, a star that changed brightness a uniform colour. Spectra at any pixel.
- **Colour view.** Combines every wavelength of one observing season into a single picture: short infrared wavelengths blue, long ones red, typical stars white, saturated pixels masked. Blink through the seasons in colour to spot what moves or looks unusual. A qualitative view; for measurements use the deep analysis.
- **Shareable links.** The page address holds the search, e.g. `http://localhost:4200/?q=Barnard's Star&fov=0.08`.

The five targets we test with are built in: Barnard's Star, Epsilon Indi B, WISE 0855-0714 (all three move), RW Aurigae and R Draconis (brightness changes). Their positions and what to expect are in [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md), the images available for each in [docs/DATA_COVERAGE.md](docs/DATA_COVERAGE.md).

## Run it

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with Compose). From the repository root:

```bash
docker compose up --build
```

Then open **http://localhost:4200**. The first build takes a few minutes. The backend API and its interactive documentation are at http://localhost:8000/docs.

What to expect on the first run:

- The images come from NASA's public SPHEREx archive (IRSA), so the first visit to a position downloads data: about 2 minutes for a new position, and it is cached afterwards. At start-up the backend also prepares the five test targets in the background, so they get quicker the longer it runs.
- The tool depends on IRSA's search service. If that service is down, the backend says so and retries by itself; positions that are already cached keep working. See [Cache snapshot](#cache-snapshot-faster-first-start) to start with data already in place.
- `docker compose ps` shows `healthy` for the backend and the database when they are ready.

Other things you may want:

```bash
docker compose --profile prod up --build frontend-prod   # production build served by nginx: http://localhost:8080
docker compose down                                      # stop (the cache is kept); add -v to delete it
```

If you change `frontend/package.json` (new package) and the frontend container fails to find it, rebuild its package volume once: `docker compose up -d --build --renew-anon-volumes frontend`.

**Ports.** The services are reachable from your own computer only: frontend 4200, backend 8000, Postgres 5432, production frontend 8080. If one is already in use, copy `.env.example` to `.env` and set `FRONTEND_PORT`, `BACKEND_PORT`, `DB_PORT` or `PROD_PORT`.

## Cache snapshot (faster first start)

The backend stores everything it downloads (search results, image cutouts, calibration files) in Postgres, and the deep-analysis results as files under `backend/cache/analysis/`. You can copy that cache to another machine as one file:

```bash
# on the machine that has the data (the stack running):
docker compose exec backend python -m app.cache_transfer export cache/cache_export.tar.gz
#   -> the file appears as backend/cache/cache_export.tar.gz (several hundred MB)

# on the new machine:
docker compose exec backend python -m app.cache_transfer import cache/cache_export.tar.gz
docker compose restart backend
```

`import` merges into what is already there (add `--replace` for an exact copy). It also accepts an `http(s)://` address. To load a snapshot automatically on the first start, set `SPHEREX_SEED_URL` (a file or address) in `.env`: it is used only when the database is empty. Snapshots should be made with the same version of the code that reads them, because analysis results are tied to the code that computed them.

## Run without Docker

You need Python 3.11+ and Node.js 22.22+ or 24.15+. The backend still needs Postgres: start only the database with `docker compose up -d db`.

```bash
# backend (http://localhost:8000)
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# frontend (http://localhost:4200, /api is proxied to localhost:8000), in a second terminal
cd frontend
npm install
npm start
```

The backend finds the database at `localhost:5432` (change it with `DATABASE_URL`) and creates its tables itself.

## Tests

```bash
cd backend && python -m pytest   # install requirements-dev.txt first; database tests are skipped when no database runs
cd frontend && npm test          # Vitest
```

## How it works

The browser cannot call IRSA directly (it sends no CORS headers), so the backend does the work:

1. **Resolve**: a name or coordinates become a target (position, field of view, proper motion).
2. **Coverage**: IRSA is searched for every SPHEREx image that contains the position (SIA2 over the current releases, DR1 and QR3). For each image the backend reads the wavelength at the target.
3. **Frames**: a small cutout around the target is read from IRSA's copy on AWS S3 (only the needed bytes), cached, and rendered as a picture.
4. **Deep analysis**: the cutouts are resampled onto one grid, averaged per epoch and detector, and combined into the epoch maps.

The frontend calls the backend only through relative `/api/...` paths: the Angular dev server forwards them in development, nginx in production.

```
backend/                    FastAPI backend (Python)
  app/main.py               app setup, error handlers, start-up warm-up
  app/api.py                /api/resolve, /api/coverage, /api/frames/{id}/image.png
  app/analysis_api.py       /api/analysis and its pictures and spectra
  app/service.py            coverage search, download queue, rendering
  app/spherex.py            SPHEREx data access (SIA2 search, wavelength lookup, reprojection)
  app/cutout.py             cutouts made from byte ranges of the image files
  app/analysis.py           the epoch-map computation (pure functions)
  app/analysis_jobs.py      analysis jobs and their stored results
  app/resolver.py, presets.py   names and coordinates -> target; the five test targets
  app/core.py               shared basics: target, errors, constants
  app/precompute.py         prepares the test targets (also runs at start-up)
  app/db.py, schema.sql     Postgres cache
  app/cache_transfer.py     export and import of the cache
  scripts/                  one-off measurement scripts behind docs/DATA_COVERAGE.md and docs/FETCH_SPEED.md
  tests/                    pytest
frontend/                   Angular 22 app (standalone components, SCSS, Vitest)
  src/app/pages/            the page (home)
  src/app/components/       search bar, viewer, controls, epoch maps, history, about panel
  src/app/core/             API client, state, models
  Dockerfile, nginx.conf    dev server (ng serve) and production image (nginx)
docker-compose.yml          frontend, backend and Postgres
docs/                       documentation (below)
```

## Documentation

- [Backend API](docs/API.md) and [deep-analysis API](docs/API_ANALYSIS.md): endpoints, call pattern, example responses. Live reference at `/docs` when the backend runs.
- [Frontend notes](frontend/FRONTEND.md): features, architecture and design rules of the Angular app.
- [Project overview](docs/PROJECT_OVERVIEW.md): goals, test targets, risks.
- [Data coverage](docs/DATA_COVERAGE.md): what SPHEREx data exists for the five test targets.
- [Fetch speed](docs/FETCH_SPEED.md): measurements of downloading and caching.
- [Resources](docs/RESOURCES.md): our measurements of the data and IRSA services.
- [Official SPHEREx documentation](docs/INDEX.md): local copies of the archive guide and notebooks, with an index by question.
- `docs/submission/`: the pitch slides and logos.

## Data and acknowledgement

All images are public SPHEREx Level 2 data from the NASA/IPAC Infrared Science Archive (IRSA): [DR1 spectral images](https://doi.org/10.26131/IRSA678) and [QR3](https://doi.org/10.26131/IRSA662).

> This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration.

## Use of AI

We used AI (super intelligence, SI) tools to implement this project. Idea and decisions about what to build, the architecture of our project and how it should behave came from the team; the AI was used as a tool to help us write and change the code.


- **Code:** large parts of implementing the backend (`backend/`) and the frontend (`frontend/`) were written or changed with the help of Claude Code, from our instructions, and then reviewed, tested and adjusted by the team. This includes the tests and the Docker setup.
- **Documentation:** much of the technical documentation in `docs/` and this README was drafted with the same tool. The copies of the official SPHEREx documentation in `docs/spherex/` were fetched with its help; they are NASA/IPAC's text, not ours.
- **Metadata:** commits made with AI help carry a `Co-Authored-By: Claude` line in the git history. `CLAUDE.md` holds the instructions the AI followed in this repository (for example: take every SPHEREx detail from the official documentation, never from memory).

## License

The code in this repository is released under the [MIT License](LICENSE). This does not cover third-party material: the SPHEREx data and the copied official documentation in `docs/spherex/` belong to NASA/IPAC, and the logos in `docs/submission/` to their owners.
