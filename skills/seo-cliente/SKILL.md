---
name: seo-cliente
description: >
  Manage SEO clients as persistent workspaces. Use when the user says
  "new client", "list clients", "cliente nuevo", "crear cliente", "dar
  de alta cliente", "contexto del cliente", or wants the current site's
  GSC property / URL / sector resolved from the working directory.
user-invokable: true
argument-hint: "<list|new|show> [slug]"
license: MIT
metadata:
  author: KernelSoluciones
  version: "0.1.0"
  category: seo
---

# Kernel SEO — Client Workspace Management

Keeps client data (audits, keyword research, rankings, reports, notes)
organized as per-client directories on disk, so every other `/seo *`
command can resolve the active client from the current working directory.

## Directory convention

```
$KSEO_CLIENTS_DIR/                 (default: ~/Documentos/kernel-seo-clientes/)
  <slug>/
    sitio.json                    # canonical client config
    notas.md                      # free-form notes (alcance, stakeholders, historial)
    audits/<YYYY-MM-DD>/          # outputs of /seo audit
    keywords/                     # keyword research (Fase 3 artifacts)
    tracking/                     # ranking snapshots, SQLite (Fase 4 artifacts)
    reportes/                     # final deliverables (PDFs, presentations)
```

`sitio.json` schema (version 1):

```json
{
  "version": 1,
  "slug": "kingconstruccion",
  "url": "https://www.kingconstruccion.app",
  "gsc_property": "sc-domain:kingconstruccion.app",
  "sector": "ecommerce-construccion",
  "pais": "MX",
  "idioma": "es",
  "competidores": ["https://..."],
  "notas": "",
  "fecha_alta": "2026-04-22"
}
```

Required fields: `slug`, `url`, `gsc_property`. Everything else is optional
and passed through unchanged so future fields can be added without breaking
existing clients.

## Active-client resolution

**cwd-based, git-style.** A command is "scoped" to whichever client's
directory it is executed inside. There is no global active-client state.

`scripts/load_client.py` walks upward from the current directory until
it finds a `sitio.json`. If the user is in
`~/Documentos/kernel-seo-clientes/kingconstruccion/audits/2026-04-22/`,
running `python load_client.py` returns the `kingconstruccion` config.

This means: **always `cd` into the client's directory before running any
`/seo *` command.** No flags, no session state, no "which client are we
using again?" confusion.

## Commands

| Command | Action |
|---------|--------|
| `/seo cliente list` | Tabular list of all clients (slug, url, sector, last audit) |
| `/seo cliente new <slug> --url=<url>` | Scaffold a new client directory |
| `/seo cliente show [slug]` | Print `sitio.json` for the current or named client |
| `/seo cliente use <slug>` | Print a `cd` command to jump to the client's root |

Under the hood, each of these maps to one of:

- `python scripts/client_list.py [--json]`
- `python scripts/client_init.py <slug> --url <url> [--gsc-property=...] [--sector=...] [--competidor=...]`
- `python scripts/load_client.py [--start <dir>] [--field <key>]`

## Integration with other skills

When the user runs any `/seo *` command that writes output to disk
(audit, plan, cluster, backlinks, rankings), the orchestrator should:

1. Call `python skills/seo-cliente/scripts/load_client.py --json` to
   resolve the active client. If exit code != 0, warn and fall back to
   the user's cwd.
2. If a client is resolved, write outputs under
   `<root_dir>/audits/<YYYY-MM-DD>/` (for audits) or the appropriate
   sub-folder.
3. Prefer the client's `gsc_property` over the global
   `default_property` from `~/.config/claude-seo/google-api.json`.

Example:

```bash
# Resolve GSC property for the current client (or fail silently)
GSC_PROP=$(python load_client.py --field gsc_property 2>/dev/null) && \
  python gsc_query.py query --property "$GSC_PROP" --days 28 --limit 100
```

## End-to-end walkthrough

```bash
# 1. Create a client
python scripts/client_init.py kingconstruccion \
    --url https://www.kingconstruccion.app \
    --sector "ecommerce-construccion" \
    --competidor https://www.cemex.com/mx

# 2. Jump into their workspace
cd ~/Documentos/kernel-seo-clientes/kingconstruccion

# 3. Open Claude Code from there
claude

# 4. Any /seo command automatically scopes to this client
#    because cwd contains sitio.json.
/seo audit https://www.kingconstruccion.app
```

## Design notes

- **No new Python dependencies.** Uses only the stdlib (`json`, `argparse`,
  `os`, `datetime`). Fits on top of the existing skill without adding
  YAML/TOML parsers.
- **Non-destructive by default.** `client_init.py` refuses to overwrite
  an existing client without `--force`.
- **GSC verification is best-effort.** `client_init.py` tries to confirm
  the given `gsc_property` is in the authenticated user's GSC sites list,
  but credential problems never block client creation — they are reported
  as a warning.
- **Portable config.** `KSEO_CLIENTS_DIR` overrides the default root, so
  clients can live on an encrypted volume or shared network drive.

## Related skills (planned)

- **Phase 4 — `seo-rankings`**: consumes `tracking/snapshots.db` in each
  client folder.
- **Phase 3 — `seo-keywords`**: writes `keywords/keywords.csv` per client.
