# How Each Tool Actually Works

Mechanism, cost, latency class and cascade stage for every tool that contributes a
check to each tenet. Derived by reading the actual source under `references/` — every
row in `data/tenet_methodology_facts.json` carries an `evidence` field naming the
`file:line`, model id or dependency it came from.

Regenerate with `python3 helpers/build_tenet_methodology_data.py`; rendered as deck
slides 62–68 by `helpers/build_deck_methodology.py`.

## Reading the Stage column

| Stage | Meaning |
|---|---|
| **Stage 1** | Free and deterministic — can run on every single request |
| **Stage 2** | Local model, or a cloud second opinion on borderline input only |
| **Stage 3** | Paid API required, or an LLM-judge call |
| **Delegates** | Provides a contract/taxonomy/orchestration but no detector of its own |
| **Offline** | CI and red-team only — never in the request path |

Stage is the **earliest** point a tool can contribute, taken from its *cheapest*
mechanism: LLM Guard's Security cover is both deterministic secret scanning and a
DeBERTa classifier, so it earns Stage 1 on the strength of the former. Latency is a
**range** across a row's mechanisms and is estimated from what the code does — it is
**not benchmarked**.


---

## Privacy

17 contributing tools — Stage 1 6 · Stage 3 1 · Delegates 2 · Offline 8

| Tool | Mechanism | What it does for this tenet | Cost | Latency | Runs | Target | Stage |
|---|---|---|---|---|---|---|---|
| hai-guardrails | Keyword/Regex + LLM-judge | piiGuard: 10 regexes incl ICD-10/MRN/NPI/DEA redaction; leakageGuard LLM-judge for prompt/config leaks | Free (+opt paid) | Very low-High | Local/remote | LLM text | **Stage 1** |
| Infosys RAI Toolkit | Module + Classifier | Presidio analyzer/anonymizer + roberta/PIIRanha NER; Faker and diffprivlib; DICOM/image redaction | Free (+opt paid) | Very low-Low | Local/remote | Both | **Stage 1** |
| LLM Guard | Module + Keyword/Regex + Classifier | Anonymize scanner: presidio-analyzer 2.2.358 + regex_patterns.py + ai4privacy NER; Vault deanonymize | Free | Very low-Low | Local | LLM text | **Stage 1** |
| NeMo Guardrails | Module + Classifier | Presidio Analyzer/Anonymizer detect+mask rails; GLiNER NIM (nvidia/gliner-pii) zero-shot NER | Free | Very low-Low | Local/remote | LLM text | **Stage 1** |
| Rebuff | Keyword/Regex | Canary word (secrets.token_hex) hidden in prompt as an HTML comment; substring check on the completion | Free (+opt paid) | Very low | Local/remote | LLM text | **Stage 1** |
| Safe Zone (TSZ) | Keyword/Regex + LLM-judge | init.sql regex patterns (EMAIL, US_SSN, CREDIT_CARD, IBAN_TR) + AI_PROMPT LLM judges; no Luhn check | Free (+opt paid) | Very low-High | Local/remote | LLM text | **Stage 1** |
| DeepTeam | LLM-judge + Attack generator | PIIMetric/PromptExtractionMetric judge leaks; PrivacyGuard (gpt-4.1) screens live input and output | Paid API req. | High-Batch | Remote | LLM text | **Stage 3** |
| Guardrails AI | Module + Keyword/Regex | NO in-repo PII code - delegates to pip guardrails-ai-detect-pii (Presidio+spaCy); MockDetectPII is tests only | Free (+opt paid) | Very low | Local/remote | LLM text | **Delegates** |
| OpenGuardrails | Cloud API + Module | taxonomy privacy.pii.* registry + presidio name mapping; no detector of its own; redact.go splices spans | Free | Very low-Medium | Remote | LLM text | **Delegates** |
| Agentic Security | Keyword/Regex | PIIDetector regex set (email/SSN/phone/private key/token) plus Luhn-checked cards; ships DISABLED by default | Free | Batch | Local | LLM text | **Offline** |
| Deepchecks | Keyword/Regex | Regex email/URL counts as TextData properties only; no Presidio, no NER, no redaction capability | Free | Batch | Local | LLM text | **Offline** |
| DeepEval | LLM-judge | PIILeakageMetric uses extract_pii + generate_verdicts Jinja prompts judged by an LLM - no regex, no Presidio | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| garak | Attack generator + Keyword/Regex | ProPILE twin/triplet/quad probes; propile.PIILeak exact + Jaro-Winkler match; sysprompt 4-gram overlap | Free | Batch | Local | LLM text | **Offline** |
| Giskard v3 | Attack generator + LLM-judge | No native PII check at all; only optional deepteam PIILeakage/PromptLeakage + garak data-exfil probes | Paid API req. | Batch | Remote | LLM text | **Offline** |
| JCB | Module + Statistical | Memorisation test: 100 copyright behaviors + datasketch MinHash Jaccard>0.6 vs 100 reference hash files | Free | Batch | Local | LLM text | **Offline** |
| Promptfoo | Attack generator + LLM-judge | PII plugins (pii:direct/api-db/session/social) generate probes; PiiGrader LLM rubric judges disclosure | Free (+opt paid) | Batch | Remote | LLM text | **Offline** |
| PyRIT | Module + Attack generator | SystemPromptExtractionScorer n-gram overlap + PlagiarismScorer LCS/Jaccard vs reference text | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |

**Stage 3 — cloud / paid fallbacks:** Microsoft Presidio (open-source, but the de facto engine everything wraps); Azure AI Language PII detection service; AWS Bedrock Guardrails (PII filters and masking); Private AI / Polygraf PII (already wired as NeMo Guardrails rails); NVIDIA GLiNER-PII NIM (hosted zero-shot PII NER)

---

## Security

16 contributing tools — Stage 1 5 · Stage 2 1 · Stage 3 2 · Offline 8

| Tool | Mechanism | What it does for this tenet | Cost | Latency | Runs | Target | Stage |
|---|---|---|---|---|---|---|---|
| hai-guardrails | Keyword/Regex + LLM-judge | injectionGuard heuristic/pattern/LLM modes; secretGuard 25 vendor regexes gated by Shannon entropy | Free (+opt paid) | Very low-High | Local/remote | LLM text | **Stage 1** |
| LLM Guard | Classifier + Keyword/Regex | protectai/deberta-v3-base-prompt-injection-v2 + bc-detect-secrets (95 plugins) + unicode invisible-char strip | Free | Very low-Low | Local/remote | LLM text | **Stage 1** |
| NeMo Guardrails | Classifier + Keyword/Regex | NemoGuard-JailbreakDetect ONNX RF over Snowflake embeddings + YARA sqli/code/template/xss rules | Free (+opt paid) | Very low-Low | Local/remote | LLM text | **Stage 1** |
| OpenGuardrails | Keyword/Regex + Cloud API | benchmark-harness KeywordBaseline 23-term list + 6 ConfigRules regexes + EGRESS_ALLOW; reference only | Free | Very low-Medium | Local/remote | LLM text | **Stage 1** |
| Safe Zone (TSZ) | Keyword/Regex + LLM-judge | PROMPT_INJECTION_SIMPLE/JAILBREAK_DAN regexes + AWS/API-key SECRET regexes; injection AI_PROMPT | Free (+opt paid) | Very low-High | Local/remote | LLM text | **Stage 1** |
| Infosys RAI Toolkit | Classifier + LLM-judge | fine_tuned_promptInjection model + mpnet cosine vs jailbreak_embeddings.json; SmoothLLM/Bergeron critique | Free (+opt paid) | Low-High | Local/remote | LLM text | **Stage 2** |
| DeepTeam | Attack generator + LLM-judge | 23 single-turn + 5 multi-turn attacks (Crescendo/Tree/Linear); PromptInjection and Cybersecurity guards | Paid API req. | High-Batch | Remote | LLM text | **Stage 3** |
| Rebuff | Keyword/Regex + LLM-judge | L1 free heuristic (11x8x20x5 generated keywords, SequenceMatcher) then paid gpt-3.5 judge + pinecone top-20 | Paid API req. | Very low-High | Local/remote | LLM text | **Stage 3** |
| Agentic Security | Attack generator + Keyword/Regex | Jailbreak-dataset + stenography/adaptive-attack generators, YAML attack rules; SandboxEscapeDetector regex | Free (+opt paid) | Batch | Remote | LLM text | **Offline** |
| DeepEval | Keyword/Regex + Module | ToolPermissionMetric allow/deny lists + ToolCorrectnessMetric set-compare; fully deterministic, no LLM | Free | Batch | Local | LLM text | **Offline** |
| FuzzyAI | Attack generator + Cloud API | 20 attack handlers in attacks/enums.py: DAN, Crescendo, ActorAttack, BoN, pygad genetic, ManyShot, ArtPrompt | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| garak | Attack generator + Keyword/Regex | DAN/encoding/latent-injection probe packs; string detectors dan.DAN, shields.Up/Down, 58 apikey regexes | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| Giskard v3 | Attack generator + LLM-judge | 18 OWASP-LLM01 scenarios in prompt_injection.jsonl (leet/base64/multilingual/DAN) + Crescendo/GOAT/GCG | Paid API req. | Batch | Remote | LLM text | **Offline** |
| JCB | Attack generator | JCB loop: ChatGPT seed templates, WordNet synonym mutation, UCB/eps-greedy bandit reuse across behaviors | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| Promptfoo | Attack generator + LLM-judge | 30+ jailbreak/encoding strategies (GCG, Crescendo, GOAT, base64/ROT13/morse) + per-plugin LLM rubric graders | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| PyRIT | Attack generator + Keyword/Regex | 657 jailbreak templates + 90 converters + Crescendo/TAP/PAIR/SkeletonKey; regex SQLi/SSRF/secret scorers | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |

**Stage 3 — cloud / paid fallbacks:** Azure AI Content Safety Prompt Shields (jailbreak and indirect-injection detection); AWS Bedrock Guardrails; Azure AI Foundry red-team agent (already integrated in PyRIT); Cisco AI Defense / CrowdStrike AIDR / Prompt Security (available as NeMo Guardrails rails); Google Perspective API (as a scoring oracle)

---

## Fairness & Bias

13 contributing tools — Stage 2 1 · Stage 3 1 · Offline 11

| Tool | Mechanism | What it does for this tenet | Cost | Latency | Runs | Target | Stage |
|---|---|---|---|---|---|---|---|
| LLM Guard | Classifier | Bias output scanner runs valurank/distilroberta-bias text-classification against a threshold | Free | Low | Local | LLM text | **Stage 2** |
| hai-guardrails | LLM-judge | biasDetectionGuard = llmGuard scoring prompt, threshold 0.7, zod schema categories/affectedGroups | Paid API req. | High | Remote | LLM text | **Stage 3** |
| AIF360 | Statistical + Module | ClassificationMetric disparities + Theil; MDSS/FACTS bias_scan discovers the biased subgroup itself | Free | Batch | Local | Classical ML | **Offline** |
| Deepchecks | Statistical | PerformanceBias subgroup score gaps + decision-tree weak-segment search; class imbalance; PPS leakage | Free | Batch | Local | Both | **Offline** |
| DeepEval | LLM-judge + Classifier | BiasMetric rubric judge (gender/political/racial/geographic); BBQ + EquityMedQA harnesses; legacy Dbias model | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| DeepTeam | LLM-judge + Attack generator | BiasMetric judge on gender/race/religion/politics axes; NO bias guardrail exists - red-team only | Paid API req. | Batch | Remote | LLM text | **Offline** |
| Fairlearn | Statistical + Module | MetricFrame disaggregates metrics by sensitive_features; ThresholdOptimizer/ExponentiatedGradient mitigate | Free | Batch | Local | Classical ML | **Offline** |
| garak | Attack generator + Keyword/Regex | lmrc probes (Deadnaming, SlurUsage, Bullying) scored by Surge/OFCOM wordlists; no fairness metrics at all | Free | Batch | Local | LLM text | **Offline** |
| Giskard v3 | LLM-judge + Attack generator | Only adversarial 'Stereotypes and Discrimination' rules judged by Conformity + Toxicity hate_speech category | Paid API req. | Batch | Remote | LLM text | **Offline** |
| Infosys RAI Toolkit | Statistical + LLM-judge | aif360+fairlearn+holisticai disparity metrics and Reweighing/DIR/ThresholdOptimizer; GPT-4o image-bias judge | Free (+opt paid) | Batch | Local/remote | Both | **Offline** |
| Promptfoo | LLM-judge + Attack generator | bias:age/disability/gender/race probes - REMOTE-generated only - graded by BiasGrader stereotyping rubric | Free (+opt paid) | Batch | Remote | LLM text | **Offline** |
| PyRIT | Attack generator + LLM-judge | FairnessBiasBenchmark story probes over gendered_professions.yaml, scored by SelfAskCategoryScorer | Paid API req. | Batch | Remote | LLM text | **Offline** |
| SHAP | Statistical | shap.plots.group_difference: bootstrapped mean-SHAP gap between two cohorts, decomposes group metrics | Free | Batch | Local | Classical ML | **Offline** |

**Stage 3 — cloud / paid fallbacks:** Fiddler AI; Arthur AI; DataRobot (bias and fairness monitoring); Truera; Monitaur; Azure Machine Learning Responsible AI dashboard (Fairlearn-based)

