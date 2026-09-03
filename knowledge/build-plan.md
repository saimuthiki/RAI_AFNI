# Build Plan

**One pass, no phases.** AFNI's decision (2026-09-03): build the whole platform as a
single body of work rather than a 90-day, three-phase rollout. This file replaces
`roadmap.md`, which arranged these same items on that calendar.

What changed is only the *arrangement*. Every work item survives, because the items were
never the problem — the calendar was. They are grouped here by the kind of work they
are, so a reader can see the whole scope at once and pick up whatever is unblocked.

The **cost ordering still stands and is not a phase**: free deterministic checks on
every request, local models only when a cheap check is unsure, paid calls only as a last
resort, and the heavy red-team and drift work offline. That is the runtime cascade
(Stage 1/2/3/Offline) and it is a per-request cost decision, not a date.

Status is marked against what is actually in the repository today, verified rather than
asserted:

| Mark | Meaning |
|---|---|
| **BUILT** | in the repo, covered by the test suite |
| **PARTIAL** | present but not finished, or present and unwired |
| **NEEDS A HOST** | code is written; needs model weights, a key, or the VPN |
| **NOT STARTED** | no code yet |
| **DROPPED** | deliberately not doing this; the reason is on the line |

---

## The runtime gateway

1. **BUILT** — Stand up the gateway: FastAPI on the NeMo Guardrails rail pattern, with
   the jailbreak rail flipped from its documented fail-open default.
2. **BUILT** — Adopt the OpenGuardrails `GuardEvent`/`Verdict` schemas and taxonomy as
   the internal contract, with the pre-1.0 protocol version pinned.
3. **PARTIAL** — Fork `llm-guard-main` into an AFNI-owned repo and pin every HuggingFace
   model revision. The free deterministic tier is enabled and running: Anonymize +
   Vault, Secrets, InvisibleText, Regex, plus the YARA injection rules and context-bloat
   heuristics. *The fork itself is not done — the code currently depends on the archived
   upstream.*
4. **NEEDS A HOST** — The model-based runtime tier: the DeBERTa-v3 injection classifier,
   the local toxicity classifier, and cross-encoder NLI `FactualConsistency` on every
   RAG response. All three rails are written and mounted; they report `unjudged` until
   the weights are present, which fails closed.
5. **BUILT** — Guard the target model directly: `POST /v1/chat` guards the prompt, calls
   the configured endpoint, guards the completion, and returns all four steps.
6. **NOT STARTED** — Route Azure AI Content Safety in through the gateway as a *second
   opinion* on high-risk content and as a groundedness detector for regulated RAG, with
   an AFNI custom blocklist. Defence in depth, explicitly never the primary filter.
7. **BUILT** — Port hai-guardrails' healthcare PHI regexes (ICD-10, MRN, NPI, DEA) and
   its entropy-gated secret patterns. **Thresholds still need calibrating on real AFNI
   traffic — the shipped numbers are the values each pattern was ported with, not tuned
   defaults.**
8. **BUILT** — Reimplement Rebuff's canary-token leak detection and its self-hardening
   attack-signature store as native rails. The corpus is deliberately EMPTY at import: it
   matches nothing until an operator or a CI run confirms a first attack.

## Testing and CI

9. **NEEDS A HOST** — Baseline red-team scan against one existing AFNI application:
   garak CLI plus a promptfoo OWASP-mapped redteam run. **Publish it as the "before"
   picture.** Needs an application endpoint to point at.
10. **PARTIAL** — The fast CI tier on the pilot app: DeepEval + promptfoo deterministic
    assertions and PyRIT regex output scorers, under five minutes on every PR. The
    scorers are ported; the CI wiring is not.
11. **NOT STARTED** — The medium CI tier: promptfoo redteam over the OWASP LLM Top 10
    plugin set plus a garak probe subset on every merge to main, gated on a maximum
    attack-success rate.
12. **BUILT** — The versioned regression corpus in git: 11,369 harmful prompts, tagged
    by tenet and OWASP category, with a shared sampler behind the CLI, `/v1/corpus` and
    the console so a run means the same thing everywhere. **Replay of previously-fixed
    attacks is not yet a hard CI gate.**
13. **NOT STARTED** — The slow tier: PyRIT Crescendo/TAP/PAIR multi-turn attacks and
    DeepTeam agentic probes. Deepchecks drift suites are **DROPPED** from the request
    path for a technical reason, not a licence one — every Deepchecks check is a batch
    `SingleDatasetCheck`/`TrainTestCheck` over a `Dataset`, so it has no per-request API
    at all. It stays available as an offline job.
14. **NOT STARTED** — Point garak's shields-up / shields-down probes at AFNI's own
    gateway to prove the rails fire, and add that to the release gate.

## Measurement

