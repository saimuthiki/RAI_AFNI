# Our own use case, if the organisers don't hand us a better one

**Recommendation: _Margin Guardian_, an agentic revenue-assurance analyst for services businesses.**
It finds the money a services firm has already earned but never billed, proves each finding with
evidence from the contract, timesheets and invoices, and drafts the fix (change request, invoice
correction, staffing move) for a human to approve.

Everything below is a proposal for team review. Numbers marked `[EST]` are hypotheses to validate
in discovery with Evoke Finance and Delivery. They are not facts.

---

## 1. How we chose: scoring against what the judges said they reward

Criteria come from the webinar and deck (see `01-brief-analysis.md`): business impact, a real Evoke
stakeholder, room to challenge the brief, AI agents as teammates, working and deployed in a week,
and C-level appeal. Scores are 1–5.

| Candidate | Business impact (×3) | C-level pull (×2) | Universal (×2) | FDE/discovery fit (×2) | Demo "wow" with mock data (×2) | Buildable in 1 week (×2) | Differentiated (×1) | **Total /70** |
|---|---|---|---|---|---|---|---|---|
| **A. Margin Guardian**: contract → timesheet → invoice leakage finder with drafted fixes | 5 | 5 (CFO, CEO, COO, delivery) | 5 (any services, BPO, agency or legal firm) | 5 | 5 ("₹ found in 90 s") | 4 | 4 | **67** |
| B. Bench-to-Billable: predict roll-offs, match bench to open demand, plan upskilling | 4 | 4 (COO, CHRO) | 5 | 4 | 3 | 4 | 3 | **55** |
| C. Delivery Early-Warning Radar: predict at-risk projects from Jira, timesheet and email signals | 4 | 4 | 5 | 4 | 3 (predictions are hard to prove on mock data) | 3 | 3 | **53** |
| D. RFP-to-Win Copilot: RFP parsing, compliance matrix, past-win retrieval, draft response | 4 | 4 (CEO, sales) | 4 | 3 | 4 | 4 | 2 (crowded market) | **52** |
| E. Discovery Copilot: transcript → PRD → backlog → prototype (the FDE motion as a product) | 3 | 3 | 4 | 3 | 4 | 4 | 3 | **48** |

**Why A wins:** it is the only option where the outcome is **cash** a CFO can count during the
demo, the logic is auditable (not a black-box prediction), and the same engine sells to every
services client Evoke has. B and C become later modules of the same platform (see section 9),
which gives the pitch a credible roadmap rather than a one-off POC.

---

## 2. The problem

Services firms sell people's time under contracts: T&M, fixed price, milestone, FTE-based. Between
the contract, the timesheet, the resource plan and the invoice, money leaks quietly:

| # | Leak | What it looks like | Who feels it |
|---|---|---|---|
| L1 | Approved hours never invoiced | Timesheet approved; invoice register missing the line | Finance |
| L2 | Wrong rate | Billed at last year's rate after an escalation (COLA) clause kicked in; senior billed at a junior rate | Finance, account manager |
| L3 | Scope creep without a change request | Effort logged against tickets that map to no SOW deliverable | Delivery head |
| L4 | Cap overrun | T&M hours above the SOW cap: unbillable unless a CR is raised in time | Delivery, finance |
| L5 | Milestone accepted, invoice not raised | Client sign-off email exists; no invoice for weeks | Finance (cash flow) |
| L6 | Working without paper | SOW expired; team still logging billable time | Legal, finance |
| L7 | Fixed-price burn | Effort-to-date + estimate-to-complete > budget; nobody flagged it at 60% | COO, delivery |
| L8 | Allocation vs actuals | People allocated 100% billable but logging non-billable time, or shadow resources not on the rate card | Resource mgmt, COO |
| L9 | Missed contractual entitlements | Late-payment interest, minimum-billing commitments, travel pass-through not charged | Finance |

Today, finding these takes manual month-end reconciliation across 4–6 systems and spreadsheets.
It catches leaks late (if at all), after the window to raise a CR or rebill has closed.

**Why it's universal:** every professional-services, consulting, BPO, staffing, agency and legal
firm runs the contract → time → invoice chain. The hackathon's own "real business problem"
framing fits it exactly.

