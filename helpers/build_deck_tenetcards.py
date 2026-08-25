# -*- coding: utf-8 -*-
"""Per-tenet prose: open-source lead, cloud lead, recommendation and principle.

Data only. The slide renderers that used to live here were retired when the two
overlapping recommendation sets were merged - build_deck_tenetmerged.py now reads
TENET_CARDS and is the single renderer for this section.
"""
TENET_CARDS = [
    {
        "tenet": "Privacy",
        "title": "Privacy & PII Protection",
        "open_source_name": "Microsoft Presidio (MIT)",
        "open_source_text": "18 country-recognizer packs built in, including India Aadhaar (Verhoeff checksum - "
            "not a custom-build gap), PAN, GSTIN, and US SSN/ITIN/passport. Anonymizer supports redact, mask, "
            "hash, AES-encrypt, or a custom operator, plus OCR and DICOM image redaction. Extending it is a "
            "~50-130 line recognizer - this is exactly what Infosys, NeMo, and LLM Guard all wrap internally.",
        "cloud_name": "Azure AI Language - PII / Conversation PII",
        "cloud_text": "A dedicated Conversation PII mode built for contact-center transcripts - a direct match "
            "for AFNI's BPO workload. Document-based PII preserves .pdf/.docx layout. Free tier: 5,000 "
            "records/month; Standard tier around $0.38 per 1,000 records (verify the exact current rate).",
        "recommendation": "Presidio + Azure PII, layered: Presidio for in-app, customizable, on-prem redaction; "
            "Azure PII/Conversation-PII wherever the pipeline is already Azure-native and call-center "
            "transcripts need managed coverage.",
        "principle": "Privacy-by-design: data minimization, consent capture, a retention policy, and runtime redaction.",
    },
    {
        "tenet": "Security",
        "title": "Security & Injection Defense",
        "open_source_name": "Microsoft PyRIT (MIT) + LLM Guard (MIT)",
        "open_source_text": "PyRIT has the deepest red-team coverage found in this review: Crescendo, TAP, PAIR, "
            "and Skeleton-Key multi-turn jailbreak strategies, about 80 prompt-obfuscation converters, and free "
            "regex output-scorers for SQL injection, SSRF, and secret leaks. At runtime, LLM Guard's DeBERTa-v3 "
            "prompt-injection classifier runs locally at zero per-call cost, and NeMo Guardrails supplies YARA "
            "injection rules plus Colang-driven orchestration.",
        "cloud_name": "Azure AI Content Safety - Prompt Shields",
        "cloud_text": "Purpose-built for both direct and indirect (document-based) prompt injection - the most "
            "mature named capability for this specific attack class. AWS Bedrock Guardrails offers a comparable "
            "managed filter. Independent benchmarks show cloud filters lose ground on adversarial input versus "
            "specialised classifiers, so never rely on one filter alone.",
        "recommendation": "LLM Guard (free local classifier) + NeMo Guardrails (orchestration and YARA rules) + "
            "PyRIT (offline red-team in CI/CD), with Azure Prompt Shields layered in as a second opinion on "
            "Azure-native traffic.",
        "principle": "Defense-in-depth: cheap local checks first, a paid model only on borderline input, and "
            "continuous offline red-teaming to keep every layer honest.",
    },
    {
        "tenet": "Fairness & Bias",
        "title": "Fairness & Bias Mitigation",
        "open_source_name": "Microsoft Fairlearn (MIT) + IBM AIF360 (Apache-2.0)",
        "open_source_text": "Fairlearn covers everyday group-fairness metrics and mitigation on structured "
            "decisioning models - Azure-aligned, lower overhead, and backed by a 62-file test suite with "
            "warnings-as-errors CI. AIF360 goes deeper: its MDSS and FACTS scanners find which subgroup is "
            "biased instead of requiring AFNI to already know which group to check.",
        "cloud_name": "Azure ML Responsible AI dashboard + Fiddler AI / Arthur AI",
        "cloud_text": "Azure's RAI dashboard is built on Fairlearn itself, giving a managed, client-facing fairness "
            "view for free. Fiddler AI and Arthur AI add continuous production bias-drift monitoring and alerting, "
            "worth the spend only if AFNI needs always-on alerts rather than scheduled batch checks.",
        "recommendation": "Fairlearn as the default, AIF360 layered in for deep subgroup audits, both run as "
            "scheduled batch jobs - never as a live per-response check - with promptfoo's bias red-team plugins "
            "in CI for the generative side.",
        "principle": "Measure before you mitigate: every fairness metric needs a labelled ground truth and a "
            "defined protected group - there is no automatic detector for “unfair” without one.",
    },
    {
        "tenet": "Explainability & Transparency",
        "title": "Explainability & Transparency",
        "open_source_name": "SHAP (MIT)",
        "open_source_text": "The tool Kiran asked about by name. Twelve Shapley-value estimation algorithms sit "
            "behind one auto-dispatching API - exact for tree and linear models, approximate elsewhere - and it "
            "is Nature-published, industry-standard, with its own benchmark for judging whether an explanation "
            "is trustworthy at all. DeepEval's G-Eval/DAG add a second, LLM-native layer: versioned, CI-runnable "
            "rubrics instead of an ad hoc prompt-based explainer.",
        "cloud_name": "Azure ML Responsible AI dashboard + IBM AIX360 / InterpretML",
        "cloud_text": "Azure's RAI dashboard surfaces SHAP-based explanations in a client-facing UI at no extra "
            "licensing cost. IBM AIX360 and Microsoft InterpretML add other explanation families - counterfactual "
            "and rule-based - for when feature attribution alone doesn't answer the question being asked.",
        "recommendation": "SHAP for every tabular/text model, DeepEval's G-Eval for LLM-answer explanations, both "
            "surfaced through the Azure ML RAI dashboard for anything client-facing.",
        "principle": "Explain the model with SHAP, explain the guardrail with a structured verdict, explain a "
            "policy judgment with a versioned rubric - three different questions, three different tools.",
    },
    {
        "tenet": "Profanity / Content Safety",
        "title": "Content Safety & Profanity",
        "open_source_name": "LLM Guard (MIT)",
        "open_source_text": "The broadest free scanner set found in this review: toxicity (unitary/unbiased-toxic-"
            "roberta), bias (valurank/distilroberta-bias), zero-shot ban-topics that need no retraining for a "
            "new restricted topic, plus gibberish, sentiment, and language-consistency detectors found nowhere "
            "else. Infosys's safety module adds NudeNet/nsfw_detector for image and video nudity if AFNI ever "
            "ships media generation or uploads.",
        "cloud_name": "Azure AI Content Safety + OpenAI Moderation",
        "cloud_text": "Azure gives managed, multi-modal, severity-graded moderation (hate, self-harm, sexual, "
            "violence) with custom blocklists. OpenAI's Moderation API is a lightweight, free second opinion if "
            "AFNI already calls OpenAI models for anything else.",
        "recommendation": "LLM Guard as the always-on, zero-marginal-cost first pass; Azure Content Safety "
            "layered in for managed multi-modal coverage and the audit evidence a client reviewer will want to see.",
        "principle": "Don't overpay for commodity checks: profanity filtering is free in five or more of the "
            "tools reviewed - spend the budget on the harder problems instead.",
    },
    {
        "tenet": "Hallucination / Reliability",
        "title": "Hallucination & Reliability",
        "open_source_name": "LLM Guard's FactualConsistency scanner (MIT)",
        "open_source_text": "A cross-encoder NLI model that scores entailment between a source and the model's "
            "answer entirely locally - no judge-LLM call - the only groundedness check in this review cheap "
            "enough to run on every single response. DeepEval and Giskard add the deeper CI-side diagnostics "
            "(faithfulness, contextual precision/recall, and sycophancy - a check unique to Giskard) for "
            "pre-release gating.",
        "cloud_name": "Azure AI Content Safety - Groundedness Detection",
        "cloud_text": "Verifies an answer against its source documents, built for regulated RAG flows. Patronus "
            "AI's Lynx model and Cleanlab's trustworthiness score are both available as ready-made NeMo "
            "Guardrails rails if a second, managed opinion is wanted.",
        "recommendation": "LLM Guard's NLI scanner on every live response; DeepEval plus Giskard's fuller metric "
            "set as a CI/CD gate; Azure Groundedness Detection layered in for regulated, client-facing RAG flows.",
        "principle": "One cheap, local, always-on groundedness score in production; the expensive diagnostic "
            "metrics stay in CI, where they are affordable.",
    },
    {
        "tenet": "Accountability",
        "title": "Accountability & Governance",
        "open_source_name": "OpenGuardrails' Verdict/GuardEvent schema (Apache-2.0)",
        "open_source_text": "Contributes no detector at all, and that is exactly its value: a vendor-neutral "
            "contract (category, severity, score, redaction span, and an explicit “unjudged” state) "
            "that lets AFNI swap any detector later without touching application code. PyRIT's memory store and "
            "DeepTeam's OWASP/NIST/MITRE/EU-AI-Act framework mapping turn red-team runs into governance-ready evidence.",
        "cloud_name": "Azure Monitor / Application Insights + Monitaur or Fiddler AI",
        "cloud_text": "Azure Monitor and Application Insights (or Azure AI Foundry Observability) give production "
            "audit trails and OpenTelemetry tracing at Azure-native cost. Monitaur or Fiddler AI are worth the "
            "spend only if AFNI wants a dedicated, vendor-managed AI-governance record store.",
        "recommendation": "Adopt the OpenGuardrails schema as AFNI's internal contract from day one; PyRIT plus "
            "DeepTeam for compliance-mapped red-team evidence; Azure Monitor for the production audit trail - "
            "one record shape, end to end.",
        "principle": "A loud-failure policy: any check that could not run is reported as unjudged, never silently "
            "passed, and the gateway fails closed on client-facing traffic.",
    },
]
