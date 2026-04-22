#!/usr/bin/env python3
"""
Expand a seed keyword list via Google Suggest autocomplete.

Uses the public ``google.com/complete/search?client=firefox`` endpoint,
which returns a JSON array ``[prefix, [suggestions, ...]]``. No API key
required, no auth. To avoid abuse, this script self-rate-limits and
caps the total number of requests per run.

Output: a CSV at ``<client_root>/keywords/sugerencias_<timestamp>.csv``
(or ``--output``) with columns:

    seed                root keyword that produced the suggestion
    depth               1 for first-level suggestions, 2 for second-level
    suggestion          the suggested keyword
    alphabet_branch     suffix used to expand ("", "a", "b", ..., "z"),
                        only when --alphabet is enabled

Usage:
    python keywords_suggest.py "cemento blanco"
    python keywords_suggest.py "cemento blanco" "armex 10x10" --depth 2
    python keywords_suggest.py "cemento" --alphabet --max-requests 30
    python keywords_suggest.py "cemento" --hl es --gl MX

Safety notes:
    * --max-requests (default 30) is a hard cap.
    * --delay is the sleep between requests (default 0.7 s).
    * Duplicate suggestions are deduplicated within a run.
    * On any HTTP error the loop continues with the remaining seeds.
"""

import argparse
import csv
import datetime as _dt
import json
import os
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENTE_SCRIPTS = os.path.normpath(os.path.join(THIS_DIR, "..", "..", "seo-cliente", "scripts"))
if os.path.isdir(CLIENTE_SCRIPTS) and CLIENTE_SCRIPTS not in sys.path:
    sys.path.insert(0, CLIENTE_SCRIPTS)


SUGGEST_URL = "https://www.google.com/complete/search"
# Plain browser-like UA; Google's public endpoint does not require it but
# some ISPs block empty UAs.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def resolve_client_or_none(client_dir: Optional[str], sitio_path: Optional[str]):
    """Resolve the active client if we're inside one; else None."""
    try:
        from load_client import find_sitio_json, load_and_validate
    except ImportError:
        return None
    if sitio_path and os.path.isfile(sitio_path):
        try:
            return load_and_validate(sitio_path)
        except Exception:
            return None
    start = client_dir or os.getcwd()
    path = find_sitio_json(start)
    if not path:
        return None
    try:
        return load_and_validate(path)
    except Exception:
        return None


def fetch_suggest(query: str, hl: str, gl: str, timeout: float = 10.0) -> list:
    """Return a list of suggestion strings for ``query`` or [] on failure."""
    params = {"client": "firefox", "q": query, "hl": hl, "gl": gl}
    url = f"{SUGGEST_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"Warning: request failed for {query!r}: {e}", file=sys.stderr)
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list) or len(data) < 2 or not isinstance(data[1], list):
        return []
    # Each item in data[1] can be a plain string or (in other clients) a [q, meta] pair.
    out = []
    for item in data[1]:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, list) and item and isinstance(item[0], str):
            out.append(item[0])
    return out


def run_expansion(
    seeds: list,
    depth: int,
    hl: str,
    gl: str,
    alphabet: bool,
    max_requests: int,
    delay: float,
) -> list:
    """Return a list of dict rows describing every unique suggestion."""
    results = []  # list of {"seed", "depth", "suggestion", "alphabet_branch"}
    seen = set()  # (seed, suggestion) de-dup
    requests_made = 0

    def record(seed, depth_, suggestion, branch):
        key = (seed, suggestion.lower())
        if key in seen:
            return
        seen.add(key)
        results.append({
            "seed": seed,
            "depth": depth_,
            "suggestion": suggestion,
            "alphabet_branch": branch,
        })

    def maybe_fetch(query: str, seed: str, depth_: int, branch: str):
        nonlocal requests_made
        if requests_made >= max_requests:
            return []
        requests_made += 1
        suggestions = fetch_suggest(query, hl=hl, gl=gl)
        for s in suggestions:
            record(seed, depth_, s, branch)
        time.sleep(delay)
        return suggestions

    alphabet_suffixes = [""] + (list(string.ascii_lowercase) if alphabet else [])

    for seed in seeds:
        seed = seed.strip()
        if not seed:
            continue

        # Level 1 (with optional alphabet fan-out)
        level1 = []
        for suffix in alphabet_suffixes:
            if requests_made >= max_requests:
                break
            query = f"{seed} {suffix}".strip()
            branch = suffix or "(none)"
            got = maybe_fetch(query, seed=seed, depth_=1, branch=branch)
            level1.extend(got)

        # Level 2: feed back the level-1 suggestions as new seeds, but
        # only if depth >= 2. No alphabet fan-out here.
        if depth >= 2:
            for s in list(level1):
                if requests_made >= max_requests:
                    break
                maybe_fetch(s, seed=seed, depth_=2, branch="")

    return results


def write_csv(rows: list, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    field_order = ["seed", "depth", "alphabet_branch", "suggestion"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=field_order)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def default_output_path(client: Optional[dict]) -> str:
    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if client:
        return os.path.join(
            client["root_dir"], "keywords", f"sugerencias_{timestamp}.csv"
        )
    return os.path.join(os.getcwd(), f"sugerencias_{timestamp}.csv")


def main():
    parser = argparse.ArgumentParser(description="Expand seed keywords via Google Suggest.")
    parser.add_argument("seeds", nargs="+", help="Seed keywords (quote multi-word phrases).")
    parser.add_argument("--depth", type=int, choices=[1, 2], default=1,
                        help="Expansion depth (1=seeds only, 2=recurse once, default 1).")
    parser.add_argument("--hl", default="es", help="Interface language (default: es).")
    parser.add_argument("--gl", default="MX", help="Country (default: MX).")
    parser.add_argument("--alphabet", action="store_true",
                        help="Fan out each seed with a-z suffixes for broader coverage.")
    parser.add_argument("--max-requests", type=int, default=30,
                        help="Hard cap on HTTP requests (default: 30).")
    parser.add_argument("--delay", type=float, default=0.7,
                        help="Seconds between requests (default: 0.7).")
    parser.add_argument("--client-dir")
    parser.add_argument("--sitio")
    parser.add_argument("--output", help="Explicit output CSV path.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    client = resolve_client_or_none(args.client_dir, args.sitio)

    rows = run_expansion(
        seeds=args.seeds,
        depth=args.depth,
        hl=args.hl,
        gl=args.gl,
        alphabet=args.alphabet,
        max_requests=args.max_requests,
        delay=args.delay,
    )

    output_path = args.output or default_output_path(client)
    write_csv(rows, output_path)

    if args.json:
        print(json.dumps({
            "seeds": args.seeds,
            "depth": args.depth,
            "hl": args.hl,
            "gl": args.gl,
            "alphabet": args.alphabet,
            "unique_suggestions": len(rows),
            "csv_path": output_path,
            "client": client["slug"] if client else None,
        }, indent=2, ensure_ascii=False))
        return

    print(f"✓ {len(rows)} unique suggestions written to {output_path}")
    if not rows:
        print("  (empty result — try different seeds, or --alphabet for broader coverage)")
        return

    # Print a compact preview.
    preview = rows[:15]
    print()
    print(f"  Preview (first {len(preview)}):")
    for r in preview:
        branch = f" ({r['alphabet_branch']})" if r['alphabet_branch'] not in ("(none)", "") else ""
        print(f"    [d{r['depth']}] {r['suggestion']}{branch}  <- seed={r['seed']!r}")


if __name__ == "__main__":
    main()
