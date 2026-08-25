# -*- coding: utf-8 -*-
"""
Tests for the Explainability & Transparency rails.

Same posture as test_foundation.py: these test the ways this tenet could quietly
lie, not the happy path. Three of them matter more than the rest.

  * A rail that runs on 100% of traffic must not storm. Every Stage-1 rail here
    gets a true negative as well as a true positive, and the mounted default
    configuration is checked against ordinary prose.
  * A rail that cannot run must say `unjudged`, never clean. `RubricJudgeRail`
    is the only rail in this tenet with a third-party dependency and deepeval is
    not installed here, so the degradation path is the real one, not a mock.
  * The coverage report must stay honest. Nine capabilities, each registered
    exactly once, and nothing claimed IMPLEMENTED that does not actually run.

Run: python3 rai_platform/run_tests.py
"""
import ast
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai.cascade.engine import Cascade  # noqa: E402
from afni_rai.cascade.rail import Stage  # noqa: E402
from afni_rai.contract.explanation import (  # noqa: E402
    CONFIDENCE_KINDS, RailAttribution,
)
from afni_rai.contract.models import (  # noqa: E402
    Action, Decision, EventKind, Finding, GuardEvent, LLMProtocol, Severity,
    Tenet, Verdict, _CATEGORY_RE,
)
from afni_rai.registry.capabilities import CapabilityRegistry, Coverage  # noqa: E402
from afni_rai.tenets import explainability as X  # noqa: E402

CONTACT_SCHEMA = {
    "type": "object",
    "required": ["name", "age"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 2, "maxLength": 40},
        "age": {"type": "integer", "minimum": 0, "maximum": 130},
        "tier": {"type": "string", "enum": ["bronze", "silver", "gold"]},
        "code": {"type": "string", "pattern": r"^[A-Z]{3}-\d{4}$"},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
    },
}

PROSE = ("Thanks for calling. I have pulled up your account and I can confirm "
         "the premium was received on the fourteenth.")


def event(payload=None, client_facing=True):
    return GuardEvent(
        kind=EventKind.RESPONSE,
        step_id="step-1",
        agent_id="agent-1",
        agent_type="chat",
        agent_workspace="afni",
        agent_user="tester",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload=payload if payload is not None else {"text": PROSE},
        client_facing=client_facing,
    )


# ------------------------------------------------ schema subset: the "why" ----
class TestSchemaExplainer(unittest.TestCase):

    def _violations(self, instance):
        return {v.json_path: v for v in X.validate_schema(instance, CONTACT_SCHEMA)}

    def test_reports_which_field_what_was_expected_and_what_arrived(self):
        # The whole point of this tenet: not "invalid", but which field, what the
        # contract asked for, and what type turned up instead.
        v = self._violations({"name": "Ada", "age": "41"})["$.age"]
        self.assertEqual(v.keyword, "type")
        self.assertEqual(v.expected, "integer")
        self.assertEqual(v.received, "string")
        self.assertEqual(v.message, "$.age: expected integer, received string")

    def test_missing_required_property_names_the_property(self):
        v = self._violations({"name": "Ada"})["$.age"]
        self.assertEqual(v.keyword, "required")
        self.assertEqual(v.received, "nothing")

    def test_every_keyword_family_is_explained(self):
        found = self._violations({
            "name": "A",                       # minLength
            "age": 200,                        # maximum
            "tier": "platinum",                # enum
            "code": "abc-1",                   # pattern
            "tags": ["a", "b", "c"],           # maxItems
            "surprise": 1,                     # additionalProperties
        })
        self.assertEqual(found["$.name"].keyword, "minLength")
        self.assertEqual(found["$.age"].keyword, "maximum")
        self.assertEqual(found["$.tier"].keyword, "enum")
        self.assertEqual(found["$.code"].keyword, "pattern")
        self.assertEqual(found["$.tags"].keyword, "maxItems")
        self.assertEqual(found["$.surprise"].keyword, "additionalProperties")

    def test_a_conforming_payload_produces_nothing(self):
        self.assertEqual(X.validate_schema(
            {"name": "Ada", "age": 41, "tier": "gold", "code": "ABC-1234",
             "tags": ["vip"]}, CONTACT_SCHEMA), [])

    def test_booleans_are_not_integers(self):
        # isinstance(True, int) is True in Python, so the naive type check lets a
        # boolean satisfy {"type": "integer"}. That is a real contract hole.
        v = self._violations({"name": "Ada", "age": True})["$.age"]
        self.assertEqual(v.received, "boolean")

    def test_a_wrong_type_does_not_also_report_its_siblings(self):
        # One real error must not become three. `maxLength` on an integer is a
        # keyword written for a type that never arrived.
        bad = X.validate_schema({"name": 7, "age": 1}, CONTACT_SCHEMA)
        self.assertEqual([(v.json_path, v.keyword) for v in bad],
                         [("$.name", "type")])

    def test_nested_paths_use_the_json_path_vocabulary(self):
        schema = {"type": "object", "properties": {
            "items": {"type": "array", "items": {
                "type": "object", "properties": {"qty": {"type": "integer"}}}}}}
        v = X.validate_schema({"items": [{"qty": 1}, {"qty": "two"}]}, schema)
        self.assertEqual([x.json_path for x in v], ["$.items[1].qty"])

    def test_received_never_echoes_the_value(self):
        secret = "424242424242"
        for v in X.validate_schema({"name": secret, "age": secret}, CONTACT_SCHEMA):
            self.assertNotIn(secret, v.message)
            self.assertNotIn(secret, v.received)

    def test_unsupported_keywords_are_reported_not_silently_ignored(self):
        # A schema leaning on oneOf is under-checked by this subset. Under-checked
        # and visible is survivable; under-checked and silent is not.
        rail = X.SchemaExplainRail(schema={
            "type": "object",
            "properties": {"a": {"oneOf": [{"type": "string"}]}}})
        self.assertIn("oneOf", rail.unsupported)
        self.assertEqual(X.SchemaExplainRail(schema=CONTACT_SCHEMA).unsupported, [])

    def test_a_violation_cap_bounds_the_finding_count(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {}}
        self.assertLessEqual(
            len(X.validate_schema({str(i): i for i in range(500)}, schema)), 25)


