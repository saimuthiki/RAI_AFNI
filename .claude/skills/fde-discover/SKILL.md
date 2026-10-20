---
name: fde-discover
description: EvoHack FDE pod stage 1. Use to prepare for, run, or synthesise a stakeholder discovery session (call prep, interview transcript, notes, "we just had the discovery call", /fde-discover). Produces discovery notes, assumption-log updates, value tree and the challenge-the-brief reframe.
---

# FDE discover: learn the problem from the stakeholder

Read `hackathon/work/00-intake.md` and `hackathon/work/assumptions.md` first. If they are missing,
run `fde-intake` first.

## Before the call
- Stress-test our own understanding with `grill-me` / `interview-me` (the humans answer).
- Turn open unknowns into a short async questionnaire (`to-questionnaire`) the stakeholder can
  fill in before the call.
- Use `hackathon/03-discovery-kit.md` for the interview guide and the "5 whys / show me" prompts.

## After the call (a transcript or notes are provided)
1. Run `meeting-analyzer` over the transcript to capture quotes,
   decisions and the stakeholder's emotional priorities (what they repeat or stress).
2. Write `hackathon/work/01-discovery.md`: verbatim pain quotes, current process, volumes,
   frequencies, costs, systems and data, constraints, definition of success in their words.
3. Map the as-is process with `process-mapper`: steps, hand-offs, wait vs work time, bottleneck.
4. Update `assumptions.md`: mark each assumption validated, invalidated or open, with the evidence.
5. Build `hackathon/work/value-tree.md`: business KPI → operational driver → lever our product
   pulls → baseline → target → how we'll measure it in the demo.
6. Write `hackathon/work/01b-reframe.md`: "You asked for X. We heard Y (evidence). We propose Z,
   which moves <KPI> by <estimate>." Include what we will NOT build.
7. Draft the playback message the humans send to the stakeholder to confirm the reframe and metric.

Quote the stakeholder exactly; never invent numbers. Mark every estimate `[EST]`, with its basis.
