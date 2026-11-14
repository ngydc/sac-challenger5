# Paper summary: Akeson et al., the SPHEREx image and spectrophotometry processing pipeline

> **This is a summary, not the paper's text.** Written 2026-11-14 from the arXiv v2 PDF.
> **How much was read:** the abstract and Sect. 1 (mission overview), Sect. 2 start (pipeline levels), Sect. 4 (modules, Level 1 to Level 3 and calibrations) and Sect. 5 (data products and cadence) were read closely. Sect. 2 (rest), 3 (ingest), 6 (archive tools), 7 (operations) and 8 (upgrades) were **not** read in detail.
> **Caution on dating:** v2 says "at the time of writing, the pipeline version is 6.4" and still lists the PSF extension as `PSF`. That predates the R7 pipeline (DR1/QR3) with its `EPSF` extension. For the current file format and flags, trust the Explanatory Supplement and the User Guide over this paper (see `source-discrepancies.md`).

| | |
|---|---|
| **Title** | The SPHEREx image and spectrophotometry processing pipeline |
| **Authors** | Rachel Akeson, Gregory P. Dubois-Felsmann, Brendan P. Crill, Andreas L. Faisst, Tamim Fatahi, Candice M. Fazar, Tatiana Goldina, Daniel C. Masters, Christina Nelson, Roberta Paladini, Harry I. Teplitz, Gabriela Torrini, Phani Velicheti, Matthew L. N. Ashby, and 30 others (44 authors in total; last author Michael Zemcov) |
| **Venue** | Astrophysical Journal Supplement Series (accepted July 5, 2026). IRSA cites it as **Akeson et al. (2026)**, ApJS 285, 67 |
| **arXiv** | arXiv:2511.15823 (v1 submitted 19 Nov 2025, hence "2025"; v2 revised 7 Jul 2026). Abstract: https://arxiv.org/abs/2511.15823 · PDF: https://arxiv.org/pdf/2511.15823 |
| **ADS** | https://ui.adsabs.harvard.edu/abs/2026ApJS..285...67A/abstract |
| **Code** | The pipeline modules are public: https://github.com/Caltech-IPAC/spherex-pipelines (pointed to by the paper) |

## What it is

The description of the software system, run by the SPHEREx Science Data Center (SSDC) at Caltech/IPAC, that turns raw spacecraft data into calibrated spectral images and photometry. It documents the fixed top-level structure; module-level algorithms and calibration provenance live in the Explanatory Supplement.

## Key points for working with the data

**Instrument and survey (Sect. 1)**
- Two focal-plane sides, each with 3 H2RG detector arrays, each behind a linear variable filter. Each detector covers **3.5 x 3.5 degrees** with **6.15 arcsec pixels**. Short-wave side (bands 1-3) covers 0.75-2.44 µm; long-wave side (bands 4-6) covers 2.40-5.01 µm. **Bands 1 & 4, 2 & 5, 3 & 6 cover the same region of sky**, so each exposure gives two wavelengths per point in the field. "Each detector pixel samples a single wavelength."
- 102 spectral channels, four all-sky surveys in the 25-month prime mission, plus hundreds of observations per channel in deep fields at the ecliptic poles.
- Small slews between exposures within a target group are quoted as 17' here; the Bock mission paper says 11.8'. Treat as unresolved (see `source-discrepancies.md`).

**Processing levels (Sect. 2, Table 1)**
- Level 0 raw packets → Level 1 FITS images in engineering units (e-/s) → **Level 2 calibrated spectral images (FITS)** → Level 3 spectro-photometric measurements (Apache Parquet) → Level 4 science catalogs/images.

**What happens to the pixels in Level 1 and 2 (Sect. 4)**
- Level 1 gives only a coarse astrometric solution (accuracy **2'-10'**); the fine astrometry is done in Level 2.
- Level 2a (per-detector, in acquisition order, because persistence carries from one image to the next): nonlinearity correction, **variance map** (per-pixel, method of Robberto 2007), **persistence** model and flags. Reference and phantom pixels are removed afterwards.
- Level 2b: bad-pixel mask (the multi-bit **flag** map; the flag list is in the Explanatory Supplement), dark/flat/absolute-gain calibration (**output units MJy/sr**), **fine astrometry**, known solar-system-object positions (using the orbit tool kete), source mask, outlier-pixel detection, zodiacal-light model, and creation of the spectral-image file.
- **Fine astrometry:** calibrators are Gaia-based; a solution is found with Astrometry.net then refined with scamp. A header keyword **`FINAST`** records astrometric quality: value **0 means rms < 1 arcsec**; "the median astrometric alignment precision of images with a `FINAST` flag equal to zero reaches **0.1-0.4 arcsec** on average."
- **Zodiacal light:** an empirical, time-variable model (Kelsall et al. 1998 updated with Tsumura et al. 2013; see also Crill et al. 2025). It "is **not subtracted** from the image but is provided for later operations, such as mosaicing."
- **What a public image must pass (Level 2 data-quality assessment):** pass at least half of the module tests, be outside the South Atlantic Anomaly, have fewer than **435,000** transient pixels, and have a fine-astrometry flag value of 0.
- Level 3 (not the raw images): forced photometry at known source positions (Tractor-style), 15 x 15 pixel cutouts, with global or local background subtraction; Level 3 output is Parquet catalogs, not FITS images.

**Calibration products (Sect. 4.4, 5.1)**
- PSF: measured on an 11 x 11 grid (121 zones) by stacking stars at **10x oversampling**, because the PSF is "significantly undersampled at SPHEREx resolution". (The newer ePSF is described in the Explanatory Supplement and the PSF notebook.)
- **Spectral WCS:** central wavelength is where the cumulative transmission reaches 50% of its total area (the median of the transmission curve per pixel); bandwidth = central wavelength divided by the measured spectral resolution. The `CWAVE`/`CBAND` extensions (from laboratory measurements) "should be used for science investigations"; `WCS-WAVE` is "a compact piecewise-bilinear approximation provided for visualization", following the FITS WAVE-TAB standard.
- The calibration file versions used for an image are recorded in its header; all calibration files are at IRSA.

**Data products and timing (Sect. 5)**
- One spectral-image FITS file **per band per exposure**; extensions listed (in this paper's v2) as IMAGE, FLAGS, VARIANCE, ZODI, PSF and WCS-WAVE; **72 MB per spectral image**; total about 190 TB; available "within 60 days of data acquisition".
- All-sky cubes (Year 1 release Nov 2026, Year 2 Nov 2027), ~95 TB.
- **High Reliability Source Catalog (HRSC):** sources with SNR > 10 in at least 5 of the 102 channels that pass a survey-to-survey consistency test; planned July 2027.
- Full reprocessing after Year 1 (DR1) and Year 2 (DR2). An extra reprocessing in Aug-Sep 2025 produced QR2; the paper "strongly recommend[s] use of QR2 data for all science applications" (at the time of writing; superseded by DR1+QR3).
- DOIs quoted for QR1 (10.26131/IRSA629) and QR2 (10.26131/IRSA652).

## What this paper does *not* tell you
- It does not define the FLAGS bit table (points to the Explanatory Supplement), does not list header keywords, and does not give photometric uncertainties or noise performance in the sections read.
