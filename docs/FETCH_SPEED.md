# Fetch speed and caching: what we measured (2026-11-14)

Branch `fetch-speed-investigation`. Team notes, not an official SPHEREx source. Every number here was measured
from a home connection in Germany on 2026-11-14 with small samples (2 to 40 images per run), so treat them as
rough, especially anything involving IRSA's `503 Server busy` answers, which come and go.

Scripts: `backend/scripts/bench/` (one per test, about 1 to 4 minutes each), raw results in `backend/out/bench/*.json`.
All tests use real images from the stored Barnard's Star coverage at the app's default view (fov 0.08°, so a
0.116° cutout of 68 × 68 pixels) and never re-use one test's images in another, so IRSA's disk cache can't flatter
a result.

Docs used: `spherex/irsa-cutout-service.md` (what a cutout is), `spherex/user-guide-data-products.md` (the HDUs),
`spherex/irsa-cloud-access.md` and `spherex/user-guide-data-access.md` (S3 copy, `cloud_access` column),
`spherex/tutorial-intro-spectral-images.md` (spectral WCS). The byte layout of the files comes from a real file's
headers, not from the docs (the docs don't cover it).

## Summary

| | Today | Best option measured | Gain |
|---|---|---|---|
| One cutout | 6.5–12 s (IRSA cutout service) | ~1 s (our own cutout from S3, by byte range) | ~10× |
| A whole target, 350 frames | ~11–24 min (14–33 cutouts/min, 3–6 workers, 503s) | ~1.5–2 min (125–225 cutouts/min, no 503s) | ~10× |
| First coverage lookup | ~32 s measured today (notes say 50–125 s) | ~5 s (skip header reads, keep calibration maps in memory) | ~6× |
| Zoom change (new fov) | a full new coverage lookup + every frame downloaded again | coverage re-used, frames fetched in ~2 min | |

**Recommendation, in order:**
1. **Build cutouts ourselves from byte ranges** instead of calling IRSA's cutout service. Our cutouts are
   bit-identical to IRSA's (test 2A). Use the S3 copy first (no rate limit seen) and IRSA's file server as a fallback.
   This also makes it cheap to **prefetch every frame** as soon as the coverage is ready.
2. **Stop reading one header per image in the coverage lookup**: compute the target pixel from the footprint polygon
   SIA2 already returns (wavelength error ≤ 7% of one channel's width, test 3C). If that is not good enough, read the
   headers from S3 with more workers.
3. **Keep the calibration maps in memory** and store each distinct file once (half of them are duplicates).
4. **Key the coverage by position, not by fov**, so zooming does not trigger a new lookup.

## Implemented (2026-11-15) and measured end to end

All four recommendations are in the backend now (branch `fetch-speed-investigation`):

| Change | Where |
|---|---|
| Cutouts from byte ranges: S3 copy first (URL from SIA2's `cloud_access`), then IRSA's file server (only the needed columns), then IRSA's cutout service. Requests to IRSA itself: at most 3 at a time. | `app/cutout.py`, `spherex.download_cutout` |
| 8 download workers; every frame of a view is prefetched once its coverage is ready; a frame a user asks for jumps ahead of the queue; zooming cancels the old view's queued prefetch. | `service.py` (`_start_prefetch`, `ensure_cutout`) |
| Target pixel from the footprint polygon; 3 real headers per lookup are checked, and if any is off by more than 25 px every header is read instead. Headers come from S3 first. | `spherex.locate_on_detector`, `footprint_pixel` |
| Calibration maps kept in memory per process, keyed by content; stored once per distinct file (existing rows migrated automatically: 12 rows → 6 files, database 423 MB → 247 MB). S3 listed once per release. | `spherex.SpectralMaps`, `schema.sql`, `db.py` |
| Coverage stored per position + motion; each request filters it for its fov. | `service.Coverage.view`, `TargetSpec.coverage_key` |
| In-memory frame cache limited by size (256 MB, `SPHEREX_FRAME_CACHE_MB`) instead of 256 frames. (Stored cutouts briefly left out `VARIANCE`; it is back since the merge with main, because the epoch maps use it.) | `service.py`, `spherex.KEEP_HDUS` |

End-to-end against the running backend (home connection):

| | Before | After |
|---|---|---|
| Barnard's Star, coverage right after a backend restart (includes the one-time migration and loading the maps) | 50–125 s (notes) / ~32 s (measured) | 15.5 s |
| R Draconis, coverage of a position never seen before (539 images) | | 6.4 s (5.1 s of it IRSA's collection list + search) |
| Barnard's Star, change fov 0.08 → 0.12 | a full new lookup | 0.3 s |
| One frame the user asks for, not cached | 6.5–12 s, more with 503s | 2.2–2.9 s |
| All 350 frames of Barnard's Star in the cache | ~11–24 min | 75 s after the coverage was ready |
| Same at fov 0.12 (341 frames, larger cutouts) | | 97 s |

No request fell back to IRSA's cutout service, and the footprint check never failed. The old coverage rows
(keyed with the fov) are no longer read, so each position is looked up once more (~6 s).

### Stored byte layouts (added 2026-11-15)

To cut a frame, the backend first has to find where each part sits in the file, which takes four header reads one
after another (each header's position depends on the size of the part before it). After the first cutout of a file
this is now stored (`app/cutout.FileLayout`, table `file_layout`, ~26 KB per image, keyed by the image's IRSA URL),
so every later cutout of the same file (another fov, a pan, a nearby target, another user) skips those reads.
A stored layout is only used if the file still has the same total size; otherwise it is read again.

| Measured (real images) | Without stored layout | With stored layout |
|---|---|---|
| One cutout from S3, median of 12 | 1.05 s, 8 requests | **0.34 s, 3 requests** (4 since `VARIANCE` is included again) |
| Result | | byte-identical in all 12 cases; a layout read from S3 also gave identical cutouts from IRSA's copy |
| Prefetch of a whole view, Barnard's Star (fov 0.10, then 0.09; ~345 frames) | 105 s | 86 s |

The prefetch gains only ~20% here because it is limited by the home connection, not by waiting: both runs downloaded
at the same ~6.2 MB/s (8 cutouts at once), and the layout only removes the ~17% of the bytes that were headers. Each
cutout still reads whole 2040-pixel rows from S3 (~1.6 MB at fov 0.09), since S3 can't return only the needed columns.
A frame the user asks for (not competing with a full prefetch) gets the full 3× gain, and so would the prefetch on a
server with a faster connection.

Still not done: the tile cache (see the caching section).

## What a cutout costs today (test 1: `t1_irsa_cutout.py`)

A "cutout" is a small piece of one image that IRSA cuts out on request. The app asks for 68 × 68 pixels.

| Measured | Result |
|---|---|
| Time until IRSA starts answering | 0.3–1.8 s |
| Time to receive the answer | 6.2–11.5 s |
| Size of the answer | 4.1 MB, of which ~96% is the PSF extension we throw away |
| Size dependence | 0.03° → 4.0 MB, 0.116° → 4.1 MB, 0.435° → 5.1 MB, same time |
| `503 Server busy` | even one request at a time (2 of 6 requests in the size test got two 503s each and waited 11–12 s) |
| 9 cutouts, 3 workers (today's setting) | 37.5 s, 5 × 503 → 14 cutouts/min |
| 9 cutouts, 6 workers | 16.6 s, 1 × 503 → 33 cutouts/min |

So the time is **not** spent making the cutout. It goes into streaming 4 MB, almost all of it the PSF table we drop.
A smaller cutout does not help, because the PSF is always sent whole (as `irsa-cutout-service.md` and CLAUDE.md say).

## Approach A: cut out ourselves with HTTP range requests (test 2: `t2_range_cutout.py`)

An HTTP **range request** asks a server for only some bytes of a file (`Range: bytes=1000-1999`). IRSA's file server
and the S3 copy both support it. A SPHEREx file (62 MB) is laid out like this (read from a real DR1 file's headers):

| HDU | What it is | How it is stored |
|---|---|---|
| `IMAGE`, `VARIANCE`, `ZODI` | 2040 × 2040 float32 | row after row, so the 68 rows we need are **one block of bytes** |
| `FLAGS` | 2040 × 2040 int32 | compressed (RICE_1), **one compressed piece per row**, so the needed rows are again one block |
| `EPSF` | PSF table, 3.9 MB | never downloaded |
| `WCS-WAVE` | wavelength lookup, 1 KB | read from the end of the file |

IRSA's own cutout only changes the image size and shifts the six `CRPIX*` keywords (checked header by header), so
the prototype (now `backend/app/cutout.py`) does the same. Nothing about the layout is hard-coded: offsets come from the headers.

**Correctness (2 images, compared with IRSA's cutout of the same image, centre and size):** same pixel box, IMAGE,
ZODI and FLAGS pixels identical, 0 header differences, same wavelength at the target, and the final north-up frame
the app shows is identical (max difference 0.0). (The prototype left out `VARIANCE`; since 2026-11-15 it is included,
as the epoch maps need it, and the check was repeated: `VARIANCE` identical too, and both files 152,640 bytes.)

**Speed (9 images per run):**

| Source | Workers | 9 cutouts took | Per cutout (median) | Data per cutout | 503s |
|---|---|---|---|---|---|
| IRSA cutout service (test 1) | 3 | 37.5 s | 6.5–12 s | 4.1 MB | 5 |
| S3, whole rows | 1 | 11.3 s | 1.0 s | 1.7 MB | 0 |
| S3, whole rows | 8 | 3.3 s | 2.6 s | 1.7 MB | 0 |
| IRSA file server, whole rows | 3 | 10.9 s | 3.1 s | 1.7 MB | 0 |
| IRSA file server, whole rows | 8 | 4.3 s | 3.1 s | 1.7 MB | 0 |
| IRSA file server, **only the needed columns** | 3 | 4.5 s | 1.4 s | 0.65 MB | 0 |
| IRSA file server, **only the needed columns** | 8 | 2.4 s | 2.0 s | 0.76 MB | 0 |

Notes:
- **"Only the needed columns"** uses a multi-range request (many byte ranges in one request). IRSA's server supports
  it; **S3 does not and sends the whole 62 MB file instead**, so this must only ever go to IRSA. The result was
  checked identical to the whole-row version.
- Of the ~1 s per S3 cutout, 0.75 s are four header reads one after another, and only 0.2 s is pixel data. A file's
  headers never change (the URL contains the version), so storing each image's byte layout once cuts a later cutout
  to one round of parallel requests. About 320 KB of each cutout's download is also header reads (64 KB per read),
  which a stored layout removes too. (Implemented since, see "Stored byte layouts" above.)
- With 8 workers the per-cutout time goes up: the home connection was probably full (1.7 MB × 9 in 3.3 s). A server
  in a data centre, especially in AWS `us-east-1` next to the bucket, should do better.
- IRSA's file server never answered 503 to range requests (also none in the 40 header reads of test 3); its cutout
  service did. We still don't know IRSA's actual rate limit, so keep the backoff.
- The S3 key is exactly the on-premises path after `/spherex/`: SIA2's `cloud_access` column says so for all 239
  rows checked. Production code should read the key from `cloud_access` rather than rebuild it.
- The SPHEREx docs say cutouts are "only for the on-premises copy". That is about IRSA's cutout *service*; reading
  byte ranges of the S3 files is a different thing and is not covered by the docs.

## Approach B: a faster coverage lookup (test 3: `t3_coverage.py`)

Today: list collections → SIA2 search → read every image's `IMAGE` header from IRSA (8 workers) → look the
target pixel up in the CWAVE map (the per-detector wavelength map from the Spectral WCS calibration file).

| Step | Measured | For Barnard's Star (350 images) |
|---|---|---|
| List collections | 1.9 s | 1.9 s (cached for an hour) |
| SIA2, 2 collections one after the other | 2.9 s | 2.9 s |
| SIA2, both at once | 2.1 s | saves ~1 s |
| Headers from IRSA, 8 workers (today) | 20 headers/s | ~18 s |
| Headers from S3, 8 workers | 31 headers/s | ~11 s |
| Headers from S3, 32 workers | 54 headers/s | ~6.5 s |
| Calibration maps (12 × 32 MB from Postgres + S3 listing) | 0.85 s each | ~10 s on **every** lookup |

**Skip the headers entirely (test 3C, offline, 576 images of both cached targets).** SIA2 already returns each
image's footprint as a 4-corner polygon (`s_region`). Mapping the target into that quadrilateral (a projective map
from the 4 corners) gives the detector pixel without downloading anything:

| | Result |
|---|---|
| Which polygon corner is pixel (0,0) | the first one, for all 58 images checked |
| Pixel error vs. the header WCS | median 4.5 px, 90% below 6.0 px, max 7.5 px (mostly a constant 4 px offset in y) |
| Wavelength error at the target | median 0.0013 µm, max 0.0055 µm = **3% (max 7%) of one channel's bandwidth** |

That is good enough to place each image on the wavelength slider, and the cutout's own WCS still gives the exact
wavelength once pixels are downloaded. The constant 4 px offset could be removed too, but the cause isn't known,
so we didn't apply a correction.

**Calibration maps:** the DR1 and QR3 Spectral WCS files have the same version name and are **byte-identical**
(6 distinct contents among 12 stored files, 200 MB stored twice). They are reloaded from Postgres on every coverage
lookup, and S3 is listed once per detector instead of once per release. Keeping the 6 distinct maps in memory
(200 MB as float32, 100 MB as float16) removes the ~10 s. Float16 changes the wavelength by at most 0.002 µm
(≤ 5% of a channel); taking every 4th pixel is **not** safe (errors up to 1.4 µm at channel boundaries in D4).

## Caching (test 4: `t4_cache.py`, local only)

**Serving a cached frame is fast:** reading from Postgres 3 ms, parsing FITS and building the WCS 50 ms,
two reprojections 10 ms, PNG <1 ms (7 ms at 8× scale; `optimize=True` costs 4 ms there). Local work is not the problem.
But the in-memory cache held 256 frames (`MAX_PIXELS_CACHE`) and Barnard's Star has 350, so a blink loop over all
frames kept re-parsing them. One frame is ~20 KB in memory, so 2000+ frames fit easily (now limited by size instead).

**Postgres already compresses** the stored cutouts (45 MB raw, 19 MB on disk), so compressing them ourselves gains nothing.

**Re-use when the view changes.** Today the cache key of a cutout is its exact URL, and the coverage key includes the
fov, so any zoom or pan re-downloads every frame, and a zoom also repeats the whole coverage lookup.
We tested a "tile" cache on paper (larger cutouts centred on a 0.05° grid, 3 size classes):

| View change | Today | Tile cache |
|---|---|---|
| same view again | hit | hit |
| fov 0.08 → 0.05 | miss | hit |
| coordinates typed slightly differently | miss | hit |
| Barnard's Star resolved for another year (10″ shift) | miss | hit |
| fov 0.08 → 0.10 or 0.20, pan 0.5′ or 2′ | miss | miss |

Tiles cost 145 KB (fov ≤ 0.08) to 1 MB (fov ≤ 0.3) per frame instead of 118 KB. A mixed result: with Approach A a
cache miss costs about 1 s per frame instead of 10 s, so this is worth less than fixing the fetch itself.
**Keying the coverage by position instead of by fov** is the cheaper, clearer win: the SIA2 search does not depend
on the fov (it is only used afterwards to drop images where the view would cross the edge).

**Small issue found:** 377 of the 380 stored cutouts have an empty `url` column (probably imported from the old
disk cache). They still work, but can't be traced back to their image.

## What we did not test

- How the backend behaves under real load, or from a cloud server (only a home connection).
- IRSA's real rate limit (still unknown); whether S3 throttles at hundreds of requests per second (AWS documents
  high limits, not measured here).
- QR3 images that arrived in the last days: SIA2 lags ingestion by about a day, and we didn't check whether the S3
  copy lags the on-premises files. The IRSA file server works as a fallback either way.
- A cutout that crosses the edge of the image (the prototype clips the box; IRSA's behaviour there was not compared).
