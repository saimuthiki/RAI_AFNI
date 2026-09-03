# -*- coding: utf-8 -*-
"""
The FastAPI gateway: the cascade, over HTTP.

    python3 rai_platform/serve.py
    curl -s localhost:8000/healthz | jq .
    curl -s localhost:8000/v1/guard -H 'content-type: application/json' \
         -d '{"kind":"step/request","step_id":"s1","agent_id":"a","agent_type":"chat",
              "agent_workspace":"afni","agent_user":"u","llm_protocol":"openai.chat",
              "payload":{"messages":[{"role":"user","content":"my ssn is 123-45-6789"}]}}'

WHAT THIS LAYER OWNS, AND WHAT IT MUST NOT REIMPLEMENT

The decision belongs to `cascade/engine.py`, the fail_mode belongs to
`tenets/accountability/policy.py`, the thresholds to `ThresholdStore`, and the
record to `VerdictStore`. This module wires them together, turns HTTP into a
`GuardEvent` and back, and owns exactly four things of its own:

  the trust boundary   `reveal_subject` is read from the SERVER's environment and
                       from nowhere else. There is no request parameter, no query
                       string and no header that can turn it on. A caller must
                       never be able to ask the gateway to echo back the secret it
                       just caught - that would make the endpoint an exfiltration
                       primitive for anyone who can reach it.

  fail closed on error If the cascade raises, this returns HTTP 200 with a BLOCK
                       verdict whose `unjudged` lists the payload paths - never a
                       500. A 500 is ambiguous, and a caller with a `try/except:
                       pass` around its guard call reads an ambiguous failure as
                       "no findings". That is the exact bug this platform exists
                       to prevent, so the failure is expressed IN the contract.

  real streaming       `/v1/guard/stream` drives `Cascade.evaluate_iter`, a
                       generator that suspends between stages. A Stage-1 frame
                       reaches the client before any Stage-3 rail has been asked
                       to spend money. Nothing is computed up front and dribbled
                       out; a progress UI fed by a fake would be a lie about
                       where the latency and the cost went.

  one error shape      `{code, message, details, request_id}` on every failure
                       path, with `x-request-id` echoed on every response.

  the guarded passthrough
                       `/v1/chat` is the same cascade run TWICE around a real
                       model call: guard the prompt, call the target, guard the
                       completion. The order is the product - see
                       `passthrough.py`. Absent target configuration is a 503 on
                       that endpoint alone; everything else here is unaffected.

Versioning: the decision endpoints are under `/v1`. `/healthz` is unversioned
because it describes the process, not the contract.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Annotated, Any, Callable, Iterator, Sequence

from fastapi import APIRouter, Body, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from ..cascade.engine import PROVIDER, Cascade, CascadeOutcome
from ..cascade.rail import Direction, Stage
from ..cli import TENET_PACKAGES, load_tenets
from ..contract.explanation import Explanation, RailAttribution, explain
from ..contract.models import (
    PROTOCOL_VERSION, Decision, EventKind, GuardEvent, LLMProtocol, Verdict,
)
from .. import topics
from ..registry import repositories
from ..tenets.explainability import TopicScopeRail
from ..registry.capabilities import CapabilityRegistry
from ..warmup import warm_all
from ..target import EndpointProbe, TargetClient, probe_timeout_from_env
from ..target import client as target_env
from ..target import from_env as target_from_env
from ..tenets.accountability.audit import ORIGIN_LIVE, VerdictStore
from ..tenets.accountability.policy import FailurePolicy
from ..tenets.accountability.thresholds import ThresholdStore
from . import providers
from .corpus_api import corpus_router
from .topics_api import topics_router
from .models import (
    ChatRequest, ChatResponse, CoverageResponse, Error, GuardRequest,
    GuardResponse, HealthResponse, RailsResponse,
)
from .passthrough import Passthrough

LOGGER = logging.getLogger("afni_rai.gateway")

# --------------------------------------------------------------------------- #
# Server-side configuration. Every one of these is an environment variable and  #
# none of them is reachable from a request body.                               #
# --------------------------------------------------------------------------- #
ENV_REVEAL = "AFNI_REVEAL_SUBJECT"
ENV_AUDIT_DB = "AFNI_AUDIT_DB"
# Aliased from the target package rather than re-spelled, so the name in an
# error message cannot drift from the name the loader actually reads.
ENV_TARGET_BASE_URL = target_env.ENV_BASE_URL
ENV_TARGET_MODEL = target_env.ENV_MODEL

STAGE_LABELS = {
    1: "free, deterministic, every request",
    2: "local model or cloud second opinion",
    3: "paid API or LLM judge",
    4: "offline - CI and red-team only, never mounted inline",
}

# Optional third-party packages a rail imports lazily, and what each one powers.
# Reported by /healthz because a missing one is not a crash here - the rail
# reports `unjudged`, which fails closed - and an operator seeing every escalated
# request blocked deserves to be told why in one call.
OPTIONAL_DEPENDENCIES: tuple[tuple[str, str], ...] = (
    ("presidio_analyzer", "privacy.presidio_ner - Presidio NER entity detection"),
    ("transformers", "security DeBERTa injection, bias and toxicity classifiers, "
                     "zero-shot topics, NLI groundedness"),
    ("torch", "the backend those classifiers run on"),
    ("deepteam", "privacy.pii_leakage_judge provenance check"),
    ("deepeval", "afni-rubric-judge G-Eval rubric scoring"),
    ("jsonschema", "structured-output-schema validation"),
    ("opentelemetry", "span export from the accountability tracer"),
)


SAMPLES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "samples", "tenet_payloads.json")


def load_samples(path: str = SAMPLES_PATH) -> dict[str, Any]:
    """The verified per-tenet sample payloads, or an empty set.

    Read at import so they can become the named examples on the request body,
    which FastAPI collects at decoration time. This is the one file this module
    reads on import: a few kilobytes of bundled API documentation, not runtime
    state, and a missing or unparseable file costs the docs their examples rather
    than costing the gateway its startup.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:  # noqa: BLE001
        LOGGER.warning("sample payloads unavailable (%s): /docs will have no "
                       "per-tenet examples", exc)
        return {"samples": []}


