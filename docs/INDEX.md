# Documentation index

Local copies of the official SPHEREx documentation (in `docs/spherex/`), plus the team's own notes. **Read the relevant file before writing code that touches SPHEREx data.** All files in `docs/spherex/` were fetched on **2026-11-14**. The SPHEREx documents are living documents, so re-fetch before relying on a detail that matters.

How the files were obtained: the User Guide pages and tutorial notebooks were saved from their public source repositories (unrendered Markdown on GitHub: `Caltech-IPAC/spherex-archive-documentation` and `Caltech-IPAC/irsa-tutorials`), because the web-fetch tool only returns short summaries of rendered pages. The content is the same as the published pages. The IRSA pages were saved from their HTML. Files marked **(extra)** were not on the original request; they are pages the requested pages depend on.

## Start here (by question)

| If you need... | Read |
|---|---|
| What is in a SPHEREx file, HDU by HDU | `spherex/user-guide-data-products.md` |
| How to find and download data (SIA2, astroquery, directories, cutouts) | `spherex/user-guide-data-access.md`, then `spherex/irsa-cutout-service.md` |
| Which release is current, what QR2/QR3/DR1 mean | `spherex/user-guide-data-releases.md` |
| What a flag bit means | `spherex/explanatory-supplement-extracts.md` (Table 16) |
| Known problems with the data | `spherex/explanatory-supplement-extracts.md` (sections 6-8), `spherex/irsa-psf-header-error.md` |
| Which citation/DOI and acknowledgement to use | `spherex/irsa-dr1-overview.md`, `spherex/irsa-quick-release-overview.md` |
| Places where two sources disagree | `spherex/source-discrepancies.md` |

## Official documentation: SPHEREx Archive User Guide (Caltech/IPAC)

- **`docs/spherex/user-guide-overview.md`**
  Source: https://caltech-ipac.github.io/spherex-archive-documentation/ · Fetched 2026-11-14
  Purpose and scope of the guide, a three-line mission overview, links. Read once for orientation.

- **`docs/spherex/user-guide-data-releases.md`**
  Source: https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-releases · Fetched 2026-11-14
  What DR1, QR3, QR2 and QR1 contain and which to use ("DR1 + QR3 supersede QR2"). Read before choosing which collection or release to query.

- **`docs/spherex/user-guide-data-products.md`**
  Source: https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products · Fetched 2026-11-14
  The six HDUs of a spectral image, filename conventions, how cutouts differ, the All-Sky Cube, and every calibration product with its filename pattern. Read before opening or interpreting any FITS file.

- **`docs/spherex/user-guide-data-access.md`**
  Source: https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access · Fetched 2026-11-14
  Browsable directory layout, the SIA2 collections and example queries, cutouts by URL, astroquery/pyvo, the Data Explorer. Read before writing any download or search code.

## Official documentation: IRSA pages

- **`docs/spherex/irsa-mission-page.md`**
  Source: https://irsa.ipac.caltech.edu/Missions/spherex.html · Fetched 2026-11-14
  Mission characteristics, the acknowledgement text, canonical papers, release timeline, and the list of IRSA services and tools. Read to find the right entry point or tool.

- **`docs/spherex/irsa-quick-release-overview.md`**
  Source: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html · Fetched 2026-11-14
  QR1-QR3 timeline, which releases are searchable vs download-only, and the QR1/QR2/QR3 DOIs. Read when you need to cite or explain a Quick Release.

- **`docs/spherex/irsa-dr1-overview.md`** (extra)
  Source: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html · Fetched 2026-11-14
  DR1 description and the **DR1 DOIs** (spectral images and All-Sky Cube). Read when citing DR1.

- **`docs/spherex/irsa-psf-header-error.md`** (extra)
  Source: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/psfhdrerr.html · Fetched 2026-11-14
  Official notice of the QR1/QR2 PSF header error (up to ±5% photometric error), how to spot corrected files (`+psffix1`). Read before using any PSF from QR2 files.

- **`docs/spherex/irsa-cutout-service.md`** (extra)
  Sources: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html and https://irsa.ipac.caltech.edu/ibe/cutouts.html · Fetched 2026-11-14
  The `center`/`size`/`gzip` parameter rules, defaults, clipping at edges, and SPHEREx-specific behaviour (not gzipped, axes follow the parent image). Read before building cutout URLs.

- **`docs/spherex/irsa-cloud-access.md`** (extra)
  Source: https://irsa.ipac.caltech.edu/cloud_access/ · Fetched 2026-11-14
  AWS S3 bucket `nasa-irsa-spherex`, region, release prefixes, anonymous access. Read before using the cloud copy.

## Official documentation: Explanatory Supplement (partial)

- **`docs/spherex/explanatory-supplement-extracts.md`**
  Source: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf (v2.1, 2026-11-10) · Fetched 2026-11-14
  Extracts only: survey definitions, release/pipeline versions, file format, **the full pixel-flag table (Table 16)**, known anomalies and limitations. Read for anything about flags, image artifacts, or which pipeline version a release used.

## Tutorial notebooks (Caltech/IPAC IRSA), code and text only, no outputs