---

## Explainability & Transparency

13 contributing tools — Stage 1 5 · Stage 3 2 · Offline 6

| Tool | Mechanism | What it does for this tenet | Cost | Latency | Runs | Target | Stage |
|---|---|---|---|---|---|---|---|
| Guardrails AI | Module + Keyword/Regex | RAIL XML/Pydantic to JSON Schema, Draft2020-12 enforcement, char-offset ErrorSpans on streamed output | Free (+opt paid) | Very low | Local | LLM text | **Stage 1** |
| LLM Guard | Module + Classifier | JSON scanner regex + json-repair validate/repair; ReadingTime words/200; BanTopics zero-shot scope | Free | Very low-Low | Local | LLM text | **Stage 1** |
| OpenGuardrails | Module + Cloud API | verdict.schema.json findings path/start/end/score/detector; tailhold.go holds stream tail for one verdict | Free | Very low-Medium | Remote | LLM text | **Stage 1** |
| Rebuff | Module | RebuffDetectionResponse/TacticResult return per-tactic score, threshold, detected flag and checks-run flags | Free | Very low | Local | LLM text | **Stage 1** |
| Safe Zone (TSZ) | Module + Keyword/Regex | ConfidenceExplanation JSON (regex_score, ai_score, final_score) + gojsonschema SCHEMA/REGEX validators | Free | Very low | Local | LLM text | **Stage 1** |
| DeepTeam | LLM-judge | TopicalGuard judges input/output against allowed_topics; HijackingMetric scores purpose deviation | Paid API req. | High | Remote | LLM text | **Stage 3** |
| NeMo Guardrails | LLM-judge | topic_safety_check prompt to nvidia/llama-3.1-nemoguard-8b-topic-control; on-topic/off-topic verdict | Free (+opt paid) | High | Local/remote | LLM text | **Stage 3** |
| AIF360 | Module + Statistical | MetricTextExplainer/MetricJSONExplainer emit templated metric explanations; FACTS mines counterfactual recourse | Free | Batch | Local | Classical ML | **Offline** |
| DeepEval | LLM-judge + Module | GEval/DAG Jinja rubric judges emit score+reason; JsonCorrectness pydantic validate; PatternMatch regex | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| Giskard v3 | Module + LLM-judge | JsonValid (jsonschema), Readability (textstat), RegexMatching/Equals, plus LLMJudge/Conformity rubric judges | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| Infosys RAI Toolkit | Statistical + LLM-judge | shap.KernelExplainer/LimeTabularExplainer for ML; GPT-4 token-importance, G-Eval rubric, CoT/CoVe/GoT | Free (+opt paid) | Batch | Local/remote | Both | **Offline** |
| Promptfoo | LLM-judge + Keyword/Regex | llm-rubric / g-eval / model-graded-closedqa judges return reasons; regex, is-json, word-count validators | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| SHAP | Statistical | Explainer auto-picks Tree/Linear (exact) or Kernel/Deep/Permutation (approx); Text masker token attribution | Free | Batch | Local | Both | **Offline** |

**Stage 3 — cloud / paid fallbacks:** Microsoft InterpretML (open-source, Azure-aligned); IBM AIX360; LIME (open-source, used inside the Infosys toolkit); Fiddler AI / Arthur AI (hosted explainability dashboards); Azure Machine Learning Responsible AI dashboard

---

## Profanity / Content Safety

15 contributing tools — Stage 1 2 · Stage 2 2 · Stage 3 2 · Delegates 1 · Offline 8