def guard_examples(document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn the samples into Swagger's named-example dropdown.

    Each entry keeps the sample's own `why` as its description, so the reason a
    payload trips a tenet is in front of whoever is about to send it rather than
    in a file they have not opened.
    """
    document = load_samples() if document is None else document
    examples: dict[str, Any] = {}
    for sample in document.get("samples", []):
        examples[sample["name"]] = {
            "summary": sample.get("summary", sample["name"]),
            "description": (f"**{sample.get('tenet', '?')}** - "
                            f"{sample.get('why', '')}\n\nExpected detectors: "
                            + (", ".join(f"`{d}`" for d in sample.get("expect_detectors", ()))
                               or "_none - this one must trip nothing_")),
            "value": sample["body"],
        }
    return examples


GUARD_EXAMPLES = guard_examples()

GUARD_BODY = Annotated[GuardRequest, Body(openapi_examples=GUARD_EXAMPLES)]

# A worked response, so the Swagger page shows what comes back before anyone
# sends anything. Taken from the `security_leaked_credentials` sample: a block
# caused by a real finding, short-circuited at Stage 1, with the value withheld.
GUARD_RESPONSE_EXAMPLE = {
    "verdict": {
        "event_id": "sample-security-2",
        "provider": "afni-rai-gateway",
        "decision": "block",
        "latency_ms": 2,
        "findings": [{
            "category": "security.secret_leak.cloud_credential",
            "severity": "critical", "action": "block",
            "path": "payload.messages[0].content", "start": 12, "end": 32,
            "detector": "security.secrets", "fp": "sha256:6f1c0e",
        }],
    },
    "explanation": {
        "decision": "block", "stages_run": 1, "latency_ms": 2,
        "could_not_judge": [],
        "blocked_by": [{
            "entity": "cloud_credential",
            "category": "security.secret_leak.cloud_credential",
            "action": "block", "score": None,
            "location": "payload.messages[0].content chars 12-32",
            "sentence": ("AFNI secret patterns (hai-guardrails-main) flagged "
                         "cloud_credential at payload.messages[0].content chars "
                         "12-32 - deterministic match, no score - action block - "
                         "value withheld (fp sha256:6f1c0e)"),
            "attributed_to": {
                "repo": "hai-guardrails-main", "tool": "AFNI secret patterns",
                "rail": "security.secrets", "mechanism": "Keyword/Regex",
                "stage": 1, "confidence_kind": "deterministic",
                "evidence": "src/guards/secret.guard.ts",
                "capability": "Secret / credential leak detection",
            },
        }],
        "also_flagged": [],
    },
}

# SSE is a text format, so the example is the literal wire bytes rather than a
# JSON object - a client author needs to see the framing, not a pretty-printed
# approximation of it.
STREAM_RESPONSE_EXAMPLE = (
    'event: stage\n'
    'data: {"event":"stage","stage":1,"ran":true,"rails_run":["security.secrets"],'
    '"rails_skipped":[],"findings":[],"stage_findings":1,"unjudged":[],'
    '"short_circuited":true,"will_escalate":false,"stage_latency_ms":2,"elapsed_ms":2}\n'
    '\n'
    'event: stage\n'
    'data: {"event":"stage","stage":2,"ran":false,"rails_run":[],'
    '"rails_skipped":["privacy.presidio_ner"],"findings":[],"stage_findings":0,'
    '"unjudged":[],"short_circuited":true,"will_escalate":false,'
    '"stage_latency_ms":0,"elapsed_ms":2}\n'
    '\n'
    'event: verdict\n'
    'data: {"event":"verdict","verdict":{"event_id":"sample-security-2",'
    '"provider":"afni-rai-gateway","decision":"block"},"explanation":{...}}\n'
    '\n'
    'event: done\n'
    'data: {"event":"done"}\n'
    '\n'
)

TAGS_METADATA = [
    {"name": "decisions", "description":
     "Judge a GuardEvent, or run a guarded passthrough. These are the only "
     "endpoints in the request path, and the only ones that write to the audit "
     "store. `/v1/guard` judges text you hand it; `/v1/chat` puts one guardrail "
     "on each side of your model and calls it for you."},
    {"name": "introspection", "description":
     "What this gateway is running, what it covers, and what is missing. "
     "Read-only, no audit rows, safe to poll."},
]


# One definition of "is this env flag on", in providers. A second reading of
# "true" that could diverge from the first is how a security flag ends up on in
# one module and off in another.
_truthy = providers.truthy


def _rail_available(rail: Any) -> tuple[bool | None, str | None]:
    """Ask a rail whether it can actually run.

    Rails answer this three different ways - `dependency_available()`,
    `available()`, `configured()` - because they were ported from three different
    upstream shapes. Probing all three rather than normalising them keeps this
    module out of the tenets; a rail that answers none of them reports None,
    which is honest rather than an assumed True.
    """
    for attribute in ("dependency_available", "available", "configured"):
        probe = getattr(rail, attribute, None)
        if probe is None or not callable(probe):
            continue
        try:
            ok = bool(probe())
        except Exception as exc:  # noqa: BLE001 - a probe must not break /healthz
            return False, f"{attribute}() raised {type(exc).__name__}"
        return ok, None if ok else f"{attribute}() is False"
    return None, None


def withhold_subjects(verdict: dict[str, Any]) -> dict[str, Any]:
    """Strip `Finding.subject` - the matched SSN, the matched API key - from a
    verdict on its way to the wire, leaving `fp` behind.

    The platform's own doctrine, from `docs/architecture.md`: "the value withheld -
    with a fingerprint instead. The subject is the actual SSN. A guardrail that
    echoes it into a log has defeated itself. `fp` is what a false-positive
    exception keys on." `VerdictStore` already has no column it could go into.
    Without this the HTTP verdict would be the one surface that still carried it,
    into every proxy log and browser devtools panel between here and the caller -
    while the explanation right next to it says "value withheld", which would be
    false.

    `subject` is optional in `verdict.schema.json`, so removing it leaves the
    verdict strictly schema-valid; nothing is added, renamed or reshaped. The
    same server-side `AFNI_REVEAL_SUBJECT` flag governs this and the explanation,
    so there is one trust boundary rather than two that can disagree, and no
    request can move either.
    """
    findings = verdict.get("findings")
    if not findings:
        return verdict
    for finding in findings:
        finding.pop("subject", None)
    return verdict


def _attribution_dict(attr: RailAttribution | None) -> dict[str, Any] | None:
    if attr is None:
        return None
    return {"repo": attr.source_repo, "tool": attr.display_name, "rail": attr.rail,
            "mechanism": attr.mechanism, "stage": attr.stage,
            "confidence_kind": attr.confidence_kind, "evidence": attr.evidence,
            "capability": attr.capability}


class Gateway:
    """Everything one gateway process holds, built once at startup.

    A class rather than module globals so a test can stand up two gateways with
    different rails in one interpreter, and so nothing is constructed at import
    time - importing this module must not open a database or read a model file.
    """

    def __init__(self, *,
                 rails: Sequence[Any] | None = None,
                 attributions: dict[str, RailAttribution] | None = None,
                 problems: Sequence[str] | None = None,
                 threshold_store: ThresholdStore | None = None,
                 verdict_store: VerdictStore | None = None,
                 judge_provider: Any | None = None,
                 reveal_subject: bool | None = None,
                 target: TargetClient | None = None,
                 probe: bool = True,
                 env: dict[str, str] | None = None) -> None:
        env = os.environ if env is None else env

        if rails is None:
            # REUSED from the CLI, not reimplemented. One definition of "which
            # tenets exist and which of them failed to load", so the CLI and the
            # HTTP API cannot disagree about what is mounted.
            loaded, loaded_attributions, loaded_problems = load_tenets()
            rails = loaded
            attributions = attributions if attributions is not None else loaded_attributions
            problems = problems if problems is not None else loaded_problems

        self.problems: list[str] = list(problems or [])
        self.attributions: dict[str, RailAttribution] = dict(attributions or {})

        # A judge provider is optional and defaults to absent. With none, every
        # Stage-3 judge rail reports `unjudged` - which fails closed. No guess.
        # A provider named in the chain with no credential is skipped rather than
        # fatal, and the reason is kept so /healthz can name it: a missing paid key
        # must not take Stage 1 and Stage 2 offline with it.
        self.judge_providers_skipped: list[str] = []
        self.judge_provider = (
            providers.from_env(env, self.judge_providers_skipped)
            if judge_provider is None else judge_provider)
        # The topic rail arrives already mounted from `load_tenets()`, so the CLI
        # and this gateway cannot disagree about what is banned. Kept as an
        # attribute for /v1/topics to report against.
        self.topic_policy = topics.load_policy()
        self.topic_rail = next(
            (r for r in rails if r.name == TopicScopeRail.name), None)

        mountable = [r for r in rails if r.stage is not Stage.OFFLINE]
        self.rails: list[Any] = providers.bind_judges(mountable, self.judge_provider)

        # THE AI SYSTEM THIS GATEWAY GUARDS. Optional, and absent by default:
        # with no target this is the judge-only gateway it has always been, and
        # `/v1/chat` says so in the standard error shape rather than 500ing.
        self.target = (target_from_env(env) if target is None else target)
        self.target_probe: EndpointProbe = EndpointProbe(configured=False)
        if self.target is not None:
            self.target_probe = EndpointProbe(
                configured=True, base_url=self.target.config.base_url,
                model=self.target.config.model, detail="not probed")
            if probe:
                # ONCE, at construction, with a short timeout of its own, and
                # never on the request path. `probe()` cannot raise - see
                # target/client.py - because a model server that is down must
                # not stop a guardrail gateway from booting. That is the same
                # trade as a keyless judge provider being skipped rather than
                # fatal.
                self.target_probe = self.target.probe(probe_timeout_from_env(env))
                LOGGER.log(
                    logging.INFO if self.target_probe.reachable else logging.WARNING,
                    "target probe: %s reachable=%s (%s) - model id %r is %s",
                    self.target.config.base_url, self.target_probe.reachable,
                    self.target_probe.detail, self.target.config.model,
                    "VERIFIED by the endpoint's /models listing"
                    if self.target_probe.model_id_verified else "UNVERIFIED")

        self.thresholds = threshold_store if threshold_store is not None else ThresholdStore()
        # The one hook a rail gets into threshold configuration. Without this the
        # threshold store would be write-only - configured, exposed, and never
        # consulted, which is Safe Zone's bug (admin.go:66 writes it,
        # guardrails.go:287 reads an env global instead).
        self.cascade = Cascade(self.rails, resolve_threshold=self.thresholds.resolve_value)
        self.policy = FailurePolicy(self.thresholds)

        self.audit_db = env.get(ENV_AUDIT_DB) or ":memory:"
        self.store = (verdict_store if verdict_store is not None
                      else VerdictStore(self.audit_db))
        # sqlite is opened with check_same_thread=False and the sync endpoints run
        # in Starlette's threadpool, so writes are serialised here rather than
        # relying on two threads sharing one cursor politely.
        self._write_lock = threading.Lock()

        # THE TRUST BOUNDARY. Server-side only, default off. There is deliberately
        # no code path from a request to this value.
        self.reveal_subject = (_truthy(env.get(ENV_REVEAL)) if reveal_subject is None
                               else bool(reveal_subject))
        if self.reveal_subject:
            LOGGER.warning(
                "%s is on: explanations will echo matched values (SSNs, API keys) "
                "to every caller and into every log this response reaches",
                ENV_REVEAL)
        if self.problems:
            LOGGER.warning("tenets not loaded: %s", "; ".join(self.problems))

    # ------------------------------------------------------------- decisions --
    def event(self, body: GuardRequest) -> GuardEvent:
        return GuardEvent(
            kind=EventKind(body.kind),
            step_id=body.step_id,
            agent_id=body.agent_id,
            agent_type=body.agent_type,
            agent_workspace=body.agent_workspace,
            agent_user=body.agent_user,
            llm_protocol=LLMProtocol(body.llm_protocol),
            payload=body.payload,
            integration=body.integration,
        )

    @staticmethod
    def unjudgeable_paths(event: GuardEvent) -> list[str]:
        """Every payload path, for the fail-closed verdict.

        `texts()` walks the payload and can itself be the thing that raised, so
        it is guarded: the fallback is the single path `payload`, which is still a
        non-empty `unjudged` and therefore still a block. An empty list here would
        read as "everything was judged", which is the one answer that must never
        come out of an error path.
        """
        try:
            paths = sorted(event.texts())
        except Exception:  # noqa: BLE001
            paths = []
        return paths or ["payload"]

    def fail_closed(self, event: GuardEvent, exc: BaseException) -> CascadeOutcome:
        """The cascade raised. Return a BLOCK, loudly, in the contract's own shape."""
        LOGGER.exception("cascade raised for event %s; failing closed",
                         event.step_id, exc_info=exc)
        verdict = Verdict(
            event_id=event.step_id,
            provider=PROVIDER,
            decision=Decision.BLOCK,
            latency_ms=None,
            findings=[],
            modifications=[],
            unjudged=self.unjudgeable_paths(event),
        )
        return CascadeOutcome(verdict=verdict, trace=[], threshold_reads=[])

    def finish(self, event: GuardEvent, outcome: CascadeOutcome,
               *, degraded: str | None = None) -> tuple[dict[str, Any], Explanation]:
        """Apply the configured fail_mode, persist, and render.

        Order matters. The policy may override the engine on an unjudged path -
        that is its entire job - so the explanation is built AFTER the override,
        or the caller would be handed an explanation that contradicts the verdict
        it arrived with.
        """
        verdict = outcome.verdict
        decided = self.policy.apply(event, outcome)
        verdict.decision = decided.decision
        if degraded:
            # A fail_mode=open is a statement about ONE rail that could not
            # look. It is not consent to serve a request the engine could not
            # evaluate at all, so an engine-level failure stays a block
            # regardless. The audit row still carries the configured fail_mode,
            # so the override is visible rather than silent.
            verdict.decision = Decision.BLOCK

        explanation = explain(verdict, self.attributions,
                              stages_run=outcome.stages_run)
        # Recorded BEFORE the wire redaction, from the objects themselves: the
        # audit store decides for itself what it keeps (and it keeps no subject),
        # and it must not depend on a presentation-layer copy.
        self.record(verdict, event, explanation, decided, degraded=degraded)
        wire = verdict.to_dict()
        if not self.reveal_subject:
            withhold_subjects(wire)
        return ({"verdict": wire,
                 "explanation": explanation.to_dict(reveal_subject=self.reveal_subject)},
                explanation)

    def record(self, verdict: Verdict, event: GuardEvent, explanation: Explanation,
               decided: Any, *, degraded: str | None = None) -> None:
        """Persist every decision, including the fail-closed ones.

        A swallowed audit failure would be the Infosys dispatcher pattern with a
        different subject, so it is logged at error level - but it does not fail
        the request. The decision has already been made correctly; losing the
        record is a serious evidence problem and not a reason to also stop
        protecting the caller.
        """
        try:
            with self._write_lock:
                self.store.record(
                    verdict, event=event, explanation=explanation,
                    attributions=self.attributions, origin=ORIGIN_LIVE,
                    enforced=decided.decision.value,
                    fail_mode=decided.fail_mode.value,
                    stages_run=explanation.stages_run)
        except Exception:  # noqa: BLE001 - never fail a request over the audit write
            LOGGER.exception("audit write failed for event %s", verdict.event_id)
        trail = getattr(self.judge_provider, "last_attempts", None)
        if trail:
            # Which provider and which key INDEX served the judge call, joined to
            # the event id. Never the key itself: `JudgeAttempt.link` is
            # `openai[1]`, and there is no code path from a key to a log line.
            LOGGER.info("event %s judge trail: %s", verdict.event_id,
                        "; ".join(f"{a.link}={'served' if a.served else a.detail}"
                                  for a in trail))
        if decided.needs_review:
            LOGGER.warning("event %s ALLOWED with %d unjudged path(s) under "
                           "fail_mode=%s - queued for review", verdict.event_id,
                           len(verdict.unjudged), decided.fail_mode.value)
        if degraded:
            LOGGER.error("event %s decided in degraded mode: %s",
                         verdict.event_id, degraded)

    # ------------------------------------------------------------ streaming ---
    def stream(self, event: GuardEvent) -> Iterator[str]:
        """SSE frames, one per cascade stage, then the verdict, then done.

        A plain synchronous generator: the cascade is CPU-bound and Starlette
        runs a sync iterator on a worker thread, so this streams without an async
        rail interface and without blocking the event loop.

        `evaluate_iter` is suspended between yields, so each frame leaves this
        process before the next stage's rails run. That is the whole difference
        between a progress stream and a progress animation.
        """
        generator = self.cascade.evaluate_iter(event)
        outcome: CascadeOutcome | None = None
        degraded: str | None = None
        while True:
            try:
                progress = next(generator)
            except StopIteration as stop:
                outcome = stop.value
                break
            except Exception as exc:  # noqa: BLE001 - fail closed, mid-stream
                # The status line is long gone, so the failure has to be reported
                # inside the stream. A client that saw two stages and then silence
                # cannot tell a crash from an allow.
                outcome = self.fail_closed(event, exc)
                degraded = f"cascade raised {type(exc).__name__}"
                yield _sse("error", {
                    "event": "error",
                    "error": Error(code="cascade_failed",
                                   message="the cascade raised; failing closed with "
                                           "a BLOCK verdict and every payload path "
                                           "unjudged",
                                   details={"exception": type(exc).__name__}
                                   ).model_dump(exclude_none=True)})
                break
            yield _sse("stage", _stage_frame(progress, self.reveal_subject))

        assert outcome is not None  # both loop exits set it
        body, _ = self.finish(event, outcome, degraded=degraded)
        yield _sse("verdict", {"event": "verdict", **body})
        yield _sse("done", {"event": "done"})

    # ---------------------------------------------------------- introspection --
    def rail_rows(self) -> list[dict[str, Any]]:
        rows = []
        for rail in sorted(self.rails, key=lambda r: (int(r.stage), r.name)):
            available, reason = _rail_available(rail)
            rows.append({
                "name": rail.name,
                "tenet": rail.tenet.value,
                "stage": int(rail.stage),
                "stage_label": STAGE_LABELS[int(rail.stage)],
                "attribution": _attribution_dict(self.attributions.get(rail.name)),
                "available": available,
                "unavailable_reason": reason,
                # Which side of the AI system this rail guards. The engine has
                # gated on this since the input/output split, but the endpoint
                # did not expose it - so the console could not say which rails
                # guard a prompt and which guard a response without making a
                # live request and reading `rails_skipped` back out of the
                # trace. A rail with no declaration is BOTH; see
                # cascade/rail.py::Direction.
                "direction": getattr(rail, "direction", Direction.BOTH).value,
            })
        return rows

    def coverage(self) -> dict[str, Any]:
        """The capability coverage report, as data rather than a rendered table.

        Rebuilt per call on purpose: `register_rail` derives DEPENDENCY from a
        live `available()` probe, so a cached report would keep claiming
        `implemented` after the model weights were removed.
        """
        registry = CapabilityRegistry()
        not_registered: list[str] = []
        for package in TENET_PACKAGES:
            try:
                module = importlib.import_module(f"afni_rai.tenets.{package}")
                module.register(registry)
            except Exception as exc:  # noqa: BLE001 - a tenet that will not
                # register is a set of gaps, and must be named as one
                not_registered.append(f"{package}: {type(exc).__name__}: {exc}")
        report = registry.report()
        tenets = []
        for tenet, rows in report.by_tenet.items():
            counts = {c.value: n for c, n in report.counts(tenet).items()}
            tenets.append({
                "tenet": tenet.value,
                "counts": counts,
                "rows": [{"capability": row.capability, "status": row.status.value,
                          "note": row.note,
                          "attribution": _attribution_dict(row.attribution)}
                         for row in rows],
            })
        return {
            "totals": {c.value: n for c, n in report.total_counts().items()},
            "tenets": tenets,
            "not_registered": not_registered,
            "rendered": report.render(),
        }

    def target_health(self) -> dict[str, Any]:
        """The `target` block for `/healthz`: configured, reachable, and whether
        the model id is anything more than a string somebody typed.

        Reads the STARTUP probe rather than making a call. A health endpoint that
        reached out per hit would make this gateway's liveness depend on a third
        party's, and would point every monitoring poll at someone's inference
        server.
        """
        if self.target is None:
            return {
                "configured": False,
                "reachable": None,
                "model_id_verified": False,
                "api_key_configured": False,
                "note": (f"no target configured: set {ENV_TARGET_BASE_URL} and "
                         f"{ENV_TARGET_MODEL} to enable /v1/chat. Every other "
                         "endpoint works without them."),
            }
        config = self.target.config
        probe = self.target_probe
        verified = bool(probe.model_id_verified)
        return {
            "configured": True,
            "base_url": config.base_url,
            "model": config.model,
            "provider": self.target.provider,
            "timeout_s": config.timeout,
            "api_key_configured": config.api_key_configured,
            "reachable": probe.reachable,
            "model_id_verified": verified,
            "probe": probe.to_dict(),
            "note": ("model id VERIFIED against the endpoint's own /models "
                     "listing at startup" if verified else
                     f"UNVERIFIED: {config.model!r} is configuration, not a "
                     "fact - no response from this endpoint has confirmed it. "
                     "The startup probe is not repeated per healthz hit."),
        }

    def health(self) -> dict[str, Any]:
        rows = self.rail_rows()
        unavailable = [f"{r['name']}: {r['unavailable_reason']}"
                       for r in rows if r["available"] is False]
        absent = [{"module": module, "present": False, "powers": powers}
                  for module, powers in OPTIONAL_DEPENDENCIES
                  if importlib.util.find_spec(module) is None]
        judge = None
        if self.judge_provider is not None:
            describe = getattr(self.judge_provider, "describe", None)
            judge = describe() if callable(describe) else {
                "provider": getattr(self.judge_provider, "name", "custom")}
        target = self.target_health()
        # A CONFIGURED target that did not answer the startup probe is a
        # degradation: `/v1/chat` will return `target_error` until it comes back.
        # An ABSENT target is not - a judge-only gateway is a supported
        # deployment, and reporting it as degraded would make the honest state
        # indistinguishable from the broken one.
        target_down = bool(target["configured"]) and target["reachable"] is False
        return {
            "status": "degraded" if (self.problems or unavailable
                                     or self.judge_providers_skipped
                                     or target_down) else "ok",
            "protocol_version": PROTOCOL_VERSION,
            "rails_mounted": len(self.rails),
            "tenets_not_loaded": list(self.problems),
            "rails_unavailable": unavailable,
            "judge_rails_without_a_judge": providers.unbound_judge_rails(self.rails),
            "judge_providers_skipped": list(self.judge_providers_skipped),
            "dependencies_absent": absent,
            "judge_provider": judge,
            "reveal_subject": self.reveal_subject,
            "audit_db": self.audit_db,
            "target": target,
        }


# --------------------------------------------------------------------------- #
# SSE encoding                                                                 #
# --------------------------------------------------------------------------- #
def _sse(name: str, payload: dict[str, Any]) -> str:
    """One Server-Sent Event: a named event and one JSON object on a data line.

    The name is duplicated into the JSON body deliberately. `EventSource`
    consumers dispatch on the `event:` field; anything reading the stream as
    plain text (curl, a log, a test) only sees `data:`. Both should be able to
    tell a stage frame from a verdict without cross-referencing.
    """
    body = json.dumps(payload, separators=(",", ":"), default=str)
    return f"event: {name}\ndata: {body}\n\n"


def _stage_frame(progress: Any, reveal_subject: bool = False) -> dict[str, Any]:
    """One stage frame. The cumulative findings go out through the same
    subject-withholding rule as the final verdict - a streaming client must not be
    the way a matched secret gets out."""
    trace = progress.trace
    findings = [f.to_dict() for f in progress.findings]
    if not reveal_subject:
        for finding in findings:
            finding.pop("subject", None)
    return {
        "event": "stage",
        "stage": int(trace.stage),
        "ran": progress.ran,
        "rails_run": list(trace.rails_run),
        "rails_skipped": list(trace.rails_skipped),
        "findings": findings,
        "stage_findings": trace.findings,
        "unjudged": list(progress.unjudged),
        "short_circuited": progress.short_circuited,
        "will_escalate": progress.will_escalate,
        "stage_latency_ms": trace.latency_ms,
        "elapsed_ms": progress.elapsed_ms,
    }


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #
def _router(gateway: Gateway) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/guard", response_model=GuardResponse, tags=["decisions"],
                 summary="Judge one GuardEvent and return the verdict",
                 response_description=(
                     "The strict OpenGuardrails v0.8 verdict, plus the AFNI "
                     "attribution alongside it. Always 200 once the body parses - "
                     "read `verdict.decision`, never the status code."),
                 responses={
                     200: {"content": {"application/json": {
                         "example": GUARD_RESPONSE_EXAMPLE}}},
                     422: {"model": Error, "description":
                           "The body is not a valid GuardEvent. `details.fields` "
                           "names the offending field.",
                           "content": {"application/json": {"example": {
                               "code": "invalid_guard_event",
                               "message": "the request body is not a valid GuardEvent",
                               "details": {"fields": [{"loc": ["body", "step_id"],
                                                       "msg": "Field required",
                                                       "type": "missing"}]},
                               "request_id": "9f2c41ab7d8e4c1e"}}}}})
    def guard(body: GUARD_BODY, response: Response) -> JSONResponse:
        """Run the cascade and return the verdict with its attribution.

        Always HTTP 200 once the body parses, including when the cascade fails:
        the decision lives in `verdict.decision`, and a transport-level error
        code for a *judged* request would invite callers to treat a block as an
        outage. A cascade failure is reported as a BLOCK with every payload path
        in `unjudged`, plus an `x-afni-degraded` response header.
        """
        event = gateway.event(body)
        degraded: str | None = None
        try:
            outcome = gateway.cascade.evaluate(event)
        except Exception as exc:  # noqa: BLE001 - fail closed, never a 500
            outcome = gateway.fail_closed(event, exc)
            degraded = f"cascade raised {type(exc).__name__}"
        payload, _ = gateway.finish(event, outcome, degraded=degraded)
        headers = {"x-afni-degraded": degraded} if degraded else None
        return JSONResponse(payload, headers=headers)

    @router.post("/v1/guard/stream", tags=["decisions"],
                 summary="Judge one GuardEvent, streaming one event per stage",
                 response_class=StreamingResponse,
                 responses={200: {
                     "description":
                         "`text/event-stream`. One `stage` event per cascade "
                         "stage AS IT COMPLETES, then one `verdict` event, then "
                         "`done`. Every frame is a JSON object on a `data:` line, "
                         "with the event name repeated inside it so a plain-text "
                         "reader can tell the frames apart too.",
                     "content": {"text/event-stream": {
                         "schema": {"type": "string"},
                         "example": STREAM_RESPONSE_EXAMPLE}}}})
    def guard_stream(body: GUARD_BODY) -> StreamingResponse:
        """Server-Sent Events, one frame per stage, emitted as the stage finishes.

        The frames are not a replay of a finished decision. Each one is produced
        by `Cascade.evaluate_iter` suspending after that stage, so a client
        watching a `stage: 1` frame arrive knows Stage 2 has not run yet.
        """
        event = gateway.event(body)
        return StreamingResponse(
            gateway.stream(event),
            media_type="text/event-stream",
            headers={
                "cache-control": "no-cache",
                # Proxies that buffer would defeat the point of streaming.
                "x-accel-buffering": "no",
                "connection": "keep-alive",
            })

    def _target_or_error(request: Request) -> JSONResponse | None:
        """The one place `/v1/chat` and `/v1/chat/stream` refuse to run.

        503 rather than 500, in the standard `Error` shape, naming the two
        variables to set. A gateway with no target is misconfigured for THIS
        endpoint and perfectly configured for every other one, so the failure has
        to be legible enough that nobody goes looking for a bug in the cascade.
        """
        if gateway.target is not None:
            return None
        return JSONResponse(
            status_code=503,
            content=Error(
                code="target_not_configured",
                message=(f"no AI system is configured for this gateway to call: "
                         f"set {ENV_TARGET_BASE_URL} and {ENV_TARGET_MODEL}. "
                         f"/v1/guard and every introspection endpoint are "
                         f"unaffected."),
                details={
                    "set": [ENV_TARGET_BASE_URL, ENV_TARGET_MODEL],
                    "optional": [target_env.ENV_API_KEY, target_env.ENV_TIMEOUT,
                                 target_env.ENV_MAX_TOKENS],
                    "example": {ENV_TARGET_BASE_URL: "http://127.0.0.1:8000/v1",
                                ENV_TARGET_MODEL: "your-model-id"},
                    "why_503": ("this is a configuration gap on one endpoint, "
                                "not a failed decision - no guardrail was "
                                "bypassed and nothing was sent anywhere"),
                },
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(exclude_none=True))

    @router.post("/v1/chat", response_model=ChatResponse, tags=["decisions"],
                 summary="Guarded passthrough: guard the prompt, call the model, "
                         "guard the answer",
                 response_description=(
                     "All four steps of one interaction. `completion` is present "
                     "only when both guardrails allowed it; a blocked completion "
                     "is not in the response under any key."),
                 responses={
                     503: {"model": Error, "description":
                           "No target is configured. `details.set` names the two "
                           "environment variables to set. Every other endpoint "
                           "is unaffected."}})
    def chat(body: ChatRequest, request: Request) -> JSONResponse:
        """Guard the prompt, call the target, guard the completion - in that order.

        THE ORDER IS THE PRODUCT. A prompt the input guardrail blocks is never
        sent to the model, so it costs nothing: the response says
        `target.called: false` and `tokens_saved: true`, and there is no code
        path from that branch to the target client. A completion the output
        guardrail blocks never reaches the caller: it is absent from the
        response, the SSE frames, the log lines and the audit row, which stores
        fingerprints and has no column a completion could occupy.

        Every failure resolves the same way - fail closed. If either cascade
        raises, that guardrail returns a BLOCK (with `degraded` naming it, and
        an `x-afni-degraded` header). If the target errors or times out, the
        decision is `target_error` with no completion. HTTP 200 in all four
        cases: read `decision`, not the status code.
        """
        refusal = _target_or_error(request)
        if refusal is not None:
            return refusal
        payload = Passthrough(gateway).run(body)
        headers = ({"x-afni-degraded": "; ".join(payload["degraded"])}
                   if payload["degraded"] else None)
        return JSONResponse(payload, headers=headers)

    @router.post("/v1/chat/stream", tags=["decisions"],
                 summary="Guarded passthrough, streamed one guard stage at a time",
                 response_class=StreamingResponse,
                 responses={
                     200: {"description":
                           "`text/event-stream`. Input `stage` frames (each with "
                           "`phase: input`), then `target_start`, then "
                           "`target_done` or `target_error`, then output `stage` "
                           "frames (`phase: output`), then `final`, then `done`. "
                           "A client that never sees `target_start` knows the "
                           "prompt was refused before anything was spent. "
                           "`target_done` deliberately carries no text: the "
                           "completion appears only in `final`, and only if the "
                           "output guardrail allowed it.",
                           "content": {"text/event-stream": {
                               "schema": {"type": "string"}}}},
                     503: {"model": Error, "description":
                           "No target is configured."}})
    def chat_stream(body: ChatRequest, request: Request) -> Response:
        """The same four steps, as they happen.

        The frames are not a replay: each guard's stage frames are produced by
        `Cascade.evaluate_iter` suspending after that stage, and `target_start`
        is emitted before the POST to the model rather than after it.
        """
        refusal = _target_or_error(request)
        if refusal is not None:
            return refusal
        return StreamingResponse(
            Passthrough(gateway).stream(body),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache",
                     "x-accel-buffering": "no",
                     "connection": "keep-alive"})

    @router.get("/v1/coverage", tags=["introspection"], response_model=CoverageResponse,
                summary="Capability coverage, with the gaps counted")
    def coverage() -> JSONResponse:
        """65 capabilities across 7 tenets, each in one of five states.

        Five states rather than a covered/not bool because `implemented`,
        `dependency-missing` and `cloud-not-configured` are three different
        answers to "are we protected right now", and a single percentage would
        round two of them up.
        """
        return JSONResponse(gateway.coverage())

    @router.get("/v1/repositories", tags=["introspection"],
                summary="Every reviewed repository against what is built")
    def repository_status() -> JSONResponse:
        """The reviewed repositories grouped by adoption verdict, each
        cross-referenced against what this platform actually implements.

        `present_in_platform` means a rail cites the repo as the source of a
        pattern. That is provenance, not adoption: Safe Zone and Guardrails AI
        both appear despite being un-adopted, because their patterns were ported
        into stdlib rails.

        This replaced `/v1/phases`, which grouped the same repositories on a
        90-day adoption calendar. AFNI builds in one pass, so the calendar is
        gone and the adoption verdict is the grouping."""
        return JSONResponse(repositories.status())

    @router.get("/v1/rails", tags=["introspection"], response_model=RailsResponse,
                summary="Every mounted rail and its provenance")
    def rails() -> JSONResponse:
        return JSONResponse({
            "protocol_version": PROTOCOL_VERSION,
            "mounted": len(gateway.rails),
            "rails": gateway.rail_rows(),
            "tenets_not_loaded": list(gateway.problems),
        })

    @router.get("/healthz", tags=["introspection"], response_model=HealthResponse,
                summary="Liveness, plus what is missing")
    def healthz() -> JSONResponse:
        """`degraded` still serves traffic - and still fails closed, which is why
        a missing dependency is a degradation and not an outage. Unversioned:
        this describes the process, not the contract."""
        return JSONResponse(gateway.health())

    return router


