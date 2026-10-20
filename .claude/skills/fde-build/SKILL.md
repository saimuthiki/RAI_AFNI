---
name: fde-build
description: EvoHack FDE pod stage 3. Use to execute the slice plan with AI agents as teammates (/fde-build, "start building", "next slice"). Drives subagent-driven TDD slices, parallel worktrees and continuous deploy.
---

# FDE build: lean, slice by slice, agents as teammates

Inputs: `hackathon/work/02-plan.md`, `02-spec.md`, `02-architecture.md`. Code lives in
`hackathon/app/` unless the plan says otherwise.

- Keep `planning-with-files` state (`task_plan.md`, `progress.md`) current so any human or agent can resume.
- Slice 1 = walking skeleton: UI → API → core logic or agent → data → UI, deployed. Nothing else
  starts until it runs.
- For each slice: `subagent-driven-development`. Dispatch an implementer subagent with
  `test-driven-development`, then a reviewer subagent (spec compliance, then code quality). Run
  independent slices in parallel (`dispatching-parallel-agents`) in separate git worktrees
  (`using-git-worktrees`).
- Pick the specialist agent per slice: `Frontend Developer`, `Backend Architect`, `AI Engineer`,
  `rapid-prototyper`, `data-visualization-engineer`, `devops-automator`.
- Look up library APIs with `find-docs` (Context7) instead of recalling them.
- Every bug goes through `systematic-debugging`. No guess-fixes.
- Generate realistic synthetic data early (volumes and edge cases from `01-discovery.md`) so the
  demo looks like the stakeholder's world.
- Log human and agent contributions in `hackathon/work/pod-log.md`. That log becomes the
  "how we built it" slide.
- After each slice: tests green, deploy, update `progress.md`, then `verification-before-completion`.
