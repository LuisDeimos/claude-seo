#!/usr/bin/env bash
# Claude SEO — Kernel Soluciones installer
#
# Fork-aware installer that:
#   1. Clones from LuisDeimos/claude-seo (this fork), NOT the upstream.
#   2. Skips paid/optional extensions (dataforseo, banana, firecrawl).
#   3. Asks before downloading Playwright's Chromium (~200MB).
#   4. Sets 0700 permissions on ~/.config/claude-seo/ for credential hygiene.
#
# Safe to re-run. No sudo, no writes outside $HOME.

set -euo pipefail

main() {
    SKILL_DIR="${HOME}/.claude/skills/seo"
    AGENT_DIR="${HOME}/.claude/agents"
    CONFIG_DIR="${HOME}/.config/claude-seo"

    # Our fork, not the upstream. Override with CLAUDE_SEO_REPO if needed.
    REPO_URL="${CLAUDE_SEO_REPO:-https://github.com/LuisDeimos/claude-seo}"
    # Default to the main branch, which carries all kernel features +
    # fixes. Override with CLAUDE_SEO_REF=v0.1.0 (or another tag) to pin
    # to a specific release instead of following main.
    REPO_REF="${CLAUDE_SEO_REF:-main}"

    # Extensions to SKIP (directory names under extensions/). All paid or
    # undesired for the free-only MVP.
    SKIP_EXTENSIONS=("dataforseo" "banana" "firecrawl")
    # Skill directories sourced from extensions/ that must also be skipped
    # if they were ever copied under skills/.
    SKIP_SKILLS=("seo-dataforseo" "seo-image-gen")

    echo "════════════════════════════════════════════════"
    echo "║  Claude SEO — Kernel Soluciones Installer    ║"
    echo "║  Fork: ${REPO_URL}"
    echo "║  Ref:  ${REPO_REF}"
    echo "════════════════════════════════════════════════"
    echo ""

    # Prerequisites
    command -v python3 >/dev/null 2>&1 || { echo "✗ python3 required"; exit 1; }
    command -v git >/dev/null 2>&1     || { echo "✗ git required"; exit 1; }

    PYTHON_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
    if [ "${PYTHON_OK}" != "1" ]; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        echo "✗ Python 3.10+ required, found ${PYTHON_VERSION}"
        exit 1
    fi

    # Destination directories
    mkdir -p "${SKILL_DIR}" "${AGENT_DIR}" "${CONFIG_DIR}"
    chmod 700 "${CONFIG_DIR}" 2>/dev/null || true

    # Clone our fork to a temp directory
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf ${TEMP_DIR}" EXIT

    echo "↓ Cloning ${REPO_URL}#${REPO_REF} ..."
    git clone --depth 1 --branch "${REPO_REF}" "${REPO_URL}" "${TEMP_DIR}/claude-seo"

    SRC="${TEMP_DIR}/claude-seo"

    # Helper: is this skill/extension in the skip list?
    is_skipped_skill() {
        local name="$1"
        for s in "${SKIP_SKILLS[@]}"; do
            [ "$s" = "$name" ] && return 0
        done
        return 1
    }

    # Copy main skill assets (content of skills/seo/)
    echo "→ Installing main skill (seo/)..."
    cp -r "${SRC}/skills/seo/"* "${SKILL_DIR}/"

    # Copy sub-skills, skipping the ones bound to paid extensions
    echo "→ Installing sub-skills..."
    local installed_skills=0 skipped_skills=0
    for skill_path in "${SRC}/skills"/*/; do
        skill_name=$(basename "${skill_path}")
        [ "${skill_name}" = "seo" ] && continue  # already installed above
        if is_skipped_skill "${skill_name}"; then
            echo "  - skipped ${skill_name} (paid extension)"
            skipped_skills=$((skipped_skills + 1))
            continue
        fi
        target="${HOME}/.claude/skills/${skill_name}"
        mkdir -p "${target}"
        cp -r "${skill_path}"* "${target}/"
        installed_skills=$((installed_skills + 1))
    done
    echo "  ${installed_skills} installed, ${skipped_skills} skipped"

    # Schema + pdf assets
    for sub in schema pdf; do
        if [ -d "${SRC}/${sub}" ]; then
            mkdir -p "${SKILL_DIR}/${sub}"
            cp -r "${SRC}/${sub}/"* "${SKILL_DIR}/${sub}/"
        fi
    done

    # Subagents
    echo "→ Installing subagents..."
    cp -r "${SRC}/agents/"*.md "${AGENT_DIR}/" 2>/dev/null || true

    # Shared scripts
    if [ -d "${SRC}/scripts" ]; then
        mkdir -p "${SKILL_DIR}/scripts"
        cp -r "${SRC}/scripts/"* "${SKILL_DIR}/scripts/"
    fi

    # Hooks (opt-in: files are copied but NOT wired into ~/.claude/settings.json
    # automatically — user must add them manually if they want them active)
    if [ -d "${SRC}/hooks" ]; then
        mkdir -p "${SKILL_DIR}/hooks"
        cp -r "${SRC}/hooks/"* "${SKILL_DIR}/hooks/"
        chmod +x "${SKILL_DIR}/hooks/"*.py 2>/dev/null || true
    fi

    # Extensions: ALL skipped per MVP policy (free-only)
    echo "→ Skipping all paid extensions: ${SKIP_EXTENSIONS[*]}"

    # Copy requirements.txt so the user can reinstall deps later
    cp "${SRC}/requirements.txt" "${SKILL_DIR}/requirements.txt" 2>/dev/null || true

    # Python dependencies in isolated venv
    echo "→ Installing Python dependencies in venv..."
    VENV_DIR="${SKILL_DIR}/.venv"
    if python3 -m venv "${VENV_DIR}" 2>/dev/null; then
        if "${VENV_DIR}/bin/pip" install --quiet --upgrade pip 2>/dev/null && \
           "${VENV_DIR}/bin/pip" install --quiet -r "${SKILL_DIR}/requirements.txt"; then
            echo "  ✓ Dependencies installed in ${VENV_DIR}"
        else
            echo "  ⚠ pip install failed. Retry manually:"
            echo "     ${VENV_DIR}/bin/pip install -r ${SKILL_DIR}/requirements.txt"
        fi
    else
        echo "  ⚠ Could not create venv. Fall back to system pip:"
        echo "     python3 -m pip install --user -r ${SKILL_DIR}/requirements.txt"
    fi

    # Playwright Chromium: ask before downloading (~200MB)
    echo ""
    if [ -t 0 ] && [ -z "${CLAUDE_SEO_AUTO_PLAYWRIGHT:-}" ]; then
        read -r -p "Install Playwright Chromium (~200MB) for screenshot analysis? [y/N] " reply
    else
        reply="${CLAUDE_SEO_AUTO_PLAYWRIGHT:-N}"
    fi
    case "${reply}" in
        [yY]|[yY][eE][sS])
            if [ -x "${VENV_DIR}/bin/python" ]; then
                "${VENV_DIR}/bin/python" -m playwright install chromium || \
                    echo "  ⚠ Playwright install failed. Visual analysis will use WebFetch fallback."
            else
                python3 -m playwright install chromium || \
                    echo "  ⚠ Playwright install failed."
            fi
            ;;
        *)
            echo "  ↷ Skipped Playwright download. Visual analysis will use WebFetch fallback."
            echo "     To install later: ${VENV_DIR}/bin/python -m playwright install chromium"
            ;;
    esac

    echo ""
    echo "✓ Claude SEO (kernel-soluciones) installed."
    echo ""
    echo "Next steps:"
    echo "  1. Configure Google API credentials:"
    echo "       python3 ${SKILL_DIR}/scripts/google_auth.py --setup"
    echo "  2. Start Claude Code in any directory:"
    echo "       claude"
    echo "  3. Try an audit:"
    echo "       /seo audit https://example.com"
    echo ""
    echo "Config directory: ${CONFIG_DIR} (permissions 0700)"
    echo "Skill directory:  ${SKILL_DIR}"
}

main "$@"
