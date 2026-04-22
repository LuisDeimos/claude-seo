#!/usr/bin/env python3
"""
List all Kernel SEO clients under $KSEO_CLIENTS_DIR.

For each client directory that contains a valid ``sitio.json``, prints:
    slug, url, gsc_property, sector, last_audit_date

Usage:
    python client_list.py
    python client_list.py --json
    python client_list.py --clients-dir /custom/path
"""

import argparse
import json
import os
import sys
from typing import Optional

DEFAULT_CLIENTS_DIR = os.path.expanduser(
    os.environ.get("KSEO_CLIENTS_DIR", "~/Documentos/kernel-seo-clientes")
)


def last_audit_date(audits_dir: str) -> Optional[str]:
    """Latest subdirectory name inside ``audits/`` (expected to be YYYY-MM-DD).

    Dates sort lexicographically in ISO format, so we can pick the maximum
    without parsing. Returns None when the folder is missing or empty."""
    if not os.path.isdir(audits_dir):
        return None
    entries = [
        name for name in os.listdir(audits_dir)
        if os.path.isdir(os.path.join(audits_dir, name))
    ]
    return max(entries) if entries else None


def scan(clients_dir: str) -> list:
    if not os.path.isdir(clients_dir):
        return []
    out = []
    for name in sorted(os.listdir(clients_dir)):
        client_path = os.path.join(clients_dir, name)
        sitio_path = os.path.join(client_path, "sitio.json")
        if not os.path.isfile(sitio_path):
            continue
        try:
            with open(sitio_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            out.append({
                "slug": name,
                "error": f"could not read sitio.json: {e}",
            })
            continue
        out.append({
            "slug": data.get("slug", name),
            "url": data.get("url", ""),
            "gsc_property": data.get("gsc_property", ""),
            "sector": data.get("sector", ""),
            "pais": data.get("pais", ""),
            "last_audit": last_audit_date(os.path.join(client_path, "audits")),
            "root_dir": client_path,
        })
    return out


def main():
    parser = argparse.ArgumentParser(description="List Kernel SEO clients.")
    parser.add_argument(
        "--clients-dir",
        default=DEFAULT_CLIENTS_DIR,
        help=f"Root directory for clients (default: {DEFAULT_CLIENTS_DIR}).",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON.")
    args = parser.parse_args()

    clients = scan(os.path.expanduser(args.clients_dir))

    if args.json:
        print(json.dumps(clients, indent=2, ensure_ascii=False))
        return

    if not clients:
        print(
            f"No clients found in {args.clients_dir}.\n"
            "Create one with: python client_init.py <slug> --url <url>",
            file=sys.stderr,
        )
        sys.exit(0)

    # Column widths
    slug_w = max(len("slug"), max(len(c.get("slug", "")) for c in clients))
    url_w = max(len("url"), max(len(c.get("url", "")) for c in clients))
    sector_w = max(len("sector"), max(len(c.get("sector", "")) for c in clients))

    header = (
        f"{'slug':<{slug_w}}  {'url':<{url_w}}  "
        f"{'sector':<{sector_w}}  last_audit"
    )
    print(header)
    print("-" * len(header))
    for c in clients:
        if c.get("error"):
            print(f"{c['slug']:<{slug_w}}  ERROR: {c['error']}")
            continue
        last = c.get("last_audit") or "(nunca)"
        print(
            f"{c['slug']:<{slug_w}}  {c.get('url', ''):<{url_w}}  "
            f"{c.get('sector', ''):<{sector_w}}  {last}"
        )


if __name__ == "__main__":
    main()
