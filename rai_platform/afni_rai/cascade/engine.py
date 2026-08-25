# -*- coding: utf-8 -*-
"""
The cascade engine: run the cheap rails on everything, escalate only what
survives, and consolidate the lot into exactly one verdict.

Two invariants are enforced *here*, in the engine, rather than trusted to each
of the dozens of rails:

  fail closed  - on client-facing traffic, a request that could not be fully
                 judged is blocked. NeMo Guardrails' own jailbreak rail defaults
                 to fail-OPEN (documented at
                 references/Guardrails-develop/docs/configure-rails/guardrail-catalog/jailbreak-protection.mdx:112),
                 which is exactly why this cannot be left to rail authors.

  fail loud    - a rail that could not run contributes its payload path to
                 `Verdict.unjudged`. It never silently reads as clean. The
                 Infosys toolkit's dispatcher wraps each check in a broad
                 try/except that logs and returns None, so one timeout drops a
                 check without anyone noticing; that is the precise behaviour
                 this engine refuses to reproduce.

Escalation is conditional, not layered-always. A stage runs only if the previous
stage asked for it (`escalate`) or if nothing conclusive was found yet. That is
where the cost saving actually comes from - a paid call on the thin slice of
borderline traffic instead of on all of it.
"""
from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..contract.models import Action, Decision, Finding, GuardEvent, Severity, Span, Verdict
from .rail import Rail, RailResult, Stage

PROVIDER = "afni-rai-gateway"


@dataclass
class StageTrace:
    """What one stage did. Kept so the audit record can explain a decision
    rather than merely stating it, and so the cost argument is measurable
    instead of asserted."""

    stage: Stage
    rails_run: list[str]
    rails_skipped: list[str]
    findings: int
    unjudged_paths: list[str]
    latency_ms: int
    short_circuited: bool = False


@dataclass
class CascadeOutcome:
    verdict: Verdict
    trace: list[StageTrace]

    @property
    def stages_run(self) -> int:
        return len(self.trace)


def _blocking(findings: Iterable[Finding]) -> bool:
    return any(f.action is Action.BLOCK for f in findings)


def _severe(findings: Iterable[Finding]) -> bool:
    return any(f.severity in (Severity.HIGH, Severity.CRITICAL) for f in findings)


class Cascade:
    """Runs rails stage by stage over every judgeable string in an event."""

    def __init__(self, rails: Sequence[Rail]) -> None:
        # Grouped once at construction; the request path does no sorting.
        self._by_stage: dict[Stage, list[Rail]] = {}
        for rail in rails:
            if rail.stage is Stage.OFFLINE:
                # A hard guard, not a filter. An offline red-team tool in the
                # request path would be a latency and cost incident, and the
                # methodology analysis shows most of the 22 repos are exactly
                # that - 8 of Privacy's 17 contributors are offline-only.
                raise ValueError(
                    f"rail {rail.name!r} is OFFLINE and cannot be mounted in the "
                    "request cascade; register it with the CI tier instead"
                )
            self._by_stage.setdefault(rail.stage, []).append(rail)

    @property
    def rails(self) -> list[Rail]:
        return [r for stage in sorted(self._by_stage) for r in self._by_stage[stage]]

    def evaluate(self, event: GuardEvent) -> CascadeOutcome:
        texts = event.texts()
        findings: list[Finding] = []
        modifications: list[Span] = []
        unjudged: set[str] = set()
        trace: list[StageTrace] = []
        started = time.perf_counter()

        escalate_next = True   # stage 1 always runs
        short_circuit = False

        for stage in sorted(self._by_stage):
            if short_circuit:
                trace.append(StageTrace(stage, [], [r.name for r in self._by_stage[stage]],
                                        0, [], 0, short_circuited=True))
                continue
            if not escalate_next:
                # Nothing asked for this stage. Skipping it is the saving.
                trace.append(StageTrace(stage, [], [r.name for r in self._by_stage[stage]],
                                        0, [], 0))
                continue

            stage_started = time.perf_counter()
            ran: list[str] = []
            stage_findings: list[Finding] = []
            stage_unjudged: list[str] = []
            asked_to_escalate = False

            for rail in self._by_stage[stage]:
                ran.append(rail.name)
                for path, text in texts.items():
                    result = self._run(rail, path, text)
                    if not result.judged:
                        unjudged.add(path)
                        stage_unjudged.append(path)
                        continue
                    stage_findings.extend(result.findings)
                    modifications.extend(result.modifications)
                    if result.escalate:
                        asked_to_escalate = True
                    if result.block:
                        short_circuit = True

            findings.extend(stage_findings)
            trace.append(StageTrace(
                stage=stage,
                rails_run=ran,
                rails_skipped=[],
                findings=len(stage_findings),
                unjudged_paths=stage_unjudged,
                latency_ms=int((time.perf_counter() - stage_started) * 1000),
                short_circuited=short_circuit,
            ))

            if short_circuit or _blocking(stage_findings):
                short_circuit = True
                continue

            # Escalate when a rail asked, or when this stage found something
            # severe enough that a second opinion is worth paying for.
            escalate_next = asked_to_escalate or _severe(stage_findings)

        decision = self._decide(event, findings, unjudged)
        verdict = Verdict(
            event_id=event.step_id,
            provider=PROVIDER,
            decision=decision,
            latency_ms=int((time.perf_counter() - started) * 1000),
            findings=findings,
            modifications=modifications,
            unjudged=sorted(unjudged),
        )
        return CascadeOutcome(verdict=verdict, trace=trace)

    @staticmethod
    def _run(rail: Rail, path: str, text: str) -> RailResult:
        """Backstop only. A rail that knows it failed should return
        `RailResult.unjudged(...)`; this catches the ones that don't and turns a
        crash into an explicit "could not judge" rather than a dropped check."""
        try:
            return rail.check(path, text)
        except Exception as exc:  # noqa: BLE001 - deliberate: any failure is unjudged
            return RailResult.unjudged(f"{rail.name} raised {type(exc).__name__}: {exc}")

    @staticmethod
    def _decide(event: GuardEvent, findings: list[Finding], unjudged: set[str]) -> Decision:
        if _blocking(findings):
            return Decision.BLOCK
        if unjudged and event.client_facing:
            # Fail closed. "Could not look" is not "found nothing".
            return Decision.BLOCK
        return Decision.ALLOW
