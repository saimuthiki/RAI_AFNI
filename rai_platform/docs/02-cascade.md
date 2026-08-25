# The Cascade

How the gateway decides, and why it costs what it costs.

## The idea in one paragraph

Run every free, deterministic check on 100% of traffic. If one of them fires with
confidence, stop there — the request never reaches a paid call. Escalate only the
thin slice that survives, first to local models, then to a paid API or an LLM
judge. Anything too slow or too expensive to run per-request runs offline in CI
instead, against a versioned attack corpus.

That is the whole cost argument, and it is enforced in
`afni_rai/cascade/engine.py` rather than left to individual rails.

## The four stages

| Stage | What runs | Latency | Cost | Runs on |
|---|---|---|---|---|
| **Stage 1** | regex, keyword lists, checksums, unicode normalisation, schema checks | sub-millisecond | free | every request |
| **Stage 2** | a locally-run classifier or NLI model; or a cloud second opinion | ~10–500 ms | free (local) or per-call | borderline input only |
| **Stage 3** | a paid API or an LLM-as-judge | ~1–5 s | per-call, the dearest | last resort |
| **Offline** | red-team attacks, fairness metrics, drift, SHAP | unbounded | CI budget | never in the request path |

Stage membership is **data, not a code decision**. It comes from
`analysis/data/tenet_methodology_data.json`, where each of the 108 repo-tenet
rows carries a mechanism, a cost, a latency class and a derived stage — each one
backed by a `file:line`, model id or dependency actually read from the vendored
source. A rail declares its stage; it does not get to invent one.

## Escalation is conditional, not layered-always

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

## The two rules that never bend

These live in the engine, not in the rails, because there are dozens of rails and
only one engine.

### Fail closed

On client-facing traffic, a request that could not be *fully* judged is blocked.

This is not paranoia — it is a direct response to something found in the source
review. NeMo Guardrails' own jailbreak rail defaults to fail-**open**, documented
at `references/Guardrails-develop/docs/configure-rails/guardrail-catalog/jailbreak-protection.mdx:112`.
If a rail author can ship a fail-open default in a mature, NVIDIA-maintained
framework, then this decision cannot be delegated to rail authors.

Internal traffic fails open — but still reports. See below.

### Fail loud

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

## What comes back

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

## Reading a block

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

## Reading a coverage gap

A gap is louder than a finding, because a finding means something looked:

```
BLOCKED after 1 cascade stage(s) in 1ms
  COULD NOT JUDGE 1 path(s): payload.attachment  <- not the same as 'found nothing'
```

## Honest limits

- **Latency classes are estimated from mechanism, not benchmarked.** A regex is
  sub-millisecond and an LLM judge is seconds; those are safe. The middle of the
  range depends on hardware, batch size and model quantisation, and nothing here
  has been measured on AFNI's infrastructure. Setting a real latency budget is an
  open item.
- **A rail with its dependency missing reports `unjudged`, which fails closed.**
  That is correct, and it also means a fresh install with no model weights will
  block client-facing traffic until either the weights are installed or the rail
  is explicitly disabled. That is deliberate, but it will surprise you once.
- **Detector accuracy is not yet measured.** The precision and recall of every
  rail here is currently a vendor claim or an inference from the mechanism. The
  plan of record is PyRIT's `scorer_evaluation` with Krippendorff's alpha against
  a human-labelled sample of real traffic, quarterly. Until that runs, no
  accuracy figure in this platform should be quoted to a client.

## See also

- `knowledge/methodology.md` — mechanism, cost and stage for all 108 repo-tenet
  pairs, each with its evidence
- `knowledge/decisions.md` — the locked architecture calls
- `01-architecture.md` — where the cascade sits in the gateway
