# Infosys Toolkit vs. NeMo Guardrails

The sharpest call in the analysis. Source: deck slides 67–69.
**Verdict: right shape, wrong implementation. Copy the shape, do not deploy the toolkit.**

## What Infosys has today (the shape worth copying)

`references/Infosys-Responsible-AI-Toolkit-master`, service `moderationlayer`:

- **One async dispatcher** fans a single input out to ~15 independently-thresholded checks.
- Returns **one pass/fail summary with per-check evidence**, in both coupled and
  decoupled modes.
- Thresholds configured **per account and per portfolio** through a separate admin service.
- Locally-hosted fine-tuned models for toxicity, jailbreak, restricted topics and
  gibberish — no per-call cloud cost.

That fan-out plus per-tenant threshold pattern is the correct design for AFNI and
should be reproduced.

## The five drawbacks found in its code

1. **Deployment cost.** Adopting it as designed means ~20 independently-versioned
   FastAPI microservices plus an Angular micro-frontend, each with its own
   requirements file and several GB of local model weights.
2. **Dead red-team modules.** PAIR/TAP modules are marked retired for release 2.2.1,
   while the frontend still ships orphaned red-teaming components pointing at nothing.
3. **No accuracy figures** published for any of its in-house fine-tuned models.
4. **Silent check-dropping — the disqualifying one.** The core dispatcher wraps each
   check in a broad `try/except` that logs and returns `None`. A single timeout or
   misconfigured threshold silently drops a check rather than failing loudly. That is
   precisely the failure mode a governance framework exists to prevent.
5. **Configuration coupling.** Every one of the ~20 services must be configured with
   every other service's URL.

Also on the record from the wider review: a **SDK version drift** issue and an **Azure
Blob Storage dependency**.

## Why NeMo Guardrails wins as the backbone

`references/Guardrails-develop`:

1. **One pip-installable Python package**, not a service mesh to operate.
2. **Already a plugin architecture** — every rail is a self-contained module (an
   actions file, a config schema, a manifest), so AFNI's own detectors and the other
   adopted repos plug in as first-class rails.
3. **~20 ready adapters** to managed safety vendors plus native Azure service
   adapters — Azure-first without lock-in.
4. **NVIDIA-maintained**, 383-file test suite, and it publishes honest numbers about
   its own weak spots instead of hiding them.

Known NeMo facts to carry into design: NIM F1 scores and Enterprise pricing are
published; **there is an HA gap**; the **jailbreak rail defaults to fail-open** and
must be explicitly flipped to fail-closed for client-facing traffic.

## What AFNI must build itself

NeMo provides none of these — all three are carried over from the Infosys pattern:

1. A **per-tenant / per-project threshold configuration service**, modelled on the
   Infosys admin pattern, so each AFNI project sets its own strictness without
   forking the gateway.
2. **One consolidated verdict summary** per request — not a raw list of rail outputs.
3. A **loud-failure policy**: any check that could not complete is reported as
   `unjudged`, and for client-facing traffic the gateway fails closed.

Plus the contract itself: the **OpenGuardrails Verdict/GuardEvent schema** as the
fixed interface between the gateway and every application. That is what lets AFNI
swap a detector, add a vendor, or move a check from local to cloud without touching
application code.

## Also considered and rejected as the backbone

**Guardrails AI** (`references/guardrails-main`) — verdict **Skip**. Superseded by
NeMo for AFNI's shape, and it carries a **documented PyPI supply-chain compromise**
plus an **Aug 2026 Hub deprecation** affecting a stated percentage of validators.
