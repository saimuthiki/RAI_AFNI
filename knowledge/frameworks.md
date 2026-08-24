# The 23 Frameworks

Every tool reviewed at source level in Phase 0, with the adoption verdict. Source of
truth: `data/RAI_Synthesis.json` → `feasibility_matrix`, and `helpers/repo_slide_content.py`
→ `REPO_SLIDES`. Each tool's actual code is in `references/<folder>/`, indexed by graft
(`graft ask "<question>" --in references/<folder>/`).

Role: **Dev** = runs live in the request path · **Test** = offline red-team/eval ·
**Dev+Test** = both. Split as analysed: 12 Dev, 4 Test, 7 both.

| Tool | `references/` folder | Role | Tier | Verdict | Cost | Effort | License |
|---|---|---|---|---|---|---|---|
| DeepEval | `deepeval-main` | Dev | Tier 1 | **Adopt now** | Mixed (free core + optional paid add-ons) | Low | Apache-2.0 |
| DeepTeam | `deepteam-main` | Dev+Test | Tier 1 | **Adopt now** | Requires paid API or hosted model | Medium | Apache-2.0 |
| Fairlearn | `fairlearn-main` | Dev | Tier 1 | **Adopt now** | Free / open-source | Medium | MIT |
| LLM Guard (Protect AI) | `llm-guard-main` | Dev | Tier 1 | **Adopt now** | Free / open-source | Medium | MIT |
| NVIDIA NeMo Guardrails | `Guardrails-develop` | Dev | Tier 1 | **Adopt now** | Mixed (free core + optional paid add-ons) | Medium | Apache-2.0 |
| NVIDIA garak | `garak-main` | Test | Tier 1 | **Adopt now** | Mixed (free core + optional paid add-ons) | Medium | Apache-2.0 |
| OpenGuardrails Protocol (OGR) | `openguardrails-main` | Dev+Test | Tier 2 | **Adopt now** | Mixed (free core + optional paid add-ons) | Medium | Apache-2.0 |
| Promptfoo | `promptfoo-main` | Dev+Test | Tier 1 | **Adopt now** | Mixed (free core + optional paid add-ons) | Medium | MIT |
| PyRIT (Microsoft) | `PyRIT-main` | Dev+Test | Tier 1 | **Adopt now** | Mixed (free core + optional paid add-ons) | Medium | MIT |
| SHAP | `shap-master` | Dev | Tier 1 | **Adopt now** | Free / open-source | Medium | MIT |
| Agentic Security | `agentic_security-main` | Dev+Test | Tier 2 | **Bench for later** | Mixed (free core + optional paid add-ons) | Medium | Apache-2.0 |
| Deepchecks | `deepchecks-main` | Dev | Tier 2 | **Bench for later** | Free / open-source | Medium | AGPL-3.0 |
| FuzzyAI | `FuzzyAI-main` | Test | Tier 2 | **Bench for later** | Mixed (free core + optional paid add-ons) | Medium | Apache-2.0 |
| Giskard OSS (v3) | `giskard-oss-main` | Dev+Test | Tier 2 | **Bench for later** | Mixed (free core + optional paid add-ons) | Medium | Apache-2.0 |
| OpenAI Evals | `evals-main` | Dev+Test | Tier 2 | **Bench for later** | Mixed (free core + optional paid add-ons) | High | MIT |
| TSZ (Thyris Safe Zone) | `safe-zone-main` | Dev | Tier 2 | **Bench for later** | Mixed (free core + optional paid add-ons) | Medium | Apache-2.0 |
| Infosys Responsible AI Toolkit | `Infosys-Responsible-AI-Toolkit-master` | Dev | Tier 1 | **Combine with Guardrails-develop** | Mixed (free core + optional paid add-ons) | High | MIT |
| Rebuff (Protect AI) | `rebuff-main` | Dev | Tier 2 | **Combine with Guardrails-develop** | Mixed (free core + optional paid add-ons) | Low | Apache-2.0 |
| AI Fairness 360 (AIF360) | `AIF360-main` | Dev | Tier 1 | **Combine with fairlearn-main** | Free / open-source | Medium | Apache-2.0 |
| hai-guardrails | `hai-guardrails-main` | Dev | Tier 2 | **Combine with llm-guard-main** | Mixed (free core + optional paid add-ons) | Medium | MIT |
| Guardrails AI | `guardrails-main` | Dev | Tier 2 | **Skip** | Mixed (free core + optional paid add-ons) | Medium | Apache-2.0 |
| JCB (Jailbreak with Cross-Behavior Attacks) | `JCB-main` | Test | Tier 3 | **Skip** | Mixed (free core + optional paid add-ons) | High | MIT |
| LLMFuzzer | `LLMFuzzer-main` | Test | Tier 3 | **Skip** | Free / open-source | Low | MIT |