- **`docs/spherex/tutorial-intro-spectral-images.md`**
  Source: https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/ · Fetched 2026-11-14 (notebook updated 5 March 2026)
  SIA2 search with astroquery, opening a file with astropy, each HDU, the spatial and spectral WCS, listing flags from the header. Read before writing code that opens a spectral image or computes wavelength per pixel.

- **`docs/spherex/tutorial-spectral-image-cutouts.md`**
  Source: https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/ · Fetched 2026-11-14 (notebook updated 5 March 2026)
  TAP query for cutout URLs, parallel download, wavelength at the target, combining cutouts into one MEF. Read before writing any cutout-fetching code.

- **`docs/spherex/tutorial-psf-in-cutouts.md`**
  Source: https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/ · Fetched 2026-11-14 (notebook updated 17 September 2026)
  Mapping cutout pixels to parent-image pixels (`CRPIX1A`), the ePSF table, version rules (`VERSION` < 7.0 vs >= 7.0), picking the right zone. Read before doing any photometry or PSF work.

## Papers (summaries only, not full text)

- **`docs/spherex/paper-akeson-2025-pipeline.md`**
  Source: https://arxiv.org/abs/2511.15823 (ApJS; IRSA cites as Akeson et al. 2026) · Fetched 2026-11-14
  Title, authors, links, and key points on how the pipeline makes the images (astrometry quality `FINAST`, zodi model, quality cuts, wavelength WCS). Predates the R7 pipeline in places.

- **`docs/spherex/paper-bock-2025-mission.md`**
  Source: https://arxiv.org/abs/2511.02985 (ApJ; IRSA cites as Bock et al. 2026) · Fetched 2026-11-14
  Title, authors, links, and key points on the instrument, survey design, depth and early in-flight performance.

## Our own analysis

- **`docs/spherex/source-discrepancies.md`**
  Source: derived from the files above (no external source) · Written 2026-11-14
  A table of places where the official sources disagree (band edges, file sizes, dates, keyword names, PSF layout). Read before hard-coding any number from the docs.

## Team notes (not official sources)

These existed before the files above were added. They contain the team's own measurements and interpretations ("tested", "inferred"), so treat them as secondary and check against the official files when they differ.

- **`docs/PROJECT_OVERVIEW.md`**: the challenge, goals, test targets, risks, MVP checklist.
- **`docs/RESOURCES.md`**: team notes on the SPHEREx data format and IRSA access, with the team's test timings.
- **`docs/DATA_COVERAGE.md`**: measured coverage of the five test targets (2026-11-14): every image's date, detector and wavelength at the target. Answers "do we get every wavelength every 6 months?" and documents the header + `CWAVE` method and the Barnard's Star pipeline test.

## Not fetched, or only partly fetched

| Item | URL | Status and reason |
|---|---|---|
| Explanatory Supplement, full text | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf | **Partly fetched.** The PDF (84 pages, 30 MB) was downloaded and read; only the sections you need are saved (see `explanatory-supplement-extracts.md`). Calibration, Level 3 photometry, all-sky cube construction, astrometry accuracy and zodi-model sections are not saved. |
| Supplement Appendix A, Table A.35 (example header, pages 73-76) | same PDF | **Not saved.** The PDF text extraction scrambles which description belongs to which keyword, and a wrong mapping is worse than none. Read it in the PDF, or from a real file's header. |
| Supplement Table 4 (pipeline versions per release) | same PDF, page 24 | **Not saved.** Same scrambling problem. The facts that are clear in the surrounding text are in the extracts file. |
| Figures and images (e.g. the release timeline PNG) | `_static/spherexreleases.png` in the guide repository | **Not saved.** Only the figure's caption and alt text were kept. |
| Notebook outputs | the rendered notebook pages | **Not saved, by request.** Only the unexecuted Markdown and code were kept. |
| Both papers in full | https://arxiv.org/pdf/2511.15823, https://arxiv.org/pdf/2511.02985 | **Not saved, by request** (summaries only). Parts of both were not read in detail; each summary says which. |
| SIA2 documentation | https://irsa.ipac.caltech.edu/ibe/sia.html | Linked from the guide; **not fetched** (not requested). Needed if you must use SIA2 parameters beyond `POS` and `COLLECTION`. |
| Spectral Calibrations page | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/spherex_spectral_calibrations.html | Linked from the mission page; **not fetched** (not requested). Spectral channel maps and response functions. |
| List of contaminated images | https://spherex.caltech.edu/page/anomalyimages | Linked from the Supplement; **not fetched** (not requested; on a different site, spherex.caltech.edu). Lists images with a large contaminated area. |
| Other tutorial notebooks | https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo/ , `.../spherex-mosaic/`, `.../spherex-hipscube/` | Linked; **not fetched** (you asked for three notebooks). |
| Other IRSA SPHEREx tools and pages | Spectrophotometry Tool docs, Mosaic Tool, MOST, SPLICES, Comet 3I/ATLAS (links in `irsa-mission-page.md`) | **Not fetched** (not requested). |

Every page you listed was fetched. Nothing failed to load.
