#!/usr/bin/env python3
"""
Compare two Google Search Console snapshots for the active client and
surface the biggest winners, biggest losers, and disappearing keywords.

Reads from ``<client_root>/tracking/snapshots.db`` populated by
``rankings_snapshot.py``. The client is resolved with the same cwd
walk-up used by the rest of seo-cliente; override with --client-dir or
--sitio.

Default comparison:
    - "after"  = most recent snapshot
    - "before" = the snapshot whose end_date is closest to `N` days before `after`

Flags for significance (applied per keyword):

    position_delta >= 3           -- position dropped by 3 or more ranks
    dropped_from_top_10           -- was <= 10.5, now > 10.5 (top 10 exit)
    clicks_dropped_>= 50_pct       -- lost >= 50% of clicks vs before
    impressions_dropped_>= 50_pct  -- lost >= 50% of impressions vs before

Usage:
    python rankings_trend.py                  # most recent vs one ~14 days earlier
    python rankings_trend.py --days 14
    python rankings_trend.py --before 2 --after 1          # by snapshot id
    python rankings_trend.py --top 20 --json
"""

import argparse
import json
import os
import sqlite3
import sys
from typing import Optional, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENTE_SCRIPTS = os.path.normpath(os.path.join(THIS_DIR, "..", "..", "seo-cliente", "scripts"))
if os.path.isdir(CLIENTE_SCRIPTS) and CLIENTE_SCRIPTS not in sys.path:
    sys.path.insert(0, CLIENTE_SCRIPTS)


def resolve_client(client_dir: Optional[str], sitio_path: Optional[str]) -> dict:
    from load_client import find_sitio_json, load_and_validate
    if sitio_path:
        return load_and_validate(sitio_path)
    start = client_dir or os.getcwd()
    path = find_sitio_json(start)
    if not path:
        raise FileNotFoundError(
            f"No sitio.json under {start} or any ancestor. "
            "Run from a client's directory or pass --client-dir."
        )
    return load_and_validate(path)


def resolve_snapshot_pair(
    conn: sqlite3.Connection,
    days: int,
    before_id: Optional[int],
    after_id: Optional[int],
) -> Tuple[dict, dict]:
    """Return (before_meta, after_meta) as dicts from the snapshots table."""
    # Latest two by default.
    all_snaps = conn.execute(
        "SELECT id, captured_at, property, start_date, end_date, dimensions, "
        "row_count FROM snapshots ORDER BY end_date DESC, id DESC"
    ).fetchall()
    if not all_snaps:
        raise RuntimeError(
            "No snapshots in the DB yet. Run rankings_snapshot.py first."
        )

    def row_to_dict(r):
        return {
            "id": r[0], "captured_at": r[1], "property": r[2],
            "start_date": r[3], "end_date": r[4],
            "dimensions": r[5], "row_count": r[6],
        }

    by_id = {r[0]: row_to_dict(r) for r in all_snaps}

    if after_id and before_id:
        if after_id not in by_id or before_id not in by_id:
            raise RuntimeError(
                f"Snapshot id(s) not found. Available ids: {sorted(by_id)}"
            )
        return by_id[before_id], by_id[after_id]

    after = by_id[all_snaps[0][0]]  # most recent

    # Pick the snapshot whose end_date is closest to (after.end_date - days)
    # AND is older than `after`. Falls back to "second most recent" if no
    # older snapshot matches the window.
    import datetime as _dt
    after_end = _dt.date.fromisoformat(after["end_date"])
    target = after_end - _dt.timedelta(days=days)

    older = [s for s in all_snaps if s[0] != after["id"]
             and _dt.date.fromisoformat(s[4]) < after_end]
    if not older:
        raise RuntimeError(
            "Only one snapshot exists; cannot compute trend. "
            "Run rankings_snapshot.py with a different --end-date or wait "
            "for the next capture."
        )

    # Nearest in absolute days from the target.
    best = min(older, key=lambda r: abs((_dt.date.fromisoformat(r[4]) - target).days))
    return row_to_dict(best), after


