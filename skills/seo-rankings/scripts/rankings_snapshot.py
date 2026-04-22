#!/usr/bin/env python3
"""
Capture a Google Search Console snapshot for the active Kernel SEO client
and persist it into a per-client SQLite database.

The target DB lives at ``<client_root>/tracking/snapshots.db`` and is
created on first use with WAL journaling. Re-running on the same day
with the same (property, end_date) tuple is rejected unless --overwrite
is passed, which deletes the matching snapshot (and its ranks) and
captures again.

The client is resolved via ``load_client.py`` from the active working
directory. Override with --client-dir or --sitio.

Usage:
    python rankings_snapshot.py                         # last 28 days, default dims
    python rankings_snapshot.py --days 14
    python rankings_snapshot.py --dimensions query
    python rankings_snapshot.py --overwrite             # replace today's snapshot
    python rankings_snapshot.py --json                  # JSON metadata to stdout
"""

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
from typing import Optional

# Repo layout at runtime:
#   ~/.claude/skills/seo/scripts/              <- gsc_query, google_auth
#   ~/.claude/skills/seo-cliente/scripts/      <- load_client
#   ~/.claude/skills/seo-rankings/scripts/     <- this file
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SEO_SCRIPTS = os.path.normpath(os.path.join(THIS_DIR, "..", "..", "seo", "scripts"))
CLIENTE_SCRIPTS = os.path.normpath(os.path.join(THIS_DIR, "..", "..", "seo-cliente", "scripts"))
for p in (SEO_SCRIPTS, CLIENTE_SCRIPTS):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at  TEXT    NOT NULL,
    property     TEXT    NOT NULL,
    start_date   TEXT    NOT NULL,
    end_date     TEXT    NOT NULL,
    dimensions   TEXT    NOT NULL,
    row_count    INTEGER NOT NULL,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS ranks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    query       TEXT    NOT NULL,
    page        TEXT,
    country     TEXT,
    device      TEXT,
    clicks      INTEGER NOT NULL DEFAULT 0,
    impressions INTEGER NOT NULL DEFAULT 0,
    ctr         REAL    NOT NULL DEFAULT 0,
    position    REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_snapshots_end_date ON snapshots(end_date);
