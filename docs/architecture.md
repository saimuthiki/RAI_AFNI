# Architecture

How a request travels, what the cascade does, and how the live path relates to
the offline testing loop. Merged on 2026-09-03 from `rai_platform/docs/00-architecture.md`,
`rai_platform/docs/02-cascade.md` and `knowledge/dev-vs-test-loop.md` — they were three
files describing one subject, and the split made the reader hunt.


---

## The request path, in detail

*Was `rai_platform/docs/00-architecture.md`.*

The question this document answers: **a prompt arrives — what actually happens
to it?** How many branches, what runs in each, in what order, and when does the
gateway stop looking.

Everything here is generated from or verified against the running code. Every
sample output was captured from a real run, not written to illustrate.

---

### 1 · Two guardrails, one AI system between them

The gateway is called **twice per interaction**. Once on the prompt heading for
the model, once on the response heading back to the person.

```mermaid
flowchart LR
    USER(["User / caller"])
    IN["<b>INPUT GUARDRAIL</b><br/>POST /v1/guard<br/>kind: step/request"]
    AI["<b>YOUR AI SYSTEM</b><br/>chatbot · RAG · agent · summariser<br/><i>the gateway does not care which</i>"]
    OUT["<b>OUTPUT GUARDRAIL</b><br/>POST /v1/guard<br/>kind: step/response"]

    USER -->|"prompt"| IN
    IN -->|"allow"| AI
    IN -.->|"<b>block</b>"| REFUSE1["neutral refusal<br/>the model is never called<br/><i>no token spent</i>"]
    AI -->|"completion"| OUT
    OUT -->|"allow"| USER
    OUT -.->|"<b>block</b>"| REFUSE2["neutral refusal<br/>the answer never reaches the user"]

    AUDIT[("audit trail<br/>fingerprints only,<br/>never the matched value")]
    IN --> AUDIT
    OUT --> AUDIT
```

Both calls hit the **same endpoint** with the same 32 rails available. What
changes is `kind`, and that decides which rails apply.

**Why blocking on the way in matters commercially:** a prompt refused at the
input guardrail never reaches the model, so it costs no tokens. A jailbreak
stopped here is cheaper than one stopped after generation.

#### Which rails run in which direction

Nine of 32 rails are direction-specific, because running them the other way is
incoherent rather than merely wasteful:

| Direction | Rails | Why |
|---|---:|---|
| **Both** | 23 | An SSN is an SSN whichever way it travels. A leaked API key is a leak in either direction. All PII, secret, toxicity and profanity rails are here, and pinned by name in `tests/test_direction.py` so nobody narrows them later. |
| **Output only** | 8 | Groundedness compares an *answer* to its source — a prompt has no answer to ground. Refusal is something a model does. An invented import is something a model emits. Schema and format validators check the model's output against the caller's contract. `security.insecure_output` catches a model emitting `DROP TABLE`; a user *asking* about SQL injection is a support question. |
| **Input only** | 1 | The confirmed-attack corpus holds attack *prompts*. |

Two whole tenets are therefore **output-side only** — Explainability and
Hallucination — and Accountability's single runtime rail is input-side. That is
architecture, not oversight, and `test_per_tenet_direction_cover_is_exactly_as_designed`
pins the map so a deliberate asymmetry stays documented and an accidental one
gets caught.

**Proof it works.** Same string, both directions:

```
$ python rai_platform/cli.py check "How do I stop '; DROP TABLE customers; -- from working?"
ALLOWED after 1 cascade stage(s) in 0ms
  No findings - every rail judged the payload and found nothing.
  (2 stage(s) never ran - that is the saving)

$ python rai_platform/cli.py check --response "'; DROP TABLE customers; --"
BLOCKED after 1 cascade stage(s) in 0ms
  Blocked by:
    - NeMo YARA injection rules + PyRIT OWASP output scorers (Guardrails-develop)
      flagged sqli at payload.choices[0].message.content chars 1-13
      - deterministic match, no score - action block
```

Before the direction gate existed, the first of those was a false positive.

#### 1b · Two ways to wire it: you call twice, or the gateway calls for you

Everything above describes `POST /v1/guard`, which judges text you hand it. Your
application makes the two calls and owns the model call in between. That is the
integration to use when the AI system is yours and already deployed.

`POST /v1/chat` is the same topology with the gateway holding the model call, so
it is the gateway that sits in front of your model rather than beside it:

| | `/v1/guard` (twice) | `/v1/chat` (once) |
|---|---|---|
| Who calls the model | your application | the gateway |
| Calls you make | 2 | 1 |
| Order enforced by | your code | the gateway |
| Use it when | the AI system is yours and wired | you want the guardrail in front of a model, or you are demonstrating one |

Four steps, and **the order is the product**:

