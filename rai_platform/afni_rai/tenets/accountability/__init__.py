# -*- coding: utf-8 -*-
"""
Accountability - the tenet that is mostly infrastructure rather than detectors.

The other six tenets wrap somebody else's detector. This one does not, and the
analysis is explicit about why: three of the things AFNI needs here have no
upstream equivalent in any of the 23 reviewed repos.

  1. the consolidated verdict          NeMo Guardrails does not produce one
  2. threshold configuration           nobody has it; Infosys has the admin
                                       shape but never reads the value back
  3. the loud-failure policy           OpenGuardrails *specifies* it, no repo
                                       enforces it, and NeMo's own jailbreak
                                       rail is documented fail-OPEN

(1) is `contract/models.py:Verdict` plus `cascade/engine.py`, already built.
(2) and (3) are `thresholds.py` and `policy.py` here.

WHAT IS IN THIS PACKAGE

    policy.py       fail_mode per risk category, layered on top of the
                    engine's rule rather than duplicating it
    thresholds.py   global defaults plus an operator override layer, with a read
                    log so "was it actually consulted?" is a testable fact
    audit.py        the verdict store - stdlib sqlite3, one schema for live and
                    offline, and structurally incapable of storing a subject
    remediation.py  the four request-flow mitigation branches and a dispatcher
    frameworks.py   Finding.category -> OWASP LLM / NIST AI RMF / MITRE ATLAS /
                    EU AI Act / ISO 42001 / GDPR control ids
    tracing.py      OpenTelemetry spans, degrading to local recording when
                    opentelemetry is absent
    gating.py       OFFLINE. The CI exit-code contract agentic_security omits
    corpus.py       the local half of Rebuff's self-hardening loop, as a Stage-1
                    rail

WHAT IS DELIBERATELY NOT HERE

    Governance dashboards      Azure Monitor / Application Insights. A UI is not
                               a Python module, and Infosys's is the only
                               single-UI option in the set.
    Detector accuracy self-eval  PyRIT's `scorer_evaluation` with Krippendorff's
                               alpha against human labels. Offline, quarterly,
                               and it needs a labelled corpus that does not exist
                               yet. Registered OFFLINE, not faked.

Every Stage-1 thing in here is pure stdlib: `re`, `hashlib`, `sqlite3`,
`unicodedata`, `time`. No network at import, no model weights, no third-party
package.
"""
from __future__ import annotations

from ...cascade.rail import RailSpec, Stage
from ...contract.explanation import RailAttribution
from ...contract.models import Tenet
from ...registry.capabilities import Coverage
from .audit import (ORIGIN_LIVE, ORIGIN_OFFLINE, ORIGIN_REPLAY, RingEvent,
                    SecurityEvent, Summary, TraceRow, VerdictStore, scan_for_leak)
from .corpus import ATTRIBUTION as RAIL_ATTRIBUTION
from .corpus import (AttackCorpus, AttackCorpusRail, AttackEntry, CorpusHit,
                     jaccard, normalise)
from .frameworks import (CATEGORY_TO_CONTROLS, FRAMEWORKS, ComplianceMapper,
                         ComplianceReport, ControlRef, Framework)
from .gating import (DEFAULT_MAX_FAILURE_RATE, FastTierGate, GateReport,
                     SuiteResult, from_failure_percentages)
from .policy import (AFNI_DEFAULT, FailMode, FailurePolicy, ModeDecision,
                     PolicyOutcome, engine_enforces_fail_closed)
from .remediation import (ON_FAIL_INTEROP, Remediation, RemediationAction,
                          RemediationDispatcher, RemediationPlan,
                          from_on_fail_action)
from .thresholds import (GLOBAL_DEFAULTS, ThresholdOverrides, ThresholdMisconfigured,
                         ThresholdRead, ThresholdScope, ThresholdStore)
from .tracing import SpanRecorder

TENET = Tenet.ACCOUNTABILITY

# --------------------------------------------------------------------------- #
# The one mountable rail this tenet contributes.
#
# Accountability is infrastructure, so the rail count is low on purpose. A rail
# invented to pad it - a "logging rail", a "policy rail" - would be a rail that
# runs on 100% of traffic to do something the gateway already does once per
# request, and the coverage report would look better for no gain in protection.
#
# The module-level corpus is empty at import: nothing is read from disk, no
# network call is made, and the rail is a clean no-op until an operator or a CI
# run confirms a first attack. A deployment binds its own corpus and threshold
# store at gateway construction; the rail reads the threshold per request.
# --------------------------------------------------------------------------- #
DEFAULT_CORPUS = AttackCorpus()
DEFAULT_THRESHOLDS = ThresholdStore()