CREATE INDEX IF NOT EXISTS idx_ranks_snapshot ON ranks(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_ranks_query ON ranks(query);

-- Schema metadata (single row) for future migrations.
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '1');
"""


def resolve_client(client_dir: Optional[str], sitio_path: Optional[str]) -> dict:
    """Resolve the active client config, honoring explicit overrides first."""
    from load_client import find_sitio_json, load_and_validate

    if sitio_path:
        if not os.path.isfile(sitio_path):
            raise FileNotFoundError(f"sitio.json not found at {sitio_path}")
        return load_and_validate(sitio_path)

    start = client_dir or os.getcwd()
    path = find_sitio_json(start)
    if not path:
        raise FileNotFoundError(
            f"No sitio.json under {start} or any ancestor. "
            "Run this script from a client's directory or pass --client-dir."
        )
    return load_and_validate(path)


def open_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def existing_snapshot(conn: sqlite3.Connection, property_: str, end_date: str) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM snapshots WHERE property = ? AND end_date = ?",
        (property_, end_date),
    ).fetchone()
    return row[0] if row else None


def take_snapshot(
    client: dict,
    days: int,
    dimensions: list,
    start_date: Optional[str],
    end_date: Optional[str],
    row_limit: int,
    overwrite: bool,
    notes: Optional[str],
) -> dict:
    """Fetch GSC data and persist it. Returns a summary dict."""
    from gsc_query import query_search_analytics

    property_ = client["gsc_property"]
    root_dir = client["root_dir"]

    # Default date window mirrors GSC's usual 2-3 day lag.
    if not end_date:
        end_date = (_dt.date.today() - _dt.timedelta(days=3)).isoformat()
    if not start_date:
        start_date = (
            _dt.date.fromisoformat(end_date) - _dt.timedelta(days=days - 1)
        ).isoformat()

    db_path = os.path.join(root_dir, "tracking", "snapshots.db")
    conn = open_db(db_path)

    existing_id = existing_snapshot(conn, property_, end_date)
    if existing_id and not overwrite:
        conn.close()
        raise FileExistsError(
            f"A snapshot for property '{property_}' ending on {end_date} "
            f"already exists (id={existing_id}). Pass --overwrite to replace."
        )

    # Pull data from GSC (re-uses the shared paginated query helper).
    result = query_search_analytics(
        site_url=property_,
        start_date=start_date,
        end_date=end_date,
        dimensions=dimensions,
        row_limit=row_limit,
    )
    if result.get("error"):
        conn.close()
        raise RuntimeError(f"GSC error: {result['error']}")

    rows = result.get("rows", [])
    captured_at = _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    with conn:  # single transaction: overwrite + insert + ranks
        if existing_id:
            conn.execute("DELETE FROM snapshots WHERE id = ?", (existing_id,))
            # ranks are removed via ON DELETE CASCADE

        cur = conn.execute(
            """
            INSERT INTO snapshots
                (captured_at, property, start_date, end_date, dimensions, row_count, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (captured_at, property_, start_date, end_date, ",".join(dimensions), len(rows), notes),
        )
        snapshot_id = cur.lastrowid

        to_insert = []
        for r in rows:
            # row_keys are labelled by dimension name; gsc_query.py already
            # enriches the row dict with per-dimension keys (e.g., "query",
            # "page"). Defaulting to empty string keeps schema columns typed.
            to_insert.append((
                snapshot_id,
                (r.get("query") or "").strip(),
                r.get("page"),
                r.get("country"),
                r.get("device"),
                int(r.get("clicks", 0)),
                int(r.get("impressions", 0)),
                float(r.get("ctr", 0.0)),
                float(r.get("position", 0.0)),
            ))
        if to_insert:
            conn.executemany(
                """
                INSERT INTO ranks
                    (snapshot_id, query, page, country, device,
                     clicks, impressions, ctr, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                to_insert,
            )

    conn.close()

    return {
        "snapshot_id": snapshot_id,
        "captured_at": captured_at,
        "property": property_,
        "start_date": start_date,
        "end_date": end_date,
        "dimensions": dimensions,
        "row_count": len(rows),
        "db_path": db_path,
        "replaced_previous": bool(existing_id),
        "totals": result.get("totals", {}),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Snapshot GSC data for the active Kernel SEO client."
    )
    parser.add_argument(
        "--client-dir",
        help="Directory to resolve the client from (default: cwd).",
    )
    parser.add_argument(
        "--sitio",
        help="Explicit path to a sitio.json (skips cwd walk-up).",
    )
    parser.add_argument("--days", type=int, default=28, help="Date range in days (default: 28).")
    parser.add_argument("--start-date", help="Override start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Override end date (YYYY-MM-DD).")
    parser.add_argument(
        "--dimensions",
        default="query,page",
        help="Comma-separated GSC dimensions (default: query,page).",
    )
    parser.add_argument(
        "--row-limit", type=int, default=5000,
        help="Max rows to fetch (default: 5000).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing snapshot with the same (property, end_date).",
    )
    parser.add_argument("--notes", help="Free-form notes attached to the snapshot.")
    parser.add_argument("--json", action="store_true", help="Emit result as JSON.")

    args = parser.parse_args()

    try:
        client = resolve_client(args.client_dir, args.sitio)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    dimensions = [d.strip() for d in args.dimensions.split(",") if d.strip()]

    try:
        result = take_snapshot(
            client=client,
            days=args.days,
            dimensions=dimensions,
            start_date=args.start_date,
            end_date=args.end_date,
            row_limit=args.row_limit,
            overwrite=args.overwrite,
            notes=args.notes,
        )
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(3)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"✓ Snapshot #{result['snapshot_id']} saved")
        print(f"  Property:     {result['property']}")
        print(f"  Date range:   {result['start_date']} -> {result['end_date']}")
        print(f"  Dimensions:   {', '.join(result['dimensions'])}")
        print(f"  Rows:         {result['row_count']}")
        totals = result.get("totals") or {}
        if totals:
            print(
                f"  Totals:       clicks={totals.get('clicks', 0)}  "
                f"impressions={totals.get('impressions', 0)}  "
                f"ctr={totals.get('ctr', 0)}%"
            )
        if result.get("replaced_previous"):
            print("  (replaced a previous snapshot with the same end_date)")
        print(f"  DB:           {result['db_path']}")


if __name__ == "__main__":
    main()
