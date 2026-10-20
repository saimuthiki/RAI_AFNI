#!/usr/bin/env bash
# Search the 10k-entry skill index and switch vault skills on/off for this project.
#
#   skill.sh find <words...>        rank index rows matching all words (name/description)
#   skill.sh show <name>            print the SKILL.md of a vault skill
#   skill.sh enable <name> [repo]   copy a vault skill into .claude/skills (repo disambiguates)
#   skill.sh disable <name>         remove it from .claude/skills
#   skill.sh active                 list skills currently active in this project
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
VAULT="${SKILL_VAULT:-$HOME/.claude/skill-vault}"
INDEX="$HERE/skill-index.tsv"

locate() {  # name [repo] -> "repo<TAB>rel_path"
  awk -F'\t' -v n="$1" -v r="${2:-}" '$1=="skill" && tolower($2)==tolower(n) && (r=="" || index($3, r)) {print $3"\t"$4; exit}' "$INDEX"
}

case "${1:-}" in
  find)
    shift; q="$*"
    python3 -I - "$INDEX" "$q" <<'PY'
import sys
idx, q = sys.argv[1], sys.argv[2].lower().split()
hits = []
for line in open(idx, encoding="utf-8").readlines()[1:]:
    kind, name, repo, path, desc = (line.rstrip("\n").split("\t") + [""] * 5)[:5]
    hay = f"{name} {desc}".lower()
    if all(w in hay for w in q):
        score = sum(3 for w in q if w in name.lower()) + (repo.startswith(("anthropics", "obra", "addyosmani", "mattpocock")) and 2)
        hits.append((score, kind, name, repo, desc))
for s, kind, name, repo, desc in sorted(hits, key=lambda h: -h[0])[:40]:
    print(f"{kind:7} {name:38.38} {repo:38.38} {desc[:90]}")
print(f"-- {len(hits)} matches")
PY
    ;;
  show)
    loc="$(locate "$2" "${3:-}")"; [[ -n "$loc" ]] || { echo "no skill named $2"; exit 1; }
    cat "$VAULT/${loc%%$'\t'*}/${loc#*$'\t'}/SKILL.md" ;;
  enable)
    loc="$(locate "$2" "${3:-}")"; [[ -n "$loc" ]] || { echo "no skill named $2"; exit 1; }
    src="$VAULT/${loc%%$'\t'*}/${loc#*$'\t'}"
    [[ -d "$src" ]] || { echo "vault missing $src - run install.sh vault"; exit 1; }
    rm -rf "$REPO_ROOT/.claude/skills/$2"; cp -R "$src" "$REPO_ROOT/.claude/skills/$2"
    printf 'source: %s\nstage: on-demand\n' "${loc/$'\t'//}" > "$REPO_ROOT/.claude/skills/$2/.provenance"
    echo "enabled $2 from ${loc%%$'\t'*} (restart or /reload to pick it up)" ;;
  disable)
    rm -rf "$REPO_ROOT/.claude/skills/${2:?name}"; echo "disabled $2" ;;
  active)
    for d in "$REPO_ROOT"/.claude/skills/*/; do n=$(basename "$d"); s=$(grep -m1 "^stage:" "$d/.provenance" 2>/dev/null | cut -d" " -f2 || true); printf '%-12s %s\n' "${s:-local}" "$n"; done | sort ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
