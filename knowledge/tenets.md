# The Seven Tenets

The framework's spine. Every AI-native AFNI application is assessed against all seven.
Runtime stacks from deck slides 70–73; open-source-vs-cloud picks from slides 39–45;
capability-by-capability detail in `data/capability_matrix_data.json` (7 tenets ×
up to 22 tools, `●` native / `◐` partial or delegated / `–` absent, with a named best
pick per capability). Checklist item counts are from `data/RAI_Synthesis.json`
→ `master_aspect_list` (142 items total).

---

## 1 · Privacy  (19 checklist items)
**Principle:** privacy-by-design — data minimisation, consent capture, a retention
policy, and runtime redaction.
**Stack:** LLM Guard (Presidio + DeBERTa NER + **Vault reversible redaction**) →
NeMo Guardrails (GLiNER zero-shot PII rail) → *optional* Azure AI Language PII →
garak ProPILE leakage probes (offline) → hai-guardrails PHI regexes ported into Presidio.
**Cloud pick:** Azure AI Language PII, specifically its **Conversation PII** mode —
built for contact-centre transcripts, a direct match for AFNI's BPO workload. Free
tier 5,000 records/month; Standard ~$0.38 per 1,000 records (re-verify the rate).
**Recommended combination:** `llm-guard-main` + `Guardrails-develop` + `garak-main`.
Two runtime layers plus one testing layer — deliberately *not* three runtime layers.

## 2 · Security  (37 checklist items — the largest tenet)
**Principle:** defence in depth — cheap local checks first, a paid model only on
borderline input, continuous offline red-teaming to keep every layer honest.
**Stack:** LLM Guard (DeBERTa-v3 injection classifier, Secrets, InvisibleText) →
NeMo Guardrails (YARA injection rules, perplexity heuristics, context-bloat,
tool-schema validation) → Azure AI Content Safety **Prompt Shields** (third opinion on
high-risk traffic) → PyRIT (offline multi-turn attacks, OWASP output scorers) →
garak (second scanner + shields up/down guardrail audit).
**Cloud pick:** Prompt Shields — the most mature named capability for direct *and*
indirect (document-borne) prompt injection.
**Recommended combination:** `llm-guard-main` + `Guardrails-develop` + `PyRIT-main`.

## 3 · Fairness & Bias  (16 checklist items)
**Principle:** measure before you mitigate — every fairness metric needs a labelled
ground truth and a defined protected group. There is no automatic detector for
"unfair" without one.
**Stack:** Fairlearn (group metrics, mitigation, intersectional analysis) → AIF360
(MDSS and FACTS subgroup *discovery*) → promptfoo bias red-team plugins in CI →
SHAP (feature-level decomposition of outcome gaps).
**Cloud pick:** the Azure ML Responsible AI dashboard (built on Fairlearn itself, so
it is a free managed client-facing view). Fiddler AI / Arthur AI only if AFNI needs
always-on production bias-drift alerting rather than scheduled batch checks.
**Runs as:** scheduled batch job. **Never** a live per-response check — see D6.
**Recommended combination:** `fairlearn-main` + `AIF360-main` + `promptfoo-main`.

## 4 · Explainability & Transparency  (14 checklist items)
**Principle:** three different questions need three different tools — explain the
*model* with SHAP, explain the *guardrail* with a structured verdict, explain a
*policy judgment* with a versioned rubric.
**Stack:** SHAP (feature attribution, tabular and text) → DeepEval G-Eval / DAG
(policy rubrics with written reasons) → OpenGuardrails Verdict schema (per-finding
score, severity, detector, span).
**Cloud pick:** Azure ML RAI dashboard surfaces SHAP explanations client-facing at no
extra licensing cost. IBM AIX360 / Microsoft InterpretML add counterfactual and
rule-based families when feature attribution alone does not answer the question.
**Runs as:** async `explain` endpoint backed by a background job — SHAP is too slow
for synchronous request handling.
**Recommended combination:** `shap-master` + `deepeval-main`.