## How to read the verdicts

- **Adopt now (10)** — goes into the platform. Ten of the 23.
- **Combine with … (4)** — adopt, but only alongside the named primary; not a
  standalone choice. AIF360 behind Fairlearn; Infosys and Rebuff behind NeMo;
  hai-guardrails behind LLM Guard (port its PHI regexes into Presidio recognisers).
- **Bench for later (6)** — genuine capability, not Phase 1–3. Deepchecks is blocked
  on an AGPL-3.0 ruling; OpenAI Evals is worth one run against any product claiming
  agent autonomy (its deception / sandbagging / covert-persuasion suite).
- **Skip (3)** — Guardrails AI (superseded by NeMo for AFNI's shape, plus a documented
  PyPI supply-chain compromise), JCB and LLMFuzzer (narrow, high effort, low return).

## The ones that carry the platform

| Tool | Why it matters |
|---|---|
| **LLM Guard** | Presidio + ai4privacy DeBERTa NER + a **Vault for reversible redaction** (unique in the set — redaction stops breaking workflows). Also the DeBERTa-v3 prompt-injection classifier, local toxicity/bias models, zero-shot BanTopics, and a cross-encoder NLI groundedness scanner cheap enough to run on every response. Archived upstream → fork it. |
| **NeMo Guardrails** | The rail engine and orchestration layer. Plugin rails, YARA injection rules, perplexity heuristics, context-bloat checks, tool-schema validation, ~20 vendor adapters. |
| **OpenGuardrails** | No detectors — the Verdict/GuardEvent schema and taxonomy. The contract that makes every other choice swappable. |
| **PyRIT** | Deepest red-team coverage found: Crescendo, TAP, PAIR, Skeleton-Key multi-turn strategies, ~80 obfuscation converters, free regex output-scorers (SQLi, SSRF, secret leaks), a memory store, and `scorer_evaluation` with Krippendorff's alpha for measuring detector accuracy against human labels. |
| **garak** | Second offline scanner. Uniquely has **shields up / shields down** probes — point them at AFNI's own gateway to prove the rails actually fire. ProPILE probes for PII leakage. |
| **promptfoo** | The compliance reporting engine: OWASP LLM Top 10, NIST AI RMF, MITRE ATLAS and EU AI Act mapped reports straight out of CI. Also HarmBench / BeaverTails / DoNotAnswer / XSTest corpora. |
| **DeepEval** | G-Eval and DAG — versioned, CI-runnable rubrics with written reasons, instead of an ad-hoc prompt-based judge. Faithfulness and contextual precision/recall for RAG. |
| **Fairlearn + AIF360** | Fairlearn for everyday group metrics and mitigation (Azure-aligned, and Azure's own RAI dashboard is built on it). AIF360's MDSS and FACTS scanners **find which subgroup is biased** rather than requiring AFNI to already know which group to check. |
| **SHAP** | The tool Kiran named. 12 Shapley estimators behind one auto-dispatching API, Nature-published, with its own benchmark for judging whether an explanation is trustworthy. |

## Tools whose only role is to be borrowed from

Not deployed — specific parts are ported into the AFNI stack:

- **hai-guardrails** — the only dedicated healthcare PHI regex set found (ICD-10, MRN,
  NPI, DEA) plus entropy-gated secret patterns. Port into Presidio custom recognisers.
- **Rebuff** — canary-token leak detection and a self-hardening attack-signature store.
  Reimplement as native NeMo rails, seeded from the Phase-1 baseline findings.
- **Infosys toolkit** — the dispatcher shape (see [infosys-vs-nemo.md](infosys-vs-nemo.md)).
  Optionally vendor three genuinely unique modules if the business needs them:
  multi-format/DICOM PII scanning, NSFW image and video detection, and Faker-based
  anonymisation with differential privacy.
- **Presidio** (not in `references/`, but the de-facto engine four of these tools wrap) —
  18 country recognizer packs including India Aadhaar with Verhoeff checksum, PAN,
  GSTIN, and US SSN/ITIN/passport. Extending it is a ~50–130 line recogniser.
