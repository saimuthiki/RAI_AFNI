# -*- coding: utf-8 -*-
"""
Validates what we emit against the real OpenGuardrails JSON Schema files in
references/, not against a copy of them.

This exists because a hand-written binding drifts from its schema silently. An
earlier draft of models.py typed `Finding.fp` as a bool; upstream types it as a
string (a whitelist fingerprint - a hash of the subject, never the value). Every
unit test still passed, because nothing was checking the two against each other.
This module is that check.

Skips itself if `jsonschema` is unavailable, so the suite still runs with no
dependencies - but the skip is reported, never silent.

Run: python3 rai_platform/tests/test_contract_conformance.py
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai.contract.explanation import (  # noqa: E402
    CONFIDENCE_KINDS, Explanation, FindingExplanation, RailAttribution, explain,
)
from afni_rai.contract.models import (  # noqa: E402
    PROTOCOL_VERSION, Action, Decision, Finding, Severity, Span, Verdict,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_SCHEMA_DIR = os.path.join(
    _REPO_ROOT, "references", "openguardrails-main", "openguardrails-main", "schema")

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


def load_schema(name):
    with open(os.path.join(_SCHEMA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


@unittest.skipIf(jsonschema is None, "jsonschema not installed")
class TestVerdictConformance(unittest.TestCase):
    """Every verdict we can emit must validate against verdict.schema.json."""

    @classmethod
    def setUpClass(cls):
        cls.schema = load_schema("verdict.schema.json")

    def assertValid(self, verdict):
        jsonschema.validate(instance=verdict.to_dict(), schema=self.schema)

    def test_schema_is_the_version_we_pinned(self):
        self.assertIn(f"/schema/{PROTOCOL_VERSION}/", self.schema["$id"],
                      "the schema on disk is not the version models.py pins")

    def test_minimal_verdict_validates(self):
        self.assertValid(Verdict(event_id="e1", provider="afni-rai-gateway",
                                 decision=Decision.ALLOW))

    def test_fully_populated_verdict_validates(self):
        # Exercises every optional field at once - this is the shape that caught
        # the fp bool/string mismatch.
        self.assertValid(Verdict(
            event_id="e2", provider="afni-rai-gateway", decision=Decision.BLOCK,
            latency_ms=42,
            findings=[Finding(
                category="privacy.pii.us_ssn", severity=Severity.CRITICAL,
                action=Action.BLOCK, path="payload.messages[0].content",
                start=11, end=22, score=0.97, detector="llm-guard/Anonymize",
                fp="sha256:6f1c0e", whitelisted=False, subject="123-45-6789")],
            modifications=[Span(path="payload.messages[0].content", start=11,
                                end=22, replacement="[REDACTED-US_SSN]")],
            unjudged=["payload.attachment"],
        ))

    def test_every_action_and_severity_value_validates(self):
        for action in Action:
            for severity in Severity:
                with self.subTest(action=action, severity=severity):
                    self.assertValid(Verdict(
                        event_id="e", provider="p", decision=Decision.BLOCK,
                        findings=[Finding(category="safety.toxicity",
                                          action=action, severity=severity)]))

    def test_our_category_pattern_is_a_subset_of_upstreams(self):
        # We are deliberately stricter (we reject empty segments). Stricter is
        # safe; looser would emit categories upstream rejects. This asserts the
        # direction of the difference rather than assuming it.
        import re
        ours = re.compile(r"^(safety|security|privacy|x)(\.[a-z0-9_]+)+$")
        theirs = re.compile(
            self.schema["properties"]["findings"]["items"]["properties"]["category"]["pattern"])
        for sample in ("privacy.pii.us_ssn", "security.injection.direct",
                       "safety.toxicity", "x.afni.custom", "privacy.a.b.c.d"):
            with self.subTest(sample=sample):
                self.assertIsNotNone(ours.match(sample))
                self.assertIsNotNone(theirs.match(sample),
                                     "we emit a category upstream would reject")

    def test_findings_never_echo_matched_text_per_span(self):
        # Upstream: findings MUST NOT carry a per-span echo of matched text;
        # `subject` is at most one value per finding. Our Finding has exactly one
        # subject field and no span-level text field, which is what enforces it.
        fields = set(Finding.__dataclass_fields__)
        self.assertIn("subject", fields)
        self.assertFalse(fields & {"text", "matched", "matched_text", "excerpt"},
                         "a span-level text field would leak matched values")


class TestExplanation(unittest.TestCase):
    """The attribution layer: which repo blocked it, how confident, what entity."""

    def attribution(self, **kw):
        base = dict(rail="llm-guard/Anonymize", source_repo="llm-guard-main",
                    display_name="LLM Guard", mechanism="Module + Keyword/Regex",
                    stage=1, confidence_kind="deterministic",
                    evidence="input_scanners/anonymize.py:28-40",
                    capability="PII entity detection & redaction")
        base.update(kw)
        return RailAttribution(**base)

    def test_confidence_kind_must_be_known(self):
        with self.assertRaises(ValueError):
            self.attribution(confidence_kind="vibes")
        for kind in CONFIDENCE_KINDS:
            with self.subTest(kind=kind):
                self.attribution(confidence_kind=kind)

    def test_names_the_repo_the_entity_and_the_confidence(self):
        v = Verdict(event_id="e", provider="p", decision=Decision.BLOCK,
                    findings=[Finding(category="privacy.pii.us_ssn",
                                      action=Action.BLOCK, score=0.97,
                                      detector="llm-guard/Anonymize",
                                      path="payload.text", start=11, end=22,
                                      subject="123-45-6789", fp="sha256:6f1c")])
        exp = explain(v, {"llm-guard/Anonymize": self.attribution()}, stages_run=1)
        line = exp.blocked_by[0].sentence()
        self.assertIn("LLM Guard", line)
        self.assertIn("llm-guard-main", line)      # which repo
        self.assertIn("us_ssn", line)              # which entity
        self.assertIn("0.97", line)                # confidence
        self.assertIn("chars 11-22", line)         # where

    def test_subject_is_withheld_by_default(self):
        # A guardrail that echoes the SSN it caught into a log has defeated
        # itself. The value is only revealed on explicit opt-in.
        v = Verdict(event_id="e", provider="p", decision=Decision.BLOCK,
                    findings=[Finding(category="privacy.pii.us_ssn",
                                      action=Action.BLOCK, detector="d",
                                      subject="123-45-6789", fp="sha256:6f1c")])
        exp = explain(v, {"d": self.attribution(rail="d")})
        self.assertNotIn("123-45-6789", exp.summary())
        self.assertIn("value withheld", exp.summary())
        self.assertIn("123-45-6789", exp.summary(reveal_subject=True))

    def test_only_blocking_findings_are_reported_as_the_cause(self):
        # A verdict can carry many flags and be blocked by one. Saying "these
        # all blocked you" would be false.
        v = Verdict(event_id="e", provider="p", decision=Decision.BLOCK, findings=[
            Finding(category="safety.toxicity", action=Action.FLAG, detector="a"),
            Finding(category="privacy.pii.email", action=Action.REDACT, detector="a"),
            Finding(category="security.injection", action=Action.BLOCK, detector="a"),
        ])
        exp = explain(v, {"a": self.attribution(rail="a")})
        self.assertEqual(len(exp.blocked_by), 1)
        self.assertEqual(exp.blocked_by[0].entity, "injection")
        self.assertIn("Also flagged (did not block): 2", exp.summary())

    def test_unjudged_is_surfaced_before_findings(self):
        v = Verdict(event_id="e", provider="p", decision=Decision.BLOCK,
                    unjudged=["payload.attachment"])
        summary = explain(v, {}).summary()
        self.assertIn("COULD NOT JUDGE", summary)
        self.assertIn("not the same as 'found nothing'", summary)

    def test_unattributed_finding_is_kept_not_dropped(self):
        # An unattributed block is still a block; dropping it would hide it from
        # the report meant to explain the decision.
        v = Verdict(event_id="e", provider="p", decision=Decision.BLOCK,
                    findings=[Finding(category="x.unknown.thing",
                                      action=Action.BLOCK, detector="mystery")])
        exp = explain(v, {})
        self.assertEqual(len(exp.blocked_by), 1)
        self.assertIn("mystery", exp.blocked_by[0].sentence())

    def test_to_dict_carries_repo_and_evidence(self):
        v = Verdict(event_id="e", provider="p", decision=Decision.BLOCK,
                    findings=[Finding(category="privacy.pii.us_ssn",
                                      action=Action.BLOCK, detector="d", score=0.9)])
        d = explain(v, {"d": self.attribution(rail="d")}, stages_run=2).to_dict()
        attr = d["blocked_by"][0]["attributed_to"]
        self.assertEqual(attr["repo"], "llm-guard-main")
        self.assertEqual(attr["stage"], 1)
        self.assertIn("anonymize.py", attr["evidence"])
        self.assertEqual(d["stages_run"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
