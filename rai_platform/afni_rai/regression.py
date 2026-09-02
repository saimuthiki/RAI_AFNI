# -*- coding: utf-8 -*-
"""
Run a CONFIGURABLE SAMPLE of the regression corpus through the cascade.

The corpus is 11,369 records. A Stage-2 pass costs 1-3 s each on CPU, so the
whole corpus is roughly nine hours of compute and a hot laptop. Nobody runs that
per commit, and nobody runs it at all from a browser tab. So the sample size is
a first-class, required-to-think-about argument in every surface that can start
a run - the CLI (`corpus/baseline.py --limit`), the API
(`POST /v1/corpus/run`) and the console - and all three call the sampler here so
a run means the same thing wherever it was started from.

Two limits are deliberately not negotiable from the request:

`MAX_SAMPLE` (default 500, `AFNI_CORPUS_MAX_SAMPLE`) caps one run. A caller who
asks for 11,369 gets a 422 naming the cap, not a request that holds a worker for
an hour. The cap is server-side because the person who sizes the box is not the
person clicking the button.

Stage 3 sends text to a paid third-party judge. `corpus/WARNING.md` forbids that
for this corpus - these are 11,369 genuinely harmful prompts and shipping them to
an external API is a disclosure, not a test. So a run is capped at Stage 2 unless
`AFNI_CORPUS_ALLOW_CLOUD` is set on the server, which is a deployment decision
and not a checkbox in the UI.

Everything here is import-light on purpose: `summary()` reads the corpus and
counts it without loading a single rail, so the console can render the picker on
a bare host with no model weights at all.
"""
from __future__ import annotations

import json
import os
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

# rai_platform/afni_rai/regression.py -> rai_platform/
_PLATFORM = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = _PLATFORM / "corpus" / "harm-intents.jsonl"

#: One run's ceiling. See the module docstring: this is a capacity decision made
#: by whoever runs the server, not by whoever sends the request.
MAX_SAMPLE_DEFAULT = 500

#: How much of a corpus prompt is echoed back. The full text is available under
#: the same `AFNI_REVEAL_SUBJECT` flag that governs matched values elsewhere,
#: because the server - not the caller - chose these prompts, so echoing them in
#: full is disclosure of corpus content rather than a reply to the caller's own
#: input. A short preview keeps a demo legible; the `id` is always complete, and
#: `corpus/WARNING.md` asks people to cite the id rather than paste the text.
PREVIEW_CHARS = 120

UNMAPPED = "(unmapped)"


def corpus_path() -> Path:
    override = os.environ.get("AFNI_CORPUS_PATH")
    return Path(override).expanduser() if override else DEFAULT_CORPUS


def max_sample() -> int:
    raw = os.environ.get("AFNI_CORPUS_MAX_SAMPLE")
    if not raw:
        return MAX_SAMPLE_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        return MAX_SAMPLE_DEFAULT
    return value if value > 0 else MAX_SAMPLE_DEFAULT


def cloud_allowed() -> bool:
    return os.environ.get("AFNI_CORPUS_ALLOW_CLOUD", "").strip().lower() in {
        "1", "true", "yes", "on"}


