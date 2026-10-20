# Discovery kit: running the stakeholder session like an FDE

Judges will ask "what did you learn, what did you assume, what did you challenge?". This kit
makes sure we have crisp answers. `/fde-intake` and `/fde-discover` use it.

## Before the call (30 min prep)
- Send a 5-question async questionnaire (`/to-questionnaire`) 24 hours ahead: volumes, systems,
  current cost, who else feels the pain, and what "great" looks like.
- Bring the top 3 assumptions we most need to kill or confirm (from `work/assumptions.md`).
- Roles: H1 leads the conversation, H2 writes verbatim quotes, H3 tracks data, systems and integrations.
- Ask permission to record. The transcript feeds `meeting-analyzer`.

## The 45-minute interview arc

| Min | Goal | Questions (pick and adapt) |
|---|---|---|
| 0–5 | Frame | "We'd like to understand the problem before proposing anything. What made you raise this now?" |
| 5–15 | **Pain and cost** | "Walk me through the last time this went wrong." · "Who noticed, and how late?" · "What did it cost: hours, money, a client, a deal?" · "How often does that happen per month?" |
| 15–25 | **Current process** | "Show me how it's done today, screen by screen." · "Where does work wait?" · "Which spreadsheets exist that shouldn't?" · "Who has to approve what?" |
| 25–32 | **Data and systems** | "Where does the data live, who owns it, how fresh is it?" · "What can't we touch?" · "What does the mock data need to look like to be believable?" |
| 32–38 | **Success** | "Six months from now this is solved. What number moved?" · "What would make you stop using it?" · "Who else has to say yes?" |
| 38–43 | **Challenge the brief** | "If we could only fix one thing, which?" · "Is X the problem or a symptom of Y?" · "What have you already tried, and why did it stall?" |
| 43–45 | **Close** | Play back the problem in one sentence and the metric. "Did we get it right?" Agree the next touchpoint (mid-week demo) |

**Techniques:** ask for a specific past instance, not "usually" · "show me" beats "tell me" ·
5 whys on every pain point · stay silent after a question · write numbers down exactly and confirm units.

## Templates

**Assumption log** (`work/assumptions.md`)

| ID | We believe… | Evidence so far | Risk if wrong (H/M/L) | How we validate | Status |
|---|---|---|---|---|---|
| A1 | | | | | open / validated / killed |

**Value tree** (`work/value-tree.md`)

```
Business outcome (what the CXO reports on)     e.g. operating margin, revenue, risk exposure
 └─ Operational driver                          e.g. unbilled effort, cycle time, bench days
     └─ Lever our product pulls                 e.g. auto-detect and draft the change request
         └─ Metric: baseline → target           e.g. 9 days → 1 day; ₹X recovered per month
             └─ How we show it live in the demo
```

**Challenge-the-brief statement** (`work/01b-reframe.md`)

> You asked for **X**. In discovery we heard **Y** ("quote", "quote", plus data point). Solving X
> alone leaves **Z** unsolved. We propose **W**, which moves **<metric>** from **a** to **b**. We
> will deliberately not build **V** this week.

**Playback message** (to the stakeholder, same day)

> Thanks for today. Our understanding: <one-sentence problem>. Success = <metric, baseline → target>.
> We'll focus on <scope>, not <out of scope>. Mid-week, we'll show a running version on <date>.
> Anything we got wrong?

## Red flags to probe

- The stakeholder describes a solution ("we need a dashboard") rather than a problem. Ask what
  decision the dashboard would change.
- No baseline number exists. Measuring the baseline becomes part of our deliverable.
- The pain belongs to someone not in the room. Ask for 15 minutes with that person.
- The data is "somewhere in emails". Plan for unstructured ingestion plus extraction.