1. **Guard the prompt** — `kind: step/request`. If it blocks, **the target is
   never called.** The response says `target.called: false` and
   `tokens_saved: true`, and there is no code path from that branch to the
   target client. A jailbreak refused here costs nothing.
2. **Call the target** — one POST to `{AFNI_TARGET_BASE_URL}/chat/completions`,
   no retry. A retry would bill twice for one interaction and could return an
   answer the verdicts and the audit row are not about.
3. **Guard the completion** — `kind: step/response`.
4. **Withhold, or hand it over.** If the output guardrail blocks, the completion
   is not in the response under any key, not in an SSE frame, not in a log line,
   and not in the audit row — that store keeps fingerprints and has no column a
   completion could occupy.

Every failure resolves the same way — no unjudged text reaches the caller:

| What failed | `decision` | Completion |
|---|---|---|
| input guardrail found something | `blocked_on_input` | never generated |
| input cascade **raised** | `blocked_on_input` (`degraded` set) | never generated |
| the target errored or timed out | `target_error` | none exists |
| output guardrail found something | `blocked_on_output` | withheld |
| output cascade **raised** | `blocked_on_output` (`degraded` set) | withheld |

`POST /v1/chat/stream` emits the same four steps as Server-Sent Events: input
`stage` frames (`phase: input`), then `target_start`, then `target_done`, then
output `stage` frames (`phase: output`), then `final`, then `done`.
`target_done` deliberately carries latency and token counts but **no text** — the
completion exists there before the output guardrail has judged it, and streaming
it at that point would deliver it a beat before the guard that can stop it.

**Configuration** (`.env.example` carries the full contract):

```
AFNI_TARGET_BASE_URL=http://10.10.10.151:8506/v1
AFNI_TARGET_MODEL=qwen3-vl-8b-instruct
AFNI_TARGET_API_KEY=
AFNI_TARGET_TIMEOUT=60
```

With `AFNI_TARGET_BASE_URL` unset, `/v1/chat` returns a 503 in the standard error
shape naming the two variables to set, and `/v1/guard` plus every introspection
endpoint work exactly as before. A judge-only gateway is a supported deployment,
not a broken one.

**UNVERIFIED.** Both ids above are configuration, not facts. The build
environment cannot reach that address — it is private, and egress is proxied — so
no call has ever confirmed the endpoint or the model id from here. `/healthz`
reports `target.model_id_verified: false` and says `UNVERIFIED` in those words
until the endpoint's own `/models` listing confirms it at startup.

---

### 2 · Stage is the only axis that uses 1, 2, 3

An earlier revision of this document spent a section separating **Stage** from
**Phase**, because both used the numbers 1, 2, 3 and conflating them was the single
most common misreading of the platform.

**Phases are gone.** AFNI decided on 2026-09-03 to build the platform in one pass
rather than across a 90-day, three-phase calendar, so there is no second numbered axis
left to confuse Stage with. `1`, `2` and `3` now mean exactly one thing anywhere in this
platform: the runtime cost tier a request paid.

```mermaid
flowchart LR
    S1["Stage 1<br/>free regex<br/>sub-ms<br/>100% of traffic"] --> S2["Stage 2<br/>local model<br/>1-3 s on CPU<br/>borderline only"]
    S2 --> S3["Stage 3<br/>paid judge<br/>1-5 s<br/>last resort"]
    OFF["Offline<br/>CI and red-team<br/>NEVER in the request path"]
```

| | **Stage** 1/2/3 |
|---|---|
| What it orders | cost and latency, per request |
| Lives in | `afni_rai/cascade/` |
| Changes | every request |
| Question | "did this need a paid call?" |

**Your mental model — "caught in stage one, don't send it to stage two" — is exactly
right.** That is the whole cascade.

The one remaining repository-level axis is the **adoption verdict** — Adopt now /
Combine / Bench / Skip — in `afni_rai/registry/repositories.py`. It carries no number
and deliberately borrows no stage colour, because an adopted repository routinely backs
a Stage-3 rail. Those two facts are unrelated.

---

### 3 · Inside one guardrail: seven branches

One call fans out across seven tenets. They are independent — no tenet can
suppress another's finding — and they are evaluated **by stage, not by tenet**:
every tenet's Stage-1 rails run together, then the engine decides once whether to
escalate at all.

