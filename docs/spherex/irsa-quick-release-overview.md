> **Source page:** https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html
> **Fetched:** 2026-11-14
> **Conversion note:** the page is HTML. Text and tables are transcribed; relative links were turned into full URLs.

# SPHEREx Quick Release (QR) Overview

## Overview

SPHEREx is a NASA Astrophysics Medium Explorer mission that launched in March 2025. During its planned two-year mission, SPHEREx is obtaining spectroscopy from 0.75 to 5.0 µm across the entire sky, with deeper observations in the SPHEREx Deep Fields. IRSA releases Quick Release spectral images on a weekly basis, with additional releases of [higher-level data products](https://spherex.caltech.edu/page/data-products) planned throughout the mission and beyond.

IRSA began releasing SPHEREx spectral image data on a weekly basis in July 2025 (Quick Release 1; **QR1**). In October 2025, IRSA transitioned to releasing data processed with substantially improved calibrations (Quick Release 2; **QR2**), with reprocessed versions of all QR1 images provided. QR1 was formally retired in February 2026 and is no longer available from IRSA. In April 2026, the QR2 headers were updated to correct [PSF extension header errors](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/psfhdrerr.html). In September 2026, IRSA began releasing Quick Release 3 (**QR3**) data, which incorporate improved PSF and other calibrations for more reliable photometry. In November 2026, IRSA released [Data Release 1 (DR1)](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html), which reprocesses the QR2 data so that the DR1 and QR3 spectral images together form a uniformly processed set of spectral images. With the release of DR1, **QR2 data are no longer returned in IRSA or VO searches, but remain available for direct download through February 2027.**

### Citation (DOIs) and acknowledgement

If you use SPHEREx QR data from the IRSA archive, please cite the appropriate Digital Object Identifier:

| Release | DOI | Landing page |
|---|---|---|
| QR1 | 10.26131/IRSA629 | https://www.ipac.caltech.edu/doi/irsa/10.26131/IRSA629 |
| QR2 | 10.26131/IRSA652 | https://www.ipac.caltech.edu/doi/irsa/10.26131/IRSA652 |
| QR3 | 10.26131/IRSA662 | https://www.ipac.caltech.edu/doi/10.26131/IRSA662 |

and include the following acknowledgement:

> "This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration."

(DR1 has its own DOIs: see `irsa-dr1-overview.md`.)

## Data Set Characteristics

| Data product | Description | Data access |
|---|---|---|
| Spectral Images QR3 | SPHEREx Spectral Images, 0.75-5.0 microns | [SPHEREx Data Explorer](https://irsa.ipac.caltech.edu/applications/spherex); [IRSA Astroquery Python module](https://astroquery.readthedocs.io/en/latest/ipac/irsa/irsa.html); [Program Interface via SIA](https://irsa.ipac.caltech.edu/ibe/sia.html); [Browsable directories on-premises at IPAC](https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2); [Cloud data access](https://irsa.ipac.caltech.edu/cloud_access/#spherex) |
| Spectral Images QR2 | SPHEREx Spectral Images, 0.75-5.0 microns | [Browsable directories on-premises at IPAC](https://irsa.ipac.caltech.edu/ibe/data/spherex/); [Cloud data access](https://irsa.ipac.caltech.edu/cloud_access/#spherex) |

Note the difference: QR3 can be searched (Data Explorer, astroquery, SIA); **QR2 can only be downloaded directly** (directories, cloud).

## Documentation

| Documentation | Python notebooks |
|---|---|
| [SPHEREx Explanatory Supplement](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf) | [Introduction to SPHEREx Spectral Images](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/) |
| [SPHEREx Archive User Guide](https://caltech-ipac.github.io/spherex-archive-documentation/) | [SPHEREx Spectral Image Cutouts](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/) |
| [SPHEREx Quick Release Spectral Images PSF Extension Header Error](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/psfhdrerr.html) | [SPHEREx PSF in Spectral Image Cutouts](https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/) |
| [SPHEREx website](https://spherex.caltech.edu) | [SPHEREx Source Discovery Tool](https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo/) |
| | [SPHEREx Mosaic Cubes](https://caltech-ipac.github.io/irsa-tutorials/spherex-mosaic/) |

## Other links on the page

- DR1 overview: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html
- QR3 browsable directories: https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2
- QR2 browsable directories: https://irsa.ipac.caltech.edu/ibe/data/spherex/
- Cloud data access: https://irsa.ipac.caltech.edu/cloud_access/#spherex
