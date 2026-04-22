#!/usr/bin/env python3
"""
Classify the active Kernel SEO client's existing Google Search Console
keyword portfolio into actionable buckets and score each query by its
potential click lift.

Pulls fresh data from GSC (via gsc_query.query_search_analytics) and
writes a CSV to ``<client_root>/keywords/portfolio.csv`` sorted by
priority score. Each row carries the original GSC metrics plus:

    bucket                 see BUCKET_RULES below
    action                 short recommended action for the bucket
    expected_ctr_at_pos3   benchmark CTR at position 3 (from CTR_CURVE)
    potential_clicks       impressions * (expected_ctr - current_ctr)
                           clamped to >= 0
    priority_score         potential_clicks, integer-rounded

The CTR curve is a conservative approximation of published SERP CTR
studies (Sistrix 2024, Advanced Web Ranking 2025 aggregates). It is NOT
a precise ranking lift model; it is a prioritisation heuristic.

Usage:
    python keywords_portfolio.py
    python keywords_portfolio.py --days 28 --output portfolio.csv
    python keywords_portfolio.py --json
"""

import argparse
import csv
import datetime as _dt
import json
import os
import sys
from typing import Optional

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SEO_SCRIPTS = os.path.normpath(os.path.join(THIS_DIR, "..", "..", "seo", "scripts"))
CLIENTE_SCRIPTS = os.path.normpath(os.path.join(THIS_DIR, "..", "..", "seo-cliente", "scripts"))
for p in (SEO_SCRIPTS, CLIENTE_SCRIPTS):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)


# Conservative CTR curve per average SERP position (desktop + mobile blended).
# Source: aggregates from Sistrix 2024, Advanced Web Ranking 2025 studies.
# Values intentionally on the lower end so recommendations are credible.
CTR_CURVE = {
    1: 0.30, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05,
    6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.015,
    11: 0.012, 12: 0.010, 13: 0.008, 14: 0.007, 15: 0.006,
    16: 0.005, 17: 0.004, 18: 0.004, 19: 0.003, 20: 0.003,
}
EXPECTED_CTR_AT_POS_3 = CTR_CURVE[3]


# Bucket rules are checked top-to-bottom; first match wins.
# Each tuple is (bucket_name, action, predicate).
BUCKET_RULES = [
    (
        "winner",
        "Defender con contenido fresco y cobertura semántica; vigilar competencia.",
        lambda r: r["position"] <= 3.5 and r["clicks"] >= 10,
    ),
    (
        "untapped_page",
        "Optimizar title y meta description para subir CTR (posicion buena, CTR bajo).",
        lambda r: r["position"] <= 5.5 and r["impressions"] >= 100 and r["ctr_pct"] < 2.0,
    ),
    (
        "quick_win",
        "Quick win: pequeño push de contenido/enlaces internos para cruzar al top 3.",
        lambda r: 3.5 < r["position"] <= 10.5 and r["impressions"] >= 50,
    ),
    (
        "striking_distance",
        "Contenido profundo y entidades relacionadas para entrar al top 10.",
        lambda r: 10.5 < r["position"] <= 20.5 and r["impressions"] >= 100,
    ),
    (
        "low_ctr_generic",
        "Revisar title/meta (CTR inusualmente bajo para la posicion).",
        lambda r: r["position"] <= 10.5 and r["ctr_pct"] < 0.5 and r["impressions"] >= 50,
    ),
    (
        "long_tail",
        "Agrupar en contenido tematico mayor (seo-cluster) si hay volumen combinado.",
        lambda r: True,  # catch-all
    ),
]


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


def classify_row(row: dict) -> tuple:
    """Return (bucket, action) for a GSC row (already enriched with ctr_pct)."""
    for bucket, action, predicate in BUCKET_RULES:
        if predicate(row):
            return bucket, action
    return "long_tail", BUCKET_RULES[-1][1]


def expected_ctr_for_position(position: float) -> float:
    """Interpolated expected CTR for a fractional average position."""
    if position < 1:
        return CTR_CURVE[1]
    if position >= 20:
        return CTR_CURVE[20]
    lo = int(position)
    hi = lo + 1
    frac = position - lo
    return CTR_CURVE[lo] * (1 - frac) + CTR_CURVE[hi] * frac


def score_row(row: dict) -> tuple:
    """Return (potential_clicks, priority_score).

    potential_clicks  = impressions * max(expected_ctr_at_pos_3 - current_ctr, 0)
    priority_score    = round(potential_clicks)

    The pos-3 benchmark is intentional: it represents "reasonable top-SERP
    performance". It is NOT a claim that every keyword can reach pos 3 --
    it is a lift estimation aimed at ranking which queries deserve effort
    first.
    """
    current_ctr = row["ctr_pct"] / 100.0
    lift = max(EXPECTED_CTR_AT_POS_3 - current_ctr, 0.0)
    potential = row["impressions"] * lift
    return round(potential, 2), int(round(potential))