**The size of the prize (formula, to validate):**
`annual leakage = services revenue × leakage rate`. Industry commentary commonly puts
services revenue leakage in the low single-digit percent of revenue `[EST]`. So **every 1% of
revenue recovered goes almost entirely to operating margin**, because the work was already
delivered and paid for in salaries. For the pitch we'll compute Evoke's number from Finance's own
figures during discovery, and show conservative (0.5%), base (1%) and stretch (2%) cases.

---

## 3. The solution: Margin Guardian

**One sentence:** an always-on revenue-assurance analyst that reads contracts the way a lawyer
does, reconciles time and billing the way an auditor does, and drafts the recovery action the way
an account manager would. A human approves every action.

### User journey (this is also the demo)
1. **Connect** (mock data): drop in SOW PDFs and DOCX, a timesheet export, the resource
   allocation sheet, the invoice register and the Jira export.
2. **Contract Reader agent** extracts each contract's commercial DNA: rates by role, escalation
   clauses, caps, milestones, payment terms, scope deliverables. Every field carries a **citation**
   to the clause text. A human confirms low-confidence fields.
3. **Reconciliation engine** (deterministic Python rules, not an LLM) runs the L1–L9 checks
   across all accounts in seconds. It is fully auditable and testable.
4. **Investigator agent** turns each raw exception into a finding: amount at stake, an evidence
   chain (clause → timesheet rows → invoice gap), a confidence level, and the likely root cause.
5. **Action agent** drafts the fix: change-request email with the effort breakdown, invoice
   correction line, milestone invoice request, staffing adjustment. Each goes to an **approval
   queue**.
6. **Margin cockpit** shows leakage found, recovered, in progress and dismissed, by account and
   leak type, with a trend. A chat box ("Ask your margin") answers questions like "Why did the
   Acme account margin drop in Q3?" with citations.
7. **Learning loop:** a dismissed finding needs a reason, and that reason tunes the rule thresholds.
   This addresses false positives.

### The demo's "wow" moment
> Upload 3 accounts' data → about 90 seconds → "**₹X lakh at risk across 23 findings**" → click
> the biggest → the SOW clause 4.2 escalation text is highlighted next to the invoice lines billed
> at the old rate → "Draft correction" → approve → the recovered counter ticks up.

### Responsible AI by design (our differentiator)
Contracts and timesheets hold people's names, rates and client data. Every LLM call goes through
**Evoke's own RAI gateway** (`rai_platform/` in this repo): PII redaction, prompt-injection
screening on uploaded contracts, hallucination checks on extracted figures. The money maths is
deterministic code; the LLM never computes an amount. Judges see an in-house AI asset reused
rather than rebuilt.

---

## 4. Agents: in the product, and in the pod

| In the product | Job | Guardrail |
|---|---|---|
| Contract Reader | Extracts the commercial terms with clause citations | Must cite; low confidence → human confirm |
| Reconciler (code) | L1–L9 rules | Unit-tested, deterministic |
| Investigator | Writes up each finding: evidence chain, root cause, confidence | Can only reference data rows by ID |
| Action Drafter | CR, rebill or staffing drafts | Never sends; the approval queue does |
| Margin Q&A | Natural-language questions over findings | Answers carry citations, or it declines |

| In the pod (who builds it) | Human | Agent teammates |
|---|---|---|
| Customer owner (discovery, metric, pitch) | H1 | product-manager, business-strategist, sales-discovery-coach, cfo-advisor, executive-summary-generator |
| Architect / AI core | H2 | software-architect, ai-engineer, rag-pipeline-engineer, prompt-engineer, data-engineer |
| UI, quality and ship | H3 | frontend-developer, ui-designer, data-visualization-engineer, test-automation-engineer, reality-checker, devops-automator |

---

## 5. Architecture (lean, one week)

```
 Uploads (SOW pdf/docx, CSV exports)
      │
      ▼
 Ingestion ──► Contract Reader agent ──► contract_terms (+ citations)   ┐
      │              (via RAI gateway)                                  │
      ▼                                                                 ▼
 normalised tables: people, roles, rates, timesheets, allocations, invoices, tickets
      │
      ▼
 Reconciler (Python rules L1–L9) ──► exceptions ──► Investigator agent ──► findings
                                                          │
                                                          ▼
                                          Action Drafter ──► approval queue ──► recovered ledger
      │
      ▼
 FastAPI ──► Next.js cockpit (cards, drill-down evidence view, approvals, Ask-your-margin chat)
 Store: SQLite/Postgres · LLM: Claude API · Guardrails: rai_platform · Deploy: organiser VM / container
```

