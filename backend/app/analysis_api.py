"""HTTP API of the deep analysis (epoch maps): one averaged picture per epoch and detector, the epoch RGB,
the difference image and per-pixel spectra. Computation: app/analysis.py; jobs and storage: app/analysis_jobs.py.
Guide: docs/API_ANALYSIS.md.

It takes the same target parameters as the viewer (/api/coverage, /api/frames), so both look at the same view,
share the coverage and the cutout store, and a frontend keeps one target object for everything. Pixel rows
count from the south edge, as for the viewer's X-Target-Y. An "epoch" is a visit of the viewer.
"""
from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .api import ERRORS, ErrorOut, TargetOut, _target_out, target_spec
from .analysis_jobs import jobs
from .core import ApiError, TargetSpec

router = APIRouter(prefix="/api/analysis", tags=["4. Deep analysis"])
BUNDLE = Path(..., pattern=r"^(D[1-6]|all)$", description="A detector (`D1` to `D6`) or `all` (every detector together).", examples=["D2"])


# =============================================================================================
# Schemas (field names are the stored metadata's, so the files and the API agree)
# =============================================================================================
class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")  # stored metadata may carry more detail than documented here


class Range(BaseModel):
    min: float | None
    max: float | None


class Channel(BaseModel):
    detector: str
    channel: int = Field(description="Spectral channel of the detector, 1-based.")
    wavelength_um: float | None = None
    wl_min_um: float | None = None
    wl_max_um: float | None = None


class EpochOut(_Open):
    index: int = Field(description="0 = oldest. Epochs are the viewer's visits: images grouped by gaps of more than 30 days.")
    start: str
    end: str
    time: str = Field(description="Median time of the epoch's images: the representative time.")
    n_images: int


class BundleEpoch(_Open):
    index: int
    usable: bool = Field(description="False if the epoch covers too few of the bundle's spectral channels to be compared.")
    n_images: int
    start: str | None = None
    end: str | None = None
    time: str | None = None
    span_days: float | None = Field(None, description="Time span of this bundle's images in the epoch: a picture is not a snapshot.")
    wavelength_at_target_um: Range | None = None
    saturated_images: int = 0
    files: list[str] = []
    background: float | None = None
    noise: float | None = None


class EpochRef(_Open):
    epoch: int
    time: str | None = None


class Diff(_Open):
    first: EpochRef
    last: EpochRef
    clip_sigma: float = Field(description="The colour scale ends at plus/minus this many times the uncertainty.")
    relative_floor: float | None = None
    definition: str
    colours: str


class Stretch(_Open):
    kind: str
    black: float | None
    white: float | None
    noise: float | None
    unit: str | None = None


class Bundle(_Open):
    id: str = Field(description="`D1`..`D6` or `all`; used in the picture paths.")
    kind: Literal["detector", "all"]
    detectors: list[str]
    mode: Literal["three_epochs", "two_epochs", "one_epoch", "no_data"]
    note: str = Field(description="One sentence describing the mode, for the user.")
    usable_epochs: list[int]
    rgb: dict[str, EpochRef] | None = Field(None, description="Which epoch is red, green and blue; null for `no_data`.")
    diff: Diff | None = Field(None, description="Null with fewer than two usable epochs.")
    wavelength_um: Range | None = None
    channels: list[Channel] = []
    epochs: list[BundleEpoch]
    stretch: Stretch | None = None
    covered_fraction: float | None = None
    gaps: list[str] = Field(description="Coverage gaps as ready-made sentences.")


class Grid(_Open):
    width: int
    height: int
    pixel_scale_arcsec: float
    orientation: str


class Failed(_Open):
    frame_id: str
    reason: str


class AnalysisResult(_Open):
    complete: bool = Field(description="False while a first computation is still adding bundles.")
    grid: Grid
    epochs: list[EpochOut]
    bundles: list[Bundle]
    collections: list[str]
    searched_at: str | None
    n_images: int
    failed: list[Failed]
    failed_retryable: int
    channel_table: list[Channel]
    bad_flags: list[str] = Field(description="Pixel flags masked in the epoch maps.")


class Progress(BaseModel):
    stage: str = Field(description="What is being done, as text for the user.")
    done: int = Field(description="Images processed so far.")
    total: int
    bundles_ready: list[str]


class AnalysisOut(BaseModel):
    target: TargetOut
    state: Literal["idle", "queued", "running", "ready", "error"] = Field(
        description="`idle`: not computed (only with `start=false`). `queued`: waiting for a free slot. `running`: being "
                    "computed (bundles appear in `result` one detector at a time). `ready`: complete. `error`: see `message`; "
                    "a request with `start=true` tries again after 30 s.")
    refreshing: bool = Field(description="True while a complete result is being recomputed with newly found images; the old one is served meanwhile.")
    message: str | None
    progress: Progress | None
    kept: bool = Field(description="True for the five challenge test targets: their result is never removed.")
    temp_ttl_hours: float = Field(description="Other positions' results are removed after this many hours without use.")
    result: AnalysisResult | None


