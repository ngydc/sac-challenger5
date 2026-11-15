# sac-challenger5 — Planet X and SPHEREx


Teamname: CHALLENGER5
Team members: Can, Duc, Daniel, Maximilian

NASA Space Apps Challenge 2026: a public web tool that shows [SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html) sky images of a given RA/Dec as a time-ordered "blink" animation, so moving and varying objects are easy to spot.

Challenge: https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/

## Docs

- [Project overview](docs/PROJECT_OVERVIEW.md): goal, test targets, features, risks, MVP checklist
- [Resources](docs/RESOURCES.md): our own measurements of the SPHEREx data and IRSA services, with pointers to the official docs
- [Data coverage](docs/DATA_COVERAGE.md): what data exists for the five test targets
- [Official SPHEREx docs](docs/INDEX.md): local copies, with an index by question
- [Backend API](docs/API.md): the endpoints the frontend uses (sliders, frames), with live docs at `/docs` when the backend runs

## Stack

| Part | Tech | Folder |
|---|---|---|
| Frontend | Angular | `frontend/` |
| Backend | Python, FastAPI | `backend/` |

The browser can't call IRSA directly (no CORS headers), so the backend searches IRSA, fetches and caches cutouts, and serves small frames to the frontend.

## Getting started

Requirements: Node.js 22.22+ or 24.15+ (Angular 22), Python 3.11+, optionally Docker Desktop.

**Backend**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000  (API docs at /docs)
```

The backend caches everything (search results, cutouts, calibration files) in Postgres. Outside Docker, start just the database with `docker compose up -d db`; the backend connects to it on `localhost:5432` by default (override with `DATABASE_URL`) and creates its tables itself (`backend/app/schema.sql`). Tests: `python -m pytest` in `backend/` (the database tests are skipped when no database is running).

**Frontend** (Angular 22, local)
```bash
cd frontend
npm install
npm start                       # http://localhost:4200  (/api is proxied to localhost:8000)
```

**Everything with Docker Desktop** (from the repo root)
```bash
docker compose up --build                                  # frontend (live reload) http://localhost:4200, backend http://localhost:8000, Postgres
docker compose --profile prod up --build frontend-prod     # production frontend build via nginx: http://localhost:8080
```

The frontend calls the backend only through relative `/api/...` paths. In development the Angular dev server forwards them (`frontend/proxy.conf.mjs`); in production nginx does (`frontend/nginx.conf`). So backend routes should live under `/api`.

## Layout

```
backend/              FastAPI backend (Python)
  app/main.py         app setup, error handlers
  app/api.py          the three MVP endpoints: /api/resolve, /api/coverage, /api/frames/{id}/image.png
  app/service.py      coverage search, download queue, rendering
  app/spherex.py      SPHEREx data access (SIA2 search, cutouts, wavelength lookup, reprojection)
  app/resolver.py     names and coordinates -> target (app/presets.py: the five challenge targets)
  app/db.py           Postgres cache (schema: app/schema.sql)
  scripts/            exploration scripts behind docs/DATA_COVERAGE.md
  tests/              pytest
frontend/             Angular 22 app (standalone components, SCSS, Vitest)
  src/app/pages/      routed pages (home)
  src/app/core/       app-wide config/services (API_BASE_URL)
  Dockerfile          targets: dev (ng serve), prod (nginx)
docker-compose.yml    frontend, backend and Postgres (db)
docs/                 project overview, API guide (API.md), measured data coverage, official SPHEREx docs (spherex/, index in INDEX.md)
```
