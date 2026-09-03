# Model drop-in manifest

Everything the platform needs but does not ship — what to fetch, from where, and
exactly where to put it.

**Step-by-step setup, in three levels:**
[`rai_platform/docs/01-setup.md`](../docs/01-setup.md). Start there if you are
provisioning a machine.

**One command downloads all five models:**

```bash
python rai_platform/scripts/fetch_models.py            # --dry-run to preview
python rai_platform/scripts/fetch_models.py --only security   # or one at a time
```

**Generate this list live at any time, from the code rather than from this file:**

```bash
python3 rai_platform/cli.py preflight
```

That reads each model id and pinned revision off the rail that loads it, so it
cannot drift from what the platform actually asks for. Use it to check your work
after copying anything in. This document is the same information plus the
fetch commands.

---

## How the drop-in works

Every Stage-2 rail loads by HuggingFace repo id with a pinned revision. That is
the right default — id plus revision is a reproducible, auditable reference. It
is also useless where `huggingface.co` is blocked.

So `afni_rai/models.py` adds a fallback: **a plain folder in this directory
wins over the hub.**

```
rai_platform/models/
├── MANIFEST.md                                        ← this file
├── protectai__deberta-v3-base-prompt-injection-v2/    ← drop folders here
│   ├── config.json
│   ├── model.safetensors
│   ├── tokenizer.json
│   ├── tokenizer_config.json
│   └── special_tokens_map.json
├── unitary__unbiased-toxic-roberta/
├── MoritzLaurer__roberta-base-zeroshot-v2.0-c/
├── MoritzLaurer__deberta-v3-base-zeroshot-v2.0/
└── valurank__distilroberta-bias/
```

Folder naming: `org/name` → **`org__name`** (double underscore, because model
names contain single underscores of their own). The bare model name without the
org also works, if that is how your download landed.

`AFNI_MODEL_DIR` overrides this directory if you would rather keep several
gigabytes of weights outside the repo — recommended, and the reason the override
exists.

**A folder is only accepted if it contains `config.json` *and* one weights file**
(`model.safetensors`, `pytorch_model.bin`, or `model.onnx`). A half-copied folder
is rejected rather than half-loaded, and `preflight` names the file that is
short. This matters because a partial folder that loaded would throw from inside
a live request instead of degrading to an honest `unjudged`.

---

## 1 · The five HuggingFace models

Total ≈ **2.8 GB**. Ordered by what you get for the download.

### 1.1 `protectai/deberta-v3-base-prompt-injection-v2` — do this one first

| | |
|---|---|
| **Rail** | `security.injection.deberta_v3_v2` |
| **Tenet** | Security |
| **Folder** | `rai_platform/models/protectai__deberta-v3-base-prompt-injection-v2/` |
| **Size** | ~740 MB |
| **Revision** | `90c9989b1a342275dd0d1a95aad283c04e075671` |

Why first: **no Stage-1 rail blocks a prompt injection.** That is deliberate —
PyRIT documents a high false-positive rate for the regex patterns, so a Stage-1
hit flags and escalates rather than refusing. This model is what the escalation
escalates *to*. Without it, a textbook injection produces four HIGH findings and
is **allowed** on internal traffic.

> **Now pinned.** This was the one model with no revision, which on a security
> control is a supply-chain hole — upstream could replace the weights and the
> gateway would adopt them on the next cold start with no diff anywhere. The sha
> above is the commit AFNI actually downloaded and verified, reported by
> `fetch_models.py`, not read off the model card: a card can be edited, a commit
> cannot.

### 1.2 `unitary/unbiased-toxic-roberta`

| | |
|---|---|
| **Rail** | `content_safety.toxicity_model` |
| **Tenet** | Profanity / Content Safety |
| **Folder** | `rai_platform/models/unitary__unbiased-toxic-roberta/` |
| **Size** | ~500 MB |
| **Revision** | `36295dd80b422dc49f40052021430dae76241adc` |

7-head multilabel toxicity. Stage 1 catches slurs from a lexicon; this catches
toxicity that contains no banned word — which is most of it.

### 1.3 `MoritzLaurer/deberta-v3-base-zeroshot-v2.0`

