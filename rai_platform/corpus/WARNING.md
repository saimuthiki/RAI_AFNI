# Read before cloning, forking, or sharing this directory

`harm-intents.jsonl` contains **11,369 genuinely harmful prompts**: requests for
weapon and drug synthesis, instructions for violence against people and animals,
child-endangerment content, hate speech, fraud, and 519 AdvBench affirmative
completions written from the attacker's point of view.

It is here on purpose. **You cannot regression-test a content filter without the
content**, and a corpus nobody can clone is not an asset — it is a claim. Every
serious red-team tool ships something like this; garak, PyRIT and promptfoo all
do.

## Consequences, stated plainly

- **This repository must stay private.** Publishing it publishes a
  ready-to-use harmful-prompt dataset.
- **Do not paste records into a chat, ticket, or shared document.** Cite the
  record `id` instead; that is what ids are for.
- **Do not send it to a third-party API for scoring.** Use the local endpoint.
  10,000 harmful prompts arriving at a vendor from one account is, at best, a
  conversation you do not want to have.
- **Nothing here is AFNI-authored.** Provenance is in every record's `origin`
  block: `saimuthiki/my-tech-journey@main:evoke-responsible-ai-toolkit/harmdataset.xlsx`.
  The original labels are preserved verbatim in `source_label`.

## What it is for, and only for

Measuring whether **this platform's guardrails** block what they should, and
detecting when a code change alters that. It is a test fixture. It is not
training data, and it is not a source of examples for anything.

If a lawful-basis or data-classification review is required before this lands in
a shared repository, that review comes first. It is one file and it can be
removed with one commit; the ingester regenerates it from the source in seconds.
