# Epoch maps API

> Team note, not an official SPHEREx source. Code: `backend/app/epochs.py` (pipeline), `backend/app/epochs_api.py` (endpoints), `backend/app/precompute.py`. Live reference: the backend's `/docs`, group "4. Epoch maps".

For one sky position the backend builds, per detector, one averaged picture per observing **epoch** (a block of observations; a gap of more than 30 days starts a new one), an **epoch RGB** (three epochs as red, green, blue: unchanged sources are white, moving or varying ones are coloured) and a **difference image** (last minus first epoch).

All pictures of one position share one grid: north up, east left, centred on `ra`/`dec`, 6.15″ per pixel. Pixels without data in one of the compared epochs are **transparent**.

## Call pattern

1. `GET /api/config` once: the default field of view.
2. `GET /api/epochs?ra=…&dec=…`: if `status` is `cached`, show the pictures.
3. If `not_computed` (or `error`): `POST /api/compute?ra=…&dec=…`, then poll `GET /api/epochs` every few seconds. Bundles appear in `result.bundles` one detector at a time while `status` is still `running`, so the first picture can be shown early.
4. Per bundle: `GET /api/rgb`, `/api/diff`, `/api/frame`, and `GET /api/rgb?format=json` for the explanation text.

Only `POST /api/compute` makes the backend talk to IRSA. A new position takes tens of minutes (IRSA delivers about 20 cutouts per minute, a position has 250 to 550). The five challenge targets are precomputed.

## Common parameters

| Parameter | Meaning |
|---|---|
| `ra`, `dec` | Position, decimal degrees or sexagesimal. Use exactly the values `GET /api/resolve` returns. |
| `fov` | Field of view in degrees. Leave it out to get the default (`default_fov` from `/api/config`, the value the precomputed targets use). |
| `bundle` | `D1` … `D6` (one detector) or `all` (all detectors together, overview only). `channel` has no pictures, use `/api/spectrum`. |
| `scale` | Optional whole factor 1–16 to enlarge a PNG (nearest neighbour). |

Errors have the usual shape `{"error": {"code", "message"}}`. Codes: `not_computed` (404), `unknown_bundle` (404), `no_data` (404, the bundle has no such picture), `epoch_not_usable` (404), `no_image_for_channels` (400), `bad_pixel` (400).

## Endpoints

### `GET /api/config`
`{"default_fov": 0.08, "fov_min": …, "fov_max": …, "bundles": {…}}`

### `GET /api/epochs?ra&dec[&fov]`
Never starts a computation.

| Field | Meaning |
|---|---|
| `status` | `cached`, `not_computed`, `running` or `error` |
| `progress` | while running: `stage` (text), `done` / `total` (images), `bundles_ready` (ids) |
| `message` | error text when `status` is `error` |
| `default_fov`, `target` | the default field of view; the position as the backend rounded it |
| `cache` | `example (permanent)` or `temporary (removed after … h without use)` |
| `result` | `null`, or the metadata below (also while running, with the bundles finished so far) |

`result`:

| Field | Meaning |
|---|---|
| `complete` | `false` while detectors are still missing |
| `grid` | `width`, `height` (pixels at scale 1), `pixel_scale_arcsec`, `orientation` |
| `epochs[]` | `index` (0 = oldest), `start`, `end`, `time` (median time of its images, the representative time), `n_images`, `images_per_detector` |
| `bundles[]` | see below |
| `collections`, `searched_at`, `n_images` | which IRSA collections were searched, when, how many images were found |
| `failed[]`, `failed_retryable` | images that could not be used (`reason`); retryable ones are fetched again by the next `POST /api/compute` |
| `channel_table[]` | every spectral channel: `detector`, `channel`, `wavelength_um`, `wl_min_um`, `wl_max_um` |
| `bad_flags` | the pixel flags that were masked |

`bundles[]`:

