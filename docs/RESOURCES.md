# Planet X and SPHEREx — Resources

Details on every resource listed on the challenge page, plus the SPHEREx data format and what we measured when testing the IRSA services. Part of the [project overview](PROJECT_OVERVIEW.md).

Sources: IRSA's [SPHEREx Archive documentation](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products) and tutorials, read on 2026-11-14. Items marked **(tested)** are things we ran ourselves that day. Items marked **(inferred)** are our own reading and need checking.

## Contents

1. [IRSA: where the SPHEREx data lives](#1-irsa-where-the-spherex-data-lives)
2. [Data format](#2-data-format)
3. [How to get the data](#3-how-to-get-the-data)
4. [What we measured (and what it means for the design)](#4-what-we-measured-and-what-it-means-for-the-design)
5. [Tutorial notebooks](#5-tutorial-notebooks)
6. [WiseView](#6-wiseview-the-model-to-imitate)
7. [Gaia](#7-gaia-mission-data)
8. [Partner resources: CSA / NEOSSat](#8-partner-resources-csa--neossat)
9. [Link list](#9-link-list)

---

## 1. IRSA: where the SPHEREx data lives

The NASA/IPAC Infrared Science Archive (IRSA) is our **only required data source**.

### Mission and release timeline

- SPHEREx launched in **March 2025**. Its planned mission is **two years** of spectroscopy from 0.75 to 5.0 µm over the whole sky, with deeper coverage in the "Deep Fields".
- IRSA releases new spectral images **weekly** ("Quick Releases"), with higher-level products to follow.

| Release | When | Status now |
|---|---|---|
| QR1 | from July 2025 | retired Feb 2026, gone |
| QR2 | from Oct 2025 (better calibration, reprocessed QR1) | **no longer searchable.** Direct download only until **Feb 2027**. Do not build on it |
| QR3 | from Sept 2026 (better PSF and photometry calibration) | **current**, weekly updates |
| **DR1** | **Nov 2026** (reprocesses the QR2 data) | **current** |

**DR1 and QR3 together form one uniformly processed set** of spectral images. To search "everything", query both. Older web pages and tutorials mention `spherex_qr` and `spherex_qr2`. Ignore those.

### Access layers

| Layer | What it is | Best for |
|---|---|---|
| **SIA2 API** | IVOA Simple Image Access v2: find images by position, band, time. `https://irsa.ipac.caltech.edu/SIA?` | Finding which images cover a patch |
| **Cutout service** | Append `?center=RA,Dec&size=DEG` to an image URL to get a small piece | Fetching the frames for the blink video |
| **TAP API** | SQL-like (ADQL) queries on metadata tables: `https://irsa.ipac.caltech.edu/TAP` | Finding images immediately after weekly ingestion |
| **Browsable directories** | Plain web directories: `https://irsa.ipac.caltech.edu/ibe/data/spherex/` | Bulk downloads with wget or curl, calibration files |
| **AWS S3 mirror** | Bucket `nasa-irsa-spherex` (region `us-east-1`, anonymous access) | Cloud processing |
| **SPHEREx Data Explorer** | IRSA's own web GUI | Manual exploration and comparison |
| **Python** | `astroquery.ipac.irsa` (recommended) and `pyvo` | Prototyping and the backend |

Notes:
- New data appears first in the browsable directories, the Data Explorer and certain TAP queries. **SIA2 lags by about a day.**
- The cutout service only works on the **on-premises** copy, not on S3.
- Calibration files are **not** available through SIA2, only through the directories.
- S3 prefixes: `dr1`, `qr3`, `qr2`. Prepend the prefix to the directory layout from the data products page.

---

## 2. Data format

### Observation structure and naming

- The satellite follows a **survey plan** uploaded in "planning periods" of about **3.5 days**, e.g. `2025W18_2B`.
- Each pointing is an **observation ID**: `2025W18_2B_0001_1` = planning period + large slew counter (`0001`) + small slew counter (`1`–`4`, at most 4 per large slew).
- Each pointing gives **6 spectral image files, one per detector** (`D1`–`D6`). Some observations lack some of the six, because quality is checked per band.
- Filename: `level2_[ObservationID]D[Detector]_spx_l2b-v[Version]-[ProcessingDate].fits`
  - Example: `level2_2025W18_2B_0001_1D1_spx_l2b-v12-2025-164.fits`
  - Processing date is `year-dayofyear`. Version is currently around v27.
- On-premises path: `ibe/data/spherex/<release>/level2/<PlanningPeriod>/l2b-v<ver>-<procdate>/<detector>/<file>`

### The main product: Level 2 Spectral Image (multi-extension FITS)

About **70 MB** per file. Every image is **2040 × 2040 pixels**, about **6.15″ per pixel** (the PSF docs give 6.15″ exactly). The file has a minimal primary HDU (no data, but the `VERSION` keyword) plus six extensions:

| HDU | Name | Content | Notes |
|---|---|---|---|
| 1 | `IMAGE` | Calibrated surface brightness, **MJy/sr**, float32 | **No zodiacal light subtracted.** This is what we display |
| 2 | `FLAGS` | Per-pixel bitmap of status and processing flags, int32 | Definitions in Table 16 of the SPHEREx Explanatory Supplement. Source for "contamination flags" |
| 3 | `VARIANCE` | Variance of the flux, (MJy/sr)² | For noise-weighted co-adds |
| 4 | `ZODI` | Modelled zodiacal light background, MJy/sr | Not subtracted from `IMAGE`. Subtract it yourself if you want a cleaner background |
| 5 | `EPSF` (DR1, QR3) or `PSF` (QR2) | Point spread functions | **Large and not needed for display** (see section 4) |
| 6 | `WCS-WAVE` | Lookup table mapping pixel to central wavelength and bandwidth | Uses a rarely supported FITS standard. See below |

### Spatial coordinates

- The sky coordinate system (WCS) is in the `IMAGE` header, and `astropy.wcs.WCS(header)` reads it. (IRSA also publishes separate SIP distortion files, which we haven't looked at.)
- Header keywords are 1-based (FITS), astropy pixel coordinates are 0-based. This trips people up in cutouts: `CRPIX1A`/`CRPIX2A` give the cutout's offset in the original image.
- Time: the TAP table column `time_bounds_lower` is the observation time, apparently in MJD (e.g. `60801.1066`, which is early May 2025). The SIA2 table has `t_min`/`t_max` **(inferred: MJD)**.

### The wavelength is different for every pixel

This is the unusual part, and it matters for our tool.

- SPHEREx has **linear variable filters (LVFs)**: the wavelength changes smoothly across each detector array.
- So **one exposure is a spectral image**: a source seen at the left of the detector and the same source seen at the right are measured at different wavelengths. Spectra are built by repointing the telescope so each source lands at many positions over time.
- For a cutout, **each frame has one effective wavelength at the target's position**. Get it from the `WCS-WAVE` HDU: `WCS(header, fobj=hdulist, key="W")` and `pixel_to_world(x, y)`. The IRSA cutouts tutorial shows exactly this.
- The `WCS-WAVE` table is meant for visualisation (about 1 nm accuracy). For science use the `CWAVE` and `CBAND` images in the separate Spectral WCS calibration product.

### The six bands (one per detector)

| Detector | Band | Wavelength (µm) | Resolving power R |
|---|---|---|---|
| D1 | 1 | 0.75 – 1.09 | 39 |
| D2 | 2 | 1.10 – 1.62 | 41 |
| D3 | 3 | 1.63 – 2.41 | 41 |
| D4 | 4 | 2.42 – 3.82 | 35 |
| D5 | 5 | 3.83 – 4.41 | 112 |
| D6 | 6 | 4.42 – 5.00 | 128 |

- Two focal plane assemblies (short-wave D1–D3 and long-wave D4–D6) observe at the same time through a dichroic beam splitter. Each holds three 2K × 2K arrays.
- The bandpass name used in queries is `SPHEREx-D1` … `SPHEREx-D6`.
- 102 spectral **channels** = 6 detectors × 17 channels. The `Spectral Channels` calibration product maps each pixel to a channel (0–18).

### Other products (probably not needed for the tool)

| Product | Notes |
|---|---|
| **All-Sky Cube** (DR1 only) | Pre-built spectral cubes: 12,288 tiles (HEALPix order 5, about 1.8° × 1.8°), 512 × 512 pixels at 12.9″, 102 channels, **zodi subtracted**. Also served as a **HiPS** tree of PNGs (one per channel, display only, fixed 0–40 MJy/sr stretch). Averaged over time, so **no time information**. Not usable for blinking, but could be a static background or overview layer. Channels 51 and 52 are empty. Helium sky emission at 1.083 µm produces stripes |
| Calibration files | Gain, dark, dichroic, nonlinearity, read noise, PSFs, solid angle map, SIP, crosstalk and others. Only in the directories, not SIA2 |
| Spectral WCS (`CWAVE`, `CBAND`) | Per-pixel wavelength and bandwidth, ~32 MB per detector |
| Solid Angle Pixel Map | Pixel area in arcsec² |

DOIs for citing: QR1 `10.26131/IRSA629`, QR2 `10.26131/IRSA652`, QR3 `10.26131/IRSA662`. The data policy asks for this acknowledgement:
> "This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration."

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

SIA2 reports the full wavelength coverage of each array, which is a little wider than the nominal ranges in the earlier band table. Neighbouring arrays overlap slightly.

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

### Step 1 (find images): SIA2

Collections (the `COLLECTION` parameter):

| Collection | Content |
|---|---|
| `spherex_dr1` | DR1 spectral images, Wide Survey (uniform all-sky coverage) |
| `spherex_dr1_deep` | DR1, Deep Survey fields |
| `spherex_dr1_cube` | DR1 All-Sky Cube tiles |
| `spherex_qr3` | QR3 spectral images, Wide Survey |
| `spherex_qr3_deep` | QR3, Deep Survey |

To search everything current, query `spherex_dr1` and `spherex_qr3` (and the `_deep` collections if you want the deep fields).

```bash
curl -o result.xml "https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_qr3&POS=circle+127.69444+-39.17760+0.01"
```
Add `&RESPONSEFORMAT=HTML` for a readable table. `POS=circle RA Dec RADIUS` is in decimal degrees.

Python:
```python
from astroquery.ipac.irsa import Irsa
results = Irsa.query_sia(pos=(coord, search_radius), collection=['spherex_dr1', 'spherex_qr3'])
```

Useful columns in the result (standard IVOA names): `access_url` (on-premises download URL), `cloud_access` (S3 info), `obs_id`, `energy_bandpassname`, `em_min`, `em_max`, `t_min`, `t_max`, `calib_level`, `dataproduct_subtype`, `obs_collection`.

### Step 2 (get small pieces): cutouts

Append `center` and `size` (degrees) to an `access_url`:

```bash
curl -o cutout.fits "https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2/2026W21_2A/l2b-v27-2026-268/1/level2_2026W21_2A_0001_2D1_spx_l2b-v27-2026-268.fits?center=337.8783221,-5.1891588&size=0.1"
```
- The cutout is a full multi-extension FITS: the same six HDUs, with `IMAGE`, `FLAGS`, `VARIANCE` and `ZODI` cropped, `WCS-WAVE` adjusted to the cutout, and the PSF HDU left **whole**.
- `size=0.1` gave a 58 × 59 pixel image in one test and 59 × 59 in another **(tested)**: 0.1° is 360″, and 360″ / 6.15″ ≈ 58.5 pixels. Don't assume an exact size.
- More options: https://irsa.ipac.caltech.edu/ibe/cutouts.html

### Alternative to steps 1 and 2: one TAP query

The IRSA cutouts tutorial finds the images and builds the cutout URLs in one query, and reads the times too. Tables: `spherex.artifact` (files) and `spherex.plane` (per-image metadata):

```sql
SELECT 'https://irsa.ipac.caltech.edu/' || a.uri || '?center=RA,Decd&size=0.1' AS uri,
       p.time_bounds_lower
FROM spherex.artifact a
JOIN spherex.plane p ON a.planeid = p.planeid
WHERE 1 = CONTAINS(POINT('ICRS', RA, DEC), p.poly)
  AND p.energy_bandpassname = 'SPHEREx-D2'
ORDER BY p.time_bounds_lower
```
(Run through `Irsa.query_tap(query)` or `https://irsa.ipac.caltech.edu/TAP/sync?QUERY=...&LANG=ADQL&FORMAT=csv`.) It sees new data right after weekly ingestion, without the SIA2 delay of about a day.

### Reading the files (Python)

```python
from astropy.io import fits
from astropy.utils.data import conf
conf.remote_timeout = 120          # SPHEREx reads can exceed astropy's default timeout
with fits.open(url, cache=True) as hdul:
    image = hdul[1].data           # IMAGE, MJy/sr
    flags = hdul[2].data
```

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
