# -*- coding: utf-8 -*-
"""
Tests for the contract and the cascade engine.

These cover the invariants, not the happy path. Every test here corresponds to a
way the framework could quietly fail in production - most of them modelled on
failures actually found in the vendored source during the analysis.

Run: python3 -m unittest discover -s platform/tests -t .
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai.cascade.engine import Cascade  # noqa: E402
from afni_rai.cascade.rail import RailResult, Stage  # noqa: E402
from afni_rai.contract.models import (  # noqa: E402
    PROTOCOL_VERSION, Action, Decision, EventKind, Finding, GuardEvent,
    LLMProtocol, Severity, Span, Tenet, Verdict,
)


def event(payload=None, client_facing=True):
    return GuardEvent(
        kind=EventKind.REQUEST,
        step_id="step-1",
        agent_id="agent-1",
        agent_type="chat",
        agent_workspace="afni",
        agent_user="tester",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload=payload if payload is not None else {"text": "hello"},
        client_facing=client_facing,
    )


class FakeRail:
    """Minimal rail. Structural typing means it needs no base class."""

    def __init__(self, name, stage, result, tenet=Tenet.PRIVACY):
        self.name = name
        self.stage = stage
        self.tenet = tenet
        self._result = result
        self.calls = 0

    def check(self, path, text):
        self.calls += 1
        return self._result() if callable(self._result) else self._result


# ------------------------------------------------------------------ contract --
class TestContract(unittest.TestCase):

    def test_protocol_version_is_pinned(self):
        # Upstream is pre-1.0 and explicitly breaking. A bump must be a
        # deliberate reviewed change, so it fails a test rather than sliding in.
        self.assertEqual(PROTOCOL_VERSION, "0.8")

    def test_category_must_match_upstream_pattern(self):
        for good in ("privacy.pii.us_ssn", "security.injection.direct",
                     "safety.toxicity", "x.afni.custom_check"):
            with self.subTest(good=good):
                Finding(category=good)
        for bad in ("pii.ssn", "Privacy.pii", "privacy", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Finding(category=bad)

    def test_empty_category_segment_is_rejected_though_upstream_allows_it(self):
        # Upstream 0.8's pattern puts "." inside the character class, so
        # "safety..x" validates against it. Findings are grouped by category to
        # build the compliance evidence, so an empty segment would create a
        # garbage bucket in what AFNI hands a client reviewer. We reject it.
        for bad in ("safety..x", "privacy.pii..ssn", "security."):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Finding(category=bad)

    def test_score_bounds_and_span_order(self):
        Finding(category="privacy.pii.email", score=0.0)
        Finding(category="privacy.pii.email", score=1.0)
        with self.assertRaises(ValueError):
            Finding(category="privacy.pii.email", score=1.5)
        with self.assertRaises(ValueError):
            Finding(category="privacy.pii.email", start=10, end=4)

    def test_optional_fields_are_omitted_not_defaulted(self):
        # A cheap regex rail genuinely knows less than an LLM judge. Emitting
        # score=0.0 when nothing was scored would read as "scored zero".
        d = Finding(category="privacy.pii.email").to_dict()
        self.assertEqual(d, {"category": "privacy.pii.email"})

    def test_verdict_serialises_to_the_upstream_shape(self):
        v = Verdict(
            event_id="e1", provider="afni-rai-gateway", decision=Decision.BLOCK,
            findings=[Finding(category="privacy.pii.us_ssn", severity=Severity.HIGH,
                              action=Action.REDACT, score=0.91, detector="presidio")],
            modifications=[Span(path="payload.text", start=0, end=11,
                                replacement="[REDACTED]")],
            unjudged=["payload.attachment"],
        )
        d = v.to_dict()
        self.assertEqual(set(d) & {"event_id", "provider", "decision"},
                         {"event_id", "provider", "decision"})
        self.assertEqual(d["decision"], "block")
        self.assertIn("spans", d["modifications"])
        self.assertEqual(d["unjudged"], ["payload.attachment"])

    def test_could_not_judge_is_not_a_pass(self):
        clean = Verdict(event_id="e", provider="p", decision=Decision.ALLOW)
        self.assertFalse(clean.could_not_judge)
        blind = Verdict(event_id="e", provider="p", decision=Decision.ALLOW,
                        unjudged=["payload.text"])
        self.assertTrue(blind.could_not_judge)

    def test_texts_walks_nested_payloads(self):
        ev = event({"messages": [{"role": "user", "content": "hi"},
                                 {"role": "assistant", "content": "yo"}],
                    "meta": {"n": 3, "tag": "x"}})
        paths = ev.texts()
        self.assertEqual(paths["payload.messages[0].content"], "hi")
        self.assertEqual(paths["payload.messages[1].content"], "yo")
        self.assertEqual(paths["payload.meta.tag"], "x")
        # non-string leaves are skipped, not coerced to "3"
        self.assertNotIn("payload.meta.n", paths)


# ------------------------------------------------------------------- cascade --
class TestCascade(unittest.TestCase):

    def test_offline_rail_cannot_be_mounted_in_the_request_path(self):
        # Most of the reviewed repos are offline-only red-team tools. Putting one
        # inline would be a latency and cost incident, so it is a hard error.
        offline = FakeRail("garak", Stage.OFFLINE, RailResult.clean())
        with self.assertRaises(ValueError):
            Cascade([offline])

    def test_stage_1_block_short_circuits_later_stages(self):
        hit = Finding(category="privacy.pii.us_ssn", action=Action.BLOCK)
        s1 = FakeRail("regex", Stage.STAGE_1, RailResult(findings=[hit], block=True))
        s2 = FakeRail("classifier", Stage.STAGE_2, RailResult.clean())
        s3 = FakeRail("llm-judge", Stage.STAGE_3, RailResult.clean())
        out = Cascade([s1, s2, s3]).evaluate(event())

        self.assertIs(out.verdict.decision, Decision.BLOCK)
        self.assertEqual(s1.calls, 1)
        # The whole cost argument: the expensive stages were never paid for.
        self.assertEqual(s2.calls, 0, "stage 2 ran despite a stage 1 block")
        self.assertEqual(s3.calls, 0, "stage 3 ran despite a stage 1 block")
        self.assertTrue(out.trace[-1].short_circuited)

    def test_clean_stage_1_does_not_escalate(self):
        s1 = FakeRail("regex", Stage.STAGE_1, RailResult.clean())
        s2 = FakeRail("classifier", Stage.STAGE_2, RailResult.clean())
        out = Cascade([s1, s2]).evaluate(event())
        self.assertIs(out.verdict.decision, Decision.ALLOW)
        self.assertEqual(s2.calls, 0, "escalated with nothing to escalate about")

    def test_explicit_escalation_reaches_the_next_stage(self):
        s1 = FakeRail("regex", Stage.STAGE_1, RailResult(escalate=True))
        s2 = FakeRail("classifier", Stage.STAGE_2, RailResult.clean())
        Cascade([s1, s2]).evaluate(event())
        self.assertEqual(s2.calls, 1, "a rail asked for escalation and was ignored")

    def test_severe_finding_escalates_without_an_explicit_ask(self):
        severe = Finding(category="security.injection", severity=Severity.CRITICAL,
                         action=Action.FLAG)
        s1 = FakeRail("regex", Stage.STAGE_1, RailResult(findings=[severe]))
        s2 = FakeRail("classifier", Stage.STAGE_2, RailResult.clean())
        Cascade([s1, s2]).evaluate(event())
        self.assertEqual(s2.calls, 1)

    def test_unjudged_fails_closed_on_client_facing_traffic(self):
        blind = FakeRail("broken", Stage.STAGE_1, RailResult.unjudged("model absent"))
        out = Cascade([blind]).evaluate(event(client_facing=True))
        self.assertIs(out.verdict.decision, Decision.BLOCK)
        self.assertTrue(out.verdict.could_not_judge)
        self.assertEqual(out.verdict.unjudged, ["payload.text"])

    def test_unjudged_allows_on_internal_traffic_but_still_reports(self):
        blind = FakeRail("broken", Stage.STAGE_1, RailResult.unjudged("model absent"))
        out = Cascade([blind]).evaluate(event(client_facing=False))
        self.assertIs(out.verdict.decision, Decision.ALLOW)
        # Allowed, but never silently: the gap is still on the record.
        self.assertTrue(out.verdict.could_not_judge)

    def test_a_raising_rail_becomes_unjudged_not_clean(self):
        # This is the Infosys failure mode: their dispatcher wraps each check in
        # a broad try/except that logs and returns None, so one timeout silently
        # drops a check. Here it must surface as "could not look".
        def boom():
            raise RuntimeError("connection reset")

        class Exploding(FakeRail):
            def check(self, path, text):
                self.calls += 1
                boom()

        rail = Exploding("timeouts", Stage.STAGE_1, None)
        out = Cascade([rail]).evaluate(event(client_facing=True))
        self.assertIs(out.verdict.decision, Decision.BLOCK)
        self.assertEqual(out.verdict.unjudged, ["payload.text"])

    def test_findings_are_consolidated_into_one_verdict(self):
        # One consolidated verdict, not a raw list of rail outputs - one of the
        # three things the analysis says AFNI must build because NeMo does not.
        a = Finding(category="privacy.pii.email", action=Action.REDACT)
        b = Finding(category="privacy.pii.phone", action=Action.REDACT)
        s1 = FakeRail("regex-a", Stage.STAGE_1, RailResult(findings=[a], escalate=True))
        s2 = FakeRail("regex-b", Stage.STAGE_2, RailResult(findings=[b]))
        out = Cascade([s1, s2]).evaluate(event())
        self.assertEqual(len(out.verdict.findings), 2)
        self.assertEqual(out.stages_run, 2)

    def test_every_payload_string_is_judged(self):
        seen = []

        class Recorder(FakeRail):
            def check(self, path, text):
                seen.append(path)
                return RailResult.clean()

        rail = Recorder("rec", Stage.STAGE_1, None)
        Cascade([rail]).evaluate(event({"a": "one", "b": {"c": "two"}}))
        self.assertEqual(sorted(seen), ["payload.a", "payload.b.c"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestCascadeReporting(unittest.TestCase):
    """Two bugs that only surfaced when the cascade was run end-to-end with real
    rails, not in the unit tests above. Both are regressions worth pinning."""

    def test_stages_run_counts_executed_stages_not_trace_entries(self):
        # A clean request must not report "3 stages" just because the trace
        # records the two it skipped. Counting skipped stages as run inverts the
        # entire cost argument in the operator-facing output.
        s1 = FakeRail("regex", Stage.STAGE_1, RailResult.clean())
        s2 = FakeRail("classifier", Stage.STAGE_2, RailResult.clean())
        s3 = FakeRail("judge", Stage.STAGE_3, RailResult.clean())
        out = Cascade([s1, s2, s3]).evaluate(event())
        self.assertEqual(out.stages_run, 1, "skipped stages counted as run")
        self.assertEqual(out.stages_skipped, 2)
        self.assertEqual(len(out.trace), 3, "the trace should still record all three")

    def test_identical_findings_from_one_detector_are_deduped(self):
        # A rail with several patterns for one attack shape matches the same span
        # twice. The duplicate would inflate the count, appear twice in the
        # explanation, and double-count in the compliance rollup.
        dup = Finding(category="security.injection", path="payload.text",
                      start=0, end=10, detector="pyrit/static", action=Action.FLAG)
        rail = FakeRail("pyrit", Stage.STAGE_1, RailResult(findings=[dup, dup]))
        out = Cascade([rail]).evaluate(event())
        self.assertEqual(len(out.verdict.findings), 1)

    def test_two_different_detectors_on_one_span_are_kept_as_corroboration(self):
        a = Finding(category="security.injection", path="payload.text", start=0,
                    end=10, detector="pyrit/static", action=Action.FLAG)
        b = Finding(category="security.injection", path="payload.text", start=0,
                    end=10, detector="llm-guard/deberta", action=Action.FLAG)
        rail = FakeRail("both", Stage.STAGE_1, RailResult(findings=[a, b]))
        out = Cascade([rail]).evaluate(event())
        self.assertEqual(len(out.verdict.findings), 2,
                         "independent detectors agreeing is signal, not noise")
