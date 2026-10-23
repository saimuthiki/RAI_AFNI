# Kickoff (22 Oct), the guidelines PDF, and our problem (#2, Halcyon Logistics)

Sources:
- the kickoff transcript (Kezia Rani Singh, organiser; Swarna Vaitla, sponsor side)
- `00-kickoff-guidelines.pdf` (14 slides)
- the Problem 2 briefing call with Swarna
- `00-problem-2-halcyon.docx`

## 1. The PDF, slide by slide

- **Slide 1, cover:** "FDE Mode ON. Kickoff: guidelines & evaluation criteria", Thursday 22 Oct 2026.
- **Slide 2, theme:** "Think like a Forward Deployed Engineer. Deliver like one."
  - **Get close to the problem:** do discovery directly with the stakeholder.
  - **Humans + AI agents:** put AI agents to work across every skill, whatever your role.
  - **Deliver an outcome:** an AI-powered solution with a measurable business result.
- **Slide 3, timeline:**
  - Discover 22–23 Oct.
  - Design after discovery.
  - Build until 28 Oct.
  - Test & Deploy, wrapped up by 28 Oct.
  - Demo & Pitch in the first week of November.
- **Slide 4, three things to do on 22 Oct:**
  - Pick the problem chit, 3:30–5:30 pm.
  - Submit discovery questions by end of day.
  - Share infra requirements by end of day.
- **Slide 5, discovery happens in two rounds:**
  - Round 1: questions in on 22 Oct, answers back 23 Oct EOD.
  - Round 2 (optional): follow-up questions by Friday 23 Oct, answers back Monday 26 Oct.
- **Slide 6, infra and AI tools:**
  - **Everyone:** send requirements by 22 Oct EOD on the L&D form; infra is provided by Mon 26 Oct.
  - **CSC team members:** VM/VDI access comes from the IT team.
  - **AI coding tools:** get your account head's approval by email and send it to the Learning team.
- **Slide 7, two levels of evaluation:**
  - **L1 Qualification (Nov week 1):** a must-have checklist on the working solution. Miss any item and the team doesn't reach L2.
  - **L2 Presentation (Nov week 1):** live demo plus PPT, scored out of 100. 30 minutes: 20 min demo and 10 min Q&A.
- **Slide 8, L1 must-have checklist:**
  - **Discovery:** questions asked and answers applied.
  - **Agent pipeline:** agents set up across roles, not just code assist.
  - **AI services:** AI used inside the solution itself.
  - **Live app demo:** a working, deployed prototype.
  - **UI:** a usable front end for the flow.
  - **Backend:** working APIs, data and logic.
  - **Testing:** evidence the solution was tested.
  - **Eliminated if:** no working prototype, no AI-usage evidence, a missed deadline, a major deviation from the problem statement, or non-compliant behaviour.
- **Slide 9, the presentation must cover these, in this order:**
  1. Discovery insights and the key problem
  2. Solution approach and architecture diagram
  3. AI agents used
  4. Quality, validation and security
  5. Metrics and business impact
  6. Future scope
  7. Live demo, running on AI end to end. It can go anywhere in the order.
  - At least one POD member presents.
- **Slide 10, L2 scoring (100 points):**
  - **Solution Design & Functional Completeness, 25** (demo + PPT): core workflows run end to end on a well-designed, tested, secure build.
  - **Technical Creativity, Problem-Solving & UX, 15** (live demo): smart trade-offs and an intuitive flow. "Runs on AI, or still depends on individuals?"
  - **AI-First Delivery, 30** (PPT): an agent pipeline from business analysis to user adoption, not just AI writing code. **This is the biggest single block.**
  - **Problem Fit & Business Outcome, 20** (PPT): think like a consultant. Frame the problem, propose the fix, prove the ROI.
  - **Communication, Impact & Future Scope, 10** (PPT): clear story, confident Q&A, next steps.
- **Slide 11, the FDE lens:**
  - See (understand the system) 15%
  - Deconstruct (name the real problem) 20%
  - Reframe (design the outcome) 20%
  - Build (a working slice) 20%
  - Prove (show the evidence) 20%
  - Customer story 5%