class TestSchemaExplainRail(unittest.TestCase):

    def setUp(self):
        self.rail = X.SchemaExplainRail(schema=CONTACT_SCHEMA)

    def test_stage_and_tenet(self):
        self.assertIs(self.rail.stage, Stage.STAGE_1)
        self.assertIs(self.rail.tenet, Tenet.EXPLAINABILITY)

    def test_malformed_json_is_caught_with_no_schema_at_all(self):
        rail = X.SchemaExplainRail()
        out = rail.check("payload.text", '{"name": "Ada",}')
        self.assertEqual([f.category for f in out.findings],
                         ["x.afni.schema.malformed_json"])

    def test_prose_is_not_json_and_is_left_alone(self):
        # The false-positive test that matters. LLM Guard's JSON scanner regexes
        # every {...} candidate out of the output; on prose that finds braces in
        # code samples and template placeholders.
        rail = X.SchemaExplainRail()
        for benign in (PROSE, "use {name} as the placeholder", "if (x) { return 1; }",
                       "", "   ", "{", "a}"):
            with self.subTest(text=benign):
                self.assertEqual(rail.check("payload.text", benign).findings, [])

    def test_valid_payload_against_a_schema_is_clean(self):
        out = self.rail.check("payload.text", '{"name": "Ada", "age": 41}')
        self.assertTrue(out.judged)
        self.assertEqual(out.findings, [])

    def test_each_failing_field_gets_its_own_finding(self):
        out = self.rail.check("payload.text", '{"name": "A", "age": "41"}')
        self.assertEqual(sorted(f.category for f in out.findings),
                         ["x.afni.schema.length_violation",
                          "x.afni.schema.type_mismatch"])
        for f in out.findings:
            self.assertEqual(f.detector, self.rail.name)
            self.assertIn("expected", f.subject)

    def test_paths_scope_the_rail(self):
        rail = X.SchemaExplainRail(schema=CONTACT_SCHEMA, paths=("arguments",))
        broken = '{"name": "A"}'
        self.assertEqual(rail.check("payload.text", broken).findings, [])
        self.assertTrue(rail.check("payload.tool.arguments", broken).findings)

    def test_assume_json_catches_a_truncated_stream(self):
        rail = X.SchemaExplainRail(paths=("arguments",), assume_json=True)
        out = rail.check("payload.arguments", '{"name": "Ada"')
        self.assertEqual([f.category for f in out.findings],
                         ["x.afni.schema.malformed_json"])

    def test_assume_json_without_paths_is_refused(self):
        # Enabling it globally would report every prose payload as broken JSON.
        with self.assertRaises(ValueError):
            X.SchemaExplainRail(assume_json=True)

    def test_malformed_reporting_can_be_handed_to_the_hallucination_rail(self):
        # The one place this tenet overlaps another: the hallucination tenet's
        # StructuredOutputRail owns Stage-1 well-formedness. A deployment running
        # both wants one voice on it, and gets it by switching this one off -
        # without losing the schema explanation, which nothing else provides.
        deferring = X.SchemaExplainRail(schema=CONTACT_SCHEMA,
                                        report_malformed=False)
        self.assertEqual(deferring.check("payload.text", '{"name":}').findings, [])
        self.assertEqual(
            [f.category for f in deferring.check(
                "payload.text", '{"name": "Ada"}').findings],
            ["x.afni.schema.missing_required"])

    def test_block_is_opt_in(self):
        self.assertFalse(self.rail.check("payload.text", "{").block)
        blocking = X.SchemaExplainRail(schema=CONTACT_SCHEMA, block_on_failure=True)
        out = blocking.check("payload.text", '{"name": "A", "age": 1}')
        self.assertTrue(out.block)
        self.assertIs(out.findings[0].action, Action.BLOCK)


