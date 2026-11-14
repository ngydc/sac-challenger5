> **Source:** SPHEREx Explanatory Supplement, document SSDC-DP-017, **Version 2.1, 2026-11-10**, 84 pages
> PDF: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf (about 30 MB)
> **Fetched:** 2026-11-14
> **Why extracts, not the whole thing:** the PDF is 84 pages. Only the parts you need for working with spectral images are kept here: acknowledgement, release/pipeline versions, file format, **the pixel-flag table (Table 16)**, and the known issues. Wording is condensed where marked; tables and flag names are exact.
> **What is NOT here:** the rest of the document (calibration products, Level 3, all-sky cube details beyond a pointer, Appendix A header listing). See "Not captured" at the end.
> **Page references** are PDF page numbers ("Page n of 84").

# Explanatory Supplement v2.1: extracts

## 1. Mission basics (Sect. 1.1, 1.4, 1.5)

- SPHEREx is a NASA Astrophysics Medium-class Explorer (MIDEX) mission performing the first all-sky spectral survey in the optical to near-infrared, **0.75 to 5.0 µm**.
- Launch: **12 March 2025, 03:10:12 UTC** (Falcon 9, Vandenberg). Regular science operations began **1 May 2025** after in-orbit checkout. (Other documents say 11 March 2025; see `source-discrepancies.md`.)
- Nominal **25-month** science mission with **four complete sky surveys**.
- **Surveys** are defined by time and spacecraft position angle (PA, relative to the line of constant ecliptic latitude through the boresight):
  - Survey 1: first 12.5 months, PA = 0
  - Survey 2: first 12.5 months, PA = 180
  - Survey 3: second 12.5 months, PA = 0
  - Survey 4: second 12.5 months, PA = 180
  - Surveys 3 and 4 are shifted on the sky by half a spectral channel relative to Surveys 1 and 2 (Nyquist sampling of spectra over the full mission). Elsewhere: "pointing targets ... are shifted by 6'" (the symbol was lost in the PDF text; read the PDF page 14 if the value matters).
- Observing pattern: a *target group* is **17 pointings** at the same ecliptic longitude, spaced one spectral-channel width apart in ecliptic latitude. The observatory does a **large slew** to a target group, then takes one exposure, then a **small slew** to the next target, and so on. Each exposure produces six spectral images (one per detector).
- **Deep Survey:** two deep fields at the north and south ecliptic poles (the southern one is offset slightly from the pole). Deep-field target groups heavily overlap, giving deep repeated coverage.
- Survey plans are loaded twice per week and named e.g. `2025W20_2B` (week of year, first/second half of the week = 1 or 2, version letter A, B, ...). The first plan of the science survey, `2025W17_4B`, has a 4 instead.

## 2. Acknowledgement (Sect. 1.6, page 10)

> "This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration."

## 3. Releases and pipeline versions (Sect. 2.1, pages 11 and 23-24)

- Calibrated spectral images are produced within a few days of acquisition and are available at IRSA **within 60 days** of observation.
- Full reprocessing after Year 1 (Surveys 1+2 = **DR1**) and Year 2 (Surveys 1-4 = **DR2**).
- An unplanned reprocessing of data from the start of the science survey to October 2025 was done and is **QR2**. QR2 files correspond to **pipeline versions 6.4 to 6.5.6**.
- **"Science users should NOT combine files from the two releases"** (QR1 and QR2): the exact file lists differ and the calibrations differ. (The QR1 text is historical; QR1 is retired.)
- **DR1 pipeline ("R7")**: pipeline versions **R7.0 and up** (`7.0 - 7.2` in Table 4). A major update: persistence masks, bad-pixel flagging, fine astrometry, outlier-pixel detection, zodiacal-light prediction, photometric measurements, PSF derivation; absolute gain and spectral calibrations were also updated. R7 images are labelled **DR1** (Surveys 1 and 2, reprocessed) and **QR3** (Surveys 3 and 4).
- The first weeks of Survey 3 and 4 data (**May 16, 2026 to July 19, 2026**) were first processed with pipeline **6.5.6**; their QR3/R7 versions are released with DR1.
- **"Due to the change in calibrations, we advise caution when combining QR2 and QR3 data."** The Spectrophotometry Tool was updated to apply the new gain calibrations to QR2 data.
- Table 4 (pipeline versions for the quick releases) is in the PDF on page 24 but its columns come out scrambled in text extraction, so it is **not** transcribed here. Facts that are clear from the surrounding text: QR2 = 6.4-6.5.6; files from 6.4 to 6.5.5 that were corrected for the PSF header issue carry the suffix `+psffix1`; 6.5.6 and later were not affected; DR1/QR3 = 7.0+.