ATTACK_CORPUS_RAIL = AttackCorpusRail(DEFAULT_CORPUS, DEFAULT_THRESHOLDS)

RAILS = [ATTACK_CORPUS_RAIL]

# The loader in `cli.py` and the gateway both read `ATTRIBUTIONS` off the tenet
# package, keyed by rail name. `corpus.py` has always defined the attribution,
# but this package only re-exported it as the singular `RAIL_ATTRIBUTION`, which
# nothing looks for - so a block from this rail arrived at the caller with no
# repo, no mechanism and no confidence kind, printing bare "attack-corpus-repeat
# flagged ...". That defeats the one thing an explanation exists to say. Keyed
# off the mounted rails rather than off `ATTRIBUTION.rail`, so renaming a rail
# cannot silently orphan its attribution again.
ATTRIBUTIONS = {rail.name: RAIL_ATTRIBUTION for rail in RAILS}

RAIL_SPECS = [
    RailSpec(
        rail=ATTACK_CORPUS_RAIL,
        source_repo="rebuff-main",
        mechanism="Keyword/Regex - normalised sha256 fingerprint plus exact "
                  "Jaccard over the hashed word set",
        evidence="rebuff-main/python-sdk/rebuff/sdk.py:205-221; "
                 "JCB-main/eval_utils.py:240-242,247,264",
        capability="Self-hardening attack corpus",
    ),
]


# --------------------------------------------------------------------------- #
# Attributions. One per capability, so the coverage report can say *which*
# upstream tool a claim rests on and where it was read.
# --------------------------------------------------------------------------- #
def _attr(rail: str, repo: str, display: str, mechanism: str, stage: int,
          evidence: str, capability: str) -> RailAttribution:
    return RailAttribution(
        rail=rail, source_repo=repo, display_name=display, mechanism=mechanism,
        stage=stage, confidence_kind="deterministic", evidence=evidence,
        capability=capability)


FAIL_CLOSED_ATTRIBUTION = _attr(
    rail="cascade-engine-fail-closed",
    repo="openguardrails-main",
    display="OpenGuardrails fail_mode contract, enforced in the AFNI engine",
    mechanism="Module - engine-level consolidation; any unjudged path blocks, "
              "with per-category fail_mode overrides",
    stage=int(Stage.STAGE_1),
    evidence="openguardrails specification/degraded-mode.md:22-49 and "
             "schema/verdict.schema.json:140; enforced at "
             "afni_rai/cascade/engine.py Cascade._decide; NeMo's own jailbreak "
             "rail is fail-OPEN at "
             "Guardrails-develop/docs/configure-rails/guardrail-catalog/"
             "jailbreak-protection.mdx:112",
    capability="Fail-closed / unjudged policy")

THRESHOLD_ATTRIBUTION = _attr(
    rail="threshold-store",
    repo="Infosys-Responsible-AI-Toolkit-master",
    display="Infosys admin ModerationCheckThreshold, collapsed to one scope",
    mechanism="Module - override/global threshold resolution with a read log; "
              "misconfiguration yields unjudged, never a default",
    stage=int(Stage.STAGE_1),
    evidence="responsible-ai-admin/.../mappers/FmConfigMapper.py:66-113 and "
             ":116-123; anti-pattern avoided: safe-zone-main "
             "internal/handlers/admin.go:66-67 stores per-pattern thresholds "
             "that internal/guardrails/thresholds.go:8-24 never reads",
    capability="Threshold configuration")

AUDIT_ATTRIBUTION = _attr(
    rail="verdict-store",
    repo="guardrails-main",
    display="Guardrails AI SQLite call tracing, plus Safe Zone's SIEM event shape",
    mechanism="Module - stdlib sqlite3 verdict/finding/attribution/span tables, "
              "50-event ring buffer, [AUDIT] log line, caller-supplied SIEM sink",
    stage=int(Stage.STAGE_1),
    evidence="guardrails-main/guardrails/call_tracing/sqlite_trace_handler.py:63-73 "
             "(CREATE TABLE guard_logs, WAL); safe-zone-main "
             "internal/guardrails/siem.go:16-39, internal/models/"
             "security_event.go:5-14, internal/metrics/store.go:18-42",
    capability="Audit trail / call history")

