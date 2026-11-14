> **Source pages (two):**
> 1. SPHEREx Cutout Capabilities: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html
> 2. IRSA Image Server Cutouts (generic parameter reference): https://irsa.ipac.caltech.edu/ibe/cutouts.html
> **Fetched:** 2026-11-14
> **Why this file exists:** not on your original list. The User Guide says the `center`/`size` parameters are "described in more detail at" page 2, so the parameter rules live here, not in the guide.
> **What was kept/omitted:** page 2 also has worked examples for Euclid, 2MASS and WISE. Those are left out; everything about the syntax, defaults, clipping and SPHEREx behaviour is kept. Relative links were turned into full URLs.

# SPHEREx cutouts via IRSA

## Part 1: SPHEREx Cutout Capabilities

The SPHEREx Cutout Service extracts spatial subsets from the large SPHEREx Spectral Image Multi-Extension FITS (MEF) files. These cutouts preserve the structure and metadata of the original files while providing smaller, more manageable datasets. The primary products are the Spectral Image MEFs, which can be several hundred megabytes in size. Because these files contain multiple HDUs with differing formats, WCSs, and cutout constraints, IRSA provides SPHEREx-specific cutout functionality designed to handle all extensions and maintain spatial and spectral integrity.

Cutouts are available **only for the on-premises copy** held at IPAC (see `user-guide-data-access.md`).

Three ways to get cutouts:

1. **SPHEREx Data Explorer** (https://irsa.ipac.caltech.edu/applications/spherex): open the *Spectral Image Search* tab; in the *Results* tab use the scissors icon above the interactive display to specify a cutout size; select the images and click *Generate Download Script*; in *Download Options* choose *cutouts* to download a script that retrieves the cutout files.
2. **Direct URL**: append position and size parameters to an on-premises image URL (from an API query or the browsable directories):

   ```bash
   curl -o cutout.fits "https://irsa.ipac.caltech.edu/ibe/data/spherex/qr/level2/2025W19_2B/l2b-v11-2025-163/3/level2_2025W19_2B_0073_2D3_spx_l2b-v11-2025-163.fits?center=156.09328159,-41.64466331&size=0.1"
   ```
   (This example path uses the old `qr/` directory name from the QR1 era; current releases live under `dr1/`, `qr3/`, `qr2/`. See `user-guide-data-access.md`.)
3. **Python**: see `tutorial-spectral-image-cutouts.md` and `tutorial-psf-in-cutouts.md`.

## Part 2: IRSA Image Server (IBE) cutouts: syntax and behaviour

The IRSA Image Back End (IBE) generates cutouts of FITS images in response to URLs built by appending a query string to the access URL of a FITS image. The SPHEREx data tree is at https://irsa.ipac.caltech.edu/ibe/data/spherex (separate from the general https://irsa.ipac.caltech.edu/ibe/data/). Only image URLs containing `/ibe/data/` can be cut out through this service.

astropy's `Cutout2D` can also extract a cutout from a remotely hosted FITS file without downloading it all (https://docs.astropy.org/en/stable/io/fits/usage/cloud.html#using-cutout2d-with-cloud-hosted-fits-files). Whether that works properly for SPHEREx's multi-extension layout is **not covered** by these pages.

### Basic form

```
<imageURL>?center=<value>&size=<value>[&gzip=<true|false>]
```

The query string starts with `?`; parameters are separated by `&`; order does not matter. `center` and `size` are required.

### `center=x,y[units]`

- Comma-separated pair plus optional units.
- Units `px`, `pix` or `pixels` → x,y are **pixel** coordinates of the parent image.
- Angular units (`rad`, `deg`, ...) → x,y are **J2000 RA and Dec**.
- **No units → degrees.**
- Declinations outside [-90, 90] are illegal; right ascensions are range-reduced.

Examples: `center=10,10deg` · `center=10,10` · `center=3.141,1.56rad` · `center=300.5,120px`

### `size=x[,y][units]`

- One or two comma-separated values plus optional units: pixels (`px`, `pix`, `pixels`) or angular (`arcsec`, `arcmin`, `deg`, `rad`). **Default is degrees.**
- First value = full width along the first image axis (NAXIS1); second = full height along NAXIS2. One value is used for both. Negative sizes are illegal.

Examples: `size=0.1` · `size=200px` · `size=100,200px` · `size=3arcmin` · `size=30,45arcsec`

### `gzip=flag`

- Default (parameter omitted): cutouts are gzipped. Explicit on: `1`, `on`, `t[rue]`, `y[es]`. Off: `0`, `off`, `f[alse]`, `n[o]`.
- **Exception for SPHEREx: "SPHEREx cutouts will not be gzipped."**

Unit parsing is forgiving (`radians`, `asec`, `"`, `arcminutes`, `'` all work). Malformed units or illegal sizes/coordinates give **HTTP 400 Bad Request**.

### SPHEREx example in pixels

A 100 x 100 pixel cutout from a SPHEREx image (the page's example uses a QR2 path):

```
<root>/data/spherex/qr2/level2/2025W20_1C/l2b-v20-2025-247/1/level2_2025W20_1C_0002_2D1_spx_l2b-v20-2025-247.fits?center=570,900pix&size=100pix
```

What the page says about SPHEREx cutouts:

- SPHEREx spectral images are MEFs (image, variance, zodiacal light background, etc.; see Section 2.2 of the Explanatory Supplement). **All extensions are cut out in the same way**, so the cutout is also a MEF with the same number of extensions as the parent.
- **The axes of cutouts are always aligned with the axes of the parent image**, which may not match the cardinal directions. A SPHEREx parent image is a single exposure, so its orientation depends on the spacecraft orientation at the time and is **not** north-up/east-left. This is true even if the cutout is specified in RA/Dec and an angular size.
- SPHEREx images carry distortion corrections in their WCS headers, so **pixel scale and orientation vary across the image**. These corrections are often not supported by FITS viewers.

### Clipping at image edges (shown with a 2MASS example on the page; the rule is generic)

- If the requested cutout extends beyond the parent image, the service still returns a cutout **clipped** to the part that overlaps the parent.
- The cutout centre does not need to be inside the parent image; there only needs to be non-zero overlap. An extreme example returns a single column of NaN pixels.
- If the cutout is completely outside the parent image, the service returns **HTTP 500 Internal Server Error**.

### Submitting requests

- Paste the URL in a browser (downloads the file), or use command-line tools. Always quote the URL.
- `wget -O filename "URL"` (or `--output-document=filename`). `wget --content-disposition "URL"` keeps the suggested name (the parent image's name).
- `curl -o filename "URL"` (or `--output`). Without `-o`, curl writes to stdout and "will likely fail". `curl -O -J "URL"` keeps the suggested name.
- Make sure the filename extension matches the format returned (`.fits` for SPHEREx, since it is not gzipped).

### Getting image URLs

- Copy the access URL from the browsable directory tree, or get it from the SIA2 service (`access_url` column; see `user-guide-data-access.md`).
- Help: https://irsa.ipac.caltech.edu/docs/help_desk.html