## 4. Spectral image file format (Sect. 2.2, pages 11-14)

- One file per **sky pointing and detector**. "While no zodiacal light subtraction is applied, each file includes an estimated background level (using the model described in Crill et al. [2025]) to support downstream analysis."
- **File size: approximately 67 MB** (the User Guide says about 70 MB).
- Filename convention (Table 3 example): `level2_2025W22_2B_0001_1D3_spx_l2b-v4-2025-152.fits`; observation ID `2025W22_2B_0001_1`; survey planning period `2025W22_2B`; large slew counter `0001` (starts from 0); small slew counter `1` (starts from 1, max 4); detector `3`; processing time `2025-152` (152nd day of 2025).
- **Format:** an MEF with **six HDUs: five image extensions and one binary table**:
  - `IMAGE`: calibrated surface brightness, **MJy/sr**, 2,040 x 2,040.
  - `FLAGS`: bitmap of per-pixel status/processing flags, 2,040 x 2,040 (see Table 16 below).
  - `VARIANCE`: per-pixel variance, **(MJy/sr)^2**, 2,040 x 2,040.
  - `ZODI`: model zodiacal light background, MJy/sr, 2,040 x 2,040 (not subtracted from `IMAGE`).
  - `EPSF`: over-sampled ePSFs. **441 rows = a 21 x 21 grid for detectors 1, 2, 4, 5 and 6; 451 rows = an 11 x 41 grid for detector 3.** The PSF is normalised to its integral and is dimensionless.
  - `WCS-WAVE`: spectral WCS lookup table (binary table, 3 columns, 1 row). "The fidelity of this lookup table is suitable for visualization, but for science analysis, the Spectral WCS files (Sec. 4.3.1) should be used."