REMEDIATION_ATTRIBUTION = _attr(
    rail="remediation-dispatcher",
    repo="guardrails-main",
    display="Guardrails AI OnFailAction, mapped onto AFNI's four branches",
    mechanism="Module - four request-flow mitigations (block/refuse, mask & "
              "continue, flag/regenerate, block tool call) plus interop with "
              "upstream's eight-value enum",
    stage=int(Stage.STAGE_1),
    evidence="guardrails-main/guardrails/types/on_fail.py:24-31 (eight values, "
             "no mask/allow/block) and :33-45; branches from "
             "knowledge/request-flow.md §'Four things that are easy to get wrong'",
    capability="On-fail remediation actions")

FRAMEWORK_ATTRIBUTION = _attr(
    rail="compliance-mapper",
    repo="promptfoo-main",
    display="promptfoo framework mappings, inverted onto the AFNI taxonomy",
    mechanism="Module - Finding.category prefix -> control ids across six "
              "frameworks, via promptfoo's control->plugin tables",
    stage=int(Stage.STAGE_1),
    evidence="promptfoo-main/src/redteam/constants/frameworks.ts:8-18 (names), "
             ":74-173 OWASP LLM Top 10, :396-485 NIST AI RMF, :487-663 MITRE "
             "ATLAS, :674-776 EU AI Act, :782-831 ISO 42001, :841-920 GDPR",
    capability="Compliance-framework mapping")

TRACING_ATTRIBUTION = _attr(
    rail="span-recorder",
    repo="Guardrails-develop",
    display="NeMo Guardrails OpenTelemetry span adapter",
    mechanism="Module - OpenTelemetry API-only span export, guarded lazy import, "
              "no-op fallback that still writes every span to the audit store",
    stage=int(Stage.STAGE_1),
    evidence="Guardrails-develop/nemoguardrails/tracing/adapters/"
             "opentelemetry.py:62-70 (raise on ImportError - deliberately not "
             "copied), :103-112 (NoOpTracerProvider warning), :117 (schema url), "
             ":120-137 (span tree)",
    capability="OpenTelemetry tracing")

GATING_ATTRIBUTION = _attr(
    rail="fast-tier-ci-gate",
    repo="agentic_security-main",
    display="agentic_security failure-rate gate, with the missing exit code",
    mechanism="Statistical - per-suite failure rate vs max_th, plus baseline "
              "regression detection and a non-zero process exit",
    stage=int(Stage.OFFLINE),
    evidence="agentic_security-main/agentic_security/lib.py:72 computes PASS/FAIL "
             "and config.py:107 sets max_th=0.3, but lib.py's only exit(1) at "
             ":206 is for a missing config file and __main__.py:30-35 returns "
             "None, so the process always exits 0",
    capability="CI/CD test-gating")

SELF_EVAL_ATTRIBUTION = _attr(
    rail="scorer-accuracy-eval",
    repo="PyRIT-main",
    display="PyRIT ScorerEvaluator with Krippendorff's alpha",
    mechanism="Statistical - detector scores against human labels; "
              "krippendorff_alpha_combined / _humans / _model, plus MAE and "
              "accuracy per harm",
    stage=int(Stage.OFFLINE),
    evidence="PyRIT-main/pyrit/score/scorer_evaluation/krippendorff.py and "
             "scorer_metrics.py:136,140-141 (HarmScorerMetrics."
             "krippendorff_alpha_combined); doc/code/scoring/4_scorer_metrics.py",
    capability="Detector accuracy self-eval")

DASHBOARD_ATTRIBUTION = _attr(
    rail="governance-dashboard",
    repo="Infosys-Responsible-AI-Toolkit-master",
    display="Azure Monitor / Application Insights (Infosys is the only single-UI "
            "open option)",
    mechanism="Cloud API - OpenTelemetry ingestion, workbooks and alerting over "
              "the same spans tracing.py emits",
    stage=int(Stage.STAGE_3),
    evidence="knowledge/tenets.md:98-100 names Azure Monitor / Application "
             "Insights (or Azure AI Foundry Observability) as the cloud pick; "
             "knowledge/methodology.md Accountability row lists Monitaur / "
             "Fiddler / DataRobot / Purview as the vendor alternatives",
    capability="Governance dashboards")


