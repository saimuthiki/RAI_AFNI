# AFNI Responsible AI Project — Work & Conversation Tracker

This file is a running, human-readable log of every substantive ask, decision, and change made
while building AFNI's Responsible AI Governance Framework (the PPTX deck, the "Guardrail Atlas"
HTML artifact, and the supporting analysis files). It is updated after every conversation where
real work happens — whether that's the same day or a new session entirely — so nothing discussed
gets lost.

**Entry format:**
```
### [Date] — [Short heading of the ask]
**Type:** New Build | Enhancement | Modification | Bug Fix | Clarification
**Ask:** one or two lines (or bullets) summarizing what was requested, in plain terms
**What was done:** bullets describing the actual work performed
**Files created / changed:** path — one-line note, for every file touched
```

---

## Log

### 2026-08-18 — Deep-dive analysis of 23 responsible-AI repos + first PPTX/HTML build
**Type:** New Build
**Ask:** Read the client-brief transcript (`Responsible_AI_Framework_Brief_for_PPT.md`), then deeply
analyze all 23 repositories under `references/` at the source-code level (not just READMEs), tag
every concrete check to one of 7 responsible-AI tenets, and produce two deliverables: a PowerPoint
deck and an HTML artifact. Mid-task additions: (1) also cover guardrail *development* vs
*vulnerability/red-team testing* as a second axis, and (2) treat Sai's prior "3-layer" (library /
model / prompt-template) pattern from Infosys as one illustrative precedent, not a mandatory mold —
pick whatever combination of tools genuinely wins per tenet.
**What was done:**
- Ran a 23-agent Workflow to deep-read every repo's actual source (modules, key classes, example/test
  files), producing structured JSON reports (features, limitations, prerequisites, license, cost,
  integration effort, layer type, dev-vs-testing role, AFNI fit).
- Retried and manually recovered the one repo (`llm-guard-main`) whose agent hit a transient API error.
- Ran an Opus-tier synthesis agent over all 23 reports to build: a master checklist of aspects (142
  items), a tenet-by-tenet recommendation matrix, a dev-vs-testing split, a feasibility matrix, a
  unified architecture recommendation, and a 3-phase roadmap.
- Hand-wrote plain-English slide copy for each repo (raw technical extracts were too dense for a
  client deck) and built a 61-slide PPTX plus an interactive "Guardrail Atlas" HTML dashboard.
- Saved a standing preference to auto-memory: use Opus for complex/judgment subtasks, Sonnet for
  routine/mechanical work.
**Files created / changed:**
- `RAI_Repo_Reports.json` — the 23 structured deep-dive reports
- `RAI_Synthesis.json` — master checklist, tenet matrix, dev/test split, feasibility, architecture, roadmap
- `repo_slide_content.py` — plain-English per-repo slide copy (23 entries)
- `build_pptx.py`, `build_deck.py`, `build_deck_synthesis.py` — PPTX generation pipeline
- `AFNI_Responsible_AI_Framework.pptx` — first version, 61 slides
- `html_css.py`, `html_js.py`, `html_diagram.py`, `build_html.py` — HTML artifact generation pipeline
- `guardrail_atlas.html` — published as Artifact "Guardrail Atlas"
- `qa_deck.py`, `verify_deck.py` — layout-overflow and coverage QA scripts for the PPTX

### 2026-08-19 — Request-flow flowchart + Infosys-vs-NeMo comparison
**Type:** Enhancement
**Ask:** Add a detailed flowchart showing exactly how a request flows end to end and how toxic/unsafe
responses get mitigated, plus a dedicated comparison slide (diagram + bullets) contrasting the
Infosys Responsible AI Toolkit's current shape against NVIDIA NeMo Guardrails, covering drawbacks
found and the right implementation path. Mirror both in the HTML artifact too.
**What was done:**
- Added flowchart-drawing helpers (connectors, arrowheads, flow boxes) to the PPTX builder.
- Built a step-by-step request-flow slide (input rails → decision diamond → model call → output
  rails → decision diamond → delivery, with the "not safe" branch fanning into 4 explicit mitigation
  actions, an audit-store sink, and the offline red-team feedback loop).