def create_app(**kwargs: Any) -> FastAPI:
    """Build the app. Keyword arguments are forwarded to `Gateway`, which is how
    a test injects fake rails, an in-memory audit store or a stub judge.

    `warm=False` skips the Stage-2 model warm-up. Tests pass it: they inject stub
    rails with nothing to warm, and paying a real model load per test case would
    make the suite unusable.
    """
    warm = kwargs.pop("warm", True)
    gateway = Gateway(**kwargs)
    if warm:
        # BEFORE the app is returned, so uvicorn cannot start accepting traffic
        # until the models are resident. A guardrail that is slow to become ready
        # is fine; one that is ready and slow is not - and the measurement that
        # prompted this was a 15,568 ms first request on a freshly provisioned
        # machine, against a documented Stage-2 latency class of 10-500 ms.
        # A rail that fails to warm is not fatal: it reports `unjudged` at request
        # time and fails closed, the same honest degrade as never having the
        # weights at all.
        gateway.warm_results = warm_all(gateway.rails)
    app = FastAPI(
        title="AFNI Responsible AI gateway",
        version=f"1.0.0 (OpenGuardrails protocol {PROTOCOL_VERSION})",
        openapi_tags=TAGS_METADATA,
        description=(
            "Guardrail decisions over HTTP.\n\n"
            f"**The contract.** `verdict` is strict OpenGuardrails v{PROTOCOL_VERSION} "
            "and nothing is added to it - both `verdict` and `findings[]` are "
            "`additionalProperties: false` upstream, so everything AFNI-specific "
            "rides in `explanation` alongside it: which repo made the call, how "
            "confident, which entity, and where.\n\n"
            "**Read the decision, not the status code.** Once a body parses, every "
            "outcome is HTTP 200 - including a cascade failure, which comes back as "
            "a BLOCK with every payload path in `unjudged`. A 500 is ambiguous, and "
            "an ambiguous guardrail failure gets read as a pass by the next "
            "`try/except` up the stack.\n\n"
            "**`unjudged` is not 'clean'.** A non-empty value means 'could not "
            "look', which is not 'found nothing'. It ALWAYS blocks - there is no "
            "per-request switch. On a fresh install with no model weights the "
            "Stage-2 rails report `unjudged`, so expect blocks until the weights "
            "are installed or the rails are explicitly disabled - deliberate, and "
            "it will surprise you once.\n\n"
            "**Matched values are withheld.** A finding carries `fp`, a fingerprint, "
            "not the SSN or the API key it matched. Revealing is a server-side "
            "environment flag and deliberately not a request parameter.\n\n"
            "**Try it.** Every example in the request-body dropdown is a real "
            "payload verified to trip the tenet it names, plus one benign control "
            "that must trip nothing."),
    )
    app.state.gateway = gateway
    app.include_router(_router(gateway))
    # The corpus routes live in their own module: they are the only routes
    # that read a 6 MB data file and spend minutes of CPU on one request,
    # and keeping their schemas and their two hard caps next to each other
    # makes both reviewable in one screen.
    app.include_router(corpus_router(gateway))
    # The topic policy: the only WRITE endpoint here, kept in its own module
    # so the authorization note sits next to the handler that needs it.
    app.include_router(topics_router(gateway))

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable) -> Response:
        """One id per request, echoed back. It is what a caller quotes to support
        and what ties a client report to a line in this process's log.

        Stashed on `request.state` before the route runs so the error handler
        below reports the SAME id the caller gets in the header - two ids for one
        request is worse than none, because it makes a support trace ambiguous.
        """
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_body(request: Request,
                           exc: RequestValidationError) -> JSONResponse:
        """FastAPI's default 422 body is `{"detail": [...]}`, which is a second
        error shape. Mapped onto the one shape this API returns everywhere, with
        the field-level detail kept - an integrator debugging their own client
        needs to know WHICH field, not just that something was wrong.

        Only `loc`, `msg` and `type` survive. Pydantic also puts `input` in each
        error, which on this endpoint is the caller's whole `payload` - the prompt
        that may hold the SSN. Echoing it into an error body, and from there into
        every log between here and the caller, would leak on the validation path
        exactly what the success path is careful to withhold. The field name is
        what makes the error debuggable; the value adds nothing the caller does
        not already have.
        """
        rid = getattr(request.state, "request_id", None)
        fields = [{"loc": [str(part) for part in error.get("loc", ())],
                   "msg": str(error.get("msg", "")),
                   "type": str(error.get("type", ""))}
                  for error in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=Error(
                code="invalid_guard_event",
                message="the request body is not a valid GuardEvent",
                details={"fields": fields},
                request_id=rid,
            ).model_dump(exclude_none=True))

    _mount_console(app)
    return app


