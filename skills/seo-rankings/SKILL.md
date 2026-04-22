---
name: seo-rankings
description: >
  Track keyword ranking positions over time for the active Kernel SEO
  client using Google Search Console as the data source. Use when the
  user says "tracking de posiciones", "ranking tracker", "snapshot de
  rankings", "trend", "tendencia de keywords", "qué keywords cayeron",
  "qué keywords subieron", "evolución de rankings".
user-invokable: true
argument-hint: "<snapshot|trend|list> [flags]"
license: MIT
metadata:
  author: KernelSoluciones
  version: "0.1.0"
  category: seo
---

# Kernel SEO — Ranking Tracker (GSC-based)

Captures GSC "Search Analytics" data for the active client and stores it
in a per-client SQLite database under ``<client_root>/tracking/snapshots.db``.
Comparing two snapshots produces a trend report: biggest winners, biggest
losers, keywords that disappeared, keywords that appeared.

**Upstream has no equivalent.** `seo-drift` in the base plugin monitors
technical/content drift, not SERP position drift. This skill fills that
gap with zero new Python dependencies (stdlib `sqlite3` + existing
`gsc_query.py`).

## Prerequisites

- The active client (resolved via `load_client.py`) must have a valid
  `gsc_property` and a Google OAuth token in
  `~/.config/claude-seo/oauth-token.json` with `webmasters.readonly` scope.
- Always run from inside the client's workspace (e.g.,
  `cd ~/Documentos/kernel-seo-clientes/kingconstruccion`).

## Database schema (version 1)

```sql
snapshots(id, captured_at, property, start_date, end_date,
          dimensions, row_count, notes)
ranks(id, snapshot_id -> snapshots.id, query, page, country, device,
      clicks, impressions, ctr, position)
```

- One `snapshots` row per capture run (one per (property, end_date) pair).
- `ranks` holds the GSC rows; dimensions not captured stay NULL.
- ON DELETE CASCADE keeps the DB clean when a snapshot is overwritten.
- `PRAGMA journal_mode=WAL` (same pattern as upstream `seo-drift`).

## Commands

| Command | Script invocation |
|---------|-------------------|
| `/seo rankings snapshot [flags]` | `python scripts/rankings_snapshot.py [--days N] [--dimensions query,page] [--overwrite] [--json]` |
| `/seo rankings trend [flags]` | `python scripts/rankings_trend.py [--days N] [--before ID --after ID] [--top N] [--json]` |
| `/seo rankings list` | `sqlite3 tracking/snapshots.db "SELECT id, captured_at, end_date, row_count FROM snapshots ORDER BY end_date DESC"` |

### snapshot

Captures the active client's GSC data for a date range and persists it.

- Default window: last 28 days ending 3 days ago (respects GSC's usual
  data lag).
- Default dimensions: `query,page`.
- Re-running on the same `(property, end_date)` tuple is refused unless
  `--overwrite` is passed — this keeps daily/weekly automation idempotent.
- Default `--row-limit` of 5000 is usually plenty; raise for very
  high-traffic sites.

### trend

Compares two snapshots and emits winners, losers, disappearing queries,
and new queries.

- Default: "after" = most recent snapshot, "before" = snapshot whose
  `end_date` is closest to `--days` (default 14) before the most recent.
- Override with explicit `--before <id> --after <id>` (see `/seo rankings list`).
- Low-noise filter: `--min-impressions` (default 10) drops long-tail
  queries that can swing wildly by statistical noise.

Significance flags applied per query:

| Flag | Trigger |
|------|---------|
| `position_drop_3plus` | position_after - position_before ≥ 3 |
| `position_gain_3plus` | position_after - position_before ≤ -3 |
| `dropped_from_top_10` | before ≤ 10.5 AND after > 10.5 |
| `entered_top_10`      | before > 10.5 AND after ≤ 10.5 |
| `clicks_dropped_50pct` | ((after - before) / before) ≤ -0.5 |
| `impressions_dropped_50pct` | ((after - before) / before) ≤ -0.5 |
| `new`          | query present only in the "after" snapshot |
| `disappeared`  | query present only in the "before" snapshot |

## Recommended cadence

- **Weekly** snapshots for the active client's main property is the sweet
  spot: enough resolution to catch algorithm updates, low enough to stay
  well within GSC's 50k-queries-per-day quota.
- **Monthly** is acceptable for low-traffic sites.
- Do not snapshot on the same day repeatedly -- `end_date` is the dedup
  key, and overwriting loses history.

## End-to-end walkthrough

```bash
# 1. Enter the client's workspace (cwd-based client resolution)
cd ~/Documentos/kernel-seo-clientes/kingconstruccion

# 2. Take today's snapshot
python ~/.claude/skills/seo-rankings/scripts/rankings_snapshot.py

# 3. ... wait a week, take another
python ~/.claude/skills/seo-rankings/scripts/rankings_snapshot.py

# 4. Produce a trend report
python ~/.claude/skills/seo-rankings/scripts/rankings_trend.py --days 7 --top 20
```

Two snapshots from today with *different* date windows also work for
smoke-testing the trend engine (e.g., `--days 28` then `--days 14`) -- the
data will overlap but numbers shift enough to exercise the classifier.

## Design notes

- **Per-client DB, not a shared one.** Isolates corruption and aligns
  with the per-client-directory convention from `seo-cliente`.
- **Position aggregation is impression-weighted** when multiple rows
  (different pages, devices) share a query. This matches how GSC itself
  reports average position.
- **No PDF in MVP.** Text output is enough for internal review. Add a
  `rankings_report.py` that renders HTML→PDF via WeasyPrint when needed.
- **Stdlib only.** `sqlite3` ships with CPython. The only dependency is
  the sibling `seo/scripts/gsc_query.py` for OAuth/pagination.

## Planned extensions

- `rankings_report.py` — WeasyPrint PDF with per-keyword trend lines
  (uses matplotlib already in requirements.txt).
- `rankings_alert.py` — Slack/email notifier when flagged losses exceed
  thresholds.
- Automatic weekly snapshot via the `schedule` skill.