```mermaid
flowchart TB
    EV["GuardEvent arrives<br/>walk the payload for judgeable text<br/><i>transport metadata keys skipped</i>"]
    EV --> FAN{"fan out across 7 tenets"}

    FAN --> T1["<b>Privacy</b><br/>8 rails · both directions"]
    FAN --> T2["<b>Security</b><br/>8 rails · both directions"]
    FAN --> T3["<b>Content Safety</b><br/>6 rails · both directions"]
    FAN --> T4["<b>Hallucination</b><br/>5 rails · OUTPUT only"]
    FAN --> T5["<b>Fairness &amp; Bias</b><br/>2 rails · both directions"]
    FAN --> T6["<b>Explainability</b><br/>2 rails · OUTPUT only"]
    FAN --> T7["<b>Accountability</b><br/>1 rail · INPUT only<br/><i>plus audit, thresholds,<br/>compliance mapping</i>"]

    T1 --> ENG
    T2 --> ENG
    T3 --> ENG
    T4 --> ENG
    T5 --> ENG
    T6 --> ENG
    T7 --> ENG
    ENG["<b>ONE engine decides</b><br/>dedupe · escalate? · fail closed?<br/>afni_rai/cascade/engine.py"]
    ENG --> V["verdict + explanation"]
```

Rails per tenet, and the order the cascade reaches them:

| Tenet | Stage 1 | Stage 2 | Stage 3 | Total | Direction |
|---|---:|---:|---:|---:|---|
| Privacy | 6 | 1 | 1 | 8 | both |
| Security | 6 | 1 | 1 | 8 | both |
| Profanity / Content Safety | 3 | 2 | 1 | 6 | both |
| Hallucination / Reliability | 3 | 2 | 0 | 5 | output |
| Fairness & Bias | 1 | 1 | 0 | 2 | both |
| Explainability & Transparency | 2 | 0 | 0 | 2 | output |
| Accountability | 1 | 0 | 0 | 1 | input |
| **All** | **22** | **7** | **3** | **32** | |

---

### 4 · One branch in full: Privacy

Your question was: within one branch, how many frameworks, in what order, and
when does it stop. Privacy is the richest example — eight rails across all three
stages, drawn from six repositories.

```mermaid
flowchart TB
    IN["text"] --> S1

    subgraph S1["<b>STAGE 1</b> — 6 rails · free · sub-millisecond · runs on 100% of traffic"]
      direction TB
      A["credit_card<br/><i>agentic_security</i><br/>regex + Luhn checksum"]
      B["region_ids<br/><i>Infosys + Safe Zone</i><br/>SSN · Aadhaar · PAN + checksums"]
      C["healthcare_phi<br/><i>hai-guardrails</i><br/>ICD-10 · MRN · NPI · DEA"]
      D["pii_entities<br/><i>hai-guardrails + agentic_security</i><br/>email · phone · IP · IBAN"]
      E["reversible_anonymiser<br/><i>llm-guard</i><br/>placeholder + vault"]
      F["system_prompt_leakage<br/><i>hai-guardrails + garak</i><br/>n-gram containment"]
    end

    S1 --> D1{"what did Stage 1 find?"}

    D1 -->|"nothing"| STOP1["<b>ALLOW</b><br/>Stages 2 and 3 never run<br/><i>this is the overwhelming majority</i>"]
    D1 -->|"a confident block<br/>e.g. a leaked API key"| STOP2["<b>BLOCK</b><br/>short-circuit — Stages 2 and 3<br/>never run, nothing is paid for"]
    D1 -->|"HIGH severity, or a rail<br/>asked to escalate"| S2

    S2["<b>STAGE 2</b> · presidio_ner<br/><i>llm-guard → Presidio + spaCy en_core_web_lg</i><br/>catches a NAME, which no regex can<br/>threshold privacy.pii.ner_score = 0.5<br/><b>1-3 s on CPU</b>"]

    S2 --> D2{"decided?"}
    D2 -->|"entity above threshold"| BLOCK2["<b>BLOCK</b> or redact"]
    D2 -->|"below"| ALLOW2["<b>ALLOW</b>"]
    D2 -->|"weights absent"| UNJ["<b>unjudged</b><br/>fails closed on<br/>client-facing traffic"]
    D2 -->|"a response that looks<br/>like a leak of context"| S3

    S3["<b>STAGE 3</b> · pii_leakage_judge<br/><i>deepteam</i> PIIMetric prompt<br/>via the judge chain:<br/>openai[0] → openai[1] → gemini[0]<br/><b>metered · 1-5 s · last resort</b>"]
    S3 --> BLOCK2
```

Read the decision diamond after Stage 1 carefully, because it is your question
exactly:

- **A confident block stops everything.** `short_circuit = True` in
  `engine.py`, and Stages 2 and 3 are recorded as skipped. Nothing is paid for.
- **Nothing found also stops everything.** No escalation is requested, so the
  expensive tiers never run. This is the common case and it is where the money
  is saved.
- **Only doubt escalates** — a rail explicitly asking (`escalate=True`), or a
  finding severe enough that a second opinion is worth buying.