def fetch_ranks(conn: sqlite3.Connection, snapshot_id: int) -> dict:
    """Return {query: aggregated row} aggregated over all pages/devices.
    Position is impression-weighted average; clicks and impressions are summed."""
    cur = conn.execute(
        "SELECT query, clicks, impressions, position "
        "FROM ranks WHERE snapshot_id = ? AND query != ''",
        (snapshot_id,),
    )
    aggregates = {}
    for query, clicks, impressions, position in cur:
        agg = aggregates.setdefault(query, {
            "query": query, "clicks": 0, "impressions": 0,
            "position_weighted": 0.0,  # sum(position * impressions)
        })
        agg["clicks"] += clicks
        agg["impressions"] += impressions
        agg["position_weighted"] += position * impressions

    # Collapse into final shape with clean position.
    out = {}
    for query, agg in aggregates.items():
        imps = agg["impressions"]
        out[query] = {
            "query": query,
            "clicks": agg["clicks"],
            "impressions": imps,
            "position": round(agg["position_weighted"] / imps, 2) if imps else 0.0,
        }
    return out


def classify(before: Optional[dict], after: Optional[dict]) -> dict:
    """Produce a delta row. Either side may be None (new keyword / dropped)."""
    def safe_pct(new, old):
        if old == 0:
            return None
        return round((new - old) / old * 100, 1)

    result = {
        "query": (after or before)["query"],
        "before": before,
        "after": after,
        "position_delta": None,          # positive = worse (higher number)
        "clicks_delta": None,
        "impressions_delta": None,
        "clicks_pct": None,
        "impressions_pct": None,
        "flags": [],
    }

    if before is None:
        result["flags"].append("new")
        return result
    if after is None:
        result["flags"].append("disappeared")
        return result

    pos_delta = round(after["position"] - before["position"], 2)
    result["position_delta"] = pos_delta
    result["clicks_delta"] = after["clicks"] - before["clicks"]
    result["impressions_delta"] = after["impressions"] - before["impressions"]
    result["clicks_pct"] = safe_pct(after["clicks"], before["clicks"])
    result["impressions_pct"] = safe_pct(after["impressions"], before["impressions"])

    if pos_delta >= 3:
        result["flags"].append("position_drop_3plus")
    if before["position"] <= 10.5 and after["position"] > 10.5:
        result["flags"].append("dropped_from_top_10")
    if result["clicks_pct"] is not None and result["clicks_pct"] <= -50:
        result["flags"].append("clicks_dropped_50pct")
    if result["impressions_pct"] is not None and result["impressions_pct"] <= -50:
        result["flags"].append("impressions_dropped_50pct")
    if pos_delta <= -3:
        result["flags"].append("position_gain_3plus")
    if before["position"] > 10.5 and after["position"] <= 10.5:
        result["flags"].append("entered_top_10")
    return result


def compute_trend(
    db_path: str,
    days: int,
    before_id: Optional[int],
    after_id: Optional[int],
    min_impressions: int,
) -> dict:
    if not os.path.isfile(db_path):
        raise FileNotFoundError(
            f"No snapshots DB at {db_path}. Run rankings_snapshot.py first."
        )

    conn = sqlite3.connect(db_path)
    try:
        before_meta, after_meta = resolve_snapshot_pair(conn, days, before_id, after_id)
        before_ranks = fetch_ranks(conn, before_meta["id"])
        after_ranks = fetch_ranks(conn, after_meta["id"])
    finally:
        conn.close()

    queries = set(before_ranks) | set(after_ranks)
    rows = [classify(before_ranks.get(q), after_ranks.get(q)) for q in queries]

    # Filter low-noise queries (rarely-impressed, unlikely to reflect real drift).
    def worthy(row):
        before = row["before"] or {}
        after = row["after"] or {}
        return max(before.get("impressions", 0), after.get("impressions", 0)) >= min_impressions
    rows = [r for r in rows if worthy(r)]

    winners = [r for r in rows if r["position_delta"] is not None and r["position_delta"] < 0]
    winners.sort(key=lambda r: r["position_delta"])

    losers = [r for r in rows if r["position_delta"] is not None and r["position_delta"] > 0]
    losers.sort(key=lambda r: -r["position_delta"])

    disappeared = [r for r in rows if "disappeared" in r["flags"]]
    disappeared.sort(key=lambda r: -(r["before"] or {}).get("impressions", 0))

    new_queries = [r for r in rows if "new" in r["flags"]]
    new_queries.sort(key=lambda r: -(r["after"] or {}).get("impressions", 0))

    summary = {
        "before": before_meta,
        "after": after_meta,
        "queries_compared": len(rows),
        "winners_count": len(winners),
        "losers_count": len(losers),
        "disappeared_count": len(disappeared),
        "new_count": len(new_queries),
        "min_impressions_filter": min_impressions,
    }
    return {
        "summary": summary,
        "winners": winners,
        "losers": losers,
        "disappeared": disappeared,
        "new": new_queries,
    }


