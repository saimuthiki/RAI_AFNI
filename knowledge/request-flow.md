# Request Flow — One Request, Start to Finish

The live path through the gateway. Source: deck slide 66 (flowchart) and slide 65
(narrative). Solid = live request path, where every millisecond counts. Dashed =
offline feedback, covered in [dev-vs-test-loop.md](dev-vs-test-loop.md).

```
Request
  │
  ▼
INPUT RAILS ── cheap deterministic first, escalate only if borderline
  · InvisibleText / unicode smuggling
  · Secrets (regex + entropy floor)
  · YARA injection rules
  · context-bloat heuristics
  · Presidio + NER PII detection → Vault (reversible) redaction
  │
  ▼
[ Block, escalate, or clear? ]
  ├── block ─────────────▶ BLOCK & Refuse
  ├── borderline ────────▶ Cloud 2nd Opinion (Azure / vendor) ──┐
  └── clear ──────────────────────────────────────────────────┬─┘
                                                              ▼
                                                        MODEL CALL
                                                              │
                                                              ▼
OUTPUT RAILS
  · toxicity classification
  · NLI-based groundedness vs the retrieved sources
  · PII re-check
  · OWASP insecure-output regex scorers
  · tool-call schema validation
  │
  ▼
[ All clear? ]
  ├── safe ──────────────▶ DELIVER RESPONSE  (delivered responses are logged too)
  └── not safe ──────────▶ four explicit mitigation branches:
        · Toxic          → Block / Refuse
        · PII leak       → Mask & Continue
        · Not grounded   → Flag / Regenerate
        · Bad tool call  → Block

  ▼ (every branch, including delivery)
AUDIT STORE — every verdict, one schema
  findings · severity · score · redaction spans · OpenTelemetry trace
```

## Design notes that are easy to lose

- **Escalation is conditional, not layered-always.** The paid model or cloud service
  is called *only* for input scoring near a threshold. That is the cost doctrine —
  cheap checks on 100% of traffic, paid checks on a thin slice.
- **Streaming responses are re-validated per chunk**, so a bad answer can be cut off
  mid-flight rather than after the fact.
- **"Not safe" is not one branch.** Four distinct mitigations, and only two of them
  block — PII leak masks and continues, ungrounded flags or regenerates. Treating
  "unsafe" as a single refuse path loses most of the usable behaviour.
- **Delivered responses are logged too**, not just blocks. The audit trail is the
  evidence pack for a client reviewer; a log of only refusals proves nothing.
- **Same record shape everywhere.** A red-team finding, a CI failure and a live
  production block are all one schema, so they can be trended on one dashboard.
- **Fail closed, fail loud** — see [decisions.md](decisions.md). These two rules
  apply at every decision diamond above.