# ------------------------------------------- deterministic format validators --
class TestFormatValidators(unittest.TestCase):

    def _fail(self, rule, text):
        return X._check_rule(rule, text)

    def test_length_bounds(self):
        rule = X.FormatRule("bounded", "length", min=3, max=6)
        self.assertIsNone(self._fail(rule, "abcd"))
        self.assertIn("at least 3 chars", self._fail(rule, "ab"))
        self.assertIn("at most 6 chars", self._fail(rule, "abcdefg"))

    def test_regex_match_search_vs_fullmatch(self):
        full = X.FormatRule("zip", "regex_match", pattern=r"\d{5}")
        self.assertIsNone(self._fail(full, "12345"))
        self.assertIsNotNone(self._fail(full, "zip 12345"))
        search = X.FormatRule("zip", "regex_match", pattern=r"\d{5}",
                              match_type="search")
        self.assertIsNone(self._fail(search, "zip 12345"))

    def test_a_broken_regex_in_the_rule_is_reported_not_raised(self):
        rule = X.FormatRule("bad", "regex_match", pattern="([")
        self.assertIn("re.error", self._fail(rule, "anything"))

    def test_allowed_choices(self):
        rule = X.FormatRule("tier", "valid_choices", choices=("bronze", "gold"))
        self.assertIsNone(self._fail(rule, "gold"))
        self.assertIn("allowed choice", self._fail(rule, "platinum"))

    def test_valid_url_needs_a_scheme_and_a_netloc(self):
        rule = X.FormatRule("link", "valid_url")
        self.assertIsNone(self._fail(rule, "https://example.com/a?b=1"))
        self.assertIn("no scheme", self._fail(rule, "example.com/a"))
        self.assertIn("no netloc", self._fail(rule, "mailto:a@b.com"))

    def test_one_line(self):
        rule = X.FormatRule("headline", "one_line")
        self.assertIsNone(self._fail(rule, "a single line"))
        self.assertIn("2 lines", self._fail(rule, "two\nlines"))

    def test_numeric_range_rejects_invalid_numbers(self):
        # This tenet ships no checksum validator - Luhn and the national-id
        # check digits belong to Privacy. The deterministic-number contract here
        # is a range, and it must reject both an out-of-band number and a string
        # that is not a number at all rather than coercing it.
        rule = X.FormatRule("score", "numeric_range", min=0.0, max=1.0)
        self.assertIsNone(self._fail(rule, "0.5"))
        self.assertIsNone(self._fail(rule, " 1.0 "))
        self.assertIn("below the minimum", self._fail(rule, "-0.1"))
        self.assertIn("above the maximum", self._fail(rule, "1.5"))
        self.assertIn("non-numeric", self._fail(rule, "one half"))
        self.assertIn("non-numeric", self._fail(rule, ""))

    def test_schema_numeric_bounds_reject_invalid_numbers_too(self):
        schema = {"type": "integer", "minimum": 1, "exclusiveMaximum": 10}
        self.assertEqual(X.validate_schema(5, schema), [])
        self.assertEqual(X.validate_schema(0, schema)[0].keyword, "minimum")
        self.assertEqual(X.validate_schema(10, schema)[0].keyword, "exclusiveMaximum")
        self.assertEqual(X.validate_schema("5", schema)[0].keyword, "type")

    def test_lower_case_two_words_reading_time_and_valid_json(self):
        self.assertIsNone(self._fail(X.FormatRule("l", "lower_case"), "abc"))
        self.assertIsNotNone(self._fail(X.FormatRule("l", "lower_case"), "aBc"))
        self.assertIsNone(self._fail(X.FormatRule("n", "two_words"), "Ada Lovelace"))
        self.assertIn("3 words", self._fail(X.FormatRule("n", "two_words"), "a b c"))
        slow = X.FormatRule("rt", "reading_time", max=1.0)
        self.assertIsNone(self._fail(slow, "word " * 100))
        self.assertIn("minutes", self._fail(slow, "word " * 400))
        self.assertIsNone(self._fail(X.FormatRule("j", "valid_json"), '{"a":1}'))
        self.assertIsNotNone(self._fail(X.FormatRule("j", "valid_json"), "{"))

    def test_an_unknown_kind_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            X.FormatValidatorRail(rules=[X.FormatRule("x", "vibes")])

    def test_rules_are_scoped_by_path(self):
        rule = X.FormatRule("link", "valid_url", paths=("homepage",))
        self.assertTrue(rule.applies_to("payload.homepage"))
        self.assertTrue(rule.applies_to("homepage"))
        self.assertFalse(rule.applies_to("payload.text"))
        self.assertTrue(X.FormatRule("any", "one_line").applies_to("anything"))

    def test_the_mounted_defaults_do_not_fire_on_ordinary_traffic(self):
        rail = X.FormatValidatorRail()
        for text in (PROSE, "ok", "", "line one\nline two", "word " * 500):
            with self.subTest(text=text[:20]):
                self.assertEqual(rail.check("payload.text", text).findings, [])

    def test_the_mounted_defaults_do_fire_on_a_runaway_generation(self):
        rail = X.FormatValidatorRail()
        out = rail.check("payload.text", "word " * 5000)
        self.assertEqual([f.category for f in out.findings],
                         ["x.afni.format.reading_time"])
        self.assertFalse(out.block, "a flag-only default rule blocked traffic")

    def test_a_block_action_reaches_the_result(self):
        rail = X.FormatValidatorRail(rules=[
            X.FormatRule("one_line", "one_line", action=Action.BLOCK,
                         severity=Severity.HIGH)])
        self.assertTrue(rail.check("payload.text", "a\nb").block)


