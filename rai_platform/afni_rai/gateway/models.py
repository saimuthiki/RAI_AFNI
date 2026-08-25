# -*- coding: utf-8 -*-
"""
The wire contract of the gateway: request and response models.

WHY THESE MODELS ARE DOCUMENTATION AND NOT THE SERIALISER

Requests are validated by these models - that is the point of having them, and a
malformed GuardEvent should be rejected at the boundary with a 422 rather than
crash a rail.

Responses are NOT serialised through them. The `/v1/guard` handlers build their
JSON from `Verdict.to_dict()` and `Explanation.to_dict()` and return it verbatim,
with the response models attached for the OpenAPI document only. That looks like
belt-and-braces until you try it the other way round:

  * `verdict.schema.json` declares `additionalProperties: false` and types
    `findings` as an array. Pydantic serialising an absent findings list emits
    `"findings": null`, which is not schema-valid. Suppressing that with
    `response_model_exclude_none` then also strips legitimate nulls out of the
    explanation, whose `score: null` means "this detector has no score", not
    "this key does not exist".
  * `Verdict.to_dict()` is already the contract's encoder, tested against the
    upstream schema by `tests/test_contract_conformance.py`. Re-encoding its
    output through a second serialiser adds a way for the two to disagree and
    buys nothing.

So the encoder stays single, and `tests/test_gateway.py` validates a live HTTP
response body against `verdict.schema.json` - the drift check that actually
matters, rather than one that only proves pydantic agrees with pydantic.

Naming and formats are fixed across every endpoint: snake_case fields, seconds
suffixed `_s`, milliseconds suffixed `_ms`, and one error shape everywhere.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..contract.models import PROTOCOL_VERSION

# --------------------------------------------------------------------------- #
# Errors - ONE shape, every endpoint, no exceptions                            #
# --------------------------------------------------------------------------- #
class Error(BaseModel):
    """The only error body this API returns.

    `code` is stable and machine-readable so a client can branch without
    string-matching prose; `message` is for the human reading the log; `details`
    carries whatever lets them self-diagnose; `request_id` is what support traces.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(examples=["invalid_guard_event"])
    message: str = Field(examples=["`payload` must be a JSON object"])
    details: dict[str, Any] | None = None
    request_id: str | None = None


