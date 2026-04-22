---
name: seo-keywords
description: >
  Keyword research and portfolio analysis for the active Kernel SEO
  client. Classifies the client's existing GSC keyword portfolio into
  actionable buckets (winner, quick_win, untapped_page, striking_distance,
  long_tail) and expands seed keywords via Google Suggest. Use when the
  user says "investigacion de keywords", "keyword research", "quick
  wins", "untapped", "clasificar keywords", "portfolio de keywords",
  "expandir keywords", "sugerencias de keywords", "Google Suggest".
user-invokable: true
argument-hint: "<portfolio|suggest> [flags]"
license: MIT
metadata:
  author: KernelSoluciones
  version: "0.1.0"
  category: seo
---

# Kernel SEO — Keyword Research (free sources only)

Two complementary scripts that together cover the "what keywords should
my client work on" question using only free data sources (GSC OAuth,
Google Suggest public endpoint). No paid APIs. No Keyword Planner required
for the core flow.

Designed to **complement** existing upstream skills, not replace them:

| Need | Skill to use |
|------|--------------|
| Classify current keyword portfolio & prioritise | **`seo-keywords portfolio`** (this skill) |
| Discover new seed ideas from the ecosystem | **`seo-keywords suggest`** (this skill) |
| Semantic clustering by intent | `/seo cluster <seed-keyword>` (upstream) |
| Per-keyword monthly volume + CPC (paid-ish) | `gsc/scripts/keyword_planner.py` (needs Google Ads token) |
| Track positions over time | `/seo rankings snapshot` + `trend` |

## portfolio — classify the client's current GSC keywords

Pulls the last 28 days (configurable) of `query,page` rows from GSC and
classifies each query into one of:

| Bucket | Predicate | Recommended action |
|--------|-----------|--------------------|
| `winner` | position ≤ 3.5 AND clicks ≥ 10 | Defender con contenido fresco y cobertura semántica. |
| `untapped_page` | position ≤ 5.5 AND impressions ≥ 100 AND CTR < 2% | Optimizar title y meta description — posición buena, CTR pobre. |
| `quick_win` | 3.5 < position ≤ 10.5 AND impressions ≥ 50 | Pequeño push de contenido/enlaces internos para cruzar al top 3. |
| `striking_distance` | 10.5 < position ≤ 20.5 AND impressions ≥ 100 | Contenido profundo, entidades relacionadas, para entrar al top 10. |
| `low_ctr_generic` | position ≤ 10.5 AND CTR < 0.5% AND impressions ≥ 50 | Revisar title/meta (CTR inusualmente bajo). |
| `long_tail` | (catch-all) | Agrupar en contenido temático con `/seo cluster`. |

### Priority scoring

Each row gets a `priority_score` = estimated click lift if the query
moved to ~position 3, using a conservative SERP CTR curve:

```
  position  expected CTR
     1        30%
     2        15%
     3        10%   <- benchmark
     4         7%
     5         5%
     ...
    10       1.5%
    20       0.3%
```

Formula: `priority_score = round(impressions * max(0.10 - current_ctr, 0))`.
It is NOT a precise lift model; it is a ranking heuristic so you can
decide "which 15 queries deserve the first week of work".

### Output

CSV at `<client_root>/keywords/portfolio.csv` with columns:

```
priority_score, bucket, query, position, impressions, clicks,
ctr_pct, expected_ctr_at_pos3_pct, potential_clicks, page, action
```

Sorted by `priority_score` desc, then `clicks` desc.

### Usage

```bash
cd ~/Documentos/kernel-seo-clientes/<slug>
python ~/.claude/skills/seo-keywords/scripts/keywords_portfolio.py
python ~/.claude/skills/seo-keywords/scripts/keywords_portfolio.py --days 90 --top 25
python ~/.claude/skills/seo-keywords/scripts/keywords_portfolio.py --json > portfolio.json
```

## suggest — expand seed keywords via Google Suggest

Hits the public `google.com/complete/search?client=firefox` endpoint and
returns autocomplete suggestions for a list of seed keywords. No OAuth,
no API key. Safe-rate-limited (0.7s between requests by default, 30
requests hard cap per run, dedup within a run).

### Modes

- **Depth 1** (default): one request per seed, yields ~10 suggestions each.
- **Depth 2**: feeds each level-1 suggestion back as a new seed (quickly
  fills the hard-cap).
- **`--alphabet`**: for a seed like `cemento`, fans out to `cemento a`,
  `cemento b`, ..., `cemento z` so you see 10 different autocompletion
  branches. Dramatically wider recall. Counts against the request cap.

### Output

CSV at `<client_root>/keywords/sugerencias_<timestamp>.csv` (or cwd if
not inside a client). Columns:

```
seed, depth, alphabet_branch, suggestion
```

### Usage

```bash
# Single seed, Spanish/Mexico defaults
python ~/.claude/skills/seo-keywords/scripts/keywords_suggest.py "cemento blanco"

# Several seeds, 2 levels deep
python ~/.claude/skills/seo-keywords/scripts/keywords_suggest.py \
    "cemento blanco" "armex" "varilla" --depth 2

# Broad coverage via alphabet fan-out (26 requests for one seed)
python ~/.claude/skills/seo-keywords/scripts/keywords_suggest.py \
    "cemento" --alphabet --max-requests 30

# Switch locale (US English)
python ~/.claude/skills/seo-keywords/scripts/keywords_suggest.py \
    "concrete mix" --hl en --gl US
```

## Recommended workflow

1. **Weekly**: `rankings_snapshot` (seo-rankings) to keep history.
2. **At start of an engagement**: `keywords_portfolio` to identify the
   top ~20 high-priority queries. Share the CSV with the client.
3. **Content-planning sessions**: `keywords_suggest` on the topics the
   client wants to invest in. Then `/seo cluster <seed>` on the
   resulting list to get semantically grouped content briefs.
4. **Before publishing**: verify search volume with `keyword_planner.py`
   for the candidate titles (if a Google Ads developer token is
   configured).

## Design notes

- **Stdlib only.** No new Python dependencies. `keywords_portfolio.py`
  uses `csv` and the existing `gsc_query.py`. `keywords_suggest.py` uses
  `urllib.request` against a fixed host (`google.com`), not a user-supplied
  URL, so no SSRF surface.
- **Language defaults to `es`/`MX`.** Easy override via `--hl` and `--gl`.
- **Google Suggest is public but not documented.** The endpoint format
  (`client=firefox`) has been stable for years but is not guaranteed.
  If it ever breaks, the fallback is to scrape the SERP's "People also
  ask" box — a heavier implementation we have not built yet.
- **Priority score is heuristic.** Clients should read `action` and
  `bucket` first, and use `priority_score` only as a tiebreaker.

## Planned extensions

- **Google Trends integration** (`pytrends` dep) to attach 12-month
  direction and seasonality to each query.
- **Volume enrichment** via `keyword_planner.py` auto-chained when the
  user has a Google Ads developer token in `google-api.json`.
- **Per-bucket markdown brief** generator that turns the top 10 queries
  of each high-value bucket into an actionable doc for the client.
