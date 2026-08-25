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

### 2026-08-24 (cont'd) — Pushed references/ too, after fixing broken Git-LFS pointer stubs
**Type:** Modification / Bug Fix
**Ask:** Push the `references/` folder (previously left out for size) into the same repo, as-is.
**What was done:**
- Moved `references/` (2GB, 23 third-party repos) into `RAI_AFNI-main` and committed it.
- First two push attempts failed: (1) local git-lfs tried to upload real content for files that
  were actually just Git-LFS pointer stubs with no backing data (the original downloads never
  pulled real LFS content for `evals-main` and part of `Infosys-Responsible-AI-Toolkit-master`);
  disabling the local LFS pre-push hook didn't help because (2) GitHub's server itself
  independently detects and rejects pointer-format blobs with no real object behind them.
- Identified and removed all 686 broken pointer-stub files (671 in `evals-main`, 15 in
  `Infosys-Responsible-AI-Toolkit-master`) — they carried zero real content, just placeholder text.
- Since deleting them in a *later* commit still left them in history (and GitHub scans the whole
  push, not just the final tree), reset back to the last successfully-pushed commit and re-committed
  `references/` fresh in one clean commit that never included the stub files.
- Pushed successfully (commit `972d4839`). Three legitimate large files (79-93MB Infosys model
  checkpoints) pushed fine with only GitHub's advisory 50MB-recommended-max warning, well under its
  100MB hard block.
**Files created / changed:**
- `references/` — added (23 repos, minus 686 broken LFS pointer stub files)
- Git: commit `972d4839` pushed to `main` (superseding two earlier local-only commits that were
  reset before ever reaching the remote)

### 2026-08-24 (cont'd) — Context layer: graft + graphify wired in, and a hand-authored knowledge/ layer
**Type:** New Build / Enhancement
**Ask:** Three things in one sitting: (1) adopt the methodology from `nanonets/graft` to cut token
consumption and make Claude Code usage more efficient on this project; (2) also adopt
`Graphify-Labs/graphify` alongside it; (3) push the current state to the repo once both are
integrated. Also a correction to record: this repo is **not** a document-generation pipeline — it is
the Phase-0 analysis step toward a unified Responsible AI governance platform for AFNI, and the PPTX
and HTML are the evidence base for that platform, not the product.
**What was done:**
- Read both tools at source level and assessed them against this repo rather than assuming the
  marketing numbers. Measured on a throwaway copy: `graft map` 597 tokens vs 54,224 to read the
  files (99% saved), `graft ask --source` 1,982 vs 22,791 (91%); `graphify benchmark` reported 5.2x
  fewer tokens per query.
- Found and recorded the honest limitation: **graft indexes code only**, so it skipped the `.pptx`,
  the `.html`, the JSON and the markdown — i.e. everything where this project's actual knowledge
  lives. graphify closes most of that gap (it covers `.md`, `.html`, `.json`), but nothing indexes a
  PowerPoint. That is what the `knowledge/` layer below is for.
- Wired graft into Claude Code (`graft init --agents claude`): statusline, hooks, skill file and the
  MCP server registration. Built the full structural graph — 120,249 nodes / 282,953 edges over
  12,828 files, deliberately including all 23 `references/` repos, since those are exactly the
  sources we will be reading while building the platform. Verified with a real query against
  LLM Guard's `Vault` class: answer returned with source inlined, 66% fewer tokens than reading it.
- Installed graphify and mirrored its skill from the machine-wide install into the repo's `.claude/`
  so the wiring is committed and teammates get it. Built the graph with the free local AST pass
  (`extract --code-only` + `cluster-only --no-label`): 113 nodes, 332 edges, 10 communities. The
  semantic pass over docs is still pending — it needs either an API key or subagent dispatch.
- Added `.graphifyignore` to keep graphify scoped to AFNI's own material (a semantic pass over the
  ~12,800 `references/` files would be expensive), and an `.ignore` file so the gitignored graph
  outputs stay greppable by ripgrep.
