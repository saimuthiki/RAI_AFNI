# -*- coding: utf-8 -*-
"""
Turn a prompt list into regression-corpus records.

    python rai_platform/corpus/ingest.py harmdataset.xlsx --out seed.jsonl
    python rai_platform/corpus/ingest.py harmdataset.xlsx --report-only

Takes an `.xlsx` or `.csv` with a prompt column and an optional label column,
and emits one JSONL record per unique prompt, mapped to a tenet and to OWASP LLM
Top 10 ids.

It deliberately does NOT record a verdict. That is `baseline.py`'s job, because
a verdict has to be stamped with the commit and tier that produced it, and
mixing the two would let an un-stamped guess into the baseline.

Three properties worth knowing:

  * The original label is kept verbatim in `source_label`, always. Our mapping is
    a judgement and it will sometimes be wrong; discarding the evidence needed to
    correct it would be careless.
  * An unmapped label yields `tenet: null` and is COUNTED AND REPORTED, never
    silently bucketed into a default. A corpus that quietly files everything it
    does not understand under "Security" is worse than one that admits a gap.
  * Duplicate prompts collapse to one record, and the labels seen for them are
    merged. The observed dataset has 4,234 duplicate rows out of 15,084; keeping
    them would inflate every future pass rate by a third.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------- #
# Label -> (tenet, OWASP ids). Matched on a NORMALISED label: lowercased,       #
# punctuation to spaces, so `Violence`, `violence` and                          #
# `violence,aiding_and_abetting,incitement` all reach the same rule.            #
#                                                                              #
# Ordered most-specific first; the first substring hit wins. Substring rather   #
# than exact because the observed data packs several labels into one cell       #
# (1,467 rows carry a comma) and invents 616 distinct spellings.                #
# --------------------------------------------------------------------------- #
RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # ---- Security: OWASP LLM01 prompt injection, LLM06 agency ---------------
    ("prompt injection",        "Security", ("LLM01",)),
    ("jailbreak",               "Security", ("LLM01",)),
    ("ignore instructions",     "Security", ("LLM01",)),
    ("malware",                 "Security", ("LLM05",)),
    ("hack",                    "Security", ("LLM01",)),
    ("cyber",                   "Security", ("LLM01",)),
    ("phishing",                "Security", ("LLM01",)),
    ("secure computer",         "Security", ("LLM01",)),
    # ---- Privacy: LLM02 sensitive information disclosure -------------------
    ("privacy violation",       "Privacy", ("LLM02",)),
    ("privacy",                 "Privacy", ("LLM02",)),
    ("personal information",    "Privacy", ("LLM02",)),
    ("identity theft",          "Privacy", ("LLM02",)),
    ("doxx",                    "Privacy", ("LLM02",)),
    # ---- Content safety: LLM09 misinformation / harmful output -------------
    ("hate speech",             "Profanity / Content Safety", ("LLM09",)),
    ("hate crime",              "Profanity / Content Safety", ("LLM09",)),
    ("hate harassment",         "Profanity / Content Safety", ("LLM09",)),
    ("offensive language",      "Profanity / Content Safety", ("LLM09",)),
    ("harassment",              "Profanity / Content Safety", ("LLM09",)),
    ("sexually explicit",       "Profanity / Content Safety", ("LLM09",)),
    ("adult content",           "Profanity / Content Safety", ("LLM09",)),
    ("sexual content",          "Profanity / Content Safety", ("LLM09",)),
    ("pornography",             "Profanity / Content Safety", ("LLM09",)),
    ("child abuse",             "Profanity / Content Safety", ("LLM09",)),
    ("child sexual",            "Profanity / Content Safety", ("LLM09",)),
    ("self harm",               "Profanity / Content Safety", ("LLM09",)),
    ("suicide",                 "Profanity / Content Safety", ("LLM09",)),
    ("violence",                "Profanity / Content Safety", ("LLM09",)),
    ("terrorism",               "Profanity / Content Safety", ("LLM09",)),
    ("weapon",                  "Profanity / Content Safety", ("LLM09",)),
    ("physical harm",           "Profanity / Content Safety", ("LLM09",)),
    ("animal abuse",            "Profanity / Content Safety", ("LLM09",)),
    ("animal neglect",          "Profanity / Content Safety", ("LLM09",)),
    ("cockfighting",            "Profanity / Content Safety", ("LLM09",)),
    ("drug",                    "Profanity / Content Safety", ("LLM09",)),
    ("banned substance",        "Profanity / Content Safety", ("LLM09",)),
    ("alcohol",                 "Profanity / Content Safety", ("LLM09",)),
    ("smoking",                 "Profanity / Content Safety", ("LLM09",)),
    ("illegal goods",           "Profanity / Content Safety", ("LLM09",)),
    ("illegal activity",        "Profanity / Content Safety", ("LLM09",)),
    ("illegal drug",            "Profanity / Content Safety", ("LLM09",)),
    # ---- Fairness ----------------------------------------------------------
    ("discrimination",          "Fairness & Bias", ("LLM09",)),
    ("stereotype",              "Fairness & Bias", ("LLM09",)),
    ("injustice",               "Fairness & Bias", ("LLM09",)),
    ("racis",                   "Fairness & Bias", ("LLM09",)),
    ("sexis",                   "Fairness & Bias", ("LLM09",)),
    ("bias",                    "Fairness & Bias", ("LLM09",)),
    # ---- Hallucination / reliability: LLM09 --------------------------------
    ("misinformation",          "Hallucination / Reliability", ("LLM09",)),
    ("disinformation",          "Hallucination / Reliability", ("LLM09",)),
    ("deception",               "Hallucination / Reliability", ("LLM09",)),
    ("conspiracy",              "Hallucination / Reliability", ("LLM09",)),
    ("fake news",               "Hallucination / Reliability", ("LLM09",)),
    # ---- Economic / other crime: no clean tenet, tagged honestly -----------
    ("financial crime",         "Profanity / Content Safety", ("LLM09",)),
    ("property crime",          "Profanity / Content Safety", ("LLM09",)),
    ("economic harm",           "Profanity / Content Safety", ("LLM09",)),
    ("fraud",                   "Profanity / Content Safety", ("LLM09",)),
    ("ponzi",                   "Profanity / Content Safety", ("LLM09",)),
    ("gambling",                "Profanity / Content Safety", ("LLM09",)),
    ("theft",                   "Profanity / Content Safety", ("LLM09",)),
    ("trafficking",             "Profanity / Content Safety", ("LLM09",)),
    ("unethical",               "Profanity / Content Safety", ("LLM09",)),
    ("crime",                   "Profanity / Content Safety", ("LLM09",)),
    ("politics",                "Profanity / Content Safety", ("LLM09",)),
    ("controversial",           "Profanity / Content Safety", ("LLM09",)),
)

OWASP_TITLES = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM09": "Misinformation",
}


def normalise(label: str | None) -> str:
    if not label:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(label).lower()).strip()


def classify(label: str | None) -> tuple[str | None, list[str], str | None]:
    """(tenet, owasp ids, matched rule). All three None/empty when unmapped."""
    norm = normalise(label)
    if not norm:
        return None, [], None
    for needle, tenet, owasp in RULES:
        if needle in norm:
            return tenet, list(owasp), needle
    return None, [], None


def record_id(prompt: str) -> str:
    """Derived from the prompt, so re-ingesting the same source is idempotent and
    two people ingesting independently agree on ids."""
    return "afni-corpus-" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def read_rows(path: Path) -> list[tuple[str, str | None]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            sys.exit("openpyxl is needed for .xlsx input:  pip install openpyxl")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        out = []
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            header = None
            for row in ws.iter_rows(values_only=True):
                if header is None:
                    header = [normalise(c) for c in row]
                    continue
                if not row or not row[0]:
                    continue
                out.append((str(row[0]).strip(),
                            str(row[1]).strip() if len(row) > 1 and row[1] else None))
        return out
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return [(r[0].strip(), r[1].strip() if len(r) > 1 and r[1] else None)
                for r in reader if r and r[0].strip()]


def build(path: Path, source_ref: str):
    rows = read_rows(path)
    merged: dict[str, dict] = {}
    unmapped = Counter()

    for prompt, label in rows:
        rid = record_id(prompt)
        tenet, owasp, rule = classify(label)
        if label and tenet is None:
            unmapped[str(label)] += 1
        if rid in merged:
            entry = merged[rid]
            if label and label not in entry["source_label"]:
                entry["source_label"].append(label)
            # A duplicate that carries a label upgrades one that did not.
            if entry["tenet"] is None and tenet is not None:
                entry["tenet"], entry["owasp"] = tenet, owasp
                entry["harm_label"] = rule
            entry["_seen"] += 1
            continue
        merged[rid] = {
            "id": rid,
            "prompt": prompt,
            "direction": "input",
            "tenet": tenet,
            "owasp": owasp,
            "harm_label": rule,
            "source_label": [label] if label else [],
            "origin": {"tool": path.name, "tool_version": source_ref,
                       "generated_at": None, "seed": None},
            "expected": None,          # baseline.py fills this, stamped
            "target_complied": None,   # a red-team run fills this
            "notes": "",
            "_seen": 1,
        }

    records = list(merged.values())
    stats = {
        "rows_in": len(rows),
        "unique_prompts": len(records),
        "duplicates_collapsed": len(rows) - len(records),
        "mapped_to_a_tenet": sum(1 for r in records if r["tenet"]),
        "no_label_in_source": sum(1 for r in records if not r["source_label"]),
        "labelled_but_unmapped": sum(
            1 for r in records if r["source_label"] and not r["tenet"]),
        "by_tenet": Counter(r["tenet"] or "(unmapped)" for r in records),
        "by_owasp": Counter(o for r in records for o in r["owasp"]),
        "top_unmapped_labels": unmapped.most_common(15),
    }
    return records, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("source", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--source-ref", default="unknown",
                    help="provenance, e.g. owner/repo@sha")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)

    records, stats = build(args.source, args.source_ref)

    print(f"source                 {args.source}")
    print(f"rows in                {stats['rows_in']:,}")
    print(f"unique prompts         {stats['unique_prompts']:,}")
    print(f"duplicates collapsed   {stats['duplicates_collapsed']:,}")
    print(f"mapped to a tenet      {stats['mapped_to_a_tenet']:,}")
    print(f"no label in source     {stats['no_label_in_source']:,}")
    print(f"labelled but unmapped  {stats['labelled_but_unmapped']:,}")
    print("\nby tenet")
    for tenet, n in stats["by_tenet"].most_common():
        print(f"  {tenet:34s} {n:6,}")
    print("\nby OWASP LLM Top 10")
    for owasp, n in stats["by_owasp"].most_common():
        print(f"  {owasp}  {OWASP_TITLES.get(owasp,'?'):36s} {n:6,}")
    if stats["top_unmapped_labels"]:
        print("\nlabels present in the source that NO rule matched")
        print("(reported rather than defaulted - add a rule or accept the gap)")
        for label, n in stats["top_unmapped_labels"]:
            print(f"  {label[:52]:54s} {n:5,}")

    if args.report_only or args.out is None:
        print("\n(no file written)")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for r in sorted(records, key=lambda x: x["id"]):
            r.pop("_seen", None)
            handle.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(records):,} records to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
