# Guardrail Development vs. Vulnerability Testing

Two halves, one closed loop. Source: deck slides 5 and 62.
`data/RAI_Synthesis.json` → `dev_vs_testing_split` is the authoritative tool split.

| Half | Runs | Count | Tools |
|---|---|---|---|
| **Development** (build the defence) | live, in front of and behind every AI call | 12 | LLM Guard, NeMo Guardrails, Guardrails AI, hai-guardrails, Safe Zone (TSZ), Rebuff, Infosys toolkit, Fairlearn, AIF360, SHAP, Deepchecks, DeepEval |
| **Testing** (attack the defence) | offline, pre-release and scheduled, in CI/CD | 4 | garak, FuzzyAI, JCB, LLMFuzzer |
| **Both** | both paths | 7 | PyRIT, DeepTeam, promptfoo, Giskard, Agentic Security, OpenAI Evals, OpenGuardrails |

## The four hand-offs — all automated

### 1 · The attack corpus becomes the test suite
PyRIT, garak, DeepTeam and promptfoo each generate adversarial inputs and score
whether the target complied. Export those generated prompts **together with the
scored verdict** into a single **versioned regression corpus in git**, tagged by
tenet and by OWASP LLM Top 10 category.

> **The corpus is the asset, not the tool.** It survives any future tool swap, and it
> is the single most persuasive thing to put in front of a client's security reviewer.

### 2 · Every finding becomes a named guardrail requirement
A jailbreak that got through is not a report line — it is a ticket against a specific
NeMo rail, a threshold change in LLM Guard, or a new blocklist entry. **It is closed
only when the same input is replayed and blocked.**

### 3 · CI gates the deploy — three tiers
Triggered by any change to prompts, rails, thresholds or model versions.

| Tier | When | Budget | Contents | Gate |
|---|---|---|---|---|
| **Fast** | every pull request | < 5 min | DeepEval + promptfoo deterministic assertions, PyRIT regex output scorers, replay of the frozen corpus of previously-fixed attacks | **100% of the frozen corpus must be blocked or the build fails** — regressions block the merge outright |
| **Medium** | merge to main | ~30–60 min | promptfoo redteam over the OWASP-mapped plugin set + a garak probe subset | gated on a **maximum attack-success rate**, not on zero findings — zero is not achievable |
| **Slow** | nightly / pre-release | unbounded | full PyRIT Crescendo, TAP and PAIR multi-turn attacks; DeepTeam agentic vulnerability probes; Deepchecks drift and data-quality suites | findings land as tickets |

### 4 · Test the guardrails, not just the model — the step most often skipped
- Point **garak's shields up / shields down probes at AFNI's own gateway** to confirm
  the rails actually fire. Add that check to the release gate.
- Run **PyRIT's `scorer_evaluation` with Krippendorff's alpha** against a
  human-labelled sample of production traffic each quarter, so AFNI can state a
  **measured precision and recall per detector** instead of a vendor claim.

## Why the loop closes
Every result from every tier is written in the OpenGuardrails Verdict schema. That is
what makes the whole thing showable: *here is the attack corpus, here is the gate,
here is the measured detector accuracy, here is the trend.*

Red-team and evaluation findings are the pass/fail gate in CI/CD — a guardrail change
only ships once it survives the attack suite. **Testing sharpens the development
layer, not the other way around.**
