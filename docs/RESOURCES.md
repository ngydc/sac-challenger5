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
- `size=0.1` gave a 58 × 59 pixel image **(tested)**: 0.1° is 360″, and 360″ / 6.15″ ≈ 58 pixels.
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
