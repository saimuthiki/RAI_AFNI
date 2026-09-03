"""Regenerate docs/request-flow.md from the live rail registry."""
import importlib, pathlib, sys

# __file__-relative, not cwd-relative: this script is run from the repo root, from
# rai_platform/, and from CI, and a cwd-relative path silently wrote the doc into
# whichever directory happened to be current.
_HERE = pathlib.Path(__file__).resolve().parent      # rai_platform/scripts
_PLATFORM = _HERE.parent                             # rai_platform
_ROOT = _PLATFORM.parent                             # repo root
OUT = _ROOT / "docs" / "request-flow.md"
sys.path.insert(0, str(_PLATFORM))
from afni_rai.cascade.rail import Stage

TEN = {'privacy':'Privacy','security':'Security','content_safety':'Content Safety',
       'fairness':'Fairness','hallucination':'Hallucination',
       'explainability':'Explainability','accountability':'Accountability'}

rows = []
for pkg, disp in TEN.items():
    m = importlib.import_module(f'afni_rai.tenets.{pkg}')
    for r in getattr(m, 'RAILS', []) or []:
        d = getattr(r, 'direction', None)
        rows.append(dict(t=disp, n=r.name,
                         s=(0 if r.stage is Stage.OFFLINE else int(r.stage)),
                         d=(d.value if d else 'both')))

both = [r for r in rows if r['d'] == 'both']
inp  = [r for r in rows if r['d'] == 'input']
out  = [r for r in rows if r['d'] == 'output']
N_IN, N_OUT = len(both) + len(inp), len(both) + len(out)

def table(sub):
    lines = ["| Rail | Tenet | Stage |", "|---|---|:---:|"]
    for r in sorted(sub, key=lambda x: (x['s'], x['t'], x['n'])):
        lines.append(f"| `{r['n']}` | {r['t']} | {r['s']} |")
    return "\n".join(lines)

def stage_table():
    lines = ["| Stage | Mounted | Run on the prompt | Run on the response |",
             "|---|:---:|:---:|:---:|"]
    for s, label in ((1, "1 — free, deterministic"), (2, "2 — local model"), (3, "3 — paid judge")):
        t = sum(1 for r in rows if r['s'] == s)
        i = sum(1 for r in rows if r['s'] == s and r['d'] in ('both', 'input'))
        o = sum(1 for r in rows if r['s'] == s and r['d'] in ('both', 'output'))
        lines.append(f"| {label} | {t} | {i} | {o} |")
    lines.append(f"| **All stages** | **{len(rows)}** | **{N_IN}** | **{N_OUT}** |")
    return "\n".join(lines)

WHY_ONE_SIDED = """
| Rail | Runs on | Why not both |
|---|---|---|
| `attack-corpus-repeat` | prompt only | The corpus holds confirmed attack **prompts**. Matching a model response against it compares the wrong text to the wrong corpus. |
| `security.insecure_output` | response only | Catches a **model** emitting a `<script>` tag, a `DROP TABLE` or a path traversal. A user *asking about* SQL injection is a support question, not an attack — running this on a prompt is a false-positive generator. |
| `refusal-phrases` | response only | A refusal is something a **model** does. A user declining to answer is not a guardrail concern. |
| `package-hallucination` | response only | An invented import is something a **model** emits. A user naming a real package they want is not a finding. |
| `groundedness-nli` | response only | Groundedness compares an **answer** to its retrieved source. A prompt has no answer to ground. |
| `structured-output-wellformed` | response only | Validates the shape of the **model's** output against the caller's declared format. A user's prose need not be well-formed JSON. |
| `structured-output-schema` | response only | The schema is the model's contract with the caller, not the user's input. |
| `afni-format-validators` | response only | Format validators check the **model's** output against the caller's declared format. Input carries no such contract. |
| `afni-schema-explain` | response only | Explains which field of the **model's** structured output failed validation. |
""".strip()