| | |
|---|---|
| **Rail** | `groundedness-nli` |
| **Tenet** | Hallucination / Reliability |
| **Folder** | `rai_platform/models/MoritzLaurer__deberta-v3-base-zeroshot-v2.0/` |
| **Size** | ~740 MB |
| **Revision** | `8e7e5af5983a0ddb1a5b45a38b129ab69e2258e8` |

Entailment of an answer against its retrieved source — the only grounding check
here that is not a string comparison. Needs a retrieved context per request to
do anything; with no source it reports `unjudged` rather than scoring an answer
against itself.

### 1.4 `valurank/distilroberta-bias`

| | |
|---|---|
| **Rail** | `llm_guard.bias` |
| **Tenet** | Fairness & Bias |
| **Folder** | `rai_platform/models/valurank__distilroberta-bias/` |
| **Size** | ~330 MB |
| **Revision** | `c1e4a2773522c3acc929a7b2c9af2b7e4137b96d` |

The only runtime bias signal beyond a regex. Fairness reads **0 of 9
implemented** without it. Note this does not make Fairness "done" — seven of
those nine capabilities are batch metrics (Fairlearn, AIF360) that cannot run
per-request at all.

### 1.5 `MoritzLaurer/roberta-base-zeroshot-v2.0-c`

| | |
|---|---|
| **Rail** | `content_safety.zeroshot_topics` |
| **Tenet** | Profanity / Content Safety |
| **Folder** | `rai_platform/models/MoritzLaurer__roberta-base-zeroshot-v2.0-c/` |
| **Size** | ~500 MB |
| **Revision** | `d825e740e0c59881cf0b0b1481ccf726b6d65341` |

Zero-shot topic scoping. **Also needs the topic list** — see §5. The weights
alone do nothing, because the rail returns clean when no topics are configured.

---

## How to fetch them

On a machine that *can* reach `huggingface.co`:

```bash
pip install huggingface_hub

huggingface-cli download protectai/deberta-v3-base-prompt-injection-v2 \
  --local-dir ./protectai__deberta-v3-base-prompt-injection-v2

huggingface-cli download unitary/unbiased-toxic-roberta \
  --revision 36295dd80b422dc49f40052021430dae76241adc \
  --local-dir ./unitary__unbiased-toxic-roberta

huggingface-cli download MoritzLaurer/deberta-v3-base-zeroshot-v2.0 \
  --revision 8e7e5af5983a0ddb1a5b45a38b129ab69e2258e8 \
  --local-dir ./MoritzLaurer__deberta-v3-base-zeroshot-v2.0

huggingface-cli download valurank/distilroberta-bias \
  --revision c1e4a2773522c3acc929a7b2c9af2b7e4137b96d \
  --local-dir ./valurank__distilroberta-bias

huggingface-cli download MoritzLaurer/roberta-base-zeroshot-v2.0-c \
  --revision d825e740e0c59881cf0b0b1481ccf726b6d65341 \
  --local-dir ./MoritzLaurer__roberta-base-zeroshot-v2.0-c
```

`--local-dir` gives a **plain folder**, which is what this drop-in wants. Copy
the five folders into `rai_platform/models/` (or wherever `AFNI_MODEL_DIR`
points) and run `preflight`.

Downloading through the browser works too — the "Files and versions" tab on each
model page. You need `config.json`, the weights file, and the tokenizer files;
skip anything ending `.msgpack`, `.h5` or `.onnx` unless you want the ONNX
runtime path, and skip the `.md` files.

**Do not** copy a `~/.cache/huggingface/hub` directory in and expect it to work
as a drop-in folder — that layout is `models--org--name/snapshots/<sha>/` with
blobs behind symlinks, and the symlinks break on copy. If you would rather use
the real cache, copy the whole cache directory and set `HF_HOME` to it instead,
leaving `rai_platform/models/` empty; the rails fall back to the hub id and the
cache serves it with `local_files_only=True`.

---

## 2 · Python packages — all from PyPI, none blocked

```bash
python3 -m pip install transformers torch --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install llm-guard presidio-analyzer
python3 -m pip install fastapi uvicorn httpx        # the gateway
```