- Built an Infosys-vs-NeMo side-by-side diagram slide plus a 4-quadrant bullet detail slide (what
  Infosys has today / drawbacks found / what NeMo brings / what AFNI must build itself).
- Mirrored both as new sections in the HTML artifact: a zoomed-in SVG mitigation-branch diagram and
  an Infosys-vs-NeMo comparison section.
**Files created / changed:**
- `build_pptx.py` — added `flow_box`, `flow_arrow`, `add_line`, `add_arrowhead` helpers
- `build_deck_flow.py` — new: request-flow slide + Infosys-vs-NeMo diagram/bullet slides
- `build_deck_synthesis.py` — wired the new flow/comparison slides into the deck assembly
- `AFNI_Responsible_AI_Framework.pptx` — grew to 64 slides
- `html_diagram.py` — added `MITIGATION_SVG`
- `build_html.py` — added the Infosys-vs-NeMo HTML section
- `guardrail_atlas.html` — republished to the same Artifact URL

### 2026-08-20 — Repo-slide enrichment, 7 tenet cheat sheets, 7 capability matrices
**Type:** Enhancement
**Ask:** Three additions, PPT-side only: (1) a Tier/Vendor/Open-source-vs-Cloud/AFNI-recommendation
"cheat sheet" slide per tenet, in the style of a detailed Privacy example the user pasted; (2) a
capability matrix per tenet (capabilities as rows, tools as columns, ●/◐/– status, best-pick call per
row) covering every reference repo, one matrix per tenet, sized to fit one slide each; (3) cross-check
the user's pasted "Framework-by-Framework Backup" write-ups (Infosys, NeMo, MS RAI Toolbox, Guardrails
AI, LLM Guard, DeepEval, DeepTeam) against the *existing* 23 repo slides and embed any missing facts
or perspective directly into those slides — reusing the existing slide layout, not creating new ones
for this part.
**What was done:**
- Patched every existing repo-slide entry with a `tier`, `vendor`, and `build_replicate` (build vs.
  buy) field; updated the repo-slide PPTX layout to show all three in the facts card and a new
  "Build vs. Buy" box.
- Cross-checked the user's pasted write-ups against the 4 repos they overlapped with
  (`Infosys-Responsible-AI-Toolkit-master`, `Guardrails-develop`, `guardrails-main`, `llm-guard-main`)
  and embedded the specific missing facts (SDK version drift, Azure Blob Storage dependency, NIM F1
  scores + Enterprise pricing + HA gap, Aug 2026 Hub-deprecation percentage, named bias/toxicity
  models) into their existing limitation/feature/fit fields.
- Built 7 new tenet cheat-sheet slides (Open-Source / Cloud & Paid / AFNI Recommendation / Principle)
  using the format of the user's pasted Privacy example, generalized to all 7 tenets with specific
  named tools per tenet.
- Built 7 new capability-matrix slides as native PPTX tables (up to 22 tool columns), each with a
  legend and per-capability best-pick line, derived from the master checklist plus manual
  delegation/partial overrides and virtual cloud-service columns.
- Iterated on font size / row height / label length twice to clear text-overflow QA on the dense
  matrix tables.
**Files created / changed:**
- `patch_repo_slides.py`, `patch_repo_slides_2.py` — one-time scripts that enriched `repo_slide_content.py`
- `repo_slide_content.py` — every entry gained `tier`, `vendor`, `build_replicate`; 4 entries gained
  cross-checked facts
- `build_deck.py` — repo-slide layout updated for the new fields
- `build_deck_tenetcards.py` — new: 7 tenet cheat-sheet slides
- `build_capability_matrix_data.py` — new: builds the 7 capability-matrix datasets from
  `RAI_Synthesis.json` plus manual overrides; writes `capability_matrix_data.json`