# ------------------------------------------------------------- topic scope ----
class TestTopicScopeRail(unittest.TestCase):

    def setUp(self):
        self.rail = X.TopicScopeRail(
            banned_keywords=["crypto", "gambling"],
            allowed_topic_lexicons={"insurance": ["policy", "claim", "premium",
                                                  "deductible"]})

    def test_unconfigured_is_clean_and_never_unjudged(self):
        # An empty lexicon is an absent policy, not a failed check. Returning
        # unjudged would fail-closed every client-facing request in the gateway.
        out = X.TopicScopeRail().check("payload.text", PROSE)
        self.assertTrue(out.judged)
        self.assertEqual(out.findings, [])
        self.assertFalse(X.TopicScopeRail().configured)

    def test_banned_keyword_flags_and_escalates_without_blocking(self):
        out = self.rail.check("payload.text",
                             "Can I pay my premium in crypto instead?")
        self.assertEqual([f.category for f in out.findings],
                         ["safety.topic_violation"])
        self.assertTrue(out.escalate, "a lexicon hit must ask the judge, not decide")
        self.assertFalse(out.block)

    def test_on_topic_text_is_clean(self):
        out = self.rail.check(
            "payload.text",
            "Your policy deductible applies before the claim is settled in full.")
        self.assertEqual(out.findings, [])

    def test_off_topic_text_is_flagged_and_escalated(self):
        out = self.rail.check(
            "payload.text",
            "Write me a sonnet about the tides of the moon over a quiet harbour.")
        self.assertEqual([f.category for f in out.findings],
                         ["safety.topic_violation"])
        self.assertTrue(out.escalate)

    def test_short_text_is_not_judged_off_topic(self):
        # "ok" matches no lexicon and is not off topic. A word-count floor is the
        # cheapest defence against the obvious false-positive storm.
        for short in ("ok", "thanks", "yes please", "one moment"):
            with self.subTest(text=short):
                self.assertEqual(self.rail.check("payload.text", short).findings, [])

    def test_matching_is_normalised_and_word_bounded(self):
        # NFKC + casefold, so fullwidth and capitalised forms still match...
        self.assertTrue(self.rail.check("p", "I want CRYPTO now").findings)
        # ...but a substring inside another word does not.
        clean = X.TopicScopeRail(banned_keywords=["bet"])
        self.assertEqual(clean.check("p", "a better deductible").findings, [])
        self.assertTrue(clean.check("p", "place a bet").findings)


