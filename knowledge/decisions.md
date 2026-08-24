# Locked Decisions

Everything here is decided in the Phase-0 analysis and presented to the client.
Treat as settled unless Kiran overturns it. Source: deck slides 65, 67–69, 78.

## D1 — One gateway, not per-project checks
Every AI-native AFNI application calls **one shared internal Responsible AI gateway**.
No project wires its own detectors. Rationale: maintenance is what sinks governance
programmes — one gateway, one verdict format, one audit trail, and accept a slightly
less capable tool when it means one fewer thing to keep alive.

## D2 — NeMo Guardrails is the rail engine
The gateway is a **Python FastAPI service running NVIDIA NeMo Guardrails**
(`references/Guardrails-develop`). Four reasons: one pip-installable package rather
than a service mesh; its `library/` directory is already a plugin architecture (each
rail = actions file + config schema + manifest) so AFNI's own detectors and the other
adopted tools plug in as first-class rails; ~20 ready adapters for managed safety
vendors plus Azure; NVIDIA-maintained with a 383-file test suite and published
weakness numbers. Detail: [infosys-vs-nemo.md](infosys-vs-nemo.md).

## D3 — OpenGuardrails Verdict/GuardEvent is the contract
The gateway speaks the **OpenGuardrails `GuardEvent` / `Verdict` JSON schema**
(`references/openguardrails-main`) plus its safety/security/privacy taxonomy as
AFNI's internal contract. OpenGuardrails contributes no detector at all — that is
the point: a vendor-neutral record shape means a detector can be swapped, a vendor
added, or a check moved from local to cloud without touching application code.
**Pin the protocol version — it is still pre-1.0.**

## D4 — LLM Guard is the runtime workhorse, forked and pinned
`references/llm-guard-main` is the single best value-per-effort component in the set
and appears in the recommended stack for four of seven tenets. MIT, free, no paid API.
**But Protect AI archived the repo**, so AFNI must fork it into an AFNI-owned
repository and pin every HuggingFace model revision. AFNI owns its maintenance.

## D5 — Cloud is a second opinion, never the primary filter
Azure-first but not vendor-locked. Cheap deterministic local checks run on every
request; a paid model or cloud service is called only for the slice of traffic that
scores near a threshold; the expensive thorough work runs offline. The independent
evidence is that cloud content filters weaken on adversarial input, so **no single
filter is ever the whole defence** and every layer is allowed to be imperfect.

## D6 — Fairness and explainability are not live checks
Bias is a pattern, not an event: Fairlearn/AIF360 run as **scheduled batch jobs**,
never as a per-response gate. SHAP is too slow for synchronous request handling —
expose an `explain` endpoint backed by a background job.

## D7 — Copy Infosys's shape, do not deploy Infosys
The Infosys toolkit's one-dispatcher / fan-out / per-tenant-threshold pattern is the
right design and should be reproduced. Deploying the toolkit itself is not — see
[infosys-vs-nemo.md](infosys-vs-nemo.md) for the five drawbacks found in its code.

## The two rules that never bend

1. **Fail closed.** For client-facing traffic the gateway blocks on failure. NeMo's
   jailbreak rail defaults to fail-*open* — that default must be explicitly flipped.
2. **Fail loud.** Any check that could not run is reported as **`unjudged`**, never
   silently passed. This exists because Infosys's dispatcher wraps each check in a
   broad `try/except` that logs and returns `None` — one timeout silently drops a
   check. That is precisely the failure a governance layer exists to prevent.

## Three things AFNI must build itself
NeMo provides none of these:
1. A **per-tenant / per-project threshold configuration service**, modelled on the
   Infosys admin pattern, so each project sets its own strictness without forking.
2. **One consolidated verdict summary** per request — not a raw list of rail outputs.
3. The **loud-failure / fail-closed policy** above, as enforced behaviour.
