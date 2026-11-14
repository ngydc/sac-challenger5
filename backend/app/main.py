from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import api_error_handler, router
from .service import ApiError


def validation_error_handler(_request, exc: RequestValidationError) -> JSONResponse:
    """Same error shape as every other error: {"error": {"code", "message"}}."""
    msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": msg}})


DESCRIPTION = """
SPHEREx sky images for any position on the sky, as a series of frames over **time** and **wavelength**.

**Three calls, in this order**

1. `GET /api/resolve?q=Barnard's Star` turns a name or coordinates into a *target*.
2. `GET /api/coverage?ra=…&dec=…&fov=…` lists everything available for it: the **visits** (time slider), the
   **wavelength range** (wavelength slider) and every **frame**. Poll until `state` is `ready`.
3. `GET /api/frames/{id}/image.png?ra=…&dec=…&fov=…` returns one picture. Call it whenever a slider moves.

Every error has the same shape: `{"error": {"code": "...", "message": "..."}}`.

Guide with the recommended call pattern, TypeScript snippets and timing: `docs/API.md` in the repository.
"""

TAGS = [
    {"name": "1. Target", "description": "What the user typed, as a target."},
    {"name": "2. Coverage", "description": "What data exists for a target. This is what the sliders are built from."},
    {"name": "3. Frames", "description": "One picture per request."},
]

app = FastAPI(title="SAC Challenger API", description=DESCRIPTION, openapi_tags=TAGS)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return {"message": "Hello from FastAPI"}


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
