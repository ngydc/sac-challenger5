# Paper summary: Bock et al., The SPHEREx Satellite Mission

> **This is a summary, not the paper's text.** Written 2026-11-14 from the arXiv v2 PDF (30 pages).
> **How much was read:** the abstract, the introduction, the instrument/survey parameter tables (Tables 1-2), the survey-design and optics passages, and the parts on the data-processing flow, archive access and in-flight pointing. The cosmology forecasts (inflation, intensity mapping) and most of the instrument engineering and thermal sections were **not** read in detail.

| | |
|---|---|
| **Title** | The SPHEREx Satellite Mission |
| **Authors** | James J. Bock, Asad M. Aboobaker, Joseph Adamo, Rachel Akeson, John M. Alred, and 109 others (114 authors in total) |
| **Venue** | The Astrophysical Journal (accepted Dec 9, 2025). IRSA cites it as **Bock et al. (2026)**, ApJ 999, 139. DOI 10.3847/1538-4357/ae2be2 |
| **arXiv** | arXiv:2511.02985 (v1 submitted 4 Nov 2025, hence "2025"; v2 revised 15 Dec 2025). Abstract: https://arxiv.org/abs/2511.02985 · PDF: https://arxiv.org/pdf/2511.02985 |
| **ADS** | https://ui.adsabs.harvard.edu/abs/2026ApJ...999..139B/abstract |

## What it is

The mission paper: why SPHEREx exists, how the satellite, instrument and survey are designed, and an early look at in-flight performance.

## Key points for working with the data

**What the mission measures**
- The first all-sky near-infrared **spectral** survey: **102 spectral bands, 0.75 to 5.0 µm**, resolving power λ/Δλ about **35-130**, **6.2 arcsec pixels** (IRSA says 6.15").
- After mapping the full sky four times over two years, the quoted **5σ depth** is **19.5-19.9 AB mag** for 0.75-3.8 µm (λ/Δλ ~ 40) and **17.8-18.8 AB mag** for 3.8-5.0 µm (λ/Δλ ~ 120). (This is the final, four-survey depth, not the depth of one exposure.)
- Science themes: galaxy redshift survey to constrain inflation (non-Gaussianity); deep spectral maps near the ecliptic poles (intensity mapping); mapping ice absorption features across the Galactic plane. Spectral catalogs of planet-bearing and low-mass stars, solar-system objects and galaxy clusters are planned for ~3 years after launch.

**Instrument (Tables 1 and 2, optics section)**
- Off-axis three-mirror telescope, **20.0 cm effective aperture**, a wide **3.5° x 11.5°** telecentric field of view split by a dichroic beam splitter (DBS) onto two focal planes. **6 H2RG detectors.** Sun-synchronous orbit (Table 1). Science data volume about 20 GB/day.
- **Optical distortion up to 0.5% over the field, "which must be accounted in the data processing"** (so pixel scale/orientation vary across an image; this is why the image WCS carries SIP terms).
- Linear variable filters: **17 spectral channels per band**, 6 bands = 102 channels. A band's wavelength changes continuously along the array. Table 2 (wavelength range; resolving power): B1 0.75-1.11 µm (41); B2 1.11-1.64 (41); B3 1.64-2.42 (41); B4 2.42-3.82 (35); B5 3.82-4.42 (110); B6 4.42-5.00 (130). "There are small regions with further coverage on each detector that provide some spectral overlap between bands." These numbers differ slightly from IRSA's (see `source-discrepancies.md`).
- "Each object will actually be observed at a unique set of wavelengths, and will typically have more than 102 wavelength observations in each survey."

**Survey and exposures**
- Exposures are **116.9 s** long while pointing is stable. An *observation* is typically **1 to 4 exposures**, each exposure producing 6 spectral images (one per detector). Exposures in a set are separated by small slews of **11.8 arcmin** (matched to the distance between spectral channels); large slews up to 70°.
- Surveys 3 and 4 are shifted by half a spectral channel relative to Surveys 1 and 2 so the full mission Nyquist-samples the spectra.
- Images taken in the South Atlantic Anomaly are still taken and telemetered. **1-3% of images** are flagged on average for potential re-observation for data-quality reasons.
- Two ~100 square degree **deep fields** near the north and south ecliptic poles.

**In-flight performance**
- Measured pointing stability **0.15 arcsec rms**; with the same settle time this "produces only a small, sub-percent broadening of the optical PSF in a 116.9 s integration". The measured jitter is low enough that the PSF is not modelled separately from it.
- After the instrument was decontaminated (heated to drive off water), observations of the diffuse zodiacal sky showed no sign of the characteristic water-ice absorption feature at 2.9-3.5 µm at the 1% level, assuming the pre-flight laboratory calibration.

**Data releases and access (Sect. 4.6, Tables 4 and 5)**
- Quick Release calibrated spectral images: **within two months of acquisition**, updated weekly at IRSA. Year 1 / Year 2 reprocessed releases follow; a High Reliability Source Catalog is planned.
- The Level 2 files remove reference pixels; they carry the zodiacal-light model (not subtracted), PSF, and a binary lookup table with central wavelengths and bandwidths (the `WCS-WAVE` extension).
- Table 4 of the paper gives the schedule of each data product (the Quick Release row is the "within two months" one above). IRSA hosts the SPHEREx-specific tools (Spectrophotometry, cutouts, mosaics, source discovery); Table 5 lists them with planned availability. Use the IRSA mission page (`irsa-mission-page.md`) for current availability.

## What this paper does *not* tell you
- File format details, flag bit definitions, header keywords or exact release/pipeline versions: use the Explanatory Supplement extracts (`explanatory-supplement-extracts.md`) and the User Guide pages.
