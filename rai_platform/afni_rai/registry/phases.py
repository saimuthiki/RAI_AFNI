# -*- coding: utf-8 -*-
"""
Roadmap phase per repository, and how it lines up with what is actually built.

Why this is curated data and not a regex over the roadmap prose: a naive scan of
`RAI_Synthesis.json` -> `roadmap_phases[].actions` puts Deepchecks, Guardrails AI
and Agentic Security in Phase 1, because Phase 1 *mentions* all three - one for a
legal ruling on its AGPL licence, two as vendor-risk items to log. None of them
is adopted. "Named in a phase" and "adopted in a phase" are different facts, and
conflating them would put a wrong table in front of a client.

So each entry records the phase where the repo is first genuinely USED, the
roadmap action that puts it there, and its adoption verdict from the feasibility
matrix. `PHASE_NOTES` carries the repos a phase only talks about.

The `status()` helper is the part worth having: it cross-references the plan
against the platform's own capability registry, so the roadmap becomes a status
board rather than a document - "Phase 1 says adopt garak; is garak actually
wired here, and how?"
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    P1 = "Phase 1 (0-30 days)"
    P2 = "Phase 2 (30-60 days)"
    P3 = "Phase 3 (60-90 days)"
    NONE = "Not adopted"


class Adoption(str, Enum):
    ADOPT = "Adopt now"
    COMBINE = "Combine with another"
    BENCH = "Bench for later"
    SKIP = "Skip"


@dataclass(frozen=True)
class PhaseEntry:
    repo: str
    display: str
    phase: Phase
    adoption: Adoption
    why: str                 # the roadmap action that places it
    conditional: bool = False  # placed, but gated on something outside our control


ROADMAP: tuple[PhaseEntry, ...] = (
    # ---------------------------------------------------------------- Phase 1 --
    PhaseEntry("Guardrails-develop", "NVIDIA NeMo Guardrails", Phase.P1, Adoption.ADOPT,
               "Stand up the gateway as a FastAPI service running NeMo Guardrails, "
               "with the jailbreak rail flipped from its fail-open default."),
    PhaseEntry("openguardrails-main", "OpenGuardrails", Phase.P1, Adoption.ADOPT,
               "Adopt the GuardEvent/Verdict schemas and taxonomy as AFNI's internal "
               "contract, pinning the pre-1.0 protocol version."),
    PhaseEntry("llm-guard-main", "LLM Guard", Phase.P1, Adoption.ADOPT,
               "Fork into an AFNI-owned repo, pin every model revision, and enable "
               "the free deterministic tier first."),
    PhaseEntry("garak-main", "NVIDIA garak", Phase.P1, Adoption.ADOPT,
               "Baseline red-team scan against one existing AFNI application, "
               "published as the before picture."),
    PhaseEntry("promptfoo-main", "Promptfoo", Phase.P1, Adoption.ADOPT,
               "Baseline OWASP-mapped redteam run, then the fast CI tier's "
               "deterministic assertions."),
    PhaseEntry("PyRIT-main", "PyRIT", Phase.P1, Adoption.ADOPT,
               "Regex output scorers in the fast CI tier - free and deterministic, "
               "so they fit a five-minute pull-request gate."),
    PhaseEntry("deepeval-main", "DeepEval", Phase.P1, Adoption.ADOPT,
               "Deterministic assertions in the fast CI tier alongside promptfoo."),

    # ---------------------------------------------------------------- Phase 2 --
    PhaseEntry("hai-guardrails-main", "hai-guardrails", Phase.P2, Adoption.COMBINE,
               "Port its healthcare PHI regexes (ICD-10, MRN, NPI, DEA) and "
               "entropy-gated secret patterns into Presidio custom recognisers."),
    PhaseEntry("rebuff-main", "Rebuff", Phase.P2, Adoption.COMBINE,
               "Reimplement canary-token leak detection and the self-hardening "
               "attack-signature store as native rails."),
    PhaseEntry("fairlearn-main", "Fairlearn", Phase.P2, Adoption.ADOPT,
               "Adopt for any application making decisions about people, as a "
               "scheduled batch job - never a runtime check."),
    PhaseEntry("AIF360-main", "AIF360", Phase.P2, Adoption.COMBINE,
               "Layer the MDSS and FACTS subgroup scanners behind Fairlearn, for "
               "audits that find the biased subgroup rather than needing it named."),
    PhaseEntry("shap-master", "SHAP", Phase.P2, Adoption.ADOPT,
               "Adopt for tabular and text explanations behind an async explain "
               "endpoint - SHAP is too slow for synchronous handling."),

    # ---------------------------------------------------------------- Phase 3 --
    PhaseEntry("deepteam-main", "DeepTeam", Phase.P3, Adoption.ADOPT,
               "Agentic vulnerability probes in the slow nightly tier."),
    PhaseEntry("evals-main", "OpenAI Evals", Phase.P3, Adoption.BENCH,
               "Run the deception / sandbagging / covert-persuasion suite once "
               "against any product claiming agent autonomy, before it ships."),
    PhaseEntry("deepchecks-main", "Deepchecks", Phase.P3, Adoption.BENCH,
               "Drift and data-quality suites in the nightly tier - explicitly "
               "'where licensing allows'.", conditional=True),
    PhaseEntry("Infosys-Responsible-AI-Toolkit-master", "Infosys RAI Toolkit",
               Phase.P3, Adoption.COMBINE,
               "Vendor the genuinely unique modules only if the business needs "
               "them: multi-format/DICOM PII, NSFW media, Faker anonymisation.",
               conditional=True),

    # ------------------------------------------------------------- Not adopted --
    PhaseEntry("guardrails-main", "Guardrails AI", Phase.NONE, Adoption.SKIP,
               "Ships base classes only - every real validator is a separate PyPI "
               "package. Also carries a documented PyPI supply-chain compromise. "
               "Phase 1 names it solely to log that risk."),
    PhaseEntry("agentic_security-main", "Agentic Security", Phase.NONE, Adoption.BENCH,
               "Phase 1 names it only to log its hard-coded third-party bearer "
               "token. A red-team fuzzer, not a runtime defence."),
    PhaseEntry("safe-zone-main", "Safe Zone (TSZ)", Phase.NONE, Adoption.BENCH,
               "Patterns were read and ported where useful; the Go service itself "
               "is not adopted."),
    PhaseEntry("giskard-oss-main", "Giskard v3", Phase.NONE, Adoption.BENCH,
               "LLM/agent-only since the v3 rewrite, and every check needs a paid "
               "judge. Its sycophancy check is the unique draw, for CI later."),
    PhaseEntry("FuzzyAI-main", "FuzzyAI", Phase.NONE, Adoption.BENCH,
               "Offline fuzzer requiring MongoDB; overlaps PyRIT and garak, which "
               "are already adopted."),
    PhaseEntry("JCB-main", "JCB", Phase.NONE, Adoption.SKIP,
               "A HarmBench fork shipping only its own method and two of the "
               "pipeline's steps."),
    PhaseEntry("LLMFuzzer-main", "LLMFuzzer", Phase.NONE, Adoption.SKIP,
               "Narrow, high effort, and contributes no checklist item at all."),
)

# What a phase merely TALKS about, so nobody reads a mention as an adoption.
PHASE_NOTES: dict[Phase, tuple[str, ...]] = {
    Phase.P1: (
        "Names Deepchecks only to get a legal ruling on its AGPL-3.0 licence.",
        "Names promptfoo's remote-only plugins as a data-residency question.",
        "Names Guardrails AI's PyPI supply-chain compromise as a risk to log.",
        "Names Agentic Security's hard-coded bearer token as a risk to log.",
    ),
    Phase.P2: (),
    Phase.P3: (
        "Deepchecks and the Infosys modules are both conditional, not committed.",
    ),
    Phase.NONE: (),
}

BY_REPO: dict[str, PhaseEntry] = {e.repo: e for e in ROADMAP}


def for_phase(phase: Phase) -> list[PhaseEntry]:
    return [e for e in ROADMAP if e.phase is phase]


def status() -> dict:
    """Cross-reference the plan against what the platform actually implements.

    This is the point of the module. It answers the question a roadmap on its own
    cannot: of the repos Phase 1 commits to, which are wired here, and in what
    state? A phase whose repos are all `gap` is a plan, not progress.
    """
    from ..contract.models import Tenet
    from .capabilities import CapabilityRegistry, Coverage

    registry = CapabilityRegistry()
    built: dict[str, set[str]] = {}
    for pkg in ("privacy", "security", "fairness", "explainability",
                "content_safety", "hallucination", "accountability"):
        try:
            import importlib
            module = importlib.import_module(f"afni_rai.tenets.{pkg}")
            module.register(registry)
        except Exception:  # noqa: BLE001 - a tenet that will not load is a gap
            continue
    report = registry.report()
    for tenet, rows in report.by_tenet.items():
        for row in rows:
            if row.attribution is None:
                continue
            built.setdefault(row.attribution.source_repo, set()).add(row.status.value)

    out: dict = {}
    for phase in (Phase.P1, Phase.P2, Phase.P3, Phase.NONE):
        entries = []
        for entry in for_phase(phase):
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
        out[phase.value] = {
            "repos": entries,
            "notes": list(PHASE_NOTES[phase]),
            # Honesty about the join itself: `status()` links a repo to the
            # platform through `RailAttribution.source_repo`, so a capability
            # registered without an attribution cannot be linked at all and
            # reads as absent. SHAP is the live example - it is registered
            # OFFLINE under Explainability with no attribution, so it shows as
            # missing from Phase 2 when the truth is "registered, unattributed".
            "unlinkable": _unattributed(report),
        }
    return out


def _unattributed(report) -> list[str]:
    """Capabilities registered with no attribution, so no repo can be linked."""
    out = []
    for tenet, rows in report.by_tenet.items():
        for row in rows:
            if row.attribution is None and row.status.value != "gap":
                out.append(f"{tenet.value}: {row.capability} ({row.status.value})")
    return out