- Rewrote `.gitignore`: `.claude/` was ignoring the very wiring both tools expect to be committed,
  so it now commits `.claude/settings.json`, `.claude/helpers/` and `.claude/skills/` while ignoring
  `.claude/settings.local.json` and the two regenerable caches (`graft/`, `graphify-out/`).
- Built `knowledge/` — 9 hand-authored markdown nodes (~6,200 words) distilling the whole Phase-0
  analysis: locked decisions, the 23 frameworks with verdicts, the 7 tenets with per-tenet stacks,
  the Infosys-vs-NeMo call, the request flow, the dev/test loop, the 90-day roadmap, and an honest
  open-questions list. Factual tables were generated from `data/*.json` and `REPO_SLIDES` rather
  than typed by hand. Reading one node costs ~600–1,500 tokens against ~35,000 to extract the deck.
- Recorded in `knowledge/open-questions.md` that the deck's "August 2026" framing for the EU AI Act
  and the Guardrails AI Hub deprecation is now past-tense and needs correcting before reuse with
  the client.
**Files created / changed:**
- `.claude/settings.json`, `.claude/helpers/graft-hooks.cjs`, `.claude/helpers/graft-statusline.cjs`,
  `.claude/skills/graft/SKILL.md` — new, written by `graft init`
- `.claude/skills/graphify/` (SKILL.md + 8 reference docs) — new, mirrored from the graphify install
- `.mcp.json` — new, registers the graft MCP server
- `.gitignore` — rewritten to commit the wiring and ignore the caches
- `.graphifyignore`, `.ignore` — new
- `knowledge/INDEX.md`, `decisions.md`, `frameworks.md`, `tenets.md`, `infosys-vs-nemo.md`,
  `request-flow.md`, `dev-vs-test-loop.md`, `roadmap.md`, `open-questions.md` — new
- `MEMORY.md` — this entry
- Not committed (regenerable caches, gitignored): `graft/` (722 MB), `graphify-out/`

### 2026-08-25 — Per-tenet methodology analysis: 7 new slides from a source-level read
**Type:** New Build
**Ask:** For each of the 7 tenets, a slide holding a table of every reference repository that
deals with that tenet, detailing *how* each one actually implements its check — module-based,
keyword-based, classifier-based, model-level, prompt-template/AI-call, cloud-based, or paid — plus
latency, and whether the tool targets chatbot/LLM text or classical classification/prediction
models. Purpose: AFNI's platform will run a **cost- and latency-ordered cascade** — free
deterministic checks on 100% of traffic, flagging immediately, and escalating only the surviving
slice to paid or higher-latency checks. Use the existing PPT as the starting reference, plan in
ultra plan mode first, and spawn multiple subagents. Deliver an updated PPTX plus a bundle/patch,
since this session cannot push.
**What was done:**
- Planned in plan mode and settled four decisions with the user before building: the full 7-attribute
  column set; broad repo scope per tenet (every repo credited with ≥1 checklist item, from
  `master_aspect_list`); a new deck section rather than replacing the capability matrices; and
  latency as a mechanism-derived tier, explicitly labelled on-slide as an estimate rather than a
  benchmark (measuring 23 frameworks against live models was not feasible and was not faked).
- Fanned out 22 subagents, one per repo appearing in the master checklist, each reading the **actual
  source** under `references/` via graft rather than the existing summaries. Produced 108 repo-tenet
  fact rows, every one carrying an `evidence` field naming the `file:line`, model id or dependency
  it came from. Hand-verified three claims against source afterwards.
- Derived `latency` and `stage` centrally rather than per fact, so they stay consistent across all
  seven tenets. Two corrections were made to the derivation during the build: latency became a
  **range** across a row's mechanisms (so a mixed row reads "Very low-Low" instead of hiding half of
  itself), and stage became the **earliest** point a tool can contribute, from its cheapest
  mechanism — the first rule (slowest component wins) wrongly left Security with no Stage 1 at all,
  because it collapsed LLM Guard's deterministic secret/unicode scanning into its classifier's tier.