- **Slide 12, deliverables:**
  - Discovery questions: 22/23 Oct EOD.
  - **Source code pushed to the designated GitHub repo by 29 Oct.**
  - **Working solution deployed and running by 29 Oct.**
  - **AI usage logs (agent logs) in the repo by 29 Oct.**
  - Deck on presentation day.
- **Slide 13, SPOCs:**
  - L&D team: AI queries, discovery and the event.
  - Satya Kolli and the IT team: infra, VDI and VM access, through the Teams group, with Learning in the loop.
- **Slide 14:** questions; pick up chits 3:30–5:30 pm.

## 2. Kickoff transcript: what matters beyond the slides

- **Three ideas that drive all the scoring:**
  - get close to the problem
  - humans plus AI agents across *every* role (dev, tester, BA, designer), not only coding
  - an AI-powered solution with measurable business results
- **Discovery channel:**
  - Use the L&D question form only, one question per row (the `Hackathon_Discovery_Log.xlsx` format).
  - Turnaround is up to 24 hours, because there are 51 teams.
  - Questions can be asked **throughout** the hackathon, not only in the two rounds.
  - Don't contact stakeholders directly; they will redirect you to L&D.
- **Swarna (sponsor side):**
  - They are testing critical thinking: how you break the problem down, and whether you *redesign the process*, not just bolt a tool on.
  - The solution must address the system holistically and be scalable.
  - Security, compliance and hosting will be looked at.
- **Infra:**
  - One SPOC per team posts requests in the infra Teams group. No duplicate posts.
  - Deadline: 7 pm on the day the problem statement is received.
  - All access is revoked after the hackathon.
  - CSC VMs arrive Monday.
- **AI tools:**
  - Most people already have Claude, Cursor and GitHub.
  - Anyone on a client-provided Claude (for example Pluralsight) should switch to Evoke Claude, with approval email from the account head.
  - Open question raised in the call: the Claude **5-hour usage window**, and whether it can be extended. L&D will answer in the group.
- **Deadline:**
  - Moved: **source code, working solution and AI usage logs are due 29 Oct EOD.**
  - Start the deck straight after 29 Oct. L1 runs around 2–3 Nov and the L2 presentations around 4–6 Nov, possibly right after L1.
- **Judging stance:**
  - **Treat the panel as your client**, not as internal managers.
  - Sell the idea, the thinking and the solution.
- **Format:**
  - In person in Hyderabad; Bangalore staff may join virtually.
  - There is a **single overall winner and one runner-up across all 4 problems**, judged on common criteria and announced at Evotsav, which all participants must attend.
  - Prize money has nearly doubled.
- **UI and tool constraints:**
  - There is no fixed UI framework.
  - Problem-specific constraints are to be asked of the stakeholder (CSC, for example, has regulatory limits).
- **Agent tools:**
  - Open-source agent tools and AWS-provisioned tools are probably allowed; L&D will confirm.
  - Pega Community Edition was asked about.

## 3. Problem 2 briefing call (Swarna Vaitla)

- **The problem is real:**
  - It is an Evoke **manufacturing customer's** problem, worked on with their Europe warehousing team. The name is withheld.
  - The best ideas may be put forward to that customer, so this is effectively a real FDE engagement.
- **What top management cares about:**
  - One number: on-time delivery.
  - "It's 75% today. Why are 25% late? Take it to 95%." The docx says **71% vs a 94% benchmark**, so we must ask which figure is right.
- **Her explicit warning:**
  - Don't assume the routing is broken.
  - If you buy a routing tool and the rate stays at 75%, or drops to 65%, you didn't do the homework.
  - The failures may sit upstream: order assignment, picking the right items, missing addresses. They may also be a **combination of 2–3 steps, each needing a different fix.**
