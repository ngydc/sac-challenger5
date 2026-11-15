"""HTTP API of the epoch maps (app/epochs.py). Short guide: docs/API_EPOCHS.md.

  GET  /api/config     the default field of view
  GET  /api/epochs     status of a position and, if computed, its metadata. Never starts a computation.
  POST /api/compute    start the computation. The only endpoint that makes the backend talk to IRSA.
  GET  /api/frame      PNG of one epoch of one bundle
  GET  /api/rgb        PNG of the epoch RGB of one bundle (format=json: the facts for the explanation)
  GET  /api/diff       PNG of the difference image of one bundle
  GET  /api/spectrum   values per channel and epoch of one pixel
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from . import epochs
from .service import FOV_MAX, FOV_MIN, ApiError, TargetSpec

router = APIRouter(prefix="/api", tags=["4. Epoch maps"])
PNG_HEADERS = {"Cache-Control": "no-cache"}  # a recomputation (new weekly data) may replace the picture


def position(
    ra: str = Query(..., description="Right ascension: decimal degrees or sexagesimal.", examples=["248.167233"]),
    dec: str = Query(..., description="Declination: decimal degrees or sexagesimal.", examples=["66.755024"]),
    fov: float | None = Query(None, description=f"Field of view in degrees ({FOV_MIN} to {FOV_MAX}). Leave out for the default (see /api/config)."),
) -> TargetSpec:
    return epochs.spec_for(ra, dec, fov)


BUNDLE = Query("D1", description="Bundle id: a detector (`D1` to `D6`) or `all` (every detector together).", examples=["D2"])
SCALE = Query(1, ge=1, le=16, description="Enlarge the picture by this whole factor (nearest neighbour, pixels stay sharp).")


@router.get("/config", summary="Default field of view")
def get_config() -> dict:
    return {"default_fov": epochs.DEFAULT_FOV_DEG, "fov_min": FOV_MIN, "fov_max": FOV_MAX,
            "bundles": {"detector": "one bundle per detector, ids D1..D6 (default)", "all": "one overview bundle, id 'all'",
                        "channel": "single channels: no pictures, only /api/spectrum"}}


@router.get("/epochs", summary="Status and metadata of a position (starts nothing)")
def get_epochs(spec: TargetSpec = Depends(position)) -> dict:
    return epochs.status(spec)


@router.post("/compute", status_code=202, summary="Start the computation (talks to IRSA)")
def post_compute(spec: TargetSpec = Depends(position),
                 refresh: bool = Query(False, description="Search IRSA again even if a result is cached (new weekly data).")) -> dict:
    return epochs.start(spec, refresh)


@router.get("/frame", summary="One epoch of one bundle (PNG)", response_class=Response)
def get_frame(spec: TargetSpec = Depends(position), bundle: str = BUNDLE,
              epoch: int = Query(..., ge=0, description="Epoch index (0 = oldest), as in /api/epochs."), scale: int = SCALE) -> Response:
    b = epochs.bundle_meta(spec, bundle)
    if epoch not in b["usable_epochs"]:
        raise ApiError(404, "epoch_not_usable", f"bundle {bundle} has no picture for epoch {epoch}; usable epochs: {b['usable_epochs']}")
    return Response(epochs.load_png(spec, f"frame_{bundle}_e{epoch}.png", scale), media_type="image/png", headers=PNG_HEADERS)


def rgb_facts(spec: TargetSpec, b: dict) -> dict:
    ep = {e["index"]: e for e in b["epochs"]}
    used = []
    for colour, sel in (b["rgb"] or {}).items():
        e = ep[sel["epoch"]]
        used.append({"colour": colour, "epoch": e["index"], "time": e["time"], "start": e["start"], "end": e["end"],
                     "span_days": e["span_days"], "n_images": e["n_images"]})
    return {"bundle": b["id"], "kind": b["kind"], "detectors": b["detectors"], "mode": b["mode"], "note": b["note"],
            "epochs_used": used, "wavelength_um": b["wavelength_um"], "n_channels": len(b["channels"]),
            "gaps": b["gaps"], "has_image": b["rgb"] is not None, "has_diff": b["diff"] is not None, "diff": b["diff"],
            "stretch": b.get("stretch"), "target": {"ra": spec.ra, "dec": spec.dec, "fov": spec.fov_deg}}


@router.get("/rgb", summary="Epoch RGB of one bundle (PNG, or its facts with format=json)", response_class=Response)
def get_rgb(spec: TargetSpec = Depends(position), bundle: str = BUNDLE, scale: int = SCALE,
            format: Literal["png", "json"] = Query("png", description="`json`: which epochs were used (with dates), the mode, detector, wavelength range and coverage gaps.")):
    b = epochs.bundle_meta(spec, bundle)
    if format == "json":
        return JSONResponse(rgb_facts(spec, b))
    if b["rgb"] is None:
        raise ApiError(404, "no_data", b["note"])
    return Response(epochs.load_png(spec, f"rgb_{bundle}.png", scale), media_type="image/png",
                    headers={**PNG_HEADERS, "X-Epoch-Mode": b["mode"]})


@router.get("/diff", summary="Difference last minus first epoch of one bundle (PNG)", response_class=Response)
def get_diff(spec: TargetSpec = Depends(position), bundle: str = BUNDLE, scale: int = SCALE) -> Response:
    b = epochs.bundle_meta(spec, bundle)
    if b["diff"] is None:
        raise ApiError(404, "no_data", "a difference needs at least two usable epochs. " + b["note"])
    return Response(epochs.load_png(spec, f"diff_{bundle}.png", scale), media_type="image/png", headers=PNG_HEADERS)


@router.get("/spectrum", summary="Values per channel and epoch of one pixel")
def get_spectrum(spec: TargetSpec = Depends(position),
                 x: int = Query(..., ge=0, description="Pixel column in the PNG at scale 1, from the left (east)."),
                 y: int = Query(..., ge=0, description="Pixel row in the PNG at scale 1, from the top (north).")) -> dict:
    return epochs.spectrum(spec, x, y)
