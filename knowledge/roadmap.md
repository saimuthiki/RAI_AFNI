# 90-Day Roadmap

Plan of record. Source: `data/RAI_Synthesis.json` → `roadmap_phases`; deck slides 74–77.
Front-loads free deterministic checks and the shared contract; adds model-based and
cloud checks once thresholds are calibrated on real traffic; takes on the heaviest
red-team and drift work only when the runtime layer is stable. Cost and complexity
ramp only as trust in the earlier layers is proven.

## Phase 1 — 0–30 days (8 actions)
1. Stand up the gateway: FastAPI + NeMo Guardrails, **jailbreak rail flipped to
   fail-closed** for client-facing traffic.
2. Adopt the OpenGuardrails GuardEvent/Verdict schemas and taxonomy as the internal
   contract. **Pin the protocol version** — it is pre-1.0.
3. Fork `llm-guard-main` into an AFNI-owned repo, **pin every HuggingFace model
   revision**, enable the free deterministic tier first: Anonymize + Vault, Secrets,
   InvisibleText, Regex, plus NeMo's YARA injection rules and context-bloat heuristics.
4. Name **one accountable owner per tenet**; record the seven tenets, owners and
   current thresholds in a single governance register.
5. Baseline red-team scan against one existing AFNI AI application — garak CLI plus a
   promptfoo OWASP-mapped redteam run. **Publish it as the "before" picture.**
6. Wire the fast CI tier on the pilot app: DeepEval + promptfoo deterministic
   assertions and PyRIT regex output scorers, **under five minutes on every PR**.
7. ~~**Legal ruling needed** on Deepchecks' AGPL-3.0~~ — **CLEARED 2026-09-02.**
   AFNI confirmed it holds licences covering Apache-2.0, MIT and AGPL-3.0, and that
   no repository in this review is licence-restricted. promptfoo's remote-only
   plugin question is **not** a licence question and still stands: those plugins
   call promptfoo-hosted services, so it is a data-residency decision about what
   leaves AFNI's network, and it applies equally to any paid judge.
8. **Log the two vendor-risk items** for the record: Guardrails AI's documented PyPI
   supply-chain compromise, and `agentic_security-main`'s hard-coded third-party
   bearer token.

## Phase 2 — 30–60 days (9 actions)
1. Turn on the model-based runtime tier: LLM Guard's DeBERTa-v3 injection classifier,
   local toxicity classifier, and cross-encoder NLI `FactualConsistency` on every RAG
   response.
2. Route Azure AI Content Safety in **through NeMo** as a second opinion on high-risk
   content and as groundedness detector for regulated RAG, with an AFNI custom
   blocklist — explicitly defence in depth, not the primary filter.
3. Port hai-guardrails' healthcare PHI regexes (ICD-10, MRN, NPI, DEA) and
   entropy-gated secret patterns into **Presidio custom recognisers**. Calibrate all
   thresholds on real AFNI traffic — do not ship defaults.
4. Reimplement Rebuff's canary-token leak detection and self-hardening
   attack-signature store as **native NeMo rails**, seeded from the Phase-1 findings.
5. Build the medium CI tier: promptfoo redteam over the OWASP LLM Top 10 plugin set
   plus a garak probe subset on every merge to main, gated on a maximum
   attack-success rate.
6. Establish the **versioned regression corpus in git** — export every attack that
   succeeded in Phase 1, tag by tenet and OWASP category, and make replay of
   previously-fixed attacks a hard gate in the fast tier.
7. Adopt Fairlearn + AIF360 MDSS/FACTS for any application making decisions about
   people. **Scheduled batch job, not a runtime check.**
8. Adopt SHAP for tabular and text explanations; expose an `explain` endpoint backed
   by a **background job** — SHAP is too slow for synchronous handling.
9. Ship the audit store and dashboard: every verdict from runtime and CI in the same
   schema, OpenTelemetry traces into Azure Monitor.

## Phase 3 — 60–90 days (9 actions)
1. Stand up the slow tier: PyRIT Crescendo/TAP/PAIR multi-turn attacks, DeepTeam
   agentic probes, Deepchecks drift suites where licensing allows.
2. **Measure the guardrails rather than assuming them** — PyRIT `scorer_evaluation`
   with Krippendorff's alpha against a human-labelled production sample; publish a
   real precision and recall figure per detector.
3. Point garak's shields up / shields down probes at AFNI's own gateway to prove the
   rails fire. Add to the release gate.
4. Build the **per-tenant / per-project threshold configuration service** on the
   Infosys admin pattern, so each project sets strictness without forking the gateway.
5. Produce the **standard client approval pack** from CI artefacts: OWASP LLM Top 10,
   NIST AI RMF, MITRE ATLAS and EU AI Act mapped reports from promptfoo, plus the
   measured detector accuracy table and an audit-trail sample.
6. Vendor the unique Infosys modules **if the business needs them**: multi-format and
   DICOM PII scanning, NSFW image/video detection, Faker-based anonymisation with
   differential privacy.
7. Run the OpenAI Evals deception / sandbagging / covert-persuasion suite **once**
   against any AFNI product claiming agent autonomy, before it ships.
8. Publish the AFNI Responsible AI Toolkit as an internal versioned package with a
   **mandatory adoption gate**: no AI-native application reaches production without
   routing through the gateway and passing the CI tiers.
9. Schedule **quarterly re-benchmarking** — garak's own published detector metrics and
   the archived status of `llm-guard-main` both mean accuracy decays unless someone
   owns it.

## The bottom line (slide 78)
Spend where the risk is highest; use free deterministic checks everywhere else. Cheap
local checks on every request, paid calls only on borderline traffic, expensive
thorough work in nightly and pre-release testing. No single filter is ever the whole
defence. Two rules matter more than any tool choice: **if a check cannot run, say so
and block**, and **measure how accurate each check really is** against human-reviewed
examples instead of trusting a vendor's claim.