One nuance worth knowing, because it surprises people: **a PII hit at Stage 1
does escalate.** Those rails emit `action: redact` at HIGH severity rather than
`block`, because the right answer to a customer's SSN in a support ticket is
usually to mask it, not to reject the ticket. HIGH severity then buys the NER
second opinion. A *leaked credential*, by contrast, emits `action: block` and
short-circuits immediately.

#### The same shape, other branches

| Branch | Stage 1 catches | Stage 2 adds | Stage 3 adds |
|---|---|---|---|
| **Security** | injection patterns, encodings, secrets, invisible text | DeBERTa injection classifier — **the only thing that BLOCKS an injection** | Azure Prompt Shields *(unconfigured)* |
| **Content Safety** | graded profanity lexicon, leetspeak-normalised | 7-head toxicity transformer; zero-shot topics | LLM judge, threshold 0.8 |
| **Hallucination** | invented imports, refusal phrases, malformed JSON/XML | NLI entailment against a retrieved source; JSON Schema | — |
| **Fairness** | protected attribute + decision term co-occurring | bias classifier, threshold 0.7 | — (7 of 9 capabilities are **offline** batch jobs) |
| **Explainability** | 10 format validators, per-field schema explanations | — | — |
| **Accountability** | confirmed-attack corpus replay | — | — |

**Security is worth a warning.** No Stage-1 rail blocks a prompt injection — by
design, because PyRIT documents a high false-positive rate for those patterns, so
a regex hit buys a second opinion rather than a refusal. Without the Stage-2
classifier installed, a textbook injection produces four HIGH findings and is still
*allowed* — none of them carries the block action. Stage 1 alone is a **detector** for
injection, not a **control** against it.

---

### 5 · Every framework, by branch and stage

23 repositories reviewed at source level; **16 contribute** to the running
platform. Adoption verdict in the last column — remember it is about the repository, not
runtime tier.

| Branch | Stage | Rail | Repository | Verdict |
|---|:---:|---|---|:---:|
| **Privacy** | 1 | `privacy.credit_card` | agentic_security | bench |
| | 1 | `privacy.healthcare_phi` | hai-guardrails | combine |
| | 1 | `privacy.pii_entities` | hai-guardrails + agentic_security | combine |
| | 1 | `privacy.region_ids` | Infosys RAI Toolkit + Safe Zone | combine |
| | 1 | `privacy.reversible_anonymiser` | llm-guard | adopt |
| | 1 | `privacy.system_prompt_leakage` | hai-guardrails + garak | combine |
| | 2 | `privacy.presidio_ner` | llm-guard → Presidio | adopt |
| | 3 | `privacy.pii_leakage_judge` | deepteam | adopt |
| **Security** | 1 | `security.encoding.obfuscation` | garak | adopt |
| | 1 | `security.indirect_injection` | garak | adopt |
| | 1 | `security.injection.heuristic` | PyRIT | adopt |
| | 1 | `security.insecure_output` | NeMo Guardrails | adopt |
| | 1 | `security.invisible_text` | llm-guard | adopt |
| | 1 | `security.secrets` | garak *(+ AFNI LLM-provider prefixes)* | adopt |
| | 2 | `security.injection.deberta_v3_v2` | llm-guard | adopt |
| | 3 | `security.prompt_shields` | Azure AI Content Safety | — |
| **Content Safety** | 1 | `content_safety.banned_substrings` | llm-guard | adopt |
| | 1 | `content_safety.explicit` | Infosys RAI Toolkit + garak | combine |
| | 1 | `content_safety.profanity` | Infosys RAI Toolkit + garak | combine |
| | 2 | `content_safety.toxicity_model` | llm-guard | adopt |
| | 2 | `content_safety.zeroshot_topics` | llm-guard | adopt |
| | 3 | `content_safety.toxicity_judge` | hai-guardrails | combine |
| **Hallucination** | 1 | `package-hallucination` | garak | adopt |
| | 1 | `refusal-phrases` | promptfoo | adopt |
| | 1 | `structured-output-wellformed` | Safe Zone | bench |
| | 2 | `groundedness-nli` | llm-guard | adopt |
| | 2 | `structured-output-schema` | Safe Zone | bench |
| **Fairness** | 1 | `afni.fairness.protected_attribute` | AFNI, from promptfoo + DeepEval BBQ + Infosys | adopt |
| | 2 | `llm_guard.bias` | llm-guard | adopt |
| **Explainability** | 1 | `afni-format-validators` | Guardrails AI | skip |
| | 1 | `afni-schema-explain` | Guardrails AI | skip |
| **Accountability** | 1 | `attack-corpus-repeat` | Rebuff *(similarity from JCB)* | combine |

A dash means the repo's *patterns* were ported without the repo being adopted —
Safe Zone's Go service runs nowhere here; its structured-output checks were
reimplemented in stdlib Python.

