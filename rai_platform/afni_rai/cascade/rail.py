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

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol, runtime_checkable

from ..contract.models import Finding, Span, Tenet


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

    @classmethod
    def clean(cls) -> "RailResult":
        return cls(judged=True)

    @classmethod
    def unjudged(cls, reason: str) -> "RailResult":
        return cls(judged=False, reason=reason)


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
