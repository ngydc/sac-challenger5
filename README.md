# sac-challenger5 — Planet X and SPHEREx


Teamname: CHALLENGER5
Team members: Can, Duc, Daniel, Maximilian

NASA Space Apps Challenge 2026: a public web tool that shows [SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html) sky images of a given RA/Dec as a time-ordered "blink" animation, so moving and varying objects are easy to spot.

Challenge: https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/

## Docs

- [Project overview](docs/PROJECT_OVERVIEW.md): goal, test targets, features, risks, MVP checklist
- [Resources](docs/RESOURCES.md): SPHEREx data format, how to get the data from IRSA, test results
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

**Frontend** (Angular 22, local)
```bash
cd frontend
npm install
npm start                       # http://localhost:4200  (/api is proxied to localhost:8000)
```

**Frontend with Docker Desktop** (from the repo root)
```bash
docker compose up --build                                  # dev server with live reload: http://localhost:4200
docker compose --profile prod up --build frontend-prod     # production build via nginx: http://localhost:8080
```

The frontend calls the backend only through relative `/api/...` paths. In development the Angular dev server forwards them (`frontend/proxy.conf.mjs`); in production nginx does (`frontend/nginx.conf`). So backend routes should live under `/api`.

## Layout

```
backend/              FastAPI app (app/main.py), requirements.txt  (not created yet)
frontend/             Angular 22 app (standalone components, SCSS, Vitest)
  src/app/pages/      routed pages (home)
  src/app/core/       app-wide config/services (API_BASE_URL)
  Dockerfile          targets: dev (ng serve), prod (nginx)
docker-compose.yml    starts frontend (later backend too)
docs/                 project overview and resources
```