**Offline, never in the request path** — 19 capabilities: garak, PyRIT,
promptfoo and DeepEval red-team suites; Fairlearn and AIF360 fairness metrics;
SHAP; Deepchecks drift. `Cascade.__init__` **raises** if you try to mount one.

Live version of this table, always current:

```bash
python rai_platform/cli.py rails        # every rail by stage, with its repo
python rai_platform/cli.py coverage     # 65 capabilities in five honest states
```

---

### 6 · Sample outputs — what you actually see

Captured from real runs on a machine with no Stage-3 credential and no Stage-2
weights installed - which is the honest default, and the reason two of these
block on a coverage gap rather than on a finding. Re-captured 2026-09-03 after
the `--internal` flag was removed; fail-closed is now unconditional.

#### Clean prompt — the common case

```
$ python rai_platform/cli.py check "Please summarise the attached invoice for finance."
ALLOWED after 1 cascade stage(s) in 0ms
  No findings - every rail judged the payload and found nothing.
  (2 stage(s) never ran - that is the saving)
```

**That last line is the product.** 22 rails ran in under a millisecond; the two
expensive tiers were never touched.

#### Leaked credential — blocked at Stage 1, nothing paid for

```
$ python rai_platform/cli.py check "our key is sk-proj-Xq7SvT2mNbLp9RdKzWyE4HcJ8FgAuQ3T"
BLOCKED after 1 cascade stage(s) in 1ms
  Blocked by:
    - garak dora key regexes + hai-guardrails entropy gate (+ AFNI LLM-provider
      prefixes) (garak-main) flagged api_key at payload.messages[0].content
      chars 11-51 - deterministic match, no score - action block
      - value withheld (fp 6c9f1c74838e3fed)
  (2 stage(s) never ran - that is the saving)
```

Note **`value withheld`**. The matched value is the key. A guardrail that prints
what it caught has defeated itself, so only a fingerprint is stored — and that
fingerprint is what a false-positive exception keys on.

#### Jailbreak — with the Stage-2 classifier installed

```
BLOCKED after 2 cascade stage(s) in 15568ms
  Blocked by:
    - LLM Guard DeBERTa-v3 prompt-injection classifier (llm-guard-main)
      flagged prompt_injection - confidence 1.00 (classifier) - action block
  Also flagged (did not block): 3
    - PyRIT static prompt-injection scorer (+ Safe Zone, Rebuff) (PyRIT-main)
      flagged instruction_override ... - deterministic match, no score - action flag
    - ... flagged system_prompt_extraction ... - action flag
    - ... flagged dan ... - action flag
  (1 stage(s) never ran - that is the saving)
```

Four findings; **one blocked**. Stage 1's three are `flag` — they escalated
rather than decided. Stage 3 never ran. Compare the confidence kinds: `1.00
(classifier)` is not the same claim as a regex at 1.00, and the output labels the
kind so nobody compares them naively.

#### The same jailbreak **without** the classifier

```
ALLOWED after 2 cascade stage(s) in 8118ms
  COULD NOT JUDGE 1 path(s): payload.messages[0].content
  Also flagged (did not block): 4
```

**Allowed.** This is the Security warning above, made concrete: on internal
traffic with no Stage-2 weights, a textbook injection gets through with four
HIGH findings. Install the model.

#### Toxicity — three tenets firing at once

Captured from the **provisioned** machine (`POST /v1/guard` via Swagger), because
the Stage-2 toxicity and bias models are what make it interesting:

```
verdict.decision: block          latency 2954 ms          stages_run 2
  BLOCKED BY
    content_safety.toxicity_model   safety.toxicity   score 1.00 (classifier)
                                    LLM Guard Toxicity (unbiased-toxic-roberta)
  ALSO FLAGGED
    content_safety.profanity        safety.toxicity.profanity   deterministic
                                    Infosys RAI Toolkit + garak
    llm_guard.bias                  x.afni.fairness.biased_language  0.94 (classifier)
  could_not_judge: []
```

Two tenets and three repositories on one payload, each attributed separately.
`could_not_judge` empty, Stage 3 skipped.

#### Output guardrail — a hallucinated package

```
$ python rai_platform/cli.py check --response "You can use:
import supercalifragil_utils"
ALLOWED after 1 cascade stage(s) in 89ms
  Also flagged (did not block): 1
    - garak packagehallucination (PyRIT port) (garak-main) flagged
      hallucinated_package at payload.choices[0].message.content
      - deterministic match, no score - action flag - value withheld (fp cbb04c80b9b42039)
  (2 stage(s) never ran - that is the saving)
```

This rail is **output-only**: a user naming a package they want is not a finding,
a model inventing one is. Two honest details:

