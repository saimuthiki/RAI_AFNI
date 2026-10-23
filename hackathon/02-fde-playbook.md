# FDE pod playbook: 3 humans + an agent bench, one week, five stages

The rule for the week: **every artifact a judge could ask about is on disk in `hackathon/work/`**
(problem, discovery notes, assumptions, spec, ADRs, test evidence, impact model, deck). Agents
read and write the same files, so the humans, the agents and the judges all see one source of truth.

## 1. Pod design (show this slide at the demo)

| Human (converged role) | Owns | Agent teammates they direct |
|---|---|---|
| **H1 · FDE lead / "customer owner"**: runs stakeholder sessions, owns the problem framing and the pitch | Problem statement, success metric, demo story | `product-manager`, `business-strategist`, `sales-discovery-coach`, `ux-researcher`, `executive-summary-generator`, `visual-storyteller` |
| **H2 · FDE builder / architect** (the one AI Practice member, if any): owns the architecture, the agentic core and the AI guardrails | Architecture, AI components, data model | `software-architect`, `backend-architect`, `ai-engineer`, `rag-pipeline-engineer`, `multi-agent-systems-architect`, `prompt-engineer` |
| **H3 · FDE builder / quality and ship**: owns the UI, tests, deploy and the evidence that it works | UI, test suite, deployment, demo environment | `frontend-developer`, `rapid-prototyper`, `ui-designer`, `test-automation-engineer`, `api-tester`, `reality-checker`, `devops-automator`, `sre` |

All agents live in `.claude/agents/`. Call them with "use the <name> agent to …" or via the
Agent tool. Run independent ones in parallel (`dispatching-parallel-agents`).

**Role convergence, made visible:** every human also takes an off-role turn. H2 runs one
stakeholder follow-up, H1 writes one acceptance test, H3 writes the cost model. Log these
in `hackathon/work/pod-log.md`. That log is the evidence for the "converged roles" slide.

## 2. Stage-by-stage runbook

Each stage has an entry skill (our own `/fde-*` skills in `.claude/skills/`), supporting skills,
an output artifact, and an exit gate. Don't advance until the gate passes.

### Stage 0 · Intake (hour 0–2 after the problem statement lands): `/fde-intake`
- Paste the problem statement. The skill writes `work/00-intake.md` with the restated problem,
  stakeholder map, unknowns, initial hypotheses, a draft success metric, and the 15 questions for
  the discovery call.
- Supporting skills: `thinking-out-loud`, `requirements-clarity`, `product-lens`, `roast`.
- **Gate:** the discovery call is booked and the question list is reviewed by all three humans.

### Stage 1 · Discover (day 1): `/fde-discover`
- Before the call: `grill-me` / `interview-me` on our own assumptions, then `to-questionnaire`
  to send the stakeholder a short async questionnaire.
- During the call: H1 leads, H2 takes notes, H3 watches for data and integration facts. Record it
  if allowed.
- After the call: feed the transcript to `meeting-analyzer`, then
  `process-mapper` (as-is process, cycle times, bottlenecks) and `product-discovery`
  (assumption map). Use `market-research` / `competitive-teardown` if an external market framing helps.
- Outputs: `work/01-discovery.md` (what we heard, as verbatim quotes), `work/assumptions.md`
  (each assumption: belief, evidence, risk, how to validate, status), `work/value-tree.md`
  (business KPI → driver → lever our product pulls → baseline → target).
- **Challenge the brief:** write `work/01b-reframe.md`, "You asked for X. We heard the real problem
  is Y, because <evidence>. We propose Z." Play it back to the stakeholder and get a yes.
- **Gate:** the stakeholder confirms the reframed problem and the success metric in writing
  (an email or chat message is enough), and all assumptions rated high-risk have a validation plan.

### Stage 2 · Design (day 2): `/fde-design`
- `spec-driven-development` / `to-spec` → `work/02-spec.md`: users, jobs-to-be-done, scope
  in and out, acceptance criteria tied to the value tree.
- `devil` attacks the spec (missing states, edge cases). Fix the spec, don't argue with it.
- `senior-architect`, `tech-stack-evaluator`, `c4-architecture`, `database-designer`; plus
  `agent-designer` / `rag-architect` if the product is agentic → `work/02-architecture.md` and ADRs
  in `work/adr/`.