# --------------------------------------------------------------------------- #
# Request                                                                      #
# --------------------------------------------------------------------------- #
class GuardRequest(BaseModel):
    """A GuardEvent, plus the three AFNI fields the upstream schema does not have.

    The required set is exactly `guard-event.schema.json`'s: an application that
    already speaks OpenGuardrails v0.8 needs no adapter to call this endpoint,
    which was the whole reason for adopting the schema.

    `client_facing` is the load-bearing extra. It selects fail-closed, so it
    defaults to `true`: a caller who forgets it gets the strict behaviour, and
    opting into fail-open is a deliberate act rather than an omission.

    `extra="forbid"` mirrors the upstream `additionalProperties: false`. A typo
    in a field name is a 422 rather than a silently ignored setting - a request
    that thought it was internal traffic and was judged as client-facing is the
    kind of surprise this rejects.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "example": {
            "kind": "step/request",
            "step_id": "step-8f2c",
            "agent_id": "support-bot",
            "agent_type": "chat",
            "agent_workspace": "afni",
            "agent_user": "u-1042",
            "llm_protocol": "openai.chat",
            "payload": {"messages": [
                {"role": "user", "content": "my ssn is 123-45-6789"}]},
            "tenant": "acme",
            "project": "support",
            "client_facing": True,
        }})

    kind: Literal["step/request", "step/response"]
    step_id: str = Field(min_length=1, description=(
        "Producer-minted id binding the request and response halves of ONE model "
        "call. Fresh per call, never reused."))
    agent_id: str = Field(description="Which agent. Empty string = no assertion.")
    agent_type: str = Field(description="What kind of agent. A label, not an identity.")
    agent_workspace: str = Field(description="The agent group sharing one policy set.")
    agent_user: str = Field(description="Who is using the agent. An attribute, "
                                        "never a policy boundary.")
    llm_protocol: Literal["openai.chat", "openai.responses",
                          "anthropic.messages", "canonical"]
    payload: dict[str, Any] = Field(description=(
        "The untouched provider request or response body. Every string in it is "
        "judged except the protocol metadata keys."))
    # Upstream types this as a string, 'name/version' - see guard-event.schema.json.
    # Followed here rather than the dataclass's dict annotation, because the schema
    # is the published contract.
    integration: str | None = Field(default=None, max_length=128, description=(
        "Who reported it, 'name/version'. Self-declared: never a basis for trust."))

    # --- AFNI additions, outside the upstream schema -------------------------
    client_facing: bool = Field(default=True, description=(
        "True (the default) fails CLOSED: a request that could not be fully "
        "judged is blocked. False fails open but still reports every unjudged "
        "path."))
    tenant: str | None = Field(default=None, description=(
        "Selects the tenant's threshold and fail_mode configuration."))
    project: str | None = Field(default=None, description=(
        "The portfolio the tenant inherits thresholds from."))


# --------------------------------------------------------------------------- #
# Verdict - a faithful mirror of verdict.schema.json, for the OpenAPI document  #
# --------------------------------------------------------------------------- #
_CATEGORY_PATTERN = r"^(safety|security|privacy|x)\.[a-z0-9_.]+$"


class FindingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(pattern=_CATEGORY_PATTERN)
    severity: Literal["low", "medium", "high", "critical"] | None = None
    action: Literal["flag", "redact", "block"] | None = None
    path: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    score: float | None = Field(default=None, ge=0, le=1)
    detector: str | None = None
    fp: str | None = Field(default=None, description=(
        "Whitelist fingerprint: a hash of the subject, minted by the engine. "
        "Never the value itself."))
    whitelisted: bool | None = None
    subject: str | None = Field(default=None, description=(
        "The detected value. Withheld unless the server is explicitly configured "
        "to reveal it - see AFNI_REVEAL_SUBJECT. Never enabled by a request."))


class SpanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    replacement: str


class ModificationsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spans: list[SpanModel]


class VerdictModel(BaseModel):
    """OpenGuardrails v0.8 `Verdict`. `extra="forbid"` because upstream says
    `additionalProperties: false`, and every AFNI-specific field therefore lives
    in `explanation` instead."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    decision: Literal["allow", "block"]
    latency_ms: float | None = Field(default=None, ge=0)
    findings: list[FindingModel] | None = None
    modifications: ModificationsModel | None = None
    unjudged: list[str] | None = Field(default=None, description=(
        "Payload paths this verdict could NOT judge. A non-empty value means "
        "'could not look', which is not 'found nothing'."))


# --------------------------------------------------------------------------- #
# Explanation and the /v1/guard envelope                                       #
# --------------------------------------------------------------------------- #
class AttributionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    tool: str
    rail: str
    mechanism: str
    stage: int
    confidence_kind: Literal["deterministic", "classifier", "entailment", "judge"]
    evidence: str
    capability: str | None = None


class FindingExplanationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str
    category: str
    action: str | None = None
    score: float | None = None
    location: str | None = None
    sentence: str
    attributed_to: AttributionModel | None = None