| Field | Meaning |
|---|---|
| `id`, `kind`, `detectors` | `D2` / `detector` / `["D2"]`, or `all` / `all` / all six |
| `mode` | `three_epochs`, `two_epochs`, `one_epoch` or `no_data` |
| `note` | one sentence describing the mode |
| `usable_epochs` | epoch indices that have a picture in this bundle |
| `rgb` | `red`, `green`, `blue`: each `{epoch, time, start, end}`; `null` for `no_data` |
| `diff` | `first`, `last` (`{epoch, time}`), `clip_sigma` (the colour scale ends at ± this), `empirical_scale`, `relative_floor`, `definition`, `colours`; `null` with fewer than two usable epochs |
| `wavelength_um` | `min`, `max` of the channels that went into the pictures |
| `channels[]`, `channels_excluded[]` | channels used, and channels left out because one usable epoch lacks them |
| `epochs[]` | per epoch for this bundle: `usable`, `n_images`, `start`, `end`, `time`, `span_days` (of this detector's images; `null` if it has none), `epoch_start`, `epoch_end` (of the whole epoch), `channels_covered`, `channels_missing`, `wavelength_at_target_um`, `saturated_images`, `files` (contributing file names), `background`, `noise` |
| `n` | `per_epoch`: min/median/max number of contributing images per pixel; `channels_per_pixel` |
| `stretch` | `kind` (`asinh`), `black`, `white`, `noise`, `unit`: one stretch for every epoch of the bundle |
| `covered_fraction` | share of the picture that is not transparent |
| `gaps[]` | coverage gaps as ready-made sentences |

### `POST /api/compute?ra&dec[&fov][&refresh=true]`
Starts the computation (202) and returns the same body as `/api/epochs`. Does nothing if it is already running or cached; `refresh=true` searches IRSA again to pick up new weekly data.

### `GET /api/frame?ra&dec[&fov]&bundle&epoch[&scale]`
PNG (greyscale with transparency) of one usable epoch.

### `GET /api/rgb?ra&dec[&fov]&bundle[&scale][&format=json]`
PNG of the epoch RGB; the response header `X-Epoch-Mode` carries the mode. In `one_epoch` mode the picture is grey; in `no_data` mode the PNG request answers 404 `no_data`.

`format=json` returns the facts for the explanation text (always 200 once the bundle exists):

| Field | Meaning |
|---|---|
| `bundle`, `kind`, `detectors` | which bundle |
| `mode`, `note` | as above |
| `epochs_used[]` | `colour`, `epoch`, `time`, `start`, `end`, `span_days`, `n_images`: the epochs actually used, which can differ between detectors |
| `wavelength_um`, `n_channels` | wavelength range and number of channels in the picture |
| `gaps[]` | coverage gaps as sentences |
| `has_image`, `has_diff`, `diff`, `stretch` | whether the pictures exist, and their scales |

### `GET /api/diff?ra&dec[&fov]&bundle[&scale]`
PNG of (last − first usable epoch) in units of the noise: red = brighter in the last epoch, blue = fainter, white = unchanged. The scale ends at ± `diff.clip_sigma`. The noise includes 15 % of the pixel's own brightness (`diff.relative_floor`), because pixels of unchanged stars differ that much between epochs; so a star must change by clearly more than 15 % to show up.

### `GET /api/spectrum?ra&dec[&fov]&x&y`
`x`, `y`: pixel in the PNG at scale 1 (x from the left, y from the top). Returns `unit`, `epochs[]` and `channels[]`, each channel with `detector`, `channel`, `wavelength_um`, `wl_min_um`, `wl_max_um` and `epochs[]` of `{epoch, value, sigma, n}` (`value` is `null` where nothing was measured).

## What the frontend should tell the user

- White = unchanged. A colour fringe on **one** star = it moved; a uniformly coloured star = it changed brightness.
- The epochs of one detector span days to weeks (`span_days`), so a picture is not a snapshot.
- Bright stars are saturated: their cores are transparent (`saturated_images`, `gaps`).
- Faint colour speckle in empty sky is noise.

## Precompute and cache

Everything is stored as files under `backend/cache/` (bind-mounted into the containers by `docker-compose.yml`, so it survives restarts and rebuilds). Two separate trees:

| Tree | For | Lifetime |
|---|---|---|
| `cache/examples/` | the five challenge test targets (any field of view) | permanent, never cleaned up automatically |
| `cache/temp/` | every other position | removed after `SPHEREX_TEMP_CACHE_TTL_HOURS` (default 72) without use, and least recently used first once the tree exceeds `SPHEREX_TEMP_CACHE_MAX_MB` (default 2000). The clean-up runs before each computation and only ever looks inside `cache/temp/`. |

Inside either tree, one directory per target and field of view:

```
ra248.167233_dec+66.755024_fov0.08000/
  target.json  search.json  status.json
  cutouts/<obs_id>-<detector>.fits        raw data: every cutout of every detector and epoch (PSF table removed)
  reproj/<key>/<obs_id>-<detector>.npz    one exposure on the common grid: img, var, chan (channel per pixel);
                                          masked pixels are NaN; `meta` holds time, wavelength, flags
  products/<kind>/<key>/                  one kind of computation with one set of parameters
    params.json                           the parameters behind <key>
    kind "epochmaps": meta.json, channels_<det>.npz (maps per channel and epoch), bundle_<id>.npz,
                      frame_<id>_e<n>.png, rgb_<id>.png, diff_<id>.png, spectrum/x<x>_y<y>.json
```

So a result is found by target, field of view, kind of computation and parameters. Changing a parameter (for example `SPHEREX_EPOCH_GAP_DAYS`) gives a new `<key>` next to the old one. A new kind of computation calls `epochs.product_dir(spec, "<kind>", params)` and reads `cutouts/` or `reproj/`: nothing is downloaded again. Spectra are written on the first request and only read afterwards.

`docker compose up` runs the `precompute` service once: `python -m app.precompute` fills `cache/examples/` for the five test targets with the default field of view and skips what is already there. By hand, from `backend/`: `.venv/bin/python -m app.precompute [--targets r_dra,barnard] [--refresh]`. `/api/epochs` reports which tree a position is in (`cache`).
