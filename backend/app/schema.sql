-- Cache tables for the backend. Applied by the backend at startup (app/db.py); every statement is
-- idempotent, so it is safe on an existing database. Everything here can be rebuilt from IRSA, so
-- dropping these tables only costs download time.

-- The SPHEREx SIA2 collections IRSA listed last time (e.g. spherex_dr1, spherex_qr3).
-- Not hard-coded: refreshed hourly; the stored list is used when IRSA is down.
CREATE TABLE IF NOT EXISTS irsa_collection (
    name       text PRIMARY KEY,
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- One finished search for a position (+ optional motion). The field of view is NOT part of it: the search
-- does not depend on it, and each request filters the images for its own fov (service.Coverage.view).
-- target_key is TargetSpec.coverage_key, a hash of exactly ra, dec, pmra, pmdec, pm_epoch.
-- (Rows written before 2026-11-14 used a key that included the fov; they are simply never read again.)
CREATE TABLE IF NOT EXISTS coverage (
    target_key    text PRIMARY KEY,
    ra            double precision NOT NULL,   -- deg
    dec           double precision NOT NULL,   -- deg
    fov_deg       double precision,            -- NULL: coverage for every fov (older rows: the fov searched)
    pmra          double precision,            -- mas/yr incl. cos(dec), NULL = no motion given
    pmdec         double precision,            -- mas/yr
    pm_epoch      double precision,            -- decimal year
    collections   text[] NOT NULL,             -- collections that were searched
    failed_locate integer NOT NULL DEFAULT 0,  -- images that could not be located
    data_as_of    timestamptz NOT NULL         -- when the search results came from IRSA
);
ALTER TABLE coverage ALTER COLUMN fov_deg DROP NOT NULL;

-- The images found by that search. x/y/wavelength are NULL when the image could not be located;
-- wavelength is NaN when the target falls off the detector.
CREATE TABLE IF NOT EXISTS coverage_image (
    target_key      text NOT NULL REFERENCES coverage (target_key) ON DELETE CASCADE,
    frame_id        text NOT NULL,             -- "<obs_id>-<detector>"
    obs_id          text NOT NULL,
    detector        text NOT NULL,             -- "D1".."D6"
    collection      text NOT NULL,
    t_mid_mjd       double precision NOT NULL,
    access_url      text NOT NULL,
    s_region        text NOT NULL,
    edge_margin_deg double precision,          -- distance of the position from the image edge, deg
    x               double precision,          -- 0-based detector pixel of the target
    y               double precision,
    wavelength_um   double precision,          -- CWAVE at that pixel
    bandwidth_um    double precision,          -- CBAND at that pixel
    cloud_url       text NOT NULL DEFAULT '',  -- the same file on S3 (SIA2 cloud_access), '' = unknown
    PRIMARY KEY (target_key, frame_id)
);
ALTER TABLE coverage_image ADD COLUMN IF NOT EXISTS cloud_url text NOT NULL DEFAULT '';

-- Downloaded cutouts (IMAGE, FLAGS, ZODI, WCS-WAVE; ~120 KB each) and permanent/recent failures.
-- cache_key is the SHA-1 of the IRSA cutout URL; the URL contains the file version, so a reprocessed
-- image gets a new key and a stored cutout never goes stale. Cutouts made from byte ranges
-- (app/cutout.py) are identical to IRSA's and use the same key.
CREATE TABLE IF NOT EXISTS cutout (
    cache_key  text PRIMARY KEY,
    url        text NOT NULL,
    status     text NOT NULL CHECK (status IN ('ready', 'outside', 'error')),
    fits       bytea,                          -- only when status = 'ready'
    message    text,                           -- error text when status = 'error'
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'ready') = (fits IS NOT NULL))
);

-- Where each part of an image file sits (byte offsets, the headers a cutout copies, the FLAGS row index):
-- app/cutout.FileLayout as compressed JSON, ~26 KB. Lets a later cutout of the same file skip four header
-- requests. file_url is the image's access_url, which contains the file version, so a layout never goes stale;
-- it is still checked against the file size on every use.
CREATE TABLE IF NOT EXISTS file_layout (
    file_url   text PRIMARY KEY,
    layout     bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Spectral WCS calibration files (CWAVE/CBAND per release and detector, ~33 MB each). Stored once per
-- distinct content: DR1 and QR3 ship byte-identical files under different S3 keys.
CREATE TABLE IF NOT EXISTS calibration_blob (
    sha256 text PRIMARY KEY,                   -- hex SHA-256 of data
    data   bytea NOT NULL
);
CREATE TABLE IF NOT EXISTS calibration_key (
    s3_key     text PRIMARY KEY,               -- contains the release and calibration version
    sha256     text NOT NULL REFERENCES calibration_blob (sha256),
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- One-time move from the old layout (one row with the data per S3 key).
DO $$
BEGIN
    IF to_regclass('calibration_file') IS NOT NULL THEN
        INSERT INTO calibration_blob (sha256, data)
            SELECT DISTINCT ON (h) h, data
            FROM (SELECT encode(sha256(data), 'hex') AS h, data FROM calibration_file) t
            ON CONFLICT DO NOTHING;
        INSERT INTO calibration_key (s3_key, sha256, fetched_at)
            SELECT s3_key, encode(sha256(data), 'hex'), fetched_at FROM calibration_file
            ON CONFLICT DO NOTHING;
        DROP TABLE calibration_file;
    END IF;
END $$;