class ExplanationModel(BaseModel):
    """What a human acts on: which repo blocked it, how confident, which entity.

    Separate from the verdict because the verdict is `additionalProperties:
    false` upstream and applications rely on its shape.
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow", "block"]
    stages_run: int
    latency_ms: int | None = None
    could_not_judge: list[str]
    blocked_by: list[FindingExplanationModel]
    also_flagged: list[FindingExplanationModel]


class GuardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: VerdictModel
    explanation: ExplanationModel


# --------------------------------------------------------------------------- #
# Stream events                                                                #
# --------------------------------------------------------------------------- #
class StageEvent(BaseModel):
    """One SSE frame, emitted the moment a cascade stage finishes.

    Documented as a model even though SSE frames are not validated through it,
    because a client parsing `data:` lines needs the shape written down
    somewhere it cannot drift from.
    """

    model_config = ConfigDict(extra="forbid")

    event: Literal["stage"] = "stage"
    stage: int = Field(description="1, 2 or 3. Stage 4 is offline-only and never here.")
    ran: bool = Field(description="False when the stage was skipped or "
                                  "short-circuited - which is the cost saving.")
    rails_run: list[str]
    rails_skipped: list[str]
    findings: list[FindingModel] = Field(description=(
        "Cumulative and deduped: every finding so far, not just this stage's."))
    stage_findings: int
    unjudged: list[str]
    short_circuited: bool
    will_escalate: bool = Field(description="Whether a further stage is expected.")
    stage_latency_ms: int
    elapsed_ms: int


class StreamVerdictEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["verdict"] = "verdict"
    verdict: VerdictModel
    explanation: ExplanationModel


class StreamErrorEvent(BaseModel):
    """A failure mid-stream. Carries the fail-closed BLOCK verdict rather than
    ending the stream, because a client that saw stages and then silence has no
    way to tell a crash from an allow."""

    model_config = ConfigDict(extra="forbid")

    event: Literal["error"] = "error"
    error: Error


class DoneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["done"] = "done"


# --------------------------------------------------------------------------- #
# Read-only introspection endpoints                                            #
# --------------------------------------------------------------------------- #
class RailInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tenet: str
    stage: int
    stage_label: str
    attribution: AttributionModel | None = Field(default=None, description=(
        "Absent when a rail has no attribution row. An unattributed rail still "
        "runs; it just cannot be traced to a source repo."))
    available: bool | None = Field(default=None, description=(
        "What the rail says about its own dependency or credential. None when "
        "the rail exposes no such probe."))
    unavailable_reason: str | None = None


class RailsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: str = PROTOCOL_VERSION
    mounted: int
    rails: list[RailInfo]
    tenets_not_loaded: list[str]


class CoverageRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str
    status: Literal["implemented", "dependency-missing", "cloud-not-configured",
                    "offline-only", "gap"]
    note: str = ""
    attribution: AttributionModel | None = None


class CoverageTenet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenet: str
    counts: dict[str, int]
    rows: list[CoverageRow]


class CoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totals: dict[str, int]
    tenets: list[CoverageTenet]
    not_registered: list[str] = Field(description=(
        "Tenet packages that failed to register, and are therefore counted as "
        "gaps above rather than quietly omitted."))
    rendered: str = Field(description="The CLI's text report, for a terminal.")


class DependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    present: bool
    powers: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"] = Field(description=(
        "'degraded' whenever a tenet failed to load or a mounted rail cannot "
        "run. Still serving - and still failing closed, which is why degraded "
        "is not an outage."))
    protocol_version: str
    rails_mounted: int
    tenets_not_loaded: list[str]
    rails_unavailable: list[str]
    judge_rails_without_a_judge: list[str] = Field(description=(
        "Each of these reports unjudged for every string, which blocks "
        "client-facing traffic that reaches its stage."))
    judge_providers_skipped: list[str] = Field(default_factory=list, description=(
        "Providers named in AFNI_JUDGE_PROVIDER that contributed no usable link - "
        "an empty key list, an unset base URL. Skipped rather than fatal, because "
        "a missing paid credential must not take Stage 1 and Stage 2 offline; the "
        "rest of the chain still serves and the judge rails fail closed if none "
        "of it does."))
    dependencies_absent: list[DependencyStatus]
    judge_provider: dict[str, Any] | None = Field(default=None, description=(
        "Never contains a credential. `model_id_verified: false` means the model "
        "id is a documented default that has not been checked against a live "
        "endpoint."))
    reveal_subject: bool = Field(description=(
        "Server-side only. True means explanations echo matched values; it can "
        "only be set by the AFNI_REVEAL_SUBJECT environment variable, never by "
        "a request."))
    audit_db: str