- It **flags rather than blocks**, because an allow-list of real packages is
  never complete and refusing a whole answer over one unrecognised import would
  be the wrong trade.
- The import must be at the **start of a line**. `here is the code: import
  supercalifragil_utils` inline in prose does **not** trip it — deliberate, since
  matching `import` mid-sentence in ordinary English is a false-positive
  generator, but it does mean an answer that discusses an invented package
  conversationally slips past. A known limit, not a bug.

#### A coverage gap — louder than any finding

Real output, from a machine where the Stage-3 judge is not configured:

```
$ python rai_platform/cli.py check "my ssn is 123-45-6789 and card 4111111111111111"
BLOCKED after 3 cascade stage(s) in 5627ms
  COULD NOT JUDGE 1 path(s): payload.messages[0].content  <- not the same as 'found nothing'
  Also flagged (did not block): 5
    - AFNI region ID recognizers (Infosys-Responsible-AI-Toolkit-master + safe-zone-main)
      flagged national_id.us at payload.messages[0].content chars 10-21
      - deterministic match, no score - action redact - value withheld (fp 01a54629efb95228)
    - AFNI Luhn card check (agentic_security-main) flagged bank_card ... action redact
    - AFNI reversible anonymiser (Vault) (llm-guard-main) ... x2
    - Presidio analyzer (via LLM Guard) (llm-guard-main) flagged bank_card
      - confidence 1.00 (classifier) - action redact
```

Five findings across three stages, **and it BLOCKS** — but read *why*. Not one
of those five findings blocked: every one carries `action: redact`. The block is
the `COULD NOT JUDGE` line, because the Stage-3 PII-leakage judge has no
credential on this machine. **The refusal is the coverage gap, not a detection.**

This is the single most important thing to understand about the output. Install
the credential and the same request is *allowed* — with five findings and two
redaction spans attached. Both answers are correct; they mean completely
different things.

Note the mix of confidence kinds in one verdict: four `deterministic` matches
with no score, and one `1.00 (classifier)`. They are not comparable, and the
output refuses to pretend otherwise.

Printed **first and loudest**, because a finding means something looked and this
means nothing did. On client-facing traffic it blocks. Three states, not two:

| State | Meaning | Client-facing result |
|---|---|---|
| clean | a rail looked and found nothing | allow |
| finding | a rail looked and found something | allow or block by action |
| **unjudged** | a rail should have looked and **could not** | **block** |
| not applicable | the check does not apply in this direction | allow, recorded in the trace |

That last row is new and it matters: before it existed, output-only rails
reported `unjudged` on every prompt, so the warning fired on all traffic and
meant nothing.

---

### 7 · Regenerate any of this yourself

```bash
python rai_platform/cli.py rails         # 32 rails by stage, with repo and evidence
python rai_platform/cli.py coverage      # 65 capabilities, five states
python rai_platform/cli.py preflight     # what is missing and where it goes
curl -s localhost:8000/v1/rails    | python -m json.tool
curl -s localhost:8000/v1/coverage | python -m json.tool
curl -s localhost:8000/v1/repositories | python -m json.tool
curl -s localhost:8000/healthz     | python -m json.tool
```

Or open the console at <http://127.0.0.1:8000/> and watch a decision stream.

### See also

- `01-setup.md` — provisioning, in three levels
- `02-cascade.md` — the cascade in depth, with the source evidence behind each rule
- `../models/MANIFEST.md` — every downloadable asset
- `../../README.md` — the platform overall


---

## The cascade, stage by stage

*Was `rai_platform/docs/02-cascade.md`.*

How the gateway decides, and why it costs what it costs.

### The idea in one paragraph

Run every free, deterministic check on 100% of traffic. If one of them fires with
confidence, stop there — the request never reaches a paid call. Escalate only the
thin slice that survives, first to local models, then to a paid API or an LLM
judge. Anything too slow or too expensive to run per-request runs offline in CI
instead, against a versioned attack corpus.

That is the whole cost argument, and it is enforced in
`afni_rai/cascade/engine.py` rather than left to individual rails.

### The four stages

| Stage | What runs | Latency | Cost | Runs on |
|---|---|---|---|---|
| **Stage 1** | regex, keyword lists, checksums, unicode normalisation, schema checks | sub-millisecond | free | every request |
| **Stage 2** | a locally-run classifier or NLI model; or a cloud second opinion | ~1–3 s on CPU (measured) | free (local) or per-call | borderline input only |
| **Stage 3** | a paid API or an LLM-as-judge | ~1–5 s | per-call, the dearest | last resort |
| **Offline** | red-team attacks, fairness metrics, drift, SHAP | unbounded | CI budget | never in the request path |