doc = f"""# Request Flow — One Request, Start to Finish

**Generated from the live rail registry** by `scripts/build_request_flow.py`. Do not
hand-edit the counts or the tables: re-run the script instead. An earlier version of
this file was written from a deck slide and listed five example checks on the input side
and five *different* ones on the output side, which read as though the two guardrails
did unrelated jobs. They do not, and that reading was the reason this file was rewritten.

## The short answer

**Almost every check runs on both sides.** Of {len(rows)} mounted rails:

- **{len(both)} run on BOTH** the prompt and the response
- **{len(inp)} run{"s" if len(inp) == 1 else ""} on the prompt only**
- **{len(out)} run on the response only**

So the response is checked by **{N_OUT}** rails and the prompt by **{N_IN}**. The output
guardrail is the *stricter* of the two, not a lighter afterthought: it does everything
the input guardrail does, plus response-specific work that has no meaning on a prompt.

{stage_table()}

## The flow

```
        user's prompt
              │
              ▼
   ┌──────────────────────────────────────────────────────┐
   │  INPUT GUARDRAIL — {N_IN} rails apply                       │
   │                                                      │
   │  Stage 1  free, deterministic, 100% of prompts       │
   │     └─ nothing conclusive? ──▶ Stage 2  local model  │
   │            └─ still unsure? ──▶ Stage 3  paid judge  │
   │                                                      │
   │  Short-circuits the moment an answer is confident.   │
   └──────────────────────────────────────────────────────┘
              │
      ┌───────┴────────┐
      │                │
   blocked          allowed
      │                │
      ▼                ▼
  REFUSE          THE TARGET AI SYSTEM
  (the prompt      (your model, RAG or chatbot —
   never reaches    the gateway does not judge
   the model)       what happens in here)
                       │
                       ▼
   ┌──────────────────────────────────────────────────────┐
   │  OUTPUT GUARDRAIL — {N_OUT} rails apply                      │
   │                                                      │
   │  The SAME {len(both)} rails as the input side, plus {len(out)} more    │
   │  that only make sense on an answer: groundedness,    │
   │  response validation, refusal detection, invented    │
   │  packages, insecure output, schema explanation.      │
   │                                                      │
   │  Same three stages, same short-circuit, same cost    │
   │  ordering.                                           │
   └──────────────────────────────────────────────────────┘
              │
      ┌───────┴────────┐
      │                │
   blocked          allowed
      │                │
      ▼                ▼
  REFUSE          DELIVER  (logged, with any redaction spans)
      │                │
      └────────┬───────┘
               ▼
      AUDIT STORE — every verdict, one schema
      findings · severity · score · redaction spans · trace
      (matched values are NEVER stored, only a fingerprint)
```

## Which rails run where

#### Both sides — {len(both)} rails

Every privacy, security, content-safety and fairness check is here. An SSN leaving the
model is worse than one arriving; a prompt injection can arrive in retrieved content as
easily as in a user's typing.

{table(both)}

#### Prompt only — {len(inp)} rail{"" if len(inp) == 1 else "s"}

{table(inp)}

#### Response only — {len(out)} rails

These are the additions you would expect on an output rail and would not expect on an
input one.

{table(out)}

## Why nine rails are one-sided

Not an oversight, and each one is asserted in `tests/test_direction.py`:

{WHY_ONE_SIDED}

## Four things that are easy to get wrong

**1 · A missing declaration means BOTH, never "neither".** A rail that does not declare
`direction` runs on both sides. That default is deliberate: forgetting to declare must
never silently *remove* a check. {len(both)} of the {len(rows)} rails rely on it.

**2 · "Does not apply" is `skipped`, not `unjudged`.** A rail that does not apply to the
side being judged is recorded as **skipped**: it had nothing to look at. It is *not*
recorded as `unjudged`, because `unjudged` means "could not look" and fail-closed turns
any unjudged path into a block. Conflating the two would mean **every response was
blocked** by the prompt-only rails and **every prompt blocked** by the eight
response-only ones. Asserted by
`test_direction.test_a_skipped_rail_cannot_cause_a_fail_closed_block`.

**3 · Escalation is conditional, not layered-always.** Stage 2 runs only when Stage 1
found something it was not confident enough to decide. Stage 3 runs only when Stage 2
was still unsure. That is the cost doctrine — free checks on 100% of traffic, paid checks
on a thin slice — and it applies identically on both sides.

**4 · "Not safe" is not one branch.** There are four outcomes, and only two of them
refuse:

| Outcome | What happens |
|---|---|
| allow, nothing found | delivered |
| allow, **with redaction spans** | delivered with the replacement text — an app that ignores `modifications.spans` **leaks the value the gateway caught** |
| block, a finding carried `action: block` | refused, and the reason is a detection |
| block, a path went `unjudged` | refused because a check **could not run** — a coverage gap, not a detection |

Treating "unsafe" as a single refuse path loses most of the usable behaviour. A support
agent pasting a customer's SSN should have it masked, not have their ticket rejected.

## Also true

- **Delivered responses are logged too**, not just blocks. An audit trail of only
  refusals proves nothing to a client reviewer.
- **Same record shape everywhere.** A red-team finding, a CI failure and a live verdict
  are the same schema, so one query answers "has this ever happened".
- **Streaming is guarded per frame.** `/v1/chat/stream` emits `stage` frames tagged
  `phase: input` or `phase: output`, so a console can show which guardrail is talking.
  (That `phase` is the input/output half of one request — it has nothing to do with the
  cascade stages, and nothing to do with the 90-day adoption phases, which were removed
  on 2026-09-03.)
"""
OUT.write_text(doc)
print(f"wrote {OUT} — both={len(both)} input={len(inp)} output={len(out)} "
      f"| input side {N_IN}, output side {N_OUT}")
