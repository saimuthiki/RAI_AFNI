# -*- coding: utf-8 -*-
"""
Plain-English slide copy for each of the 23 repositories.
Hand-written summaries (by the assistant) derived from the deep-dive reports
in RAI_Repo_Reports.json, simplified for a client-facing deck, enriched with
tier/vendor/build-vs-buy framing and specific facts cross-checked against
external framework write-ups.
"""

REPO_SLIDES = [{'repo_folder': 'agentic_security-main',
  'display_name': 'Agentic Security',
  'tenets': ['Security', 'Privacy', 'Hallucination / Reliability'],
  'role': 'Both',
  'summary': 'A web tool that attacks your own chatbot with thousands of known jailbreak prompts (including '
             'hidden-in-image and hidden-in-audio tricks) and reports which ones got through. It grades each '
             'response using simple word-lists, a small trained model, and optionally another AI model as a judge.',
  'features': ['About 25 ready-made jailbreak and prompt-injection prompt collections, plus your own CSV or Google '
               'Sheet',
               'Can turn attacks into images or spoken audio to test picture- and voice-enabled bots',
               'Scrambles or encodes attacks (like Base64 or Caesar cipher) to see if disguising them still works',
               'Several ways to judge a response: keyword list, a small trained model, or an AI judge',
               'Stops testing early once it finds a bot is clearly failing, to save time and cost'],
  'limitations': ['Its own detectors are simple word/pattern checks with no published accuracy numbers',
                  "One optional add-on quietly connects to an outside company's server using a built-in password",
                  'Needs a decent Python setup; the AI-judge and cloud add-ons cost money'],
  'prerequisites': 'Python 3.12+, no GPU needed; optional paid OpenAI/Anthropic key for the AI-judge option',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration / Library / Model',
  'fit': "Use as an attack simulator to test AFNI's guardrails before launch, not as the guardrail itself.",
  'tier': 'Tier 2',
  'vendor': 'Independent (Alexander Miasoiedov)',
  'build_replicate': 'Moderate - the attack/scoring pipeline is easy to script, but the hidden cloud-calling module '
                     '(hard-coded token) must be stripped out first'},
 {'repo_folder': 'AIF360-main',
  'display_name': 'AI Fairness 360 (AIF360)',
  'tenets': ['Fairness & Bias', 'Explainability & Transparency', 'Accountability'],
  'role': 'Guardrail Development',
  'summary': "IBM's toolkit for checking whether a traditional prediction model (like a credit or hiring model) "
             "treats different groups of people fairly, and for fixing it if it doesn't. It measures over 50 "
             'fairness numbers and includes about 15 different fixes.',
  'features': ['50+ fairness metrics (e.g., are approval rates equal across groups?)',
               'Smart search tools that find the exact group of people being treated worst, without you guessing '
               'which group to check',
               '15 fixes you can apply before, during, or after training a model',
               'Plain-English explanations of what each fairness number means',
               'Works with standard data-science tools (scikit-learn)'],
  'limitations': ['Only works on structured data (spreadsheets), not on chatbot text',
                  'Some fixes need extra, sometimes older, software installed (TensorFlow 1.x, R, etc.)',
                  "You must decide which groups and outcomes count as 'fair' - the tool won't decide that for you"],
  'prerequisites': 'Python or R, no GPU or paid API needed for the core checks',
  'license': 'Apache-2.0',
  'cost': 'Free / open-source',
  'effort': 'Medium',
  'layer': 'Library-based',
  'fit': 'The go-to option for fairness checks on any traditional scoring model AFNI builds, not for chatbot output.',
  'tier': 'Tier 1',
  'vendor': 'IBM',
  'build_replicate': 'N/A, consume as-is - mature, peer-reviewed algorithms; re-implementing them would waste effort '
                     'better spent integrating'},
 {'repo_folder': 'deepchecks-main',
  'display_name': 'Deepchecks',
  'tenets': ['Hallucination / Reliability', 'Fairness & Bias'],
  'role': 'Guardrail Development',
  'summary': 'A testing toolkit that runs dozens of automatic quality checks on your data and models - for tables, '
             'text, and images - to catch problems like bad data, model drift, or weak performance on certain groups '
             'before they cause trouble.',
  'features': ["Ready-made check bundles ('suites') for text, tables, and images",
               'Flags toxic, low-quality, or gibberish text using built-in AI models',
               'Finds groups of records where the model performs worse than average',
               "Detects when live data has 'drifted' away from the data the model was trained on",
               'Every result can gate a build pipeline (pass/fail), like a unit test'],
  'limitations': ['No jailbreak, PII, or hallucination-in-generation checks - this is a data/quality tool, not a '
                  'safety filter',
                  'Uses a license (AGPL) that needs legal review before embedding in a product',
                  'Some text-quality models need a GPU to run at speed'],
  'prerequisites': 'Python, optional GPU for faster text-quality scoring',
  'license': 'AGPL-3.0',
  'cost': 'Free / open-source',
  'effort': 'Medium',
  'layer': 'Evaluation/Testing, Library, Model',
  'fit': 'Good as an offline data-quality and drift-detection gate in CI/CD, feeding the governance dashboard.',
  'tier': 'Tier 2',
  'vendor': 'Deepchecks',
  'build_replicate': 'Moderate - clean API, but AGPL-3.0 licensing needs legal clearance before embedding in a '
                     'client deliverable'},
 {'repo_folder': 'deepeval-main',
  'display_name': 'DeepEval',
  'tenets': ['Hallucination / Reliability', 'Fairness & Bias', 'Profanity / Content Safety', 'Privacy'],
  'role': 'Guardrail Development',
  'summary': 'A pytest-style testing framework with about 50 ready-made ways to grade an AI answer - did it make '
             'things up, was it biased, was it toxic, did it leak private information - plus 17 standard exam-style '
             'benchmarks. Most checks ask another AI model to be the judge.',
  'features': ['Hallucination, faithfulness, and relevancy checks for chatbot and RAG answers',
               'Bias, toxicity, and PII-leak scoring built in',
               'Some checks are simple and free (exact match, regex) with no AI cost',
               '17 academic exam benchmarks (like MMLU) to test overall model quality',
               'Plugs into your CI pipeline like a normal test suite'],
  'limitations': ['Most safety checks call a paid AI model as the judge',
                  'The jailbreak/attack side of this project was moved to a sister project called DeepTeam',
                  'No published accuracy numbers for its own judging - quality depends on the judge model'],
  'prerequisites': 'Python, an OpenAI (or similar) API key for most checks',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Low',
  'layer': 'Prompt/Template, Model, Library',
  'fit': "Strong choice as AFNI's main scoring engine for hallucination, bias, and content checks in CI/CD.",
  'tier': 'Tier 1',
  'vendor': 'Confident AI',
  'build_replicate': 'Easy - drop-in pytest plugin; the work is authoring golden test cases, not building the tool'},
 {'repo_folder': 'deepteam-main',
  'display_name': 'DeepTeam',
  'tenets': ['Security', 'Hallucination / Reliability', 'Fairness & Bias', 'Privacy'],
  'role': 'Both',
  'summary': 'The red-teaming sister of DeepEval. It automatically generates over 50 kinds of attacks (PII '
             'extraction, jailbreaks, SQL injection, bias baiting, and more) against your chatbot, and also ships 7 '
             'ready-to-use runtime guardrails you can turn on immediately.',
  'features': ['50+ vulnerability tests across privacy, security, safety, fairness, and business risk',
               "20+ jailbreak attack styles, including multi-turn 'slow escalation' attacks",
               '7 ready runtime guardrails (privacy, toxicity, prompt-injection, hallucination, and more)',
               'Automatically maps its tests to OWASP, NIST, and MITRE security standards',
               "Special test set for AI 'agents' that use tools (checks for abuse of tool access)"],
  'limitations': ['Every single check calls a paid AI model as the judge - nothing runs for free',
                  'No simple keyword or regex checks at all - 100% AI-judged',
                  'Python only, so a non-Python app needs a small bridge service'],
  'prerequisites': 'Python, OpenAI API key required for every check',
  'license': 'Apache-2.0',
  'cost': 'Requires paid API or hosted model',
  'effort': 'Medium',
  'layer': 'Prompt/Template, Model, Orchestration',
  'fit': 'Excellent pre-launch red-team suite; pair with a free regex/PII layer since it has none of its own.',
  'tier': 'Tier 1',
  'vendor': 'Confident AI',
  'build_replicate': 'Easy - one-line red_team() call once the target is wrapped; the attack taxonomy is already '
                     'built'},
 {'repo_folder': 'evals-main',
  'display_name': 'OpenAI Evals',
  'tenets': ['Accountability', 'Hallucination / Reliability', 'Security', 'Explainability & Transparency'],
  'role': 'Both',
  'summary': "OpenAI's own testing framework, with about 463 ready-made test tasks plus some unusual 'can this AI "
             "deceive another AI' games (bluffing, secret-codeword persuasion, hiding its own abilities). Useful for "
             'measuring trustworthiness, not for blocking bad output live.',
  'features': ['Simple free checks (exact match, contains, JSON validity) with no AI cost',
               "A generic 'ask an AI to grade this' engine for custom rubrics",
               'Unusual deception-testing games: can one AI secretly manipulate or con another?',
               '463 pre-built benchmark tasks covering many topics',
               'Works with OpenAI, Anthropic, Google, and other providers'],
  'limitations': ["Command-line/batch tool only - no live 'check this text now' function",
                  'No PII, bias, or toxicity detectors of its own',
                  'Most checks need a paid AI API call'],
  'prerequisites': 'Python, OpenAI API key for most evals',
  'license': 'MIT',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'High',
  'layer': 'Evaluation/Testing, Orchestration, Prompt/Template',
  'fit': 'Niche value: its deception/manipulation games are a good addition to a pre-release trust audit.',
  'tier': 'Tier 2',
  'vendor': 'OpenAI',
  'build_replicate': 'Moderate - CLI/registry workflow needs a custom adapter before it can be called from a live '
                     'backend'},
 {'repo_folder': 'fairlearn-main',
  'display_name': 'Fairlearn',
  'tenets': ['Fairness & Bias'],
  'role': 'Guardrail Development',
  'summary': "Microsoft's fairness toolkit, similar in spirit to AIF360 but tightly built around standard "
             'data-science tools. It measures group fairness (e.g., equal approval rates) and can retrain or adjust '
             'a model so its decisions are fairer across groups.',
  'features': ['Easy-to-read fairness report across any grouping (age, gender, region, etc.)',
               'Automatic versions of common accuracy metrics split out by group',
               'Algorithms that adjust model training or decision thresholds to close fairness gaps',
               'Works cleanly with scikit-learn pipelines',
               'Can check more than one sensitive attribute at once (e.g., age AND gender together)'],
  'limitations': ['Only for traditional prediction models with clear right/wrong labels, not chatbot text',
                  'You must already have the true outcomes and the sensitive group labels ready',
                  "The project itself says fairness metrics can conflict and don't cover every ethical concern"],
  'prerequisites': 'Python, no GPU or paid API needed for core use',
  'license': 'MIT',
  'cost': 'Free / open-source',
  'effort': 'Medium',
  'layer': 'Library, Model-based',
  'fit': "Microsoft's own answer to AIF360 - a strong, Azure-aligned pick for structured-model fairness checks.",
  'tier': 'Tier 1',
  'vendor': 'Microsoft',
  'build_replicate': 'N/A, consume as-is - Azure-aligned and peer-reviewed; adopt directly rather than rebuild'},
 {'repo_folder': 'FuzzyAI-main',
  'display_name': 'FuzzyAI',
  'tenets': ['Security', 'Hallucination / Reliability', 'Profanity / Content Safety'],
  'role': 'Vulnerability / Red-Team Testing',
  'summary': 'A red-teaming tool from CyberArk with 20+ jailbreak attack styles (including genetic-algorithm-evolved '
             "attacks) and 14 ways to judge whether an attack worked, including calling Azure, AWS, and OpenAI's own "
             'safety filters to compare results.',
  'features': ['20+ jailbreak techniques, from simple role-play tricks to AI-evolved attack prompts',
               'Can call Azure Content Safety, AWS Bedrock Guardrails, or OpenAI Moderation as judges - handy for '
               'comparing cloud filters side by side',
               "Multi-turn 'slow escalation' style attacks (Crescendo)",
               'Works against OpenAI, Anthropic, Azure, AWS, and local models',
               'Optional fully free/local mode using Ollama'],
  'limitations': ["It's an attack tool, not a defense - it doesn't block anything in production",
                  'No accuracy numbers for its own judges; several use hand-picked cutoff scores',
                  'Very light automated testing of its own code'],
  'prerequisites': 'Python 3.10+, optional GPU for local classifiers, API keys for cloud targets/judges',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration, Model, Prompt/Template',
  'fit': "Useful for benchmarking how AFNI's chosen cloud guardrail stacks up against many attack styles.",
  'tier': 'Tier 2',
  'vendor': 'CyberArk',
  'build_replicate': 'Moderate - clean plugin API, but the heavier attacks need GPU-backed local models'},
 {'repo_folder': 'garak-main',
  'display_name': 'NVIDIA garak',
  'tenets': ['Security', 'Profanity / Content Safety', 'Privacy', 'Hallucination / Reliability'],
  'role': 'Vulnerability / Red-Team Testing',
  'summary': "Often called 'nmap for LLMs' - NVIDIA's open-source scanner that fires over 100 different attack types "
             'at a chatbot (jailbreaks, hidden-encoding tricks, PII leakage tests, fake-package generation) and '
             'grades the results. It even publishes how accurate some of its own graders are.',
  'features': ['100+ attack probes: jailbreaks, prompt injection, 20 different text-encoding tricks, and more',
               "Checks whether generated code recommends software packages that don't actually exist (a real "
               'supply-chain risk)',
               'Built-in toxicity and hate-speech word-lists plus two AI toxicity models',
               "Can test whether your own guardrail is even switched on ('shields up/down' check)",
               'Publishes real accuracy numbers for a few of its checks - refreshingly honest about their limits'],
  'limitations': ['The maintainers say clearly: this is a security tool, not a bias or social-safety benchmark',
                  'Most of its 100+ checks have no published accuracy numbers',
                  'Built for offline scanning, not for blocking a live production message'],
  'prerequisites': 'Python 3.11-3.13, optional GPU, API keys for cloud targets',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Evaluation/Testing, Orchestration, Model',
  'fit': "A strong, well-respected offline scanner for AFNI's pre-release security testing stage.",
  'tier': 'Tier 1',
  'vendor': 'NVIDIA',
  'build_replicate': 'Moderate - reusing one detector is easy; the CLI/harness/plugin-cache system is the real '
                     'design centre and expects a full Generator adapter'},
 {'repo_folder': 'giskard-oss-main',
  'display_name': 'Giskard OSS (v3)',
  'tenets': ['Hallucination / Reliability', 'Security', 'Profanity / Content Safety', 'Privacy'],
  'role': 'Both',
  'summary': 'A testing framework for AI agents that both grades answer quality (is it grounded, toxic, relevant?) '
             "and auto-generates attack scenarios. It can also plug in NVIDIA garak's and DeepTeam's attacks so you "
             'get their coverage inside one tool.',
  'features': ['AI-judge checks for groundedness, contradiction, toxicity, and answer relevance',
               'Free, no-AI-cost checks too: exact match, JSON validity, readability score',
               'Auto-generates jailbreak and prompt-injection test scenarios',
               'Bridges to garak and DeepTeam so their attack libraries run inside the same reporting format',
               'Tags every finding with the matching OWASP Top-10 risk number'],
  'limitations': ["This is a brand-new rewrite (marked 'Beta'); the older, more proven version is no longer "
                  'maintained',
                  'Its jailbreak/bias/PII coverage mostly comes from garak/DeepTeam add-ons, not its own code',
                  "No runtime blocking - it's for testing, not live enforcement"],
  'prerequisites': 'Python 3.12+, AI provider API key for judge checks',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration, Model, Evaluation/Testing',
  'fit': 'A useful hub that combines several testing tools, but still early-stage - watch before betting on it long '
         'term.',
  'tier': 'Tier 2',
  'vendor': 'Giskard AI',
  'build_replicate': 'Moderate - clean Scenario/Suite API, but the v3 rewrite is Beta and much of its attack '
                     'coverage is borrowed via garak/DeepTeam bridges'},
 {'repo_folder': 'Guardrails-develop',
  'display_name': 'NVIDIA NeMo Guardrails',
  'tenets': ['Security', 'Privacy', 'Profanity / Content Safety', 'Hallucination / Reliability'],
  'role': 'Guardrail Development',
  'summary': "NVIDIA's framework for wiring together many different safety checks around a chatbot at runtime - "
             "before the user's message reaches the AI, and before the AI's answer reaches the user. It comes with "
             'about 35 ready-made checks and can also call 15+ outside security vendors.',
  'features': ['Built-in PII detection and masking (using Microsoft Presidio)',
               'Jailbreak detection using both quick statistical tricks and a trained model',
               "Content-safety and 'is this answer grounded in the facts' checks using an AI judge",
               'A simple rule language (Colang) to design exactly how checks fire and in what order',
               'Ready-made connectors to ~25+ paid security vendors (Cisco, Fiddler, Patronus AI, and more)'],
  'limitations': ['If the jailbreak-detection service goes down, it lets requests through instead of blocking them '
                  'by default',
                  'The maintainers openly publish that the fast built-in jailbreak check only catches about 31% of '
                  'attacks',
                  'Many of the strongest checks (content safety, groundedness) need an AI model configured to judge '
                  'them',
                  'NVIDIA NIM enterprise safety models report 0.79-0.88 F1 with +100-300ms latency, and the OSS '
                  'self-managed server has no built-in high availability - production HA needs paid NVIDIA AI '
                  'Enterprise (~$4,500/GPU/yr list).'],
  'prerequisites': 'Python 3.10-3.13, an LLM for judge-based checks, extra downloads for PII/jailbreak add-ons',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration, Library, Model',
  'fit': "A strong candidate as AFNI's central runtime 'traffic control' layer that other checks plug into.",
  'tier': 'Tier 1',
  'vendor': 'NVIDIA',
  'build_replicate': "Moderate - the Colang orchestration pattern is replicable in-house, but rebuilding NVIDIA's "
                     "fine-tuned NemoGuard safety models needs a labelled dataset and training budget AFNI doesn't "
                     'have'},
 {'repo_folder': 'guardrails-main',
  'display_name': 'Guardrails AI',
  'tenets': ['Accountability', 'Explainability & Transparency', 'Hallucination / Reliability', 'Privacy'],
  'role': 'Guardrail Development',
  'summary': "A framework for wrapping any AI call with 'validators' - checks that run before and after the AI "
             'responds, with automatic re-asking if something fails. Important: this repo is just the engine; the '
             'actual checks (PII, toxicity, etc.) are separate downloadable add-ons.',
  'features': ['Automatically re-asks the AI with the exact error when a check fails, instead of just rejecting',
               'Seven ways to react to a failed check: fix it, filter it, block it, or raise an error, among others',
               'Works live even on streaming (word-by-word) responses',
               'Ships a ready-made server so it can sit in front of an existing OpenAI-style API with no code '
               'changes',
               'Records a full history of every check run, for audits'],
  'limitations': ['Ships zero real checks itself - every named check (PII, toxicity, secrets, etc.) is a separate '
                  'package to review and install',
                  'Had a real security incident in 2026: a hacked maintainer account published a tampered version to '
                  'the public package index',
                  'Currently changing how its checks are distributed, so some older instructions no longer match '
                  'reality',
                  'The Hub and its free hosted inference are being retired on August 6, 2026, and only about 78% of '
                  'validators had migrated to plain PyPI packages as of this review - a real near-term compatibility '
                  'risk.'],
  'prerequisites': 'Python 3.10-3.13, an AI provider key, one extra package per specific check you want',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration, Library',
  'fit': 'Usable as an alternative runtime engine to NeMo Guardrails, but pin versions carefully given its '
         'supply-chain incident.',
  'tier': 'Tier 2',
  'vendor': 'Guardrails AI, Inc.',
  'build_replicate': 'Easy - the Guard/validator/reask pattern is simple to replicate, but there is little reason '
                     'to; adopt the free core. The Aug 2026 Hub migration has already happened'},
 {'repo_folder': 'hai-guardrails-main',
  'display_name': 'hai-guardrails',
  'tenets': ['Security', 'Privacy', 'Profanity / Content Safety', 'Fairness & Bias'],
  'role': 'Guardrail Development',
  'summary': 'A JavaScript/TypeScript guardrail library with 10 guards (prompt injection, PII, secrets, toxicity, '
             'hate speech, bias, adult content, copyright, profanity, prompt leakage). Each guard can run as a '
             'simple keyword check, a regex check, or an AI-judge check.',
  'features': ['10 default PII types including US SSN, credit card, and several healthcare ID formats',
               '24 different secret/credential patterns (AWS keys, GitHub tokens, GitLab tokens, etc.) with a smart '
               'filter to cut false alarms',
               "A generic 'build your own AI-judge check' framework used for all its content-safety guards",
               'Choice of detection style per guard: keyword, regex, or AI judge',
               'Works with LangChain out of the box'],
  'limitations': ['Almost no automated tests for accuracy - only one test file, and it only tests message selection '
                  'logic',
                  "Not related to Microsoft's Presidio despite a similar-sounding maintainer name",
                  'Written in TypeScript/Node, so a Python backend needs a small bridge service to call it'],
  'prerequisites': 'Node.js or Bun, an AI provider key for the 6 content-safety guards',
  'license': 'MIT',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Library, Model, Orchestration',
  'fit': "A useful reference for its regex/secret patterns and AI-judge prompt designs, best ported into AFNI's "
         'Python stack.',
  'tier': 'Tier 2',
  'vendor': 'presidio-dev (independent, unrelated to Microsoft Presidio)',
  'build_replicate': 'Easy - a small, well-factored TypeScript SDK, but needs a Node microservice bridge to call '
                     "from AFNI's Python stack"},
 {'repo_folder': 'Infosys-Responsible-AI-Toolkit-master',
  'display_name': 'Infosys Responsible AI Toolkit',
  'tenets': ['Security', 'Privacy', 'Profanity / Content Safety', 'Fairness & Bias'],
  'role': 'Guardrail Development',
  'summary': 'The most complete toolkit in this review - about 20 connected services covering privacy, safety, '
             'fairness, hallucination, and explainability all at once, plus an admin console and dashboard. This is '
             'the closest match to the toolkit Sai built at his previous company and is the natural backbone for '
             "AFNI's own build.",
  'features': ['One central dispatcher sends a message to about 15 checks at once and returns a single pass/fail '
               "with evidence for each - exactly the 'one-stop' pattern AFNI wants",
               'Its own locally-run AI models for toxicity, jailbreak, restricted topics, and gibberish - no '
               'per-request cloud cost',
               'Privacy engine covering 30 PII types across text, PDFs, Word/Excel/PowerPoint files, images, and '
               'even video',
               'Fairness engine combining AIF360 and Fairlearn behind one simple interface',
               'Hallucination scoring that blends AI grading with text-similarity checks, plus SHAP/LIME '
               'explainability'],
  'limitations': ['This snapshot has its jailbreak-attack-simulation feature switched off/removed for this release',
                  'No published accuracy numbers for its own custom-trained models',
                  'Standing up the full ~20-service suite is a real infrastructure project, not a quick install',
                  'Version drift across internal modules (one service pins openai SDK 1.52.2, another 0.28.0) plus '
                  'hardcoded thresholds, with no vendor SLA on the OSS repo itself.'],
  'prerequisites': 'Python + FastAPI per service, several GB of model files, MongoDB-style storage, Elasticsearch '
                   'for logging; Azure Blob Storage (the file-storage module is hard-wired to it)',
  'license': 'MIT',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'High',
  'layer': 'Orchestration, Model, Prompt/Template',
  'fit': 'Best treated as a reference architecture or a consulting-supported deployment, not a quick pip install - a '
         'strong Azure fit given its native Azure Blob Storage dependency, and the shape (not the code) to copy for '
         "AFNI's own build.",
  'tier': 'Tier 1',
  'vendor': 'Infosys',
  'build_replicate': 'Hard - already OSS, so the real question is self-host TCO, not replication; standing up 20+ '
                     'microservices, Elasticsearch, MongoDB and an Angular front end is a multi-week platform '
                     'effort'},
 {'repo_folder': 'JCB-main',
  'display_name': 'JCB (Jailbreak with Cross-Behavior Attacks)',
  'tenets': ['Security', 'Hallucination / Reliability', 'Accountability'],
  'role': 'Vulnerability / Red-Team Testing',
  'summary': 'A university research project implementing one specific, very effective jailbreak attack method, built '
             "on top of the well-known HarmBench testing framework. It's a single attack technique with its own "
             'scoring, not a general toolkit.',
  'features': ['One advanced jailbreak method that learns from past successes to attack faster and better',
               '400 pre-written harmful test requests across 7 risk categories (weapons, cybercrime, misinformation, '
               'etc.)',
               'Uses a well-respected classifier model (from HarmBench) to score whether an attack truly succeeded',
               'Detects when a chatbot reproduces copyrighted lyrics or book text word-for-word',
               'Works against many AI providers, including local open-source models'],
  'limitations': ['Single-purpose research code, not a maintained product - no automated tests at all',
                  "Needs a paid AI judge model plus a large GPU-hosted classifier to get the 'real' accuracy score",
                  'File paths are hard-coded, so it only runs cleanly from its own folder'],
  'prerequisites': 'Python 3.12, GPU strongly recommended, OpenAI API key for the default judge',
  'license': 'MIT',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'High',
  'layer': 'Orchestration, Evaluation/Testing',
  'fit': "Use only as an occasional deep stress-test of AFNI's defenses, not as a running service.",
  'tier': 'Tier 3',
  'vendor': 'Academic (Vasudev Gohil, single-paper artifact)',
  'build_replicate': 'Hard - heavy GPU plus paid-judge dependency to reproduce, and it exists to attack, not defend; '
                     'useful only as an occasional external stress test'},
 {'repo_folder': 'LLMFuzzer-main',
  'display_name': 'LLMFuzzer',
  'tenets': ['Security', 'Accountability'],
  'role': 'Vulnerability / Red-Team Testing',
  'summary': 'A very small, no-longer-maintained tool that sends two example attacks (a prompt-injection trick and a '
             'hidden-Base64 trick) to a chatbot API and checks if a keyword shows up in the reply. Useful mainly as '
             'a simple idea, not as real software to adopt.',
  'features': ['Config-file driven - point it at any chatbot API',
               'Add your own attacks as simple text files',
               'Very lightweight, no heavy dependencies'],
  'limitations': ["Officially marked 'Unmaintained' by its own creator",
                  'Ships only 2 example attacks total',
                  'No test suite, no real reporting despite the settings mentioning reports'],
  'prerequisites': 'Python 3, a target chatbot API to test',
  'license': 'MIT',
  'cost': 'Free / open-source',
  'effort': 'Low',
  'layer': 'Library, Evaluation/Testing',
  'fit': 'Not worth adopting directly - just borrow its two attack ideas as seeds for a proper test suite.',
  'tier': 'Tier 3',
  'vendor': 'Independent, officially unmaintained',
  'build_replicate': 'Easy - trivial to replicate, but not worth adopting as-is; borrow its two attack ideas as '
                     'seeds instead'},
 {'repo_folder': 'llm-guard-main',
  'display_name': 'LLM Guard (Protect AI)',
  'tenets': ['Security', 'Privacy', 'Profanity / Content Safety', 'Hallucination / Reliability'],
  'role': 'Guardrail Development',
  'summary': 'A Python library with about 15 input checks and 20 output checks that can be chained together around a '
             'chatbot call. It builds on Microsoft Presidio for PII and uses several purpose-trained AI models for '
             'jailbreak, toxicity, and fact-checking.',
  'features': ['PII detection and masking (built on Presidio) with the ability to safely restore the original text '
               'later',
               'A dedicated jailbreak-detection AI model tuned specifically for this purpose',
               "A 'is the answer actually grounded in the facts' checker using an AI entailment model",
               'Secret/credential scanning and code-block detection',
               'A ready-made web service so all checks can run as one shared gateway',
               'Dedicated bias scanner (valurank/distilroberta-bias) and toxicity scanner '
               '(unitary/unbiased-toxic-roberta) - a fairness check most competing gateways lack'],
  'limitations': ["This project is officially archived - no longer actively maintained, so it won't get fixes for "
                  'brand-new attack types',
                  'Needs a decent-sized AI library stack (PyTorch/Transformers) and benefits from a GPU',
                  "Default sensitivity settings will likely need retuning for AFNI's own traffic"],
  'prerequisites': 'Python 3.10-3.12, PyTorch/Transformers, optional GPU',
  'license': 'MIT',
  'cost': 'Free / open-source',
  'effort': 'Medium',
  'layer': 'Library, Model, Orchestration',
  'fit': "Good building blocks for Privacy and Security, especially since it's built on Presidio like Sai's prior "
         "work - but plan to maintain it in-house since it's archived.",
  'tier': 'Tier 1',
  'vendor': 'Protect AI',
  'build_replicate': 'Easy - free, MIT-licensed, pip-installable; the only real work is standing up the FastAPI '
                     'gateway and tuning which scanners run inline vs. sampled'},
 {'repo_folder': 'openguardrails-main',
  'display_name': 'OpenGuardrails Protocol (OGR)',
  'tenets': ['Security', 'Privacy', 'Profanity / Content Safety', 'Accountability'],
  'role': 'Both',
  'summary': "This is not a working guardrail at all - it's a shared 'rulebook' (a data format and naming standard) "
             'for how different guardrail tools should report their findings, so tools from different vendors can '
             'plug into the same system. It ships only toy example checks to demonstrate the format.',
  'features': ['A standard way to describe a risk finding: category, severity, confidence score, and exactly which '
               'part of the text to redact',
               "A shared list of risk category names (PII types, jailbreak, secrets, and more) that any vendor's "
               'tool can use',
               'A clear rule for what happens if a check times out: block everything, or let it through, your choice',
               'Sample connectors for popular chatbot gateways',
               'A small benchmark showing how weak plain keyword-matching is compared to smarter detection'],
  'limitations': ["The maintainers state plainly: 'we do not build detection capability' - there is no real detector "
                  'inside',
                  'Still an early, unstable specification (version 0.8) that can change between releases',
                  'Its example benchmark tests are extremely small (8-14 examples per category)'],
  'prerequisites': 'Depends entirely on which real detector tool you plug in behind it',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration, Evaluation/Testing, Library',
  'fit': 'Worth reading as a design reference for how AFNI should format guardrail results, not worth adopting as a '
         'dependency.',
  'tier': 'Tier 2',
  'vendor': 'OpenGuardrails community',
  'build_replicate': "N/A, schema only - the maintainers themselves say 'we do not build detection capability'; "
                     'there is a contract to adopt, not code to replicate'},
 {'repo_folder': 'promptfoo-main',
  'display_name': 'Promptfoo',
  'tenets': ['Security', 'Hallucination / Reliability', 'Privacy', 'Fairness & Bias'],
  'role': 'Both',
  'summary': 'A large, actively growing testing tool (now backed by OpenAI) that both checks everyday answer quality '
             'and red-teams a chatbot with over 100 attack types across privacy, bias, harmful content, and many '
             'industry-specific rules (medical, financial, insurance, and more).',
  'features': ['100+ ready-made red-team checks: PII leaks, bias, jailbreaks, SQL injection, and dozens of '
               'industry-specific rules',
               '30+ attack styles, including multi-turn jailbreaks and code-based optimization attacks',
               'About 65 everyday quality checks (exact match, similarity score, AI-judge rubric, and more)',
               'Automatically tags findings against OWASP, NIST, and other named security standards',
               'A web dashboard for reviewing results over time'],
  'limitations': ["A large chunk of its best checks only work by calling promptfoo's own paid cloud service - not "
                  'fully self-hosted',
                  'Written in TypeScript/Node.js, so a Python backend needs a small bridge to use it',
                  'No published accuracy numbers - quality depends entirely on whichever AI model is set as the '
                  'judge'],
  'prerequisites': 'Node.js 22+, an AI provider key, optional promptfoo Cloud account for full plugin coverage',
  'license': 'MIT',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration, Prompt/Template, Evaluation/Testing',
  'fit': 'A strong CI/CD red-team and regression-test layer, especially valuable for its OWASP/NIST mapping and '
         'reporting.',
  'tier': 'Tier 1',
  'vendor': 'promptfoo / OpenAI',
  'build_replicate': "Moderate - quick to bolt onto CI via its CLI, but a Python backend can't import it natively "
                     '(Node/TypeScript) and many plugins are remote-only'},
 {'repo_folder': 'PyRIT-main',
  'display_name': 'PyRIT (Microsoft)',
  'tenets': ['Security', 'Hallucination / Reliability', 'Fairness & Bias', 'Profanity / Content Safety'],
  'role': 'Both',
  'summary': "Microsoft's own red-teaming framework - the tool Sai referenced from his Apple project. One AI model "
             'attacks a target chatbot using many attack styles, while a large library of scorers (AI-judge, trained '
             'models, and simple regex) grades every response.',
  'features': ['Multi-turn jailbreak strategies like Crescendo (slow escalation) and Tree-of-Attacks',
               'About 80 ways to disguise an attack (encoding, translation, ASCII art, and more)',
               'Can call Llama Guard, ShieldGemma, or Azure Content Safety directly as scoring judges',
               'Free, no-AI-cost regex scorers for SQL injection, secret leaks, and other technical risks',
               'A built-in tool to measure how well its own scorers agree with real human judgment (a trust check on '
               'the checker)'],
  'limitations': ['Most of its strongest scorers need a paid AI model or a GPU-hosted safety model',
                  'The maintainers openly admit one of their fast filters has a high false-alarm rate',
                  'A very large, fast-changing codebase with a heavy set of dependencies'],
  'prerequisites': 'Python 3.10-3.14, AI provider key, optional GPU for local safety models',
  'license': 'MIT',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration, Model, Library',
  'fit': "Directly matches Sai's prior hands-on Apple project experience - a top pick for AFNI's red-team engine, "
         'with reusable checklists for the runtime guardrail too.',
  'tier': 'Tier 1',
  'vendor': 'Microsoft AI Red Team',
  'build_replicate': 'Hard - the attack/scorer abstractions are clean, but the memory layer, async surface, and '
                     'large dependency tree make this a genuine platform commitment, not a quick pilot'},
 {'repo_folder': 'rebuff-main',
  'display_name': 'Rebuff (Protect AI)',
  'tenets': ['Security', 'Accountability'],
  'role': 'Guardrail Development',
  'summary': 'A focused, single-purpose tool just for catching prompt-injection attacks. It combines a keyword '
             "check, an AI-judge check, and a 'have we seen this attack before' memory search, plus a clever trick: "
             'it hides a secret code in the prompt and checks if that code leaks back out.',
  'features': ['Three different detection methods combined into one score: keyword matching, AI judge, and '
               'similarity search against known attacks',
               'Canary-token trick: plants a hidden code to catch system-prompt leaks',
               "Self-learning: once a real attack is confirmed, it's remembered so similar future attacks are caught "
               'faster',
               'Available in both Python and JavaScript',
               'Very light to add - about 10 lines of code to call it'],
  'limitations': ["The maintainers themselves call it 'still a prototype' that 'cannot provide 100% protection'",
                  'Only covers prompt-injection and leak detection - nothing else (no PII, toxicity, bias, or '
                  'hallucination checks)',
                  'Two of its three detection methods need a paid OpenAI key and a Pinecone database subscription'],
  'prerequisites': 'Python or Node.js, OpenAI API key, optional Pinecone account',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Low',
  'layer': 'Library, Model, Prompt/Template',
  'fit': "A cheap, quick first-pass filter for prompt injection; its 'self-learning' idea is worth copying into "
         "AFNI's own system.",
  'tier': 'Tier 2',
  'vendor': 'Protect AI',
  'build_replicate': 'Easy - about 10 lines of code to call; the real cost is a paid OpenAI key and a Pinecone index '
                     'for two of its three tactics'},
 {'repo_folder': 'safe-zone-main',
  'display_name': 'TSZ (Thyris Safe Zone)',
  'tenets': ['Privacy', 'Security', 'Hallucination / Reliability', 'Accountability'],
  'role': 'Guardrail Development',
  'summary': 'A standalone Go-based gateway service that sits in front of any AI call to catch PII, secrets, and '
             'prompt-injection attempts, and can even watch a live streaming response and cut it off mid-sentence if '
             'something bad shows up.',
  'features': ['Detects PII and secrets using fast, free regex rules, with an optional AI double-check for extra '
               'confidence',
               'Every decision shows its full reasoning (regex score + AI score = final score) for easy auditing',
               'Can plug into OpenAI, Azure OpenAI, or AWS Bedrock as a drop-in safety gateway',
               "Real-time 'streaming firewall' that can stop a bad answer while it's still being typed out",
               'Simple ALLOW / MASK / BLOCK settings you control per risk category'],
  'limitations': ['Most of its ready-made ID patterns are built for Turkey; global coverage relies on the (paid) AI '
                  'checks instead',
                  'Only one content-safety check (toxicity) ships by default; no bias or hallucination checks',
                  'Needs its own database and cache running alongside it (Postgres + Redis)'],
  'prerequisites': 'Go runtime, PostgreSQL, Redis, optional local or cloud AI model',
  'license': 'Apache-2.0',
  'cost': 'Mixed (free core + optional paid add-ons)',
  'effort': 'Medium',
  'layer': 'Orchestration, Library, Model',
  'fit': 'A solid front-door gateway pattern for Privacy/Security, especially the live streaming firewall idea - '
         'would need AFNI-specific ID patterns added.',
  'tier': 'Tier 2',
  'vendor': 'Thyris',
  'build_replicate': 'Moderate - a self-hosted Go service; core detection is free, but needs Postgres and Redis '
                     'running alongside it'},
 {'repo_folder': 'shap-master',
  'display_name': 'SHAP',
  'tenets': ['Explainability & Transparency', 'Fairness & Bias', 'Accountability'],
  'role': 'Guardrail Development',
  'summary': 'The most well-known explainability library in the industry. It shows, for any AI decision, exactly '
             'which input factors pushed the result up or down and by how much - the tool Kiran specifically asked '
             'about by name.',
  'features': ['Works with almost any model type: simple models, tree models (like XGBoost), deep learning, and even '
               'text-generation AI',
               'Beautiful, standard charts (waterfall, force plot, summary plot) that non-technical people can read',
               'A special chart that breaks down a fairness gap between two groups feature-by-feature',
               'Has its own built-in benchmark to check whether its explanations are actually trustworthy',
               'Backed by published academic research and used industry-wide'],
  'limitations': ['Purely an explainability tool - it does not detect PII, jailbreaks, toxicity, or hallucinations '
                  'on its own',
                  'Some explanation methods can be slow on very large or complex models',
                  "Needs direct access to the model itself (or its scoring function), which some hosted APIs don't "
                  'expose'],
  'prerequisites': 'Python, no GPU or paid API required to run locally',
  'license': 'MIT',
  'cost': 'Free / open-source',
  'effort': 'Medium',
  'layer': 'Library, Evaluation/Testing',
  'fit': "The clear pick for Explainability & Transparency - directly answers Kiran's question about SHAP with a "
         'real, mature tool.',
  'tier': 'Tier 1',
  'vendor': 'Community / academic (Lundberg et al.)',
  'build_replicate': 'N/A, consume as-is - mature, Nature-published, industry-standard; no reason to rebuild '
                     'Shapley-value estimation in-house'}]

# Sanity check helper
if __name__ == "__main__":
    print(f"{len(REPO_SLIDES)} repo slide entries defined")
    folders = [r["repo_folder"] for r in REPO_SLIDES]
    assert len(folders) == len(set(folders)), "duplicate repo_folder!"
