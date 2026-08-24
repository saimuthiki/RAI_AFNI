# Open Questions & Risks

Things that are genuinely unresolved. Anything settled lives in
[decisions.md](decisions.md). Keep this file honest — it is the list that stops the
platform stalling in Phase 1.

## Blocking Phase 1

| # | Item | Owner | Why it blocks |
|---|---|---|---|
| 1 | **Deepchecks AGPL-3.0 ruling** | Legal | AGPL is copyleft over a network boundary. Until ruled on, Deepchecks cannot be embedded in anything client-facing, which is why it sits at "Bench for later" rather than adopted for drift detection. |
| 2 | **promptfoo remote-only plugin data residency** | Legal | Some redteam plugins call promptfoo-hosted services. Needs a ruling before AFNI puts client data through them or ships a promptfoo-generated report as a client deliverable. |
| 3 | **One accountable owner per tenet** | Kiran / AFNI | Seven names. Phase 1 action 4. Without them there is no governance register and no escalation path — the framework is a document, not a standard. |

## Vendor and supply-chain risks on the record

| Risk | Detail | Handling |
|---|---|---|
| **LLM Guard is archived** | Protect AI archived the repo; no upstream fixes will arrive. It is nonetheless the runtime primary for four of seven tenets. | Fork into an AFNI-owned repo, pin every model revision, own maintenance. Maintenance burden assessed as **High**. |
| **Guardrails AI PyPI compromise** | Documented supply-chain compromise, plus an Aug 2026 Hub deprecation affecting a percentage of validators. | Contributes to the **Skip** verdict. Log for the record (Phase 1 action 8). |
| **`agentic_security-main` hard-coded bearer token** | A third-party bearer token committed in the source. | Log for the record. Do not run as-is; it is "Bench for later" anyway. |
| **OpenGuardrails is pre-1.0** | The schema AFNI is adopting as its permanent internal contract is not yet stable. | Pin the protocol version. Accept that a migration may be needed. |
| **NeMo HA gap** | No high-availability story published for the rail engine that sits in every request path. | Design the gateway's own HA around it; unresolved. |
| **NeMo jailbreak rail fails open** | Default behaviour passes traffic when the rail errors. | Explicitly flipped to fail-closed (Phase 1 action 1) — but verify it stays flipped across upgrades. |
| **No accuracy figures for Infosys in-house models** | Nothing published for any of its fine-tuned models. | Contributes to "copy the shape, not the build". |

## Design questions not yet answered

1. **Where does the gateway physically run?** Azure-first is agreed; the deployment
   target (App Service / AKS / Container Apps), scaling model, and the latency budget
   for the input-rail chain are not specified anywhere in Phase 0.
2. **What is the latency budget?** The whole cost doctrine rests on "cheap checks on
   every request", but no per-rail millisecond target was set. This determines how
   many local models can sit in the input path.
3. **Threshold calibration data.** Phase 2 says "calibrate on real AFNI traffic, do
   not ship defaults" — but which application's traffic, and is it available and
   permitted for this use?
4. **The pilot application.** Phase 1 needs one existing AFNI AI app for the baseline
   scan and the fast CI tier. Not yet named.
5. **Azure PII pricing.** ~$0.38 per 1,000 records was noted with an explicit
   "verify the exact current rate" caveat. Not verified.
6. **Multi-tenancy model.** The threshold service is per-account and per-portfolio in
   Infosys's shape. Whether AFNI's unit is client, project, or application is undecided
   and changes the config schema.
7. **Does AFNI need media moderation at all?** NSFW image/video and DICOM PII scanning
   are Phase 3 "if the business needs them". Nobody has said whether it does.

## Stale framing to fix in the client materials

The deck cites **August 2026** EU AI Act high-risk obligations and the Guardrails AI
Hub deprecation as *future* dates. Both are now in the past. Any slide or narrative
reused with Kiran needs the tense corrected — this is a credibility detail in front of
a client, not a cosmetic one.
