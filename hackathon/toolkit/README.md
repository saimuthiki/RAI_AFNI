# FDE pod toolkit: what's installed, and how to get the rest

Installing every one of the ~10k skills found across the 50 repos and 11 skill directories would
make Claude worse. Every active skill puts its description into context, and overlapping
skills fight over triggers. So the toolkit has **four layers**:

| Layer | What | Where | Loaded by Claude? |
|---|---|---|---|
| 1. Active curated skills | 89 vetted skills mapped to the 5 hackathon stages, plus 6 `/fde-*` stage skills we wrote | `.claude/skills/` (committed) | Yes, in every session for every teammate |
| 2. Pod agents | 43 subagent personas (product, design, engineering, testing, sales, strategy) | `.claude/agents/` (committed) | Yes, as Agent types |
| 3. Vault | All 50 source repos, indexed (8,126 skills, 1,191 agents, 1,156 commands, deduplicated) | `~/.claude/skill-vault/` (built by `install.sh vault`), index in `skill-index.tsv` (committed) | No, until you `skill.sh enable` one |
| 4. Plugins and MCP | Full plugin bundles (with hooks and commands) and MCP servers | `plugins.tsv`, `config/` | Opt-in per laptop |

```bash
bash hackathon/toolkit/install.sh vault                  # clone all 50 repos (~2.8 GB) and rebuild the index
bash hackathon/toolkit/install.sh project                # (re)install the curated set from the vault
bash hackathon/toolkit/skill.sh find dashboard kpi       # search 10k entries
bash hackathon/toolkit/skill.sh enable kpi-dashboard-design wshobson   # activate one on demand
bash hackathon/toolkit/skill.sh active                   # what's active, by stage
bash hackathon/toolkit/install.sh plugins                # register marketplaces and install plugin bundles (laptop)
python3 hackathon/toolkit/config/apply.py                # add context7 + playwright MCP and the marketplaces to project config
```

Every installed skill has a `.provenance` file recording its source repo, path, commit and stage.
The curated list lives in `curated-skills.tsv`; edit it and re-run `install.sh project`.

## Active skills by stage (`curated-skills.tsv`)

| Stage | Skills |
|---|---|
| **Our stage skills** | `fde-intake` · `fde-discover` · `fde-design` · `fde-build` · `fde-ship` · `fde-pitch` |
| Meta / how we work | karpathy-guidelines · planning-with-files · dispatching-parallel-agents · subagent-driven-development · context-engineering · handoff · caveman · find-docs (Context7) · repomix-explorer · claude-md-improver |
| 1 Discover | brainstorming · grill-me · grill-with-docs · interview-me · idea-refine · to-questionnaire · requirements-clarity · thinking-out-loud · roast · product-discovery · ux-researcher-designer · process-mapper · meeting-analyzer · market-research · competitive-teardown · domain-modeling · product-lens · devil |
| 2 Design | product-strategist · product-manager-toolkit · spec-driven-development · to-spec · to-tickets · writing-plans · planning-and-task-breakdown · api-and-interface-design · documentation-and-adrs · senior-architect · tech-stack-evaluator · database-designer · rag-architect · agent-designer · agent-workflow-designer · experiment-designer · c4-architecture · ui-ux-pro-max · taste-skill · frontend-design · architecture-diagram-creator · flowchart-creator |
| 3 Build | executing-plans · incremental-implementation · test-driven-development · prototype · senior-fullstack · frontend-ui-engineering · kpi-dashboard-design · dashboard-creator · systematic-debugging · using-git-worktrees · code-simplification · security-and-hardening |
| 4 Test & Deploy | verification-before-completion · webapp-testing · requesting-code-review · receiving-code-review · doubt-driven-development · adversarial-reviewer · ship-gate · ci-cd-and-automation · shipping-and-launch · finishing-a-development-branch · observability-and-instrumentation |
| 5 Pitch | ceo-advisor · cfo-advisor · cto-advisor · chief-ai-officer-advisor · executive-mentor · board-deck-builder · scenario-war-room · financial-analyst · market-sizing-analysis · sales-engineer · roadmap-communicator · data-storytelling · frontend-slides · ui-demo · demo-video · timeline-creator |
| Built into Claude Code here | pptx · docx · xlsx · pdf · doc-coauthoring · internal-comms · theme-factory · web-artifacts-builder · mcp-builder · skill-creator · dataviz · code-review · security-review · simplify · graphify |

