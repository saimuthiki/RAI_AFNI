---
name: fde-intake
description: EvoHack FDE pod stage 0. Use the moment a hackathon problem statement or stakeholder brief arrives ("here is our problem statement", "we got the use case", /fde-intake). Turns the raw brief into hackathon/work/00-intake.md with restated problem, stakeholder map, hypotheses, draft success metric and the discovery question list.
---

# FDE intake: first two hours with a new problem statement

You are the FDE pod's lead analyst. The pod is 3 humans plus the agent bench in `.claude/agents/`.
Read `hackathon/02-fde-playbook.md` (section 2, Stage 0) and `hackathon/01-brief-analysis.md` first.

1. Save the brief verbatim to `hackathon/work/00-brief.md`, with the date and the stakeholder name.
2. If the brief is a messy ramble or a transcript, use the `thinking-out-loud` echo discipline:
   separate what was *said* from what you *infer*.
3. Write `hackathon/work/00-intake.md` with these sections:
   - **Restated problem** in one sentence: "<who> cannot <do what> because <why>, costing <what>".
   - **Stakeholder map**: sponsor, decision maker, daily users, data owners, blockers.
   - **What we know / what we assume / what we don't know**, as three columns.
   - **Hypotheses** (3–5), each with how we'd prove it wrong.
   - **Draft north-star metric** and 2–3 guardrail metrics, each with a baseline if known, else "TBD in discovery".
   - **Brief-challenge candidates**: where the brief may be solving a symptom.
   - **Discovery questions**, 15 maximum, ordered: pain and cost → current process → data →
     constraints → success → politics. Every question must close a specific unknown or assumption.
   - **Data and access requests** for the organisers (mock data shape, systems, infra).
4. Run the `roast` skill on the restated problem. Record its GO / RESHAPE / KILL verdict and the
   cheapest de-risking test.
5. Create `hackathon/work/assumptions.md` as a table (id, assumption, evidence, risk H/M/L,
   validation, status) and `hackathon/work/pod-log.md` (who did what, human or agent).
6. End with a short summary for the humans: the 3 biggest unknowns and the proposed agenda for
   the discovery call.

Do not design solutions yet. Note solution ideas under "Parked ideas" only.
