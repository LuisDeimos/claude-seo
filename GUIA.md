<!-- GUIA.md — Kernel Soluciones / claude-seo fork -->

# Guía Kernel SEO

Operativa de principio a fin: instalar el stack, dar de alta un cliente,
generar el reporte inicial, y hacer seguimiento semanal/mensual.

Este fork (`LuisDeimos/claude-seo`) extiende el upstream
`AgriciDaniel/claude-seo` con:

- **3 skills nuevos** — `seo-cliente` (workspace por cliente con
  detección cwd-based), `seo-rankings` (tracker de posiciones con
  SQLite), `seo-keywords` (portfolio + Google Suggest).
- **7 fixes aplicados** (seguridad: chmod 600 en tokens OAuth, SSRF
  con resolución DNS, etc.; funcionales: pagespeed_check,
  capture_screenshot con fallback a chrome, gsc_query honrando
  `--limit`; SEO: eliminación del obsoleto "keyword density 1-3%").
- **Instalador propio** `install-kernel.sh` que salta extensiones de
  pago (DataForSEO / Banana / Firecrawl) y ajusta permisos de
  credenciales.

Funciona 100% con fuentes gratuitas: Google Search Console, Google
Suggest público, PageSpeed Insights y Chrome UX Report (gratis con API
key), Moz / Bing Webmaster / Common Crawl (para backlinks).

---

## Tabla de contenido