Vetting: every curated skill's scripts were grepped for pipe-to-shell, outbound POSTs, eval,
telemetry and credential access before install. Nothing risky was found. Some mattpocock skills are
user-invoked only (`/grill-me`, `/to-spec`, `/to-tickets`, `/handoff`); that's by design.

## Pod agents (`.claude/agents/`)

- Product: product-manager · feedback-synthesizer · sprint-prioritizer · trend-researcher
- Design: ux-researcher · ux-architect · ui-designer · visual-storyteller · persona-walkthrough
- Engineering: software-architect · backend-architect · frontend-developer · ai-engineer ·
  rag-pipeline-engineer · multi-agent-systems-architect · prompt-engineer · data-engineer ·
  data-visualization-engineer · rapid-prototyper · devops-automator · sre · api-platform-engineer ·
  code-reviewer · technical-writer
- Quality and security: reality-checker · test-automation-engineer · api-tester · evidence-collector ·
  appsec-engineer · security-architect · privacy-engineer · compliance-auditor ·
  automation-governance-architect
- Business: business-strategist · strategy-duel-agent · pricing-analyst · operations-manager ·
  workflow-architect · agents-orchestrator · sales-discovery-coach · sales-engineer ·
  proposal-strategist · executive-summary-generator

Source: msitarzewski/agency-agents (MIT).

## All 50 sources: verdict for this hackathon

ADOPT = in use now. OPTIONAL = install on demand. SKIP = deliberately not used (reason given).
Policy context: the organisers approved Claude, Cursor and Copilot only.