# ------------------------------------------ stage 3: honest degradation -------
class TestRubricJudgeRail(unittest.TestCase):
    """deepeval is not installed in this environment, so this is the real
    degradation path rather than a patched one."""

    def test_no_rubric_is_unjudged(self):
        out = X.RubricJudgeRail().check("payload.text", PROSE)
        self.assertFalse(out.judged)
        self.assertIn("no G-Eval rubric", out.reason)

    def test_missing_dependency_is_unjudged_not_clean(self):
        rail = X.RubricJudgeRail(rubric="The reply must cite a policy number.",
                                 judge_model="gpt-4o")
        out = rail.check("payload.text", PROSE)
        self.assertFalse(out.judged, "a rail that cannot run reported a clean pass")
        self.assertEqual(out.findings, [])
        self.assertIn("deepeval", out.reason)

    def test_unjudged_fails_closed_through_the_engine(self):
        # The consequence that makes the honesty load-bearing: an unrunnable
        # judge blocks client-facing traffic instead of waving it through.
        rail = X.RubricJudgeRail(rubric="must cite a source", judge_model="gpt-4o")
        out = Cascade([rail]).evaluate(event(client_facing=True))
        self.assertIs(out.verdict.decision, Decision.BLOCK)
        self.assertTrue(out.verdict.could_not_judge)

    def test_it_is_stage_3_and_not_mounted_by_default(self):
        self.assertIs(X.RubricJudgeRail.stage, Stage.STAGE_3)
        self.assertNotIn(X.RubricJudgeRail.name, [r.name for r in X.RAILS])

    def test_configured_needs_both_a_rubric_and_an_explicit_judge(self):
        self.assertFalse(X.RubricJudgeRail(rubric="r").configured)
        self.assertFalse(X.RubricJudgeRail(judge_model="gpt-4o").configured)
        self.assertTrue(X.RubricJudgeRail(rubric="r", judge_model="gpt-4o").configured)


# --------------------------------------------- per-check confidence table -----
def _attr(rail, kind, stage, repo="repo"):
    return RailAttribution(rail=rail, source_repo=repo, display_name=rail,
                           mechanism="m", stage=stage, confidence_kind=kind,
                           evidence="e")


