#!/usr/bin/env python3
"""Merge the toolkit's MCP servers and plugin marketplaces into the project config.

Run from the repo root after reviewing config/*.json:  python3 hackathon/toolkit/config/apply.py
Existing keys are kept; only missing servers, marketplaces and allow rules are added.
"""
import json
import pathlib

here = pathlib.Path(__file__).parent
root = here.parents[2]


def merge(target, additions):
    path = root / target
    data = json.loads(path.read_text()) if path.exists() else {}
    for key, val in additions.items():
        if isinstance(val, dict):
            data.setdefault(key, {})
            for k, v in val.items():
                if k == "allow":
                    data[key].setdefault("allow", [])
                    data[key]["allow"] += [r for r in v if r not in data[key]["allow"]]
                else:
                    data[key].setdefault(k, v)
        else:
            data.setdefault(key, val)
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"updated {target}")


merge(".mcp.json", json.loads((here / "mcp.servers.json").read_text()))
merge(".claude/settings.json", json.loads((here / "settings.additions.json").read_text()))