def format_row_text(row: dict) -> str:
    q = row["query"]
    before = row["before"]
    after = row["after"]
    if "disappeared" in row["flags"]:
        return (
            f"  [GONE] {q!r}  "
            f"(was pos {before['position']}, {before['clicks']} clicks, "
            f"{before['impressions']} impressions)"
        )
    if "new" in row["flags"]:
        return (
            f"  [NEW]  {q!r}  "
            f"(now pos {after['position']}, {after['clicks']} clicks, "
            f"{after['impressions']} impressions)"
        )
    arrow = "↓" if row["position_delta"] > 0 else ("↑" if row["position_delta"] < 0 else "=")
    flag_str = f"  flags={','.join(row['flags'])}" if row["flags"] else ""
    return (
        f"  {arrow} {q!r}  pos {before['position']}->{after['position']} "
        f"(Δ{row['position_delta']:+.1f})  clicks {before['clicks']}->{after['clicks']} "
        f"({row['clicks_pct']}%){flag_str}"
    )


def print_human(report: dict, top: int) -> None:
    s = report["summary"]
    print("=== Snapshot trend ===")
    print(f"  Before: snap #{s['before']['id']}  {s['before']['start_date']}→{s['before']['end_date']}  rows={s['before']['row_count']}")
    print(f"  After:  snap #{s['after']['id']}  {s['after']['start_date']}→{s['after']['end_date']}  rows={s['after']['row_count']}")
    print(f"  Queries compared: {s['queries_compared']} (min impressions filter: {s['min_impressions_filter']})")
    print()
    print(f"[ Top {top} position losers ]")
    for r in report["losers"][:top]:
        print(format_row_text(r))
    print()
    print(f"[ Top {top} position winners ]")
    for r in report["winners"][:top]:
        print(format_row_text(r))
    if report["disappeared"]:
        print()
        print(f"[ Disappeared queries (top {top}) ]")
        for r in report["disappeared"][:top]:
            print(format_row_text(r))
    if report["new"]:
        print()
        print(f"[ New queries (top {top}) ]")
        for r in report["new"][:top]:
            print(format_row_text(r))


def main():
    parser = argparse.ArgumentParser(description="Compute ranking trend between two GSC snapshots.")
    parser.add_argument("--client-dir")
    parser.add_argument("--sitio")
    parser.add_argument("--days", type=int, default=14,
                        help="When --before is omitted, pick the snapshot closest to N days "
                             "before the most recent one (default: 14).")
    parser.add_argument("--before", type=int, help="Explicit 'before' snapshot id.")
    parser.add_argument("--after", type=int, help="Explicit 'after' snapshot id.")
    parser.add_argument("--top", type=int, default=15,
                        help="How many winners/losers/new/gone to print (default: 15).")
    parser.add_argument("--min-impressions", type=int, default=10,
                        help="Ignore queries whose max(before,after) impressions is below this "
                             "(default: 10). Filters out long-tail noise.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        client = resolve_client(args.client_dir, args.sitio)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    db_path = os.path.join(client["root_dir"], "tracking", "snapshots.db")
    try:
        report = compute_trend(db_path, args.days, args.before, args.after, args.min_impressions)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_human(report, args.top)


if __name__ == "__main__":
    main()
