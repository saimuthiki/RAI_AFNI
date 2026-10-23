# EvoHack 2026: FDE pod workspace

Everything our 3-person pod needs to "think like a Forward Deployed Engineer" during Hackathon 5.0
(window 21 Oct – 3 Nov 2026).

| File | What it is |
|---|---|
| [01-brief-analysis.md](01-brief-analysis.md) | What the organisers said (transcript + deck), the hidden rubric, questions to send them |
| [02-fde-playbook.md](02-fde-playbook.md) | Pod design (3 humans + agent bench), stage-by-stage runbook with gates, daily cadence |
| [03-discovery-kit.md](03-discovery-kit.md) | Stakeholder interview arc, assumption log, value tree, challenge-the-brief template |
| [04-use-case-proposal.md](04-use-case-proposal.md) | Our own use case if needed: **Margin Guardian** (scored against 4 alternatives) |
| [toolkit/](toolkit/README.md) | 89 curated skills + 6 fde-* skills, 43 agents, 10k-entry vault + index, plugin and MCP config, verdicts on all 50 repos |
| [work/](work/README.md) | Where the `/fde-*` skills write artifacts during the week |

## The moment the problem statement lands

```
/fde-intake      paste the problem statement
/fde-discover    before and after the stakeholder session
/fde-design      spec, architecture, plan, tech request to organisers
/fde-build       slice by slice with agent teammates
/fde-ship        test, harden, deploy, evidence
/fde-pitch       impact model, deck, demo script, Q&A war room
```

## Fresh laptop or teammate setup

```bash
git pull                                         # curated skills + agents come with the repo
bash hackathon/toolkit/install.sh vault          # optional: full 50-repo vault for skill.sh enable
python3 hackathon/toolkit/config/apply.py        # optional: context7 + playwright MCP, plugin marketplaces
bash hackathon/toolkit/install.sh plugins        # optional: plugin bundles (hooks, commands)
```
