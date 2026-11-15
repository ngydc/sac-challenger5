"""Postgres-backed cache: IRSA collection list, search results (coverage), cutouts, calibration files.

The schema is in app/schema.sql and is applied on first use (idempotent). The connection string comes
from DATABASE_URL (set by docker-compose.yml); without it, the compose database on localhost is used,
so `docker compose up db` is enough for running the backend outside Docker.

Nothing here knows about SPHEREx: callers pass plain values. Times are Unix seconds (float).
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("spherex.db")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sac:sac_password@localhost:5432/sac")
SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

IMAGE_COLUMNS = ("frame_id", "obs_id", "detector", "collection", "t_mid_mjd", "access_url", "s_region",
                 "edge_margin_deg", "x", "y", "wavelength_um", "bandwidth_um", "cloud_url")


class Store:
    """Thread-safe (connection pool). The pool opens on first use, so importing the app needs no database."""

    def __init__(self, url: str = DATABASE_URL, max_size: int = 10):
        self._url, self._max_size = url, max_size
        self._pool: ConnectionPool | None = None
        self._lock = threading.Lock()

    def _connection(self):
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    pool = ConnectionPool(self._url, min_size=1, max_size=self._max_size, open=True,
                                          kwargs={"row_factory": dict_row}, timeout=10)
                    try:
                        with pool.connection() as conn:
                            conn.execute(SCHEMA_SQL)
                    except Exception:
                        pool.close()  # database down: try again on the next call
                        raise
                    self._pool = pool
        return self._pool.connection()

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    # -- IRSA collection list --------------------------------------------------------------
    def collections(self) -> tuple[list[str], float] | None:
        """(names, fetched_at) of the last stored list, or None if never stored."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT name, extract(epoch FROM fetched_at) AS t FROM irsa_collection ORDER BY name").fetchall()
        return ([r["name"] for r in rows], min(float(r["t"]) for r in rows)) if rows else None

    def save_collections(self, names: list[str]) -> None:
        with self._connection() as conn, conn.transaction():
            conn.execute("DELETE FROM irsa_collection")
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO irsa_collection (name) VALUES (%s)", [(n,) for n in names])

    # -- coverage --------------------------------------------------------------------------
    def save_coverage(self, key: str, target: dict, collections: list[str], failed_locate: int,
                      data_as_of: float, images: list[dict]) -> None:
        """Replace the stored coverage of `key`. `target` has ra, dec, fov_deg (may be None), pmra, pmdec,
        pm_epoch; each image dict has IMAGE_COLUMNS."""
        with self._connection() as conn, conn.transaction():
            conn.execute(
                """INSERT INTO coverage (target_key, ra, dec, fov_deg, pmra, pmdec, pm_epoch, collections,
                                         failed_locate, data_as_of)
                   VALUES (%(key)s, %(ra)s, %(dec)s, %(fov_deg)s, %(pmra)s, %(pmdec)s, %(pm_epoch)s, %(cols)s,
                           %(failed)s, to_timestamp(%(as_of)s))
                   ON CONFLICT (target_key) DO UPDATE SET collections = EXCLUDED.collections,
                       failed_locate = EXCLUDED.failed_locate, data_as_of = EXCLUDED.data_as_of""",
                {**target, "key": key, "cols": collections, "failed": failed_locate, "as_of": data_as_of})
            conn.execute("DELETE FROM coverage_image WHERE target_key = %s", (key,))
            cols = ", ".join(IMAGE_COLUMNS)
            vals = ", ".join(f"%({c})s" for c in IMAGE_COLUMNS)
            with conn.cursor() as cur:
                cur.executemany(f"INSERT INTO coverage_image (target_key, {cols}) VALUES (%(target_key)s, {vals})",
                                [{**img, "target_key": key} for img in images])

    def load_coverage(self, key: str) -> dict | None:
        """{"collections", "failed_locate", "data_as_of", "images": [dict with IMAGE_COLUMNS]} or None."""
        with self._connection() as conn:
            row = conn.execute(
                """SELECT collections, failed_locate, extract(epoch FROM data_as_of) AS data_as_of
                   FROM coverage WHERE target_key = %s""", (key,)).fetchone()
            if row is None:
                return None
            images = conn.execute(
                f"SELECT {', '.join(IMAGE_COLUMNS)} FROM coverage_image WHERE target_key = %s ORDER BY t_mid_mjd",
                (key,)).fetchall()
        return {"collections": list(row["collections"]), "failed_locate": row["failed_locate"],
                "data_as_of": float(row["data_as_of"]), "images": images}

    # -- cutouts ---------------------------------------------------------------------------
    def cutout(self, key: str) -> bytes | None:
        """The stored FITS bytes, or None if not downloaded (yet)."""
        with self._connection() as conn:
            row = conn.execute("SELECT fits FROM cutout WHERE cache_key = %s AND status = 'ready'", (key,)).fetchone()
        return bytes(row["fits"]) if row else None

    def cutout_states(self, keys: list[str]) -> dict[str, tuple[str, float, str | None]]:
        """key -> (status, updated_at, message) for the keys that have a row; one query for many frames."""
        if not keys:
            return {}
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT cache_key, status, extract(epoch FROM updated_at) AS t, message
                   FROM cutout WHERE cache_key = ANY(%s)""", (keys,)).fetchall()
        return {r["cache_key"]: (r["status"], float(r["t"]), r["message"]) for r in rows}

    def put_cutout(self, key: str, url: str, data: bytes) -> None:
        self._upsert_cutout(key, url, "ready", data, None)

    def put_cutout_failure(self, key: str, url: str, status: str, message: str) -> None:
        """status 'outside' (permanent: the view is not in this image) or 'error' (retry after a cooldown).
        Never overwrites a ready cutout."""
        self._upsert_cutout(key, url, status, None, message)

    def _upsert_cutout(self, key: str, url: str, status: str, data: bytes | None, message: str | None) -> None:
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO cutout (cache_key, url, status, fits, message) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (cache_key) DO UPDATE SET url = EXCLUDED.url, status = EXCLUDED.status,
                       fits = EXCLUDED.fits, message = EXCLUDED.message, updated_at = now()
                   WHERE cutout.status <> 'ready' OR EXCLUDED.status = 'ready'""",
                (key, url, status, data, message))

    # -- file layouts (app/cutout.FileLayout, compressed) -----------------------------------
    def file_layout(self, url: str) -> bytes | None:
        with self._connection() as conn:
            row = conn.execute("SELECT layout FROM file_layout WHERE file_url = %s", (url,)).fetchone()
        return bytes(row["layout"]) if row else None

    def put_file_layout(self, url: str, data: bytes) -> None:
        """Store or replace (a layout is only re-read when the stored one no longer fits the file)."""
        with self._connection() as conn:
            conn.execute("""INSERT INTO file_layout (file_url, layout) VALUES (%s, %s)
                            ON CONFLICT (file_url) DO UPDATE SET layout = EXCLUDED.layout, created_at = now()""",
                         (url, data))

    # -- calibration files (stored once per distinct content) --------------------------------
    def calibration(self, s3_key: str) -> bytes | None:
        with self._connection() as conn:
            row = conn.execute("""SELECT b.data FROM calibration_key k JOIN calibration_blob b USING (sha256)
                                  WHERE k.s3_key = %s""", (s3_key,)).fetchone()
        return bytes(row["data"]) if row else None

    def calibration_digest(self, s3_key: str) -> str | None:
        """Hex SHA-256 of the stored file, without loading it (lets callers reuse a copy they already hold)."""
        with self._connection() as conn:
            row = conn.execute("SELECT sha256 FROM calibration_key WHERE s3_key = %s", (s3_key,)).fetchone()
        return row["sha256"] if row else None

    def put_calibration(self, s3_key: str, data: bytes) -> None:
        """Store a file under its S3 key; the first file stored for a key wins, equal contents are kept once."""
        digest = hashlib.sha256(data).hexdigest()
        with self._connection() as conn, conn.transaction():
            conn.execute("INSERT INTO calibration_blob (sha256, data) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                         (digest, data))
            conn.execute("INSERT INTO calibration_key (s3_key, sha256) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                         (s3_key, digest))


store = Store()
