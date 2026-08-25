# AFNI Responsible AI — Knowledge Layer

Hand-authored, greppable distillation of the Phase-0 analysis. **Read from here, not
from the PPTX.**

## Why this exists

The analysis behind AFNI's Responsible AI platform lives in three places an agent
cannot read cheaply: a 79-slide `.pptx` (~35,000 tokens to extract), a 275 KB HTML
artifact, and ~530 KB of JSON. Answering "which tool did we pick for Privacy, and
why?" used to mean re-parsing all of it, every session.

These nodes hold the conclusions in prose, with pointers back to the authoritative
source for anything deeper. Same idea as `graft/` and `graphify-out/`, but for the
research corpus rather than the code — those two tools index code and structured
files; nothing indexes a PowerPoint.

| Layer | Covers | Cost to query | Committed? |
|---|---|---|---|
| `knowledge/` (this) | the analysis, decisions, rationale | ~1–2k tokens | yes — hand-authored |
| `graft/` | AFNI Python + all 23 `references/` repos | ~600–2k tokens | no — regenerable cache |
| `graphify-out/` | AFNI code + `data/*.json` as a traversable graph | ~1.4k tokens | no — regenerable cache |

## Nodes

| Node | Read it when you need… |
|---|---|
| [decisions.md](decisions.md) | the locked architecture calls and the two non-negotiable rules |
| [frameworks.md](frameworks.md) | the 23 tools: verdict, role, tier, cost, licence, where the source is |
| [tenets.md](tenets.md) | per-tenet runtime stack, open-source vs cloud pick, and the principle |
| [methodology.md](methodology.md) | per tenet, HOW each tool implements its check - mechanism, cost, latency class, cascade stage |
| [infosys-vs-nemo.md](infosys-vs-nemo.md) | why NeMo is the backbone and what to carry over from Infosys |
| [request-flow.md](request-flow.md) | the live request path and the four mitigation branches |
| [dev-vs-test-loop.md](dev-vs-test-loop.md) | the offline red-team/CI loop and its four hand-offs |
| [roadmap.md](roadmap.md) | the 90-day phase plan, 26 concrete actions |
| [open-questions.md](open-questions.md) | legal, vendor-risk and unresolved items blocking Phase 1 |

## Authoritative sources (go here only when a node is not enough)

| Source | Holds |
|---|---|
| `data/RAI_Repo_Reports.json` | 23 source-level deep-dive reports (features, limits, prerequisites, fit) |
| `data/RAI_Synthesis.json` | 142-item master checklist, tenet matrix, feasibility, architecture, roadmap |
| `data/capability_matrix_data.json` | 7 tenets × up to 22 tools, capability-by-capability |
| `data/tenet_methodology_facts.json` | per-repo mechanism facts with `file:line` / model-id evidence |
| `helpers/repo_slide_content.py` | plain-English per-tool copy (`REPO_SLIDES`), incl. build-vs-buy |
| `Responsible_AI_Framework_Brief_for_PPT.md` | the original client brief and meeting transcript |
| `AFNI_Responsible_AI_Framework.pptx` | the client deliverable — rendered output, not a source of truth |
| `references/<folder>/` | the actual third-party source, indexed by graft |

## Status

Phase 0 (analysis) is complete. The unified platform is **not built yet** — nothing
in this repo implements a gateway. `roadmap.md` is the plan of record; design
decisions still open are in `open-questions.md`.