- `ui-ux-pro-max` / `taste-skill` / `frontend-design` → design system and key screens.
- `to-tickets` / `planning-and-task-breakdown` / `writing-plans` → `work/02-plan.md`, vertical
  slices sized for subagents.
- Submit the tech-spec and infra request to the organisers today. They asked for it in the
  first couple of days.
- **Gate:** walking-skeleton slice defined; the stakeholder has seen a clickable `prototype` of the
  main screen.

### Stage 3 · Build (days 3–5): `/fde-build`
- Day-3 morning: ship a **walking skeleton** end to end (UI → API → agent → data → UI) and deploy
  it, even though it's ugly.
- Then `subagent-driven-development` per slice: a fresh subagent implements with
  `test-driven-development`, then a reviewer subagent checks spec compliance and code quality.
- Use `using-git-worktrees` so H2 and H3 (and their agents) build in parallel without collisions.
- Use `find-docs` (Context7) before writing against any library API. Never guess an API.
- Use `systematic-debugging` for every bug. Keep `planning-with-files` running so the plan
  survives context resets.
- Mid-build stakeholder check-in on day 4: show the running app and capture feedback in `work/feedback.md`.
- **Gate:** every acceptance criterion has a passing automated test or a recorded manual check.

### Stage 4 · Test & Deploy (day 5–6): `/fde-ship`
- `webapp-testing` (Playwright) for E2E on the demo path; `reality-checker` agent as the skeptic.
- `adversarial-reviewer` + `requesting-code-review` for the code; `security-and-hardening` +
  `ship-gate` for the pre-launch audit.
- If the product uses LLMs: run prompts and outputs through our RAI gateway (`rai_platform/`) and
  show it in the demo. Responsible AI by design is a differentiator.
- `shipping-and-launch` + `observability-and-instrumentation`: health check, logs, rollback plan.
- Deploy to the organiser-provided target and record a backup demo video with `ui-demo` / `demo-video`.
- **Gate:** the demo script runs three times in a row on the deployed URL with no manual fixes
  (`verification-before-completion`).

### Stage 5 · Demo & Pitch (day 6–7): `/fde-pitch`
- `data-storytelling` + `financial-analyst` / `cfo-advisor` + `market-sizing-analysis` →
  `work/05-impact-model.md` (conservative, base and stretch cases, with every assumption cited).
- `board-deck-builder` / `ceo-advisor` / `executive-mentor` frame the narrative for C-level judges.
- Build the deck: the `pptx` skill for PowerPoint, or `frontend-slides` for an animated HTML deck.
  Use `architecture-diagram-creator` / `timeline-creator` for visuals.
- Rehearse against the clock with `scenario-war-room`: "what if the judge asks X". Prepare 10 hard
  Q&A answers.
- **30-minute slot shape:** 3 min hook (stakeholder pain in their words + the cost of it) → 2 min
  reframe ("we challenged the brief") → 12 min live demo of the outcome → 5 min "how 3 humans and
  N agents built it" (pod chart, agent log, evidence) → 3 min impact, rollout and next 90 days →
  5 min Q&A.

## 3. Daily cadence

| Time | Ritual |
|---|---|
| 09:30 | 15-min stand-up: read `work/progress.md` (written by `planning-with-files`), pick slices |
| 13:30 | 10-min integration check: is the deployed build still green? |
| 18:00 | `handoff` skill: each human writes a handoff note so tomorrow's agents start warm |

## 4. Guardrails for working with agents

- Agents never talk to the stakeholder; humans do. Agents prepare, synthesise and challenge.
- Every agent claim of "done" needs evidence: test output, screenshot or URL
  (`verification-before-completion`).
- Keep the active skill set lean. Pull extra skills from the 10k-entry vault only when a stage
  needs them: `hackathon/toolkit/skill.sh find <words>`, then `skill.sh enable <name>`.
- Corporate policy: Claude, Cursor and Copilot only. MCPs that call third-party SaaS (Firecrawl,
  Composio) need organiser approval first.
- No real customer PII in prompts. Use the synthetic data generator, and the RAI gateway for anything live.
