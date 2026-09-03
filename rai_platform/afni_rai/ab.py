# -*- coding: utf-8 -*-
"""
Guardrails off versus on - the before-and-after number, measured.

AFNI asked for a demonstrable attack success rate with the guardrails turned off
and turned on. This module produces it, and the honest version of it is a LADDER
rather than a pair, because "off versus on" hides the question that actually
matters to the build: which tier is doing the work.

    OFF          every attack reaches the model, by definition
    STAGE 1      free, deterministic, sub-millisecond, on every request
    STAGE 1+2    adds the local models
    STAGE 1+2+3  adds the paid judge, if the server allows it

WHY "OFF" IS 100% BY DEFINITION AND NOT A MEASUREMENT

With no guardrail there is no decision to make: every message reaches the model.
So the off arm is asserted rather than run, labelled as a definition, and costs
nothing to compute. Running forty records through an empty cascade to be told
what "no guardrail" means would be a number dressed up as an experiment.

An empty cascade DOES agree, and it is worth writing down why, because the
opposite was assumed here first and was wrong. `unjudged` is populated only when
a rail RUNS and cannot judge - `engine.py:302` sits inside the per-rail loop -
so with zero rails nothing is marked unjudged, fail-closed never fires, and the
verdict is `allow`. Asserted in `test_ab.py` so the assumption is checked rather
than repeated.

That has a consequence beyond this module, and it is reported to AFNI rather
than fixed here: **a gateway constructed with zero rails allows everything, and
`unjudged` will not catch it.** Fail-closed protects against a rail that tried
and failed, not against a rail that was never mounted. `Gateway.__init__` now
logs a CRITICAL when nothing is mounted at Stage 1; whether that should be a
hard refusal to boot is a policy decision, not one for this file.

WHAT THIS MEASURES, AND WHAT IT DOES NOT

It measures **delivery**: what fraction of known-harmful traffic reaches the
model. It does **not** measure whether the model would then have complied. A
prompt that reaches a well-aligned model and gets refused is a delivered attack
that failed, and this number counts it as delivered. That is the conservative
direction for a guardrail measurement and it is the one to report - but calling
it "attack success rate" without saying so would be an overclaim, so every
surface here says `delivered_to_model` and the label travels with the number.

The one exception is `pipeline` mode below, which does estimate end-to-end
success without needing a model, by using the corpus's own affirmative
completions.

Zero third-party dependencies.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import regression

#: The arms, in order. `off` is first because that is the reading order of the
#: result: this is what you have today, this is what each tier buys.
ARMS: tuple[tuple[str, int, str], ...] = (
    ("off", 0, "No guardrail. Every message reaches the model."),
    ("stage_1", 1, "Stage 1 only - free, deterministic, sub-millisecond."),
    ("stage_1_2", 2, "Stage 1 + 2 - adds the local models."),
    ("stage_1_2_3", 3, "Stage 1 + 2 + 3 - adds the paid third-party judge."),
)

ARM_BY_NAME = {name: (ceiling, why) for name, ceiling, why in ARMS}

#: How many records to spend warming an arm before timing it. Ten is enough
#: for at least one to escalate on every sample tried; the cap exists so a
#: selection where nothing escalates does not warm the whole sample twice.
WARM_RECORDS = 10


@dataclass
class Arm:
    """One rung of the ladder."""

    name: str
    ceiling: int
    label: str
    sample: int = 0
    stopped: int = 0
    delivered: int = 0
    unjudged: int = 0
    errors: int = 0
    elapsed_ms: float = 0.0
    rails: int = 0
    #: Which rail stopped what, so a demo can say WHY rather than just how many.
    stopped_by: dict[str, int] = field(default_factory=dict)
    #: Ids the arm let through, capped - the interesting rows in a demo are the
    #: ones that got past, not the ones that were caught.
    delivered_ids: list[str] = field(default_factory=list)
    #: Rails in this arm that CANNOT judge on this host. A non-empty list means
    #: this arm's stop rate is a floor rather than a measurement.
    rails_unavailable: list[str] = field(default_factory=list)
    #: Median and p95 per-record latency. Reported alongside the mean because
    #: the mean is the one a single slow record distorts, and on this cascade a
    #: single record that escalates to a model can be four seconds while the
    #: median is under a millisecond. Quoting only the mean would make the
    #: free-first design look expensive; quoting only the median would hide the
    #: tail an SLO has to survive.
    median_ms: float | None = None
    p95_ms: float | None = None

    @property
    def delivery_rate(self) -> float | None:
        return round(self.delivered / self.sample, 4) if self.sample else None

    @property
    def stop_rate(self) -> float | None:
        return round(self.stopped / self.sample, 4) if self.sample else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.name,
            "label": self.label,
            "ceiling": self.ceiling,
            "rails": self.rails,
            "sample": self.sample,
            "stopped": self.stopped,
            "delivered_to_model": self.delivered,
            "delivery_rate": self.delivery_rate,
            "stop_rate": self.stop_rate,
            "unjudged": self.unjudged,
            "errors": self.errors,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "ms_per_record": (round(self.elapsed_ms / self.sample, 2)
                              if self.sample else None),
            "median_ms_per_record": self.median_ms,
            "p95_ms_per_record": self.p95_ms,
            "stopped_by": self.stopped_by,
            "delivered_ids": self.delivered_ids[:40],
            "rails_unavailable": self.rails_unavailable,
            "measured": not self.rails_unavailable,
        }


def _off_arm(records: list[dict[str, Any]]) -> Arm:
    """The definition, not a run. See the module docstring."""
    return Arm(name="off", ceiling=0, label=ARM_BY_NAME["off"][1],
               sample=len(records), stopped=0, delivered=len(records),
               rails=0, elapsed_ms=0.0,
               delivered_ids=[r["id"] for r in records])


def cannot_judge(rails: Iterable[Any]) -> list[str]:
    """Which of these rails cannot judge on THIS host.

    `regression.tier_label` answers a coarser question - "can ANY Stage-2 rail
    run?" - and on this machine it says yes because Presidio is installed while
    four of the seven Stage-2 rails have no model weights. A ladder measured that
    way reports a Stage-2 delta that is a FLOOR and looks like a measurement, so
    the missing rails are named per arm rather than summarised into a tier.
    """
    out = []
    for rail in rails:
        for attr in ("dependency_available", "available", "configured"):
            probe = getattr(rail, attr, None)
            if callable(probe):
                try:
                    if not probe():
                        out.append(rail.name)
                except Exception:  # noqa: BLE001 - a broken probe is not a rail
                    out.append(rail.name)
                break
    return sorted(out)


def _run_arm(name: str, ceiling: int, rails: list[Any],
             records: list[dict[str, Any]],
             on_row: Callable[[str, int, int], None] | None = None,
             resolve_threshold: Callable[[str], float | None] | None = None
             ) -> Arm:
    from .cascade.engine import Cascade

    trimmed = regression.rails_for(ceiling, rails)
    absent = cannot_judge(trimmed)
    arm = Arm(name=name, ceiling=ceiling, label=ARM_BY_NAME[name][1],
              rails=len(trimmed), rails_unavailable=absent)
    # The threshold resolver is threaded through so an arm reflects the
    # deployment's SENSITIVITY SETTINGS. Without it the ladder would silently
    # measure the shipped defaults while the gateway ran on an operator's
    # overrides, and a demo would quote a number nobody's traffic sees.
    cascade = Cascade(trimmed, resolve_threshold=resolve_threshold)

    # WARM THE ARM BEFORE TIMING IT, and warm it until a Stage-2 rail has
    # actually run.
    #
    # Two versions of this were wrong before this one. Timing with no warm-up at
    # all put spaCy's en_core_web_lg load inside the window and reported the
    # Stage-2 rung at ~44 ms a record. Warming on records[0] alone did not fix
    # it, because Stage 1 short-circuits most records and never reaches the
    # model rails - the load then landed on whichever later record first
    # escalated. Measured directly: median 0.61 ms, max 4644 ms, one record
    # carrying the entire lazy load.
    #
    # So the warm-up walks records until an arm's top stage reaches its ceiling,
    # capped at WARM_RECORDS. The number wanted is the PER-REQUEST cost in
    # production, where the model is already resident.
    for record in records[:WARM_RECORDS]:
        warm = regression.judge(cascade, record)
        if (warm.get("top_stage") or 0) >= ceiling:
            break

    started = time.perf_counter()
    per_record: list[float] = []
    for index, record in enumerate(records, start=1):
        tick = time.perf_counter()
        actual = regression.judge(cascade, record)
        per_record.append((time.perf_counter() - tick) * 1000)
        arm.sample += 1
        if actual["decision"] == "error":
            arm.errors += 1
        if actual["unjudged"]:
            arm.unjudged += 1
        if actual["decision"] in ("block", "error"):
            # An `error` counts as STOPPED, not delivered. The engine threw, so
            # nothing was forwarded - counting it as delivered would flatter the
            # off arm and counting it as neither would break the arithmetic.
            arm.stopped += 1
            key = actual["blocking_rail"] or (
                "unjudged (fail closed)" if actual["unjudged"] else "engine error")
            arm.stopped_by[key] = arm.stopped_by.get(key, 0) + 1
        else:
            arm.delivered += 1
            arm.delivered_ids.append(record["id"])
        if on_row is not None:
            on_row(name, index, len(records))
    arm.elapsed_ms = (time.perf_counter() - started) * 1000
    arm.median_ms = _median(per_record)
    arm.p95_ms = _percentile(per_record, 0.95)
    return arm


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 3)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 3)


def _percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile. No interpolation, because a p95 of a 30-record
    sample interpolated between two points implies a precision the sample does
    not have."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))
    return round(ordered[index], 3)


@dataclass
class Comparison:
    arms: list[Arm] = field(default_factory=list)
    selection: str = ""
    tier: str = ""
    notes: list[str] = field(default_factory=list)
    #: Only populated in pipeline mode.
    pipeline: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        rows = [a.to_dict() for a in self.arms]
        body: dict[str, Any] = {
            "selection": self.selection,
            "tier": self.tier,
            "arms": rows,
            "deltas": _deltas(self.arms),
            "headline": headline(self.arms),
            "notes": self.notes,
            "measures": (
                "DELIVERY, not compliance. This is the fraction of "
                "known-harmful traffic that reaches the model. It does not "
                "measure whether the model would then have complied - a prompt "
                "that reaches a well-aligned model and gets refused is counted "
                "here as delivered. That is the conservative direction, and it "
                "is why the field is called `delivered_to_model`."),
        }
        if self.pipeline is not None:
            body["pipeline"] = self.pipeline
        return body


def _deltas(arms: list[Arm]) -> list[dict[str, Any]]:
    """What each rung buys over the one below it.

    This is the number that justifies the cascade's ordering. If Stage 2 adds
    nothing over Stage 1 on this corpus, the local models are not earning their
    latency and the delta says so plainly.
    """
    out = []
    for previous, arm in zip(arms, arms[1:]):
        gained = arm.stopped - previous.stopped
        out.append({
            "from": previous.name,
            "to": arm.name,
            "extra_stopped": gained,
            "extra_stop_rate": (round(gained / arm.sample, 4)
                                if arm.sample else None),
            "extra_ms_per_record": round(
                (arm.elapsed_ms - previous.elapsed_ms) / max(arm.sample, 1), 2),
            "extra_median_ms": (
                round((arm.median_ms or 0) - (previous.median_ms or 0), 3)),
        })
    return out


def headline(arms: list[Arm]) -> dict[str, Any] | None:
    """The one sentence a demo needs, built from the first and last arms."""
    if len(arms) < 2:
        return None
    off, best = arms[0], arms[-1]
    return {
        "sample": off.sample,
        "off_delivered": off.delivered,
        "off_delivery_rate": off.delivery_rate,
        "on_delivered": best.delivered,
        "on_delivery_rate": best.delivery_rate,
        "on_arm": best.name,
        "prevented": off.delivered - best.delivered,
        "sentence": (
            f"Of {off.sample} known-harmful messages, all {off.delivered} reach "
            f"the model with no guardrail. With {best.label.split(' - ')[0]} "
            f"in front, {best.delivered} do - {off.delivered - best.delivered} "
            f"are stopped before the model ever sees them."),
    }


def arms_for(max_stage: int) -> list[tuple[str, int, str]]:
    """Which arms to run, honouring the Stage-3 corpus restriction.

    `corpus/WARNING.md` forbids sending these prompts to a paid third-party
    judge, so the Stage-3 arm is dropped unless the server has explicitly
    allowed cloud calls. Dropped rather than silently downgraded to a duplicate
    of Stage 2, which would show a flat line and read as "Stage 3 adds nothing".
    """
    ceiling, _note = regression.effective_max_stage(max_stage)
    return [a for a in ARMS if a[1] <= ceiling]


def compare(rails: list[Any], records: list[dict[str, Any]],
            selection: str, tier: str, max_stage: int = 2,
            on_row: Callable[[str, int, int], None] | None = None,
            on_arm: Callable[[Arm], None] | None = None,
            resolve_threshold: Callable[[str], float | None] | None = None
            ) -> Comparison:
    """Run the same records through every arm and report the ladder.

    THE SAME RECORDS, not a fresh sample per arm. Sampling twice would make the
    delta between two arms partly a sampling artefact, and on a corpus that is
    42% content-safety a re-draw can move a rate by several points on its own.
    """
    result = Comparison(selection=selection, tier=tier)
    chosen = arms_for(max_stage)
    _ceiling, note = regression.effective_max_stage(max_stage)
    if note:
        result.notes.append(note)
    for name, ceiling, _why in chosen:
        arm = (_off_arm(records) if ceiling == 0
               else _run_arm(name, ceiling, rails, records, on_row,
                             resolve_threshold))
        result.arms.append(arm)
        if on_arm is not None:
            on_arm(arm)

    # Named AFTER the arms have run, from what each arm actually found missing,
    # so the warning lists the real rails rather than a tier's summary of them.
    for arm in result.arms:
        if arm.rails_unavailable:
            result.notes.append(
                f"The {arm.name} arm ran with {len(arm.rails_unavailable)} of "
                f"{arm.rails} rails unable to judge on this host "
                f"({', '.join(arm.rails_unavailable)}). Its stop rate is a "
                f"FLOOR, not a measurement - run it on a provisioned host for "
                f"the real number. `afni-rai preflight` says what is missing.")
    return result


# --------------------------------------------------------------------------- #
# Pipeline mode - end-to-end, still without a model                           #
# --------------------------------------------------------------------------- #
def pipeline_estimate(records: list[dict[str, Any]],
                      input_arm: Arm, output_arm: Arm) -> dict[str, Any]:
    """An end-to-end attack-success estimate that needs no model at all.

    The corpus carries both halves of an attack: the prompt, and - for 519
    records - the AFFIRMATIVE TARGET COMPLETION, the answer a jailbroken model
    would have produced. So the two guardrails can be measured against their own
    real inputs and composed:

        an attack succeeds only if the PROMPT gets past the input guardrail
        AND the harmful ANSWER gets past the output guardrail

    The composition assumes the model always complies, which is the worst case
    and therefore the right assumption for a guardrail claim: it measures the
    guardrail, not the model's alignment. Stated in the returned `assumes` field
    rather than left implicit, because an estimate whose assumption is invisible
    is a number people will quote without it.

    Independence is also assumed - that a prompt getting through does not make
    its completion more likely to get through - and it is not obviously true.
    Reported as an assumption, not smuggled in.
    """
    p_in = input_arm.delivery_rate
    p_out = output_arm.delivery_rate
    if p_in is None or p_out is None:
        return {
            "available": False,
            "why": ("needs both an input-direction and an output-direction "
                    "sample; one of them was empty. Run without a `direction` "
                    "filter so both are in the selection."),
        }
    combined = round(p_in * p_out, 4)
    return {
        "available": True,
        "input_sample": input_arm.sample,
        "output_sample": output_arm.sample,
        "prompt_gets_through": p_in,
        "harmful_answer_gets_through": p_out,
        "end_to_end_success_rate": combined,
        "off_success_rate": 1.0,
        "reduction": round(1.0 - combined, 4),
        "assumes": [
            "the model always complies with the attack - the worst case, and "
            "the right assumption for a claim about the GUARDRAIL rather than "
            "about the model's alignment",
            "the two guardrails are independent: that a prompt getting through "
            "does not make its own completion more likely to get through. Not "
            "obviously true, and reported rather than smuggled in.",
        ],
    }


def split_by_direction(records: Iterable[dict[str, Any]]
                       ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(input records, output records). A record with no `direction` is input."""
    ins, outs = [], []
    for record in records:
        (outs if record.get("direction") == "output" else ins).append(record)
    return ins, outs