## 5 · Profanity / Content Safety  (12 checklist items)
**Principle:** don't overpay for commodity checks — profanity filtering is free in
five or more of the reviewed tools. Spend the budget on the harder problems. And
never one filter alone.
**Stack:** LLM Guard (local toxicity `unitary/unbiased-toxic-roberta`, bias
`valurank/distilroberta-bias`, BanTopics zero-shot, BanSubstrings, plus gibberish,
sentiment and language-consistency detectors found nowhere else) → NeMo routing to
Llama Guard 3 or Azure AI Content Safety with an AFNI custom blocklist → promptfoo
(HarmBench, BeaverTails, DoNotAnswer, XSTest corpora in CI).
**Cloud pick:** Azure AI Content Safety — managed, multi-modal, severity-graded
(hate / self-harm / sexual / violence) with custom blocklists, and the audit evidence
a client reviewer will want. OpenAI Moderation as a free second opinion if AFNI
already calls OpenAI models.
**Recommended combination:** `llm-guard-main` + `Guardrails-develop` + `promptfoo-main`.

## 6 · Hallucination / Reliability  (20 checklist items)
**Principle:** one cheap, local, always-on groundedness score in production; the
expensive diagnostic metrics stay in CI, where they are affordable.
**Stack:** LLM Guard cross-encoder NLI `FactualConsistency` at runtime (**the only
groundedness check in the review cheap enough to run on every response — no judge-LLM
call**) → DeepEval (faithfulness, contextual precision/recall/relevancy, offline) →
Azure AI Content Safety groundedness detection (regulated RAG) → Deepchecks drift
suite in a scheduled job, *subject to AGPL-3.0 clearance*.
**Also:** Giskard uniquely checks **sycophancy**.
**Recommended combination:** `llm-guard-main` + `deepeval-main`.

## 7 · Accountability  (24 checklist items)
**Principle:** a loud-failure policy — any check that could not run is reported as
`unjudged`, never silently passed, and the gateway fails closed on client-facing
traffic. One record shape end to end, a named owner per tenet, and a *measured*
accuracy figure per detector rather than a vendor claim.
**Stack:** OpenGuardrails (GuardEvent + Verdict schema, taxonomy, fail-closed
contract) → PyRIT (memory persistence, harm taxonomy, scorer accuracy vs human
labels) → promptfoo (OWASP / NIST / EU AI Act mapped reports from CI) → Azure Monitor
and Application Insights for guardrail telemetry.
**Cloud pick:** Azure Monitor / Application Insights (or Azure AI Foundry
Observability) for OpenTelemetry tracing at Azure-native cost. Monitaur or Fiddler AI
only if AFNI wants a dedicated vendor-managed AI-governance record store.
**Recommended combination:** `openguardrails-main` + `PyRIT-main` + `promptfoo-main`.

---

## At a glance

| Tenet | Runtime primary | Offline / CI | Cloud second opinion |
|---|---|---|---|
| Privacy | LLM Guard + NeMo | garak | Azure AI Language PII |
| Security | LLM Guard + NeMo | PyRIT, garak | Azure Prompt Shields |
| Fairness & Bias | *(batch only)* Fairlearn | AIF360, promptfoo | Azure ML RAI dashboard |
| Explainability | *(async)* SHAP | DeepEval G-Eval | Azure ML RAI dashboard |
| Content Safety | LLM Guard + NeMo | promptfoo | Azure AI Content Safety |
| Hallucination | LLM Guard NLI | DeepEval, Giskard | Azure Groundedness |
| Accountability | OpenGuardrails schema | PyRIT, promptfoo | Azure Monitor |

**LLM Guard is the runtime primary for four of seven tenets.** That concentration is
why D4 (fork it, pin the model revisions, own it) matters more than any other single
adoption decision.
