# Deep analysis API (epoch maps)

> Team note, not an official SPHEREx source. Code: `backend/app/analysis.py` (computation), `backend/app/analysis_jobs.py` (jobs, inputs, storage), `backend/app/analysis_api.py` (endpoints). Live reference: the backend's `/docs`, group "4. Deep analysis". Replaces `docs/API_EPOCHS.md` (the first version of this feature, until 2026-11-15).

For one view, the backend builds per detector one averaged picture per observing **epoch**, an **epoch RGB** (three epochs as red, green, blue: unchanged sources are white, moving or varying ones are coloured) a **difference image** (last minus first epoch, "Total") and **step differences** (each epoch minus the one before it), plus a **spectrum** for every pixel.

An **epoch** is the same as a **visit** of the viewer (`/api/coverage`): images grouped by gaps of more than 30 days.

All pictures of one view share one grid: north up, east left, centred on `ra`/`dec`, 6.15″ per pixel, the same grid as the viewer's frames. Pixels without data in one of the compared epochs are **transparent**.

## How it fits with the viewer

| | Viewer (`docs/API.md`) | Deep analysis |
|---|---|---|
| Target parameters | `ra, dec, fov, pmra, pmdec, pm_epoch` | the same, unchanged |
| Images | the coverage of the position | the same coverage (every image containing the position, also where the view crosses the image edge) |
| Cutouts | downloaded on request and prefetched; stored in Postgres | the same store, through the same download queue, at the lowest priority |
| Calibration files | stored in Postgres | the same |
| Pixel rows | row 0 = south (`X-Target-Y`) | row 0 = south (`y` of `/spectrum`) |

So analysing a view the user has already looked at needs few or no downloads, and the viewer profits from cutouts the analysis fetched.

## Call pattern

1. `GET /api/analysis?<target>&start=false` when the user opens the panel: shows a result at once if there is one (the five test targets are computed at backend start-up), starts nothing.
2. To compute: `GET /api/analysis?<target>` (`start=true` is the default). Then poll every few seconds with `start=false` while `state` is `queued` or `running`, or `refreshing` is true. Bundles appear in `result.bundles` one detector at a time.
3. Per bundle: `GET /api/analysis/{bundle}/diff.png`, `/steps/{k}.png`, `/rgb.png`, `/epochs/{n}.png`; a click on a pixel: `GET /api/analysis/spectrum`.

A new position takes about 2 minutes (about 350 images, measured on a home connection), less if its frames were already loaded. At most 2 analyses run at the same time (`SPHEREX_ANALYSIS_JOBS`); others wait as `queued`.

## Endpoints

`<target>` = `ra`, `dec`, `fov`, and optionally `pmra`, `pmdec`, `pm_epoch`: exactly as for `/api/coverage`. `{bundle}` = `D1` … `D6` (one detector) or `all` (every detector together). Errors have the usual shape `{"error": {"code", "message"}}`.

### `GET /api/analysis?<target>[&start=false]`

| Field | Meaning |
|---|---|
| `target` | the target as the backend understood it |
| `state` | `idle` (not computed; only with `start=false`), `queued`, `running`, `ready`, `error` |
| `refreshing` | `true` while a complete result is recomputed because the archive has new images; the old result is served meanwhile |
| `progress` | while queued or running: `stage` (text), `done` / `total` (images), `bundles_ready` |
| `message` | the error text when `state` is `error` (a request with `start=true` retries after 30 s) |
| `kept`, `temp_ttl_hours` | `true` for the five test targets (kept for good); other results are removed after `temp_ttl_hours` without use |
| `result` | `null`, or the metadata below (also while running, with the bundles finished so far) |

`result`: `complete`, `images_key` (changes when new images were used: add it as `v=` to picture URLs to reload them), `grid` (`width`, `height`, `pixel_scale_arcsec`, `orientation`), `epochs[]` (`index`, `start`, `end`, `time` = median time, `n_images`, `images_per_detector`), `bundles[]`, `collections`, `searched_at`, `n_images`, `failed[]` (`frame_id`, `reason`), `failed_retryable`, `channel_table[]` (every spectral channel: `detector`, `channel`, `wavelength_um`, `wl_min_um`, `wl_max_um`), `bad_flags` (masked pixel flags).

`bundles[]`: `id`, `kind` (`detector` / `all`), `detectors`, `mode` (`three_epochs`, `two_epochs`, `one_epoch`, `no_data`), `note` (one sentence on the mode), `usable_epochs`, `rgb` (`red`/`green`/`blue` → `{epoch, time, start, end}`; `null` for `no_data`), `diff` (`first`, `last`, `clip_sigma`, `relative_floor`, `definition`, `colours`; `null` with fewer than two usable epochs), `diff_steps[]` (see below; empty with fewer than two usable epochs), `wavelength_um` (`min`, `max`), `channels[]`, `channels_excluded[]`, `epochs[]` (per epoch for this bundle: `usable`, `n_images`, `start`, `end`, `time`, `span_days`, `wavelength_at_target_um`, `saturated_images`, `files`, `background`, `noise`, …), `n`, `stretch` (`kind`, `black`, `white`, `noise`, `unit`: one stretch for every epoch of the bundle), `covered_fraction`, `gaps[]` (coverage gaps as sentences).