def register(registry) -> None:
    """Register every Accountability capability, honestly.

    Ten capabilities, and the statuses are not uniform on purpose:

      IMPLEMENTED (6)  runs today, pure stdlib, no external anything
      DEPENDENCY  (1)  OpenTelemetry tracing - the rest of the trail works, but
                       nothing is exported until opentelemetry-api is installed
      OFFLINE     (2)  CI/CD gating and detector self-eval; claiming either as
                       runtime cover would be false
      CLOUD       (1)  governance dashboards
      GAP         (0)

    The OpenTelemetry status is *probed*, not asserted: `SpanRecorder.available`
    performs the guarded lazy import and checks for a real TracerProvider. If a
    deployment installs opentelemetry-api and configures a provider, this
    registration flips to IMPLEMENTED on its own, and if it does not, the report
    says DEPENDENCY. Hardcoding either would make the coverage number a claim
    instead of a measurement.
    """
    # ---- IMPLEMENTED ------------------------------------------------------- #
    registry.register(
        TENET, "Fail-closed / unjudged policy", Coverage.IMPLEMENTED,
        FAIL_CLOSED_ATTRIBUTION,
        note="Enforced in cascade/engine.py (Cascade._decide blocks ANY request "
             "with an unjudged path, unconditionally; Cascade._run turns a "
             "rail exception into unjudged rather than dropping the check). "
             "policy.FailurePolicy adds the per-category fail_mode "
             "OpenGuardrails degraded-mode.md:46-49 requires; the fallback is "
             "closed, there is no per-request switch that relaxes it, and "
             "fail_mode=open never suppresses the report.")
    registry.register(
        TENET, "Threshold configuration", Coverage.IMPLEMENTED,
        THRESHOLD_ATTRIBUTION,
        note="ThresholdStore resolves override -> global -> rail "
             "default -> last resort, logs every read, and all 11 "
             "threshold-bearing rails now consult it through "
             "CheckContext.threshold(). Earlier this was registered DEPENDENCY "
             "because exactly one consumer read the store - the same shape as "
             "the Safe Zone bug it was built to avoid, where admin.go:66 writes "
             "a threshold guardrails.go:287 never reads. The bar for this "
             "registration is an OUTCOME difference, not a read: "
             "test_threshold_wiring.py drives one identical payload through one "
             "rail at two configured thresholds and asserts it blocks at one and "
             "passes at the other. Keys are mechanism-specific (…toxicity.classifier vs "
             "…toxicity.judge) because a classifier probability and a judge's "
             "self-report are not one scale, and a shared knob would let an "
             "operator tighten one while loosening the other. Each default is "
             "the value its rail was ported with, so wiring changed no detection "
             "behaviour. A misconfigured value falls back to that default rather "
             "than becoming unjudged - unjudged fails closed, so one typo would "
             "take all traffic down - and the read is labelled "
             "rail-default-after-resolver-error so it stays distinguishable from "
             "a value nobody set.")
    registry.register(
        TENET, "Audit trail / call history", Coverage.IMPLEMENTED,
        AUDIT_ATTRIBUTION,
        note="audit.VerdictStore persists every verdict - live, offline or "
             "replay - in one schema, with findings, redaction spans, spans and "
             "the full RailAttribution per finding. The findings table has no "
             "subject column, so matched values cannot be stored even by "
             "mistake; a test scans every value in every table to prove it. "
             "SIEM delivery is a caller-supplied callable, so this module makes "
             "no network call.")
    registry.register(
        TENET, "On-fail remediation actions", Coverage.IMPLEMENTED,
        REMEDIATION_ATTRIBUTION,
        note="remediation.RemediationDispatcher implements the four branches the "
             "request-flow slide specifies, which Guardrails AI's eight-value "
             "OnFailAction does not cover - it has no mask, allow or block. "
             "ON_FAIL_INTEROP maps upstream's eight onto AFNI's five for "
             "applications already written against it.")
    registry.register(
        TENET, "Compliance-framework mapping", Coverage.IMPLEMENTED,
        FRAMEWORK_ATTRIBUTION,
        note="All six promptfoo frameworks transcribed and inverted onto "
             "Finding.category. OWASP LLM Top 10, NIST AI RMF (21 MEASURE "
             "controls), ISO 42001 and GDPR are complete. MITRE ATLAS and the EU "
             "AI Act are PARTIAL and say so in Framework.completeness: "
             "mitre:atlas:ai-model-access has no upstream plugins "
             "(frameworks.ts:501), and only EU AI Act Art.5 and Annex III are "
             "mapped - Art.9/12/13/14 are process controls no detector finding "
             "can evidence. owasp:llm:03 and nist:ai:measure:2.12 are likewise "
             "empty upstream and are carried as declared-but-unevidenceable.")
    registry.register_rail(
        ATTACK_CORPUS_RAIL, RAIL_ATTRIBUTION, available=True,
        note="Stage 1. Rebuff's log_leakage loop (sdk.py:205-221) reimplemented "
             "locally: confirm() appends a confirmed attack, and check() blocks "
             "an exact replay by normalised fingerprint or a near-repeat by "
             "exact Jaccard over the hashed word set (JCB's mechanism and its "
             "0.6 threshold). The corpus keeps no plaintext by default. NOT "
             "implemented and NOT claimed: Rebuff's embedding half (Pinecone + "
             "OpenAI ada-002), which is what catches a reworded attack - so "
             "recall here is lower than Rebuff's, and a paraphrase gets through. "
             "That half is cloud and is unconfigured.")

    # ---- DEPENDENCY -------------------------------------------------------- #
    recorder = SpanRecorder()
    registry.register(
        TENET, "OpenTelemetry tracing",
        Coverage.IMPLEMENTED if recorder.available else Coverage.DEPENDENCY,
        TRACING_ATTRIBUTION,
        note="tracing.SpanRecorder records every span into the audit store's "
             "spans table with zero dependencies, and exports via the "
             "OpenTelemetry API when it is installed and a real TracerProvider "
             "is configured. Probed at registration: "
             + ("export ACTIVE. " if recorder.available
                else f"export NOT active - {recorder.degraded_reason} ")
             + "The local trail survives either way, which is why NeMo's "
               "raise-on-ImportError (opentelemetry.py:62-70) was not copied.")

    # ---- OFFLINE ----------------------------------------------------------- #
    registry.register(
        TENET, "CI/CD test-gating", Coverage.OFFLINE, GATING_ATTRIBUTION,
        note="gating.FastTierGate is CI-only and is never mounted - the Cascade "
             "constructor raises on an OFFLINE rail, and this is not even a rail "
             "(no check method, so it cannot satisfy the Rail protocol). What is "
             "implemented is the exit-code contract agentic_security omits: "
             "GateReport.exit_code is 1 on any failure or baseline regression, "
             "and render_junit() emits the JUnit shape Deepchecks and Giskard "
             "already produce. The suites themselves (garak, promptfoo, PyRIT, "
             "DeepEval) are external and run in CI.")
    registry.register(
        TENET, "Detector accuracy self-eval", Coverage.OFFLINE,
        SELF_EVAL_ATTRIBUTION,
        note="PyRIT's scorer_evaluation compares detector scores against human "
             "labels and reports Krippendorff's alpha. Quarterly, offline, and "
             "it needs a human-labelled AFNI corpus that does not exist yet. "
             "Nothing here implements it; a measured F1 per detector is the "
             "output, and asserting one before the corpus exists would be the "
             "vendor claim this tenet is meant to replace.")

    # ---- CLOUD ------------------------------------------------------------- #
    registry.register(
        TENET, "Governance dashboards", Coverage.CLOUD, DASHBOARD_ATTRIBUTION,
        note="Azure Monitor / Application Insights, ingesting the same "
             "OpenTelemetry spans tracing.py emits, is the cloud pick "
             "(tenets.md:98-100). Infosys is the only reviewed option with one "
             "UI spanning all seven tenets, but it is ~20 FastAPI services and "
             "multi-GB model weights - not a dashboard AFNI can lift out. Not "
             "configured, so not counted as cover.")