class TestConfidenceBreakdown(unittest.TestCase):

    def setUp(self):
        self.attrs = dict(X.ATTRIBUTIONS)
        self.attrs.update({
            "regexy": _attr("regexy", "deterministic", 1),
            "classy": _attr("classy", "classifier", 2),
            "nli": _attr("nli", "entailment", 2),
            "judgy": _attr("judgy", "judge", 3),
        })

    def _verdict(self, findings, unjudged=(), decision=Decision.BLOCK):
        return Verdict(event_id="e", provider="p", decision=decision,
                       findings=list(findings), unjudged=list(unjudged))

    def test_no_findings_reports_no_score_rather_than_zero(self):
        b = X.confidence_breakdown(self._verdict([], decision=Decision.ALLOW),
                                   self.attrs, stages_run=1)
        self.assertIsNone(b.final_score)
        self.assertEqual(b.fusion, "NONE")
        self.assertFalse(b.blind)

    def test_a_deterministic_hit_is_not_averaged_away(self):
        b = X.confidence_breakdown(self._verdict([
            Finding(category="privacy.pii.us_ssn", detector="regexy",
                    action=Action.REDACT),
            Finding(category="safety.toxicity", detector="judgy", score=0.4,
                    action=Action.FLAG),
        ]), self.attrs, stages_run=3)
        self.assertEqual(b.fusion, "DETERMINISTIC")
        self.assertEqual(b.final_score, 1.0)
        self.assertFalse(b.hybrid_applied)

    def test_two_soft_sources_are_fused_and_the_fusion_is_named(self):
        b = X.confidence_breakdown(self._verdict([
            Finding(category="privacy.pii.email", detector="classy", score=1.0),
            Finding(category="safety.toxicity", detector="judgy", score=0.0),
        ]), self.attrs, stages_run=3)
        self.assertEqual(b.fusion, "HYBRID")
        self.assertTrue(b.hybrid_applied)
        # weighted by evidence weight: classifier 0.8, judge 0.5
        self.assertAlmostEqual(b.final_score, 0.8 / 1.3, places=3)

    def test_one_source_takes_the_max_not_the_mean(self):
        b = X.confidence_breakdown(self._verdict([
            Finding(category="privacy.pii.phone", detector="classy", score=0.4),
            Finding(category="privacy.pii.email", detector="classy", score=0.9),
        ]), self.attrs, stages_run=2)
        self.assertEqual(b.fusion, "SINGLE_SOURCE")
        self.assertEqual(b.final_score, 0.9)

    def test_confidence_kinds_come_from_the_contract_not_from_here(self):
        b = X.confidence_breakdown(self._verdict([
            Finding(category="privacy.pii.email", detector="classy", score=0.9),
            Finding(category="safety.hallucination", detector="nli", score=0.6),
            Finding(category="safety.toxicity", detector="judgy", score=0.8),
        ]), self.attrs, stages_run=3)
        self.assertEqual(set(b.by_kind()), {"classifier", "entailment", "judge"})
        for kind in b.by_kind():
            self.assertIn(kind, CONFIDENCE_KINDS)
        weights = {k: v[0].weight for k, v in b.by_kind().items()}
        self.assertGreater(weights["classifier"], weights["entailment"])
        self.assertGreater(weights["entailment"], weights["judge"])

    def test_checks_that_could_not_run_are_counted_in_the_same_table(self):
        # No reviewed tool does this, and it is the reason the port exists: a
        # confidence report that silently omits the rails that never ran reads as
        # complete when it is not.
        b = X.confidence_breakdown(self._verdict(
            [Finding(category="privacy.pii.email", detector="classy", score=0.9)],
            unjudged=["payload.attachment"]), self.attrs, stages_run=2)
        self.assertTrue(b.blind)
        self.assertEqual(b.unjudged, ["payload.attachment"])
        self.assertIn("COULD NOT JUDGE", b.render())
        self.assertIn("incomplete", b.render())

    def test_an_unattributed_detector_is_surfaced_not_dropped(self):
        b = X.confidence_breakdown(self._verdict(
            [Finding(category="x.afni.format.length", detector="mystery")]),
            self.attrs, stages_run=1)
        self.assertEqual(b.unattributed, ["mystery"])
        self.assertEqual(b.checks, [])
        self.assertIn("mystery", b.render())

    def test_to_dict_carries_the_inputs_beside_the_fused_number(self):
        b = X.confidence_breakdown(self._verdict(
            [Finding(category="privacy.pii.email", detector="classy", score=0.9,
                     action=Action.REDACT)]), self.attrs, stages_run=2)
        d = b.to_dict()
        self.assertEqual(d["fusion"], "SINGLE_SOURCE")
        self.assertEqual(len(d["checks"]), 1)
        check = d["checks"][0]
        self.assertEqual(check["confidence_kind"], "classifier")
        self.assertEqual(check["score"], 0.9)
        self.assertEqual(check["evidence"], "e")
        self.assertIn("evidence_weight", check)

    def test_it_explains_this_tenet_s_own_rails(self):
        # The breakdown has to work on the rails in this package, not only on
        # hand-built fixtures.
        rail = X.SchemaExplainRail(schema=CONTACT_SCHEMA)
        result = rail.check("payload.text", '{"name": "A", "age": "x"}')
        b = X.confidence_breakdown(
            self._verdict(result.findings), X.ATTRIBUTIONS, stages_run=1)
        self.assertEqual(b.fusion, "DETERMINISTIC")
        self.assertEqual(b.unattributed, [])
        self.assertTrue(all(c.confidence_kind == "deterministic" for c in b.checks))