- Added a fifth stage, **Delegates**, after finding an internally contradictory row: Guardrails AI
  was ranked Stage 1 for Privacy while its own description said "NO in-repo PII code". Tools that
  supply a contract or taxonomy but no detector of their own cannot occupy a cascade stage.
- Recorded ten corrections to the existing deck's claims that the source read turned up — see
  `knowledge/methodology.md`. The most consequential: hai-guardrails' toxicity/profanity/bias guards
  are LLM-judge prompts needing a paid API (not wordlists, so Stage 3 not Stage 1); Giskard v3 is
  LLM/agent-only with its tabular-ML support gone since v2; garak's shields.Up/Down detectors ship
  with no matching probe, so the Phase-3 "point shields at AFNI's gateway" action needs AFNI to
  write that probe; and OpenAI Evals' sample data is absent locally because it was all Git-LFS stubs
  removed when `references/` was first committed.
- **Mistake made and corrected:** I treated the reference repos' own `.claude/` folders as accidental
  noise from the earlier `.gitignore` change and removed 26 of them in a merge. Commit `6d8da14`
  tracks them deliberately, as part of the reference material. Restored, and the ignore rule I added
  was dropped with a note in `.gitignore` so it is not repeated.
- Verified: 87 slides (PAGE counter and actual count agree), 16 tables with 0 overflow cells, 0 deck
  layout issues, all 23 repos and 7 tenets still present, `guardrail_atlas.html` byte-identical
  (the HTML path is untouched), and the data build byte-identical on re-run.
**Files created / changed:**
- `data/tenet_methodology_facts.json` — new: 22 repos × 108 tenet rows of source-level facts with evidence
- `data/tenet_methodology_data.json` — new: generated tables, latency/stage derived
- `helpers/build_tenet_methodology_data.py` — new: the derivation, documented in its docstring
- `helpers/build_deck_methodology.py` — new: renders the 7 slides, sized against the `qa_matrix.py` estimator
- `helpers/build_deck_synthesis.py` — +6 lines: divider + call, after the capability matrices
- `AFNI_Responsible_AI_Framework.pptx` — grew to 87 slides (new slides 61-68)
- `knowledge/methodology.md` — new: the same tables in markdown, generated from the data so it cannot drift
- `knowledge/INDEX.md`, `knowledge/tenets.md` — +links to the new node
- `.gitignore` — note added about the reference repos' tracked `.claude/` folders

### 2026-08-25 (cont'd) — Merged the two conflicting per-tenet recommendation sets
**Type:** Modification / Bug Fix
**Ask:** The deck carried two separate sets of per-tenet slides that both said "AFNI
RECOMMENDATION" and did not agree — one set starting around slide 36 (the tenet cheat sheets) and
another around slide 43 (the tenet recommendation slides). Merge the two sets into one, carrying any
information present in one but not the other, and resolve the recommendation ambiguity so the client
sees a single answer per tenet. Also: clean up unnecessary files before the unified-tool build, keep
the updated PPTX in the repo, update this tracker, push, and merge to `main`.
**What was done:**
- Diagnosed the root cause rather than just picking a winner. The two sets were answering **different
  questions under the same heading**: the recommendation slides answered "which of the 23 reviewed
  repos do we adopt" (so their badges were repo names), while the cheat sheets answered "what does
  the runtime stack look like", which mixes repos with the *engines inside them* and the *cloud
  services beside them*. For Privacy that produced "Presidio + Azure PII" on one slide and
  "LLM Guard + NeMo Guardrails + garak" on another — the same stack at two different altitudes, but
  a client cannot tell that.
- Built one merged slide per tenet (`helpers/build_deck_tenetmerged.py`) that states the
  recommendation in the three layers it actually has, each explicitly labelled — **ADOPT** (of the
  23), **ENGINE UNDER IT**, **CLOUD SECOND OPINION** — plus **WHERE IT RUNS**, which ties each pick
  to its cascade stage from the methodology analysis. A "RECONCILED" note on every slide says what
  the two earlier slides disagreed about and why the merged answer is what it is, so the ambiguity
  cannot silently reappear.