def reveal_prompts() -> bool:
    return os.environ.get("AFNI_REVEAL_SUBJECT", "").strip().lower() in {
        "1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# Loading                                                                     #
# --------------------------------------------------------------------------- #
_CACHE: dict[str, tuple[float, int, list[dict[str, Any]]]] = {}


def load(path: Path | None = None) -> list[dict[str, Any]]:
    """Parse the corpus, cached on (path, mtime, size).

    6.1 MB of JSONL is ~200 ms to parse. Doing that per request would make the
    endpoint's own overhead comparable to a Stage-1 run over 200 records, and the
    corpus changes only when someone regenerates it - so cache it, but key the
    cache on mtime AND size so a regenerated corpus is picked up without a
    restart. Same-second rewrites of an identical length are the one case this
    misses, and a stale read there is a re-run, not a wrong verdict.
    """
    path = path or corpus_path()
    if not path.exists():
        raise FileNotFoundError(
            f"corpus not found at {path}. Generate it with "
            f"`python rai_platform/corpus/ingest.py` or point "
            f"AFNI_CORPUS_PATH at an existing JSONL file.")
    stat = path.stat()
    key = str(path)
    hit = _CACHE.get(key)
    if hit and hit[0] == stat.st_mtime and hit[1] == stat.st_size:
        return hit[2]
    records = [json.loads(line) for line
               in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    _CACHE[key] = (stat.st_mtime, stat.st_size, records)
    return records


def summary(path: Path | None = None) -> dict[str, Any]:
    """Counts for the picker: what can be sampled, and how much of it.

    Deliberately loads no rails. A bare host with no model weights still needs to
    render this, and `tenets` here is what the CORPUS holds - not what the
    platform can judge.
    """
    records = load(path)
    tenets: Counter[str] = Counter()
    owasp: Counter[str] = Counter()
    direction: Counter[str] = Counter()
    baselined = 0
    for record in records:
        tenets[record.get("tenet") or UNMAPPED] += 1
        for code in record.get("owasp") or []:
            owasp[code] += 1
        direction[record.get("direction") or "input"] += 1
        if record.get("expected"):
            baselined += 1
    return {
        "path": str(path or corpus_path()),
        "records": len(records),
        "baselined": baselined,
        "max_sample": max_sample(),
        "cloud_allowed": cloud_allowed(),
        "tenets": [{"tenet": k, "records": v} for k, v in
                   sorted(tenets.items(), key=lambda kv: (-kv[1], kv[0]))],
        "owasp": [{"code": k, "records": v} for k, v in sorted(owasp.items())],
        "directions": [{"direction": k, "records": v} for k, v
                       in sorted(direction.items())],
    }


# --------------------------------------------------------------------------- #
# Selecting                                                                   #
# --------------------------------------------------------------------------- #
class SampleTooLarge(ValueError):
    """Asked for more records than one run is allowed to hold."""


@dataclass(frozen=True)
class Selection:
    """What to run. Every field has a defensible default so `Selection()` is a
    sane 100-record deterministic sample rather than an accident."""

    limit: int = 100
    per_tenet: int | None = None
    tenet: str | None = None
    owasp: str | None = None
    direction: str | None = None
    seed: int = 0
    max_stage: int = 2

    def describe(self) -> str:
        parts = [f"{self.per_tenet} per tenet" if self.per_tenet
                 else f"limit {self.limit}"]
        if self.tenet:
            parts.append(f"tenet={self.tenet}")
        if self.owasp:
            parts.append(f"owasp={self.owasp}")
        if self.direction:
            parts.append(f"direction={self.direction}")
        parts.append("random" if self.seed < 0 else f"seed={self.seed}")
        parts.append(f"max stage {self.max_stage}")
        return ", ".join(parts)


def _filter(records: list[dict[str, Any]], sel: Selection) -> list[dict[str, Any]]:
    out = records
    if sel.tenet:
        want = sel.tenet
        out = [r for r in out
               if (r.get("tenet") or UNMAPPED) == want]
    if sel.owasp:
        code = sel.owasp.upper()
        out = [r for r in out if code in (r.get("owasp") or [])]
    if sel.direction:
        out = [r for r in out if (r.get("direction") or "input") == sel.direction]
    return out


def _shuffled(group: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Sort by id first, THEN shuffle.

    Sorting first is what makes `seed=0` mean the same sample on every machine:
    the corpus file's line order is an artefact of how it was generated, so
    shuffling it directly would make a "deterministic" sample depend on the
    ingest run. A regression corpus whose sample moves when you regenerate it
    cannot detect a regression.
    """
    ordered = sorted(group, key=lambda r: r["id"])
    if seed >= 0:
        random.Random(seed).shuffle(ordered)
    else:
        random.shuffle(ordered)
    return ordered


def select(records: list[dict[str, Any]], sel: Selection,
           cap: int | None = None) -> list[dict[str, Any]]:
    """Filter, then sample. Raises `SampleTooLarge` above the cap.

    The cap is checked against the size of the sample that would be RETURNED,
    not against the requested limit, so `--limit 5000` over a tenet holding 60
    records is fine and does not need a smaller number typed in.
    """
    cap = max_sample() if cap is None else cap
    pool = _filter(records, sel)
    if sel.per_tenet:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in pool:
            buckets[record.get("tenet") or UNMAPPED].append(record)
        chosen: list[dict[str, Any]] = []
        for key in sorted(buckets):
            chosen.extend(_shuffled(buckets[key], sel.seed)[:sel.per_tenet])
    else:
        chosen = _shuffled(pool, sel.seed)[:max(sel.limit, 0)]
    if len(chosen) > cap:
        raise SampleTooLarge(
            f"that selection is {len(chosen):,} records and one run is capped at "
            f"{cap:,}. The cap is server-side (AFNI_CORPUS_MAX_SAMPLE) because a "
            f"Stage-2 pass costs 1-3 s per record: {len(chosen):,} records is "
            f"about {len(chosen) * 2 / 60:.0f} minutes of held-open request. "
            f"Lower the sample size, or run "
            f"`python rai_platform/corpus/baseline.py` offline for a full pass.")
    return chosen


# --------------------------------------------------------------------------- #
# Running                                                                     #
# --------------------------------------------------------------------------- #
def event_for(record: dict[str, Any]) -> Any:
    """Wrap a record as the GuardEvent its `direction` calls for.

    An output-direction record is an affirmative target completion - the text a
    jailbroken model would have produced - so it has to arrive as a RESPONSE or
    the output rails never see it. Sending everything as a REQUEST would score
    the output guardrail against input it will never be shown.
    """
    from afni_rai.contract.models import EventKind, GuardEvent, LLMProtocol

    text = record["prompt"]
    common = dict(step_id=record["id"], agent_id="corpus", agent_type="batch",
                  agent_workspace="afni", agent_user="corpus",
                  llm_protocol=LLMProtocol.OPENAI_CHAT, client_facing=True)
    if record.get("direction") == "output":
        return GuardEvent(kind=EventKind.RESPONSE,
                          payload={"choices": [{"message": {
                              "role": "assistant", "content": text}}]},
                          **common)
    return GuardEvent(kind=EventKind.REQUEST,
                      payload={"messages": [{"role": "user", "content": text}]},
                      **common)


def judge(cascade: Any, record: dict[str, Any]) -> dict[str, Any]:
    """One record's verdict, flattened to the fields a row needs.

    Never raises: a cascade that throws on record 47 of 200 must not lose the
    other 199, and "the engine failed here" is itself a finding worth reporting.
    A raised exception is recorded as `error`, which is a fourth decision value
    on this endpoint and is counted separately from a block.
    """
    try:
        outcome = cascade.evaluate(event_for(record))
    except Exception as exc:  # noqa: BLE001 - one bad record must not end the run
        return {"decision": "error", "blocking_rail": None,
                "blocking_category": None, "findings": 0, "unjudged": True,
                "stages_run": 0, "top_stage": None,
                "error": f"{type(exc).__name__}: {exc}"}
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
        # `stages_run` is a COUNT (stages that executed a rail), and `top_stage`
        # is the highest stage that had to run. Both, because the cost argument
        # needs the second one: a corpus where every record reaches Stage 2 is a
        # corpus where the free tier is short-circuiting nothing, and a count
        # alone hides that.
        "stages_run": int(outcome.stages_run),
        "top_stage": max((int(t.stage) for t in outcome.trace if t.rails_run),
                         default=None),
        "error": None,
    }


def preview(text: str, reveal: bool | None = None) -> str:
    if reveal is None:
        reveal = reveal_prompts()
    if reveal or len(text) <= PREVIEW_CHARS:
        return text
    return text[:PREVIEW_CHARS - 1].rstrip() + "…"


def row(record: dict[str, Any], actual: dict[str, Any],
        reveal: bool | None = None) -> dict[str, Any]:
    """One result row, including whether it AGREES with the recorded baseline.

    `agrees` is tri-state on purpose. `None` means there was nothing to compare -
    either no baseline, or a baseline taken on a different tier - and reporting
    that as agreement would let an unbaselined run look like a clean one.
    """
    expected = record.get("expected") or None
    agrees: bool | None = None
    if expected and expected.get("decision"):
        agrees = expected["decision"] == actual["decision"]
    return {
        "id": record["id"],
        "prompt": preview(record["prompt"], reveal),
        "direction": record.get("direction") or "input",
        "tenet": record.get("tenet"),
        "owasp": record.get("owasp") or [],
        "harm_label": record.get("harm_label"),
        "decision": actual["decision"],
        "blocking_rail": actual["blocking_rail"],
        "blocking_category": actual["blocking_category"],
        "findings": actual["findings"],
        "unjudged": actual["unjudged"],
        "stages_run": actual["stages_run"],
        "top_stage": actual.get("top_stage"),
        "error": actual.get("error"),
        "expected_decision": (expected or {}).get("decision"),
        "expected_tier": (expected or {}).get("tier"),
        "agrees": agrees,
    }


def aggregate(rows: list[dict[str, Any]], elapsed_ms: float,
              sel: Selection, tier: str) -> dict[str, Any]:
    """The numbers a run is judged on.

    `block_rate` is over the records that were actually judged, and `drift` is
    over the records that had a comparable baseline - two different denominators,
    both reported, because a single percentage over the sample size would quietly
    treat "no baseline" as "no drift".
    """
    decisions = Counter(r["decision"] for r in rows)
    comparable = [r for r in rows if r["agrees"] is not None]
    drifted = [r for r in comparable if r["agrees"] is False]
    return {
        "sample": len(rows),
        "selection": sel.describe(),
        "tier": tier,
        "elapsed_ms": round(elapsed_ms, 1),
        "ms_per_record": round(elapsed_ms / max(len(rows), 1), 2),
        "decisions": dict(decisions.most_common()),
        "block_rate": (round(decisions.get("block", 0) / len(rows), 4)
                       if rows else None),
        "unjudged": sum(1 for r in rows if r["unjudged"]),
        "errors": decisions.get("error", 0),
        "blocked_by": dict(Counter(
            r["blocking_rail"] for r in rows if r["blocking_rail"]).most_common()),
        # How far up the cascade each record actually had to go. This is the
        # measurement the free-first design lives or dies by: if every record
        # reaches Stage 2, Stage 1 short-circuited nothing and the ordering
        # bought nothing.
        "top_stage": {str(k): v for k, v in sorted(
            Counter(r["top_stage"] for r in rows).items(),
            key=lambda kv: (kv[0] is None, kv[0]))},
        "baseline_compared": len(comparable),
        "baseline_drift": len(drifted),
        "drifted_ids": [r["id"] for r in drifted][:40],
    }


def rails_for(max_stage: int, rails: list[Any]) -> list[Any]:
    """Trim the mounted rails to the requested ceiling, clamping at Stage 2
    unless the server allows cloud calls.

    Clamping here rather than in the route means the CLI, the API and any future
    caller get the same protection: `corpus/WARNING.md` forbids sending these
    prompts to a third-party judge, and a rule enforced in one surface is not a
    rule.
    """
    ceiling = max_stage
    if ceiling >= 3 and not cloud_allowed():
        ceiling = 2
    return [rail for rail in rails if int(rail.stage) <= ceiling]


def effective_max_stage(requested: int) -> tuple[int, str | None]:
    if requested >= 3 and not cloud_allowed():
        return 2, ("Stage 3 sends prompt text to a paid third-party judge, which "
                   "corpus/WARNING.md forbids for this corpus. Capped at Stage 2. "
                   "Set AFNI_CORPUS_ALLOW_CLOUD=1 on the server to permit it.")
    return requested, None


def tier_label(rails: list[Any]) -> str:
    """Which tiers can actually judge on THIS host.

    Stamped onto every run because rails that need model weights cannot run on a
    bare host, so the same prompt legitimately yields a different verdict there.
    Comparing a bare-host run against a provisioned baseline produces confident
    nonsense, which is why `agrees` refuses the comparison across tiers.
    """
    def can(rail: Any) -> bool:
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


@dataclass
class Run:
    """A completed run: the rows, plus the aggregate they add up to."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    note: str | None = None


def run(cascade: Any, records: list[dict[str, Any]], sel: Selection,
        tier: str, reveal: bool | None = None,
        note: str | None = None,
        on_row: Callable[[dict[str, Any], int, int], None] | None = None) -> Run:
    """Judge `records` and return the rows plus the aggregate.

    `on_row` is called after each record so a streaming caller can emit progress.
    A 200-record Stage-2 run is ten minutes; a browser given no frames for ten
    minutes is a browser that has given up.
    """
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    total = len(records)
    for index, record in enumerate(records, start=1):
        result = row(record, judge(cascade, record), reveal)
        rows.append(result)
        if on_row is not None:
            on_row(result, index, total)
    elapsed = (time.perf_counter() - started) * 1000
    return Run(rows=rows, stats=aggregate(rows, elapsed, sel, tier), note=note)


def iter_run(cascade: Any, records: list[dict[str, Any]], sel: Selection,
             tier: str, reveal: bool | None = None) -> Iterator[dict[str, Any]]:
    """Generator form: yields one `{"kind": "row", ...}` per record, then one
    `{"kind": "summary", ...}`. The route turns each into an SSE frame."""
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    total = len(records)
    for index, record in enumerate(records, start=1):
        result = row(record, judge(cascade, record), reveal)
        rows.append(result)
        yield {"kind": "row", "index": index, "total": total, "row": result}
    elapsed = (time.perf_counter() - started) * 1000
    yield {"kind": "summary", "stats": aggregate(rows, elapsed, sel, tier)}
