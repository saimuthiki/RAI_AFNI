# AFNI Responsible AI

Two halves. The **analysis** established what AFNI should build and why; the
**platform** is the thing being built.

```
knowledge/       distilled analysis - read here first, not the PPTX
rai_platform/    the unified Responsible AI gateway (in progress)
analysis/        the pipeline that produces the deck and the HTML artifact
deliverables/    the client-facing outputs
references/      23 third-party repos read at source level for the analysis
```

## Start here

`knowledge/INDEX.md`. One node costs ~600-1,500 tokens to read; extracting the
same conclusions from the 80-slide deck costs ~35,000. The deck is a rendered
deliverable, not a source of truth.

| Node | Answers |
|---|---|
| `knowledge/decisions.md` | the locked architecture calls and the two rules that never bend |
| `knowledge/tenets.md` | per-tenet stack, and the single recommendation per tenet |
| `knowledge/methodology.md` | how each of the 22 contributing tools implements its check |
| `knowledge/frameworks.md` | the 23 tools with adopt/skip verdicts |
| `knowledge/roadmap.md` | the 90-day plan of record |
| `knowledge/open-questions.md` | what is genuinely unresolved |

## rai_platform/ - the gateway

One shared internal gateway. Every AFNI AI application calls it; no project
wires its own detectors.

```
afni_rai/contract/   OpenGuardrails v0.8 GuardEvent / Verdict - the fixed boundary
afni_rai/cascade/    the stage engine: Stage 1 -> 2 -> 3, short-circuit, fail-closed
afni_rai/rails/      one adapter per tool - the only place a vendor API is touched
afni_rai/tenets/     one package per tenet
afni_rai/policy/     per-tenant / per-project thresholds
afni_rai/gateway/    FastAPI app
afni_rai/audit/      verdict store + OpenTelemetry
afni_rai/registry/   capability -> rail map, and the coverage report
ci/                  the offline tier: fast / medium / slow suites
corpus/              the versioned attack corpus - the durable asset
docs/                the playbook
```

The cascade is the cost argument: free deterministic checks on 100% of traffic,
a paid call only on the thin slice that survives. Two invariants live in the
engine, not in each rail - **fail closed** on client-facing traffic, and any
check that could not run is reported `unjudged`, never silently passed.

Named `rai_platform` rather than `platform` on purpose: a top-level `platform/`
package shadows Python's stdlib `platform` module.

### Run the tests

```bash
python3 rai_platform/tests/test_foundation.py
```

No dependencies - stdlib `unittest`.

## analysis/ - the deck and HTML pipeline

```bash
python3 analysis/scripts/build_deck.py     # -> deliverables/*.pptx  (80 slides)
python3 analysis/scripts/build_html.py     # -> deliverables/*.html
python3 analysis/qa/qa_deck.py             # layout / overflow check
python3 analysis/qa/qa_matrix.py           # table-cell overflow check
python3 analysis/qa/verify_deck.py         # coverage: 23 repos, 7 tenets
```

Requires `python-pptx`. Both builders are deterministic - rebuilding from
unchanged inputs produces byte-identical output, which is how a drift is caught.

`analysis/data/` is the authoritative research corpus:

| File | Holds |
|---|---|
| `RAI_Repo_Reports.json` | 23 source-level deep-dive reports |
| `RAI_Synthesis.json` | 142-item master checklist, tenet matrix, feasibility, roadmap |
| `capability_matrix_data.json` | 7 tenets x up to 22 tools, capability by capability |
| `tenet_methodology_facts.json` | 108 repo-tenet mechanism facts, each with `file:line` evidence |

## Context tooling

`graft` and `graphify` are wired in (`.claude/`, `.mcp.json`). Both build local
caches that are gitignored; each developer runs their own:

```bash
graft build          # code graph, $0, no API key
graphify extract . --code-only
```

Query the graph instead of re-reading files - `graft ask "<question>" --source`.

## references/

The 23 analysed repos, kept while the platform is built so rails can be written
against real source. Licences: 22 MIT/Apache-2.0, 1 AGPL-3.0 (Deepchecks - see
`knowledge/open-questions.md`).