| Tool | Mechanism | What it does for this tenet | Cost | Latency | Runs | Target | Stage |
|---|---|---|---|---|---|---|---|
| Infosys RAI Toolkit | Classifier + Keyword/Regex | Detoxify fine_tuned_toxicity_model, better_profanity wordlist (918 rows), deberta zero-shot, NudeNet/nsfw.h5 | Free | Very low-Low | Local | LLM text | **Stage 1** |
| LLM Guard | Classifier + Keyword/Regex | unitary/unbiased-toxic-roberta + BanSubstrings blocklist + BanTopics zero-shot + VADER sentiment | Free | Very low-Low | Local | LLM text | **Stage 1** |
| NeMo Guardrails | LLM-judge + Cloud API | content_safety rails to nemoguard-8b-content-safety, Llama Guard, ShieldGemma; ~8 vendor adapters | Free (+opt paid) | Medium-High | Local/remote | LLM text | **Stage 2** |
| Promptfoo | Cloud API + Attack generator | moderation assert to openai / azure text-content-safety / replicate llama-guard-4-12b; 26 harmful:* categories | Free (+opt paid) | Medium-Batch | Remote | LLM text | **Stage 2** |
| DeepTeam | LLM-judge + Attack generator | Toxicity/Graphic/Illegal judges + ToxicityGuard, IllegalGuard; Aegis and BeaverTails HF datasets | Paid API req. | High-Batch | Remote | LLM text | **Stage 3** |
| hai-guardrails | LLM-judge | toxic/hateSpeech/adultContent/profanity guards are all LLM prompts - no wordlist, no classifier | Paid API req. | High | Remote | LLM text | **Stage 3** |
| OpenGuardrails | Cloud API | taxonomy safety.* 11-category table only; no profanity or slur wordlist ships in this repo | Free | Medium | Remote | LLM text | **Delegates** |
| Agentic Security | Attack generator | Loads AdvBench/ForbiddenQuestion/MaliciousInstruct via EasyJailbreak_Datasets purely as attack prompts | Free | Batch | Remote | LLM text | **Offline** |
| Deepchecks | Classifier + Statistical | Toxicity via SkolkovoInstitute/roberta_toxicity_classifier + TextBlob sentiment/subjectivity | Free | Batch | Local | LLM text | **Offline** |
| DeepEval | LLM-judge + Classifier | ToxicityMetric LLM-judge on generate_verdicts.txt; optional Detoxify (original/unbiased/multilingual) scorer | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| FuzzyAI | Cloud API + NLI/Cross-encoder | Harm oracles: OpenAI omni-moderation-latest, Azure ContentSafety, AWS Guardrails, local bart-large-mnli | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| garak | Classifier + Keyword/Regex | HF detectors garak-llm/roberta_toxicity_classifier and toxic-comment-model; Surge/OFCOM/LDNOOBW wordlists | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| Giskard v3 | LLM-judge + Attack generator | Toxicity judge (6 categories) + HarmBench / Do-Not-Answer HF scenario sets via harmbench_safety.j2 | Paid API req. | Batch | Remote | LLM text | **Offline** |
| JCB | Classifier + Attack generator | 400 HarmBench behaviors + 50-row AdvBench subset; harm scored by local vLLM HarmBench-Llama-2-13b-cls | Free | Batch | Local | LLM text | **Offline** |
| PyRIT | LLM-judge + Cloud API | SelfAskLikertScorer over harm_definition YAMLs; Llama-Guard-3-8B and shieldgemma-9b; AzureContentFilter | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |

**Stage 3 — cloud / paid fallbacks:** Azure AI Content Safety (hate, sexual, violence, self-harm with severity levels, plus custom blocklists); OpenAI Moderation API (omni-moderation); AWS Bedrock Guardrails content filters; Google Perspective API; Llama Guard 3 / ShieldGemma / Nemotron Content Safety (self-hostable guard models, already wired into NeMo and PyRIT)

---

## Hallucination / Reliability

17 contributing tools — Stage 1 1 · Stage 2 2 · Stage 3 4 · Offline 10