# --------------------------------------------------------------------------- #
# The operator console                                                         #
# --------------------------------------------------------------------------- #
def _mount_console(app: FastAPI) -> None:
    """Serve `rai_platform/web/` from this app's own origin at `/`.

    Same-origin is the point, and it is a security decision rather than a
    convenience one. The console reads `/healthz` and posts to `/v1/guard`, so
    the alternative to a static mount is CORS - and a guardrail gateway that
    sends `Access-Control-Allow-Origin` is a gateway any page on the internet
    can drive with the operator's cookies. Serving the console from here means
    the browser's same-origin policy does that work for free and no CORS header
    is needed anywhere.

    Mounted last, after every `/v1` route and after `/docs`, because a mount at
    `/` matches everything: registered earlier it would shadow the entire API.

    Absent directory is not an error. The gateway's job is judging events, and a
    missing console must not stop it from serving them - so this logs and returns
    rather than raising, and `/` then 404s like any other unrouted path.
    """
    console = Path(__file__).resolve().parents[2] / "web"
    if not (console / "index.html").is_file():
        LOGGER.warning(
            "operator console not mounted: no index.html under %s - the API is "
            "unaffected and every /v1 route still serves", console)
        return
    try:
        from fastapi.staticfiles import StaticFiles
    except ImportError:  # pragma: no cover - starlette ships it with fastapi
        LOGGER.warning("operator console not mounted: StaticFiles unavailable")
        return
    app.mount("/", StaticFiles(directory=str(console), html=True),
              name="console")
    LOGGER.info("operator console mounted at / from %s", console)


app_factory = create_app  # what `serve.py --factory` names
