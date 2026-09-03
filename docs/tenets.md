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
suite in a scheduled job. (AGPL-3.0 clearance was granted by AFNI on
2026-09-02; the remaining constraint is that Deepchecks is batch-only.)
**Also:** Giskard uniquely checks **sycophancy**.
**Recommended combination:** `llm-guard-main` + `deepeval-main`.

## 7 · Accountability  (24 checklist items)
**Principle:** a loud-failure policy — any check that could not run is reported as
`unjudged`, never silently passed, and the gateway fails closed **unconditionally**:
no request field and no console switch relaxes it. One record shape end to end, an
accountable **role** per tenet — generated, see [the governance register](#the-governance-register)
— and a *measured* accuracy figure per detector rather than a vendor claim.
**Stack:** OpenGuardrails (GuardEvent + Verdict schema, taxonomy, fail-closed
contract) → PyRIT (memory persistence, harm taxonomy, scorer accuracy vs human
labels) → promptfoo (OWASP / NIST / EU AI Act mapped reports from CI) → Azure Monitor
and Application Insights for guardrail telemetry.
**Cloud pick:** Azure Monitor / Application Insights (or Azure AI Foundry
Observability) for OpenTelemetry tracing at Azure-native cost. Monitaur or Fiddler AI
only if AFNI wants a dedicated vendor-managed AI-governance record store.
**Recommended combination:** `openguardrails-main` + `PyRIT-main` + `promptfoo-main`.

---

## The single recommendation per tenet

The deck previously carried **two** overlapping sets of per-tenet slides, both
headed "AFNI RECOMMENDATION", and they did not agree. They have been merged into
one slide per tenet (deck slides 39-45). The root cause of the apparent conflict:

- the *recommendation* slides answered "which of the 23 reviewed repos do we adopt",
  so their picks were repo names
- the *cheat sheets* answered "what does the runtime stack look like", which mixes
  repos with the **engines inside them** and the **cloud services beside them**

For Privacy that produced "Presidio + Azure PII" on one slide and "LLM Guard +
NeMo + garak" on another - the same stack at two different altitudes. The merged
slide states all three layers explicitly, so nothing reads as a contradiction:

| Layer | Question it answers |
|---|---|
| **ADOPT** | which of the 23 reviewed repos AFNI takes on |
| **ENGINE UNDER IT** | the library or model those repos actually run (Presidio, the HF model ids) |
| **CLOUD SECOND OPINION** | the managed Azure/vendor service layered beside them |
| **WHERE IT RUNS** | the cascade stage, from [methodology.md](frameworks.md#methodology--mechanism-cost-and-stage-per-repo-tenet-pair) |

Two tenets genuinely disagreed rather than differing in altitude:

- **Accountability** - the cheat sheet named DeepTeam, the recommendation slide
  named Promptfoo. **Promptfoo is the pick**: it maps 6 compliance frameworks
  (OWASP LLM, NIST AI RMF, MITRE ATLAS, EU AI Act, ISO 42001, GDPR) against
  DeepTeam's 5, and PyRIT ships no report generator at all. DeepTeam stays as a
  secondary source of agentic findings.
- **Hallucination** - the cheat sheet put Giskard in the runtime picture. Giskard
  v3 is LLM-judge based and needs a paid API, so it is CI-only, never inline.

Content Safety differed only by omission (the union is correct: LLM Guard for the
local pass, NeMo for routing, Promptfoo for the CI corpus, Azure for the audit
trail). Privacy, Security, Fairness and Explainability agreed once the altitude
difference is accounted for.

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

For *how* each tool implements its check - module vs keyword vs classifier vs LLM judge vs
cloud API - and which cascade stage that puts it in, see
[methodology.md](frameworks.md#methodology--mechanism-cost-and-stage-per-repo-tenet-pair).

**LLM Guard is the runtime primary for four of seven tenets.** That concentration is
why D4 (fork it, pin the model revisions, own it) matters more than any other single
adoption decision.

---

## The governance register

Build-plan item 21 asked AFNI for **seven names** — one accountable owner per tenet —
and said no code could produce it. AFNI's answer was that the framework comes with all
of this, so why does it need names.

**They were right, and the design changed rather than the default.** A person's name in
a governance register is stale the moment they change team, and a register with a *wrong*
escalation path is worse than one with an honest gap: the first sends an incident to
somebody who left, the second is visibly unfinished.

What governance actually needs is an **escalation path**, and a role plus an address is
one. So:

- **The roles are generated**, with no configuration at all. `Privacy steward — AFNI
  Responsible AI`, and so on for all seven, each with a sentence saying what arriving
  there *means* — because "owner of Privacy" is a label, not an accountability.
- **One setting arms all seven addresses.** `AFNI_GOVERNANCE_DOMAIN` turns
  `rai-privacy` into `rai-privacy@your-domain`. One environment variable instead of
  seven names.
- **Nothing is invented in the meantime.** Until that variable is set the addresses are
  aliases with no domain and the register says so. A plausible-looking address that goes
  nowhere is worse in a compliance artefact than a visibly unfinished one.
- **Real people are still possible**, per tenet, via `AFNI_GOVERNANCE_OWNERS` — a JSON
  object of `{tenet: contact}` — without a code change.

The register is not a contact list. Every other number in it is read from the **running
platform**: rails mounted per tenet, capability coverage, and the threshold values in
force right now *including operator overrides*. It cannot describe a configuration
nobody is running.

```bash
# on screen
python -m afni_rai.cli governance

# as Markdown, for the client approval pack
python -m afni_rai.cli governance --markdown > governance-register.md
```

It is also `GET /v1/governance`, and it renders at the bottom of the console's **Tenets**
screen.

**It is read-only from the console, on purpose.** An escalation path that anybody with
the console could rewrite is not an escalation path, so the domain is a server
environment variable rather than a UI setting.
