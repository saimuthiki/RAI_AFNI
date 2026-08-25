# -*- coding: utf-8 -*-
"""
Builds data/tenet_methodology_data.json - the per-tenet methodology tables.

Inputs
------
data/tenet_methodology_facts.json
    Per-repo, per-tenet mechanism facts gathered by reading the actual source
    under references/. Each entry carries an `evidence` field naming the
    file:line, model id or dependency it was derived from.
data/RAI_Synthesis.json
    `master_aspect_list` decides which repos appear under which tenet (a repo
    is listed for a tenet iff it is credited with at least one checklist item
    for it); `tenet_matrix[].cloud_paid_options` supplies the Stage-3 band.

Derivation
----------
`latency` and `stage` are NOT taken from the facts file. They are derived here,
in one place, so the two columns stay internally consistent across all seven
slides instead of varying with whoever wrote a given fact row.

A tool often offers several mechanisms for one tenet at very different costs -
LLM Guard's Security cover is both deterministic secret/unicode scanning AND a
DeBERTa classifier. The two columns therefore answer two different questions:

  latency = the RANGE across the mechanism list, cheapest to dearest, so a
            mixed row reads "Very low-Low" rather than hiding either half.
  stage   = the EARLIEST stage at which the tool can contribute, taken from its
            CHEAPEST mechanism. This is the cascade question - "can this run on
            every request, or only after something else has already filtered?"
            Judging a mixed row by its slowest part would wrongly disqualify a
            tool that has a perfectly good deterministic first pass.

Anything off the request path is Batch/Offline regardless, and a tool that
needs a paid API for this tenet is Stage 3 regardless of mechanism.

Run directly to regenerate the JSON. Output is deterministic - re-running with
unchanged inputs produces a byte-identical file.
"""
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_ROOT, "data")

FACTS_PATH = os.path.join(_DATA_DIR, "tenet_methodology_facts.json")
SYNTHESIS_PATH = os.path.join(_DATA_DIR, "RAI_Synthesis.json")
OUT_PATH = os.path.join(_DATA_DIR, "tenet_methodology_data.json")

TENET_ORDER = [
    "Privacy", "Security", "Fairness & Bias", "Explainability & Transparency",
    "Profanity / Content Safety", "Hallucination / Reliability", "Accountability",
]

# Short display labels, keyed by references/ folder name. Kept separate from
# repo_slide_content.REPO_SLIDES["display_name"], which is too long for a table
# cell (and diverges from the capability-matrix labels for 11 repos).
DISPLAY = {
    "agentic_security-main": "Agentic Security",
    "AIF360-main": "AIF360",
    "deepchecks-main": "Deepchecks",
    "deepeval-main": "DeepEval",
    "deepteam-main": "DeepTeam",
    "evals-main": "OpenAI Evals",
    "fairlearn-main": "Fairlearn",
    "FuzzyAI-main": "FuzzyAI",
    "garak-main": "garak",
    "giskard-oss-main": "Giskard v3",
    "Guardrails-develop": "NeMo Guardrails",
    "guardrails-main": "Guardrails AI",
    "hai-guardrails-main": "hai-guardrails",
    "Infosys-Responsible-AI-Toolkit-master": "Infosys RAI Toolkit",
    "JCB-main": "JCB",
    "LLMFuzzer-main": "LLMFuzzer",
    "llm-guard-main": "LLM Guard",
    "openguardrails-main": "OpenGuardrails",
    "promptfoo-main": "Promptfoo",
    "PyRIT-main": "PyRIT",
    "rebuff-main": "Rebuff",
    "safe-zone-main": "Safe Zone (TSZ)",
    "shap-master": "SHAP",
}

# ------------------------------------------------------- DERIVATION RULES ----
# Latency rank per mechanism. Rank 0-3 are request-path tiers in increasing
# cost; rank 4 means the mechanism cannot run inline at all.
_MECH_LATENCY = {
    "Keyword/Regex": (0, "Very low"),
    "Module": (0, "Very low"),
    "Classifier": (1, "Low"),
    "NLI/Cross-encoder": (1, "Low"),
    "Cloud API": (2, "Medium"),
    "LLM-judge": (3, "High"),
    "Statistical": (4, "Batch"),
    "Attack generator": (4, "Batch"),
}

_PAID_REQUIRED = {"Needs paid API", "Paid"}

