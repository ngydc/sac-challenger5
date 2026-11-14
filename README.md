# sac-challenger5 — Planet X and SPHEREx


Teamname: CHALLENGER5
Team members: Can, Duc, Daniel, Maximilian

NASA Space Apps Challenge 2026: a public web tool that shows [SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html) sky images of a given RA/Dec as a time-ordered "blink" animation, so moving and varying objects are easy to spot.

Challenge: https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/

## Docs

- [Project overview](docs/PROJECT_OVERVIEW.md): goal, test targets, features, risks, MVP checklist
- [Resources](docs/RESOURCES.md): SPHEREx data format, how to get the data from IRSA, test results

## Stack

| Part | Tech | Folder |
|---|---|---|
| Frontend | Angular | `frontend/` |
| Backend | Python, FastAPI | `backend/` |

The browser can't call IRSA directly (no CORS headers), so the backend searches IRSA, fetches and caches cutouts, and serves small frames to the frontend.

## Getting started

Requirements: Node.js 20+ with the Angular CLI, and Python 3.11+.

**Backend**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000  (API docs at /docs)
```

**Frontend**
```bash
cd frontend
npm install
ng serve                        # http://localhost:4200
```

## Layout (planned)

```
backend/    FastAPI app (app/main.py), requirements.txt
frontend/   Angular app
docs/       project overview and resources
```

The `frontend/` and `backend/` folders don't exist yet, so create them first (`ng new frontend`, and a FastAPI app in `backend/app/`).

