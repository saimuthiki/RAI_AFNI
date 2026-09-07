# The console, tab by tab

Every screen in the operator console at `http://127.0.0.1:8000/`, in the order
the left-hand menu shows them: what it is for, how to drive it, one worked
example, what you should see, and what is worth measuring.

Every number below was read from a live gateway on the machine that wrote this
file, not copied from a design document. Where a number depends on your host —
which model weights are installed, which keys are set — that is said in the row
rather than hidden.

> **One rule before anything else.** Read the DECISION, not the HTTP status
> code. Once a request body parses, every outcome is `HTTP 200` — including a
> cascade failure, which comes back as a BLOCK with every payload path listed in
> `unjudged`. A `500` is ambiguous, and an ambiguous guardrail failure gets read
> as a pass by the next `try/except` up the stack.

---

## Contents

| Tab | Answers | Writes anything? |
|---|---|---|
| [Live check](#live-check) | what happens to one prompt, stage by stage | audit row |
| [How it works](#how-it-works) | where each rail sits in the request path | no |
| [Tenets](#tenets) | which capabilities are real, which are gaps | no |
| [Rails](#rails) | every detector and the source line behind it | no |
| [Topics](#topics) | which subjects this deployment refuses | policy file |
| [Sensitivity](#sensitivity) | the threshold in force, per detection | policy file |
| [Media](#media) | image and video moderation | audit row |
| [Corpus](#corpus) | how many known-harmful prompts get through | audit rows |
| [Before and after](#before-and-after) | the guardrail's value as one number | audit rows |
| [Frameworks](#frameworks) | which of the 23 repositories contribute | no |
| [Governance](#governance) | the compliance register, generated | no |

The two write-capable settings screens (Topics, Sensitivity) use `PUT`
endpoints with **no authentication**. They are localhost operator tools. Do not
expose this gateway on `0.0.0.0` without putting your own auth in front.

---

## Two things always on screen

**The status line.** `Gateway live` or `Gateway live · degraded`. Degraded means
one or more mounted rails cannot judge on this host — they stay mounted, run,
and return "could not judge", which **fails closed without protecting
anything**. Expand *What exactly is missing* to see which. This is the most
important line in the product: a rail that cannot look is not a rail that found
nothing.

**The judge chain.** e.g. `judge provider: local[0] → gemini[0] → openai[0]`.
Read it left to right — that is the order Stage-3 judge calls are tried, and the
first link is where the **flagged content** goes. `local[0]` first means it stays
on your network. `local[nokey]` instead of `local[0]` means no credential is
attached to that link; if your endpoint requires one, every judge call will 401.

---

## Live check

**What it is for.** Watch one prompt resolve, one cascade stage at a time,
with the reason for every finding.

**How to use it.** Type or paste a prompt. Choose *input* (the user is asking)
or *output* (the model is answering) — the direction matters, because 1 of the
33 rails is input-only and 8 are output-only. Press the button and watch the
stages arrive.

### Worked example

Paste this:

```
My SSN is 123-45-6789 and my card is 4111111111111111.
Email jane.doe@example.com, phone 555-0100.
```

**What you should see:**

| | |
|---|---|
| Decision | `block` |
| Stages run | 2, or 3 if no Stage-2 rail blocks |
| Findings | SSN, card and email, each `redact`, each from more than one detector |
| Redactions | `[REDACTED-US-SSN]`, `[REDACTED-CREDIT-CARD]`, `[REDACTED-EMAIL]` |
| The values themselves | **absent** — each finding carries `fp`, a fingerprint |

**What to observe.** The same SSN is reported by `privacy.region_ids` (a regex
plus a checksum), by `privacy.reversible_anonymiser` and by
`privacy.presidio_ner` (a model). That is not a bug — it is three independent
detectors agreeing, and the `fp` fingerprint is identical across all three,
which is how you know they are talking about the same span.

**Why `fp` and not the value.** A guardrail that echoes the SSN it caught into
your logs has defeated itself. `fp` is what a false-positive exception keys on.
Revealing the real value is `AFNI_REVEAL_SUBJECT`, a server-side environment
flag, deliberately not a request parameter.

### Four outcomes, not two

| Decision | Means | What to do |
|---|---|---|
| `allow` | every eligible rail ran and found nothing | nothing |
| `flag` | found something, not enough to stop | review, tune the threshold |
| `block` | a rail returned a blocking finding | this is the guardrail working |
| `block` with non-empty `unjudged` | **something could not look** | fix the host, do not tune |

The last row is the one people misread. `unjudged` is not "clean". It always
blocks, for every caller, with no request field and no console switch that
relaxes it.

---

## How it works

**What it is for.** The request path, drawn: which rails run at which stage, in
which direction, and where the cascade can stop early.

**How to use it.** Read it once before the demo. There is nothing to click.

**What to observe.** The cascade stages, and what each costs:

| Stage | What runs | Cost | Runs on |
|---|---|---|---|
| 1 | 23 rails — regex, wordlists, checksums, pure standard library | free, sub-millisecond | every request |
| 2 | 7 rails — local models (toxicity, injection, PII NER, bias, topics) | CPU, tens of ms | only if Stage 1 asked |
| 3 | 3 rails — LLM judge, paid or local | a model call | only on escalation |
| offline | 19 capabilities — red-team, SHAP, benchmarks | minutes | never in the request path |

**The single most useful fact on this screen:** a blocking finding at any stage
**short-circuits** the rest. So a prompt blocked at Stage 2 never reaches the
Stage-3 judge. If you are trying to demonstrate the judge and keep seeing
`stages_run: 2`, that is why — see [Sensitivity](#sensitivity).

---

## Tenets

**What it is for.** Coverage, counted honestly, across the seven tenets.

**How to use it.** Read the counts per tenet, then open a tenet to see each
capability and its status.

**What you should see** (totals from a live gateway; your `dependency-missing`
count depends on what is installed):

| Status | Count | Means |
|---|---|---|
| `implemented` | 27 | built, mounted, runs here |
| `dependency-missing` | 7 | built, but a package is absent on this host |
| `cloud-not-configured` | 8 | built, needs a key you have not set |
| `offline-only` | 19 | real, but never in the request path |
| `gap` | 4 | **not built** |

Privacy, as an example: 6 implemented, 1 cloud-not-configured, 1 offline-only,
1 gap.

**What to observe.** `gap` is the honest column. A platform that reported 100%
coverage would be counting things it cannot do. Four gaps, named, is the number
to quote — and the three non-`implemented` statuses are three different problems
with three different fixes (install a package, set a key, write the code).

---

## Rails

**What it is for.** Every one of the 33 mounted detectors, with the upstream
file and line it came from.

**How to use it.** Scan it, or use it to answer "where did this finding come
from" after a Live check.

**What you should see:** 33 rails — 23 rails at Stage 1, 7 at Stage 2, 3 at
Stage 3. By direction, 24 rails apply to both sides, 8 are output-only, 1 is
input-only.

Each row carries an `evidence` string, for example:

```
llm-guard-main/llm_guard/input_scanners/toxicity.py:13-26
model unitary/unbiased-toxic-roberta revision 36295dd8...
```

**What to observe.** The `mechanism` column is the one that matters for cost:
`Keyword/Regex` is free, `Classifier` is a local model, `LLM-judge` is a model
call. A rail marked *cannot judge* here is a rail that will contribute
`unjudged` to every request it runs on — which blocks.

---

## Topics

**What it is for.** Which subjects this deployment refuses to discuss.

**How to use it.** Six topics are **always banned** and cannot be switched off
from the console — they are compiled in, so deleting the policy file cannot
disable them. Twenty-four more are optional: enable one to make it *flag*, then
promote it to *block*.

**What you should see:** `always: 6`, `optional_available: 24`,
`blocking_patterns: 46`, `semantic_classes: 6`.

**How each ban is actually enforced — two mechanisms, not one:**

| | Stage | Catches |
|---|---|---|
| 46 blocking patterns | 1 | the exact phrasings on the list ("pipe bomb", "how to make meth") |
| 6 semantic classes | 2 | phrasings nobody listed, by classifier |

That second row matters more than it looks. `weapons_manufacture` lists
"pipe bomb" and "improvised explosive". It does **not** list "suicide vest" —
and a phrase list only ever catches the phrasings somebody thought of. The
semantic classifier is what covers the rest.

### Worked example

Enable *Gambling advice*, leave it on **flag**, save, restart. Then run through
Live check:

```
Which roulette strategy has the best expected return?
```

Expect `flag`, not `block`, attributed to `explainability.topic_scope`.
Now promote the same topic to **blocking** and re-run: `block`, and
`semantic_classes` in the save response goes from 6 to 7.

**Two things to know.**

- **Topics arm on RESTART.** Thresholds arm on the next request; topics do not.
  If your change appears to do nothing, restart before debugging.
- A topic you set to **flag** gets no semantic class. That is deliberate: the
  classifier blocks on a match, so arming it for a flag-only topic would promote
  that topic to blocking behind your back.

---

## Sensitivity

**What it is for.** Every tunable threshold and the number actually in force.

**How to use it.** 24 thresholds, each showing its **shipped** value (cited to
the repository it was ported from) and its **effective** value. Change one, or
apply a preset.

| Preset | Does | Touches |
|---|---|---|
| `balanced` | clears every override, back to shipped | 0 |
| `strict` | every detection threshold × 0.75, floor 0.25 | 21 |
| `maximum` | every detection threshold to 0.10 | 21 |

`maximum` is a red-team and demonstration setting, not a production one: at 0.10
a classifier's noise floor becomes a finding.

Direction is `lower-is-stricter` for every detection threshold.

### Worked example — forcing a Stage-3 judge call

This is the most common real need. A PII prompt often gets blocked at Stage 2 by
the prompt-injection classifier, which short-circuits before the judge runs.

1. Note the shipped value: `security.prompt_injection.classifier` = **0.9**.
2. Set it to **0.99**:

```bash
curl -s -X PUT http://127.0.0.1:8000/v1/thresholds \
  -H 'content-type: application/json' \
  -d '{"thresholds":{"security.prompt_injection.classifier":0.99}}'
```

3. Re-send your PII prompt. Now `stages_run: 3`, and the judge rails appear in
   the findings.
4. **Put it back:** `{"preset": "balanced"}`.

**Two traps.**

- `thresholds` **replaces** the whole override map — it does not merge. What you
  send is what is in force, because a merge would make "remove this override"
  impossible to express.
- 0.99 on the injection classifier is a hole in that rail. It is for the test,
  not for the demo.

**What to observe.** A threshold change is the cheapest way to move the
false-positive / false-negative trade-off, and the only honest way to measure it
is to re-run the [Corpus](#corpus) at the same seed before and after.

---

## Media

**What it is for.** Moderating images, and sampled frames of video.

**How to use it.** Upload an image. Video is offline-cost — it samples frames
rather than watching the whole file.

**What you should see:** detector `nudenet-320n`, package `nudenet`, running as
**Stage 2 — a local model, no network**. Labels are graded, not binary:

| Group | Labels | Action |
|---|---|---|
| explicit | `FEMALE_GENITALIA_EXPOSED`, `MALE_GENITALIA_EXPOSED`, `ANUS_EXPOSED`, `BUTTOCKS_EXPOSED`, `FEMALE_BREAST_EXPOSED` | block |
| suggestive | the `_COVERED` variants, `MALE_BREAST_EXPOSED` | flag |
| face | `face` | flag |
| ignored | `BELLY_*`, `FEET_*`, `ARMPITS_*` | nothing |

**What to observe.** An oversized upload is reported `unjudged` — "something
that could not be looked at" — rather than as an error, which is the same
fail-closed rule as everywhere else. The cap is `AFNI_MEDIA_MAX_BYTES`,
defaulting to 16 MB per decoded upload.

**Not yet measured:** accuracy against a labelled set. The labels above are the
detector's own; nobody here has scored them against ground truth.

---

## Corpus

**What it is for.** The regression asset. 11,369 adversarial prompts, tagged by
tenet and by OWASP LLM Top 10, with a recorded baseline. This is what turns "the
guardrail works" into a number you can re-measure after every change.

**How to use it.** Pick a sample size, pick how far up the cascade to run, pick
stratified or not, then run.

**What you should see:**

| | |
|---|---|
| Records | 11,369 |
| With a baseline | 280 — only these can drift |
| Run cap | `AFNI_CORPUS_MAX_SAMPLE` (500 shipped) — a bigger pass belongs offline |
| Output-direction | 519 affirmative completions — what a jailbroken model would have said |
| Stage 3 | **off** unless `AFNI_CORPUS_ALLOW_CLOUD=true` |

Composition, which you need in order to read any rate:

| Tenet | Records |
|---|---|
| (unmapped) | 5,170 |
| Profanity / Content Safety | 4,815 |
| Security | 452 |
| Hallucination / Reliability | 321 |
| Privacy | 264 |
| Explainability & Transparency | 246 |
| Fairness & Bias | 101 |

**Always choose *stratified*** for a headline number. An unstratified draw is
42% content safety, so it mostly measures one tenet.

### Worked example

98 records, 14 per tenet, seed 0, ceiling Stage 1 + 2.

**On this corpus an `allow` is a MISS, not a pass.** Every record is a harmful
prompt. So the number to read is the block rate, and a low one is a real gap at
that ceiling — read the allowed rows and check which rails were even eligible.

**What to observe.**

- **Deterministic seed.** Seed 0 means two runs are directly comparable. Change
  a threshold, re-run the same seed, and the difference is the threshold.
- **Drift is not automatically a regression.** A changed verdict against the
  baseline means "read this and decide". Only then re-record with
  `corpus/baseline.py --write`. A tool that updates its own expectations cannot
  detect anything.
- **Errors ≠ blocks.** The `Errors` counter is the cascade raising — a broken
  check, not a caught prompt.
- **`Stage 3 on this host: off` is the right setting.** These are 11,369
  genuinely harmful prompts. Turning Stage 3 on would post them to a third-party
  vendor under your account.

**Cite the record `id`, never the text.** See `corpus/WARNING.md`. Prompts are
shown truncated to 120 characters for the same reason.

---

## Before and after

**What it is for.** The one number for a demo: what the guardrail buys.

**How to use it.** Pick records per rung, pick the top rung, run. It runs the
**same records** at every rung — no guardrail, then Stage 1, then Stage 1 + 2.

**What to observe.** The same-records rule is the whole point. Re-drawing the
sample per rung would make the difference between two rungs partly a sampling
artefact, and on a corpus that is 42% content safety a re-draw can move a rate
by several points on its own.

There is also an optional end-to-end attack-success estimate, computed with **no
model** by composing the input guardrail against the prompts and the output
guardrail against the corpus's own 519 affirmative completions. It costs a
second ladder. Use it when someone asks "what would have got through".

---

## Frameworks

**What it is for.** All 23 repositories that were read, and what each one
contributes.

**What you should see:** four adoption verdicts.

| Verdict | Repos |
|---|---|
| Adopt now | 10 |
| Combine with another | 5 |
| Bench for later | 6 |
| Skip | 2 |

**What to observe.** A verdict is about a repository, not a date. There is no
phased rollout anywhere in this platform. The screen also lists **unlinkable**
capabilities — 12 of them — which are capabilities no mounted rail implements,
each tagged with why (`offline-only`, `cloud-not-configured`). That list is the
honest edge of the coverage claim.

---

## Governance

**What it is for.** The compliance register, generated from the live platform
rather than maintained by hand.

**What you should see:** 7 tenets, 33 rails mounted, 24 thresholds listed, and a
`problems` array.

**What to observe.** The `problems` array is the feature. With
`AFNI_GOVERNANCE_DOMAIN` unset it says so, in as many words, rather than
inventing addresses:

> a plausible-looking address that goes nowhere is worse in a compliance
> artefact than a visibly unfinished one

**Two settings, and one is a trap.**

| Variable | Does |
|---|---|
| `AFNI_GOVERNANCE_CONTACT` | one address, used verbatim for all seven roles |
| `AFNI_GOVERNANCE_DOMAIN` | generates `rai-privacy@`, `rai-security@` and five more |

Set **CONTACT** unless those seven aliases actually exist. `DOMAIN` with no
aliases behind it puts seven bouncing addresses into a compliance document.
`/v1/governance` reports the one-shared-mailbox weakness in `problems` either
way, which is the point: the weakness is visible instead of hidden.

**No names.** The framework assigns tenet owners by role, not by person.

---

## When something looks wrong

| Symptom | Cause | Fix |
|---|---|---|
| `judge provider: local[nokey]` | no credential on the local link | set `AFNI_TARGET_API_KEY` (the local judge inherits it) |
| `local` missing from the chain | the probe got 401/403, or `LOCAL_BASE_URL` is set without `LOCAL_API_KEYS` | see `docs/setup.md` |
| every escalated request blocks | a Stage-3 rail reports `unjudged` | check the judge key shape; startup warns about a wrong-kind key |
| `stages_run` never reaches 3 | a Stage-2 rail is blocking first | raise that rail's threshold for the test |
| a topic change did nothing | topics arm on **restart** | restart |
| a threshold change did nothing | check `effective`, not `shipped` | `GET /v1/thresholds` |
| `degraded` banner | a mounted rail cannot judge on this host | expand *What exactly is missing* |
| everything blocks on a fresh install | Stage-2 weights absent → `unjudged` → fail closed | `python fetch_models.py` |

---

## Related

- `docs/setup.md` — installation, every environment variable, the judge chain
- `docs/request-flow.md` — the cascade in detail, rail by rail
- `docs/architecture.md` — why the platform is shaped this way
- `docs/corpus.md` — the corpus, its provenance and its handling rules
- `docs/ui-walkthrough.html` — the same tour, in plain English, for a
  non-technical reader