| Tool | Mechanism | What it does for this tenet | Cost | Latency | Runs | Target | Stage |
|---|---|---|---|---|---|---|---|
| Safe Zone (TSZ) | Module | JSON/XML/JSON-Schema structural checks only; no auto-repair and no re-ask path exists in the code | Free | Very low | Local | LLM text | **Stage 1** |
| LLM Guard | NLI/Cross-encoder + Classifier | FactualConsistency entailment via MoritzLaurer/deberta-v3-base-zeroshot-v2.0; NoRefusal classifier | Free | Low | Local | LLM text | **Stage 2** |
| NeMo Guardrails | NLI/Cross-encoder + LLM-judge | AlignScore roberta-base nli_sp server; self_check_facts prompt; Patronus-Lynx-70B and Cleanlab rails | Free (+opt paid) | Low-High | Local/remote | LLM text | **Stage 2** |
| DeepTeam | LLM-judge | HallucinationMetric probes fake citations/APIs/entities/stats; HallucinationGuard fact-checks output | Paid API req. | High | Remote | LLM text | **Stage 3** |
| Guardrails AI | Module + LLM-judge | Schema-fail re-ask via constants.xml prompts; groundedness ONLY via external provenance-llm/embeddings pkgs | Paid API req. | Very low-High | Local/remote | LLM text | **Stage 3** |
| hai-guardrails | Module + LLM-judge | llmGuard repairs judge JSON via jsonrepair then zod safeParse; fails closed, no re-ask/retry loop | Paid API req. | Very low-High | Remote | LLM text | **Stage 3** |
| Infosys RAI Toolkit | LLM-judge + Statistical | show_score weighted mpnet cosine (input/output/source); GPT-4 self-score, G-Eval, CoVe; TrustLLM truthfulness | Free (+opt paid) | High-Batch | Local/remote | LLM text | **Stage 3** |
| Agentic Security | Keyword/Regex + Classifier | Refusal detection: 28-phrase REFUSAL_MARKS + one-class SVM (joblib); optional LLM judge | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| Deepchecks | Statistical + Classifier | Dataset drift (KS/EMD/PSI/Cramer's V), LoOP+IQR outliers, dup/null/mixed-type integrity, fasttext lang | Free (+opt paid) | Batch | Local/remote | Both | **Offline** |
| DeepEval | LLM-judge + NLI/Cross-encoder | Faithfulness claim-vs-truth verdicts; contextual precision/recall/relevancy judges; vectara CrossEncoder | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| FuzzyAI | Keyword/Regex + NLI/Cross-encoder | Refusal detection only: 7-phrase prefix list + bart-large-mnli disapproval score; no factuality check | Free | Batch | Local | LLM text | **Offline** |
| garak | Keyword/Regex + Classifier | packagehallucination pkg-list lookup; refusal via mitigation string list or garak-refusal-detector | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| Giskard v3 | LLM-judge + Module | Groundedness/Contradiction/AnswerRelevance judges + SemanticSimilarity cosine; KB sycophancy generator | Paid API req. | Batch | Remote | LLM text | **Offline** |
| JCB | Keyword/Regex + LLM-judge | 29-prefix AdvBench refusal list + gpt-4.1 judge score cutoff 8.5; MinHash verbatim-reproduction check | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| OpenAI Evals | LLM-judge + Keyword/Regex | 463 registry evals; modelgraded fact/closedqa judge prompts + Match/FuzzyMatch/Includes/JsonValidator | Paid API req. | Batch | Remote | LLM text | **Offline** |
| Promptfoo | LLM-judge + Statistical | context-faithfulness/recall/relevance + answer-relevance judges; rouge-n, bleu, meteor, levenshtein | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| PyRIT | Keyword/Regex + LLM-judge | PackageHallucinationScorer allow-list vs registry names (garak port); SelfAskRefusalScorer; PlagiarismScorer | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |

**Stage 3 — cloud / paid fallbacks:** Azure AI Content Safety groundedness detection; Patronus AI Lynx hallucination model (available as a NeMo rail); Cleanlab trustworthiness score (available as a NeMo rail); Fiddler AI faithfulness monitoring; Vectara hallucination evaluation model (self-hostable, wired into DeepEval)

---

## Accountability

17 contributing tools — Stage 1 6 · Stage 3 2 · Offline 9

| Tool | Mechanism | What it does for this tenet | Cost | Latency | Runs | Target | Stage |
|---|---|---|---|---|---|---|---|
| Guardrails AI | Module | SQLite guard_logs audit DB, Guard.history per-call tree, OTel spans, 8-value OnFailAction enum | Free | Very low | Local/remote | LLM text | **Stage 1** |
| Infosys RAI Toolkit | Module + Statistical | 16 checks gathered into summary(status,reason); admin ModerationCheckThreshold per account/portfolio; telemetry | Free | Very low-Batch | Local | Both | **Stage 1** |
| LLM Guard | Classifier + Module | BanCompetitors NER (guishe/nuner-v1_orgs); TokenLimit via tiktoken; slowapi rate limit in API layer | Free | Very low-Low | Local | LLM text | **Stage 1** |
| NeMo Guardrails | Module | OpenTelemetry span adapter + RailDecision ALLOW/BLOCK/TRANSFORM; rail_guard fail-closed envelope | Free | Very low | Local/remote | LLM text | **Stage 1** |
| OpenGuardrails | Module + Statistical | guard-event + verdict JSON Schemas, fail_mode open|closed + unjudged, composition strategies, F1 leaderboard | Free | Very low-Batch | Local/remote | LLM text | **Stage 1** |
| Safe Zone (TSZ) | Module | SecurityEvent POSTed to SIEM_WEBHOOK_URL, [AUDIT] log line, 50-event ring buffer, per-route rate limits | Free | Very low | Local/remote | LLM text | **Stage 1** |
| hai-guardrails | LLM-judge | copyrightGuard llmGuard prompt, threshold 0.8, flags lyrics/excerpts/code; no ethics guard exists | Paid API req. | High | Remote | LLM text | **Stage 3** |
| Rebuff | Module + Cloud API | Tactics run in fixed order, OR-combined; log_leakage writes the confirmed attack back into the vector corpus | Paid API req. | Very low-Medium | Remote | LLM text | **Stage 3** |
| Agentic Security | Statistical | Per-module failure rate vs max_th=0.3 PASS/FAIL, failures.csv, matplotlib chart; never exits non-zero | Free | Batch | Local | LLM text | **Offline** |
| Deepchecks | Module | Condition pass/fail per check with JUnit XML, JSON and HTML suite serializers for CI gating | Free | Batch | Local | Both | **Offline** |
| DeepEval | Module + LLM-judge | pytest11 assert_test fails on threshold miss; JSON results folder; Misuse/RoleViolation rubric judges | Free (+opt paid) | Batch | Local/remote | LLM text | **Offline** |
| DeepTeam | Module + LLM-judge | 5 framework maps (OWASP LLM/ASI, NIST AI RMF, MITRE ATLAS, EU AI Act) + CVSS scoring report | Paid API req. | Batch | Remote | LLM text | **Offline** |
| garak | Statistical | detector_metrics_summary.json holds per-detector F1/sensitivity/specificity from human + LLM labels | Free | Batch | Local | LLM text | **Offline** |
| Giskard v3 | Module | assert_passed + to_junit_xml/to_hub_format JSON; RegoPolicy via regorus; only OWASP LLM01 tags mapped | Free | Batch | Local | LLM text | **Offline** |
| OpenAI Evals | LLM-judge + Statistical | sandbagging (MMLU accuracy vs target), make_me_say/make_me_pay, ballots, steganography, bluff suites | Paid API req. | Batch | Remote | LLM text | **Offline** |
| Promptfoo | Module + Statistical | OTel spans + 6 framework maps (OWASP LLM, NIST RMF, ATLAS, EU AI Act, ISO 42001, GDPR), junit.xml, pass-rate gate | Free | Batch | Local/remote | LLM text | **Offline** |
| PyRIT | Module + Statistical | SQLite/AzureSQL memory (PromptMemoryEntries, ScoreEntry, AttackResults); ScorerEvaluator Krippendorff alpha | Free | Batch | Local/remote | LLM text | **Offline** |

**Stage 3 — cloud / paid fallbacks:** Monitaur (AI governance and model audit records); Fiddler AI / Arthur AI (production monitoring and drift alerting); DataRobot governance and model registry; Azure Monitor plus Application Insights for guardrail telemetry; Microsoft Purview for data-governance lineage

---

## Per-repo caveats found in the source

These came out of the source read and are not in the original deck.

- **`agentic_security-main`** — SECURITY: hard-coded default third-party bearer token CONFIRMED at probe_data/modules/fine_tuned.py:9 and rl_model.py:14, posted to mcp.metaheuristic.co/infer. Red-team fuzzer, NOT a runtime defence. Malwaregen/Hallucination/DataLeak are registry stubs with no loader.
- **`AIF360-main`** — Ships an R package (aif360/aif360-r via reticulate). setup.py pins scikit-learn<1.6. MDSS/FACTS confirmed - they FIND the biased subgroup rather than needing it named, which is the real differentiator vs Fairlearn.
- **`deepchecks-main`** — AGPL-3.0 CONFIRMED in LICENSE (+ ee/ commercial exception). Every check is a batch SingleDatasetCheck/TrainTestCheck over a Dataset - there is no per-request API at all. No MDSS/GerryFair/FACTS in tree despite those aspect labels.
- **`deepeval-main`** — v4.1.8, openai is a HARD dependency. Default judge gpt-5.4 - paid unless `deepeval set-ollama`. Only 4 of ~49 metrics are LLM-free (ExactMatch, PatternMatch, ToolPermission, AgentLoopDetection). Local classifier paths are legacy and their deps are undeclared.
- **`deepteam-main`** — Red-team framework PLUS 7 LLM-judge Guardrails that do run in-path. Every check is an LLM call; default gpt-4o-mini/gpt-4.1 needs OPENAI_API_KEY (Ollama swappable). No TAP/PAIR, no HarmBench, no ProPILE.
- **`evals-main`** — Suites confirmed as code+yaml, BUT 0 .jsonl remain under registry/data - all were Git-LFS stubs removed when references/ was committed, so sandbagging/ballots/steganography samples are ABSENT locally. MMLU/HellaSwag still load via hf://. Requires OPENAI_API_KEY at import.
- **`fairlearn-main`** — Pure numpy/pandas/scikit-learn/scipy/narwhals - no network, no model weights. Requires y_true plus a DECLARED sensitive_features column, which is why it is structurally offline-only.
- **`FuzzyAI-main`** — Offline CLI red-teamer requiring MongoDB; ollama/local providers make it free. No Llama Guard/ShieldGemma, no GCG/TAP/PAIR/GOAT code, no base64/ROT13 encoders despite the aspect labels.
- **`garak-main`** — CORRECTION: shields.Up/Down DETECTORS exist but ship with NO matching probe module - the deck's Phase-3 'point shields up/down at AFNI's gateway' action needs AFNI to write the probe. Attacker LLMs default to local HF; only judge.* detectors need a paid key.
- **`giskard-oss-main`** — CORRECTION: Giskard v3 is a rewrite and is LLM/agent-ONLY - tabular ML support was v2 and is gone. Sycophancy generator CONFIRMED (unique in the set). Default judge gpt-4o-mini; garak/deepteam are optional heavy extras.
- **`Guardrails-develop`** — v0.24.0.dev0. Jailbreak rail is documented FAIL-OPEN (jailbreak-protection.mdx:112) - confirms the deck's Phase-1 flip-to-fail-closed action. Heuristics pull gpt2-large. yara-python is an extra.
- **`guardrails-main`** — v0.11.0 is ORCHESTRATION ONLY - guardrails/validators ships just base classes; every real validator is a separate PyPI guardrails-ai-<name> package. This is the concrete basis for the Skip verdict. No ICD-10/MRN/NPI/DEA anywhere.
- **`hai-guardrails-main`** — @presidio-dev/hai-guardrails v1.11.0 TS/bun; NOT Microsoft Presidio despite the npm scope. No bundled model. Docs overclaim: no medical-licence/MAC/UUID/intl-phone patterns, no ethics guard.
- **`Infosys-Responsible-AI-Toolkit-master`** — Model weights are ABSENT from the repo - fine_tuned_*/PIIRanha/roberta/deberta/nsfw.h5/glove must be fetched into models/ (multi-GB, Git LFS). ~20 FastAPI services. Security (adversarial) module retired at 2.2.1, confirming the deck's finding.
- **`JCB-main`** — HarmBench fork shipping ONLY the JCB method and pipeline steps 1+3 - none of the paper's baselines. Supports a local judge but config defaults to paid gpt-4.1. Supports the Skip verdict.
- **`llm-guard-main`** — llm-guard 0.3.16 (Protect AI, archived); all scanners local HF transformers/torch with pinned model revisions, optional ONNX; no paid API; only URLReachability makes a network call at scan time.
- **`openguardrails-main`** — Spec repo. CORRECTION to prior framing: it DOES ship offline reference regex/keyword detectors (benchmarks/harness/detectors.py). Zero ML deps. Protocol v0.8 - pre-1.0 and breaking, confirming the pin-the-version action.
- **`promptfoo-main`** — v0.122.0 MIT. CONFIRMS the data-residency concern: harmful:*, bias:* and ~40 REMOTE_ONLY_PLUGIN_IDS require api.promptfoo.app, and llm-rubric grading also defaults remote. Richest compliance mapping of the whole set (6 frameworks incl. ISO 42001 + GDPR).
- **`PyRIT-main`** — v1.1.0.dev0, offline harness - nothing inline, though the ~11 pure re.search output scorers could be. Compliance mapping is only OWASP LLM01/LLM02 docstrings; there is NO NIST/ATLAS report generator (deck overstates this).
- **`rebuff-main`** — Only the L1 heuristic layer is genuinely free and local. JS SDK can swap Pinecone for self-hosted Chroma, but embeddings still call OpenAI ada-002. The self-hardening corpus (log_leakage back into the same index) is the part AFNI wants to reimplement.
- **`safe-zone-main`** — Go service. LLM layer defaults to LOCAL Ollama (llama3, config.go:104-106) so paid API is optional. No Luhn/checksum in code. Per-pattern thresholds are stored and API-exposed (admin.go:66) but never read by Detect - env globals only.
- **`shap-master`** — Pure local library, no paid API, no hardcoded model ids (user supplies the model). Kernel/Deep cost scales samples x features - that is the concrete reason it cannot run synchronously. Tree/Linear are fast. Also ships a GPUTreeExplainer.