| Package | Needed by | Size |
|---|---|---|
| `transformers` | all four HF-backed rails | ~12 MB |
| `torch` | all four HF-backed rails | ~900 MB (CPU wheel; the CUDA one is ~2.5 GB) |
| `llm-guard` | `content_safety.toxicity_model`, `.zeroshot_topics` | ~1 MB |
| `presidio-analyzer` | `privacy.presidio_ner` | ~1 MB |
| `fastapi`, `uvicorn`, `httpx` | the gateway and judge chain | ~7 MB |

Use the CPU wheel index unless you have a GPU. It is a third of the size and
these are all small classifiers.

## 3 · spaCy pipeline — **not** from HuggingFace

```bash
python3 -m spacy download en_core_web_lg
```

~590 MB, needed by `privacy.presidio_ner`. It comes from
`github.com/explosion/spacy-models/releases`, which **is reachable from here** —
I verified it and installed this successfully, so Presidio NER already works in
this container.

Use `spacy download`, **never a pinned wheel URL**. The model version must match
the installed spaCy; a `3.7.1` model against spaCy 3.8 installs without error
and then fails to load. I hit exactly that.

## 4 · Credentials — `.env` only, never a committed file

| Variable | For | Notes |
|---|---|---|
| `OPENAI_API_KEYS` | Stage-3 judge chain | Comma-separated, tried in order |
| `GOOGLE_API_KEYS` | Stage-3 judge chain | Comma-separated, tried in order |
| `LOCAL_BASE_URL` | Stage-3 judge chain | **Prefer this.** The only judge option that keeps flagged content on your own network — a judge call sends the flagged text to whoever serves it |
| `AZURE_CONTENT_SAFETY_KEY` | `security.prompt_shields` | Optional; Stage 1 + 2 cover injection without it |

`.env` is gitignored. A key that reaches a commit is public and permanent, and
rotation is the only remedy.

## 5 · The one item that is not a download

**The allowed / banned topic list.** This is the `Ban-topics / on-topic scope`
gap. `TopicScopeRail` is written and unit-tested but ships with an empty lexicon,
so it is **not mounted** — and `content_safety.zeroshot_topics` returns clean
with no topics configured, weights or no weights.

Every reviewed tool treats on-topic as deployment policy, not a model artefact
(NeMo's `config.yml`, DeepTeam's `TopicalGuard(allowed_topics=[...])`). So no
download closes this. What it needs is, per AFNI application: **the topics that
application is allowed to discuss, and the ones it must refuse.** Give me that
for one application and I will wire it and mount the rail.

## 6 · Gaps no download closes

| Gap | Tenet | What it would actually take |
|---|---|---|
| **NSFW image/video detection** | Content Safety | Infosys ships `nsfw.299x299.h5` and `nsfw_mobilenet2.224x224.h5` (`responsible-ai-toxicity/.../nsfw_detector/predict.py:132-133`) plus NudeNet. Both are Keras/TF, which would pull TensorFlow in alongside torch. Needs a decision on whether AFNI handles media at all before it is worth the dependency. |
| **Multi-format / DICOM PII** | Privacy | The Infosys multi-format and DICOM modules. Conditional on the business needing them. |
| **Dedicated hallucination models** | Hallucination | No specific model is committed to; `groundedness-nli` covers the entailment case. Genuinely open. |
| **Fairness at runtime** | Fairness & Bias | Nothing. 7 of 9 capabilities measure a *distribution of decisions* — Fairlearn and AIF360 as scheduled batch jobs over decision logs. Not a download and not a runtime rail. |

---

## Checking your work

```bash
python3 rai_platform/cli.py preflight        # every item, present or missing
python3 rai_platform/cli.py coverage         # what that changed
python3 rai_platform/cli.py rails            # every rail by stage
curl -s localhost:8000/healthz | python3 -m json.tool   # live, per rail
```

`preflight` exits with the number of outstanding items, so a provisioning script
can gate on it.

## What none of this blocks

**Stage 1 — 22 rails across all seven tenets — is pure Python standard library
and needs none of the above.** Every item here is a rail that reports `unjudged`
until it arrives, which fails closed on client-facing traffic. That is honest
behaviour, and it is not the same as protection.