# ------------------------------------------------------ platform invariants ---
class TestRailsAreWellBehaved(unittest.TestCase):

    def test_all_mounted_rails_are_stage_1_and_this_tenet(self):
        self.assertTrue(X.RAILS)
        for rail in X.RAILS:
            with self.subTest(rail=rail.name):
                self.assertIs(rail.stage, Stage.STAGE_1)
                self.assertIs(rail.tenet, Tenet.EXPLAINABILITY)

    def test_no_offline_rail_is_mounted(self):
        # SHAP, LIME and FACTS are registered OFFLINE and wrapped by nothing;
        # Cascade would raise if one of them had leaked into RAILS.
        Cascade(X.RAILS)

    def test_the_mounted_cascade_allows_ordinary_traffic(self):
        out = Cascade(X.RAILS).evaluate(event(
            {"messages": [{"role": "assistant", "content": PROSE}]}))
        self.assertIs(out.verdict.decision, Decision.ALLOW)
        self.assertEqual(out.verdict.findings, [])
        self.assertFalse(out.verdict.could_not_judge)

    def test_every_emitted_category_matches_the_contract_pattern(self):
        emitted = []
        emitted += X.SchemaExplainRail(schema=CONTACT_SCHEMA).check(
            "payload.text", '{"name": "A", "age": "x", "nope": 1}').findings
        emitted += X.SchemaExplainRail().check("payload.text", "{,}").findings
        emitted += X.FormatValidatorRail(rules=[
            X.FormatRule(k, k, max=1, min=0, pattern="^z$", choices=("z",))
            for k in X.FORMAT_KINDS]).check("payload.text", "a b\nc").findings
        emitted += X.TopicScopeRail(banned_keywords=["crypto"]).check(
            "p", "buy crypto").findings
        self.assertTrue(emitted)
        for finding in emitted:
            with self.subTest(category=finding.category):
                self.assertRegex(finding.category, _CATEGORY_RE.pattern)

    def test_no_finding_echoes_the_payload_and_fp_is_a_hash_of_the_subject(self):
        secret = "987-65-4320-SECRET"
        payload = '{"name": "%s", "age": "%s"}' % (secret, secret)
        findings = X.SchemaExplainRail(schema=CONTACT_SCHEMA).check(
            "payload.text", payload).findings
        findings += X.FormatValidatorRail(rules=[
            X.FormatRule("choice", "valid_choices", choices=("a",)),
            X.FormatRule("url", "valid_url")]).check("payload.text", secret).findings
        self.assertTrue(findings)
        for f in findings:
            with self.subTest(category=f.category):
                for field in (f.subject, f.category, f.detector, f.fp):
                    self.assertNotIn(secret, field or "")
                self.assertEqual(
                    f.fp, hashlib.sha256(f.subject.encode("utf-8")).hexdigest()[:16])

    def test_stage_1_imports_nothing_third_party(self):
        # The hard constraint for this tier: the gateway must be useful before
        # anyone installs torch. Asserted structurally rather than by trusting a
        # comment - the only third-party import in the module is the deepeval one
        # inside RubricJudgeRail.check, which is a function body, not module scope.
        source = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "afni_rai", "tenets", "explainability",
            "__init__.py")
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        stdlib = {"hashlib", "json", "re", "unicodedata", "urllib", "dataclasses",
                  "typing", "collections", "__future__", "os", "sys", "enum"}
        roots = set()
        for node in tree.body:                      # module scope only
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        self.assertTrue(roots <= stdlib, f"non-stdlib module-scope import: {roots - stdlib}")

    def test_every_attribution_declares_a_known_confidence_kind_and_evidence(self):
        for name, attr in X.ATTRIBUTIONS.items():
            with self.subTest(rail=name):
                self.assertIn(attr.confidence_kind, CONFIDENCE_KINDS)
                self.assertTrue(attr.evidence, "an unevidenced stage claim")
                self.assertIn(":", attr.evidence, "evidence must cite a file:line")
                self.assertEqual(attr.rail, name)


