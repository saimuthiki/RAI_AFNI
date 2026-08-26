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

import inspect
import time
from collections.abc import Callable, Generator, Iterable, Sequence
from dataclasses import dataclass, field

from ..contract.models import Action, Decision, Finding, GuardEvent, Severity, Span, Verdict
from .rail import CheckContext, Rail, RailResult, Stage

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
class StageProgress:
    """One stage's result, handed out the moment that stage finishes.

    This exists so a caller can stream a decision as it is being made rather
    than after it has been made. `evaluate_iter` yields one of these per stage -
    including the stages that were skipped or short-circuited, because "stage 2
    never ran" is the cost argument becoming visible and is worth reporting.

    `findings` and `unjudged` are cumulative snapshots, deduped the same way the
    final verdict is, so a UI rendering them stage by stage shows the same rows
    it will end up with rather than a set that has to be reconciled at the end.
    """

    trace: StageTrace
    findings: list[Finding]
    unjudged: list[str]
    short_circuited: bool
    will_escalate: bool
    elapsed_ms: int

    @property
    def stage(self) -> Stage:
        return self.trace.stage

    @property
    def ran(self) -> bool:
        return bool(self.trace.rails_run)


@dataclass
class CascadeOutcome:
    verdict: Verdict
    trace: list[StageTrace]
    # (key, value, source) for every threshold consulted this request. The audit
    # trail has to be able to say WHICH threshold produced a decision - "a
    # threshold was applied" is not evidence anyone can act on.
    threshold_reads: list[tuple[str, float, str]] = field(default_factory=list)

    @property
    def stages_run(self) -> int:
        """Stages that actually executed a rail.

        Not `len(trace)`: the trace deliberately records skipped and
        short-circuited stages too, so that the saving is visible. Counting
        those as "run" would report a clean request as having cost three stages
        and quietly invert the whole cost argument.
        """
        return sum(1 for t in self.trace if t.rails_run)

    @property
    def stages_skipped(self) -> int:
        return sum(1 for t in self.trace if not t.rails_run)


def _dedupe(findings: Iterable[Finding]) -> list[Finding]:
    """Collapse findings that are the same observation reported twice.

    A rail with several patterns for one attack shape will legitimately match
    more than once on the same span - PyRIT's static injection scorer has 11
    rules and "ignore all previous instructions" trips two of them. Left alone,
    the duplicate inflates the finding count, appears twice in an operator's
    explanation, and double-counts in the compliance rollup that groups findings
    by category.

    Identity is (category, path, start, end, detector). Two genuinely different
    detectors finding the same span is corroboration and is kept - that is
    signal, not noise.
    """
    seen: set[tuple] = set()
    out: list[Finding] = []
    for f in findings:
        key = (f.category, f.path, f.start, f.end, f.detector)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _applies(rail, kind) -> bool:
    """Does this rail belong on this side of the AI system?

    A rail with no `direction` is treated as BOTH. That keeps every existing
    rail and every third-party rail working unchanged, and it is the safe way
    round: an absent declaration must never silently REMOVE a check.
    """
    direction = getattr(rail, "direction", None)
    if direction is None:
        return True
    try:
        return direction.covers(kind)
    except AttributeError:      # someone set a plain string
        return str(direction) in ("both", str(getattr(kind, "value", kind)))


def _blocking(findings: Iterable[Finding]) -> bool:
    return any(f.action is Action.BLOCK for f in findings)


def _severe(findings: Iterable[Finding]) -> bool:
    return any(f.severity in (Severity.HIGH, Severity.CRITICAL) for f in findings)