- **Header:** key fields include observation ID, detector number, creation time, exposure start time (UTC), exposure duration; astrometric metadata (coordinate system and optical distortion parameters); calibration product identifiers; an approximate pixel-to-wavelength mapping; spacecraft and instrument parameters (mean array and telescope mirror temperatures). The **full list of processing modules executed and their software versions** is recorded in the header.
- **Long keywords use the HIERARCH convention** (https://fits.gsfc.nasa.gov/registry/hierarch_keyword.html), because they exceed the 8-character FITS limit. (This is why the intro notebook's header search is written `'L2 N_*'`, with a space.)
- The planned boresight pointing is in ecliptic coordinates in header keywords. The text names them `SPS_LON_ECL`, `SPS_LAT_ECL`, `SPS_PA_ECL` (underscores partly lost in the PDF text), but the Appendix A example lists `SPS_ELON`, `SPS_ELAT`, `SPS_EPA`. **These two disagree; read the real header before using either.** The position-angle keyword tells you which survey (1-4) an observation belongs to, using the PA and time rules in section 1 above.
- `CRVAL1`/`CRVAL2` hold the RA/Dec calculated per band in the astrometric calibration. The `IMAGE` header has a WCS giving an approximate pixel-to-wavelength mapping.
- A python notebook demonstrating how to explore the extensions: https://caltech-ipac.github.io/irsa-tutorials/tutorials/spherex/spherex_intro.html (same content as `tutorial-intro-spectral-images.md`).
- **QR2 PSF-layer header note (page 13):** the PSF cube planes are stored in order of increasing x-index but the original header said increasing y-index; fixed March 31, 2026 for QR2; "this issue does not apply to QR3 or DR1 calibrated images." Details in `irsa-psf-header-error.md`.

## 5. Pixel flags: Table 16 (Sect. 3.2.5, pages 33-35)

The FLAGS extension is a coded map, not a simple binary mask: "each pixel is annotated with a symbolic flag indicating its classification. **Each flag corresponds to a specific bit position**, with standardized symbolic identifiers assigned to defined conditions. The full set of flag names is recorded in the header of the associated spectral image output file." Flags are generated in several pipeline modules and preserved in the released images.

> The "Bit #" column is the bit position, as the paragraph above says. That a pixel has flag *n* set when bit *n* of the integer is 1 (mask value 2**n) is standard bitmask arithmetic, not a statement in the document. The intro notebook shows how to list the flags from the real `FLAGS` header (`MSKN####` = name, `MSKD####` = description), which is the safest way to confirm the numbering for the release you use.

| Symbolic name | Bit # | Description (condensed from the PDF) |
|---|---|---|
| `TRANSIENT` | 0 | Transient (such as a cosmic-ray hit) detected during SUR (sample-up-the-ramp). Transients in the first ten seconds may not be flagged. Can also indicate charge spillover (bloom) from very bright neighbours. |
| `OVERFLOW` | 1 | Overflow threshold reached during SUR; threshold is about half of full-well saturation. |
| `SUR_ERROR` | 2 | `chksum_error` bit from instrument data processing. Alone: a data-handling error in the onboard SUR algorithm. Combined with `TRANSIENT`/`OVERFLOW`: early transient (first half of exposure) or early overflow (first ~5 s). |
| `NONFUNC` | 6 | Static pre-flight assessment that a pixel is permanently unusable/dead; may be updated during the mission. "Unusable for any purpose." |
| `DICHROIC` | 7 | Pixels in the "dark corners" of Bands 3 and 4 where the "smile" effect gives a bandpass incompatible with their side of the dichroic; low expected throughput (below 50%), "not usefully calibratable or of value for photometry". |
| `MISSING_DATA` | 9 | Onboard data lost before ingest (e.g. corrupted downlink packages not retransmitted); no data for this pixel in this image. |
| `HOT` | 10 | Hot pixel (noisy / spurious signal), determined per exposure; permanently hot pixels are `NONFUNC`. Not usable for science. |
| `COLD` | 11 | Pixel unresponsive to light or with anomalously low signal in this exposure; permanently dead pixels are `NONFUNC`. Not usable for science. |
| `FULLSAMPLE` | 12 | Full sample history is available (rotating 8 x 32 pixel full-readout region). "Not usable for science, purely informational." |
| `PHANMISS` | 14 | Pixel cannot be corrected because of missing phantom pixels. |
| `NONLINEAR` | 15 | No reliable nonlinearity correction could be determined; poor photometric accuracy, "should be excluded from most scientific analyses". |
| `PERSIST` | 17 | Affected by persistent charge above the Level 2 threshold. |
| `OUTLIER` | 19 | Flagged by the "Detect Outlier Pixels" module (Sect. 3.2.10). |
| `CROSSTALK` | 20 | Affected by "ordinary" crosstalk (Sect. 3.2.9). |
| `SOURCE` | 21 | Pixel mapped to a known source. (The intro notebook notes that most pixels typically carry this flag.) |
| `GHOST` | 22 | Optical ghost from a bright source inside the exposure frame (Sect. 3.2.9). |
| `GHOST_FPA` | 23 | Ghost from a bright source seen on another detector in the FPA. "Currently unused (subsumed into GHOST_EXT) and will be removed in Year 2 processing." |
| `GHOST_EXT` | 24 | Ghost from a bright source outside the field of view. "Currently in development." |
| `STREAK` | 25 | Affected by a streak, presumably from an object in Earth orbit (Sect. 3.2.10). |
| `BLOOM` | 26 | Affected by source blooming (Sect. 3.2.1). |
| `SNOWBALL` | 27 | Affected by snowball events (very large quantities of electrons released) (Sect. 3.2.1). |
| `HALO` | 28 | Affected by the halo of a transient. "Caution is recommended when using this pixel in science analysis" (Sect. 3.2.1). |
| `SATELLITE_HALO` | 29 | Affected by the halo of a satellite streak. "Not recommended for use in science analysis" (Sect. 3.2.1). |

**Note column of the PDF table (not mapped per flag here):** the PDF's right-hand "Note" column uses merged cells: "Determined onboard (Level 0)" (next to `TRANSIENT`, `OVERFLOW`, `SUR_ERROR`), "Static" (`NONFUNC`), then "Set by the Level 1 pipeline based on per-image data content and quality assessment" and "Set by the Level 2 pipeline based on per-image data content and quality assessment" for the later rows. Which rows each of the last two covers cannot be read reliably from the PDF text, so it is left out. Check pages 33-35 of the PDF if you need it.


Gaps in the bit numbers (3, 4, 5, 8, 13, 16, 18) are not described in Table 16. Do not assume what they mean.

**NaN pixels:** "For a small number of pixels, the Level 1 processing sets the pixel value to NaN", when the onboard error bit is set together with an early-overflow or `SUR_ERROR` flag (page 23-24). Early-overflow pixels at the centres of bright sources "have no determinable flux measurement, and so are assigned NaN" (crosstalk figure caption, page 17).

**Header counters:** the header carries counts of flagged pixels, e.g. `L2.N_SOURCE`, `L2.N_BLOOM_NS`; per the intro notebook, names ending `_NB` count pixels "not also flagged as bad" and `_NS` count pixels "not also flagged SOURCE".

## 6. Anomalies and features in the images (Sect. 2.3, pages 14-18)

"A small percentage of the SPHEREx on-sky data show a range of image artifacts, atmospheric features, and anomalies." A list of images with a substantial contaminated portion is maintained at https://spherex.caltech.edu/page/anomalyimages. Summary (condensed):

**Anomalies (optics/detector/particles):**
- *Frame-edge ghost*: light from sources focused just outside the detector can scatter in; roughly triangular; any of four edges; left/right-edge ghosts can repeat across several exposures of a small-slew sequence.
- *Linear bright-source ghost*: very bright sources off the top/bottom of the detector; stronger at longer wavelengths.
- *Beam-splitter ghost*: reflection off the dichroic beam splitter, a disk (diameter lost in extraction); most prominent near the Band 3/4 boundary, present at lower level in Bands 3-6.
- *Stray-light artifact from very bright stars* about 8 (units lost in extraction) away, in a fraction of exposures in Bands 2-6.
- *Moon stray light* at the left/right detector edge in a fraction of exposures in Bands 1, 4, 5, 6.
- *Extended cosmic-ray signatures*: cosmic rays above 100 photoelectrons are removed onboard, but many affect neighbours; **snowballs** give a core flagged `OVERFLOW`+`TRANSIENT` with an extended halo of *unflagged* pixels. For R7, extra flags were added (`BLOOM`, `SNOWBALL`, `HALO`, `SATELLITE_HALO`).
- *Cosmic-ray-induced glow*: faint diffuse glow, strongest in Bands 1-2.
- *Crosstalk*: percent-level to nearest neighbours, plus three long-range forms: (1) a negative image of a bright source displaced vertically by 32 rows, (2) a smear after a bright last-read pixel in the prior row, (3) crosstalk between readout channels spaced by multiples of 64 pixels horizontally. **In R7 the first two types are flagged** (Sect. 3.2.9).

**Features (atmospheric / non-astrophysical):**
- *Atmospheric He emission line at 1.083 µm* in Bands 1 and 2, "a factor few to a factor of 30" brighter than the zodiacal background; varies over the orbit and with time; "astrophysical sources are visible behind the emission". Can produce weak spectral leak features in Band 1 (pixels with band centre near 0.84 µm) and Band 2 (near 1.49 and 1.25 µm).
- *Auroral emission lines* mainly in Bands 1-2, more frequent over polar regions, can be a factor of a few above the zodiacal background.
- *Other atmospheric lines* of variable amplitude at 0.78, 0.84, 0.93, 1.13, 1.81, 2.63, 2.75, 4.03 and 4.64 µm.
- *Shuttle glow*: emission from spacecraft/atmosphere interaction, mitigated by limiting ram angle; most contamination at 2.9 µm in Band 4 and 4.5 µm in Bands 5-6.
- *Diffuse optical transients*: roughly **1% of exposures** show diffuse ephemeral features believed to be foreground objects/particles.
- *Earth-orbiting satellite streaks*: seen in many images; brightest are flagged onboard as transients (possibly also `SATELLITE_HALO`); fainter ones by the outlier module as `STREAK`; **streaks near the noise level may not be flagged.**
- **Level 1 note (page 24):** templates for helium, aurora and shuttle glow are *correlated* with each image and fit amplitudes/correlation coefficients are written to the Level 2 header, but "emission from these lines is **NOT subtracted** from the calibrated images."

## 7. Known limitations of spectral images (Sect. 2.4, pages 18-20)

- **Incorrect source masking**: the `SOURCE` mask size is set from the magnitude in the Reference Catalog; if the magnitude estimate is wrong the mask is too large or too small.
- **Pixels at the dichroic edge**: the long-wavelength side of Band 3 and the short-wavelength side of Band 4 have rows where sensitivity and spectral response are affected by the beam splitter. Pixels with throughput below 50% have `DICHROIC` set. "While the gain calibration includes the decreased throughput, users should exercise caution when working with sources in these areas of the detectors, as the noise will be increased and the photometric calibration will be more uncertain."

## 8. Known issues in the Level 3/mosaic products (Sect. 3.4.10, page 50), and masking history

(Written about mosaics, but it states what the Level 2 masks do not catch.)
- Airglow and extended-source emission lines cause stripe artifacts in mosaics (see section 6 above).
- **Residual artifacts from incomplete Level 2 masking:**
  - Snowball, bloom and halo masking was introduced **starting with planning period 2025W51_1A (December 2025) and pipeline version 6.5**. "Quick Release 2 images from prior planning periods have these artifacts unmasked." All images will include this masking after the Year 1 release.
  - Satellite-streak masking is incomplete, and crosstalk masking "was not implemented in Quick Release 2 processing" (to be included after the Year 1 release).

## 9. All-sky cube and the pipeline

- All-sky cubes: Sect. 2.5 (page 21) and known issues in Sect. 2.5.2 (page 22). The User Guide's summary of both is in `user-guide-data-products.md`.
- The FLAGS extension of the all-sky cube has `MP <FLAG NAME>` keywords defining the bit position of each propagated flag (Sect. 3.4, page 50). Text says "(needs reference)".

## Not captured here

- **Appendix A, Table A.35 (example spectral-image header, pages 73-76):** the PDF text extraction scrambles the Description/Units columns against the keyword names, so it was **not** transcribed (a wrong keyword-to-meaning mapping would be worse than none). Use the page in the PDF, or read keywords from a real file's header.
- Calibration products (Sect. 4), Level 3 photometry (Sect. 3.3), all-sky cube construction (Sect. 3.4), data-quality assessment (Sect. 3.2.12), astrometry accuracy (Sect. 3.2.8), the zodiacal-light model (Sect. 3.2.11), source and outlier masks (Sect. 3.2.9-3.2.10).
