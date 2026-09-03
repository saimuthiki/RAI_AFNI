# -*- coding: utf-8 -*-
"""
Record what the gateway decides for each corpus record, and compare later.

    # take a baseline over a SAMPLE, which is the normal case
    python rai_platform/corpus/baseline.py corpus.jsonl --limit 200 --write

    # check the corpus against the current build and report drift
    python rai_platform/corpus/baseline.py corpus.jsonl --limit 500 --check

    # stratified: N per tenet rather than N from the top of the file
    python rai_platform/corpus/baseline.py corpus.jsonl --per-tenet 50 --check

`--limit` exists because the corpus is 11,369 records and a Stage-2 pass costs
1-3 s each on CPU. Ten thousand prompts is nine hours and a warm laptop; nobody
runs that per commit. So the sample size is a first-class argument everywhere -
here, in the API, and in the console.

Sampling is DETERMINISTIC by default (`--seed`, default 0). A random sample would
make every run's pass rate incomparable to the last, which defeats the purpose of
a regression corpus. Pass `--seed -1` for a genuinely random draw when you want
to explore beyond the fixed sample.

`--check` never rewrites the baseline. It reports drift and exits non-zero, and a
human decides whether a change is an improvement or a regression. A tool that
silently updates its own expectations cannot detect anything.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from afni_rai.cascade.engine import Cascade                      # noqa: E402
from afni_rai.cascade.rail import Stage                          # noqa: E402
from afni_rai.cli import load_tenets                             # noqa: E402
from afni_rai.contract.models import (                           # noqa: E402
    EventKind, GuardEvent, LLMProtocol,
)


def build_commit() -> str:
    try:
        from afni_rai.build_info import collect
        return collect().short
    except Exception:  # noqa: BLE001
        return "unknown"


def tier_label(rails) -> str:
    """Which tiers can actually judge on THIS host.

    Stamped into every baseline because 7 of 32 rails cannot run without model
    weights, so the same prompt legitimately yields different verdicts on a bare
    host and a provisioned one. Comparing across tiers produces confident
    nonsense, so `--check` refuses to.
    """
    def can(rail):
        for attr in ("dependency_available", "available", "configured"):
            probe = getattr(rail, attr, None)
            if callable(probe):
                try:
                    return bool(probe())
                except Exception:  # noqa: BLE001
                    return False
        return True

    live = {int(r.stage) for r in rails if can(r)}
    if 3 in live:
        return "all_stages"
    if 2 in live:
        return "stage_1_and_2"
    return "stage_1_only"


def event_for(record: dict) -> GuardEvent:
    text = record["prompt"]
    if record.get("direction") == "output":
        return GuardEvent(
            kind=EventKind.RESPONSE, step_id=record["id"], agent_id="corpus",
            agent_type="batch", agent_workspace="afni", agent_user="corpus",
            llm_protocol=LLMProtocol.OPENAI_CHAT,
            payload={"choices": [{"message": {"role": "assistant",
                                              "content": text}}]})
    return GuardEvent(
        kind=EventKind.REQUEST, step_id=record["id"], agent_id="corpus",
        agent_type="batch", agent_workspace="afni", agent_user="corpus",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload={"messages": [{"role": "user", "content": text}]})


def judge(cascade, record: dict) -> dict:
    outcome = cascade.evaluate(event_for(record))
    verdict = outcome.verdict
    blocking = [f for f in verdict.findings
                if f.action is not None and f.action.value == "block"]
    top = blocking[0] if blocking else None
    return {
        "decision": verdict.decision.value,
        "blocking_rail": top.detector if top else None,
        "blocking_category": top.category if top else None,
        "findings": len(verdict.findings),
        "unjudged": bool(verdict.unjudged),
        "stages_run": outcome.stages_run,
    }


def sample(records: list[dict], limit: int | None, per_tenet: int | None,
           seed: int) -> list[dict]:
    if per_tenet:
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            buckets[r.get("tenet") or "(unmapped)"].append(r)
        out = []
        for key in sorted(buckets):
            group = sorted(buckets[key], key=lambda r: r["id"])
            if seed >= 0:
                random.Random(seed).shuffle(group)
            else:
                random.shuffle(group)
            out.extend(group[:per_tenet])
        return out
    ordered = sorted(records, key=lambda r: r["id"])
    if seed >= 0:
        random.Random(seed).shuffle(ordered)
    else:
        random.shuffle(ordered)
    return ordered if limit is None else ordered[:limit]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--limit", type=int, default=200,
                    help="how many records to run (default 200). The corpus is "
                         "far larger than anyone wants to run per commit.")
    ap.add_argument("--per-tenet", type=int, default=None,
                    help="stratified sample: N per tenet, instead of --limit")
    ap.add_argument("--seed", type=int, default=0,
                    help="deterministic sample (default 0). -1 for random.")
    ap.add_argument("--stage-1-only", action="store_true",
                    help="mount only Stage-1 rails: fast, and the only sane "
                         "choice for a large sample on CPU")
    ap.add_argument("--write", action="store_true",
                    help="record the verdicts as the baseline")
    ap.add_argument("--check", action="store_true",
                    help="compare against the recorded baseline; exit 1 on drift")
    args = ap.parse_args(argv)

    if args.write and args.check:
        sys.exit("--write and --check are mutually exclusive: a tool that "
                 "updates its own expectations cannot detect drift")

    records = [json.loads(line) for line in
               args.corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
    rails, _, problems = load_tenets()
    if problems:
        sys.exit(f"tenets failed to load, refusing to baseline: {problems}")
    if args.stage_1_only:
        rails = [r for r in rails if r.stage is Stage.STAGE_1]
    cascade = Cascade(rails)
    tier = "stage_1_only" if args.stage_1_only else tier_label(rails)
    commit = build_commit()

    chosen = sample(records, args.limit, args.per_tenet, args.seed)
    print(f"corpus      {args.corpus}  ({len(records):,} records)")
    print(f"sample      {len(chosen):,}"
          + (f"  ({args.per_tenet} per tenet)" if args.per_tenet
             else f"  (--limit {args.limit})")
          + f"  seed={args.seed}")
    print(f"build       {commit}   tier={tier}")
    print()

    started = time.perf_counter()
    results, drift = {}, []
    for i, record in enumerate(chosen, start=1):
        actual = judge(cascade, record)
        results[record["id"]] = actual
        expected = record.get("expected")
        if args.check and expected:
            if expected.get("tier") != tier:
                drift.append((record["id"], "TIER MISMATCH",
                              expected.get("tier"), tier))
            elif expected.get("decision") != actual["decision"]:
                drift.append((record["id"], record["prompt"][:48],
                              expected["decision"], actual["decision"]))
        if i % 500 == 0:
            print(f"  ... {i:,}/{len(chosen):,}")
    elapsed = time.perf_counter() - started

    counts = Counter(r["decision"] for r in results.values())
    print(f"decisions   " + "  ".join(f"{k}={v:,}" for k, v in counts.most_common()))
    print(f"blocked by  " + ", ".join(
        f"{rail}={n}" for rail, n in Counter(
            r["blocking_rail"] for r in results.values()
            if r["blocking_rail"]).most_common(6)) or "blocked by  (nothing)")
    print(f"elapsed     {elapsed:.1f}s  ({elapsed / max(len(chosen),1) * 1000:.1f} ms/record)")

    if args.check:
        checked = sum(1 for r in chosen if r.get("expected"))
        print(f"\nchecked     {checked:,} of {len(chosen):,} had a baseline")
        if not drift:
            print("drift       none")
            return 0
        print(f"drift       {len(drift)} record(s) changed\n")
        for rid, prompt, was, now in drift[:40]:
            print(f"  {rid}  {was} -> {now}   {prompt}")
        if len(drift) > 40:
            print(f"  ... and {len(drift) - 40} more")
        print("\nA changed verdict is not automatically a regression. Read them, "
              "then re-run with --write if the new behaviour is correct.")
        return 1

    if not args.write:
        print("\n(no baseline written - pass --write)")
        return 0

    stamp = {"recorded_by": f"afni-rai {commit}",
             "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "tier": tier}
    written = 0
    for record in records:
        actual = results.get(record["id"])
        if actual is None:
            continue
        record["expected"] = {**actual, **stamp}
        written += 1
    with args.corpus.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\nwrote a baseline for {written:,} record(s) to {args.corpus}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