__all__ = [
    "RAILS", "RAIL_SPECS", "TENET", "register", "RAIL_ATTRIBUTION",
    "ATTRIBUTIONS",
    # policy / fail-closed
    "FailMode", "FailurePolicy", "PolicyOutcome", "ModeDecision",
    "AFNI_DEFAULT", "engine_enforces_fail_closed",
    # thresholds
    "ThresholdStore", "ThresholdOverrides", "ThresholdRead", "ThresholdScope",
    "ThresholdMisconfigured", "GLOBAL_DEFAULTS",
    # audit
    "VerdictStore", "SecurityEvent", "RingEvent", "Summary", "TraceRow",
    "scan_for_leak", "ORIGIN_LIVE", "ORIGIN_OFFLINE", "ORIGIN_REPLAY",
    # remediation
    "RemediationAction", "Remediation", "RemediationPlan",
    "RemediationDispatcher", "ON_FAIL_INTEROP", "from_on_fail_action",
    # compliance
    "ComplianceMapper", "ComplianceReport", "ControlRef", "Framework",
    "FRAMEWORKS", "CATEGORY_TO_CONTROLS",
    # tracing
    "SpanRecorder",
    # ci gate
    "FastTierGate", "GateReport", "SuiteResult", "from_failure_percentages",
    "DEFAULT_MAX_FAILURE_RATE",
    # corpus
    "AttackCorpus", "AttackCorpusRail", "AttackEntry", "CorpusHit",
    "ATTACK_CORPUS_RAIL", "DEFAULT_CORPUS", "DEFAULT_THRESHOLDS",
    "jaccard", "normalise",
]