1. [Requisitos](#1-requisitos)
2. [Instalación inicial](#2-instalación-inicial)
3. [Credenciales de Google](#3-credenciales-de-google)
4. [Alta de un cliente](#4-alta-de-un-cliente)
5. [Auditoría inicial](#5-auditoría-inicial)
6. [Keyword research](#6-keyword-research)
7. [Tracking de posiciones](#7-tracking-de-posiciones)
8. [Flujo mensual recomendado](#8-flujo-mensual-recomendado)
9. [Actualizar el fork y reinstalar](#9-actualizar-el-fork-y-reinstalar)
10. [Troubleshooting](#10-troubleshooting)
11. [Estructura del repo](#11-estructura-del-repo)

---

## 1. Requisitos

- **SO**: Linux o macOS. En Windows, usar WSL.
- **Python 3.10+**. Verificar con `python3 --version`.
- **git 2.20+**.
- **Claude Code CLI** instalado y autenticado. Descarga:
  https://claude.ai/code.
- **Navegador** (para el flujo OAuth).
- **Cuenta de Google** con acceso a Google Cloud Console y Search
  Console. Si tu cuenta en GSC es distinta de tu cuenta personal de
  Google, vas a configurarla más adelante.
- **Opcional**: `google-chrome` o `chromium` instalado (el script
  `capture_screenshot.py` lo usa como fallback si no tienes Playwright).
  En Ubuntu: `sudo apt install google-chrome-stable` o `chromium-browser`.

---

## 2. Instalación inicial

### 2.1 Clonar el fork

Con el alias SSH configurado (recomendado — ver anexo A si necesitas
configurarlo):

```bash
git clone git@luisdeimos:LuisDeimos/claude-seo.git ~/Documentos/kernel-seo-src
```

Por HTTPS (alternativa si no tienes SSH):

```bash
git clone https://github.com/LuisDeimos/claude-seo.git ~/Documentos/kernel-seo-src
```

### 2.2 (Opcional) Pinear a una versión etiquetada

Por default `git clone` te deja en la rama `main`, que siempre apunta al
último estado estable (tag más reciente + fixes pendientes). Si
prefieres pinear a una versión específica (reproducibilidad,
producción):

```bash
cd ~/Documentos/kernel-seo-src
git checkout v0.1.0       # o la versión que quieras
```

Para ver las versiones disponibles: `git tag -l`.

### 2.3 Correr el instalador

```bash
bash install-kernel.sh
```

Qué hace, en orden:

1. Verifica que `python3 >= 3.10` y `git` estén disponibles.
2. Clona temporalmente la rama seleccionada a `/tmp/`.
3. Copia los skills a `~/.claude/skills/` (salta
   `seo-dataforseo` y `seo-image-gen` por ser extensiones de pago).
4. Copia los 17 agentes a `~/.claude/agents/`.
5. Crea un venv aislado en `~/.claude/skills/seo/.venv/` e instala las
   dependencias (beautifulsoup4, lxml, Pillow, google-api-python-client,
   matplotlib, weasyprint, etc.) — versiones con CVEs conocidos parchadas.
6. Crea `~/.config/claude-seo/` con permisos `0700`.
7. Pregunta si descargar Chromium para Playwright (~200 MB). Responde
   **N** si no vas a usar análisis visual intensivo — el fallback a
   `google-chrome` / `chromium` del sistema ya cubre el caso común.

Al terminar debes ver `23 installed, 2 skipped` y la siguiente
sección de próximos pasos. Si lanzar de nuevo el comando (p.ej. tras un
pull), simplemente re-ejecuta `bash install-kernel.sh` — es idempotente.

### 2.4 Verificación rápida

```bash
ls ~/.claude/skills/ | grep -E "seo-cliente|seo-rankings|seo-keywords"
```

Debes ver los tres skills. Si no aparecen, el `git checkout` anterior no
dejó la rama correcta.

---

## 3. Credenciales de Google

### 3.1 Crear (o elegir) un proyecto en Google Cloud

https://console.cloud.google.com → crea un proyecto llamado, por
ejemplo, `kernel-seo`. Anota el ID.

### 3.2 Habilitar APIs

Desde **APIs & Services → Library**, habilita:

- **Google Search Console API** (requerido)
- **PageSpeed Insights API** (requerido para `/seo audit` y CrUX)
- **Chrome UX Report API** (requerido para `/seo audit`)
- **Google Analytics Data API** (opcional, solo si vas a jalar tráfico
  orgánico de GA4)
- **Web Search Indexing API** (opcional, solo si vas a pedir re-indexado
  desde la skill)

### 3.3 Crear API key (para PSI y CrUX)

**APIs & Services → Credentials → Create Credentials → API key**.

Copia la key. Por seguridad, restríngela a los APIs arriba desde
"Restrict key → API restrictions".

### 3.4 Crear OAuth Client ID (para Search Console)

**APIs & Services → Credentials → Create Credentials → OAuth client ID**.

- **Application type**: Web application
- **Authorized redirect URIs**: `http://localhost:8085`
- Guarda el archivo JSON que descargas como
  `~/.config/claude-seo/client_secret.json`.

### 3.5 Configurar la pantalla de consentimiento

En **APIs & Services → OAuth consent screen**:

- **User Type**: External
- **Publishing status**: Testing
- **Test users**: agrega el email de Google con el que vas a autenticar
  (p.ej. `luisramirez@kernelsoluciones.com`). Sin esto, el flujo
  OAuth devuelve `access_denied 403`.

No es necesario publicar la app ni pedir verificación a Google.

### 3.6 Crear el archivo de configuración

```bash
cat > ~/.config/claude-seo/google-api.json <<EOF
{
  "api_key": "PEGA_TU_API_KEY_AQUI",
  "oauth_client_path": "~/.config/claude-seo/client_secret.json"
}
EOF

chmod 600 ~/.config/claude-seo/*.json
```

### 3.7 Ejecutar el flujo OAuth

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo/scripts/google_auth.py \
  --auth --creds ~/.config/claude-seo/client_secret.json
```

Se abrirá tu navegador. Acepta el consentimiento. Si Google muestra
"Google hasn't verified this app": **Advanced → Go to Kernel SEO
(unsafe)** (es tu propia app, es seguro).

Al volver a la terminal verás `OAuth token saved successfully!`. El
token queda en `~/.config/claude-seo/oauth-token.json` con permisos
`0600` (el fix de seguridad garantiza que no sea legible por otros
usuarios del sistema).

### 3.8 Verificar

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo/scripts/google_auth.py --check
```

Deberías ver al menos:

```
[OK] PageSpeed Insights v5
[OK] Chrome UX Report (CrUX) API
[OK] CrUX History API
[OK] Google Search Console API
[OK] Google Indexing API v3
```

GA4 aparecerá como MISSING si no configuraste `ga4_property_id` — eso
es normal y opcional.

---

## 4. Alta de un cliente

### 4.1 Qué es "un cliente" en este stack

Un cliente es una carpeta bajo
`~/Documentos/kernel-seo-clientes/<slug>/` con un archivo `sitio.json`
que describe su URL, su propiedad de GSC, sector, país, idioma, y
competidores. Todos los scripts (snapshot, portfolio, trend, etc.)
**detectan automáticamente el cliente activo** según el directorio de
trabajo actual, estilo git.

Override de la raíz: variable de entorno `KSEO_CLIENTS_DIR`.

### 4.2 Scaffolder

Sintaxis general:

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo-cliente/scripts/client_init.py \
  <slug> \
  --url https://www.ejemplo.com \
  [--gsc-property sc-domain:ejemplo.com] \
  [--sector "ecommerce-construccion"] \
  [--pais MX] [--idioma es] \
  [--competidor https://competidor-a.com] \
  [--competidor https://competidor-b.com]
```

**Reglas del slug**: lowercase, letras / dígitos / guiones, entre 2 y 64
caracteres, debe empezar con letra o dígito. Este valor se usa como
nombre de carpeta y como identificador en todos los reportes.

**`--gsc-property`**: si lo omites, se infiere a partir de `--url`
eliminando el `www.` y prefijando `sc-domain:`. Para propiedades de tipo
URL prefix, pásalo explícito (`https://www.ejemplo.com/`).

### 4.3 Ejemplo real

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo-cliente/scripts/client_init.py \
  kingconstruccion \
  --url https://www.kingconstruccion.app \
  --sector "ecommerce-construccion-mx" \
  --pais MX --idioma es
```

Salida esperada:

```
✓ Cliente creado: kingconstruccion
  Carpeta:        /home/deimos/Documentos/kernel-seo-clientes/kingconstruccion
  URL:            https://www.kingconstruccion.app
  GSC property:   sc-domain:kingconstruccion.app
  Sector:         ecommerce-construccion-mx
  GSC check:      verified     <-- significa que tu cuenta ya tiene acceso
```

Si ves `GSC check: skipped` → no tienes credenciales aún (regresa al
paso 3). Si ves `GSC check: property 'X' is NOT in this account's GSC
sites`, significa que el cliente aún no te ha dado acceso en su panel
de Search Console; pídeselo.

### 4.4 Estructura que se crea

```
~/Documentos/kernel-seo-clientes/<slug>/
├── sitio.json                 # config canónica (solo 6 campos obligatorios)
├── notas.md                   # plantilla para apuntes del cliente
├── audits/                    # outputs de /seo audit (una subcarpeta por fecha)
├── keywords/                  # portfolio.csv y sugerencias_*.csv
├── tracking/                  # snapshots.db (SQLite) y futuros reportes
└── reportes/                  # entregables finales (PDF, presentaciones)
```

### 4.5 Listar todos los clientes

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo-cliente/scripts/client_list.py
```

Muestra slug, url, sector y fecha del último audit.

---

## 5. Auditoría inicial

### 5.1 Abrir Claude Code dentro del workspace del cliente

```bash
cd ~/Documentos/kernel-seo-clientes/<slug>
claude
```

Es importante: el skill `/seo audit` depende de que el `cwd` contenga
`sitio.json` para escribir los outputs dentro del workspace. Si lo
abres en otro directorio, el audit se ejecuta contra la URL pero guarda
los archivos en donde estés.

### 5.2 Disparar la auditoría

Dentro de Claude Code:

```
/seo audit https://www.<dominio-del-cliente>
```

Qué hace:

- ~10 subagentes corren en paralelo (technical, content, schema,
  performance, geo, local, sxo, etc.).
- Extrae HTML crudo + renderizado, screenshots, PSI mobile/desktop,
  CrUX, sitemap, robots.txt, llms.txt.
- Genera `FULL-AUDIT-REPORT.md` + `ACTION-PLAN.md` en el directorio de
  trabajo (idealmente un subfolder por fecha).

Duración típica: 5–20 minutos, dependiendo del tamaño del sitio.

### 5.3 Organizar el output por fecha

Una convención cómoda es guardar cada corrida en una carpeta
`audits/YYYY-MM-DD/`:

```bash
mkdir -p audits/$(date +%F)
cd audits/$(date +%F)
claude
```

y luego `/seo audit ...` desde ahí. El `client_list.py` usa esta
convención para reportar la fecha del último audit.

### 5.4 Qué hacer con el output

1. Leer `FULL-AUDIT-REPORT.md` primero (diagnóstico).
2. Usar `ACTION-PLAN.md` como guion para la reunión con el cliente.
3. Priorizar los hallazgos **Critical** antes que **High / Medium**.
4. El reporte usa la nomenclatura moderna (INP, E-E-A-T con Experience,
   AI Overviews, llms.txt) — ya está alineado con las políticas de
   Google 2025-2026.

---

## 6. Keyword research

Dos scripts complementarios. Ambos se corren desde el workspace del
cliente (`cd` primero).

### 6.1 Clasificar el portfolio actual del cliente

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo-keywords/scripts/keywords_portfolio.py
```

Qué produce:

- `keywords/portfolio.csv` — todas las queries que ya rankean el sitio
  en los últimos 28 días (configurable con `--days`), clasificadas en
  seis buckets accionables:

  | Bucket | Acción recomendada |
  |--------|---------------------|
  | **winner** (pos ≤ 3.5, ≥ 10 clicks) | Defender con contenido fresco. |
  | **untapped_page** (pos ≤ 5.5, CTR < 2%) | Optimizar title y meta (posición buena, nadie hace click). |
  | **quick_win** (pos 4–10, ≥ 50 imps) | Push pequeño para cruzar al top 3. |
  | **striking_distance** (pos 11–20, ≥ 100 imps) | Contenido profundo / entidades. |
  | **low_ctr_generic** | Revisar title/meta. |
  | **long_tail** | Agrupar con `/seo cluster`. |

- Score de prioridad `priority_score = impressions × max(0.10 −
  current_ctr, 0)` — estima clicks potenciales si la query moviera a
  pos ~3. Es una **heurística de priorización**, no una predicción.

### 6.2 Expandir seeds nuevas

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo-keywords/scripts/keywords_suggest.py \
  "seed 1" "seed 2" --depth 2 --max-requests 30
```

Qué hace:

- Consulta Google Suggest público (`google.com/complete/search`).
- Auto-rate-limit (0.7 s entre requests, 30 requests por corrida por
  default).
- Escribe `keywords/sugerencias_<timestamp>.csv`.
- `--alphabet` hace fan-out con sufijos a–z para máxima cobertura (cada
  corrida cuenta contra el `--max-requests`).

### 6.3 Clustering semántico (upstream)

Ya existente en el upstream:

```
/seo cluster <seed-keyword>
```

Agrupa las sugerencias por intención (informational, commercial,
transactional, etc.) y sugiere una arquitectura de contenido.

### 6.4 Volumen (opcional, requiere Google Ads)

Si tienes cuenta de Google Ads Manager con developer token:

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo/scripts/keyword_planner.py ideas "cemento blanco"
```

Requiere agregar `ads_developer_token`, `ads_customer_id` y
`ads_login_customer_id` al `google-api.json`. Sin ads activos, los
volúmenes vienen en rangos (`1K–10K`).

---

## 7. Tracking de posiciones

### 7.1 Primer snapshot

```bash
cd ~/Documentos/kernel-seo-clientes/<slug>
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo-rankings/scripts/rankings_snapshot.py
```

- Default: últimos 28 días (terminando 3 días atrás, para respetar el
  lag de GSC).
- Captura (query, page) por cada URL que haya rankeado.
- Persiste en `tracking/snapshots.db` (SQLite, WAL journaling).

### 7.2 Snapshots recurrentes

Re-ejecutar la misma corrida más de una vez en el mismo `end_date` es
rechazado por default (evita duplicados). Pasa `--overwrite` si quieres
sobrescribir un snapshot del día.

Cadencia recomendada: **semanal** (un snapshot cada lunes, por ejemplo).

### 7.3 Ver tendencias

Tras tener dos o más snapshots:

```bash
~/.claude/skills/seo/.venv/bin/python \
  ~/.claude/skills/seo-rankings/scripts/rankings_trend.py \
  --days 7 --top 20
```

Reporta:

- **Position losers** — queries que cayeron en posición (con flags:
  `position_drop_3plus`, `dropped_from_top_10`, `clicks_dropped_50pct`).
- **Position winners** — queries que mejoraron.
- **Disappeared** — queries que había antes y ya no están.
- **New** — queries nuevas que aparecieron.

El filtro `--min-impressions 10` (default) elimina ruido de long-tail.

### 7.4 Ver el histórico

```bash
sqlite3 ~/Documentos/kernel-seo-clientes/<slug>/tracking/snapshots.db \
  "SELECT id, captured_at, end_date, row_count FROM snapshots ORDER BY end_date DESC"
```

### 7.5 Automatizar (opcional)

Dos alternativas:

**A) `/schedule` de Claude Code**

```
/schedule create --cron "0 9 * * 1" \
  "cd ~/Documentos/kernel-seo-clientes/<slug> && python ~/.claude/skills/seo-rankings/scripts/rankings_snapshot.py"
```

**B) Cron del sistema**

```bash
crontab -e
# Añadir:
0 9 * * 1 cd ~/Documentos/kernel-seo-clientes/<slug> && ~/.claude/skills/seo/.venv/bin/python ~/.claude/skills/seo-rankings/scripts/rankings_snapshot.py >> /tmp/kseo-snapshot.log 2>&1
```

---

## 8. Flujo mensual recomendado

| Frecuencia | Tarea | Comando |
|------------|-------|---------|
| Al dar de alta el cliente | Scaffolder | `client_init.py <slug> --url ...` |
| Semana 1 del engagement | `/seo audit` inicial | Dentro de Claude Code en el workspace |
| Semana 1 del engagement | Portfolio baseline | `keywords_portfolio.py --days 90` |
| Semana 1 del engagement | Primer snapshot | `rankings_snapshot.py` |
| Cada lunes | Snapshot semanal | `rankings_snapshot.py` |
| Cada lunes | Chequeo de tendencia | `rankings_trend.py --days 7 --top 10` |
| Día 1 de cada mes | Portfolio del mes | `keywords_portfolio.py --days 28` |
| Día 1 de cada mes | Trend mensual | `rankings_trend.py --days 28 --top 25` |
| Cada 3 meses | Re-auditoría completa | `/seo audit` dentro del workspace |
| Planeación trimestral | Expansión de temas | `keywords_suggest.py` + `/seo cluster` |

El entregable mensual típico para el cliente:

1. **Carta de contexto** (1 página) — qué se hizo, qué mejoró, qué se
   va a trabajar el próximo mes.
2. **Trend report de GSC** — output de `rankings_trend.py --days 28`.
3. **Portfolio del mes** — top 15 de cada bucket accionable.
4. **Acciones específicas** — derivadas del `ACTION-PLAN.md` original
   del audit, actualizadas.

Guarda el PDF final en `reportes/` del workspace del cliente.

---

## 9. Actualizar el fork y reinstalar

### 9.1 Traer cambios del upstream (oportunamente)

El upstream `AgriciDaniel/claude-seo` sigue desarrollándose. Para
incorporar fixes upstream:

```bash
cd ~/Documentos/kernel-seo-src
git fetch upstream
git checkout main
git log main..upstream/main     # revisar commits nuevos antes de merge
git merge upstream/main         # resuelve conflictos si los hay
```

**Antes de ejecutar el merge**: lee los commits nuevos del upstream y
evalúa si introducen código que cambia comportamiento. La regla del
proyecto: no confiar ciegamente en código de terceros; revisar antes de
usar. Si un commit upstream es riesgoso, se puede cherry-pick selectivo
en vez de merge completo.

### 9.2 Reinstalar tras cambios locales o pull

```bash
cd ~/Documentos/kernel-seo-src
bash install-kernel.sh
```

Es idempotente. Los snapshots, clientes y credenciales no se tocan.

### 9.3 Commits propios

Siempre trabajar en una rama feature, nunca directo sobre `main`.
Convención usada en este fork:

- `feature/<nombre>` para funcionalidad nueva.
- `fix/<nombre>` para correcciones puntuales.
- Merges a `main` solo después de validar con al menos un cliente real
  y cortar un tag nuevo (`vX.Y.Z`) para marcar el baseline.

---

## 10. Troubleshooting

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `access_denied 403` en OAuth | Email no está en Test Users | Agregar email en OAuth consent screen → Test users |
| `PSI 429 rate limit` | Falta `api_key` en `google-api.json` | Agregar API key y re-verificar |
| `KeyError: 'audit_details'` (ya parchado en v1.9.x + kernel) | Caso imposible tras el fix | Reinstalar: `bash install-kernel.sh` |
| `playwright required` | No instalaste Chromium para Playwright | Instalar `google-chrome-stable` del sistema — el fallback lo usa automáticamente |
| `No sitio.json found in X or any ancestor` | `cd` a un directorio fuera de un cliente | `cd ~/Documentos/kernel-seo-clientes/<slug>` o pasa `--client-dir` |
| `--limit` de gsc_query devuelve más filas | Versión previa a v0.1.0 | Reinstalar: `git pull && bash install-kernel.sh` |
| OAuth token expirado | Corren meses | El refresh es automático; si falla: re-ejecutar `--auth` |
| `gsc_property NOT in this account` al crear cliente | El cliente aún no te dio acceso en GSC | GSC del cliente → Configuración → Usuarios → agregar tu email |

### Logs útiles

- Token OAuth: `~/.config/claude-seo/oauth-token.json` (no abrir a menos
  que debuguees; tiene secretos, debe estar en `0600`).
- Base de snapshots: `~/Documentos/kernel-seo-clientes/<slug>/tracking/snapshots.db`.
- Cache de requirements: `~/.claude/skills/seo/requirements.txt`.

---

## 11. Estructura del repo

```
claude-seo/                          (nuestro fork)
├── GUIA.md                          <-- este archivo
├── install-kernel.sh                <-- instalador nuestro
├── install.sh                       <-- del upstream (no lo usamos)
├── skills/
│   ├── seo/                         <-- orquestador upstream
│   ├── seo-audit/, seo-technical/   <-- auditorías upstream
│   ├── seo-content/, seo-schema/    <-- análisis upstream
│   ├── seo-geo/, seo-local/         <-- GEO y local upstream
│   ├── seo-cluster/, seo-drift/     <-- upstream
│   │
│   ├── seo-cliente/                 <-- NUESTRO (workspace per-client)
│   ├── seo-rankings/                <-- NUESTRO (tracker SQLite)
│   └── seo-keywords/                <-- NUESTRO (portfolio + suggest)
│
├── scripts/                         <-- scripts Python compartidos
│   ├── google_auth.py               <-- OAuth + validate_url (FIX-1, FIX-2)
│   ├── gsc_query.py                 <-- GSC Search Analytics (FIX-7)
│   ├── pagespeed_check.py           <-- PSI v5 + CrUX (FIX-5)
│   ├── capture_screenshot.py        <-- Playwright + chrome fallback (FIX-6)
│   ├── keyword_planner.py           <-- Google Ads volumes (FIX-3)
│   └── ... (24 scripts más)
│
├── agents/                          <-- 17 subagentes upstream
├── schema/                          <-- templates JSON-LD
├── hooks/                           <-- validate-schema.py
├── extensions/                      <-- DataForSEO / Banana / Firecrawl (SKIPEAMOS)
└── docs/                            <-- doc upstream
```

Ramas y tags en el remoto:

- `main` — rama estable, contiene todo el trabajo validado. Es la
  default branch del repo en GitHub y el objetivo por default de
  `install-kernel.sh`.
- `v0.1.0` (tag) — primer baseline estable: upstream v1.9.0 + 7 fixes
  (seguridad + SEO) + 3 skills nuevos (`seo-cliente`, `seo-rankings`,
  `seo-keywords`) + esta guía.
- `feature/*` — ramas de trabajo previas, preservadas como referencia
  hasta que ya no hagan falta. Ninguna es el objetivo de instalación.

---

## Anexo A — Configurar alias SSH para la cuenta `LuisDeimos`

Si usas la misma máquina para varias cuentas de GitHub (como es el caso
de esta configuración), el patrón recomendado es tener **una llave por
cuenta**.

```bash
# 1. Generar llave dedicada
ssh-keygen -t ed25519 -C "LuisDeimos@github" -f ~/.ssh/luisdeimos_github

# 2. Añadir bloque a ~/.ssh/config
cat >> ~/.ssh/config <<'EOF'

Host luisdeimos
  HostName github.com
  User git
  IdentityFile ~/.ssh/luisdeimos_github
  IdentitiesOnly yes
EOF

# 3. Subir la clave pública a GitHub (cuenta LuisDeimos logueada)
cat ~/.ssh/luisdeimos_github.pub
# -> copiar el contenido y pegarlo en https://github.com/settings/keys

# 4. Verificar
ssh -T git@luisdeimos
# Debe responder: Hi LuisDeimos! You've successfully authenticated...
```

Con eso, las URLs SSH del repo usan el alias:

```bash
git remote set-url origin git@luisdeimos:LuisDeimos/claude-seo.git
```

---

## Anexo B — Seguridad y permisos

Este fork aplica medidas de higiene que conviene no revertir:

- Todos los archivos bajo `~/.config/claude-seo/*.json` deben estar en
  `0600`. El instalador las pone al directorio (`0700`) y el script
  `google_auth.py` lo aplica al token tras escribirlo (FIX-1). Si por
  algo queda un archivo en `0664`:
  ```bash
  chmod 600 ~/.config/claude-seo/*.json
  ```
- `validate_url()` en `google_auth.py` resuelve DNS antes de validar
  (FIX-2). Nunca des bypass a esta función para "que acepte
  `cliente.local`" — es lo que evita SSRF.
- Nunca commitear archivos `.env`, `client_secret*.json`,
  `oauth-token.json`, `service_account*.json`. El `.gitignore` del
  upstream ya los excluye; verifica que siga así tras pulls.
- Al pushear, el workflow del fork usa tu alias SSH (`luisdeimos`) y los
  commits quedan con la identidad que hayas configurado en el repo
  (`git config user.name/user.email`).

---

*Fin de la guía.* Cualquier paso que no funcione exactamente como se
describe aquí, abre un issue en
https://github.com/LuisDeimos/claude-seo/issues con el comando exacto y
el output completo.
