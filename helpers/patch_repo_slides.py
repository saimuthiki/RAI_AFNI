# -*- coding: utf-8 -*-
"""Adds tier / vendor / build_replicate fields to every entry in
repo_slide_content.py, and re-serializes the file. Run once."""
import ast
import pprint
from repo_slide_content import REPO_SLIDES

ENRICH = {
    "agentic_security-main": ("Tier 2", "Independent (Alexander Miasoiedov)",
        "Moderate - the attack/scoring pipeline is easy to script, but the hidden cloud-calling module (hard-coded token) must be stripped out first"),
    "AIF360-main": ("Tier 1", "IBM",
        "N/A, consume as-is - mature, peer-reviewed algorithms; re-implementing them would waste effort better spent integrating"),
    "deepchecks-main": ("Tier 2", "Deepchecks",
        "Moderate - clean API, but AGPL-3.0 licensing needs legal clearance before embedding in a client deliverable"),
    "deepeval-main": ("Tier 1", "Confident AI",
        "Easy - drop-in pytest plugin; the work is authoring golden test cases, not building the tool"),
    "deepteam-main": ("Tier 1", "Confident AI",
        "Easy - one-line red_team() call once the target is wrapped; the attack taxonomy is already built"),
    "evals-main": ("Tier 2", "OpenAI",
        "Moderate - CLI/registry workflow needs a custom adapter before it can be called from a live backend"),
    "fairlearn-main": ("Tier 1", "Microsoft",
        "N/A, consume as-is - Azure-aligned and peer-reviewed; adopt directly rather than rebuild"),
    "FuzzyAI-main": ("Tier 2", "CyberArk",
        "Moderate - clean plugin API, but the heavier attacks need GPU-backed local models"),
    "garak-main": ("Tier 1", "NVIDIA",
        "Moderate - reusing one detector is easy; the CLI/harness/plugin-cache system is the real design centre and expects a full Generator adapter"),
    "giskard-oss-main": ("Tier 2", "Giskard AI",
        "Moderate - clean Scenario/Suite API, but the v3 rewrite is Beta and much of its attack coverage is borrowed via garak/DeepTeam bridges"),
    "Guardrails-develop": ("Tier 1", "NVIDIA",
        "Moderate - the Colang orchestration pattern is replicable in-house, but rebuilding NVIDIA's fine-tuned NemoGuard safety models needs a labelled dataset and training budget AFNI doesn't have"),
    "guardrails-main": ("Tier 2", "Guardrails AI, Inc.",
        "Easy - the Guard/validator/reask pattern is simple to replicate, but there is little reason to; adopt the free core and track the Aug 2026 Hub migration"),
    "hai-guardrails-main": ("Tier 2", "presidio-dev (independent, unrelated to Microsoft Presidio)",
        "Easy - a small, well-factored TypeScript SDK, but needs a Node microservice bridge to call from AFNI's Python stack"),
    "Infosys-Responsible-AI-Toolkit-master": ("Tier 1", "Infosys",
        "Hard - already OSS, so the real question is self-host TCO, not replication; standing up 20+ microservices, Elasticsearch, MongoDB and an Angular front end is a multi-week platform effort"),
    "JCB-main": ("Tier 3", "Academic (Vasudev Gohil, single-paper artifact)",
        "Hard - heavy GPU plus paid-judge dependency to reproduce, and it exists to attack, not defend; useful only as an occasional external stress test"),
    "LLMFuzzer-main": ("Tier 3", "Independent, officially unmaintained",
        "Easy - trivial to replicate, but not worth adopting as-is; borrow its two attack ideas as seeds instead"),
    "llm-guard-main": ("Tier 1", "Protect AI",
        "Easy - free, MIT-licensed, pip-installable; the only real work is standing up the FastAPI gateway and tuning which scanners run inline vs. sampled"),
    "openguardrails-main": ("Tier 2", "OpenGuardrails community",
        "N/A, schema only - the maintainers themselves say 'we do not build detection capability'; there is a contract to adopt, not code to replicate"),
    "promptfoo-main": ("Tier 1", "promptfoo / OpenAI",
        "Moderate - quick to bolt onto CI via its CLI, but a Python backend can't import it natively (Node/TypeScript) and many plugins are remote-only"),
    "PyRIT-main": ("Tier 1", "Microsoft AI Red Team",
        "Hard - the attack/scorer abstractions are clean, but the memory layer, async surface, and large dependency tree make this a genuine platform commitment, not a quick pilot"),
    "rebuff-main": ("Tier 2", "Protect AI",
        "Easy - about 10 lines of code to call; the real cost is a paid OpenAI key and a Pinecone index for two of its three tactics"),
    "safe-zone-main": ("Tier 2", "Thyris",
        "Moderate - a self-hosted Go service; core detection is free, but needs Postgres and Redis running alongside it"),
    "shap-master": ("Tier 1", "Community / academic (Lundberg et al.)",
        "N/A, consume as-is - mature, Nature-published, industry-standard; no reason to rebuild Shapley-value estimation in-house"),
}

for r in REPO_SLIDES:
    tier, vendor, build = ENRICH[r["repo_folder"]]
    r["tier"] = tier
    r["vendor"] = vendor
    r["build_replicate"] = build

missing = [r["repo_folder"] for r in REPO_SLIDES if "tier" not in r]
assert not missing, f"missing enrichment for: {missing}"

header = '''# -*- coding: utf-8 -*-
"""
Plain-English slide copy for each of the 23 repositories.
Hand-written summaries (by the assistant) derived from the deep-dive reports
in RAI_Repo_Reports.json, simplified for a client-facing deck, enriched with
tier/vendor/build-vs-buy framing.
"""

REPO_SLIDES = '''

with open("repo_slide_content.py", "w", encoding="utf-8") as f:
    f.write(header)
    f.write(pprint.pformat(REPO_SLIDES, width=118, sort_dicts=False))
    f.write("\n\n# Sanity check helper\nif __name__ == \"__main__\":\n"
            "    print(f\"{len(REPO_SLIDES)} repo slide entries defined\")\n"
            "    folders = [r[\"repo_folder\"] for r in REPO_SLIDES]\n"
            "    assert len(folders) == len(set(folders)), \"duplicate repo_folder!\"\n")

print("Patched and rewrote repo_slide_content.py")
