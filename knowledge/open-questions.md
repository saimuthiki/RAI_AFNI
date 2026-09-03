# Open Questions & Risks

Things that are genuinely unresolved. Anything settled lives in
[decisions.md](decisions.md). Keep this file honest — it is the list that stops the
platform stalling before it ships.

## Blocking the build

| # | Item | Owner | Why it blocks |
|---|---|---|---|
| ~~1~~ | ~~**Deepchecks AGPL-3.0 ruling**~~ — **CLOSED 2026-09-02** | Legal | AFNI confirmed it holds licences covering Apache-2.0, MIT and AGPL-3.0 and that no repository in this review is licence-restricted. Deepchecks stays at "Bench for later" for a technical reason instead: every check is a batch `SingleDatasetCheck`/`TrainTestCheck` over a `Dataset`, so it has no per-request API to put on a request path at all. |
| ~~2~~ | ~~**promptfoo remote-only plugin data residency**~~ — **CLOSED 2026-09-02** | Legal | AFNI confirmed that sending data to an external service is acceptable, and that external plugins may be used. So this no longer blocks the build. Two consequences worth keeping on the record rather than losing with the question: (a) it is a *per-dataset* clearance in practice — the harm corpus is the one asset still held back, and not on residency grounds (see below); (b) an external plugin is a **reliability** dependency as well as a data one, so a remote-only redteam plugin cannot be the sole evidence for a capability the platform claims. Pair each one with a local check. |
| 3 | **One accountable owner per tenet** | Kiran / AFNI | Seven names. Build-plan item 21. Without them there is no governance register and no escalation path — the framework is a document, not a standard. |

### The one dataset still held back, and why it is not a residency question

`rai_platform/corpus/harm-intents.jsonl` holds **11,369 genuinely harmful prompts**.
`AFNI_CORPUS_ALLOW_CLOUD` defaults to **off**, so a corpus run is capped at Stage 2 and
cannot reach a paid third-party judge. With external transport now cleared, that default
stands for three reasons that are **not** about residency, and the flag exists so AFNI can
override it deliberately rather than by accident:

1. **Volume.** 11,369 prompts through a paid judge, twice per prompt (two judge rails), is
   a bill nobody has approved. The cap is a spend control before it is anything else.
2. **What the content is.** Sending a vendor 11,369 requests for bomb-making and
   drug-synthesis instructions will trip their own abuse detection. The likely outcome is
   a suspended AFNI account, not a scored corpus.
3. **It is not needed for the measurement.** The comparison that makes the business case
   is Stage 1 versus Stage 1 + 2 — both entirely local. Stage 3 adds cost to a number we
   can already produce.

Set `AFNI_CORPUS_ALLOW_CLOUD=1` on the server when AFNI wants a Stage-3 pass; the run then
reports which provider served each call. It is server-side, not a request field, so it is
a deployment decision and not a checkbox in the console.

## Vendor and supply-chain risks on the record

| Risk | Detail | Handling |
|---|---|---|
| **LLM Guard is archived** | Protect AI archived the repo; no upstream fixes will arrive. It is nonetheless the runtime primary for four of seven tenets. | Fork into an AFNI-owned repo, pin every model revision, own maintenance. Maintenance burden assessed as **High**. |
| **Guardrails AI PyPI compromise** | Documented supply-chain compromise, plus an Aug 2026 Hub deprecation affecting a percentage of validators. | Contributes to the **Skip** verdict. Kept on the record; AFNI has since asked for integration regardless. |
| **`agentic_security-main` hard-coded bearer token** | A third-party bearer token committed in the source. | Log for the record. Do not run as-is; it is "Bench for later" anyway. |
| **OpenGuardrails is pre-1.0** | The schema AFNI is adopting as its permanent internal contract is not yet stable. | Pin the protocol version. Accept that a migration may be needed. |
| **NeMo HA gap** | No high-availability story published for the rail engine that sits in every request path. | Design the gateway's own HA around it; unresolved. |
| **NeMo jailbreak rail fails open** | Default behaviour passes traffic when the rail errors. | Explicitly flipped to fail-closed — but verify it stays flipped across upgrades. |
| **No accuracy figures for Infosys in-house models** | Nothing published for any of its fine-tuned models. | Contributes to "copy the shape, not the build". |

## Design questions not yet answered

1. **Where does the gateway physically run?** Azure-first is agreed; the deployment
   target (App Service / AKS / Container Apps), scaling model, and the latency budget
   for the input-rail chain are not specified anywhere in the analysis.
