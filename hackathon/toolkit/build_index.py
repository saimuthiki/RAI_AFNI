#!/usr/bin/env python3
"""Index every SKILL.md, agent and command under a vault of cloned repos.

Usage: build_index.py <vault_dir> <out.tsv>
Columns: kind, name, source_repo, rel_path, description
Duplicates (same kind+name+description) are collapsed to the first source.
"""
import os
import re
import sys

SKIP_DIRS = {"node_modules", ".git", "i18n", "zh-CN", "ja-JP", "ko-KR", "es", "de", "fr", "pt-BR"}
MIRROR_DIRS = {".cursor", ".gemini", ".codex", ".kiro", ".opencode", ".pi", ".factory",
               ".hermes", ".continue", ".codebuddy", ".mastracode", ".openclaw", ".agents", ".windsurf"}


def frontmatter(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(6000)
    except OSError:
        return {}
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    meta, key = {}, None
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            meta[key] = val.strip("'\"") if val not in ("|", ">", "|-", ">-") else ""
        elif key and line.startswith((" ", "\t")) and key in ("description",):
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta


def clean(s):
    return re.sub(r"\s+", " ", s or "").replace("\t", " ")[:300]


def main(vault, out):
    rows, seen = [], set()
    for repo in sorted(os.listdir(vault)):
        root = os.path.join(vault, repo)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d not in MIRROR_DIRS]
            rel = os.path.relpath(dirpath, root)
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                kind = None
                if fn == "SKILL.md":
                    kind = "skill"
                elif fn.endswith(".md") and os.path.basename(dirpath) == "agents":
                    kind = "agent"
                elif fn.endswith(".md") and os.path.basename(dirpath) == "commands":
                    kind = "command"
                if not kind:
                    continue
                meta = frontmatter(p)
                name = meta.get("name") or (os.path.basename(dirpath) if kind == "skill" else fn[:-3])
                desc = clean(meta.get("description", ""))
                if kind != "skill" and not desc:
                    continue  # READMEs and notes inside agents/ or commands/
                key = (kind, name.lower(), desc.lower()[:120])
                if key in seen:
                    continue
                seen.add(key)
                relp = os.path.join(rel, fn if kind != "skill" else "").rstrip("/")
                rows.append((kind, clean(name), repo, relp if kind != "skill" else rel, desc))
    with open(out, "w", encoding="utf-8") as f:
        f.write("kind\tname\tsource_repo\trel_path\tdescription\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    counts = {}
    for r in rows:
        counts[r[0]] = counts.get(r[0], 0) + 1
    print(f"indexed {len(rows)} unique entries: {counts}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
