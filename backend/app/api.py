"""HTTP API for the frontend (MVP). Three endpoints, used in this order:

  GET /api/resolve                 what the user typed (a name or coordinates) -> a target
  GET /api/coverage                everything available for that target; poll until ready -> the sliders
  GET /api/frames/{id}/image.png   one picture; fetched whenever a slider moves

The same text is shown, with live "Try it out" buttons, at /docs (Swagger UI) when the backend runs.
The guide with the recommended call pattern and TypeScript snippets is docs/API.md.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import resolver, spherex
from .service import (
    FOV_MAX, FOV_MIN, PIXEL_SCALE_ARCSEC, AlignedFrame, ApiError, TargetSpec, display_range, frame_id, iso,
    render_png, service,
)

router = APIRouter(prefix="/api")  # the 422 response is added to the schema below, once ErrorOut exists


# =============================================================================================
# Schemas
# =============================================================================================
class TargetOut(BaseModel):
    """Where to look. Pass these fields, unchanged, to `/api/coverage` and to every image request."""

    ra: float = Field(description="Right ascension of the centre of the view, degrees (ICRS). The view is fixed on the sky: stars stay still, a moving object moves through it.", examples=[269.446269])
    dec: float = Field(description="Declination of the centre of the view, degrees.", examples=[4.768204])
    fov: float = Field(description=f"Width and height of the view in degrees ({FOV_MIN} to {FOV_MAX}).", examples=[0.08])
    pmra: float | None = Field(None, description="Proper motion in RA, mas/yr, already multiplied by cos(dec). `null` = treat the object as fixed. Only moves the predicted-position marker (never the view).", examples=[-801.551])
    pmdec: float | None = Field(None, description="Proper motion in Dec, mas/yr.", examples=[10362.394])
    pm_epoch: float | None = Field(None, description="Decimal year for which `ra`/`dec` is the object's position (e.g. 2026.0). `null` when there is no proper motion.", examples=[2026.0])


class ResolvedTarget(TargetOut):
    name: str | None = Field(None, description="Display name of the object, `null` for typed coordinates.", examples=["Barnard's Star"])
    note: str | None = Field(None, description="A short remark about the object (only for the challenge test targets).")


class ResolveOut(BaseModel):
    query: str = Field(description="The text that was sent, unchanged.")
    kind: Literal["coordinates", "preset", "name"] = Field(description="`coordinates`: the text was a position. `preset`: one of the five challenge targets, matched locally. `name`: found by the name service (SIMBAD).")
    target: ResolvedTarget
    warnings: list[str] = Field(description="Things worth telling the user, e.g. that a moving object's position was moved from its catalogue value. May be empty.")


class GridOut(BaseModel):
    width: int = Field(description="Picture width in pixels at `scale=1`.", examples=[47])
    height: int = Field(examples=[47])
    pixel_scale_arcsec: float = Field(description="Size of one pixel on the sky.", examples=[6.15])
    center_ra: float
    center_dec: float
    orientation: str = Field("north up, east left; pixel row 0 is the south edge", description="Every picture uses this same grid, so stars line up between frames.")


class SkyPos(BaseModel):
    ra: float
    dec: float


class VisitOut(BaseModel):
    index: int = Field(description="Position on the time slider (0 = oldest).")
    start: str = Field(description="Date of the first image of this visit, YYYY-MM-DD (UTC).", examples=["2025-08-15"])
    end: str = Field(description="Date of the last image.", examples=["2025-10-01"])
    n_frames: int = Field(description="How many frames this visit has (all detectors together).")
    target: SkyPos | None = Field(None, description="Where the target is predicted to be in the middle of this visit. Only when `pmra`/`pmdec`/`pm_epoch` were given.")


class FrameOut(BaseModel):
    id: str = Field(description="Use in `/api/frames/{id}/image.png`.", examples=["2025W35_2A_0221_3-D5"])
    visit: int = Field(description="Index into `visits`: which time-slider stop this frame belongs to.")
    detector: str = Field(description="D1 to D6: which of the six cameras took it (each covers one wavelength range). Informational: the user never picks a detector.", examples=["D5"])
    wavelength_um: float = Field(description="Wavelength in micrometres **at the target's position** in this image (every pixel of a SPHEREx image has its own wavelength, so an image is not one colour).", examples=[4.2027])
    bandwidth_um: float = Field(description="Width of the wavelength band at that position.", examples=[0.0369])
    time: str = Field(description="Middle of the exposure, UTC.", examples=["2025-08-29T15:50:00Z"])
    release: str = Field(description="Data release the image comes from (needed for citing).", examples=["spherex_dr1"])
    cache: Literal["ready", "fetching", "queued", "failed", "outside", "missing"] = Field(
        description="`ready`: answers instantly. `fetching`/`queued`: being downloaded. `failed`: a recent download failed, retry later. "
                    "`outside`: the view lies outside this image, never available. `missing`: not requested yet. "
                    "You never have to wait for `ready` before asking for an image.")


class Progress(BaseModel):
    located: int = Field(description="Images processed so far.")
    total: int = Field(description="Images found (0 until the search has finished).")


class CoverageOut(BaseModel):
    target: TargetOut = Field(description="The target as the backend understood it (coordinates normalised to degrees).")
    state: Literal["searching", "locating", "ready", "error"] = Field(description="`searching`: looking up which images cover the position. `locating`: working out each image's wavelength (see `progress`). `ready`: done. `error`: see `message`; the backend retries by itself after about 15 s, so keep polling.")
    message: str | None = Field(None, description="Explanation when `state` is `error`, or a notice that the list could not be refreshed and is the last known one.")
    progress: Progress
    grid: GridOut
    visits: list[VisitOut] = Field(description="The **time slider**: one stop per observing season (the telescope revisits a position about every six months). Empty until `ready`.")
    wavelength_range_um: tuple[float, float] | None = Field(None, description="The **wavelength slider**: one continuous axis from the shortest to the longest wavelength, across all six detectors. `null` until `ready`.", examples=[[0.741, 5.0012]])
    frames: list[FrameOut] = Field(description="Every image, sorted by `(visit, wavelength_um)`. Empty until `ready` (also when nothing covers the position).")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable, machine-readable. See the table in docs/API.md.", examples=["bad_fov"])
    message: str = Field(description="For humans (may be shown to the user).")


class ErrorOut(BaseModel):
    error: ErrorBody


class PendingOut(BaseModel):
    status: Literal["queued", "fetching", "failed", "missing"] = Field(description="Where the download stands.")
    frame_id: str
    retry_after_s: int = Field(description="Ask again after this many seconds (also sent as the `Retry-After` header).")


# =============================================================================================
# Helpers
# =============================================================================================
def api_error_handler(_request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


def target_spec(
    ra: str = Query(..., description="Right ascension: decimal degrees (`269.446`) or sexagesimal (`17h57m47.1s`, `17:57:47.1`).", examples=["269.446269"]),
    dec: str = Query(..., description="Declination: decimal degrees (`4.768`) or sexagesimal (`+04d46m06s`, `+04:46:06`).", examples=["4.768204"]),
    fov: float = Query(0.08, description=f"Field of view in degrees, {FOV_MIN} to {FOV_MAX}. 0.08 (4.8 arcmin) is 47 pixels wide.", examples=[0.08]),
    pmra: float | None = Query(None, description="Proper motion in RA, mas/yr, including cos(dec). Give `pmra`, `pmdec` and `pm_epoch` together, or none of them.", examples=[-801.551]),
    pmdec: float | None = Query(None, description="Proper motion in Dec, mas/yr.", examples=[10362.394]),
    pm_epoch: float | None = Query(None, description="Decimal year for which `ra`/`dec` is the object's position.", examples=[2026.0]),
) -> TargetSpec:
    """The six target parameters, shared by `/api/coverage` and every `/api/frames/...` request."""
    return TargetSpec.build(ra, dec, fov, pmra, pmdec, pm_epoch)


def _target_out(spec: TargetSpec) -> TargetOut:
    return TargetOut(ra=spec.ra, dec=spec.dec, fov=spec.fov_deg, pmra=spec.pmra, pmdec=spec.pmdec, pm_epoch=spec.pm_epoch)


def _grid(spec: TargetSpec) -> GridOut:
    return GridOut(width=spec.n_pix, height=spec.n_pix, pixel_scale_arcsec=PIXEL_SCALE_ARCSEC, center_ra=spec.ra, center_dec=spec.dec)


def _pending(spec: TargetSpec, fid: str, record: spherex.ImageRecord) -> JSONResponse:
    state = service.frame_state(spec, record)
    retry = 3
    return JSONResponse(status_code=202, headers={"Retry-After": str(retry)},
                        content={"status": state if state != "ready" else "fetching", "frame_id": fid, "retry_after_s": retry})


def _get_frame(spec: TargetSpec, fid: str, wait: float) -> tuple[AlignedFrame | None, spherex.ImageRecord]:
    """The frame, fetching it if needed. Returns (None, record) if it is still being fetched after `wait` seconds."""
    record = service.record_for(spec, fid)
    fut = service.ensure_cutout(spec, record, priority=0)
    if fut is not None:
        try:
            fut.result(timeout=wait)
        except TimeoutError:
            return None, record
        except spherex.OutsideImageError as err:
            raise ApiError(404, "outside_image", "the requested field is outside this image") from err
        except Exception as err:  # noqa: BLE001
            raise ApiError(502, "upstream_error", f"IRSA download failed: {str(err)[:160]}") from err
    return service.aligned_frame(spec, record), record


PNG_HEADER_NAMES = ["X-Frame-Id", "X-Wavelength-Um", "X-Bandwidth-Um", "X-Time-Utc", "X-Flags-At-Target", "X-Target-X",
                    "X-Target-Y", "X-Image-Size", "X-Stretch-Min", "X-Stretch-Max"]


def _frame_headers(af: AlignedFrame, spec: TargetSpec, lo: float, hi: float) -> dict[str, str]:
    return {
        "X-Frame-Id": af.frame_id,
        "X-Wavelength-Um": f"{af.wavelength_um:.4f}",
        "X-Bandwidth-Um": f"{af.bandwidth_um:.4f}",
        "X-Time-Utc": iso(af.record.t_mid_mjd),
        "X-Flags-At-Target": ",".join(af.flags_at_target),
        "X-Target-X": f"{af.target_xy[0]:.2f}",
        "X-Target-Y": f"{af.target_xy[1]:.2f}",
        "X-Image-Size": f"{spec.n_pix}",
        "X-Stretch-Min": f"{lo:.6g}",
        "X-Stretch-Max": f"{hi:.6g}",
        "Cache-Control": "public, max-age=3600",
        "Access-Control-Expose-Headers": ", ".join(PNG_HEADER_NAMES),
    }


def _hdr(description: str) -> dict:
    return {"description": description, "schema": {"type": "string"}}


PNG_HEADER_DOCS = {
    "X-Frame-Id": _hdr("The frame id."),
    "X-Wavelength-Um": _hdr("Wavelength at the target's position, micrometres."),
    "X-Bandwidth-Um": _hdr("Width of the wavelength band there."),
    "X-Time-Utc": _hdr("Middle of the exposure, UTC."),
    "X-Flags-At-Target": _hdr("Comma-separated quality flags set on the target's pixel, e.g. `OVERFLOW,BLOOM` (saturated). Empty if none."),
    "X-Target-X": _hdr("Predicted target position in pixels from the left edge. May lie outside the picture (see `X-Image-Size`)."),
    "X-Target-Y": _hdr("Predicted target position in pixels from the **bottom** edge (row 0 = south). In picture coordinates use `height - 1 - Y`."),
    "X-Image-Size": _hdr("Width and height of the picture in pixels at `scale=1`; multiply by `scale` for the real size."),
    "X-Stretch-Min": _hdr("Brightness value drawn as black (MJy/sr). Pass it as `vmin` for other frames to keep the scale fixed."),
    "X-Stretch-Max": _hdr("Brightness value drawn as white. Pass it as `vmax`."),
}

ERRORS = {400: {"model": ErrorOut, "description": "Invalid input."}, 404: {"model": ErrorOut}, 502: {"model": ErrorOut, "description": "IRSA or the name service failed."}}
router.responses[422] = {"model": ErrorOut, "description": "`invalid_request`: a required parameter is missing or has the wrong type."}


# =============================================================================================
# Endpoints
# =============================================================================================
@router.get(
    "/resolve", response_model=ResolveOut, tags=["1. Target"],
    summary="Turn a name or coordinates into a target",
    responses={400: ERRORS[400], 404: {"model": ErrorOut, "description": "`name_not_found`"}, 502: {"model": ErrorOut, "description": "`resolver_unavailable`: the name service did not answer."}},
)
def get_resolve(q: str = Query(..., description="What the user typed: an object name or a pair of coordinates.", examples=["Barnard's Star", "WISE 0855", "17h57m48.5s +04d41m36s", "269.452 4.693"])) -> ResolveOut:
    """One search box for both. Call it when the user **submits** (not on every keystroke) and pass the returned
    `target` fields on to `/api/coverage`.

    **Coordinates** are two numbers (degrees: `269.452 4.693`) or sexagesimal (`17h57m48.5s +04d41m36s`,
    `17:57:48.5 +04:41:36`, `08h55m10.831s -07d14m42.53s`). RA is read as **hours** only when written in
    sexagesimal. Typed coordinates have no proper motion: the view stays exactly there.

    **Names** are matched first against the five challenge targets (so `WISE 0855` and `R Dra` work), then
    looked up in SIMBAD through CDS's Sesame service (about 1 second; once in a while a few).

    For objects with a **proper motion** the returned position is moved from the catalogue epoch (J2000) to
    1 January of the current year, so that the object sits near the middle of recent images. Barnard's Star
    has moved 4.5 arcmin since J2000, more than half of a default field of view. `warnings` says so.

    Not supported (yet): comets and asteroids (SIMBAD does not know them)."""
    r = resolver.resolve(q)
    return ResolveOut(
        query=q, kind=r.kind, warnings=r.warnings,
        target=ResolvedTarget(name=r.name, ra=r.ra, dec=r.dec, fov=r.fov, pmra=r.pmra, pmdec=r.pmdec, pm_epoch=r.pm_epoch, note=r.note))


@router.get(
    "/coverage", response_model=CoverageOut, tags=["2. Coverage"],
    summary="What SPHEREx data exists at this target (the data behind the sliders)",
    responses={400: ERRORS[400]},
)
def get_coverage(spec: TargetSpec = Depends(target_spec)) -> CoverageOut:
    """The first call starts looking up the data in the background and returns at once; **poll every 1.5 s
    until `state` is `ready`** (show `progress`). The call always returns HTTP 200; problems with the
    data source are reported in `state` and `message`, so the polling loop stays simple. Looking up a position
    that was seen before is instant, also after a backend restart. A first lookup took 50 to 125 s in our tests.

    **How the sliders map onto the data**

    - **Time slider** = `visits`. A visit is one observing season; Barnard's Star has 3 so far.
    - **Wavelength slider** = one continuous axis over `wavelength_range_um`, across all six detectors. The
      detector is a property of a frame, not a control.
    - For a slider position *(visit v, wavelength w)* show the frame of visit v whose `wavelength_um` is nearest
      to w. If it is further away than about `2 * bandwidth_um`, there is no real frame at that wavelength in
      that visit: show the nearest one with a notice, or disable that position. Do this in the frontend with the
      list you already have; no request is needed.
    - **Blink** = the same wavelength, stepping the time slider through the visits.

    Most visits cover almost all wavelengths, but not all (the mission start, partly processed visits, the
    newest visit of an object may be missing). Frames of one visit at different wavelengths were taken up to
    a few weeks apart."""
    cov = service.coverage(spec)
    frames: list[FrameOut] = []
    for e in cov.exposures:
        r = e.record
        if not np.isfinite(e.wavelength_um):
            continue  # the target falls outside the detector in this image
        fid = frame_id(r)
        frames.append(FrameOut(
            id=fid, visit=cov.visit_of[fid], detector=r.detector, wavelength_um=round(e.wavelength_um, 4),
            bandwidth_um=round(e.bandwidth_um, 4), time=iso(r.t_mid_mjd), release=r.collection,
            cache=service.frame_state(spec, r)))
    frames.sort(key=lambda f: (f.visit, f.wavelength_um))

    n_in_visit: dict[int, int] = {}
    for f in frames:
        n_in_visit[f.visit] = n_in_visit.get(f.visit, 0) + 1
    visits = []
    for i, v in enumerate(cov.visits):
        tgt = None
        if spec.pmra is not None:
            c = spec.at((v[0].t_mid_mjd + v[-1].t_mid_mjd) / 2)
            tgt = SkyPos(ra=round(float(c.ra.deg), 6), dec=round(float(c.dec.deg), 6))
        visits.append(VisitOut(index=i, start=iso(v[0].t_mid_mjd)[:10], end=iso(v[-1].t_mid_mjd)[:10],
                               n_frames=n_in_visit.get(i, 0), target=tgt))

    wl = [f.wavelength_um for f in frames]
    return CoverageOut(
        target=_target_out(spec), state=cov.state, message=cov.message, progress=Progress(located=cov.located, total=cov.total),
        grid=_grid(spec), visits=visits, wavelength_range_um=(min(wl), max(wl)) if wl else None, frames=frames)


@router.get(
    "/frames/{frame_id}/image.png", tags=["3. Frames"],
    summary="One frame as a ready-to-show PNG",
    responses={
        200: {"content": {"image/png": {}}, "headers": PNG_HEADER_DOCS, "description": "The picture, north up, east left. Details about the frame are in the `X-*` response headers."},
        202: {"model": PendingOut, "description": "Still being downloaded after `wait` seconds. Ask again after `Retry-After` seconds."},
        400: ERRORS[400],
        404: {"model": ErrorOut, "description": "`unknown_frame` (no such image for this target) or `outside_image` (permanent: the view lies outside this image)."},
        502: ERRORS[502],
    },
)
def get_frame_image(
    frame_id: str,
    spec: TargetSpec = Depends(target_spec),
    mask: bool = Query(True, description="Draw flagged bad pixels dark red. `false` shows their raw values (a saturated star's core then shows as bright pixels instead of a hole)."),
    vmin: float | None = Query(None, description="Brightness drawn as black. Give **both** `vmin` and `vmax`, or neither."),
    vmax: float | None = Query(None, description="Brightness drawn as white."),
    scale: int = Query(1, ge=1, le=16, description="Integer upscale factor (nearest neighbour). The picture is 47 px wide at the default field of view: use 8, or CSS `image-rendering: pixelated`."),
    wait: float = Query(20.0, ge=0, le=60, description="Seconds to wait if the frame has to be downloaded first. `0` = never wait: you get 202 at once."),
):
    """`frame_id` is `frames[].id` from `/api/coverage`. Send the **same target parameters** as for the coverage
    request (they are part of what a frame is). Use it as an `<img src>` for ready frames, or `fetch()` it to
    handle 202.

    **Speed.** A frame already in the cache answers in about 0.1 s (10 ms if it was shown recently). Any other is downloaded from IRSA first
    (about 12 s; IRSA is slow and rate-limits) and this call waits up to `wait` seconds for it, then answers
    **202** with a `Retry-After` header and the frame keeps downloading in the background: ask again. Several
    frames can be requested at once; the backend downloads three at a time. When the wavelength slider settles,
    request the frames of **all visits at that wavelength** together (the blink set): that also fills the cache.

    **Brightness.** Without `vmin`/`vmax` each frame is scaled on its own, which hides brightness changes
    between visits (important for variable stars). For a blink: request the first frame without them, read
    `X-Stretch-Min` / `X-Stretch-Max` from its response and pass them as `vmin` / `vmax` for the other frames
    at the same wavelength. Frames of different detectors differ a lot in brightness: don't reuse a range across
    detectors.

    **Colours.** Grey = brightness (asinh scale), **dark red** = masked bad pixel, **slate blue** = no data.

    The response depends only on the URL, so the browser may cache it (`Cache-Control: max-age=3600`)."""
    if (vmin is None) != (vmax is None):
        raise ApiError(400, "bad_stretch", "give both vmin and vmax, or neither")
    af, record = _get_frame(spec, frame_id, wait)
    if af is None:
        return _pending(spec, frame_id, record)
    lo, hi = display_range(af, vmin, vmax)
    png = render_png(af, mask=mask, vmin=vmin, vmax=vmax, scale=scale)
    return Response(content=png, media_type="image/png", headers=_frame_headers(af, spec, lo, hi))