- **What she wants:**
  1. Lay out the whole workflow, upstream and downstream: warehouse, dispatch, carrier, routing, customer availability, re-delivery.
  2. Find where the 25–29% of late deliveries come from, as an attribution such as 10% + 15% + 10%.
  3. A fix per failure point.
  4. **Measurable proof.** Apply the solution to the provided or synthetic order data and show the number moving.
- **Validate against the data:**
  - "What people say versus what the data tells is often different."
  - List every assumption in the response document.
- **Data:**
  - Synthetic data in the customer's real format.
  - Generate our own data where there are gaps.
- **Domain homework:** WMS, warehousing, logistics vs transportation vs supply chain, and who the parties are.
- **Evaluation within Problem 2:** they want a variety of perspectives. The best answer may combine ideas from several teams.

## 4. Problem 2: the brief, and what it hides

- **The facts as given:**
  - 280 enterprise clients, 5 warehouses, 6 carriers.
  - On-time delivery is 71% against a 94% benchmark.
  - 34 formal complaints in 90 days.
  - 9 accounts worth **$14.2M** a year are threatening to leave.
  - 48,340 deliveries over 6 months.
- **Leadership's thesis:**
  - "Carrier routing and selection is inefficient; a smarter routing engine fixes it."
  - The COO and CFO have shortlisted a vendor with a **$680K** budget. The contract is **two weeks** from signature.
- **Our mandate:** establish what is really happening, with evidence, before the signature. We may support, change or reject the vendor decision, but must show why.
- **The steps marked † in the docx are the organisers' guesses.** We must verify them.

**Candidate root causes the process description hints at.** Each is a hypothesis to test against the data:

- **H1. Order intake latency.**
  - Email orders are keyed by hand into the WMS.
  - **14 clients use non-standard email formats**, so expect keying delays and errors (wrong SKU, quantity or address).
- **H2. The 8am pick-list cutoff.**
  - Orders arriving after 8am wait a full day before picking starts.
  - A late-morning order may already be "late" before anyone touches it.
- **H3. Inventory allocation.**
  - Which warehouse holds a client's stock is fixed at onboarding and reviewed only quarterly.
  - The result is stock far from demand, stock-outs, and split shipments.
- **H4. Carrier choice by spreadsheet.**
  - Carriers are picked from a rate card and a preference spreadsheet, so cost wins over performance.
  - The **single-carrier preferred-supplier deal** may be overloading one carrier.
- **H5. Visibility.**
  - **3 of the 6 carriers have no API**, so delays are only found when the client complains.
  - Failed-delivery returns: address quality, recipient availability.
- **H6. Reactive exception handling.**
  - Customer success learns of a problem only when the client chases.
  - The expedite desk and extra coordinators are treating symptoms.
- **H7. Measurement itself.**
  - How is "on time" defined: promised vs requested date, ship date vs delivery date?
  - Do carriers without APIs report delivery timestamps late, or not at all?
- **Where routing would help:**
  - Only the transit leg (H4/H5), and only if the data shows lateness concentrated **after** dispatch.
  - If most late orders were already late at dispatch (H1–H3), a routing engine can't fix them. That is the likely "challenge the brief" moment.

## 5. What this means for our plan

- **Deliverable shape:**
  - an evidence-based **late-delivery root-cause attribution**, stage by stage, on the 48,340 deliveries
  - targeted AI-powered fixes at each failure point
  - a **counterfactual simulation** showing on-time delivery moving, and an informed **go / reshape / no-go on the $680K vendor**
- **Must-haves to plan for from day one:**
  - **agent pipeline across roles:** BA, design, dev, test and adoption agents, with logs committed to the repo
  - **AI inside the product**
  - a deployed UI plus API
  - test evidence
- **Weighting tells us where to spend effort:**
  - AI-First Delivery (30) and Problem Fit & ROI (20) are half the score.
  - The FDE lens rewards *Deconstruct*, *Reframe* and *Prove* (20% each) as much as *Build*.
- **Things to clarify with L&D:**
  - The PDF says the repo is **GitHub**; the infra form has an **Azure DevOps repository** column.
  - The Claude 5-hour usage window.
