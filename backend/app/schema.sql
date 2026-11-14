-- Cache tables for the backend. Applied by the backend at startup (app/db.py); every statement is
-- idempotent, so it is safe on an existing database. Everything here can be rebuilt from IRSA, so
-- dropping these tables only costs download time.

-- The SPHEREx SIA2 collections IRSA listed last time (e.g. spherex_dr1, spherex_qr3).
-- Not hard-coded: refreshed hourly; the stored list is used when IRSA is down.
CREATE TABLE IF NOT EXISTS irsa_collection (
    name       text PRIMARY KEY,
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- One finished search for a view (position + field of view + optional motion).
-- target_key is TargetSpec.key, a hash of exactly those values.
CREATE TABLE IF NOT EXISTS coverage (
    target_key    text PRIMARY KEY,
    ra            double precision NOT NULL,   -- deg
    dec           double precision NOT NULL,   -- deg
    fov_deg       double precision NOT NULL,
    pmra          double precision,            -- mas/yr incl. cos(dec), NULL = no motion given
    pmdec         double precision,            -- mas/yr
    pm_epoch      double precision,            -- decimal year
    collections   text[] NOT NULL,             -- collections that were searched
    failed_locate integer NOT NULL DEFAULT 0,  -- images whose header could not be read
    data_as_of    timestamptz NOT NULL         -- when the search results came from IRSA
);

-- The images found by that search. x/y/wavelength are NULL when the image could not be located
-- (header read failed); wavelength is NaN when the target falls off the detector.
CREATE TABLE IF NOT EXISTS coverage_image (
    target_key      text NOT NULL REFERENCES coverage (target_key) ON DELETE CASCADE,
    frame_id        text NOT NULL,             -- "<obs_id>-<detector>"
    obs_id          text NOT NULL,
    detector        text NOT NULL,             -- "D1".."D6"
    collection      text NOT NULL,
    t_mid_mjd       double precision NOT NULL,
    access_url      text NOT NULL,
    s_region        text NOT NULL,
    edge_margin_deg double precision,
    x               double precision,          -- 0-based detector pixel of the target
    y               double precision,
    wavelength_um   double precision,          -- CWAVE at that pixel
    bandwidth_um    double precision,          -- CBAND at that pixel
    PRIMARY KEY (target_key, frame_id)
);

-- Downloaded cutouts (PSF extension removed, ~120 KB each) and permanent/recent failures.
-- cache_key is the SHA-1 of the cutout URL; the URL contains the file version, so a reprocessed
-- image gets a new key and a stored cutout never goes stale.
CREATE TABLE IF NOT EXISTS cutout (
    cache_key  text PRIMARY KEY,
    url        text NOT NULL,
    status     text NOT NULL CHECK (status IN ('ready', 'outside', 'error')),
    fits       bytea,                          -- only when status = 'ready'
    message    text,                           -- error text when status = 'error'
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'ready') = (fits IS NOT NULL))
);

-- Spectral WCS calibration files (CWAVE/CBAND per release and detector, ~33 MB each), keyed by
-- their S3 object key, which contains the release and calibration version.
CREATE TABLE IF NOT EXISTS calibration_file (
    s3_key     text PRIMARY KEY,
    data       bytea NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now()
);
