"""Copy the backend's cache between machines, so a new machine does not have to download everything from IRSA.

What is copied:
  - the Postgres cache (schema.sql): IRSA collection list, search results (coverage), cutouts, file layouts
    and calibration files
  - the deep-analysis results under backend/cache/analysis/ (pictures, resampled arrays)
into ONE archive file (.tar.gz). Nothing in it is secret: it is all public SPHEREx data and derived results.

From backend/ (database running), or inside the container (`docker compose exec backend python -m app.cache_transfer ...`):

    python -m app.cache_transfer export [cache_export.tar.gz]
    python -m app.cache_transfer import <file or http(s) URL> [--replace]

Import MERGES into what the machine already has; nothing is lost:
  - a search result (coverage) is taken when the local one is missing or older (`data_as_of`)
  - a cutout is taken when missing locally, or when the local one is only a failure record
  - everything else is taken when missing (file layouts, calibration files, collection list)
  - an analysis folder (one target) is copied when that target has no folder locally
With --replace, the cache tables are emptied and the analysis folders overwritten first, so the result is an
exact copy of the archive.

The backend can also load an archive by itself when its database is empty: set SPHEREX_SEED_URL (see seed_if_empty).
For a manual import, stop the backend first (`docker compose stop backend`) so it does not write at the same time.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

import psycopg

from . import db

log = logging.getLogger("spherex.cache_transfer")

FORMAT_VERSION = 1
DEFAULT_ANALYSIS_DIR = Path(os.environ.get("SPHEREX_CACHE_DIR", Path(__file__).resolve().parents[1] / "cache")) / "analysis"

# Parents before children (foreign keys).
TABLES = ["irsa_collection", "coverage", "coverage_image", "cutout", "file_layout",
          "calibration_blob", "calibration_key"]
PRIMARY_KEYS = {
    "irsa_collection": ["name"],
    "coverage": ["target_key"],
    "coverage_image": ["target_key", "frame_id"],
    "cutout": ["cache_key"],
    "file_layout": ["file_url"],
    "calibration_blob": ["sha256"],
    "calibration_key": ["s3_key"],
}
CHUNK = 1 << 20


def mb(n: int) -> str:
    return f"{n / 1e6:,.1f} MB"


def columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = %s ORDER BY ordinal_position", (table,)).fetchall()
    return [r[0] for r in rows]


def quoted(names: list[str]) -> str:
    return ", ".join(f'"{n}"' for n in names)


class TransferError(Exception):
    """The archive cannot be used (wrong format, newer schema, ...). The message says what to do."""


# =============================================================================================
# Export
# =============================================================================================
def export_cache(out: Path, url: str | None = None, analysis_dir: Path | None = None, say=print) -> None:
    url, analysis_dir = url or db.DATABASE_URL, analysis_dir or DEFAULT_ANALYSIS_DIR
    t0 = time.time()
    manifest = {"format": FORMAT_VERSION, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tables": {}}
    with tempfile.TemporaryDirectory() as tmp, psycopg.connect(url) as conn:
        conn.execute(db.SCHEMA_SQL)  # an empty database gets the tables, so the export just has 0 rows
        conn.commit()
        # One snapshot for all tables, so coverage and its images match even if the backend is writing.
        # (Set on the connection: psycopg opens the transaction itself, a "BEGIN ..." statement would be ignored.)
        conn.isolation_level, conn.read_only = psycopg.IsolationLevel.REPEATABLE_READ, True
        for table in TABLES:
            cols = columns(conn, table)
            rows = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            path = Path(tmp) / f"{table}.bin"
            with path.open("wb") as fh, conn.cursor().copy(
                    f'COPY "{table}" ({quoted(cols)}) TO STDOUT (FORMAT binary)') as copy:
                for chunk in copy:
                    fh.write(chunk)
            manifest["tables"][table] = {"columns": cols, "rows": rows}
            say(f"  {table:17s} {rows:7d} rows  {mb(path.stat().st_size):>10s}")
        conn.rollback()

        targets = sorted(p.relative_to(analysis_dir).as_posix()
                         for p in analysis_dir.glob("*/*") if p.is_dir()) if analysis_dir.is_dir() else []
        manifest["analysis_targets"] = targets
        say(f"  analysis folders  {len(targets):7d}")

        (Path(tmp) / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_name(out.name + ".partial")
        with tarfile.open(partial, "w:gz", compresslevel=3) as tar:  # level 3: much faster, barely larger
            tar.add(Path(tmp) / "manifest.json", "manifest.json")
            for table in TABLES:
                tar.add(Path(tmp) / f"{table}.bin", f"db/{table}.bin")
            for t in targets:
                tar.add(analysis_dir / t, f"analysis/{t}")
        partial.replace(out)  # an interrupted export never leaves a file that looks complete
    say(f"wrote {out} ({mb(out.stat().st_size)}) in {time.time() - t0:.0f} s")


# =============================================================================================
# Import
# =============================================================================================
def merge_table(conn: psycopg.Connection, table: str, cols: list[str]) -> int:
    """Move the rows of temp table `incoming` into `table`; returns the number of rows written."""
    pk = PRIMARY_KEYS[table]
    c = quoted(cols)
    if table == "coverage":
        # The newer search wins. Deleting the older local one also drops its images (ON DELETE CASCADE);
        # the incoming images are inserted next, so a search result and its images always stay together.
        conn.execute("""DELETE FROM coverage l USING incoming i
                        WHERE l.target_key = i.target_key AND l.data_as_of < i.data_as_of""")
        return conn.execute(f"INSERT INTO coverage ({c}) SELECT {c} FROM incoming "
                            "ON CONFLICT DO NOTHING").rowcount
    if table == "coverage_image":
        # Only the images of a search result that came from the archive: a local search result that was kept
        # (newer) keeps exactly its own images.
        ic = ", ".join(f'i."{x}"' for x in cols)
        return conn.execute(f"""INSERT INTO coverage_image ({c}) SELECT {ic}
                                FROM incoming i
                                WHERE NOT EXISTS (SELECT 1 FROM coverage_image l WHERE l.target_key = i.target_key)
                                   OR i.target_key IN (SELECT target_key FROM imported_coverage)
                                ON CONFLICT DO NOTHING""").rowcount
    if table == "cutout":
        # A downloaded cutout replaces a local failure record ('error' or 'outside' never beats 'ready').
        updates = ", ".join(f'"{x}" = EXCLUDED."{x}"' for x in cols if x not in pk)
        return conn.execute(f"""INSERT INTO cutout ({c}) SELECT {c} FROM incoming
                                ON CONFLICT (cache_key) DO UPDATE SET {updates}
                                WHERE cutout.status <> 'ready' AND EXCLUDED.status = 'ready'""").rowcount
    return conn.execute(f'INSERT INTO "{table}" ({c}) SELECT {c} FROM incoming ON CONFLICT DO NOTHING').rowcount


def import_cache(archive: Path, replace: bool = False, url: str | None = None,
                 analysis_dir: Path | None = None, say=print) -> None:
    url, analysis_dir = url or db.DATABASE_URL, analysis_dir or DEFAULT_ANALYSIS_DIR
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive, "r:gz") as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())
        if manifest.get("format") != FORMAT_VERSION:
            raise TransferError(f"{archive}: archive format {manifest.get('format')}, this code reads {FORMAT_VERSION}")
        say(f"archive from {manifest['created']}")

        with psycopg.connect(url) as conn:
            conn.execute(db.SCHEMA_SQL)  # brings the tables up to the current schema first
            with conn.transaction():  # all tables or none
                if replace:
                    conn.execute(f"TRUNCATE {', '.join(TABLES)}")
                for table in TABLES:
                    info = manifest["tables"][table]
                    cols, local = info["columns"], set(columns(conn, table))
                    missing = [x for x in cols if x not in local]
                    if missing:
                        raise TransferError(f"{table}: the archive has columns this database lacks ({missing}); "
                                            "update this checkout (git pull) and try again")
                    conn.execute("DROP TABLE IF EXISTS incoming")
                    conn.execute(f'CREATE TEMP TABLE incoming AS SELECT {quoted(cols)} FROM "{table}" LIMIT 0')
                    src = tar.extractfile(f"db/{table}.bin")
                    with conn.cursor().copy(f"COPY incoming ({quoted(cols)}) FROM STDIN (FORMAT binary)") as copy:
                        while chunk := src.read(CHUNK):
                            copy.write(chunk)
                    if table == "coverage":
                        # Which search results the archive wins (missing or older locally), for coverage_image.
                        conn.execute("DROP TABLE IF EXISTS imported_coverage")
                        conn.execute("""CREATE TEMP TABLE imported_coverage AS
                                        SELECT i.target_key FROM incoming i LEFT JOIN coverage l USING (target_key)
                                        WHERE l.target_key IS NULL OR l.data_as_of < i.data_as_of""")
                    written = merge_table(conn, table, cols)
                    say(f"  {table:17s} {info['rows']:7d} in archive, {written:7d} written")
                conn.execute("DROP TABLE IF EXISTS incoming, imported_coverage")

        copied = skipped = 0
        for t in manifest.get("analysis_targets", []):
            dest = analysis_dir / t
            if dest.exists() and not replace:
                skipped += 1
                continue
            members = [m for m in tar.getmembers() if m.name == f"analysis/{t}" or m.name.startswith(f"analysis/{t}/")]
            tar.extractall(tmp, members=members, filter="data")  # "data": no absolute paths, links or ../
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(Path(tmp) / "analysis" / t), dest)
            copied += 1
        say(f"  analysis folders  {copied} copied, {skipped} kept (already here)")
    say(f"done in {time.time() - t0:.0f} s")


def download(source: str, dest_dir: str, say=print) -> Path:
    """`source` is a local file or an http(s) URL; returns the path of a local file (downloaded into dest_dir)."""
    if not source.startswith(("http://", "https://")):
        return Path(source)
    dest = Path(dest_dir) / "cache_archive.tar.gz"
    say(f"downloading {source}")
    req = urllib.request.Request(source, headers={"User-Agent": "sac-challenger5-cache-transfer"})
    with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as fh:
        total, done, last = int(resp.headers.get("Content-Length") or 0), 0, time.time()
        while chunk := resp.read(CHUNK):
            fh.write(chunk)
            done += len(chunk)
            if time.time() - last > 10:
                say(f"  {mb(done)}" + (f" of {mb(total)}" if total else ""))
                last = time.time()
    say(f"  downloaded {mb(dest.stat().st_size)}")
    return dest


# =============================================================================================
# Start-up helper
# =============================================================================================
def is_empty(url: str | None = None) -> bool:
    """True when the cache database holds no search results and no cutouts (a fresh install)."""
    with psycopg.connect(url or db.DATABASE_URL) as conn:
        conn.execute(db.SCHEMA_SQL)
        return conn.execute("SELECT NOT EXISTS (SELECT 1 FROM coverage) AND NOT EXISTS (SELECT 1 FROM cutout)").fetchone()[0]


def seed_if_empty(source: str | None, url: str | None = None, analysis_dir: Path | None = None) -> bool:
    """Load the archive `source` (file or URL) when the database is empty. Used by the backend at start-up when
    SPHEREX_SEED_URL is set. Never raises: if it fails the backend simply starts with an empty cache and downloads
    from IRSA as usual. Returns True when something was imported."""
    if not source:
        return False
    try:
        if not is_empty(url):
            log.info("cache seed skipped: the database already has data")
            return False
        log.info("empty cache: loading the snapshot from %s", source)
        with tempfile.TemporaryDirectory() as tmp:
            import_cache(download(source, tmp, say=log.info), url=url, analysis_dir=analysis_dir, say=log.info)
        return True
    except Exception as err:  # noqa: BLE001
        log.warning("cache seed failed, continuing with an empty cache: %s", err)
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Copy the backend cache (database + analysis results) between machines.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write the cache to an archive")
    e.add_argument("archive", nargs="?", type=Path, default=Path("cache_export.tar.gz"))
    i = sub.add_parser("import", help="merge an archive (file or http(s) URL) into this machine's cache")
    i.add_argument("archive", help="path or URL of the .tar.gz")
    i.add_argument("--replace", action="store_true", help="discard this machine's cache first (exact copy)")
    args = ap.parse_args()
    print(f"database: {db.DATABASE_URL.split('@')[-1]}")
    try:
        if args.cmd == "export":
            export_cache(args.archive)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                import_cache(download(args.archive, tmp), args.replace)
            print("Restart the backend if it is running: docker compose restart backend")
    except TransferError as err:
        sys.exit(str(err))


if __name__ == "__main__":
    main()
