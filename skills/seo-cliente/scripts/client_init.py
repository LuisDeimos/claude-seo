#!/usr/bin/env python3
"""
Scaffold a new Kernel SEO client directory.

Creates ``$KSEO_CLIENTS_DIR/<slug>/`` (default: ``~/Documentos/kernel-seo-clientes``)
with:

    sitio.json       -- client config (url, gsc_property, sector, ...)
    audits/          -- outputs of /seo audit, one sub-dir per run
    keywords/        -- keyword research outputs
    tracking/        -- ranking snapshots (SQLite lives here)
    reportes/        -- final deliverables (PDFs, presentations)
    notas.md         -- free-form notes

Validation:
    - Refuses to overwrite an existing client (use --force to replace).
    - If Google credentials are configured, verifies the given
      gsc_property appears in the authenticated user's GSC sites list.

Usage:
    python client_init.py kingconstruccion \\
        --url https://www.kingconstruccion.app \\
        --gsc-property sc-domain:kingconstruccion.app \\
        --sector "ecommerce-construccion" \\
        --pais MX --idioma es
"""

import argparse
import datetime as _dt
import json
import os
import re
import sys
from typing import Optional
from urllib.parse import urlparse

SCHEMA_VERSION = 1
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
DEFAULT_CLIENTS_DIR = os.path.expanduser(
    os.environ.get("KSEO_CLIENTS_DIR", "~/Documentos/kernel-seo-clientes")
)


def validate_slug(slug: str) -> str:
    if not SLUG_PATTERN.match(slug):
        raise ValueError(
            f"Invalid slug '{slug}'. Use lowercase letters, digits, and hyphens "
            "(2-64 chars, must start alphanumeric)."
        )
    return slug


