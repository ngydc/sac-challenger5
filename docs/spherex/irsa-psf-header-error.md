> **Source page:** https://irsa.ipac.caltech.edu/data/SPHEREx/docs/psfhdrerr.html
> **Fetched:** 2026-11-14
> **Why this file exists:** not on your original list, but it is the official "known issue" notice that the User Guide and the QR/DR1 pages link to.
> **Conversion note:** HTML page transcribed; the two 4x4 example grids are reproduced as tables (row 1 = top row of the page's grid).

# SPHEREx Quick Release Spectral Images PSF Extension Header Error

## Summary of Affected Data and Impact

The original SPHEREx QR1 and QR2 data products contained an error in the PSF header. This issue affected the stand-alone PSF calibration product, the PSF extension in individual spectral images, and results produced by the SPHEREx Spectrophotometry Tool.

The impact varies with source location and the variation of the PSF across the detector. The largest discrepancies occur in two of the detector corners and can lead to photometric errors of up to ±5% relative to results obtained with the correct PSF.

## Correction and Updated Data Products

On March 31, 2026, the affected QR2 data products and the Spectrophotometry Tool were updated to correct this issue. Corrected spectral image files processed with pipeline versions 6.4 through 6.5.5 can be identified by header `VERSION` keywords that include the suffix `+psffix1`. Files processed with pipeline version 6.5.6 and later were not affected.

Updated versions of the stand-alone PSF calibration products are also available at IRSA. However, the calibration reference string in the spectral image FITS headers has not been updated.

The Python notebook "Understanding and Extracting the PSF Extension in a SPHEREx Cutout" (https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/) has been updated to:

- Check the pipeline version to determine if the PSF header needs to be updated.
- Provide a function to update the header.

More information about this issue and its resolution can be found in the SPHEREx Explanatory Supplement (the page links `SPHEREx_Expsupp_QR.pdf`; the current document is https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf).

(The Explanatory Supplement v2.1 also states: "this issue does not apply to QR3 or DR1 calibrated images.")

## Description of the Original Issue

The SPHEREx PSF is represented as a cube, with each plane representing the PSF for a different zone. The zones correspond to an 11×11 grid across the detector. The PSF cube planes are stored in order of increasing x-index across the grid, but the header incorrectly indicates increasing y-index. As a result, software that relies on the header information to select a PSF for a given location on the detector may retrieve the wrong PSF cube plane. The magnitude of this error depends both on the source location and the variation of the PSF across the detector. The error is largest in two of the corners and can result in a photometry error of ±5% as compared to using the correct PSF.

The issue is illustrated with two small 4x4 grids (16 zones). The number in each cell is the cube plane (i_plane) corresponding to that zone. The actual SPHEREx PSF cubes are computed for an 11x11 grid (121 zones).

**Actual PSF cube (correct):**

| | | | |
|---|---|---|---|
| 13 | 14 | 15 | 16 |
| 9 | 10 | 11 | 12 |
| 5 | 6 | 7 | 8 |
| 1 | 2 | 3 | 4 |

In the actual PSF cube, the FITS plane number (1 to 121) corresponding to a source in the zone at **zero-indexed** grid coordinates (x, y) is

```
i_plane = y × n_cols + x + 1
```

where n_cols is the number of columns in the grid. The origin of the grid coordinates (x, y) = (0, 0) is in the bottom left corner of each detector, such that the (0, 0) zone contains the FITS origin pixel (1, 1).

**What the incorrect header implied:**

| | | | |
|---|---|---|---|
| 4 | 8 | 12 | 16 |
| 3 | 7 | 11 | 15 |
| 2 | 6 | 10 | 14 |
| 1 | 5 | 9 | 13 |

The incorrect PSF headers indicate that

```
i_plane = x × n_cols + y + 1
```