Synthetic data generator (day 1): 6 accounts, 120 people, 6 months of timesheets, with planted
leaks of every type, plus clean noise, so precision and recall are measurable. "We planted 31
leaks; it found 29, with 2 false positives, and here's why" is a strong judge answer.

---

## 6. Impact model (to fill with Evoke's numbers in discovery)

| Lever | Formula | Source to validate |
|---|---|---|
| Recovered revenue | Σ findings approved × amount | Finance: last 2 quarters' write-offs and credit notes |
| Faster cash | Days from milestone sign-off to invoice, before vs after × daily revenue × cost of capital | Finance: DSO, milestone log |
| Analyst time saved | Hours of month-end reconciliation per account × accounts × loaded cost | Finance ops and delivery managers |
| Margin protection | Fixed-price overruns flagged at 60% vs 90% burn × average overrun | Delivery: last 4 FP projects |
| New revenue line | Margin Guardian as a managed service for Evoke's clients (BPO, services) | Sales head |

---

## 7. Seven-day plan (maps to the 5 stages)

| Day | Stage | Output |
|---|---|---|
| 1 | Discover | Sessions with Finance controller and a delivery head; validate L1–L9 and rank by $; get real export formats; `/fde-discover` |
| 2 | Design | Spec, ADRs, data model, synthetic data generator, walking skeleton deployed; `/fde-design` |
| 3 | Build | Contract Reader + rules L1–L4 + findings list |
| 4 | Build | Investigator + Action Drafter + approval queue + cockpit; mid-week stakeholder demo |
| 5 | Build/Test | L5–L9, Ask-your-margin, RAI gateway wiring, E2E tests; `/fde-ship` |
| 6 | Deploy | Hardening, deploy, precision/recall report, backup video |
| 7 | Pitch | Impact model with Evoke numbers, deck, rehearsals x3; `/fde-pitch` |

**Not building this week:** live ERP or HRMS connectors (CSV import only), email sending
(drafts only), multi-currency, user management beyond a single demo login.

---

## 8. Risks and how we answer them

| Risk / judge question | Answer |
|---|---|
| "Our finance team already reconciles this." | Discovery will quantify how late and how manual it is. The pitch is about catching leaks before the billing window closes, not about replacing finance. |
| "LLMs hallucinate numbers." | They don't compute anything. The money is deterministic code; the LLM extracts terms with citations and explains findings; humans approve. |
| "Data sensitivity." | Runs inside Evoke's tenant; every prompt goes through the RAI gateway; PII is redacted before the model sees it. |
| "False positives will annoy account managers." | Confidence scores, dismiss-with-reason feedback, and a measured precision score on planted data. |
| "Is this just a dashboard?" | No. It ends in an **action** (CR or rebill draft) and a **recovered ₹** ledger, not a chart. |

## 9. Platform roadmap (why this isn't a one-off POC)

The same contract → effort → billing graph powers the runners-up as next modules:
**Bench-to-Billable** (allocation vs demand) → **Delivery Early-Warning** (burn and scope-creep
trends) → **Renewal & Upsell signals** (accounts with recurring CRs). Pitch line: *"Margin Guardian
is the first agent on Evoke's delivery-economics platform, and a service we can sell to every
client that bills for people's time."*

## 10. Discovery questions to take to the Evoke stakeholders

1. What was written off or credited in the last two quarters, and why? (This sizes the problem.)
2. How is month-end billing reconciliation done today: who, how many hours, which tools?
3. Which contract types dominate (T&M, FP, FTE, milestone), and which leak most in your experience?
4. How many days on average from milestone acceptance to invoice?
5. How are change requests detected today, and how many are raised late or never?
6. What exports can we get (timesheet tool, finance or ERP, PSA, Jira) and in what format?
7. Who would act on a finding: the account manager, delivery head or finance? Who approves?
8. What would make you trust a finding enough to act on it without re-checking?

## 11. Backup options if the team or stakeholders prefer another direction

- **B. Bench-to-Billable** if the stakeholder is HR or resourcing. Same pod structure; the "wow"
  is a ranked match list with an upskilling plan and bench-days saved.
- **C. Delivery Early-Warning** if the stakeholder is a delivery head. Reuse the synthetic data;
  the "wow" is a risk alert fired three weeks before a planted escalation.
- **D. RFP-to-Win** if the stakeholder is sales. The "wow" is a compliance matrix plus a first
  draft in 10 minutes from a 60-page RFP.
