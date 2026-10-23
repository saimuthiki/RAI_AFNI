---
name: fde-design
description: EvoHack FDE pod stage 2. Use after discovery is confirmed to produce the spec, architecture, ADRs, UI direction, slice plan and organiser tech-spec request (/fde-design, "let's design it", "write the spec").
---

# FDE design: shape the solution around what discovery proved

Inputs: `hackathon/work/01-discovery.md`, `01b-reframe.md`, `value-tree.md`, `assumptions.md`.

1. **Spec**: use `spec-driven-development` (or `to-spec`) to write `hackathon/work/02-spec.md`:
   personas and jobs-to-be-done, the demo user journey, scope in and out, functional requirements,
   and acceptance criteria. Each acceptance criterion links to a value-tree lever.
2. **Attack it**: run `devil` on the spec. Fold its blocking questions back in, or list them for
   the stakeholder.
3. **Architecture**: use `senior-architect` + `tech-stack-evaluator`. Prefer boring, fast-to-ship
   tech the pod knows. Produce `hackathon/work/02-architecture.md` with C4 context and container
   diagrams (`c4-architecture`), data model (`database-designer`), and the agent design
   (`agent-designer` / `agent-workflow-designer` / `rag-architect`) if AI is in the product.
   Record decisions as ADRs in `hackathon/work/adr/NNN-title.md` (`documentation-and-adrs`).
4. **Responsible AI**: if an LLM touches user data, route it through `rai_platform/` (the AFNI
   RAI gateway in this repo) and note the rails used.
5. **UI**: pick a design system with `ui-ux-pro-max` / `taste-skill`, and sketch the 3 key screens.
   Build a throwaway `prototype` of the main screen for stakeholder feedback.
6. **Plan**: break the work into vertical slices with `to-tickets` / `planning-and-task-breakdown`,
   then `writing-plans`, in `hackathon/work/02-plan.md`. Slice 1 is the walking skeleton deployed
   end to end. Tag each slice with its owner (H1/H2/H3) and the agents to use.
7. **Organiser request**: draft `hackathon/work/02-tech-request.md` (stack, infra, API access, data).

Gate: walking skeleton defined, prototype shown, tech request drafted.