def infer_gsc_property(url: str) -> str:
    """Default GSC property format when the caller omits --gsc-property."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"Could not parse hostname from url: {url}")
    # Strip leading 'www.' since GSC domain properties cover all sub-domains.
    host = host[4:] if host.startswith("www.") else host
    return f"sc-domain:{host}"


def check_gsc_access(gsc_property: str) -> Optional[str]:
    """Return None if the property is accessible, else an informative message.
    Never raises; credential issues should not block client creation."""
    # Import lazily so a broken google_auth doesn't break `client_init`.
    try:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        parent_scripts = os.path.normpath(
            os.path.join(this_dir, "..", "..", "seo", "scripts")
        )
        if parent_scripts not in sys.path:
            sys.path.insert(0, parent_scripts)
        from google_auth import get_oauth_credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        return f"skipped (import failed: {e})"

    try:
        creds = get_oauth_credentials(
            ["https://www.googleapis.com/auth/webmasters.readonly"]
        )
        if not creds:
            return "skipped (no credentials configured)"
        service = build("searchconsole", "v1", credentials=creds)
        resp = service.sites().list().execute()
        sites = {s.get("siteUrl") for s in resp.get("siteEntry", [])}
        if gsc_property in sites:
            return None
        return (
            f"property '{gsc_property}' is NOT in this account's GSC sites. "
            f"Available: {sorted(sites)[:5]}..."
        )
    except Exception as e:
        return f"skipped (GSC API error: {e})"


def write_sitio_json(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def write_notas(path: str, slug: str, url: str) -> None:
    body = (
        f"# Notas — {slug}\n\n"
        f"URL: {url}\n"
        f"Fecha de alta: {_dt.date.today().isoformat()}\n\n"
        "## Contexto del cliente\n\n"
        "_Breve descripción del negocio, stakeholders, objetivos SEO._\n\n"
        "## Acuerdos y alcance\n\n"
        "_Servicios contratados, periodicidad de reportes, SLAs._\n\n"
        "## Histórico\n\n"
        "_Auditorías anteriores, cambios relevantes en el sitio, incidencias._\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def scaffold(
    clients_dir: str,
    slug: str,
    url: str,
    gsc_property: str,
    sector: Optional[str],
    pais: str,
    idioma: str,
    competidores: list,
    force: bool,
) -> str:
    client_dir = os.path.join(clients_dir, slug)
    if os.path.exists(client_dir) and not force:
        raise FileExistsError(
            f"Client directory already exists: {client_dir}. "
            "Use --force to replace."
        )

    os.makedirs(client_dir, exist_ok=True)
    for sub in ("audits", "keywords", "tracking", "reportes"):
        os.makedirs(os.path.join(client_dir, sub), exist_ok=True)

    payload = {
        "version": SCHEMA_VERSION,
        "slug": slug,
        "url": url,
        "gsc_property": gsc_property,
        "sector": sector or "",
        "pais": pais,
        "idioma": idioma,
        "competidores": competidores,
        "notas": "",
        "fecha_alta": _dt.date.today().isoformat(),
    }
    write_sitio_json(os.path.join(client_dir, "sitio.json"), payload)
    write_notas(os.path.join(client_dir, "notas.md"), slug, url)

    return client_dir


def main():
    parser = argparse.ArgumentParser(
        description="Scaffold a new Kernel SEO client."
    )
    parser.add_argument("slug", help="Client slug (lowercase, hyphens). Becomes the dir name.")
    parser.add_argument("--url", required=True, help="Canonical URL, e.g. https://www.example.com")
    parser.add_argument(
        "--gsc-property",
        help="GSC property (e.g. sc-domain:example.com). Inferred from --url if omitted.",
    )
    parser.add_argument("--sector", help="Free-form sector tag (saas, ecommerce, local, publisher, etc.).")
    parser.add_argument("--pais", default="MX", help="ISO country code (default: MX).")
    parser.add_argument("--idioma", default="es", help="ISO language code (default: es).")
    parser.add_argument(
        "--competidor",
        action="append",
        default=[],
        help="Competitor URL. Repeatable: --competidor A --competidor B.",
    )
    parser.add_argument(
        "--clients-dir",
        default=DEFAULT_CLIENTS_DIR,
        help=f"Root directory for all clients (default: {DEFAULT_CLIENTS_DIR}, "
             "override with KSEO_CLIENTS_DIR env var).",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing client dir.")
    parser.add_argument(
        "--skip-gsc-check",
        action="store_true",
        help="Do not verify the gsc_property against the authenticated GSC account.",
    )
    parser.add_argument("--json", action="store_true", help="Output result as JSON.")
    args = parser.parse_args()

    try:
        slug = validate_slug(args.slug)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        gsc_property = args.gsc_property or infer_gsc_property(args.url)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    gsc_status = "skipped"
    if not args.skip_gsc_check:
        warn = check_gsc_access(gsc_property)
        if warn:
            print(f"Warning: {warn}", file=sys.stderr)
            gsc_status = warn
        else:
            gsc_status = "verified"

    try:
        client_dir = scaffold(
            clients_dir=os.path.expanduser(args.clients_dir),
            slug=slug,
            url=args.url,
            gsc_property=gsc_property,
            sector=args.sector,
            pais=args.pais,
            idioma=args.idioma,
            competidores=args.competidor,
            force=args.force,
        )
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Error creating client directory: {e}", file=sys.stderr)
        sys.exit(1)

    result = {
        "slug": slug,
        "url": args.url,
        "gsc_property": gsc_property,
        "sector": args.sector or "",
        "pais": args.pais,
        "idioma": args.idioma,
        "competidores": args.competidor,
        "root_dir": client_dir,
        "gsc_check": gsc_status,
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"✓ Cliente creado: {slug}")
        print(f"  Carpeta:        {client_dir}")
        print(f"  URL:            {args.url}")
        print(f"  GSC property:   {gsc_property}")
        print(f"  Sector:         {args.sector or '(no especificado)'}")
        print(f"  GSC check:      {gsc_status}")
        print()
        print("Siguiente paso:")
        print(f"  cd {client_dir}")
        print(f"  claude   # abre Claude Code en el directorio del cliente")
        print(f"  /seo audit {args.url}")


if __name__ == "__main__":
    main()
