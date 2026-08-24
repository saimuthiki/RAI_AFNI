# -*- coding: utf-8 -*-
"""Builds the 7 tenet capability-matrix datasets from RAI_Synthesis.json,
with manual delegation overrides and virtual cloud/Presidio columns."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

with open(os.path.join(DATA_DIR, "RAI_Synthesis.json"), encoding="utf-8") as f:
    SYN = json.load(f)

# Hand-picked capabilities per tenet, chosen from RAI_Synthesis.json's master_aspect_list
# (matched below by substring against each aspect's full name) to build the 7 capability
# matrix slides. Kept inline (rather than a throwaway intermediate JSON) so this script is
# reproducible on its own.
SELECTED_ASPECTS = {
    "Privacy": [
        "Presidio-backed PII entity detection and redaction",
        "National / government ID detection across jurisdictions",
        "Credit card detection with Luhn checksum validation",
        "Healthcare PHI entities (ICD-10, MRN, NPI, DEA, medical licence)",
        "LLM-as-judge PII leakage detection",
        "System-prompt and configuration leakage detection",
        "PII leakage red-team probing (ProPILE twin/triplet/quadruplet patterns)",
        "Reversible anonymisation with a vault for later re-identification",
        "Multi-format and multi-modal PII scanning (PDF, Office, images/OCR, DICOM, video)",
    ],
    "Security": [
        "Regex / phrase-list prompt-injection and jailbreak detection",
        "Fine-tuned transformer prompt-injection classifier",
        "LLM-as-judge prompt-injection scoring",
        "Multi-turn iterative jailbreaks (Crescendo, TAP, PAIR, GOAT, Tree, Linear, ActorAttack)",
        "Encoding and obfuscation attacks (base64, ROT13, leetspeak, morse, unicode tags, ASCII art, steganography)",
        "Secrets and credential leak regex scanning",
        "Invisible-text, zero-width and ASCII-smuggling detection",
        "Indirect / latent prompt injection via documents, RAG chunks and web content",
        "Insecure-output-handling scorers (SQLi, XSS, SSRF, SSTI, XXE, path traversal, LDAP, shell)",
    ],
    "Fairness & Bias": [
        "LLM-output bias detection by demographic axis (LLM-as-judge)",
        "Group fairness disparity metrics (demographic parity, equalised odds, equal opportunity, disparate impact)",
        "Pre-processing bias mitigation (Reweighing, Disparate Impact Remover, CorrelationRemover, LFR)",
        "Post-processing bias mitigation (ThresholdOptimizer, calibrated equalised odds, reject option, reranking)",
        "In-processing bias mitigation (adversarial debiasing, exponentiated gradient, grid search, prejudice remover)",
        "Automated biased-subgroup discovery (MDSS, FACTS, GerryFair, weak segments)",
        "Bias red-team probe packs (age, disability, gender, race, LMRC risk cards)",
        "Local model-based bias classifier for text",
        "Standard bias benchmark harnesses (BBQ, EquityMedQA, TrustLLM fairness)",
    ],
    "Explainability & Transparency": [
        "Structured-output and JSON-schema contract enforcement",
        "Topic-adherence / on-topic scope classification",
        "Custom natural-language rubric judges with reasons (G-Eval, llm-rubric, Conformity, DAG)",
        "Shapley-value feature attribution across model families (Tree, Kernel, Deep, Gradient, Linear, GPU)",
        "Token-level attribution for text and generative models",
        "Per-check confidence breakdown showing which layer fired and why",
        "LIME local surrogate explanations",
        "Counterfactual recourse and minimal-change action optimisation",
        "Deterministic format validators (regex, length, range, choices, valid URL, one-line)",
    ],
    "Profanity / Content Safety": [
        "Transformer toxicity classifier (Detoxify, roberta-toxicity, unbiased-toxic-roberta)",
        "LLM-as-judge toxicity, hate-speech and harassment classification",
        "Managed safety-model integration (Llama Guard, ShieldGemma, Azure Content Safety, Perspective, OpenAI Moderation)",
        "Multi-category harm taxonomy (self-harm, sexual, violence, weapons/CBRN, illegal, child exploitation)",
        "Profanity wordlist, slur list and substring blocklist filtering",
        "Zero-shot / NER-model PII detection beyond a fixed taxonomy",
        "Adult / explicit text content detection",
        "NSFW image and video frame detection",
        "Harmful-content red-team datasets (HarmBench, BeaverTails, DoNotAnswer, AdvBench, ToxicChat, Aegis, XSTest)",
    ],
    "Hallucination / Reliability": [
        "LLM-as-judge groundedness and faithfulness",
        "NLI / entailment-based groundedness scoring",
        "Refusal and over-refusal detection (phrase list, ML classifier, LLM judge, NoRefusal)",
        "RAG retrieval-quality metrics (contextual precision, recall, relevance, answer relevancy)",
        "Deterministic regression matchers (exact, fuzzy, includes, JSON match, schema validity)",
        "Structural output validation with automatic repair and re-ask",
        "Academic capability and truthfulness benchmark harnesses (MMLU, TruthfulQA, HellaSwag, TrustLLM, 463-eval registry)",
        "Fabrication probes for fake citations, APIs, entities and statistics",
        "Package / dependency hallucination detection",
        "Dedicated hallucination-evaluation models (Vectara, Patronus Lynx)",
    ],
    "Accountability": [
        "Compliance-framework mapping and reporting (OWASP LLM Top 10, NIST AI RMF, MITRE ATLAS, EU AI Act, ISO 42001, GDPR)",
        "CI-gateable pass/fail condition system with JUnit and JSON export",
        "Named on-fail remediation actions (allow, mask, block, filter, refrain, re-ask, fix)",
        "Per-call execution history and persistent audit trail",
        "OpenTelemetry tracing of guardrail execution",
        "Governance dashboards, leaderboards and report artefacts",
        "Fail-open versus fail-closed degraded-mode contract with unjudged reporting",
        "Detector accuracy self-evaluation against human labels",
        "Per-tenant threshold and policy configuration service",
        "Self-hardening attack-signature corpus that learns from confirmed incidents",
    ],
}


def _lookup_source_repos():
    by_name = {a["aspect"]: a["source_repos"] for a in SYN["master_aspect_list"]}
    out = {}
    for tenet, aspects in SELECTED_ASPECTS.items():
        out[tenet] = []
        for a in aspects:
            if a not in by_name:
                raise KeyError(f"aspect not found in master_aspect_list: {tenet} | {a}")
            out[tenet].append({"aspect": a, "source_repos": by_name[a]})
    return out


SELECTED = _lookup_source_repos()

TENET_REPOS = {t["tenet"]: t["open_source_repos"] for t in SYN["tenet_matrix"]}

CODE = {
    "agentic_security-main": "AS", "AIF360-main": "AIF", "deepchecks-main": "DCk",
    "deepeval-main": "DEv", "deepteam-main": "DTm", "evals-main": "OAE",
    "fairlearn-main": "FLn", "FuzzyAI-main": "FZ", "garak-main": "GRK",
    "giskard-oss-main": "GSK", "Guardrails-develop": "NeMo", "guardrails-main": "GAI",
    "hai-guardrails-main": "HAI", "Infosys-Responsible-AI-Toolkit-master": "INF",
    "JCB-main": "JCB", "LLMFuzzer-main": "LMF", "llm-guard-main": "LG",
    "openguardrails-main": "OGR", "promptfoo-main": "PF", "PyRIT-main": "PyR",
    "rebuff-main": "RB", "safe-zone-main": "TSZ", "shap-master": "SHAP",
}
DISPLAY = {
    "agentic_security-main": "Agentic Security", "AIF360-main": "AIF360", "deepchecks-main": "Deepchecks",
    "deepeval-main": "DeepEval", "deepteam-main": "DeepTeam", "evals-main": "OpenAI Evals",
    "fairlearn-main": "Fairlearn", "FuzzyAI-main": "FuzzyAI", "garak-main": "garak",
    "giskard-oss-main": "Giskard", "Guardrails-develop": "NeMo Guardrails", "guardrails-main": "Guardrails AI",
    "hai-guardrails-main": "hai-guardrails", "Infosys-Responsible-AI-Toolkit-master": "Infosys RAI Toolkit",
    "JCB-main": "JCB", "LLMFuzzer-main": "LLMFuzzer", "llm-guard-main": "LLM Guard",
    "openguardrails-main": "OpenGuardrails", "promptfoo-main": "Promptfoo", "PyRIT-main": "PyRIT",
    "rebuff-main": "Rebuff", "safe-zone-main": "Safe Zone (TSZ)", "shap-master": "SHAP",
}

# Virtual (non-repo) reference columns per tenet: (code, display, why-relevant hint used for manual marking)
VIRTUAL_COLS = {
    "Privacy": [("PSD", "Presidio*")],
    "Security": [("AzPS", "Azure Prompt Shields"), ("AWSB", "AWS Bedrock GR")],
    "Fairness & Bias": [("AzML", "Azure ML RAI"), ("Fid", "Fiddler AI")],
    "Explainability & Transparency": [("AzML", "Azure ML RAI"), ("AIX", "IBM AIX360")],
    "Profanity / Content Safety": [("AzCS", "Azure Content Safety"), ("OAIM", "OpenAI Moderation")],
    "Hallucination / Reliability": [("AzGD", "Azure Groundedness"), ("Ptr", "Patronus Lynx")],
    "Accountability": [("AzMon", "Azure Monitor"), ("Mon", "Monitaur/Fiddler")],
}

# Manual overrides: (tenet, aspect substring, repo_folder_or_code) -> status symbol, for known
# delegation/partial cases the automated source_repos membership can't express.
OVERRIDES = {
    ("Privacy", "Presidio-backed", "Guardrails-develop"): "◐",  # NeMo: 100% Presidio dependency
    ("Privacy", "Presidio-backed", "llm-guard-main"): "●",
    ("Security", "LLM-as-judge prompt-injection", "Guardrails-develop"): "◐",
    ("Profanity / Content Safety", "Managed safety-model", "Guardrails-develop"): "●",
    ("Fairness & Bias", "LLM-output bias detection", "giskard-oss-main"): "◐",
    ("Hallucination / Reliability", "LLM-as-judge groundedness", "giskard-oss-main"): "●",
}

# Manual cloud/virtual-column marks per (tenet, aspect substring): dict of code -> symbol
CLOUD_MARKS = {
    "Privacy": {
        "Presidio-backed": {"PSD": "●"},
        "National / government ID": {"PSD": "●"},
        "Credit card": {"PSD": "●"},
        "Healthcare PHI": {"PSD": "◐"},
        "LLM-as-judge PII leakage": {"PSD": "–"},
        "System-prompt and configuration leakage": {"PSD": "–"},
        "PII leakage red-team": {"PSD": "–"},
        "Reversible anonymisation": {"PSD": "●"},
        "Multi-format and multi-modal PII": {"PSD": "◐"},
    },
    "Security": {
        "Regex / phrase-list": {"AzPS": "◐", "AWSB": "◐"},
        "Fine-tuned transformer": {"AzPS": "●", "AWSB": "●"},
        "LLM-as-judge prompt-injection": {"AzPS": "●", "AWSB": "◐"},
        "Multi-turn iterative jailbreaks": {"AzPS": "◐", "AWSB": "◐"},
        "Encoding and obfuscation": {"AzPS": "◐", "AWSB": "◐"},
        "Secrets and credential": {"AzPS": "–", "AWSB": "–"},
        "Invisible-text": {"AzPS": "–", "AWSB": "–"},
        "Indirect / latent prompt injection": {"AzPS": "●", "AWSB": "◐"},
        "Insecure-output-handling": {"AzPS": "–", "AWSB": "–"},
    },
    "Fairness & Bias": {
        "LLM-output bias detection": {"AzML": "◐", "Fid": "●"},
        "Group fairness disparity": {"AzML": "●", "Fid": "●"},
        "Pre-processing bias mitigation": {"AzML": "◐", "Fid": "–"},
        "Post-processing bias mitigation": {"AzML": "◐", "Fid": "–"},
        "In-processing bias mitigation": {"AzML": "–", "Fid": "–"},
        "Automated biased-subgroup discovery": {"AzML": "–", "Fid": "◐"},
        "Bias red-team probe packs": {"AzML": "–", "Fid": "–"},
        "Local model-based bias classifier": {"AzML": "–", "Fid": "◐"},
        "Standard bias benchmark harnesses": {"AzML": "–", "Fid": "–"},
    },
    "Explainability & Transparency": {
        "Structured-output and JSON-schema": {"AzML": "–", "AIX": "–"},
        "Topic-adherence": {"AzML": "–", "AIX": "–"},
        "Custom natural-language rubric": {"AzML": "◐", "AIX": "–"},
        "Shapley-value feature attribution": {"AzML": "●", "AIX": "●"},
        "Token-level attribution": {"AzML": "◐", "AIX": "◐"},
        "Per-check confidence breakdown": {"AzML": "◐", "AIX": "–"},
        "LIME local surrogate": {"AzML": "◐", "AIX": "●"},
        "Counterfactual recourse": {"AzML": "●", "AIX": "●"},
        "Deterministic format validators": {"AzML": "–", "AIX": "–"},
    },
    "Profanity / Content Safety": {
        "Transformer toxicity classifier": {"AzCS": "●", "OAIM": "●"},
        "LLM-as-judge toxicity": {"AzCS": "●", "OAIM": "◐"},
        "Managed safety-model integration": {"AzCS": "●", "OAIM": "●"},
        "Multi-category harm taxonomy": {"AzCS": "●", "OAIM": "●"},
        "Profanity wordlist": {"AzCS": "●", "OAIM": "●"},
        "Zero-shot / NER-model PII": {"AzCS": "–", "OAIM": "–"},
        "Adult / explicit text": {"AzCS": "●", "OAIM": "●"},
        "NSFW image and video": {"AzCS": "●", "OAIM": "–"},
        "Harmful-content red-team datasets": {"AzCS": "–", "OAIM": "–"},
    },
    "Hallucination / Reliability": {
        "LLM-as-judge groundedness": {"AzGD": "●", "Ptr": "●"},
        "NLI / entailment-based": {"AzGD": "◐", "Ptr": "●"},
        "Refusal and over-refusal": {"AzGD": "–", "Ptr": "–"},
        "RAG retrieval-quality": {"AzGD": "◐", "Ptr": "◐"},
        "Deterministic regression matchers": {"AzGD": "–", "Ptr": "–"},
        "Structural output validation": {"AzGD": "–", "Ptr": "–"},
        "Academic capability and truthfulness": {"AzGD": "–", "Ptr": "–"},
        "Fabrication probes": {"AzGD": "◐", "Ptr": "●"},
        "Package / dependency hallucination": {"AzGD": "–", "Ptr": "–"},
        "Dedicated hallucination-evaluation models": {"AzGD": "◐", "Ptr": "●"},
    },
    "Accountability": {
        "Compliance-framework mapping": {"AzMon": "◐", "Mon": "●"},
        "CI-gateable pass/fail": {"AzMon": "–", "Mon": "–"},
        "Named on-fail remediation": {"AzMon": "–", "Mon": "–"},
        "Per-call execution history": {"AzMon": "●", "Mon": "●"},
        "OpenTelemetry tracing": {"AzMon": "●", "Mon": "◐"},
        "Governance dashboards": {"AzMon": "●", "Mon": "●"},
        "Fail-open versus fail-closed": {"AzMon": "–", "Mon": "–"},
        "Detector accuracy self-evaluation": {"AzMon": "–", "Mon": "◐"},
        "Per-tenant threshold": {"AzMon": "◐", "Mon": "●"},
        "Self-hardening attack-signature": {"AzMon": "–", "Mon": "–"},
    },
}

BEST_PICK = {
    "Privacy": {
        "Presidio-backed": "Presidio via LLM Guard - free, most complete region coverage",
        "National / government ID": "Presidio / Infosys - Aadhaar, PAN, SSN, IBAN packs built in",
        "Credit card": "Agentic Security / TSZ - Luhn-validated, low false positives",
        "Healthcare PHI": "hai-guardrails - only dedicated PHI regex set found",
        "LLM-as-judge PII leakage": "DeepTeam - purpose-built PII vulnerability metric",
        "System-prompt and configuration leakage": "DeepTeam + LLM Guard secrets scan as backstop",
        "PII leakage red-team": "garak's ProPILE probes - fuzzy + exact matching",
        "Reversible anonymisation": "LLM Guard's Vault - only reversible redaction found",
        "Multi-format and multi-modal PII": "Infosys - PDF/Office/OCR/DICOM/video, unmatched breadth",
    },
    "Security": {
        "Regex / phrase-list": "LLM Guard / TSZ - free, zero-latency first pass",
        "Fine-tuned transformer": "LLM Guard's DeBERTa-v3 classifier - free, self-hosted",
        "LLM-as-judge prompt-injection": "Azure Prompt Shields if Azure-native; else PyRIT/DeepTeam",
        "Multi-turn iterative jailbreaks": "PyRIT - deepest coverage (Crescendo/TAP/PAIR/GOAT), free",
        "Encoding and obfuscation": "garak - 20 distinct encodings in one probe family",
        "Secrets and credential": "LLM Guard - free, gateway-ready",
        "Invisible-text": "LLM Guard / PyRIT - only native detectors found for this attack",
        "Indirect / latent prompt injection": "Azure Prompt Shields - most mature named capability",
        "Insecure-output-handling": "PyRIT for scoring; Guardrails AI validators for enforcement",
    },
    "Fairness & Bias": {
        "LLM-output bias detection": "LLM Guard - free, inline; pair with Fairlearn for tabular",
        "Group fairness disparity": "Fairlearn - Azure-aligned, lower overhead",
        "Pre-processing bias mitigation": "AIF360 - widest algorithm variety",
        "Post-processing bias mitigation": "Fairlearn's ThresholdOptimizer - simple, well-tested",
        "In-processing bias mitigation": "AIF360 - only source with adversarial debiasing built in",
        "Automated biased-subgroup discovery": "AIF360's MDSS/FACTS - finds the group for you",
        "Bias red-team probe packs": "DeepTeam / promptfoo - CI-ready bias attack packs",
        "Local model-based bias classifier": "LLM Guard's bias scanner - fast, no training needed",
        "Standard bias benchmark harnesses": "DeepEval - BBQ/EquityMedQA out of the box",
    },
    "Explainability & Transparency": {
        "Structured-output and JSON-schema": "Guardrails AI - purpose-built, its core strength",
        "Topic-adherence": "NeMo topic rails or LLM Guard BanTopics - zero-shot, no training",
        "Custom natural-language rubric": "DeepEval G-Eval/DAG - versioned, CI-runnable",
        "Shapley-value feature attribution": "SHAP - broadest family, most actively maintained",
        "Token-level attribution": "Infosys LLM-Explain (prompt-based); SHAP for real models",
        "Per-check confidence breakdown": "TSZ / OpenGuardrails verdict schema - explicit per-layer score",
        "LIME local surrogate": "Infosys explainability module (SHAP+LIME combo)",
        "Counterfactual recourse": "AIF360's FACTS / SHAP's action optimizer",
        "Deterministic format validators": "Guardrails AI / TSZ - regex/length/range, no ML needed",
    },
    "Profanity / Content Safety": {
        "Transformer toxicity classifier": "LLM Guard / Detoxify - free, self-hosted",
        "LLM-as-judge toxicity": "Azure Content Safety for managed/graded severity",
        "Managed safety-model integration": "NeMo Guardrails - routes to Llama Guard or Azure in one config",
        "Multi-category harm taxonomy": "garak / DeepTeam - broadest category coverage",
        "Profanity wordlist": "Commodity - free in 5+ tools; don't overpay for this one",
        "Zero-shot / NER-model PII": "LLM Guard - only dedicated zero-shot NER beyond fixed taxonomy",
        "Adult / explicit text": "hai-guardrails / Azure Content Safety",
        "NSFW image and video": "Infosys's NudeNet integration - only one found in this review",
        "Harmful-content red-team datasets": "promptfoo - widest dataset-plugin bundle (HarmBench, BeaverTails+)",
    },
    "Hallucination / Reliability": {
        "LLM-as-judge groundedness": "DeepEval / Giskard - versioned, CI-gateable rubrics",
        "NLI / entailment-based": "LLM Guard's FactualConsistency - free, no judge-LLM call",
        "Refusal and over-refusal": "LLM Guard's NoRefusal + DeepEval role-adherence",
        "RAG retrieval-quality": "DeepEval - contextual precision/recall/relevancy built in",
        "Deterministic regression matchers": "promptfoo / OpenAI Evals - free, zero API cost",
        "Structural output validation": "Guardrails AI - reask loop guarantees the output shape",
        "Academic capability and truthfulness": "DeepEval - 17 benchmark harnesses bundled",
        "Fabrication probes": "DeepTeam's HallucinationGuard - fake citations/APIs/entities",
        "Package / dependency hallucination": "garak / PyRIT - catches slopsquatting risk in generated code",
        "Dedicated hallucination-evaluation models": "DeepEval's Vectara model wrapper - no LLM cost",
    },
    "Accountability": {
        "Compliance-framework mapping": "DeepTeam - uniquely useful for governance reporting",
        "CI-gateable pass/fail": "DeepEval - the only genuine first-party pytest11 plugin",
        "Named on-fail remediation": "Guardrails AI - 7 named on-fail actions plus custom",
        "Per-call execution history": "Guardrails AI / Infosys - full call/iteration history",
        "OpenTelemetry tracing": "NeMo Guardrails / Infosys telemetry pipeline",
        "Governance dashboards": "Infosys - only option with one UI spanning all 7 tenets",
        "Fail-open versus fail-closed": "OpenGuardrails - the only repo that names this contract explicitly",
        "Detector accuracy self-evaluation": "PyRIT's scorer_evaluation - Krippendorff's alpha vs human labels",
        "Per-tenant threshold": "Infosys's admin service - the pattern to copy, not the code",
        "Self-hardening attack-signature": "Rebuff - the only self-learning attack corpus found",
    },
}


SHORT_LABEL = {
    "Privacy": {
        "Presidio-backed": "PII entity detection & redaction", "National / government ID": "Region-specific ID recognizers",
        "Credit card": "Credit card detection (Luhn-checked)", "Healthcare PHI": "Healthcare PHI entities",
        "LLM-as-judge PII leakage": "PII leakage detection (LLM judge)", "System-prompt and configuration": "System-prompt leakage detection",
        "PII leakage red-team": "PII leakage red-team probing", "Reversible anonymisation": "Reversible anonymisation (vault)",
        "Multi-format and multi-modal PII": "Multi-format PII scanning",
    },
    "Security": {
        "Regex / phrase-list": "Prompt injection (regex/heuristic)", "Fine-tuned transformer": "Prompt injection (ML classifier)",
        "LLM-as-judge prompt-injection": "Prompt injection (LLM judge)", "Multi-turn iterative jailbreaks": "Multi-turn jailbreak attacks",
        "Encoding and obfuscation": "Encoding / obfuscation attacks", "Secrets and credential": "Secrets / credential leakage",
        "Invisible-text": "Invisible-text smuggling", "Indirect / latent prompt injection": "Indirect / document injection",
        "Insecure-output-handling": "Insecure code / SQLi / XSS output",
    },
    "Fairness & Bias": {
        "LLM-output bias detection": "Bias detection (generative)", "Group fairness disparity": "Group fairness metrics",
        "Pre-processing bias mitigation": "Pre-processing mitigation", "Post-processing bias mitigation": "Post-processing mitigation",
        "In-processing bias mitigation": "In-processing mitigation", "Automated biased-subgroup discovery": "Automated subgroup discovery",
        "Bias red-team probe packs": "Bias red-team probe packs", "Local model-based bias classifier": "Local bias classifier (text)",
        "Standard bias benchmark harnesses": "Bias benchmark harnesses",
    },
    "Explainability & Transparency": {
        "Structured-output and JSON-schema": "Structured-output / schema validity", "Topic-adherence": "Ban-topics / on-topic scope",
        "Custom natural-language rubric": "Custom rubric judges (G-Eval)", "Shapley-value feature attribution": "Feature attribution (SHAP)",
        "Token-level attribution": "Token-level attribution", "Per-check confidence breakdown": "Per-check confidence breakdown",
        "LIME local surrogate": "LIME local explanations", "Counterfactual recourse": "Counterfactual / recourse analysis",
        "Deterministic format validators": "Deterministic format validators",
    },
    "Profanity / Content Safety": {
        "Transformer toxicity classifier": "Toxicity / hate-speech (model)", "LLM-as-judge toxicity": "Toxicity (LLM judge)",
        "Managed safety-model integration": "Managed safety-model routing", "Multi-category harm taxonomy": "Multi-category harm taxonomy",
        "Profanity wordlist": "Profanity / banned-word filter", "Zero-shot / NER-model PII": "Zero-shot restricted-topic filter",
        "Adult / explicit text": "Adult / explicit content", "NSFW image and video": "NSFW image/video detection",
        "Harmful-content red-team datasets": "Harmful-content red-team sets",
    },
    "Hallucination / Reliability": {
        "LLM-as-judge groundedness": "Groundedness (LLM judge)", "NLI / entailment-based": "Groundedness (NLI/entailment)",
        "Refusal and over-refusal": "Refusal / over-refusal detection", "RAG retrieval-quality": "RAG retrieval-quality metrics",
        "Deterministic regression matchers": "Deterministic regression checks", "Structural output validation": "Structured-output validation",
        "Academic capability and truthfulness": "Truthfulness benchmarks", "Fabrication probes": "Fabrication probes (fake facts)",
        "Package / dependency hallucination": "Package hallucination check", "Dedicated hallucination-evaluation models": "Dedicated hallucination models",
    },
    "Accountability": {
        "Compliance-framework mapping": "Compliance-framework mapping", "CI-gateable pass/fail": "CI/CD test-gating",
        "Named on-fail remediation": "On-fail remediation actions", "Per-call execution history": "Audit trail / call history",
        "OpenTelemetry tracing": "OpenTelemetry tracing", "Governance dashboards": "Governance dashboards",
        "Fail-open versus fail-closed": "Fail-closed / unjudged policy", "Detector accuracy self-evaluation": "Detector accuracy self-eval",
        "Per-tenant threshold": "Per-tenant threshold config", "Self-hardening attack-signature": "Self-hardening attack corpus",
    },
}


def _short_label(tenet, aspect):
    for sub, label in SHORT_LABEL.get(tenet, {}).items():
        if sub in aspect:
            return label
    return aspect.split(" (")[0]


def _cap(text, n=58):
    if len(text) <= n:
        return text
    return text[: n - 1].rsplit(" ", 1)[0] + "…"


def build():
    matrices = {}
    for tenet, rows_data in SELECTED.items():
        repo_cols = TENET_REPOS[tenet]
        virt = VIRTUAL_COLS.get(tenet, [])
        columns = [{"code": CODE[r], "name": DISPLAY[r], "kind": "repo", "key": r} for r in repo_cols]
        columns += [{"code": c, "name": n, "kind": "virtual", "key": c} for c, n in virt]

        rows = []
        for item in rows_data:
            aspect = item["aspect"]
            source = set(item["source_repos"])
            cells = {}
            for r in repo_cols:
                sym = "●" if r in source else "–"
                for (tt, sub, repo_key), ovr in OVERRIDES.items():
                    if tt == tenet and sub in aspect and repo_key == r:
                        sym = ovr
                cells[CODE[r]] = sym
            # virtual/cloud marks
            best_key = None
            for key_sub in CLOUD_MARKS.get(tenet, {}):
                if key_sub in aspect:
                    best_key = key_sub
                    break
            marks = CLOUD_MARKS.get(tenet, {}).get(best_key, {}) if best_key else {}
            for code, _name in virt:
                cells[code] = marks.get(code, "–")
            best = None
            for key_sub, txt in BEST_PICK.get(tenet, {}).items():
                if key_sub in aspect:
                    best = txt
                    break
            short_label = _short_label(tenet, aspect)
            rows.append({"aspect": short_label, "cells": cells, "best": _cap(best or "")})
        matrices[tenet] = {"columns": columns, "rows": rows}
    return matrices


if __name__ == "__main__":
    m = build()
    with open(os.path.join(DATA_DIR, "capability_matrix_data.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
    for t, mm in m.items():
        print(t, "columns:", len(mm["columns"]), "rows:", len(mm["rows"]))