def build_portfolio(
    client: dict,
    days: int,
    start_date: Optional[str],
    end_date: Optional[str],
    row_limit: int,
) -> list:
    from gsc_query import query_search_analytics

    if not end_date:
        end_date = (_dt.date.today() - _dt.timedelta(days=3)).isoformat()
    if not start_date:
        start_date = (
            _dt.date.fromisoformat(end_date) - _dt.timedelta(days=days - 1)
        ).isoformat()

    gsc = query_search_analytics(
        site_url=client["gsc_property"],
        start_date=start_date,
        end_date=end_date,
        dimensions=["query", "page"],
        row_limit=row_limit,
    )
    if gsc.get("error"):
        raise RuntimeError(f"GSC error: {gsc['error']}")

    enriched = []
    for r in gsc.get("rows", []):
        query = (r.get("query") or "").strip()
        if not query:
            continue
        row = {
            "query": query,
            "page": r.get("page") or "",
            "clicks": int(r.get("clicks", 0)),
            "impressions": int(r.get("impressions", 0)),
            "ctr_pct": float(r.get("ctr", 0.0)),  # already in percent
            "position": float(r.get("position", 0.0)),
        }
        bucket, action = classify_row(row)
        potential, priority = score_row(row)
        row.update({
            "bucket": bucket,
            "action": action,
            "expected_ctr_at_pos3_pct": round(EXPECTED_CTR_AT_POS_3 * 100, 2),
            "potential_clicks": potential,
            "priority_score": priority,
        })
        enriched.append(row)

    # Highest-priority first, with clicks as tiebreaker.
    enriched.sort(key=lambda r: (-r["priority_score"], -r["clicks"]))
    return enriched, {"start_date": start_date, "end_date": end_date,
                      "totals": gsc.get("totals", {})}


def write_csv(rows: list, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    field_order = [
        "priority_score", "bucket", "query", "position",
        "impressions", "clicks", "ctr_pct",
        "expected_ctr_at_pos3_pct", "potential_clicks",
        "page", "action",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=field_order)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in field_order})


def bucket_summary(rows: list) -> list:
    """Per-bucket aggregate counts, clicks, potential. Preserves rule order."""
    order = [name for name, _, _ in BUCKET_RULES]
    by = {name: {"count": 0, "clicks": 0, "impressions": 0, "potential": 0.0}
          for name in order}
    for r in rows:
        b = by[r["bucket"]]
        b["count"] += 1
        b["clicks"] += r["clicks"]
        b["impressions"] += r["impressions"]
        b["potential"] += r["potential_clicks"]
    return [{"bucket": name, **by[name]} for name in order if by[name]["count"]]


def main():
    parser = argparse.ArgumentParser(description="Classify and score the active client's GSC keyword portfolio.")
    parser.add_argument("--client-dir")
    parser.add_argument("--sitio")
    parser.add_argument("--days", type=int, default=28, help="Date window in days (default: 28).")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--row-limit", type=int, default=5000, help="Max GSC rows (default: 5000).")
    parser.add_argument(
        "--output",
        help="Output CSV path (default: <client>/keywords/portfolio.csv).",
    )
    parser.add_argument(
        "--top", type=int, default=15,
        help="How many top rows per bucket to print (default: 15).",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        client = resolve_client(args.client_dir, args.sitio)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        rows, meta = build_portfolio(
            client=client,
            days=args.days,
            start_date=args.start_date,
            end_date=args.end_date,
            row_limit=args.row_limit,
        )
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    output_path = args.output or os.path.join(
        client["root_dir"], "keywords", "portfolio.csv"
    )
    write_csv(rows, output_path)

    summary = bucket_summary(rows)

    if args.json:
        print(json.dumps({
            "client": {
                "slug": client["slug"],
                "url": client["url"],
                "gsc_property": client["gsc_property"],
            },
            "date_range": meta,
            "summary_by_bucket": summary,
            "csv_path": output_path,
            "row_count": len(rows),
        }, indent=2, ensure_ascii=False))
        return

    print(f"=== Portfolio for {client['slug']} ({meta['start_date']} -> {meta['end_date']}) ===")
    totals = meta.get("totals") or {}
    if totals:
        print(f"  GSC totals: clicks={totals.get('clicks', 0)}  "
              f"impressions={totals.get('impressions', 0)}  ctr={totals.get('ctr', 0)}%")
    print(f"  Rows saved: {len(rows)}  ->  {output_path}")
    print()
    print(f"  {'bucket':<22}{'count':>7}{'clicks':>9}{'impressions':>13}{'potential_clicks':>20}")
    print("  " + "-" * 70)
    for b in summary:
        print(
            f"  {b['bucket']:<22}{b['count']:>7}{b['clicks']:>9}"
            f"{b['impressions']:>13}{int(round(b['potential'])):>20}"
        )

    # Print the top rows per high-value bucket.
    high_value = ["untapped_page", "quick_win", "striking_distance"]
    for bucket_name in high_value:
        top_rows = [r for r in rows if r["bucket"] == bucket_name][:args.top]
        if not top_rows:
            continue
        print()
        print(f"[ Top {len(top_rows)} in {bucket_name} ]")
        for r in top_rows:
            print(
                f"  +{r['priority_score']:>4} {r['query']!r:<55.55}  "
                f"pos={r['position']:>4.1f}  imp={r['impressions']:>5}  "
                f"clicks={r['clicks']:>3}  ctr={r['ctr_pct']:>4.2f}%"
            )


if __name__ == "__main__":
    main()
