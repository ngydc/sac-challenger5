> **Source page:** https://irsa.ipac.caltech.edu/Missions/spherex.html
> **Fetched:** 2026-11-14
> **Conversion note:** the page is HTML. This file is a faithful transcription of its tables and link lists; relative links were turned into full `https://irsa.ipac.caltech.edu/...` URLs.

# SPHEREx: An All-Sky Spectral Survey (IRSA mission page)

Entry points shown at the top of the page: [SPHEREx Data Explorer](https://irsa.ipac.caltech.edu/applications/spherex) and [Documentation](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html) (the DR1 overview).

## Mission Characteristics

| Item | Value |
|---|---|
| Lifetime | 2025 - 2027 (planned) |
| Area coverage (planned) | 100% of sky |
| Instruments | Wide Field Linear Variable Filter (LVF) Imaging Spectrograph |
| Funding agency | NASA |
| Contributing institutions | JPL, Caltech, RIT, Harvard/CFA, Arizona State, University of Arizona, Ohio State University, KASI, UC Irvine, Johns Hopkins, ASIAA |

**Wavelength coverage and resolving power R (as listed on this page):**

| Wavelength (µm) | R |
|---|---|
| 0.75 - 1.1 | 39 |
| 1.1 - 1.6 | 41 |
| 1.6 - 2.4 | 41 |
| 2.4 - 3.8 | 35 |
| 3.8 - 4.4 | 112 |
| 4.4 - 5.0 | 128 |

(These are rounded; the User Guide gives slightly different band edges. See `source-discrepancies.md`.)

## Acknowledgement

Please include the following acknowledgement in any published material that makes use of SPHEREx data products:

> "This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration."

No DOI is given on this page. DOIs are on the release overview pages (see `irsa-quick-release-overview.md` and `irsa-dr1-overview.md`).

## Canonical Papers

| Topic | Paper | Link |
|---|---|---|
| Mission | Bock et al. (2026) | https://ui.adsabs.harvard.edu/abs/2026ApJ...999..139B/abstract |
| Pipeline | Akeson et al. (2026) | https://ui.adsabs.harvard.edu/abs/2026ApJS..285...67A/abstract |
| Sky Simulator | Crill et al. (2025) | https://ui.adsabs.harvard.edu/abs/2025ApJS..281...10C/abstract |
| Instrument & Calibration | Korngut et al. (2026) | https://ui.adsabs.harvard.edu/abs/2026arXiv260329835K/abstract |

(The arXiv preprints of the Bock and Akeson papers were posted in Nov 2025, which is why they are also called "2025" papers. See `paper-bock-2025-mission.md` and `paper-akeson-2025-pipeline.md`.)

## SPHEREx Releases (timeline on this page)

- **July 2025:** [First Quick Release products available at IRSA](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html)
- **October 2025:** [First reprocessed Quick Release products (QR2) available at IRSA](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html)
- **April 10, 2026:** [QR2 headers updated to correct PSF extension header error](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/psfhdrerr.html) (see documentation for details)
- **September 2026:** [First Quick Release 3 (QR3) products available at IRSA](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html)
- **November 2026:** [Data Release 1 (DR1) products available at IRSA](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html)

## IRSA Services - SPHEREx Releases

| Service | Description |
|---|---|
| [SPHEREx Data Release 1](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html) | Access DR1 data |
| [SPHEREx Quick Releases](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html) | Access QR2 and QR3 data |
| [SPHEREx Target List of Ice Sources (SPLICES)](https://irsa.ipac.caltech.edu/data/SPHEREx/SPLICES/) | Access SPLICES catalog |
| [Comet 3I/ATLAS](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/index.html) | Access SPHEREx Spectral Images of Comet 3I/ATLAS |
| [Cloud Data Access](https://irsa.ipac.caltech.edu/cloud_access/#spherex) | Access SPHEREx data available on AWS S3 cloud storage |
| [Moving Object Search Tool (MOST)](https://irsa.ipac.caltech.edu/applications/MOST) | Determine the orbit for a given solar system object, then find SPHEREx images that covered the object's predicted positions at their observation epochs |

## SPHEREx Science Tools

| Tool | Description |
|---|---|
| [Spectrophotometry Tool](https://irsa.ipac.caltech.edu/applications/spherex/tool-spectrophotometry) | Extract spectra from SPHEREx Spectral Images using forced photometry. Usage docs: https://irsa.ipac.caltech.edu/onlinehelp/spherex/#sp |
| [Mosaic Tool](https://irsa.ipac.caltech.edu/applications/spherex/tool-mosaic) | Create custom multiwavelength mosaics from SPHEREx Spectral Images |
| [Cutout Tool](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html) | Extract spatial subsets from SPHEREx Spectral Image Multi-Extension FITS files |
| [Source Discovery Tool](https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo/) | Identify and characterize significant detected sources within a user-defined region using SPHEREx data alone, without requiring positional priors |

## IRSA Documentation - SPHEREx Releases

| Document | Description |
|---|---|
| [Documentation](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf) | SPHEREx Explanatory Supplement |
| [SPHEREx Archive User Guide](https://irsa.ipac.caltech.edu/spherex-archive-documentation/) | SPHEREx Archive User Guide |
| [Program Interfaces](https://irsa.ipac.caltech.edu/voapi.html) | Information on program-friendly data services |
| [Spectral Calibrations](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/spherex_spectral_calibrations.html) | SPHEREx Spectral Channel Maps and Response Functions |

## Other Resources

- [SPHEREx website](http://spherex.caltech.edu/)
- Python notebooks: [Introduction](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/) · [Cutouts](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/) · [PSF](https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/) · [Source Discovery Tool](https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo/) · [Mosaic Cubes](https://caltech-ipac.github.io/irsa-tutorials/spherex-mosaic/) · [HiPS Cubes](https://caltech-ipac.github.io/irsa-tutorials/spherex-hipscube/)