class Cascade:
    """Runs rails stage by stage over every judgeable string in an event."""

    def __init__(self, rails: Sequence[Rail],
                 resolve_threshold: Callable[[str | None, str], float] | None = None) -> None:
        """`resolve_threshold(tenant, key) -> float` is the only hook a rail gets
        into per-tenant configuration. Pass
        `ThresholdStore(...).resolve_value` to wire the real store; leave it None
        and every rail falls back to the threshold it was ported with, so an
        unconfigured gateway behaves exactly as before.
        """
        self._resolve = resolve_threshold
        # Which rails take a CheckContext is decided ONCE, here. Doing it per
        # request would mean an inspect.signature call per rail per payload
        # string, on the hot path, to answer a question that cannot change.
        self._wants_ctx: dict[str, bool] = {}
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
            self._wants_ctx[rail.name] = self._accepts_context(rail)

    @staticmethod
    def _accepts_context(rail: Rail) -> bool:
        """True when `rail.check` takes a third parameter for the context.

        Signature inspection rather than an isinstance check, because Rail is a
        structural Protocol - an adapter should not have to import from us just
        to be usable, and that property is worth keeping.
        """
        try:
            params = list(inspect.signature(rail.check).parameters.values())
        except (TypeError, ValueError):  # C extension, or an exotic callable
            return False
        positional = [p for p in params
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        if len(positional) >= 3:
            return True
        return any(p.name in ("ctx", "context") for p in params
                   if p.kind is p.KEYWORD_ONLY)

    @property
    def rails(self) -> list[Rail]:
        return [r for stage in sorted(self._by_stage) for r in self._by_stage[stage]]

    def evaluate(self, event: GuardEvent) -> CascadeOutcome:
        """Run the whole cascade and return the one consolidated outcome.

        Deliberately a thin driver over `evaluate_iter` rather than a second
        implementation. There is exactly one place in this codebase that decides
        what a stage does and when the next one runs; a streaming caller and a
        blocking caller get answers from the same code or they will eventually
        disagree, and a UI that disagrees with the audit record is worse than no
        UI.
        """
        generator = self.evaluate_iter(event)
        while True:
            try:
                next(generator)
            except StopIteration as stop:
                return stop.value

    def evaluate_iter(self, event: GuardEvent
                      ) -> Generator[StageProgress, None, CascadeOutcome]:
        """Yield after every stage; return the consolidated outcome at the end.

        The progress objects are produced *as each stage completes*, so a caller
        streaming them is reporting work that has actually happened. Nothing is
        buffered and re-emitted: the generator is suspended between stages, and
        the Stage-3 rails that cost money have genuinely not run yet when the
        Stage-1 event reaches the client.

        The final outcome is the generator's return value rather than a last
        yield, so the type of "a stage finished" and the type of "here is the
        verdict" cannot be confused by a consumer.
        """
        texts = event.texts()
        ctx = CheckContext(
            tenant=event.tenant, portfolio=event.project,
            client_facing=event.client_facing, resolve=self._resolve,
        )
        findings: list[Finding] = []
        modifications: list[Span] = []
        unjudged: set[str] = set()
        trace: list[StageTrace] = []
        started = time.perf_counter()

        escalate_next = True   # stage 1 always runs
        short_circuit = False

        def progress(entry: StageTrace) -> StageProgress:
            """One snapshot. Built here so the streaming and blocking paths
            cannot drift in what a stage is reported to have done."""
            return StageProgress(
                trace=entry,
                findings=_dedupe(findings),
                unjudged=sorted(unjudged),
                short_circuited=short_circuit,
                will_escalate=escalate_next and not short_circuit,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

        for stage in sorted(self._by_stage):
            if short_circuit:
                entry = StageTrace(stage, [], [r.name for r in self._by_stage[stage]],
                                   0, [], 0, short_circuited=True)
                trace.append(entry)
                yield progress(entry)
                continue
            if not escalate_next:
                # Nothing asked for this stage. Skipping it is the saving.
                entry = StageTrace(stage, [], [r.name for r in self._by_stage[stage]],
                                   0, [], 0)
                trace.append(entry)
                yield progress(entry)
                continue

            stage_started = time.perf_counter()
            ran: list[str] = []
            not_applicable: list[str] = []
            stage_findings: list[Finding] = []
            stage_unjudged: list[str] = []
            asked_to_escalate = False

            for rail in self._by_stage[stage]:
                # Direction gate. A rail that does not apply to this side of the
                # AI system is not run and not counted as coverage - and, crucially,
                # does NOT contribute an `unjudged` path. Before this gate,
                # output-only rails ran on prompts and reported "could not judge",
                # which stamped a coverage warning on almost every request and
                # trained operators to ignore the loudest line in the product.
                if not _applies(rail, event.kind):
                    not_applicable.append(rail.name)
                    continue
                ran.append(rail.name)
                for path, text in texts.items():
                    result = self._run(rail, path, text,
                                       ctx if self._wants_ctx.get(rail.name) else None)
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
            entry = StageTrace(
                stage=stage,
                rails_run=ran,
                rails_skipped=not_applicable,
                findings=len(stage_findings),
                unjudged_paths=stage_unjudged,
                latency_ms=int((time.perf_counter() - stage_started) * 1000),
                short_circuited=short_circuit,
            )
            trace.append(entry)

            if short_circuit or _blocking(stage_findings):
                short_circuit = True
            else:
                # Escalate when a rail asked, or when this stage found something
                # severe enough that a second opinion is worth paying for.
                escalate_next = asked_to_escalate or _severe(stage_findings)

            # After the escalation call, not before: a consumer streaming this
            # is told whether it should expect another stage.
            yield progress(entry)

        findings = _dedupe(findings)
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
        # The generator's RETURN value, not a final yield: "a stage finished" and
        # "here is the verdict" are different facts and stay different types.
        return CascadeOutcome(verdict=verdict, trace=trace,
                              threshold_reads=list(ctx.reads))

    @staticmethod
    def _run(rail: Rail, path: str, text: str,
             ctx: CheckContext | None = None) -> RailResult:
        """Backstop only. A rail that knows it failed should return
        `RailResult.unjudged(...)`; this catches the ones that don't and turns a
        crash into an explicit "could not judge" rather than a dropped check."""
        try:
            return rail.check(path, text, ctx) if ctx is not None else rail.check(path, text)
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
