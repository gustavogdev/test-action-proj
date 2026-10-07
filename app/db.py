"""Versioned SQLite storage for the click-counter demo.

Each app version gets its own db file (clicks_v<version>.db). On startup:
1. Every existing clicks_v*.db is backed up to <name>.bak (overwritten each
   run) as a manual-recovery safety net -- these are never auto-restored.
2. The current version's db is created if missing, and its schema is brought
   up to date with SCHEMA below (new tables/columns only -- additive).
3. If the current version's db was just created, data is copied forward
   from the most recent older version's db that exists, so click history
   isn't lost across version bumps.

To evolve the schema, edit SCHEMA. A new column must carry a DEFAULT if it's
NOT NULL, since SQLite's ALTER TABLE ADD COLUMN rejects NOT NULL columns
without one.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

SCHEMA = {
    "clicks": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "clicked_at": "TEXT NOT NULL",
    },
}

DB_GLOB = "clicks_v*.db"
DB_PREFIX = "clicks_v"
DB_SUFFIX = ".db"


def get_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            # A macOS .app launched before being dragged to /Applications can
            # run from a read-only, Gatekeeper-translocated path, and writing
            # inside Contents/MacOS would mutate the bundle anyway.
            data_dir = Path.home() / "Library" / "Application Support" / "myapp"
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def version_db_path(data_dir: Path, version: str) -> Path:
    return data_dir / f"{DB_PREFIX}{version}{DB_SUFFIX}"


def _version_from_path(path: Path) -> Version | None:
    name = path.name
    if not (name.startswith(DB_PREFIX) and name.endswith(DB_SUFFIX)):
        return None
    raw = name[len(DB_PREFIX):-len(DB_SUFFIX)]
    try:
        return Version(raw)
    except InvalidVersion:
        return None


def backup_existing_dbs(data_dir: Path) -> None:
    import shutil

    for db_file in data_dir.glob(DB_GLOB):
        shutil.copy2(db_file, db_file.with_suffix(db_file.suffix + ".bak"))


def ensure_schema(conn: sqlite3.Connection) -> None:
    for table, columns in SCHEMA.items():
        col_defs = ", ".join(f"{name} {decl}" for name, decl in columns.items())
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")

        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def find_previous_db(data_dir: Path, current_version: str) -> Path | None:
    current = Version(current_version)
    candidates = []
    for db_file in data_dir.glob(DB_GLOB):
        version = _version_from_path(db_file)
        if version is not None and version < current:
            candidates.append((version, db_file))
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[0])[1]


def migrate_data(old_path: Path, new_conn: sqlite3.Connection) -> None:
    new_conn.execute("ATTACH DATABASE ? AS old_db", (str(old_path),))
    try:
        old_tables = {
            row[0]
            for row in new_conn.execute(
                "SELECT name FROM old_db.sqlite_master WHERE type='table'"
            )
        }
        for table in SCHEMA:
            if table not in old_tables:
                continue
            old_cols = [row[1] for row in new_conn.execute(f"PRAGMA old_db.table_info({table})")]
            new_cols = [row[1] for row in new_conn.execute(f"PRAGMA table_info({table})")]
            shared = [c for c in new_cols if c in old_cols]
            if not shared:
                continue
            col_list = ", ".join(shared)
            new_conn.execute(
                f"INSERT INTO main.{table} ({col_list}) "
                f"SELECT {col_list} FROM old_db.{table}"
            )
        new_conn.commit()
    finally:
        new_conn.execute("DETACH DATABASE old_db")


def init_version_db(version: str) -> Path:
    data_dir = get_data_dir()
    backup_existing_dbs(data_dir)

    path = version_db_path(data_dir, version)
    is_new = not path.exists()

    conn = sqlite3.connect(path)
    try:
        ensure_schema(conn)
        if is_new:
            previous = find_previous_db(data_dir, version)
            if previous is not None:
                migrate_data(previous, conn)
        conn.commit()
    finally:
        conn.close()

    return path