- Settled the two genuine disagreements on evidence, not preference:
  - **Accountability** — cheat sheet said DeepTeam, recommendation slide said Promptfoo. Promptfoo
    wins: 6 framework mappings (OWASP LLM, NIST AI RMF, MITRE ATLAS, EU AI Act, ISO 42001, GDPR) vs
    DeepTeam's 5, and PyRIT ships no report generator at all. DeepTeam kept as a secondary source.
  - **Hallucination** — the cheat sheet put Giskard in the runtime picture; Giskard v3 is LLM-judge
    based and needs a paid API, so it is CI-only, never inline.
  - **Content Safety** differed only by omission; the union is correct (LLM Guard local pass, NeMo
    routing, Promptfoo CI corpus, Azure audit trail).
- Nothing was dropped: the long `combination_rationale`, the full cloud/paid option list and Sai's
  prior-experience note all moved to each slide's **speaker notes** rather than being cut, since the
  merged slide could not hold them at a readable size.
- Deck went 87 → 80 slides (14 slides became 7). `build_deck_tenetcards.py` is now a **data-only**
  module — the merged renderer reads its `TENET_CARDS` prose, so there is no second copy of any text.
- Cleanup, scoped deliberately: removed the two spent one-time migration scripts
  (`patch_repo_slides.py`, `patch_repo_slides_2.py`, 0 references), the orphaned
  `add_tenet_recommendation_slide` (81 lines), the retired cheat-sheet renderers, and 8 imports the
  removals left unused (AST-verified, not guessed). **`helpers/` itself was NOT deleted** — it is the
  entire deck and HTML generation pipeline; removing it would destroy the ability to rebuild either
  deliverable. Flagged for the user rather than acted on unilaterally.
- Verified: 80 slides (counter and actual agree), 16 tables with 0 overflow cells, 0 deck layout
  issues, all 23 repos and 7 tenets still present, `guardrail_atlas.html` byte-identical, and no
  unused imports remaining in the touched modules.
**Files created / changed:**
- `helpers/build_deck_tenetmerged.py` — new: the merged renderer plus the `RECONCILED` dataset
- `helpers/build_deck_tenetcards.py` — reduced to data only (179 → 136 lines); renderers retired
- `helpers/build_deck_synthesis.py` — `add_tenet_recommendation_slide` removed; wiring points at the
  merged set; unused imports cleaned
- `helpers/patch_repo_slides.py`, `helpers/patch_repo_slides_2.py` — deleted (spent migrations)
- `AFNI_Responsible_AI_Framework.pptx` — 87 → 80 slides, merged tenet section at slides 39-45
- `knowledge/tenets.md` — new section documenting the reconciliation and the two settled conflicts

---

## 2026-08-25 — FastAPI gateway, operator console, and the README

**What was asked:** build the gateway and a frontend UI covering all tenets with
streaming; report per tenet which repos are used and in which phase, in the
README; add Swagger with sample tenet payloads; implement a multi-key provider
fallback chain; and write the README about the *tool* — folder structure,
tenet↔framework↔phase mapping, methodology, and a fresh-user guide with
flowcharts.

**Shipped (commit `baa4cb29`, pushed to `claude/raiafni-repo-overview-grhjtb`):**

- **Gateway** — 7 routes. `/v1/guard`, `/v1/guard/stream` (SSE, one frame per
  cascade stage), `/v1/coverage`, `/v1/phases`, `/v1/rails`, `/healthz`, `/docs`.
  `Cascade.evaluate_iter()` became a real generator so streaming is incremental;
  `evaluate()` is now a driver over it, with a test comparing both paths.
- **Provider chain** — ordered across providers and keys, advancing only on
  401/403/408/429/5xx/timeout/connect-error. A low score never falls through. A
  400/404 is terminal. Exhaustion → `unjudged` → fails closed. Logs the key
  *index*, never the key. Verified over a real socket against a local stub
  (429 → next key → 200).