### `GET /api/analysis/{bundle}/diff.png?<target>`
(last − first usable epoch) in units of the uncertainty: blue = brighter in the last epoch, red = fainter, white = unchanged. A moving star leaves red where it was and blue where it is now. The scale ends at ± `diff.clip_sigma`. The uncertainty includes 15 % of the pixel's own brightness (`diff.relative_floor`), because pixels of unchanged stars differ that much between epochs. 404 `no_data` with fewer than two usable epochs.

### `GET /api/analysis/{bundle}/steps/{step}.png?<target>`
One **step**: (later − earlier epoch) of the `step`-th pair of **neighbouring usable** epochs of this bundle, `step` from 0. Same computation, colours and scale (± `diff.clip_sigma`) as `/diff.png`, so steps and Total can be compared: blue = brighter in the later epoch, red = brighter in the earlier one, white = unchanged. The empirical noise scale is measured per pair. 404 `no_data` if the bundle has no such step or it is not available (the message lists the available steps).

Why: for a variable star (RW Aurigae, R Draconis) "last minus first" can hide a back-and-forth; the steps show when something changed. For proper motion Total is the stronger picture (the shift is larger), so it stays the default.

`bundle.diff_steps[]`: one entry per pair, `{step, first: {epoch, time}, last: {epoch, time}, available, empirical_scale}`. `first`/`last` have the form of `diff.first`/`diff.last`. A pair whose difference cannot be computed keeps its entry with `available: false`, so step numbers never shift.

**Gap rule:** epochs a bundle cannot use are skipped, so the pairs differ between bundles. Example: the result has epochs 0-3 and D2 cannot use epoch 1 (`usable_epochs: [0, 2, 3]`):

```json
"diff_steps": [
  {"step": 0, "first": {"epoch": 0, "time": "2025-05-12T…Z"}, "last": {"epoch": 2, "time": "2025-11-08T…Z"}, "available": true, "empirical_scale": 1.07},
  {"step": 1, "first": {"epoch": 2, "time": "2025-11-08T…Z"}, "last": {"epoch": 3, "time": "2026-05-10T…Z"}, "available": true, "empirical_scale": 0.98}
]
```

so `/api/analysis/D2/steps/0.png` is epoch 2 minus epoch 0, while for a detector with all four epochs step 0 is epoch 1 minus epoch 0. With exactly two usable epochs the only step equals Total. Since `PIPELINE_VERSION` 9; older results have no `diff_steps`.

### `GET /api/analysis/{bundle}/rgb.png?<target>`
The epoch RGB (`bundle.rgb` says which epoch is which colour). Grey in `one_epoch` mode, 404 `no_data` in `no_data` mode.

### `GET /api/analysis/{bundle}/epochs/{n}.png?<target>`
The averaged picture of epoch `n` (greyscale with transparency). 404 `no_data` if the epoch is not usable for this bundle.

Pictures carry an `ETag` and `Cache-Control: no-cache`: the browser revalidates and gets `304` while the picture is unchanged.

### `GET /api/analysis/spectrum?<target>&x&y`
`x` from the left (east), `y` from the **bottom** (south), as the viewer's `X-Target-Y`. Returns `unit`, `epochs[]` and `channels[]`, each channel with `detector`, `channel`, `wavelength_um`, `wl_min_um`, `wl_max_um` and `epochs[]` of `{epoch, value, sigma, n}` (`value` is `null` where nothing was measured).

Errors: `not_ready` (409, nothing computed yet), `unknown_bundle` (404), `no_data` (404), `bad_pixel` (400), `no_images` (in `message`: the archive has no images of this position).

## What the frontend should tell the user

- White = unchanged. A colour fringe on **one** star = it moved; a uniformly coloured star = it changed brightness.
- The epochs of one detector span days to weeks (`span_days`), so a picture is not a snapshot.
- Bright stars are saturated: their cores are transparent (`saturated_images`, `gaps`).
- Faint colour speckle in empty sky is noise.

## Precompute and storage

At start-up the backend analyses the five challenge test targets in the background (`SPHEREX_PRECOMPUTE=1`, default), with the target, field of view and proper motion `GET /api/resolve` returns for their names. This also looks up their coverage and lets the viewer's prefetch fill their frames. Complete, current results are skipped, so a restart costs a few database reads. By hand, without the web server: `python -m app.precompute [--targets r_dra,barnard]` (waits until done).

Inputs (search results, cutouts, calibration files) are in Postgres, shared with the viewer. Results are files under `backend/cache/analysis/` (git-ignored, bind-mounted by `docker-compose.yml`):

```
analysis/<tier>/ra<deg>_dec<deg>_fov<deg>/
  latest.json                          which products folder is served, and whether it is complete
  reproj/<key>/<obs_id>-<detector>.npz one exposure on the common grid: image, variance, channel per pixel
  products/<params key>/<images key>/  meta.json, channels_<det>.npz, bundle_<id>.npz, the PNGs
                                       (diff_<id>.png, diff_<id>_s<k>.png, rgb_…, frame_…), spectrum/
```

`<tier>` is `examples` for the five test targets (never removed) and `temp` for every other position (removed after `SPHEREX_TEMP_CACHE_TTL_HOURS`, default 72, without use, and least recently used first above `SPHEREX_TEMP_CACHE_MAX_MB`, default 2000). A change of the computation gives a new `<params key>`, new images a new `<images key>`; the new folder is served once it is complete, and the old one is then removed.

Data from the first version (`backend/cache/examples/`, `backend/cache/temp/`) is no longer read. `python -m scripts.import_examples` copies its downloaded cutouts into Postgres; the folders can be deleted afterwards.
