#!/usr/bin/env python3
"""
Resolve the active client by walking upward from the current working
directory looking for a ``sitio.json`` file, git-style.

Exit codes:
    0 - a client was resolved; JSON written to stdout
    1 - no sitio.json found in cwd or any ancestor
    2 - sitio.json found but is malformed / fails schema check

Usage:
    python load_client.py               # walk from cwd
    python load_client.py --start /path # walk from a specific directory
    python load_client.py --field url   # print only one field
"""

import argparse
import json
import os
import sys
from typing import Optional


SITE_FILE = "sitio.json"

# Minimal required fields in sitio.json. Extra fields are allowed and passed
# through unchanged so the schema can evolve without breaking older clients.
REQUIRED_FIELDS = ("slug", "url", "gsc_property")


def find_sitio_json(start_dir: str) -> Optional[str]:
    """Walk upward from ``start_dir`` until SITE_FILE is found or / is hit."""
    current = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(current, SITE_FILE)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def load_and_validate(path: str) -> dict:
    """Load sitio.json and verify the required fields are present."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("sitio.json must contain a JSON object at the root")
    missing = [k for k in REQUIRED_FIELDS if not data.get(k)]
    if missing:
        raise ValueError(
            f"sitio.json is missing required field(s): {', '.join(missing)}"
        )
    data["_path"] = path
    data["root_dir"] = os.path.dirname(path)
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Resolve the active Kernel SEO client from cwd."
    )
    parser.add_argument(
        "--start",
        default=os.getcwd(),
        help="Directory to start the upward search from (default: cwd).",
    )
    parser.add_argument(
        "--field",
        help="Print only this field from sitio.json (e.g., gsc_property).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="(default) Output the full client config as JSON.",
    )
    args = parser.parse_args()

    path = find_sitio_json(args.start)
    if not path:
        print(
            f"No {SITE_FILE} found in '{args.start}' or any ancestor. "
            f"Create a client with: python client_init.py <slug> --url=<url>",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        client = load_and_validate(path)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error loading {path}: {e}", file=sys.stderr)
        sys.exit(2)

    if args.field:
        value = client.get(args.field)
        if value is None:
            print(f"Field '{args.field}' not present in {path}", file=sys.stderr)
            sys.exit(2)
        if isinstance(value, (dict, list)):
            print(json.dumps(value, ensure_ascii=False))
        else:
            print(value)
    else:
        print(json.dumps(client, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