# Abbreviations that keep the narrow columns inside their QA width budget.
_COST_SHORT = {
    "Free": "Free",
    "Free + optional paid": "Free (+opt paid)",
    "Needs paid API": "Paid API req.",
    "Paid": "Paid",
}
_LOCALITY_SHORT = {
    "Local": "Local",
    "Remote": "Remote",
    "Local + remote option": "Local/remote",
}


def derive_latency(mechanisms, in_request_path):
    """The range across the mechanism list, so a mixed row hides neither half."""
    if not in_request_path:
        return "Batch"
    tiers = sorted({_MECH_LATENCY[m] for m in mechanisms}, key=lambda t: t[0])
    if len(tiers) == 1:
        return tiers[0][1]
    return f"{tiers[0][1]}-{tiers[-1][1]}"


def derive_stage(mechanisms, cost, in_request_path, ships_own_detector=True):
    """Earliest stage the tool can contribute, from its CHEAPEST mechanism."""
    if not in_request_path:
        return "Offline"
    if not ships_own_detector:
        # Provides the contract/taxonomy/orchestration but no detector of its
        # own for this tenet, so it cannot occupy a cascade stage at all.
        return "Delegates"
    if cost in _PAID_REQUIRED:
        return "Stage 3"
    cheapest = min(_MECH_LATENCY[m][0] for m in mechanisms)
    if cheapest == 0:        # deterministic module / regex - runs on everything
        return "Stage 1"
    if cheapest in (1, 2):   # local model, or a cloud second opinion
        return "Stage 2"
    if cheapest == 3:        # LLM judge is the only option here
        return "Stage 3"
    return "Offline"         # statistical / attack-generator only


def _repos_per_tenet(synthesis):
    """A repo belongs to a tenet iff it is credited with >=1 checklist item."""
    out = {t: [] for t in TENET_ORDER}
    for aspect in synthesis["master_aspect_list"]:
        tenet = aspect["tenet"]
        for repo in aspect["source_repos"]:
            if repo not in out[tenet]:
                out[tenet].append(repo)
    return out


def build():
    with open(FACTS_PATH, encoding="utf-8") as f:
        facts = json.load(f)
    with open(SYNTHESIS_PATH, encoding="utf-8") as f:
        synthesis = json.load(f)

    by_repo = {entry["repo"]: entry for entry in facts["repos"]}
    per_tenet = _repos_per_tenet(synthesis)
    cloud = {t["tenet"]: t["cloud_paid_options"] for t in synthesis["tenet_matrix"]}

    # Stage sort order puts the cheap, fast, always-on tools at the top - the
    # reading order the cascade design actually needs.
    stage_rank = {"Stage 1": 0, "Stage 2": 1, "Stage 3": 2, "Delegates": 3, "Offline": 4}

    result = {}
    for tenet in TENET_ORDER:
        rows = []
        for repo in per_tenet[tenet]:
            entry = by_repo.get(repo)
            if entry is None or tenet not in entry["tenets"]:
                # A repo credited in the checklist but with no verified
                # mechanism is dropped rather than guessed at.
                continue
            fact = entry["tenets"][tenet]
            mechanisms = fact["mechanism"]
            latency = derive_latency(mechanisms, fact["in_request_path"])
            stage = derive_stage(mechanisms, fact["cost"], fact["in_request_path"],
                                 fact.get("ships_own_detector", True))
            rows.append({
                "repo": DISPLAY[repo],
                "repo_folder": repo,
                "mechanism": " + ".join(mechanisms),
                "functionality": fact["functionality"],
                "cost": _COST_SHORT[fact["cost"]],
                "latency": latency,
                "locality": _LOCALITY_SHORT[fact["locality"]],
                "target": fact["target"],
                "stage": stage,
                "evidence": fact["evidence"],
            })
        rows.sort(key=lambda r: (stage_rank[r["stage"]], r["repo"].lower()))
        result[tenet] = {
            "columns": ["Repository", "Mechanism", "What it does for this tenet",
                        "Cost", "Latency", "Runs", "Target", "Stage"],
            "rows": rows,
            "cloud_options": cloud.get(tenet, []),
        }
    return result


if __name__ == "__main__":
    data = build()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT_PATH}")
    for tenet, d in data.items():
        stages = {}
        for r in d["rows"]:
            stages[r["stage"]] = stages.get(r["stage"], 0) + 1
        summary = "  ".join(f"{k}:{v}" for k, v in sorted(stages.items()))
        print(f"  {tenet:32s} {len(d['rows']):2d} rows   {summary}")
