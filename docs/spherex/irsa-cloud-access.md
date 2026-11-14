> **Source page:** https://irsa.ipac.caltech.edu/cloud_access/ (SPHEREx anchor: `#spherex`)
> **Fetched:** 2026-11-14
> **Why this file exists:** not on your original list. The User Guide says "see our instructions for accessing on-cloud SPHEREx data" and points here; this is the only page that gives the bucket name, region and prefixes.
> **What was kept/omitted:** the general S3 instructions and the SPHEREx section are kept. The page also covers Euclid and WISE buckets; those are omitted.

# Cloud Data Access (AWS S3): SPHEREx

IRSA datasets are available on Amazon Web Services (AWS) S3 cloud storage. The files are hosted through the AWS Open Data Sponsorship Program, allowing them to be downloaded or accessed directly **without credentials or egress charges**.

## Key terms

- **Bucket:** container holding objects.
- **Object:** analogous to a file (called "file" below).
- **S3 prefix:** path to a directory, relative to the bucket.
- **S3 key:** path to a file, relative to the bucket.

## Ways to access the buckets

- **Python:** see IRSA's Notebook Tutorials (https://irsa.ipac.caltech.edu/docs/notebooks/). The User Guide names `IRSA Cloud Access Introduction` and the `SPHEREx Source Discovery Tool` notebooks as examples of using the `cloud_access` column from SIA2 (see `user-guide-data-access.md`).
- **Command line:** AWS CLI (https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-welcome.html). Basic example:

  ```bash
  aws s3 ls --no-sign-request "s3://${bucket_name}/${prefix}/"
  ```
- **Bulk downloads:** download scripts are provided in most buckets.

> **Note:** The data are freely available and no special permissions or credentials are required. However, most tools will look for credentials by default and raise an error when none are found. To avoid this, make an **anonymous connection**. Typically this is done by including a parameter such as `--no-sign-request` or `anonymous=True`. Consult the tool's documentation for details.

## SPHEREx

For descriptions of the releases, data products and access methods, see the SPHEREx Archive User Guide. **To find a specific product in the bucket, prepend the S3 prefix listed below to the directory names described under "Browsable Directories"** (in `user-guide-data-access.md`).

- **Bucket:** `nasa-irsa-spherex`
- **Region:** `us-east-1`
- Browse: https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/index.html

| Release | AWS Open Data registry page | Content | S3 prefix |
|---|---|---|---|
| Data Release 1 (DR1) | https://registry.opendata.aws/spherex-dr1/ (page says "pending publish by AWS") | Spectral Images, calibration, and other products | `dr1` |
| Quick Release 3 (QR3) | https://registry.opendata.aws/spherex-qr3/ (page says "pending publish by AWS") | Spectral Images, calibration, and other products | `qr3` |
| Quick Release 2 (QR2) | https://registry.opendata.aws/spherex-qr/ | Spectral Images, calibration, and other products | `qr2` |

Example of how the guide's directory layout maps to a key: the Spectral Image directory pattern is `level2/[Planning Period]/l2b-v[Version]-[Processing Date]/[Detector]/`, so a QR3 file would be under `qr3/level2/...`. A real example from the PSF notebook (a calibration file on the same bucket): `https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/qr3/epsf/cal-epsf-v1-2026-191/1/epsf_D1_spx_cal-epsf-v1-2026-191.fits`.

**Remember (from the User Guide):** cutouts are available only for the on-premises copy, not from S3. SIA2 results include a `cloud_access` column with cloud-hosted access information.