| Repo | What it is | Verdict | How we use it / why not |
|---|---|---|---|
| anthropics/skills | Official skills and spec | ADOPT | frontend-design, webapp-testing (copied); pptx/xlsx/docx/pdf built in. Plugin: `document-skills@anthropic-agent-skills` |
| anthropics/claude-plugins-official | Official plugin directory (315) | ADOPT | Plugins: feature-dev, pr-review-toolkit, security-guidance, commit-commands, playground, claude-md-management |
| obra/superpowers | Brainstorm → plan → subagent TDD → review methodology | ADOPT | Backbone of the Build stage. 12 skills copied. Plugin: `superpowers@claude-plugins-official` |
| obra/superpowers-lab | Experimental extras | SKIP | Niche (tmux, Windows VM) |
| addyosmani/agent-skills | Define → Plan → Build → Verify → Ship lifecycle | ADOPT (selected) | 15 skills copied. Overlaps Superpowers, so we use it for spec/interview/ship, not as a second build loop |
| mattpocock/skills | Grill, spec, tickets, TDD | ADOPT | grill-me, grill-with-docs, to-questionnaire, to-spec, to-tickets, domain-modeling, prototype, handoff |
| multica-ai/andrej-karpathy-skills | 4 coding rules | ADOPT | karpathy-guidelines |
| OthmanAdi/planning-with-files | Plan, findings and progress on disk | ADOPT | Shared state for 3 humans plus agents. The plugin adds the hooks |
| garrytan/gstack | "Virtual eng team" slash commands | OPTIONAL | `/office-hours` and `/plan-ceo-review` are excellent but need bun plus its runtime: `install.sh gstack` on one laptop. Design tools need an OpenAI key, so not those |
| DietrichGebert/ponytail | "Lazy senior dev" reuse ladder | OPTIONAL | `/ponytail-review` as a pre-demo check; the always-on mode overlaps karpathy |
| affaan-m/everything-claude-code | Mega harness (311 skills) | Cherry-pick | product-lens, ui-demo, frontend-slides copied. The full install bloats context |
| Yeachan-Heo/oh-my-claudecode | Autopilot and team pipelines | OPTIONAL | `/deep-interview` idea folded into fde-discover; heavy otherwise |
| coleam00/Archon | YAML workflow engine for agents | SKIP (build) | Too much platform for a week. Its approval-gate idea is in our stage gates |
| wshobson/agents | 94 granular plugins | Cherry-pick | data-storytelling, kpi-dashboard-design, market-sizing-analysis copied. Plugins: startup-business-analyst, c4-architecture, full-stack-orchestration, agent-teams |
| msitarzewski/agency-agents | 300+ agent personas | ADOPT | 30 personas copied into `.claude/agents/` |
| alirezarezvani/claude-skills | 99 plugins: product, C-level, engineering | ADOPT (selected) | 27 skills copied (discovery, PM, architecture, C-level pitch) |
| davila7/claude-code-templates (aitmpl.com) | ~1,900 components | Cherry-pick | requirements-clarity, devil, c4-architecture. CLI: `npx claude-code-templates@latest --skill <cat>/<name>` |
| ComposioHQ/awesome-claude-skills | List plus 832 app connectors | Vault only | No LICENSE file, so nothing is copied; the connectors also need a Composio key |
| saimuthiki/claude_skills_mastery | Our aggregated mirror (38 domains) | Vault | Fully indexed; search with `skill.sh find` |
| Shubhamsaboo/awesome-llm-apps | LLM app examples plus `agent_skills/` | Cherry-pick | thinking-out-loud. Its app templates are a reference if we build an agentic app |
| mhattingpete/claude-skills-marketplace | Visual docs and workflow skills | ADOPT | architecture-diagram, flowchart, dashboard and timeline creators |
| nextlevelbuilder/ui-ux-pro-max-skill | Searchable design intelligence DB | ADOPT | ui-ux-pro-max (Python stdlib scripts) |
| Leonxlnx/taste-skill (moved from jeettrench) | Anti-slop frontend art direction | ADOPT | taste-skill (`design-taste-frontend`) |
| numman-ali/openskills | Universal skill loader | OPTIONAL | Only if a teammate uses Cursor or Copilot: `npx openskills install` + `sync` writes AGENTS.md |
| shareAI-lab/learn-claude-code | Build-your-own-agent course | SKIP | Learning material. Reference if the product is a custom agent |
| shanraisshan/claude-code-best-practice | 83 practices | ADOPT (practices) | See "Strategies" below |
| x1xhlol/system-prompts-and-models-of-ai-tools | Leaked system prompts | Read-only | GPL and leaked IP: never copy into deliverables. Patterns are summarised below |
| BehiSecc/awesome-claude-skills, travisvn/awesome-claude-skills | Curated lists | Reference | Browse; vet each entry |
| punkpeye/awesome-mcp-servers | MCP list | Reference | Shortlist below |
| upstash/context7 | Current library docs | ADOPT | find-docs skill; MCP in `config/mcp.servers.json` |
| microsoft/playwright-mcp | Browser automation MCP | ADOPT | E2E checks and demo evidence; MCP in `config/` |
| github/github-mcp-server | GitHub MCP | ADOPT if on GitHub | Already available in cloud sessions. Laptop: see `install.sh mcp` |
| yamadashy/repomix | Pack a repo for AI | ADOPT | repomix-explorer; `npx repomix --remote owner/repo` |
| Graphify-Labs/graphify | Knowledge graph of code and docs | OPTIONAL | Already active (`graphify` skill). Use it when the stakeholder hands over a pile of docs |
| colbymchenry/codegraph | Code graph MCP | OPTIONAL | Only for a large brownfield codebase. Telemetry on by default (`DO_NOT_TRACK=1`) |
| steveyegge/beads | Dependency-graph task tracker for agents | OPTIONAL | Visibly shows agents claiming work, but costs half a day to learn. planning-with-files is the default |
| multica-ai/multica | Agents as issue-board assignees | OPTIONAL | Great "humans + agents" visual for the pitch; needs Docker or an account |
| thedotmack/claude-mem | Cross-session memory | SKIP | Records every tool output (stakeholder data) and upsells a cloud tier. `handoff` + planning files instead |
| Obidel/Agentmemory | Memory UI + MCP | SKIP | v0.1, provenance of the npm package unverified |
| firecrawl/firecrawl | Web scraping API | SKIP | AGPL plus a paid external key; data leaves the network |
| farion1231/cc-switch, musistudio/claude-code-router | Route Claude Code to other providers | SKIP | Sends traffic to non-approved models |
| udeope/codex-plugin-cc | Delegate review to OpenAI Codex | SKIP | Codex isn't approved. Same idea done with a fresh Claude subagent (`adversarial-reviewer`) |
| BloopAI/vibe-kanban | Agent kanban | SKIP | Project is sunsetting |
| jarrodwatts/claude-hud | Status line: context, agents, todos | ADOPT (laptop) | `/plugin install claude-hud@claude-hud`. Shows agent activity live during the demo |
| rtk-ai/rtk | Shell-output compression | OPTIONAL | `rtk-oss` edition only, if context gets tight |
| headroomlabs-ai/headroom | Context-compression proxy | SKIP | Man-in-the-middle proxy on every API call |
| JuliusBrussee/caveman | Terse mode | ADOPT (skill only) | `/caveman` for internal work; never for stakeholder-facing text |