# --------------------------------------------------------------------------- #
# The other half: how much ORDINARY work does it refuse?                       #
# --------------------------------------------------------------------------- #
def false_positives(rails: list[Any], records: list[dict[str, Any]],
                    max_stage: int = 2,
                    resolve_threshold: Callable[[str], float | None] | None = None
                    ) -> dict[str, Any]:
    """Run the benign corpus and split the refusals THREE ways.

    A single "false-positive rate" over this corpus would be a misleading
    number, and the first measurement proved it: 15 of 178 benign messages came
    back BLOCKED on this host, which reads as an 8.4% false-positive rate.
    **Every single one was a coverage gap**, not a detection - the Stage-2 model
    rails have no weights here, so they reported `unjudged`, and unjudged fails
    closed. The detection false-positive rate was ZERO.

    Reporting those together would have produced a number that gets worse when
    you install FEWER models, which is exactly backwards. So:

      refused_by_detection   a rail looked and was wrong. THE false-positive
                             rate, and the only one that tuning a threshold
                             changes.
      refused_by_coverage_gap  nothing could look. Fail-closed doing its job.
                             Fix it by installing the model, not by tuning.
      allowed_with_findings  allowed, but something was flagged or redacted.
                             Not a refusal, and still friction: a customer's
                             order number coming back as [REDACTED-US-SSN] is
                             a real problem even though the message went
                             through.

    `by_category` and `by_rail` are what make it actionable - a rate tells you
    there is a problem, a category tells you which rail to look at.
    """
    from collections import Counter

    from .cascade.engine import Cascade

    trimmed = regression.rails_for(max_stage, rails)
    cascade = Cascade(trimmed, resolve_threshold=resolve_threshold)

    detection: list[dict[str, Any]] = []
    gap: list[dict[str, Any]] = []
    noisy: list[dict[str, Any]] = []
    clean = 0

    for record in records:
        try:
            outcome = cascade.evaluate(regression.event_for(record))
        except Exception as exc:  # noqa: BLE001 - one record must not end the run
            detection.append({"id": record["id"],
                              "category": record.get("category", ""),
                              "prompt": regression.preview(record["prompt"]),
                              "rail": f"engine error: {type(exc).__name__}",
                              "finding": None})
            continue
        verdict = outcome.verdict
        blocked = verdict.decision.value == "block"
        row = {
            "id": record["id"],
            "category": record.get("category", ""),
            "tempts": record.get("tempts", ""),
            "prompt": regression.preview(record["prompt"]),
        }
        if blocked and verdict.unjudged:
            gap.append(dict(row, unjudged=list(verdict.unjudged)))
        elif blocked:
            top = next((f for f in verdict.findings
                        if f.action is not None and f.action.value == "block"), None)
            detection.append(dict(row, rail=top.detector if top else None,
                                  finding=top.category if top else None))
        elif verdict.findings or verdict.modifications:
            noisy.append(dict(
                row,
                findings=[f.category for f in verdict.findings],
                rails=sorted({f.detector for f in verdict.findings if f.detector}),
                redactions=len(verdict.modifications)))
        else:
            clean += 1

    total = len(records)
    def rate(n: int) -> float | None:
        return round(n / total, 4) if total else None

    return {
        "sample": total,
        "corpus": str(regression.benign_path()),
        "max_stage": max_stage,
        "rails": len(trimmed),
        "rails_unavailable": cannot_judge(trimmed),
        "clean": clean,
        "refused_by_detection": len(detection),
        "refused_by_coverage_gap": len(gap),
        "allowed_with_findings": len(noisy),
        "false_positive_rate": rate(len(detection)),
        "coverage_gap_rate": rate(len(gap)),
        "friction_rate": rate(len(noisy)),
        "by_category": {
            "detection": dict(Counter(r["category"] for r in detection).most_common()),
            "coverage_gap": dict(Counter(r["category"] for r in gap).most_common()),
            "friction": dict(Counter(r["category"] for r in noisy).most_common()),
        },
        "by_rail": dict(Counter(
            r.get("rail") or "?" for r in detection).most_common()),
        "detections": detection[:40],
        "friction": noisy[:40],
        "measures": (
            "`false_positive_rate` is the only one of the three that tuning a "
            "threshold changes. `coverage_gap_rate` gets WORSE when you install "
            "fewer models and is fixed by installing them. `friction_rate` is "
            "messages that went through with something flagged or redacted - "
            "not a refusal, and still a problem when it is a customer's order "
            "number coming back as [REDACTED-US-SSN]."),
    }


__all__ = ["ARMS", "ARM_BY_NAME", "Arm", "Comparison", "arms_for", "compare",
           "false_positives",
           "cannot_judge",
           "headline", "pipeline_estimate", "split_by_direction"]