2. **What is the latency budget?** The whole cost doctrine rests on "cheap checks on
   every request", but no per-rail millisecond target was set. This determines how
   many local models can sit in the input path.
3. **Threshold calibration data.** The build plan says "calibrate on real AFNI traffic, do
   not ship defaults" — but which application's traffic, and is it available and
   permitted for this use?
4. **The pilot application.** The baseline red-team scan needs one existing AFNI AI app
   scan and the fast CI tier. Not yet named.
5. **Azure PII pricing.** ~$0.38 per 1,000 records was noted with an explicit
   "verify the exact current rate" caveat. Not verified.
6. **Multi-tenancy model.** The threshold service is per-account and per-portfolio in
   Infosys's shape. Whether AFNI's unit is client, project, or application is undecided
   and changes the config schema.
7. **Does AFNI need media moderation at all?** NSFW image/video and DICOM PII scanning
   are conditional "if the business needs them". Nobody has said whether it does.

## Found while building the platform (new)

These came out of writing rails against the real vendored source, and none of
them are in the original analysis.

| # | Finding | Consequence |
|---|---|---|
| 1 | **promptfoo's `bias:*` probes are remote-generated only.** Confirmed at `references/promptfoo-main/src/redteam/constants/plugins.ts:576-582`, where `BIAS_PLUGINS` sits in `UI_DISABLED_WHEN_REMOTE_UNAVAILABLE`. | Running that pack ships AFNI-derived prompts and the application's stated purpose to `api.promptfoo.app`. CI only, so no client traffic is involved, but it is a pre-adoption review item and it widens open item #2 above from "some plugins" to a named, confirmed set. |
| 2 | **A checksum-valid SSN blocks client-facing traffic today.** HIGH severity escalates for a NER second opinion; Presidio is absent, so the rail returns `unjudged`, and `unjudged` fails closed. | Correct behaviour for "regulated PII is present and I cannot fully assess this payload", but installing `presidio-analyzer` will visibly change the block rate. Worth knowing before a pilot, not during one. |
| 3 | **Several upstream patterns are too loose to ship as-is.** hai-guardrails' `mrn-numeric` regex has an optional prefix group, so it matches every 7–10 digit integer; its bare ICD-10 pattern redacts "vitamin B12" and "room T10"; NeMo's `code.yara` fires on `import os`; NeMo's `sqli.yara` bare `--` signal fires on ordinary prose containing an em-dash. | Each is gated, tightened or left opt-in, with the reason in a code comment and a false-positive test. Relevant to the roadmap's "calibrate on real AFNI traffic" action — the defaults are not safe unreviewed. |
| 4 | **Checksums are missing upstream where they matter.** Infosys' Aadhaar recognizer is pattern-only at score 0.5 (no Verhoeff); safe-zone's `IBAN_TR` is shape-only (no mod-97); no reviewed repo validates NPI or DEA check digits. | Implemented here. Note the provenance honestly: the Verhoeff tables and the NPI 80840 prefix rule are published standards, **not** ported from any vendored repo. |
| 5 | **Stdlib `xml.etree` is the only XML parser available at Stage 1** (`defusedxml` would break the zero-dependency rule). | Mitigated by refusing any `<!DOCTYPE`/`<!ENTITY>` fragment before parsing, plus a size cap; verified against a billion-laughs payload (returns in 0.1 ms without expanding). A security reviewer should still see this decision explicitly. |
| 6 | **AGPL-3.0 obligation is about distribution, not possession.** Deepchecks is AGPL-3.0; §13 attaches an obligation to offer the combined work's source to anyone served over a network. | **Settled 2026-09-02:** AFNI holds the licences and has confirmed there is no restriction on using any repository in this review, including the AGPL-3.0 one. Kept on the record — not as an open question, but because a future reader will otherwise re-open it. The §13 mechanics are unchanged; what changed is that AFNI has cleared them. |
| 7 | **`stop_reason` / `finish_reason` / `model` were being judged as user content.** | Fixed. Worth noting as a class of bug: any field-walking guardrail will do this unless it filters transport metadata, and the symptom is bizarre — a missing model dependency blocking a request because nothing could judge the string `"gpt-4o"`. |

## Stale framing to fix in the client materials

The deck cites **August 2026** EU AI Act high-risk obligations and the Guardrails AI
Hub deprecation as *future* dates. Both are now in the past. Any slide or narrative
reused with Kiran needs the tense corrected — this is a credibility detail in front of
a client, not a cosmetic one.