### Websites surveyed

| Site | Use |
|---|---|
| aitmpl.com | Catalog for claude-code-templates; `npx claude-code-templates@latest --skill/--agent/--mcp <cat>/<name>` |
| claude.com/plugins | The official marketplace (`@claude-plugins-official`) |
| skills.sh | Vercel skills leaderboard; `npx skills add <owner/repo> --skill <name>` |
| claudeskills.info, claudeskills.club, openaitoolshub skillsmap and blog, mcpmarket leaderboard, skillsmp.com, chat2anyllm catalog | Discovery only. Their top picks (grill-me, frontend-design, ui-ux-pro-max, superpowers, find-skills) are already active |
| mcpservers.org/agent-skills | Blocked (403) during the survey |

### MCP shortlist for building enterprise apps fast (from awesome-mcp-servers)

markitdown-mcp (stakeholder DOCX/PPTX/XLSX → Markdown) · playwright · github · supabase-mcp
(instant Postgres + auth) · genai-toolbox / postgres-mcp (databases) · mcp-atlassian (Jira and
Confluence) · Azure MCP / awslabs MCP (deploy targets) · mcp-mermaid / mcp-server-chart (diagrams)
· excel-mcp-server.

## Strategies we adopt (distilled from the repos)

1. **Interview before you build.** Have Claude interview you (and draft questions for the
   stakeholder) before any spec: grill-me, interview-me, /deep-interview pattern.
2. **Spec triad with approval gates** (Kiro pattern): requirements (EARS: "WHEN … THEN the system
   SHALL …") → design → tasks, each approved before the next. These are our stage gates.
3. **Vertical tracer-bullet slices.** Walking skeleton deployed on day 3; every slice cuts DB → API → UI.
4. **Subagent-per-task with two-stage review** (Superpowers): fresh implementer, then reviewers
   for spec compliance and code quality.
5. **Plans on disk** (planning-with-files, Manus): context is RAM, the filesystem is disk.
6. **Context hygiene.** Stay under ~40% context; `/compact` with a focus hint; rewind rather than
   argue; use subagents when you only need the conclusion.
7. **Evidence before "done".** Tests, screenshots or a URL (verification-before-completion,
   Reality Checker).
8. **Cross-context adversarial review.** A second Claude with fresh context reviews the plan and
   the code; it catches what the author's context hides.
9. **Docs from source, not memory** (Context7 / find-docs).
10. **Design-system tokens and hard visual limits.** 3–5 colours, ≤2 fonts, semantic tokens only
    (Lovable and v0 patterns, taste-skill).
11. **Turn anything done twice a day into a skill.** That's why the `/fde-*` skills exist.
12. **Failures become rules.** After a repeated mistake, add a line to CLAUDE.md (the headroom
    "learn" idea, done by hand).