- `build_deck_matrix.py` — new: renders the 7 capability-matrix slides as native tables
- `build_deck_synthesis.py` — wired tenet-cheat-sheet and capability-matrix slides into the deck
- `capability_matrix_data.json` — generated matrix data (7 tenets)
- `AFNI_Responsible_AI_Framework.pptx` — grew to 79 slides
- `qa_matrix.py` — new: overflow QA specifically for table-cell content

### 2026-08-24 — Tracker file setup, repo reorganization, and git migration
**Type:** New Build / Modification
**Ask:** Several requests in one sitting: (1) set up a strict, standing rule to log every future
ask/modification — same session or a new one — into a dated tracker file with date, heading, ask
type, what was done, and files changed. (2) Move everything under `D:\Afni` into
`D:\Afni\RAI_AFNI-main` (a new GitHub repo the user created) and push it, so the project is under
version control — but explicitly leaving the 2GB `references/` folder (23 downloaded third-party
repos) out, since that's just research material, not AFNI's own code. (3) Mid-task correction: don't
scatter helper scripts at the repo root — group generation helpers, QA scripts, and entry-point
scripts into their own folders to reduce noise. (4) Mid-task correction: stop over-engineering the
move into a heavier refactor than needed, and don't add unrequested content (an unrequested README
write-up was created and reverted).
**What was done:**
- Created this file (`MEMORY.md`) with the entry format above and backfilled prior milestones from
  file timestamps and conversation history.
- Saved two standing feedback memories in the assistant's cross-session auto-memory system (separate
  from this file): (a) always log AFNI-project work here, (b) never add unrequested files/content
  without explicit instruction.
- Fixed a latent bug: `build_capability_matrix_data.py` depended on a throwaway intermediate JSON
  file that had already been deleted; inlined the capability-selection data as a constant instead so
  the script is reproducible on its own.
- Reorganized the project into `data/` (JSON research data), `helpers/` (reusable generation
  modules), `qa/` (overflow/coverage checks), and `scripts/` (the two entry points,
  `build_deck.py`/`build_html.py`) — updating hardcoded absolute paths to be portable
  (`__file__`-relative) and adding a `sys.path` bootstrap in each entry point so the flat
  cross-imports between helper modules keep working.
- Verified both entry points and all three QA scripts still produce identical output (79 slides, 0
  layout issues, full 23-repo/7-tenet coverage) after each stage of the reorg.
- Initialized git in `RAI_AFNI-main`, added the `origin` remote, reconciled with the repo's existing
  initial README commit (identical content, no conflict), committed all 25 project files, and pushed
  to `main`. Left the `references/` folder at its original `D:\Afni\references` location, untouched
  and outside the repo.
**Files created / changed:**
- `MEMORY.md` — new, this file
- `.gitignore` — new (`__pycache__/`, `*.pyc`, `.claude/`)
- `helpers/build_capability_matrix_data.py` — inlined the selection data; fixed to `__file__`-relative paths
- `helpers/build_pptx.py`, `helpers/build_deck_matrix.py` — fixed to `__file__`-relative paths
- `scripts/build_deck.py`, `scripts/build_html.py` — fixed to `__file__`-relative paths + `sys.path` bootstrap
- `qa/qa_deck.py`, `qa/qa_matrix.py`, `qa/verify_deck.py` — fixed to `__file__`-relative paths (+ bootstrap for `verify_deck.py`)
- Moved (no content change): `build_deck_flow.py`, `build_deck_synthesis.py`, `build_deck_tenetcards.py`,
  `html_css.py`, `html_js.py`, `html_diagram.py`, `repo_slide_content.py`, `patch_repo_slides.py`,
  `patch_repo_slides_2.py` → `helpers/`; `RAI_Repo_Reports.json`, `RAI_Synthesis.json`,
  `capability_matrix_data.json` → `data/`
- Git: initialized `D:\Afni\RAI_AFNI-main` as a repo, remote `origin` = `https://github.com/saimuthiki/RAI_AFNI.git`,
  pushed commit `286eaa4` to `main`