class SpectrumEpoch(BaseModel):
    epoch: int
    value: float | None = Field(description="Null where nothing was measured.")
    sigma: float | None
    n: int


class SpectrumChannel(Channel):
    epochs: list[SpectrumEpoch]


class SpectrumOut(BaseModel):
    x: int
    y: int
    unit: str | None
    value_definition: str
    epochs: list[dict]
    channels: list[SpectrumChannel]


# =============================================================================================
# Endpoints
# =============================================================================================
@router.get("", response_model=AnalysisOut, summary="State and result of the deep analysis of a target",
            responses={400: ERRORS[400]})
def get_analysis(spec: TargetSpec = Depends(target_spec),
                 start: bool = Query(True, description="Start the analysis if it is missing, failed more than 30 s ago, or "
                                                       "was computed from fewer images than the archive now has. `false` only reports.")
                 ) -> AnalysisOut:
    """Poll every few seconds until `state` is `ready`; bundles appear in `result` while it runs. Images come from the
    same coverage and cutout store as the viewer's frames, so a target already viewed needs few or no downloads.
    A new position takes about 2 minutes (350 images); the five test targets are computed at start-up."""
    st = jobs.status(spec, start=start)
    return AnalysisOut(target=_target_out(spec), **st)


@router.get("/spectrum", response_model=SpectrumOut, summary="Values per channel and epoch of one pixel",
            responses={400: ERRORS[400], 409: {"model": ErrorOut, "description": "`not_ready`"}})
def get_spectrum(spec: TargetSpec = Depends(target_spec),
                 x: int = Query(..., ge=0, description="Pixel column, from the left (east) edge."),
                 y: int = Query(..., ge=0, description="Pixel row, from the BOTTOM (south) edge, as the viewer's X-Target-Y.")):
    return jobs.spectrum(spec, x, y)


def _png(request: Request, spec: TargetSpec, name: str) -> Response:
    """A stored picture. It changes only when the analysis is recomputed, so the browser revalidates (ETag)."""
    path = jobs.picture(spec, name)
    st = path.stat()
    etag = '"' + hashlib.sha1(f"{path}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(path.read_bytes(), media_type="image/png", headers=headers)


PNG = {200: {"content": {"image/png": {}}}, 404: {"model": ErrorOut, "description": "`unknown_bundle`, `no_data`"},
       409: {"model": ErrorOut, "description": "`not_ready`: nothing computed yet"}}


@router.get("/{bundle}/diff.png", response_class=Response, responses=PNG, summary="Difference last minus first epoch (PNG)")
def get_diff(request: Request, bundle: str = BUNDLE, spec: TargetSpec = Depends(target_spec)) -> Response:
    """(last - first usable epoch) / uncertainty: blue = brighter in the last epoch, red = fainter, white = unchanged.
    Transparent = no data in one of the two epochs."""
    b = jobs.bundle(spec, bundle)
    if b["diff"] is None:
        raise ApiError(404, "no_data", "a difference needs at least two usable epochs. " + b["note"])
    return _png(request, spec, f"diff_{bundle}.png")


@router.get("/{bundle}/rgb.png", response_class=Response, responses=PNG, summary="Epoch RGB (PNG)")
def get_rgb(request: Request, bundle: str = BUNDLE, spec: TargetSpec = Depends(target_spec)) -> Response:
    """Three epochs as red, green and blue (`bundle.rgb` says which): unchanged sources are white, moving or varying ones
    coloured. Grey in `one_epoch` mode."""
    b = jobs.bundle(spec, bundle)
    if b["rgb"] is None:
        raise ApiError(404, "no_data", b["note"])
    return _png(request, spec, f"rgb_{bundle}.png")


@router.get("/{bundle}/epochs/{epoch}.png", response_class=Response, responses=PNG, summary="One epoch's averaged picture (PNG)")
def get_epoch(request: Request, bundle: str = BUNDLE, epoch: int = Path(..., ge=0, description="Epoch index (0 = oldest)."),
              spec: TargetSpec = Depends(target_spec)) -> Response:
    b = jobs.bundle(spec, bundle)
    if epoch not in b["usable_epochs"]:
        raise ApiError(404, "no_data", f"bundle {bundle} has no picture for epoch {epoch}; usable epochs: {b['usable_epochs']}")
    return _png(request, spec, f"frame_{bundle}_e{epoch}.png")