Stage membership is **data, not a code decision**. It comes from
`analysis/data/tenet_methodology_data.json`, where each of the 108 repo-tenet
rows carries a mechanism, a cost, a latency class and a derived stage — each one
backed by a `file:line`, model id or dependency actually read from the vendored
source. A rail declares its stage; it does not get to invent one.

### Escalation is conditional, not layered-always

A common way to build this wrong is to run every layer on every request and call
it defence in depth. That is just paying three times for one answer.

A stage runs only when:

- a rail in the previous stage set `escalate=True` — it saw something suspicious
  but is not confident enough to decide, or
- the previous stage produced a `high` or `critical` severity finding, so a
  second opinion is worth paying for.

A clean Stage 1 ends the cascade. A blocking Stage 1 finding ends it immediately.
Both are asserted in tests rather than assumed:

```python
def test_stage_1_block_short_circuits_later_stages(self):
    ...
    self.assertEqual(s2.calls, 0, "stage 2 ran despite a stage 1 block")
    self.assertEqual(s3.calls, 0, "stage 3 ran despite a stage 1 block")
```

### The two rules that never bend

These live in the engine, not in the rails, because there are dozens of rails and
only one engine.

#### Fail closed

On client-facing traffic, a request that could not be *fully* judged is blocked.

This is not paranoia — it is a direct response to something found in the source
review. NeMo Guardrails' own jailbreak rail defaults to fail-**open**, documented
at `references/Guardrails-develop/docs/configure-rails/guardrail-catalog/jailbreak-protection.mdx:112`.
If a rail author can ship a fail-open default in a mature, NVIDIA-maintained
framework, then this decision cannot be delegated to rail authors.

Internal traffic fails open — but still reports. See below.

#### Fail loud

A rail that could not run contributes its payload path to `Verdict.unjudged`. It
never silently reads as clean.

The wording in the OpenGuardrails spec is worth quoting, because it is the
clearest statement of the principle anywhere in the reviewed material:

> a fail-closed enforcement point MUST treat a non-empty value as "could not
> look", which is not "found nothing".

The failure mode this prevents is real and specific. The Infosys Responsible AI
Toolkit's `moderationlayer` dispatcher wraps each check in a broad `try/except`
that logs and returns `None` — so a single timeout or a misconfigured threshold
silently drops a check, and the summary still says pass. That is precisely the
behaviour a governance layer exists to prevent, and it is why a rail raising an
exception here becomes `unjudged` rather than `clean`:

```python
def test_a_raising_rail_becomes_unjudged_not_clean(self):
    ...
    self.assertIs(out.verdict.decision, Decision.BLOCK)
    self.assertEqual(out.verdict.unjudged, ["payload.text"])
```

### What comes back

Two objects, deliberately separate:

```json
{
  "verdict":     { "...strict OpenGuardrails v0.8..." },
  "explanation": { "...AFNI attribution..." }
}
```

The verdict is the contract — strictly schema-valid, because both `verdict` and
`findings[]` are `additionalProperties: false` upstream and applications need to
rely on the shape. The explanation is what a human acts on: which repo blocked
it, how confident, which entity.

### Reading a block

```
BLOCKED after 1 cascade stage(s) in 3ms
  Blocked by:
    - LLM Guard (llm-guard-main) flagged us_ssn at payload.messages[0].content
      chars 11-22 - confidence 0.97 (deterministic) - action block
      - value withheld (fp sha256:6f1c0e)
  Also flagged (did not block): 2
```

Five things are in there on purpose:

- **which tool and which repo** — `LLM Guard (llm-guard-main)`, so a false
  positive goes to the right place and nobody has to guess whether a regex or a
  language model made the call
- **which entity** — `us_ssn`, taken from the category path
- **where** — the exact payload path and character span
- **confidence, with its kind** — `0.97 (deterministic)`. The kind matters: a
  regex at 1.0 and an LLM judge at 0.82 are not the same claim, and comparing the
  bare numbers compares nothing. The four kinds are `deterministic`,
  `classifier`, `entailment`, `judge`.
- **the value withheld** — with a fingerprint instead. The subject is the actual
  SSN. A guardrail that echoes it into a log has defeated itself. `fp` is what a
  false-positive exception keys on.

Only findings with `action: block` are listed as the cause. A verdict can carry a
dozen flags and be blocked by one; reporting all twelve as the cause would be
false.

### Reading a coverage gap

A gap is louder than a finding, because a finding means something looked:

```
BLOCKED after 1 cascade stage(s) in 1ms
  COULD NOT JUDGE 1 path(s): payload.attachment  <- not the same as 'found nothing'
```

### Honest limits