15. **NOT STARTED** — **Measure the guardrails rather than assuming them.** PyRIT
    `scorer_evaluation` with Krippendorff's alpha against a human-labelled production
    sample; publish a real precision and recall figure per detector. Nothing in this
    platform currently claims an accuracy number, and that is deliberate.
16. **NEEDS A HOST** — Re-run the 280-record corpus baseline at Stage 1, then at
    Stage 1 + 2, on a machine with the model weights. The gap between those two numbers
    is the single most persuasive artefact this project has. **On the free tier alone,
    279 of 280 harmful prompts pass** — Stage 1 matches patterns, and harmful intent in
    ordinary English has no pattern to match.
17. **NOT STARTED** — Quarterly re-benchmarking. garak's own published detector metrics
    and the archived status of `llm-guard-main` both mean accuracy decays unless
    somebody owns it.

## Fairness, explainability and the batch work

18. **PARTIAL** — Fairlearn + AIF360 MDSS/FACTS for any application making decisions
    about people. **A scheduled batch job, never a runtime check** — one response is not
    a fairness measurement. Registered as offline cover; no scheduled job exists yet.
19. **PARTIAL** — SHAP for tabular and text explanations behind an async `explain`
    endpoint backed by a background job. SHAP is far too slow for synchronous handling.
    Registered; the endpoint is not built.

## Governance and accountability

20. **BUILT** — The audit store: every verdict from runtime, offline and replay in one
    schema, with findings, redaction spans and trace spans. **Matched values are never
    stored — only a fingerprint.** OpenTelemetry export is wired but off by default.
21. **NOT STARTED — THE LAST REAL BLOCKER** — Name **one accountable owner per tenet**.
    Seven names from AFNI, recorded with the seven tenets and their current thresholds
    in a single governance register. No code can do this.
22. **NOT STARTED** — The **standard client approval pack**, produced from CI artefacts:
    OWASP LLM Top 10, NIST AI RMF, MITRE ATLAS and EU AI Act mapped reports, plus the
    measured detector-accuracy table from item 15 and an audit-trail sample.
23. **NOT STARTED** — Publish the platform as an internal versioned package with a
    **mandatory adoption gate**: no AI-native application reaches production without
    routing through the gateway and passing the CI tiers.
24. **NOT STARTED** — The allowed/banned topic list per application. `TopicScopeRail` is
    built and tested but deliberately **unmounted**, because the list is a business
    decision, not a download.

## Conditional and dropped

25. **DROPPED (superseded)** — A *per-tenant / per-project* threshold configuration
    service on the Infosys admin pattern. AFNI removed the tenant dimension on
    2026-09-03. What remains, and is **BUILT**, is a single global threshold store with
    an operator override layer and a read log that proves on the detection path that a
    configured threshold was actually consulted — which was the only part of the Infosys
    pattern worth copying. The bug it avoids is Safe Zone's: a threshold stored,
    admin-exposed, and never read.
26. **CONDITIONAL** — Vendor the genuinely unique Infosys modules **only if the business
    needs them**: multi-format and DICOM PII scanning, NSFW image/video detection, and
    Faker-based anonymisation with differential privacy.
27. **CONDITIONAL** — Run the OpenAI Evals deception / sandbagging / covert-persuasion
    suite **once** against any AFNI product claiming agent autonomy, before it ships.

---

## A correction carried over from the old roadmap

The 90-day plan asked to "log the two vendor-risk items". One of them was wrong.

- **Guardrails AI's PyPI supply-chain compromise is real** and stays on the record. Any
  adoption must pin and vendor rather than resolve at install time. AFNI has asked for
  the package to be integrated regardless; that is tracked in `open-questions.md`.
- **`agentic_security-main` does NOT contain a hard-coded third-party bearer token.**
  This was checked at source on 2026-09-03: a scan for real credential shapes (`sk-`,
  `hf_`, `ghp_`, `AIza`, `xox*`, long bearer values) returns nothing. What is actually
  there is `Authorization: Bearer XXXXX` at
  `references/agentic_security-main/agentic_security/config.py:99`, inside a function
  that writes a **default config template for the user to fill in**, plus
  `Bearer test_api_key` in its own test suite. The repo even ships a redactor at
  `core/security.py:173` that scrubs bearer values from its logs. The earlier claim was
  wrong and is withdrawn.

## The bottom line

Spend where the risk is highest; use free deterministic checks everywhere else. Cheap
local checks on every request, paid calls only on borderline traffic, expensive thorough
work offline in nightly and pre-release testing. No single filter is ever the whole
defence.

Two rules matter more than any tool choice: **if a check cannot run, say so and block**,
and **measure how accurate each check really is** against human-reviewed examples
instead of trusting a vendor's claim. The first is built and unconditional. The second
is item 15, and it is not started.