- **Console** — four views, vanilla ES modules, no build step. Mounted at `/`
  **after** the API routes; a mount at `/` matches everything, so registered
  earlier it would shadow `/v1` and `/docs`. Same-origin is deliberate: the
  alternative is CORS, and a guardrail gateway sending
  `Access-Control-Allow-Origin` is one any page can drive with the operator's
  session. A test pins both halves and asserts no CORS header is ever sent.
- **README** — 986 lines, 8 Mermaid flowcharts (whole cascade + one per tenet),
  folder-by-folder responsibility, the full rail→repo→phase table, methodology,
  fresh-user guide, and honest limits.

**Four defects found by running it, not by reading it:**

1. **`attack-corpus-repeat` could not name itself.** `corpus.py` always defined
   its `RailAttribution`, but the package re-exported it only as
   `RAIL_ATTRIBUTION` — a name no loader reads. So a block from that rail
   arrived with no repo, no mechanism and no confidence kind, which defeats the
   one thing an explanation exists for. Now keyed off the mounted rails, plus a
   test asserting **no** mounted rail lacks an attribution. Verified failing
   against the reverted export.
2. **An OpenAI key was not detected.** Every secret pattern was a faithful port,
   and none of the reviewed repos carries an `sk-proj-` format — garak's dora
   list, PyRIT's credential scorer and hai-guardrails' vendor list all predate
   it. So the rail caught a pasted Google AI Studio key (`AIza…`) and let an
   OpenAI project key through, while this platform's own judge chain is
   configured against both providers. Added six LLM-provider prefixes as
   **declared AFNI additions**, disclosed in the attribution so a false positive
   is filed against the right author. 10 tests, including the benign strings a
   short prefix could trip (`hf_hub_download`, `sk-learn`, `sklearn`) and a
   zero-entropy placeholder.
   *Lesson: a faithful port is the right default and is not a completeness
   guarantee.*
3. **The reported entity was uninformative.** `entity` took the last segment of
   the category, which works for `security.secret_leak.api_key` and degrades to
   `us` for `privacy.pii.national_id.us` — and `in` for a tax id reads as an
   English preposition. A two-letter tail now keeps its parent
   (`national_id.us`), restricted to two so `health_id.dea` stays `dea`. A test
   walks every category the platform emits and rejects any yielding under three
   characters.
4. **No favicon**, so the browser's unprompted request logged a 404. Cosmetic
   anywhere else; in a governance console an operator cannot tell a spurious red
   error from a real one. Inline data URI.

**Two limits discovered and now documented rather than hidden:**

- **On a fresh install most blocks are fail-closed blocks, not detections.** The
  same SSN is *allowed* on internal traffic and *blocked* on client-facing
  traffic with identical findings — the block comes from Presidio being absent,
  not from the SSN. The README leads with this.
- **No Stage-1 rail blocks on a prompt-injection pattern, by design** (PyRIT
  documents a high FP rate, so a regex hit buys a second opinion). Consequence:
  a textbook injection plus a DAN jailbreak yields four HIGH findings and is
  **allowed** on internal traffic when the classifier weights are absent. Stage 1
  alone is a detector for injection, not a control against it.

**Also:** removed three empty placeholder packages (`audit/`, `policy/`,
`rails/`) that the old README described as holding the rails and policy code.
They never did — that code lives in `tenets/` and `tenets/accountability/`. A
structure section describing directories that do not exist is worse than none.

**Verification:** 726 tests pass. Server started and every route curled; SSE
frames timestamped; the console driven in headless Chromium against the live
gateway — four views render real data, zero console errors, no horizontal
overflow. The gateway agent independently confirmed no matched value reaches the
wire (it closed two leaks the brief did not name: the verdict's optional
`Finding.subject`, and pydantic's 422 `input` field echoing the whole payload).

**Still unverified, and stated as such everywhere:** no live provider call is
possible from this container — `api.openai.com` and
`generativelanguage.googleapis.com` are both blocked by the proxy while
`pypi.org` returns 200. `HTTP=000` is a connection failure, not an auth
rejection, so the user's keys remain untested from here and the model ids stay
marked `UNVERIFIED DEFAULT`.
