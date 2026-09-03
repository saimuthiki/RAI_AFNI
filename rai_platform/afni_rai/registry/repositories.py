# -*- coding: utf-8 -*-
"""
The reviewed repositories, their adoption verdict, and whether each is actually
wired into this platform.

This file replaces `phases.py`, which carried the same repository facts arranged
on a 90-day, three-phase adoption calendar. AFNI's decision (2026-09-03) is to
build the platform in one pass rather than in phases, so the calendar dimension
is gone. What the calendar was WRAPPED AROUND is kept, because it is the part
that was ever load-bearing:

  * the adoption verdict per repo - adopt, combine, bench, skip
  * why that verdict, in one sentence
  * whether the verdict is conditional on something outside our control
  * and the cross-reference that makes this a status board rather than a
    document: "we said adopt garak - is garak actually wired here, and how?"

Why this is curated data and not a regex over the analysis prose: a naive scan
put Deepchecks, Guardrails AI and Agentic Security alongside the adopted repos,
because the roadmap text *mentioned* all three - one for a legal ruling, two as
vendor-risk items to log. None was adopted. "Named" and "adopted" are different
facts, and conflating them would put a wrong table in front of a client. That
hazard survives the removal of phases, so the curation does too.

Zero third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Adoption(str, Enum):
    ADOPT = "Adopt now"
    COMBINE = "Combine with another"
    BENCH = "Bench for later"
    SKIP = "Skip"


#: Display order. Adopted first, then combined, then benched, then skipped -
#: so the table reads most-relevant-first without needing a phase number.
ADOPTION_ORDER: tuple[Adoption, ...] = (
    Adoption.ADOPT, Adoption.COMBINE, Adoption.BENCH, Adoption.SKIP,
)


@dataclass(frozen=True)
class RepoEntry:
    repo: str
    display: str
    adoption: Adoption
    why: str                   # what this repo contributes, and on what terms
    conditional: bool = False  # verdict gated on something outside our control


INVENTORY: tuple[RepoEntry, ...] = (
    # ------------------------------------------------------------- adopt now --
    RepoEntry("Guardrails-develop", "NVIDIA NeMo Guardrails", Adoption.ADOPT,
              "The gateway runs as a FastAPI service on the NeMo rail pattern, "
              "with the jailbreak rail flipped from its fail-open default."),
    RepoEntry("openguardrails-main", "OpenGuardrails", Adoption.ADOPT,
              "The GuardEvent/Verdict schemas and taxonomy are AFNI's internal "
              "contract, pinned to the pre-1.0 protocol version."),
    RepoEntry("llm-guard-main", "LLM Guard", Adoption.ADOPT,
              "Forked into an AFNI-owned repo with every model revision pinned; "
              "the free deterministic tier is enabled first."),
    RepoEntry("garak-main", "NVIDIA garak", Adoption.ADOPT,
              "Red-team scan against an existing AFNI application, published as "
              "the before picture. Offline - never in the request path."),
    RepoEntry("promptfoo-main", "Promptfoo", Adoption.ADOPT,
              "OWASP-mapped redteam runs, plus deterministic assertions in the "
              "fast CI tier."),
    RepoEntry("PyRIT-main", "PyRIT", Adoption.ADOPT,
              "Regex output scorers in the fast CI tier - free and deterministic, "
              "so they fit a five-minute pull-request gate."),
    RepoEntry("deepeval-main", "DeepEval", Adoption.ADOPT,
              "Deterministic assertions in the fast CI tier alongside promptfoo."),
    RepoEntry("fairlearn-main", "Fairlearn", Adoption.ADOPT,
              "For any application making decisions about people, as a scheduled "
              "batch job - never a runtime check."),
    RepoEntry("shap-master", "SHAP", Adoption.ADOPT,
              "Tabular and text explanations behind an async explain endpoint - "
              "SHAP is too slow for synchronous handling."),
    RepoEntry("deepteam-main", "DeepTeam", Adoption.ADOPT,
              "Agentic vulnerability probes in the slow nightly tier."),

    # ------------------------------------------------- combine with another --
    RepoEntry("hai-guardrails-main", "hai-guardrails", Adoption.COMBINE,
              "Its healthcare PHI regexes (ICD-10, MRN, NPI, DEA) and "
              "entropy-gated secret patterns, ported into Presidio custom "
              "recognisers."),
    RepoEntry("rebuff-main", "Rebuff", Adoption.COMBINE,
              "Canary-token leak detection and the self-hardening attack-signature "
              "store, reimplemented as native rails."),
    RepoEntry("AIF360-main", "AIF360", Adoption.COMBINE,
              "The MDSS and FACTS subgroup scanners layered behind Fairlearn, for "
              "audits that find the biased subgroup rather than needing it named."),
    RepoEntry("Infosys-Responsible-AI-Toolkit-master", "Infosys RAI Toolkit",
              Adoption.COMBINE,
              "Vendor the genuinely unique modules only where the business needs "
              "them: multi-format/DICOM PII, NSFW media, Faker anonymisation.",
              conditional=True),

    # -------------------------------------------------------- bench for later --
    RepoEntry("evals-main", "OpenAI Evals", Adoption.BENCH,
              "The deception / sandbagging / covert-persuasion suite, run once "
              "against any product claiming agent autonomy before it ships."),
    RepoEntry("deepchecks-main", "Deepchecks", Adoption.BENCH,
              "Drift and data-quality suites in the nightly tier. Benched on a "
              "TECHNICAL ground, not a licence one: every check is a batch "
              "SingleDatasetCheck/TrainTestCheck over a Dataset, so there is no "
              "per-request API to put on a request path at all."),
    RepoEntry("agentic_security-main", "Agentic Security", Adoption.BENCH,
              "A red-team fuzzer, not a runtime defence. Overlaps garak and PyRIT, "
              "which are already adopted."),
    RepoEntry("safe-zone-main", "Safe Zone (TSZ)", Adoption.BENCH,
              "Patterns were read and ported where useful; the Go service itself "
              "is not adopted."),
    RepoEntry("giskard-oss-main", "Giskard v3", Adoption.BENCH,
              "LLM/agent-only since the v3 rewrite, and every check needs a paid "
              "judge. Its sycophancy check is the unique draw, for CI later."),
    RepoEntry("FuzzyAI-main", "FuzzyAI", Adoption.BENCH,
              "Offline fuzzer requiring MongoDB; overlaps PyRIT and garak, which "
              "are already adopted."),

    # -------------------------------------------------------------------- skip --
    RepoEntry("guardrails-main", "Guardrails AI", Adoption.SKIP,
              "Ships base classes only - every real validator is a separate PyPI "
              "package, and the Hub deprecation affects a share of them. Carries "
              "a documented historical PyPI supply-chain compromise, so any "
              "adoption must pin and vendor rather than resolve at install time. "
              "AFNI has asked for it to be integrated regardless; that verdict "
              "change is tracked separately from the removal of phases."),
    RepoEntry("JCB-main", "JCB", Adoption.SKIP,
              "A HarmBench fork shipping only its own method and two of the "
              "pipeline's steps. Its 0.6 similarity threshold was read and reused."),
    RepoEntry("LLMFuzzer-main", "LLMFuzzer", Adoption.SKIP,
              "Narrow, high effort, and contributes no checklist item at all."),
)

BY_REPO: dict[str, RepoEntry] = {e.repo: e for e in INVENTORY}


def for_adoption(adoption: Adoption) -> list[RepoEntry]:
    return [e for e in INVENTORY if e.adoption is adoption]


def status() -> dict:
    """Cross-reference the inventory against what the platform implements.

    This is the point of the module. It answers the question a repository list
    on its own cannot: of the repos we said to adopt, which are wired here, and
    in what state? A verdict of "adopt now" whose repo shows nothing is an
    intention, not progress.
    """
    from .capabilities import CapabilityRegistry

    registry = CapabilityRegistry()
    for pkg in ("privacy", "security", "fairness", "explainability",
                "content_safety", "hallucination", "accountability"):
        try:
            import importlib
            module = importlib.import_module(f"afni_rai.tenets.{pkg}")
            module.register(registry)
        except Exception:  # noqa: BLE001 - a tenet that will not load is a gap
            continue
    report = registry.report()

    built: dict[str, set[str]] = {}
    for _tenet, rows in report.by_tenet.items():
        for row in rows:
            if row.attribution is None:
                continue
            built.setdefault(row.attribution.source_repo, set()).add(row.status.value)

    groups = []
    for adoption in ADOPTION_ORDER:
        entries = []
        for entry in for_adoption(adoption):
            states = sorted(built.get(entry.repo, ()))
            entries.append({
                "repo": entry.repo,
                "display": entry.display,
                "adoption": entry.adoption.value,
                "conditional": entry.conditional,
                "why": entry.why,
                # Coverage states this repo backs in the running platform.
                "implemented_as": states,
                # Deliberately NOT called "adopted". A repo shows up here when a
                # rail cites it as the source of a pattern, which is provenance,
                # not a dependency. Safe Zone, Guardrails AI and Agentic Security
                # all appear despite being un-adopted, because their regexes and
                # validator shapes were ported into stdlib rails. Reading this as
                # "we adopted 3 repos we said we would skip" would be wrong.
                "present_in_platform": bool(states),
            })
        groups.append({"adoption": adoption.value, "repos": entries})

    return {
        "groups": groups,
        # Honesty about the join itself: `status()` links a repo to the platform
        # through `RailAttribution.source_repo`, so a capability registered
        # without an attribution cannot be linked at all and reads as absent.
        # SHAP is the live example - it is registered OFFLINE under
        # Explainability with no attribution, so it shows as missing when the
        # truth is "registered, unattributed".
        "unlinkable": _unattributed(report),
    }


def _unattributed(report) -> list[str]:
    """Capabilities registered with no attribution, so no repo can be linked."""
    out = []
    for tenet, rows in report.by_tenet.items():
        for row in rows:
            if row.attribution is None and row.status.value != "gap":
                out.append(f"{tenet.value}: {row.capability} ({row.status.value})")
    return out
