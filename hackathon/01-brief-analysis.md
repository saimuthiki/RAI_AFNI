# EvoHack 2026 (Hackathon 5.0): what the organisers actually said

Sources: the kickoff webinar transcript (Kezia Rani Singh, organiser; Divya Madala; Hari Prasad Alla)
and the 7-slide deck "FDE Mode ON — Think like a Forward Deployed Engineer. Deliver like one."
(webinar Monday 12 Oct 2026). The deck slides are images only; their text is transcribed below.

## 1. The facts

| Topic | What was said | Source |
|---|---|---|
| Theme | "Think like a Forward Deployed Engineer." Nobody becomes an FDE in a week, but you can think like one | Deck s1–2, Kezia |
| FDE definition | "An engineer embedded with the customer, who turns real-world problems into working software and owns the outcome" | Deck s2 |
| What your pod will do | Work with a **real Evoke business leader** · start from a **loose brief and mock data** · build with **AI agents as teammates** · be **judged on business impact** | Deck s2 |
| Pod model | Humans + AI agents side by side; converged roles; small teams that own the problem end to end | Deck s3 |
| Team size | Ideal 1–3, max 5. Five-person teams aren't penalised, but team structure counts toward how well you show AI use. Recommended: 3 | Deck s4, Divya |
| AI Practice rule | At most **one** AI Practice member per pod (none is fine) | Deck s4, Kezia |
| Duration | One week, five stages: Discover → Design → Build → Test & Deploy → Demo & Pitch | Deck s5 |
| Discover | (1) Organisers share a problem statement from a real business need, given by a stakeholder · (2) "Own the problem statement" · (3) Run discovery **directly with that stakeholder** | Deck s6 |
| Design / Build / Test / Demo | "Shape a solution around what you learned in discovery" · "Build lean, with AI agents as part of your team" · "Make sure it works and is running" · "Show what you built **and the outcome it delivers**" | Deck s7 |
| Demo slot | 30 minutes per team, strictly enforced. Recent years favoured working POCs | Kezia |
| Dates | Window **21 Oct – 3 Nov 2026**. Exact dates "end of day tomorrow" | Kezia |
| Venue | Hyderabad teams present in person. Bangalore participants may join the final round online | Kezia |
| Evaluation | Criteria and weightings are shared transparently **after nominations** | Kezia |
| Tooling | Approved: **Cursor, Copilot, Claude**. Anything else, ask first. Subscriptions and infra on request | Hari |
| Tech specs | Teams submit tech-stack and infra needs in the first couple of days after receiving the problem | Kezia, Hari |
| Roles | Nothing fixed. A "true FDE" does it all with agents; bring in specialities as your maturity needs | Hari |

## 2. What the judges are really scoring (read between the lines)

Divya described the skills under test. Those are the hidden rubric:

1. **Discovery quality.** "Are you able to ask the right questions? Are you able to validate the
   assumptions you're making?" Expect them to ask what you learned from the stakeholder, not only
   what you built.
2. **Challenging the brief.** "Sometimes you may even have to challenge the brief that was given by
   the business leaders." A pod that reframes the problem, with evidence, gets marks a pod that
   just builds the brief does not.
3. **Outcome over output.** "Owns the outcome, not the task" and "judged on business impact". The
   demo has to end on a measurable business result: money, hours, risk or a decision made faster.
4. **AI-first delivery model, made visible.** The hackathon is not about coding faster, which was
   last year's theme. It is about how humans and agents split the roles. Show the org chart of
   humans and agents, and show the agent hand-offs.
5. **Role convergence.** Each human wears developer, business-analyst and product hats, and agents
   fill the gaps. A 3-person pod that looks like a 10-person team scores.
6. **Working and running.** "Make sure it works and is running." Deploy it, don't just screenshot it.
7. **Storytelling.** Kezia stressed it twice: "storytelling, storyboarding… pitch it, demo it, sell it".

## 3. Implications for our pod

- **Team:** 3 humans (the recommended size), with only one from the AI Practice.
- **Problem source:** the problem statement comes from Evoke leaders, so it will probably be an
  internal Evoke business problem (delivery, sales, HR/talent, finance, operations). Our fallback
  use case should be one too, so it plugs into the same judging lens. See `04-use-case-proposal.md`.
- **Speed of discovery:** we get one week from the problem statement. The first 48 hours decide
  the outcome: discovery call, assumption log, reframed problem statement and tech-spec request.
  The `/fde-intake` and `/fde-discover` commands produce all of these. See `02-fde-playbook.md`.
- **Mock data:** the deck says "mock data". Expect synthetic CSVs or JSON and build a realistic
  synthetic-data generator early, so the demo has volume and edge cases.
- **Tooling compliance:** stay on Claude Code, Cursor and Copilot. Everything in `toolkit/` runs
  inside Claude Code. Anything that needs a third-party SaaS key (Firecrawl, gstack design tools
  that need OpenAI) is opt-in and needs organiser approval first.
- **Demo slot:** in 30 minutes, plan roughly 5 min story, 12 min live demo, 5 min "how humans and
  agents built it", 3 min impact and rollout, 5 min Q&A.

## 4. Questions to send the organisers now

1. Exact dates for kickoff, the problem-statement release, the discovery-session booking window,
   and the demo day.
2. Evaluation criteria and weightings. They said these come after nominations; ask for them as
   soon as we nominate.
3. Can we pick from several problem statements, or is one assigned? Can we propose our own (our
   fallback use case)?
4. How many stakeholder touchpoints do we get: one discovery call, or ongoing access during the week?
5. Is the mock data provided, or do we generate it? Can we use any real (anonymised) Evoke data?
6. Deployment target: Evoke Azure/AWS tenant, a VM, or our own laptops? Is there a corporate SSO
   or network we must stay inside?
7. Are Claude Code CLI and the Claude API (not just the chat app) both covered by the approved
   "Claude" tool, and will the organisers fund API usage for an agentic product?
8. IP and data handling: may the code live on GitHub (private repo), or must it be on an Evoke Git server?
