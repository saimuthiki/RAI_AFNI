#!/usr/bin/env bash
# EvoHack 2026 FDE pod toolkit installer.
#
#   install.sh vault     clone/update every source repo into the skill vault and index it
#   install.sh project   copy the curated skill set into <repo>/.claude/skills   (default)
#   install.sh user      copy the curated skill set into ~/.claude/skills
#   install.sh plugins   register plugin marketplaces with the claude CLI
#   install.sh mcp       print / register the MCP servers the pod uses
#   install.sh gstack    install garrytan/gstack as a user-level skill pack (needs bun)
#   install.sh all       vault + project + plugins
#
# The vault lives at $SKILL_VAULT (default ~/.claude/skill-vault). Nothing in the vault
# is loaded by Claude until you enable it with skill.sh, so the 10k+ indexed skills cost
# no context.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
VAULT="${SKILL_VAULT:-$HOME/.claude/skill-vault}"
JOBS="${JOBS:-12}"

log() { printf '\033[1;36m[fde-toolkit]\033[0m %s\n' "$*"; }

vault_dir() { echo "$VAULT/$(echo "$1" | tr / _)"; }

cmd_vault() {
  mkdir -p "$VAULT"
  log "syncing $(grep -vc '^#' "$HERE/repos.tsv") repos into $VAULT"
  grep -v '^#' "$HERE/repos.tsv" | cut -f1 | xargs -P "$JOBS" -I{} bash -c '
    d="$0/$(echo {} | tr / _)"
    if [ -d "$d/.git" ]; then git -C "$d" pull -q --ff-only >/dev/null 2>&1 && echo "updated {}" || echo "kept {}"
    else git clone -q --depth 1 --filter=blob:limit=2m "https://github.com/{}.git" "$d" >/dev/null 2>&1 && echo "cloned {}" || echo "FAILED {}"
    fi' "$VAULT"
  python3 -I "$HERE/build_index.py" "$VAULT" "$HERE/skill-index.tsv"
}

copy_curated() {
  local dest="$1"
  mkdir -p "$dest"
  local n=0 missing=0
  while IFS=$'\t' read -r stage name repo path; do
    [[ -z "$stage" || "$stage" == \#* ]] && continue
    local src
    src="$(vault_dir "$repo")/$path"
    if [[ ! -f "$src/SKILL.md" ]]; then
      log "missing $name ($repo/$path) - run: install.sh vault"; missing=$((missing+1)); continue
    fi
    rm -rf "${dest:?}/$name"
    cp -R "$src" "$dest/$name"
    find "$dest/$name" -name '__pycache__' -prune -exec rm -rf {} +
    printf 'source: https://github.com/%s/tree/HEAD/%s\nstage: %s\ncommit: %s\n' \
      "$repo" "$path" "$stage" "$(git -C "$(vault_dir "$repo")" rev-parse --short HEAD 2>/dev/null || echo unknown)" \
      > "$dest/$name/.provenance"
    n=$((n+1))
  done < "$HERE/curated-skills.tsv"
  log "installed $n curated skills into $dest ($missing missing)"
}

cmd_project() { [[ -d "$VAULT" ]] || cmd_vault; copy_curated "$REPO_ROOT/.claude/skills"; }
cmd_user()    { [[ -d "$VAULT" ]] || cmd_vault; copy_curated "$HOME/.claude/skills"; }

cmd_plugins() {
  if ! command -v claude >/dev/null; then log "claude CLI not found; run these inside Claude Code instead:"; fi
  while IFS=$'\t' read -r market plugin; do
    [[ -z "$market" || "$market" == \#* ]] && continue
    if command -v claude >/dev/null; then
      claude plugin marketplace add "$market" >/dev/null 2>&1 || true
      [[ -n "$plugin" ]] && { claude plugin install "$plugin" >/dev/null 2>&1 && log "plugin $plugin" || log "skipped $plugin (install it from /plugin)"; }
    else
      echo "  /plugin marketplace add $market"; [[ -n "$plugin" ]] && echo "  /plugin install $plugin"
    fi
  done < "$HERE/plugins.tsv"
}

cmd_mcp() {
  log "project MCP servers are declared in $REPO_ROOT/.mcp.json (context7, playwright)."
  log "optional user-level servers (need accounts/keys):"
  cat <<'EOF'
  claude mcp add --scope user firecrawl -e FIRECRAWL_API_KEY=... -- npx -y firecrawl-mcp
  claude mcp add --scope user serena -- uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant
  claude mcp add --transport http --scope user github https://api.githubcopilot.com/mcp/ -H "Authorization: Bearer $GITHUB_PAT"
EOF
}

cmd_gstack() {
  command -v bun >/dev/null || { log "gstack needs bun: curl -fsSL https://bun.sh/install | bash"; exit 1; }
  local d="$HOME/.claude/skills/gstack"
  [[ -d "$d" ]] || git clone -q --depth 1 https://github.com/garrytan/gstack.git "$d"
  (cd "$d" && ./setup)
}

case "${1:-project}" in
  vault) cmd_vault ;;
  project) cmd_project ;;
  user) cmd_user ;;
  plugins) cmd_plugins ;;
  mcp) cmd_mcp ;;
  gstack) cmd_gstack ;;
  all) cmd_vault; cmd_project; cmd_plugins ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
