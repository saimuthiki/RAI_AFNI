---
name: fde-ship
description: EvoHack FDE pod stage 4. Use when the build is feature-complete to test, harden, deploy and prove it runs (/fde-ship, "are we ready", "deploy it", "pre-demo check").
---

# FDE ship: make sure it works and is running

1. E2E-test the exact demo path with `webapp-testing` (Playwright): screenshots go to
   `hackathon/work/evidence/`.
2. Have the `Reality Checker` agent try to break the demo path. It defaults to NEEDS WORK until
   there is evidence.
3. Review the code with `adversarial-reviewer` + `requesting-code-review`. Fix what's real
   (`receiving-code-review`).
4. Run `security-and-hardening` + `ship-gate` (secrets, auth, input validation, dependency audit).
5. If there are AI features: run the prompt and output paths through `rai_platform` rails, and keep
   a block or redaction example ready to show.
6. Run `shipping-and-launch` + `observability-and-instrumentation`: health endpoint, structured
   logs, a rollback note.
7. Deploy to the agreed target. Run the demo script 3 times in a row on the deployed URL, then
   record a backup video (`ui-demo` or `demo-video`).
8. Write `hackathon/work/04-test-report.md`: acceptance criteria → evidence link → pass/fail.

Never claim ready without the evidence table (`verification-before-completion`).
