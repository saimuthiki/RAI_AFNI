# -*- coding: utf-8 -*-
"""
Human-readable attribution for a decision: which tool blocked it, how confident
it was, and which entity it fired on.

Why this is a separate object rather than extra fields on the verdict: both
`verdict` and its `findings[]` are declared `additionalProperties: false` in
OpenGuardrails v0.8. Bolting AFNI-specific keys onto them would produce a
verdict that no longer validates against the very schema we adopted as the
contract - and the whole point of adopting it was that any AFNI application, or
a future vendor, can rely on the shape. So the wire verdict stays strictly
compliant and the attribution rides alongside it:

    { "verdict": { ...strict OGR v0.8... },
      "explanation": { ...this... } }

Three things a caller and an auditor both need, and which a bare `decision:
"block"` does not give them:

  which repo   the upstream tool that actually made the call, so a false positive
               can be taken to the right place - and so nobody has to guess
               whether a block came from a regex or a language model
  confidence   the score, plus what kind of number it is; a regex match at 1.0
               and an LLM judge at 0.82 are not the same claim
  which entity the subject the detector fired on, redacted by default - the
               entity type and location are what an operator needs, and echoing
               the raw value back into a log is how PII leaks out of a guardrail
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Action, Decision, Finding, Verdict

# What kind of number `score` is. A caller comparing 0.9 from a regex against
# 0.9 from a judge is comparing nothing, so the kind travels with the value.
CONFIDENCE_KINDS = {
    "deterministic": "exact match or checksum - no model involved, so the score is 1.0 or absent",
    "classifier": "a locally-run trained model's probability",
    "entailment": "an NLI cross-encoder's entailment score",
    "judge": "a language model's self-reported score, the softest of the four",
}


@dataclass(frozen=True)
class RailAttribution:
    """Provenance for one rail. Built from the methodology analysis, so every
    field traces to something read in the vendored source rather than asserted."""

    rail: str
    source_repo: str
    display_name: str
    mechanism: str
    stage: int
    confidence_kind: str
    evidence: str
    capability: str | None = None

    def __post_init__(self) -> None:
        if self.confidence_kind not in CONFIDENCE_KINDS:
            raise ValueError(
                f"confidence_kind {self.confidence_kind!r} not one of "
                f"{sorted(CONFIDENCE_KINDS)}"
            )


@dataclass
class FindingExplanation:
    finding: Finding
    attribution: RailAttribution | None

    @property
    def entity(self) -> str:
        """The entity type, taken from the last segment of the category path -
        `security.secret_leak.api_key` reads as `api_key`.

        With one exception. The taxonomy suffixes region-scoped identifiers with
        a two-letter country code, so the bare last segment of
        `privacy.pii.national_id.us` is `us` - and "flagged us" tells an operator
        nothing at all. `privacy.pii.tax_id.in` is worse, because `in` reads as
        an English preposition. Those get their parent segment back.

        Deliberately restricted to a two-letter tail: `privacy.pii.health_id.dea`
        must keep reading as `dea`, which is the entity, not a locale.
        """
        parts = self.finding.category.split(".")
        if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
            return f"{parts[-2]}.{parts[-1]}"
        return parts[-1]

    @property
    def location(self) -> str | None:
        """Where the finding is. A span when there is one, the path otherwise.

        A whole-text classifier scores the input as a unit and legitimately has
        no character span - a toxicity model does not say WHICH four characters
        were toxic. The path, though, is always known, and returning None for the
        whole location threw it away: a real block came back reading
        `"location": null`, so an operator triaging a payload with a system
        prompt, three turns of history and an attachment could not tell which of
        them the classifier objected to.

        No span is stated where none exists - inventing `chars 0-N` would imply a
        precision the classifier does not have.
        """
        path = self.finding.path
        if self.finding.start is None or self.finding.end is None:
            return path or None
        return f"{path or 'payload'} chars {self.finding.start}-{self.finding.end}"

    def sentence(self, reveal_subject: bool = False) -> str:
        """One line an operator can act on.

        `reveal_subject` defaults to False on purpose. The subject is the matched
        value - an actual SSN, an actual API key. Echoing it into an explanation
        that gets logged or shown to a user would leak the very thing the rail
        caught, which is a guardrail defeating itself.
        """
        attr = self.attribution
        who = f"{attr.display_name} ({attr.source_repo})" if attr else (
            self.finding.detector or "unknown detector")
        parts = [f"{who} flagged {self.entity}"]
        if self.location:
            parts.append(f"at {self.location}")
        if self.finding.score is not None:
            kind = attr.confidence_kind if attr else "unknown"
            parts.append(f"- confidence {self.finding.score:.2f} ({kind})")
        elif attr and attr.confidence_kind == "deterministic":
            parts.append("- deterministic match, no score")
        if self.finding.action:
            parts.append(f"- action {self.finding.action.value}")
        if reveal_subject and self.finding.subject:
            parts.append(f"- value {self.finding.subject!r}")
        elif self.finding.subject:
            parts.append(f"- value withheld (fp {self.finding.fp or 'n/a'})")
        return " ".join(parts)


@dataclass
class Explanation:
    """Why the gateway decided what it decided."""

    decision: Decision
    findings: list[FindingExplanation] = field(default_factory=list)
    unjudged: list[str] = field(default_factory=list)
    stages_run: int = 0
    latency_ms: int | None = None

    @property
    def blocked_by(self) -> list[FindingExplanation]:
        """Only the findings that actually caused the block. A verdict can carry
        a dozen `flag` findings and be blocked by exactly one, and telling the
        caller "these twelve blocked you" would be false."""
        return [fe for fe in self.findings if fe.finding.action is Action.BLOCK]

    def summary(self, reveal_subject: bool = False) -> str:
        if self.decision is Decision.ALLOW:
            head = "ALLOWED"
        else:
            head = "BLOCKED"
        lines = [f"{head} after {self.stages_run} cascade stage(s)"
                 + (f" in {self.latency_ms}ms" if self.latency_ms is not None else "")]

        if self.unjudged:
            # Stated first and unmissably. This is the fail-loud rule surfacing:
            # a gap in coverage is more dangerous than a finding, because a
            # finding at least means something looked.
            lines.append(
                f"  COULD NOT JUDGE {len(self.unjudged)} path(s): "
                + ", ".join(self.unjudged)
                + "  <- not the same as 'found nothing'"
            )

        causes = self.blocked_by
        if causes:
            lines.append("  Blocked by:")
            lines += [f"    - {fe.sentence(reveal_subject)}" for fe in causes]
        other = [fe for fe in self.findings if fe not in causes]
        if other:
            lines.append(f"  Also flagged (did not block): {len(other)}")
            lines += [f"    - {fe.sentence(reveal_subject)}" for fe in other]
        if not self.findings and not self.unjudged:
            lines.append("  No findings - every rail judged the payload and found nothing.")
        return "\n".join(lines)

    def to_dict(self, reveal_subject: bool = False) -> dict[str, Any]:
        def one(fe: FindingExplanation) -> dict[str, Any]:
            d: dict[str, Any] = {
                "entity": fe.entity,
                "category": fe.finding.category,
                "action": fe.finding.action.value if fe.finding.action else None,
                "score": fe.finding.score,
                "location": fe.location,
                "sentence": fe.sentence(reveal_subject),
            }
            if fe.attribution:
                d["attributed_to"] = {
                    "repo": fe.attribution.source_repo,
                    "tool": fe.attribution.display_name,
                    "rail": fe.attribution.rail,
                    "mechanism": fe.attribution.mechanism,
                    "stage": fe.attribution.stage,
                    "confidence_kind": fe.attribution.confidence_kind,
                    "evidence": fe.attribution.evidence,
                    "capability": fe.attribution.capability,
                }
            return d

        return {
            "decision": self.decision.value,
            "stages_run": self.stages_run,
            "latency_ms": self.latency_ms,
            "could_not_judge": list(self.unjudged),
            "blocked_by": [one(fe) for fe in self.blocked_by],
            "also_flagged": [one(fe) for fe in self.findings
                             if fe not in self.blocked_by],
        }


def explain(verdict: Verdict, attributions: dict[str, RailAttribution],
            stages_run: int = 0) -> Explanation:
    """Join a verdict's findings to the rails that produced them.

    The join key is `Finding.detector`, which every AFNI rail sets to its own
    name. A finding with no matching attribution is kept rather than dropped -
    an unattributed block is still a block, and silently discarding it would
    hide it from the very report meant to explain the decision.
    """
    return Explanation(
        decision=verdict.decision,
        findings=[FindingExplanation(f, attributions.get(f.detector or ""))
                  for f in verdict.findings],
        unjudged=list(verdict.unjudged),
        stages_run=stages_run,
        latency_ms=verdict.latency_ms,
    )