# ------------------------------------------------------------ coverage report -
class TestRegistration(unittest.TestCase):

    def setUp(self):
        self.registry = CapabilityRegistry()
        X.register(self.registry)
        self.report = self.registry.report()
        self.rows = self.report.by_tenet[Tenet.EXPLAINABILITY]

    def test_every_capability_of_the_tenet_is_accounted_for_exactly_once(self):
        names = [r.capability for r in self.rows]
        self.assertEqual(sorted(names),
                         sorted(self.registry.names(Tenet.EXPLAINABILITY)))
        self.assertEqual(len(names), len(set(names)))

    def test_the_honest_distribution_is_three_live_two_cloud_three_offline_one_gap(self):
        counts = self.report.counts(Tenet.EXPLAINABILITY)
        self.assertEqual(counts[Coverage.IMPLEMENTED], 3)
        self.assertEqual(counts[Coverage.CLOUD], 2)
        self.assertEqual(counts[Coverage.OFFLINE], 3)
        self.assertEqual(counts[Coverage.GAP], 1)
        self.assertEqual(counts[Coverage.DEPENDENCY], 0)
        self.assertEqual(sum(counts.values()), 9)

    def test_implemented_means_a_rail_that_actually_runs(self):
        live = {r.capability for r in self.rows
                if r.status is Coverage.IMPLEMENTED}
        self.assertEqual(live, {"Structured-output / schema validity",
                                "Deterministic format validators",
                                "Per-check confidence breakdown"})
        for row in self.rows:
            if row.status is Coverage.IMPLEMENTED:
                with self.subTest(capability=row.capability):
                    self.assertIsNotNone(row.attribution)
                    self.assertEqual(row.attribution.stage, int(Stage.STAGE_1))

    def test_the_batch_only_explainers_are_offline_and_say_where_they_belong(self):
        offline = {r.capability: r for r in self.rows
                   if r.status is Coverage.OFFLINE}
        self.assertEqual(set(offline), {"Feature attribution (SHAP)",
                                        "LIME local explanations",
                                        "Counterfactual / recourse analysis"})
        for capability, row in offline.items():
            with self.subTest(capability=capability):
                self.assertIn("references/", row.note)
        self.assertIn("explain endpoint", offline["Feature attribution (SHAP)"].note)

    def test_the_paid_judges_are_cloud_and_name_the_cost(self):
        cloud = {r.capability: r for r in self.rows if r.status is Coverage.CLOUD}
        self.assertEqual(set(cloud), {"Custom rubric judges (G-Eval)",
                                      "Token-level attribution"})
        self.assertIn("paid", cloud["Custom rubric judges (G-Eval)"].note)

    def test_the_gap_is_registered_as_a_gap_and_explains_itself(self):
        gap = [r for r in self.rows if r.status is Coverage.GAP]
        self.assertEqual([r.capability for r in gap],
                         ["Ban-topics / on-topic scope"])
        self.assertIn("NOT MOUNTED", gap[0].note)

    def test_a_configured_topic_rail_flips_the_gap_to_implemented(self):
        # The only thing that closes it is an actual lexicon, which is the point:
        # the status tracks reality, not intent.
        registry = CapabilityRegistry()
        configured = X.TopicScopeRail(
            allowed_topic_lexicons={"insurance": ["policy", "claim"]})
        X.register(registry, rails=list(X.RAILS) + [configured])
        rows = {r.capability: r for r in
                registry.report().by_tenet[Tenet.EXPLAINABILITY]}
        self.assertIs(rows["Ban-topics / on-topic scope"].status,
                      Coverage.IMPLEMENTED)
        self.assertEqual(registry.report().counts(Tenet.EXPLAINABILITY)[Coverage.GAP], 0)

    def test_a_configured_rubric_judge_flips_cloud_to_implemented(self):
        registry = CapabilityRegistry()
        judge = X.RubricJudgeRail(rubric="must cite a policy number",
                                  judge_model="gpt-4o")
        X.register(registry, rails=list(X.RAILS) + [judge])
        rows = {r.capability: r for r in
                registry.report().by_tenet[Tenet.EXPLAINABILITY]}
        self.assertIs(rows["Custom rubric judges (G-Eval)"].status,
                      Coverage.IMPLEMENTED)

    def test_registering_leaves_the_other_tenets_untouched(self):
        # Seven agents write seven packages; this one must not claim any of the
        # other six.
        for tenet, rows in self.report.by_tenet.items():
            if tenet is Tenet.EXPLAINABILITY:
                continue
            with self.subTest(tenet=tenet.value):
                self.assertTrue(all(r.status is Coverage.GAP for r in rows))

    def test_every_registration_carries_a_note_or_an_attribution(self):
        for row in self.rows:
            with self.subTest(capability=row.capability):
                self.assertTrue(row.note or row.attribution,
                                "a status with no justification is an assertion")

    def test_registering_an_unknown_capability_name_is_an_error(self):
        with self.assertRaises(KeyError):
            self.registry.register(Tenet.EXPLAINABILITY, "Feature attribution (SHAPP)",
                                   Coverage.IMPLEMENTED)

    def test_the_rendered_report_lists_the_gap(self):
        rendered = self.report.render()
        self.assertIn("Ban-topics / on-topic scope", rendered)
        self.assertIn(Tenet.EXPLAINABILITY.value, rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