- **Stage 2 is seconds on CPU, not the 10-500 ms in the table above.** Now
  measured rather than estimated: on an AFNI Windows laptop with the CPU torch
  wheel, one request through two transformer rails took **2,954 ms warm** - models
  resident, no loading involved - and **15,568 ms cold**, before the startup
  warm-up existed. The 10-500 ms figure is a GPU or batched number.

  Stage 1 remains sub-millisecond, which is what makes the cascade worth having:
  the cheap tier carries the traffic and the expensive tier only sees the thin
  slice that survives. But budget seconds, not milliseconds, for anything that
  escalates on this hardware, and treat the boot warm-up as mandatory rather than
  an optimisation. A real per-tenant latency budget is still an open item.
- **A rail with its dependency missing reports `unjudged`, which fails closed.**
  That is correct, and it also means a fresh install with no model weights will
  block client-facing traffic until either the weights are installed or the rail
  is explicitly disabled. That is deliberate, but it will surprise you once.
- **Detector accuracy is not yet measured.** The precision and recall of every
  rail here is currently a vendor claim or an inference from the mechanism. The
  plan of record is PyRIT's `scorer_evaluation` with Krippendorff's alpha against
  a human-labelled sample of real traffic, quarterly. Until that runs, no
  accuracy figure in this platform should be quoted to a client.

### See also

- `frameworks.md` — mechanism, cost and stage for all 108 repo-tenet
  pairs, each with its evidence
- `plan.md` — the locked architecture calls
- `01-architecture.md` — where the cascade sits in the gateway


---

## The live path vs the offline loop

*Was `knowledge/dev-vs-test-loop.md`.*

Two halves, one closed loop. Source: deck slides 5 and 62.
`data/RAI_Synthesis.json` → `dev_vs_testing_split` is the authoritative tool split.

| Half | Runs | Count | Tools |
|---|---|---|---|
| **Development** (build the defence) | live, in front of and behind every AI call | 12 | LLM Guard, NeMo Guardrails, Guardrails AI, hai-guardrails, Safe Zone (TSZ), Rebuff, Infosys toolkit, Fairlearn, AIF360, SHAP, Deepchecks, DeepEval |
| **Testing** (attack the defence) | offline, pre-release and scheduled, in CI/CD | 4 | garak, FuzzyAI, JCB, LLMFuzzer |
| **Both** | both paths | 7 | PyRIT, DeepTeam, promptfoo, Giskard, Agentic Security, OpenAI Evals, OpenGuardrails |

### The four hand-offs — all automated

#### 1 · The attack corpus becomes the test suite
PyRIT, garak, DeepTeam and promptfoo each generate adversarial inputs and score
whether the target complied. Export those generated prompts **together with the
scored verdict** into a single **versioned regression corpus in git**, tagged by
tenet and by OWASP LLM Top 10 category.

> **The corpus is the asset, not the tool.** It survives any future tool swap, and it
> is the single most persuasive thing to put in front of a client's security reviewer.

#### 2 · Every finding becomes a named guardrail requirement
A jailbreak that got through is not a report line — it is a ticket against a specific
NeMo rail, a threshold change in LLM Guard, or a new blocklist entry. **It is closed
only when the same input is replayed and blocked.**

#### 3 · CI gates the deploy — three tiers
Triggered by any change to prompts, rails, thresholds or model versions.

| Tier | When | Budget | Contents | Gate |
|---|---|---|---|---|
| **Fast** | every pull request | < 5 min | DeepEval + promptfoo deterministic assertions, PyRIT regex output scorers, replay of the frozen corpus of previously-fixed attacks | **100% of the frozen corpus must be blocked or the build fails** — regressions block the merge outright |
| **Medium** | merge to main | ~30–60 min | promptfoo redteam over the OWASP-mapped plugin set + a garak probe subset | gated on a **maximum attack-success rate**, not on zero findings — zero is not achievable |
| **Slow** | nightly / pre-release | unbounded | full PyRIT Crescendo, TAP and PAIR multi-turn attacks; DeepTeam agentic vulnerability probes; Deepchecks drift and data-quality suites | findings land as tickets |

#### 4 · Test the guardrails, not just the model — the step most often skipped
- Point **garak's shields up / shields down probes at AFNI's own gateway** to confirm
  the rails actually fire. Add that check to the release gate.
- Run **PyRIT's `scorer_evaluation` with Krippendorff's alpha** against a
  human-labelled sample of production traffic each quarter, so AFNI can state a
  **measured precision and recall per detector** instead of a vendor claim.

### Why the loop closes
Every result from every tier is written in the OpenGuardrails Verdict schema. That is
what makes the whole thing showable: *here is the attack corpus, here is the gate,
here is the measured detector accuracy, here is the trend.*

Red-team and evaluation findings are the pass/fail gate in CI/CD — a guardrail change
only ships once it survives the attack suite. **Testing sharpens the development
layer, not the other way around.**
