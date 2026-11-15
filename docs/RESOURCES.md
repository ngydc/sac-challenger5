# Planet X and SPHEREx — Resources

The team's own measurements and notes on the resources listed on the challenge page. Part of the [project overview](PROJECT_OVERVIEW.md).

**Official facts are not repeated here.** Release status, file format, flags, access methods, DOIs and the acknowledgement text are in the local copies of the official documentation in [`docs/spherex/`](spherex/) (index: [INDEX.md](INDEX.md)); section 1 says which file covers what. This file keeps only what we measured or concluded ourselves, on 2026-11-14. Items marked **(tested)** are things we ran ourselves that day. Items marked **(inferred)** are our own reading and need checking.

## Contents

1. [Where the official facts are](#1-where-the-official-facts-are)
2. [Data format: our measurements](#2-data-format)
3. [How to get the data](#3-how-to-get-the-data)
4. [What we measured (and what it means for the design)](#4-what-we-measured-and-what-it-means-for-the-design)
5. [Tutorial notebooks](#5-tutorial-notebooks)
6. [WiseView](#6-wiseview-the-model-to-imitate)
7. [Gaia](#7-gaia-mission-data)
8. [Partner resources: CSA / NEOSSat](#8-partner-resources-csa--neossat)
9. [Link list](#9-link-list)

---

## 1. Where the official facts are

The NASA/IPAC Infrared Science Archive (IRSA) is our **only required data source**. Its documentation, saved locally:

| Topic | Read |
|---|---|
| Releases (DR1, QR3, QR2, QR1), which to use, which are searchable | [user-guide-data-releases.md](spherex/user-guide-data-releases.md), [irsa-quick-release-overview.md](spherex/irsa-quick-release-overview.md) |
| Access layers: SIA2, TAP, browsable directories, Data Explorer, Python | [user-guide-data-access.md](spherex/user-guide-data-access.md) |
| AWS S3 copy (bucket, region, prefixes) | [irsa-cloud-access.md](spherex/irsa-cloud-access.md) |
| Cutout parameters (`center`, `size`), clipping, axes | [irsa-cutout-service.md](spherex/irsa-cutout-service.md) |
| Observation IDs, filenames, the six HDUs, All-Sky Cube, calibration products | [user-guide-data-products.md](spherex/user-guide-data-products.md) |
| Sky and spectral WCS in Python, wavelength per pixel | [tutorial-intro-spectral-images.md](spherex/tutorial-intro-spectral-images.md) |
| Flag bits (Table 16), known artifacts | [explanatory-supplement-extracts.md](spherex/explanatory-supplement-extracts.md) |
| Band edges and other places where sources disagree | [source-discrepancies.md](spherex/source-discrepancies.md) |
| DOIs and the required acknowledgement text | [irsa-dr1-overview.md](spherex/irsa-dr1-overview.md), [irsa-quick-release-overview.md](spherex/irsa-quick-release-overview.md) |

---

## 2. Data format

What the official docs describe is in section 1. Below is what we found ourselves in real search results and files.

### Technical summary (planning tables)

Checked on 2026-11-14 against IRSA: SIA2 searches (collections `spherex_dr1`, `spherex_qr3` and their `_deep` versions) at the five test targets, plus the headers and pixels of one real cutout (D2, Barnard's Star, `size=0.1`). Items marked *(derived)* are our own arithmetic from those numbers.

**A. What is the same in every image**

| Property | Value | Source |
|---|---|---|
| Instrument / facility | `SPHEREx` / `SPHEREx` for all 3,900+ images found. Single instrument, no other missions mixed in | SIA2 |
| Product | Level 2 spectral image, one exposure (`calib_level` 2, `dataproduct_subtype` science, `obs_intent` science). All from the survey "SPHEREx LVF Survey Data" | SIA2 |
| Detector arrays | 6 H2RG arrays, 2040 × 2040 light-sensitive pixels each. D1–D3 are short-wave (SWIR), D4–D6 mid-wave (MWIR) | `DETECTOR` header, SIA2 |
| Pixel scale | 6.15″ per pixel. Median pixel solid angle 37.7 arcsec² | SIA2 `s_pixel_scale`, `OMEGA_MEDIAN` |
| Footprint of one image | 3.485° (`s_fov`), about 3.5° × 3.5° | SIA2 |
| Exposure time | 113.58 s (`XPOSURE`), 118.2 s elapsed. Identical in every image checked | SIA2 `t_exptime`, header |
| Pixel unit and type | Surface brightness in **MJy/sr**, float32 (`BUNIT`). Zodiacal light **not** subtracted | header |
| Sky WCS | ICRS, `RA---TAN-SIP` (TAN projection plus SIP distortion terms). Read with `astropy.wcs.WCS` | header |
| Time stamps | UTC. `MJD-BEG`, `MJD-AVG`, `MJD-END`, with `DATE-AVG` as the mid-exposure time. SIA2 `t_min`/`t_max` are in MJD (confirmed: 60908.98 matches `DATE-OBS` 2025-08-21) | header, SIA2 |
| HDUs | `IMAGE`, `FLAGS`, `VARIANCE`, `ZODI` (all float32 or int32), `EPSF` (binary table), `WCS-WAVE` (binary table) | file |
| File size | Full file 57–68 MB. A 0.1° cutout is **4.0 MB**, of which `EPSF` is 3.86 MB. Each image layer of a 59 × 59 cutout is only 13.9 KB | SIA2 `access_estsize`, file |
| Cutout size | `size=0.1` gave a **59 × 59** pixel cutout here (58 × 59 earlier). Plan on ±1 pixel | tested |

**B. What differs between images**

| Property | How it varies | Consequence for the tool |
|---|---|---|
| **Detector / band** | An image is from one of D1–D6, so its wavelength range is fixed by the detector (table C) | Never mix detectors in one blink sequence without saying so |
| **Wavelength inside an image** | Changes along the array's y axis at about **0.00028 µm per pixel** (D2 example, derived). In our D2 cutout it ran from 1.095 to 1.108 µm, with a bandwidth of about 0.025 µm. Only a weak, curved dependence along x | Over a ~10′ field (~100 px) the shift is about one bandwidth. Over 30′ it is about 3. Use **one wavelength per frame, taken at the target**, and warn when a large field is used |
| **Which detectors cover a position** | Each pointing places the target on only **one of three detector pairs: D1+D4, D2+D5 or D3+D6** (the two arrays in a pair see nearly the same sky at once through the dichroic, offset by about 0.02°). Of about 2,000 pointings at our five targets, 97% gave a pair and 3% only one array. None gave more than 2. Pair frequency: D3+D6 41%, D1+D4 39%, D2+D5 17% | A given epoch gives you **2 bands, not 6**. Which pair you get depends on where the target falls relative to the boresight, and it varies by target (R Dra has far fewer D2/D5 images) |
| **Pointing and pixel grid** | Every exposure has its own boresight, so the footprint centre and the target's pixel position change. Each image has its own WCS | Frames are **not aligned**. Reproject all cutouts to one common WCS (e.g. `reproject`, or a client-side warp) before blinking, or the target will jump for the wrong reason |
| **Observation time** | 2025-04-24 to 2026-10-02 at the time of checking. Exposures of one position cluster in short visit windows (a day or a few days), then nothing for weeks to months | See table D. Group by visit window, not by image |
| **Release** | `spherex_dr1` and `spherex_qr3` (and `_deep`). Filenames show the same pipeline version (`v27`) but different processing dates. IRSA says DR1 + QR3 form one uniformly processed set | Query both. Record the collection in the metadata panel |
| **PSF width** | `PSF_FWHM` is stored per image. 7.46″ for the one image we read | The PSF is about 1.2 px wide (FWHM), so a mover is blurred over a couple of pixels |
| **Quality and contamination** | Per-image header counters (`N_PERSIST`, `N_SNOWBALL`, `L2DQAFLG`, `SATSTRKS`, and so on) and the `FLAGS` bit map. In the cutout, bit 21 was set on 3,478 of 3,481 pixels. This is probably the SOURCE flag, because the header says 94.9% of the image carries it **(inferred)** | Do **not** mask on "any flag set". Look up each bit in the Explanatory Supplement (Table 16) first |
| **Background** | `ZODI` was a flat 0.152 MJy/sr over the cutout, against an image median of 0.43 MJy/sr. It changes with date and sky position | Subtract `ZODI` before stretching, or frames from different dates will look different even with no change in the sky |
| **Bad pixels** | 3 of 3,481 pixels were NaN in `IMAGE` and `VARIANCE`. The brightest star pixel was 1,876 MJy/sr, against a typical 0.2–2 | Use a robust (percentile or asinh) stretch, and handle NaN |

**C. The six bands**

SIA2 reports the full wavelength coverage of each array, which is a little wider than the nominal ranges in the official docs (see [source-discrepancies.md](spherex/source-discrepancies.md)). Neighbouring arrays overlap slightly.

| Detector | Type | Wavelength range from SIA2 (µm) | Resolving power R | Typical bandwidth |
|---|---|---|---|---|
| D1 | SWIR | 0.7455 – 1.1167 | 39.1 | ~0.02 µm at 0.9 µm *(derived: λ/R)* |
| D2 | SWIR | 1.1033 – 1.6499 | 41.4 | 0.025–0.040 µm (measured in the WCS-WAVE table) |
| D3 | SWIR | 1.6301 – 2.4346 | 40.6 | ~0.05 µm at 2 µm *(derived)* |
| D4 | MWIR | 2.4027 – 3.8473 | 34.9 | ~0.09 µm at 3.1 µm *(derived)* |
| D5 | MWIR | 3.8113 – 4.4300 | 111.6 | ~0.04 µm at 4.1 µm *(derived)* |
| D6 | MWIR | 4.4115 – 5.0096 | 127.8 | ~0.04 µm at 4.7 µm *(derived)* |

The bandpass name in queries is `SPHEREx-D1` … `SPHEREx-D6`. Each detector has 17 channels (102 in total).

**D. Coverage at the five test targets**

Cone search of 0.01° at the late-2026 positions from the overview, all four collections. "Visit windows" are groups of exposures of one detector less than 2 days apart, so they approximate separate epochs. The last column is our estimate of the motion across the whole available baseline *(derived: proper motion × baseline ÷ 6.15″)*.

| Target | Images found | Per detector (D1 / D2 / D3 / D4 / D5 / D6) | Collections | Date range | Visit windows (D1 / D4 / D6) | Total motion over the baseline |
|---|---|---|---|---|---|---|
| Barnard's Star | 363 | 60 / 61 / 61 / 59 / 62 / 60 | DR1 239, QR3 124 | 2025-08 → 2026-09 | 7 / 7 / 11 | 1.1 yr × 10.4″/yr ≈ 11″ ≈ **1.9 px** |
| Epsilon Indi B | 467 | 48 / 93 / 99 / 46 / 86 / 95 | DR1 347, QR3 120 | 2025-04 → 2026-10 | 10 / 10 / 10 | 1.4 yr × 4.7″/yr ≈ 6.7″ ≈ **1.1 px** |
| WISE 0855 | 258 | 36 / 48 / 45 / 36 / 48 / 45 | DR1 258, QR3 0 | 2025-05 → 2026-05 | 4 / 4 / 8 | 1.0 yr × 8.2″/yr ≈ 8.2″ ≈ **1.3 px** |
| RW Aurigae | 336 | 56 per detector | DR1 226, QR3 110 | 2025-09 → 2026-09 | 5 / 5 / 5 | none (static). Variability only |
| R Draconis | 2,514 | 586 / 92 / 576 / 588 / 93 / 579 | DR1 422, QR3 126, plus **DR1 deep 1,233 and QR3 deep 733** | 2025-04 → 2026-09 | 27 / 27 / 23 | none (static). Variability only |

Some detector counts of one pair differ by a few images (one array of a pair missing in some pointings).

**E. What this means for planning our features**

These were our conclusions before building the backend. Some were changed later: the backend has one wavelength slider across all detectors instead of a detector picker, and frames are single images rather than co-adds. The current design is in [API.md](API.md).

| Planned feature | Finding that affects it |
|---|---|
| **Blink player (MVP)** | Total motion across the whole mission so far is only **1–2 pixels** for the three movers, and the PSF is already ~1.2 px wide. A raw blink will be subtle. Plan for good stretch controls, a visit-window-averaged frame, and difference images early, not as extras |
| **What is a frame** | Use **one frame per visit window, within one detector** (take one exposure, or co-add the minutes-apart exposures of the window if the download budget allows). That gives roughly 4–10 frames per mover target (Barnard 7, Epsilon Indi 10, WISE 0855 4–8), 5 for RW Aur and 25+ for R Dra |
| **Band handling and co-adds** | Co-add **within one detector**. Do not co-add across detectors: the wavelengths are very different, and brown dwarfs and comets change brightness strongly with wavelength. Offer a "same detector only" blink, and let the user pick the detector. Since a position is seen by only one pair per pointing, expect some detectors to have fewer windows than others |
| **Field of view** | Wavelength shifts ~0.0003 µm per pixel along y. Keep the default field ≤10′ and show the wavelength per frame. A 10′ field is ~100 px, so a cutout is about 100 × 100 px (~38 KB per layer) |
| **Alignment** | Cutouts come on different pixel grids. A reprojection step on the backend is **required**, not optional |
| **Epsilon Indi B pair** | Ba and Bb are ~1–2″ apart against a 7.5″ PSF, so they are unresolved. Do not promise to separate them |
| **R Dra performance** | Our query returned 2,514 images because R Dra sits in the deep field. Cap how many frames are fetched (e.g. latest N per detector, or pick one window per month) and let the user widen it |
| **WISE 0855 coverage** | Only DR1 images so far (no QR3 at this position when we checked), ending 2026-05. Centre each frame on the target's position **at that image's date**, not on the late-2026 position |
| **Latency and size** | **Every exposure is its own ~4 MB, ~10 s download**, though the useful data in it is ~55 KB. One detector at Barnard's Star is ~60 images, about 240 MB from IRSA. All six detectors is 363 images, about 1.4 GB. So default to **one detector** and/or **one exposure per visit window**, fetch in parallel, drop `EPSF`, and cache. Offer "load more" for the rest |
| **Metadata display** | Per-image values worth showing: date (`DATE-AVG`), detector, wavelength at the target, `PSF_FWHM`, `L2DQAFLG`, collection and observation ID. All are in the header or SIA2 result |
| **Updating with new releases** | Collection names and `v27` change. Read the collection list and file names from the SIA2 result, never hard-code them |

---

## 3. How to get the data

The official how-to (SIA2 collections and example queries, cutout URLs, the one-query TAP alternative, reading files in Python) is in [user-guide-data-access.md](spherex/user-guide-data-access.md), [irsa-cutout-service.md](spherex/irsa-cutout-service.md) and [tutorial-spectral-image-cutouts.md](spherex/tutorial-spectral-image-cutouts.md). The backend implements it in `backend/app/spherex.py`.

Our own findings on top of that:

- **SIA2 is the search step we use.** It is fast (section 4). The backend reads the list of SPHEREx collections from IRSA each hour instead of hard-coding them, and leaves out the All-Sky Cube (no time information) and, for now, the `_deep` collections.
- **Cutout size is not exact (tested):** `size=0.1` gave a 58 × 59 pixel image in one test and 59 × 59 in another (0.1° is 360″, and 360″ / 6.15″ ≈ 58.5 pixels).
- **A cutout lying fully outside the image returns HTTP 500** ([irsa-cutout-service.md](spherex/irsa-cutout-service.md)), and **a busy server returns 503** (tested, see [DATA_COVERAGE.md](DATA_COVERAGE.md)). The backend treats the first as permanent and retries the second with backoff.
- **The wavelength at the target can be found without downloading pixels:** read only the image header with an HTTP range request (~26 KB), then look the pixel up in the Spectral WCS calibration maps (`CWAVE`/`CBAND`). Method and results: [DATA_COVERAGE.md](DATA_COVERAGE.md).

---

## 4. What we measured (and what it means for the design)

Tests run on 2026-11-14 from a normal home connection, using `curl` and an `Origin` header. Treat the timings as rough.

| Finding | Detail | Consequence |
|---|---|---|
| **No CORS headers (tested)** | The SIA2, TAP and cutout responses carry no `Access-Control-Allow-Origin` header | A browser page on our own domain **cannot call IRSA directly**. We need a **small backend proxy** (or a serverless function) |
| **Cutouts are mostly PSF (tested)** | A 0.1° cutout was **4.0 MB**: `EPSF` 3.86 MB, but `IMAGE`, `FLAGS`, `VARIANCE` and `ZODI` together only ~55 KB | The backend should **drop the PSF HDU** before sending data to the browser. Frames become tiny (≈14 KB per layer), which makes a smooth blink video and larger fields feasible. We can't avoid downloading the full 4 MB from IRSA per frame |
| **Cutout speed (tested)** | About 9.7 s for one cutout | Fetch many cutouts **in parallel**, show frames as they arrive, and **cache** results by position, size and image ID |
| **SIA2 is quick (tested)** | 2.7 s, 249 KB of VOTable for a small cone search at one position | Use SIA2 for the search step |
| **TAP can be very slow (tested)** | A simple 3-row query took **82 s** (IRSA's own notebook reports about 20 s for another query and 84 images) | Prefer SIA2. Use TAP only when we need data in its first day |
| **Many images per position (tutorial)** | The cutouts tutorial found **84 images** for one position in a single detector | Expect several hundred frames over all 6 bands. We will need to choose and group them |
| **Consecutive exposures (tested, inferred)** | At one position, three consecutive D2 images were about 129 s apart (small slews `_1`, `_2`, `_3` of one large slew) | Many images are only minutes apart and **cannot show motion** by themselves. Real motion shows up between **separate planning periods** (weeks to months). The frame builder should group by time (see "What is one frame?" in the overview) |
| **Wavelength differs between frames (inferred)** | Each frame is at a different wavelength | Brown dwarfs and comets change brightness a lot with wavelength, so frames of different wavelength look different even without motion. Co-add or compare **within the same detector/band**, and offer a band filter |

---

## 5. Tutorial notebooks

Python examples for accessing the data. Start here to prototype the backend (index: [IRSA notebook tutorials](https://irsa.ipac.caltech.edu/docs/notebooks)):

- [Introduction to SPHEREx Spectral Images](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro): SIA2 search with `astroquery`, reading the HDUs, the `WCS-WAVE` table and the result columns.
- [Download a collection of SPHEREx cutouts as a multi-extension FITS file](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts): TAP query plus parallel cutout download, computing the wavelength at the target. **Closest to what we need.**
- [Understanding and extracting the ePSF](https://caltech-ipac.github.io/irsa-tutorials/spherex-psf): what the PSF extension contains.
- [SPHEREx Source Discovery Tool demo](https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo): finds overlapping spectral images via SIA2 and uses `cloud_access`.
- [SPHEREx Mosaic](https://caltech-ipac.github.io/irsa-tutorials/spherex-mosaic): builds image mosaics with `photutils` and `reproject`. Relevant for co-adding images.
- [IRSA Cloud Access introduction](https://caltech-ipac.github.io/irsa-tutorials/): how to read the S3 copies.

The notebooks are written for `astroquery`, `astropy`, `numpy` and `matplotlib`.

---

## 6. WiseView (the model to imitate)

- Browser tool by citizen scientists Dan Caselden and Paul Westin. It blinks through WISE images from **unWISE time-resolved coadds**, one epoch per sky pass.
- Features worth copying: flipbook animation, adjustable stretch (asinh), zoom, Gaia overlay, no image subtraction needed.
- It has led to hundreds of brown dwarf discoveries.
- Differences for us: WISE has few bands and images are mapped cleanly onto fixed epochs. SPHEREx images vary in wavelength (see above), and the pixels are much coarser (6.15″).
- References: [Backyard Worlds blog post](https://blog.backyardworlds.org/2017/09/13/wiseview/), [ASCL entry](https://www.ascl.net/1806.004).

## 7. Gaia mission data

- Use **Data Release 3 (DR3)**. It gives positions, proper motions and parallaxes. It's useful as an overlay and for checking that a mover is real (e.g. Barnard's Star's known proper motion).
- Gaia positions are given at epoch **2016.0**. Proper motion must be applied to overlay them correctly on 2025–26 images.
- Access (not yet tested): the Gaia archive's TAP service, or CDS's Aladin Lite and VizieR (`I/355/gaiadr3`).

## 8. Partner resources: CSA / NEOSSat

Optional. These concern **NEOSSat**, a Canadian space telescope for tracking asteroids, comets, satellites and debris:

- NEOSSat overview page
- **Canadian Astronomy Data Centre (CADC)**: archive of Canadian and international observations
- NEOSSat data tutorial (Python visualization)
- NEOSSat dataset

These are not needed for the core tool. They could be a stretch idea (a second data source for moving objects), but the brief centres on SPHEREx.

---

## 9. Link list

| What | URL |
|---|---|
| SPHEREx at IRSA | https://irsa.ipac.caltech.edu/Missions/spherex.html |
| Archive user guide: data access | https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access |
| Archive user guide: data products | https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products |
| Release overview (QR/DR1) | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html |
| Cutout capabilities | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html |
| Cutout URL parameters | https://irsa.ipac.caltech.edu/ibe/cutouts.html |
| Browsable data directories | https://irsa.ipac.caltech.edu/ibe/data/spherex/ |
| SIA2 endpoint | https://irsa.ipac.caltech.edu/SIA? |
| TAP endpoint | https://irsa.ipac.caltech.edu/TAP |
| AWS S3 | bucket `nasa-irsa-spherex`, region `us-east-1`, see https://irsa.ipac.caltech.edu/cloud_access/ |
| Tutorial notebooks | https://irsa.ipac.caltech.edu/docs/notebooks |
| SPHEREx Explanatory Supplement | linked from the user guide (flag table, calibration details) |
| Pipeline paper | https://arxiv.org/pdf/2511.15823 |
