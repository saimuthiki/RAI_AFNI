# -*- coding: utf-8 -*-
"""
The Rail interface every detector is wrapped in, and the stage vocabulary.

A rail is the *only* place a third-party library is touched. LLM Guard, NeMo,
Presidio, an Azure client - each gets exactly one adapter, so swapping a
detector is a one-file change and nothing in the gateway or the tenets knows
which vendor is underneath. That is what the OpenGuardrails contract buys us.

Stage membership is data, not code. It comes from the source-level methodology
analysis in `analysis/data/tenet_methodology_data.json`, where every one of the
108 repo-tenet rows carries a mechanism, a cost, a latency class and a derived
stage - each backed by a `file:line`, model id or dependency actually read from
the vendored source. A rail declares its stage; it does not get to invent one.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Protocol, runtime_checkable

from ..contract.models import EventKind, Finding, Span, Tenet


class Stage(IntEnum):
    """Cascade position. Ordered so `sorted()` gives execution order, and so
    "cheaper than" is a plain `<` comparison.

    The ordering is the whole cost argument: run everything free and
    deterministic on 100% of traffic, escalate only what survives. A request
    blocked at STAGE_1 never pays for STAGE_2 or STAGE_3.
    """

    STAGE_1 = 1   # free, deterministic, sub-millisecond - every request
    STAGE_2 = 2   # local model, or a cloud second opinion on borderline input
    STAGE_3 = 3   # paid API or LLM judge - last resort
    OFFLINE = 4   # CI and red-team only; never reachable from the request path


class Direction(str, Enum):
    """Which side of the AI system a rail belongs on.

    The gateway is called TWICE per interaction - once on the prompt heading for
    the model, once on the response heading for the person:

        user -> [INPUT guardrail] -> AI system -> [OUTPUT guardrail] -> user

    Most rails belong on both sides. An SSN is an SSN whether a support agent
    pasted it in or the model repeated it back. But some checks are meaningless
    in one direction and were, until now, running there anyway:

      * Groundedness compares an answer to its retrieved source. A user prompt
        has no answer to ground.
      * Refusal detection looks for a model declining. A user does not refuse.
      * Package hallucination looks for an invented import in generated code.
      * Schema and format validators check the shape of a MODEL's output against
        what the caller asked for.
      * The attack corpus holds confirmed attack PROMPTS.

    Running those in the wrong direction is not merely wasted work. Before this
    existed, `groundedness-nli` reported `unjudged` on every request that carried
    no retrieved context - which stamped COULD NOT JUDGE on nearly all traffic
    and made the loudest signal in the product meaningless.

    BOTH is the default, and deliberately so: restricting a rail REMOVES
    protection, so a rail is narrowed only where running it the other way is
    genuinely incoherent. Where the direction is arguable - prompt injection
    echoed back in a response, say - it stays BOTH.
    """

    INPUT = "input"
    OUTPUT = "output"
    BOTH = "both"

    def covers(self, kind: "EventKind") -> bool:
        """Does this rail apply to an event of `kind`?"""
        if self is Direction.BOTH:
            return True
        if self is Direction.INPUT:
            return kind is EventKind.REQUEST
        return kind is EventKind.RESPONSE


@dataclass
class RailResult:
    """What one rail reports. Deliberately not a bool.

    `judged=False` is the honest answer when a rail could not run - a model
    failed to load, a network call timed out, a threshold was misconfigured. The
    engine turns that into `unjudged` on the verdict rather than letting it read
    as "clean", which is the single failure mode this framework exists to stop.
    """

    judged: bool = True
    findings: list[Finding] = field(default_factory=list)
    modifications: list[Span] = field(default_factory=list)
    # Set when the rail wants to end the cascade immediately - a confident,
    # blocking hit. The engine still records everything found so far.
    block: bool = False
    # Set when the rail is unsure and wants the next stage to look. This is what
    # makes escalation conditional instead of "always run every layer".
    escalate: bool = False
    reason: str | None = None

    # Set when the check does not APPLY to this input, as distinct from having
    # failed to run. See `not_applicable`.
    inapplicable: bool = False

    @classmethod
    def clean(cls) -> "RailResult":
        return cls(judged=True)

    @classmethod
    def unjudged(cls, reason: str) -> "RailResult":
        """"I should have looked and could not." A real gap in coverage.

        Reserve this for a rail that was SUPPOSED to assess this input and
        failed: absent weights, an unconfigured credential, a timeout, a
        misconfigured threshold. The engine turns it into `unjudged` on the
        verdict and fails closed on client-facing traffic.
        """
        return cls(judged=False, reason=reason)

    @classmethod
    def not_applicable(cls, reason: str) -> "RailResult":
        """"This check does not apply to this input." NOT a gap.

        The distinction is not pedantry, it is what keeps the fail-loud signal
        worth reading. Groundedness is a *relation* between an answer and a
        retrieved source; a user prompt with no RAG context has nothing to be
        grounded in. Reporting that as "could not judge" made every single
        request arrive stamped `COULD NOT JUDGE 1 path(s)` - and a warning that
        fires on 100% of traffic conveys exactly nothing. Worse, it teaches an
        operator to skip the line that is supposed to be the loudest one on the
        page.

        `judged=True`, so it never fails closed; `inapplicable=True`, so the
        trace can still show that the rail declined rather than passed. Distinct
        from `clean()`, which claims "I looked and found nothing" - a claim a
        rail with no input to look at has not earned.
        """
        return cls(judged=True, inapplicable=True, reason=reason)


@dataclass
class CheckContext:
    """Per-request state a rail may need but cannot get from `(path, text)`.

    This exists because a configured threshold has to be *read* on the decision
    path. Without it a threshold service is write-only - stored, exposed through
    an admin API, and never consulted where it matters. That is not
    hypothetical: it is exactly what Safe Zone does (`admin.go:66` writes
    BlockThreshold/AllowThreshold, `guardrails.go:287` reads env globals
    instead).

    `resolve` is injected rather than the store itself, so a rail cannot reach
    past the context to read or mutate configuration it has no business touching,
    and so tests can supply a plain lambda.
    """

    resolve: Callable[[str], float | None] | None = None
    # Every (key, value, source) actually consulted this request. The audit
    # record needs to show which threshold produced a decision, not merely that
    # some threshold did.
    reads: list[tuple[str, float, str]] = field(default_factory=list)

    def threshold(self, key: str, default: float) -> float:
        """Resolve `key`, falling back to the rail's own value.

        The fallback is the threshold the rail was ported with, so a gateway
        constructed without a store behaves exactly as it did before this
        context existed. A resolver that raises falls back too, rather than
        failing the check - a misconfigured threshold must not become an
        unjudged path, because unjudged fails closed and a config typo would
        take all traffic down.
        """
        if self.resolve is None:
            self.reads.append((key, default, "rail-default"))
            return default
        try:
            value = self.resolve(key)
        except Exception:  # noqa: BLE001 - a bad config must not break the check
            self.reads.append((key, default, "rail-default-after-resolver-error"))
            return default
        if value is None:
            self.reads.append((key, default, "rail-default"))
            return default
        self.reads.append((key, float(value), "resolved"))
        return float(value)


@runtime_checkable
class Rail(Protocol):
    """Structural, not inherited - a rail is anything with these members, so an
    adapter never has to import from us just to be usable."""

    name: str
    tenet: Tenet
    stage: Stage

    def check(self, path: str, text: str) -> RailResult:
        """Judge one payload string. Must not raise for an expected failure -
        return `RailResult.unjudged(reason)` instead. The engine catches
        exceptions as a backstop, but a rail that knows it failed should say so.

        A rail with a tunable threshold takes an optional third parameter,
        `ctx: CheckContext | None`, and resolves through `ctx.threshold(key,
        default)`. The engine decides once, at construction, which rails accept
        it - never per request. Rails with nothing to tune (a regex either
        matches or it does not) keep the two-argument form, and that is not a
        gap: 20 of the 31 rails have no threshold at all.
        """
        ...


@dataclass
class RailSpec:
    """A rail plus the provenance of its stage assignment.

    `evidence` is not decoration. Every stage claim in this platform traces back
    to something actually read in the vendored source, and keeping the citation
    next to the rail is what makes the coverage report defensible to a client
    reviewer rather than merely assertive.
    """

    rail: Rail
    source_repo: str
    mechanism: str
    evidence: str
    capability: str | None = None
