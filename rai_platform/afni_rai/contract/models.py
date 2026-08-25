# -*- coding: utf-8 -*-
"""
The contract every AFNI AI application speaks to the gateway.

This is a faithful Python binding of the OpenGuardrails protocol **v0.8**, whose
JSON Schemas live at:

    references/openguardrails-main/openguardrails-main/schema/guard-event.schema.json
    references/openguardrails-main/openguardrails-main/schema/verdict.schema.json
    ($id https://openguardrails.com/schema/0.8/...)

Why borrow rather than invent: OpenGuardrails contributes no detector of its own,
and that is exactly its value. A vendor-neutral record shape is what lets AFNI
swap a detector, add a vendor, or move a check from local to cloud without
touching a single application. The protocol is **pre-1.0 and explicitly
breaking**, so `PROTOCOL_VERSION` is pinned here and asserted in tests - an
upstream bump must be a deliberate, reviewed change, never a silent one.

The one semantic that matters more than any other is `unjudged`. Upstream states
it plainly: a non-empty value means "could not look", which is *not* "found
nothing". A fail-closed enforcement point must treat it as a block. That is the
Infosys failure mode this whole framework exists to prevent - their dispatcher
wraps each check in a broad try/except that logs and returns None, so one
timeout silently drops a check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

PROTOCOL_VERSION = "0.8"

# Upstream constrains category to a dotted path under four roots. `x.` is the
# vendor-extension namespace, which is where AFNI's own detectors live.
#
# Deliberately STRICTER than upstream 0.8. Its published pattern is
# `^(safety|security|privacy|x)\.[a-z0-9_.]+$`, which puts `.` inside the
# character class and therefore accepts an empty segment - "safety..x" validates
# against it. Findings are grouped by category to produce the OWASP/NIST/EU-AI-Act
# compliance reports, so an empty segment would silently create a garbage bucket
# in the evidence AFNI hands a client reviewer. Rejecting it at the boundary is
# consistent with the rest of this platform: fail loud on malformed input rather
# than carry it forward. Every well-formed upstream category still validates.
_CATEGORY_RE = re.compile(r"^(safety|security|privacy|x)(\.[a-z0-9_]+)+$")


class Decision(str, Enum):
    """The only two outcomes upstream allows. Deliberately not a tri-state:
    "could not judge" is expressed by `Verdict.unjudged`, not by a third value,
    so a caller can never treat uncertainty as a pass by accident."""

    ALLOW = "allow"
    BLOCK = "block"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Action(str, Enum):
    """What a single finding contributed to the decision."""

    FLAG = "flag"
    REDACT = "redact"
    BLOCK = "block"


class EventKind(str, Enum):
    REQUEST = "step/request"
    RESPONSE = "step/response"


class LLMProtocol(str, Enum):
    OPENAI_CHAT = "openai.chat"
    OPENAI_RESPONSES = "openai.responses"
    ANTHROPIC_MESSAGES = "anthropic.messages"
    CANONICAL = "canonical"


# Keys whose string values are transport metadata, never user or model content.
# Kept deliberately tight - each entry is a field defined by a provider's API
# schema, not a guess. `user` is NOT here: it is an opaque caller-supplied
# identifier that has been known to carry an email address, and PII in that
# field is a real leak worth catching.
PROTOCOL_METADATA_KEYS = frozenset({
    "role",             # openai.chat / anthropic.messages: "user" | "assistant"
    "model",            # model id
    "type",             # anthropic content-block discriminator: "text" | "image"
    "object",           # openai response envelope: "chat.completion"
    "id",               # request / message / tool-call identifiers
    "tool_call_id",
    "request_id",
    "session_id",
    "finish_reason",    # openai
    "stop_reason",      # anthropic
    "stop",             # openai: caller-supplied terminators, a list of strings
    "stop_sequence",
    "system_fingerprint",
    "encoding_format",
    "api_version",
    "index",
    "created",
})


# The seven tenets. Spelled exactly as the analysis data spells them, so a tenet
# string joins cleanly against data/tenet_methodology_data.json and
# data/capability_matrix_data.json without a translation table.
class Tenet(str, Enum):
    PRIVACY = "Privacy"
    SECURITY = "Security"
    FAIRNESS = "Fairness & Bias"
    EXPLAINABILITY = "Explainability & Transparency"
    CONTENT_SAFETY = "Profanity / Content Safety"
    HALLUCINATION = "Hallucination / Reliability"
    ACCOUNTABILITY = "Accountability"


@dataclass(frozen=True)
class Finding:
    """One thing a detector found. `category` is the only field upstream
    requires; everything else is optional because a cheap regex rail genuinely
    knows less than an LLM judge, and padding the gap with zeros would be a lie."""

    category: str
    severity: Severity | None = None
    action: Action | None = None
    path: str | None = None
    start: int | None = None
    end: int | None = None
    score: float | None = None
    detector: str | None = None
    # `fp` is a whitelist FINGERPRINT - a hash of the subject minted by the
    # engine, never the value itself. Upstream types it as a string; an earlier
    # draft of this file had it as a bool, which the schema-conformance test now
    # catches. `subject` is the single detected value the finding is about, and
    # is what an operator's false-positive exception keys on - deliberately not
    # a per-span echo of matched text, which upstream says findings MUST NOT
    # carry.
    fp: str | None = None
    whitelisted: bool | None = None
    subject: str | None = None

    def __post_init__(self) -> None:
        if not _CATEGORY_RE.match(self.category):
            raise ValueError(
                f"category {self.category!r} must match {_CATEGORY_RE.pattern} - "
                "AFNI's own detectors belong under the 'x.' extension namespace"
            )
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [0, 1], got {self.score}")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"span end {self.end} precedes start {self.start}")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"category": self.category}
        for key in ("severity", "action", "path", "start", "end", "score",
                    "detector", "fp", "whitelisted", "subject"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value.value if isinstance(value, Enum) else value
        return out


@dataclass(frozen=True)
class Span:
    """A replacement applied to the payload - how redaction is reported without
    the caller having to diff anything."""

    path: str
    start: int
    end: int
    replacement: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "start": self.start, "end": self.end,
                "replacement": self.replacement}


@dataclass
class Verdict:
    """The single consolidated answer per request.

    Note "consolidated": one verdict, not a raw list of rail outputs. That is one
    of the three things the analysis says AFNI must build itself, because NeMo
    Guardrails does not provide it.
    """

    event_id: str
    provider: str
    decision: Decision
    latency_ms: int | None = None
    findings: list[Finding] = field(default_factory=list)
    modifications: list[Span] = field(default_factory=list)
    unjudged: list[str] = field(default_factory=list)

    @property
    def could_not_judge(self) -> bool:
        """True when at least one payload path was not judged at all.

        Read the upstream wording literally: this is "could not look", which is
        not "found nothing". Never let this collapse into a pass.
        """
        return bool(self.unjudged)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "event_id": self.event_id,
            "provider": self.provider,
            "decision": self.decision.value,
        }
        if self.latency_ms is not None:
            out["latency_ms"] = self.latency_ms
        if self.findings:
            out["findings"] = [f.to_dict() for f in self.findings]
        if self.modifications:
            out["modifications"] = {"spans": [s.to_dict() for s in self.modifications]}
        if self.unjudged:
            out["unjudged"] = list(self.unjudged)
        return out


@dataclass
class GuardEvent:
    """What an application sends in. Field names and the required set follow
    guard-event.schema.json exactly, so an AFNI app that already speaks
    OpenGuardrails needs no adapter."""

    kind: EventKind
    step_id: str
    agent_id: str
    agent_type: str
    agent_workspace: str
    agent_user: str
    llm_protocol: LLMProtocol
    payload: dict[str, Any]
    integration: dict[str, Any] | None = None

    # AFNI additions, carried outside the upstream schema so the wire format
    # stays compatible. `client_facing` is load-bearing: it selects fail-closed.
    client_facing: bool = True
    project: str | None = None
    tenant: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind.value,
            "step_id": self.step_id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "agent_workspace": self.agent_workspace,
            "agent_user": self.agent_user,
            "llm_protocol": self.llm_protocol.value,
            "payload": self.payload,
        }
        if self.integration is not None:
            out["integration"] = self.integration
        return out

    def texts(self) -> dict[str, str]:
        """Every judgeable string in the payload, keyed by its path.

        The path is what `unjudged` and `Finding.path` refer to, so this is the
        single place that decides what "a payload path" means. Nested lists and
        dicts are walked; non-string leaves are skipped rather than coerced.

        Protocol metadata is excluded (see `PROTOCOL_METADATA_KEYS`). Judging it
        is not merely wasteful - it is actively harmful. A Stage-2 rail whose
        model weights are absent returns `unjudged` for every path it was handed,
        and `unjudged` on client-facing traffic fails closed. Left unfiltered,
        that means a missing dependency blocks a request because nothing could
        judge the string "gpt-4o" in `payload.model`. Observed exactly that way
        while running the CLI.

        This is a DENY-list, not an allow-list, and deliberately so: anything
        unrecognised is still judged. Missing a content field would mean missing
        protection, whereas judging one extra metadata field is only noise, so
        the failure is pointed in the safe direction.
        """
        found: dict[str, str] = {}

        def walk(node: Any, path: str, key: str | None) -> None:
            if isinstance(node, str):
                if key not in PROTOCOL_METADATA_KEYS:
                    found[path] = node
            elif isinstance(node, dict):
                for k, value in node.items():
                    walk(value, f"{path}.{k}" if path else str(k), k)
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    # A list element inherits its container's key, so
                    # `stop: ["\n", "END"]` stays metadata rather than becoming
                    # two judgeable strings.
                    walk(value, f"{path}[{i}]", key)

        walk(self.payload, "payload", None)
        return found
