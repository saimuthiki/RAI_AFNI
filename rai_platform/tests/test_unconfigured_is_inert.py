# -*- coding: utf-8 -*-
"""Does a rail nobody configured get to decide every verdict?

MEASURED ON AFNI'S HOST, with the local judge answering and both cloud keys
working. Two Live-check runs, one benign and one carrying PII, both came back:

    BLOCK - No finding blocked this. A payload path went unjudged, and that
    always fails closed - the block is the missing check, not a detection.

The unjudged rail was `security.prompt_shields`: Stage 3, Azure AI Content
Safety, and nobody there has an Azure key. It was mounted, it ran, it returned
`unjudged` on every call, and `unjudged` always blocks. Once Stage 2 began
looking at every undecided request and escalating on a flag, that was most
requests - a rail nobody bought was the verdict.

The console's own copy had already conceded the point: "they stay mounted, run,
and return could not judge - which fails closed WITHOUT PROTECTING ANYTHING."

THE DISTINCTION THAT FIXES IT is one the platform already drew twice. The
coverage report separates `cloud-not-configured` from `dependency-missing`. The
engine already skips a rail that does not apply to the event's direction -
"not run and not counted as coverage, and, crucially, does NOT contribute an
unjudged path". Upstream draws the same line in as many words:
`if (!API_KEY) emitAllow() // not configured -> inert, not degraded`
(references/openguardrails-main/.../hooks/ogr-hook.mjs:241).

So: UNCONFIGURED is inert - skipped per request, recorded as skipped, never
`unjudged`, listed on /healthz under its own key, and NOT a degradation.
A rail that IS configured and fails at call time is untouched: that is a fault,
and a fault still blocks. These tests hold both halves.

THE SAME GATE FOR THE JUDGE RAILS. The three Stage-3 LLM-judge rails had the
same shape as prompt_shields: with no judge bound they answered `unjudged`, so
a clone with no AFNI_JUDGE_PROVIDER blocked everything the moment Stage 3 was
reached - which is the one measured reason `full` could not be the default,
and `stage2` as the default is what allowed "tips for robbing a jewellery
store" at stages_run 2 with Stage 3 "never asked". Each judge rail now answers
`configured()` with "is a judge bound", the engine skips it when not, and
`full` is the default. A BOUND judge that fails at call time still blocks.
"""
from __future__ import annotations

import os
import unittest

from afni_rai.cascade.engine import Cascade, _unconfigured
from afni_rai.cascade.rail import Finding, RailResult, Stage
from afni_rai.contract.models import Decision, EventKind, GuardEvent, Tenet
from afni_rai.tenets.security import PromptShieldsRail

AZURE = (PromptShieldsRail.ENV_ENDPOINT, PromptShieldsRail.ENV_KEY)


def event(text: str = "What is the capital of France?") -> GuardEvent:
    return GuardEvent(
        kind=EventKind.REQUEST, step_id="s", agent_id="a", agent_type="chat",
        agent_workspace="w", agent_user="u", llm_protocol="openai.chat",
        payload={"messages": [{"role": "user", "content": text}]})


class Clean:
    """A Stage-1 rail so the cascade has something to run before Stage 3."""
    name, tenet, stage = "stub.clean", Tenet.PRIVACY, Stage.STAGE_1

    def check(self, path, text):
        return RailResult.clean()


class NoAzure(unittest.TestCase):
    """Every test here runs with the Azure variables ABSENT."""

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in AZURE}

    def tearDown(self):
        # Restore what was there, and REMOVE what a test set. Restoring only the
        # non-None values left a key a test had set behind, and test_security's
        # coverage rows then read prompt_shields as configured on any run where
        # this file happened to come first.
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TheProbeIsNarrow(NoAzure):

    def test_prompt_shields_without_a_key_is_unconfigured(self):
        self.assertTrue(_unconfigured(PromptShieldsRail()))

    def test_with_a_key_it_is_not(self):
        os.environ[AZURE[0]] = "https://x.cognitiveservices.azure.com/"
        os.environ[AZURE[1]] = "0" * 32
        self.assertFalse(_unconfigured(PromptShieldsRail()))

    def test_a_rail_with_no_configured_attribute_is_not_unconfigured(self):
        """The safe way round, as with the direction gate: an absent
        declaration must never silently REMOVE a check."""
        self.assertFalse(_unconfigured(Clean()))

    def test_a_configured_PROPERTY_is_not_read(self):
        """The schema and rubric rails use a `configured` property to mean
        "given something to check against" - a per-request applicability fact,
        not a credential. Reading it here would unmount rails this change has
        no business touching."""
        class WithProperty:
            @property
            def configured(self):
                return False
        self.assertFalse(_unconfigured(WithProperty()))

    def test_a_probe_that_raises_does_not_decide_a_verdict(self):
        class Broken:
            def configured(self):
                raise RuntimeError("boom")
        self.assertFalse(_unconfigured(Broken()))

    def test_it_is_not_available_and_not_dependency_available(self):
        """Those two mean a package or weights are MISSING on a host where the
        rail was meant to run. That is a fault, and a fault must still block.
        The stage-2 classifiers report through them, and if this probe read
        them, a fresh install with no weights would silently allow everything -
        the exact failure `unjudged` exists to prevent."""
        class MissingWeights:
            def available(self):
                return False
            def dependency_available(self):
                return False
        self.assertFalse(_unconfigured(MissingWeights()))


class TheEngineSkipsItAndDoesNotBlock(NoAzure):

    def test_a_benign_request_reaching_stage_3_is_allowed(self):
        """THE MEASURED FAILURE, reversed. Under `full` every undecided request
        reaches Stage 3; before this change that made prompt_shields block all
        of them."""
        out = Cascade([Clean(), PromptShieldsRail()],
                      escalation="full").evaluate(event())
        self.assertIs(out.verdict.decision, Decision.ALLOW)
        self.assertEqual(out.verdict.unjudged, [],
                         "an unconfigured optional rail became an unjudged path")

    def test_it_is_recorded_as_skipped_not_as_run(self):
        """Inert is not invisible. The trace names it, so the console can show
        "did not apply" rather than pretending the capability is on."""
        out = Cascade([Clean(), PromptShieldsRail()],
                      escalation="full").evaluate(event())
        stage3 = next(t for t in out.trace if t.stage is Stage.STAGE_3)
        self.assertIn(PromptShieldsRail.name, stage3.rails_skipped)
        self.assertNotIn(PromptShieldsRail.name, stage3.rails_run)

    def test_a_configured_rail_that_fails_at_call_time_still_blocks(self):
        """THE HALF THAT MUST NOT MOVE. A key is set, so the rail is meant to
        run; the endpoint is unreachable, so it cannot. That is a fault, and a
        fault reports unjudged and fails closed."""
        os.environ[AZURE[0]] = "http://127.0.0.1:9/"       # nothing listens
        os.environ[AZURE[1]] = "0" * 32
        out = Cascade([Clean(), PromptShieldsRail(timeout=0.2)],
                      escalation="full").evaluate(event())
        self.assertIs(out.verdict.decision, Decision.BLOCK)
        self.assertTrue(out.verdict.unjudged)

    def test_the_rails_own_check_is_unchanged(self):
        """`test_security` pins that `check()` returns unjudged without a key.
        The gate lives in the engine; the rail still tells the truth when asked
        directly."""
        result = PromptShieldsRail().check("payload.text", "anything")
        self.assertFalse(result.judged)


class HealthzTellsTheTruthAboutIt(NoAzure):

    def client(self):
        from fastapi.testclient import TestClient

        from afni_rai.gateway.app import create_app
        os.environ.setdefault("AFNI_AUDIT_DB", ":memory:")
        return TestClient(create_app(warm=False,
                                     rails=[Clean(), PromptShieldsRail()],
                                     attributions={}, env={}))

    def test_it_is_listed_under_its_own_key(self):
        body = self.client().get("/healthz").json()
        self.assertIn(PromptShieldsRail.name, body["rails_not_configured"])

    def test_it_is_not_in_the_unavailable_list(self):
        body = self.client().get("/healthz").json()
        self.assertEqual([r for r in body["rails_unavailable"]
                          if PromptShieldsRail.name in r], [])

    def test_it_alone_does_not_make_the_gateway_degraded(self):
        """`degraded` is the loudest line in the product. It was on for every
        install without an Azure key - which so far is every install - and a
        warning on every healthy machine is a warning nobody reads."""
        body = self.client().get("/healthz").json()
        self.assertEqual(body["status"], "ok", body)

    def test_v1_rails_still_shows_it_as_unavailable_with_the_reason(self):
        """Not hidden. An operator reading the rail list must still see that
        the capability is off and why."""
        rows = self.client().get("/v1/rails").json()
        rows = rows if isinstance(rows, list) else rows["rails"]
        row = next(r for r in rows if r["name"] == PromptShieldsRail.name)
        self.assertFalse(row["available"])


class TheFullModeWarningNoLongerCountsIt(NoAzure):

    def test_no_blind_rail_error_for_a_skipped_one(self):
        """My own startup check called an unconfigured Stage-3 rail "blind" and
        promised EVERY REQUEST WILL BLOCK. That was true before the gate and is
        false after it; a startup ERROR that is false is worse than none."""
        import logging

        from afni_rai.gateway.app import create_app
        os.environ.setdefault("AFNI_AUDIT_DB", ":memory:")
        with self.assertNoLogs("afni_rai.gateway", logging.ERROR):
            create_app(warm=False, rails=[Clean(), PromptShieldsRail()],
                       attributions={},
                       env={"AFNI_CASCADE_ESCALATION": "full"})



# --------------------------------------------------------------------------- #
# The judge rails take the same gate                                          #
# --------------------------------------------------------------------------- #
def _judge_rails():
    """(name, unbound rail, bound-and-raising rail) for every judge rail whose
    package imports here. The omnibus moderation rail is optional: its
    `configured()` is owned elsewhere, and a test that cannot import it skips
    rather than pins a file this one does not own."""
    from afni_rai.tenets.content_safety import ToxicityJudge
    from afni_rai.tenets.privacy import PiiLeakageJudgeRail

    def boom(_text):
        raise RuntimeError("judge chain down")

    rows = [
        ("toxicity", ToxicityJudge(), ToxicityJudge(judge=boom)),
        ("pii_leakage", PiiLeakageJudgeRail(), PiiLeakageJudgeRail(judge=boom)),
    ]
    try:
        from afni_rai.tenets.moderation import OmnibusJudgeRail
    except ImportError:                                   # pragma: no cover
        return rows
    def boom2(_text):
        raise RuntimeError("judge chain down")
    omnibus_bound = OmnibusJudgeRail()
    omnibus_bound.judge = boom2
    if callable(getattr(OmnibusJudgeRail(), "configured", None)):
        rows.append(("omnibus", OmnibusJudgeRail(), omnibus_bound))
    return rows


class TheJudgeRailsAreUnconfiguredWithoutAJudge(unittest.TestCase):

    def test_configured_is_whether_a_judge_is_bound(self):
        for name, unbound, bound in _judge_rails():
            with self.subTest(rail=name):
                self.assertFalse(unbound.configured())
                self.assertTrue(bound.configured())

    def test_the_engine_probe_agrees(self):
        for name, unbound, bound in _judge_rails():
            with self.subTest(rail=name):
                self.assertTrue(_unconfigured(unbound))
                self.assertFalse(_unconfigured(bound))

    def test_available_is_unchanged(self):
        """The console and coverage report still read `available()`, and it
        still answers the same question."""
        for name, unbound, bound in _judge_rails():
            with self.subTest(rail=name):
                self.assertFalse(unbound.available())
                self.assertTrue(bound.available())

    def test_the_rails_own_check_still_says_unjudged(self):
        """The gate lives in the engine. Asked directly, an unbound judge rail
        tells the truth: it could not judge."""
        for name, unbound, _ in _judge_rails():
            with self.subTest(rail=name):
                self.assertFalse(unbound.check("payload.text", "anything").judged)


class TheEngineSkipsAnUnboundJudgeRail(unittest.TestCase):
    """`full` is the default. A fresh clone has no judge. Every request that
    Stage 1 does not block reaches Stage 3, and it must NOT block there."""

    def test_a_benign_request_is_allowed_with_no_unjudged_path(self):
        for name, unbound, _ in _judge_rails():
            with self.subTest(rail=name):
                out = Cascade([Clean(), unbound]).evaluate(event())
                self.assertIs(out.verdict.decision, Decision.ALLOW)
                self.assertEqual(out.verdict.unjudged, [],
                                 f"an unbound {name} judge became an unjudged path")
                self.assertEqual(out.verdict.findings, [])

    def test_it_is_recorded_as_skipped_not_run_and_stage_3_still_happens(self):
        for name, unbound, _ in _judge_rails():
            with self.subTest(rail=name):
                out = Cascade([Clean(), unbound]).evaluate(event())
                stage3 = next(t for t in out.trace if t.stage is Stage.STAGE_3)
                self.assertIn(unbound.name, stage3.rails_skipped)
                self.assertNotIn(unbound.name, stage3.rails_run)

    def test_all_three_at_once_still_allow(self):
        rails = [Clean()] + [unbound for _, unbound, _ in _judge_rails()]
        out = Cascade(rails).evaluate(event())
        self.assertIs(out.verdict.decision, Decision.ALLOW)
        self.assertEqual(out.verdict.unjudged, [])

    def test_a_bound_judge_that_fails_at_call_time_still_blocks(self):
        """THE HALF THAT MUST NOT MOVE. A judge is bound, so the rail is meant to
        run; the chain is down, so it cannot. Fault -> unjudged -> fail closed."""
        for name, _, bound in _judge_rails():
            with self.subTest(rail=name):
                out = Cascade([Clean(), bound]).evaluate(event())
                self.assertIs(out.verdict.decision, Decision.BLOCK)
                self.assertTrue(out.verdict.unjudged)

    def test_a_bound_judge_that_returns_unjudged_still_blocks(self):
        """Bound, ran, and answered something the rail cannot use - a score
        outside [0, 1]. The rail says `unjudged`; the engine fails closed."""
        from afni_rai.tenets.privacy import PiiLeakageJudgeRail

        rail = PiiLeakageJudgeRail(judge=lambda _t: 7.0)
        self.assertTrue(rail.configured())
        out = Cascade([Clean(), rail]).evaluate(event())
        stage3 = next(t for t in out.trace if t.stage is Stage.STAGE_3)
        self.assertIn(rail.name, stage3.rails_run)
        self.assertIs(out.verdict.decision, Decision.BLOCK)
        self.assertTrue(out.verdict.unjudged)


class RailAvailableAsksConfiguredFirst(unittest.TestCase):
    """`gateway.app._rail_available` used to return the FIRST probe found, in the
    order dependency_available / available / configured. A judge rail answers
    `available()` and `configured()` identically, so it would have reported
    "available() is False" - and every exclusion keyed on the string
    "configured() is False" (the /healthz split, the full-mode blind check)
    would never have fired for it."""

    def setUp(self):
        from afni_rai.gateway.app import _rail_available
        self.probe = _rail_available

    def test_both_false_reports_configured(self):
        class Rail:
            def available(self): return False
            def configured(self): return False
        self.assertEqual(self.probe(Rail()), (False, "configured() is False"))

    def test_dependency_and_configured_both_false_reports_configured(self):
        class Rail:
            def dependency_available(self): return False
            def configured(self): return False
        self.assertEqual(self.probe(Rail()), (False, "configured() is False"))

    def test_configured_true_and_available_false_reports_available(self):
        class Rail:
            def available(self): return False
            def configured(self): return True
        self.assertEqual(self.probe(Rail()), (False, "available() is False"))

    def test_configured_true_and_dependency_false_reports_dependency(self):
        """When `configured()` passes, the original order is untouched."""
        class Rail:
            def dependency_available(self): return False
            def available(self): return True
            def configured(self): return True
        self.assertEqual(self.probe(Rail()),
                         (False, "dependency_available() is False"))

    def test_only_configured_behaves_as_before(self):
        class Off:
            def configured(self): return False
        class On:
            def configured(self): return True
        self.assertEqual(self.probe(Off()), (False, "configured() is False"))
        self.assertEqual(self.probe(On()), (True, None))

    def test_a_configured_property_is_not_called(self):
        """The schema and rubric rails carry a `configured` PROPERTY. It is not
        callable and must not be treated as the probe."""
        class Rail:
            configured = False
            def available(self): return True
        self.assertEqual(self.probe(Rail()), (True, None))

    def test_a_raising_configured_is_reported_not_raised(self):
        class Rail:
            def configured(self): raise RuntimeError("boom")
        ok, why = self.probe(Rail())
        self.assertFalse(ok)
        self.assertIn("configured() raised", why)

    def test_the_real_judge_rails_report_configured(self):
        for name, unbound, bound in _judge_rails():
            with self.subTest(rail=name):
                self.assertEqual(self.probe(unbound), (False, "configured() is False"))
                self.assertEqual(self.probe(bound)[0], True)


class HealthzTreatsAnUnboundJudgeRailAsNotConfigured(NoAzure):

    def client(self, env=None):
        from fastapi.testclient import TestClient

        from afni_rai.gateway.app import create_app
        from afni_rai.tenets.content_safety import ToxicityJudge
        from afni_rai.tenets.privacy import PiiLeakageJudgeRail
        os.environ.setdefault("AFNI_AUDIT_DB", ":memory:")
        return TestClient(create_app(
            warm=False, rails=[Clean(), ToxicityJudge(), PiiLeakageJudgeRail()],
            attributions={}, env=env or {}))

    def test_they_are_listed_under_rails_not_configured(self):
        body = self.client().get("/healthz").json()
        for name in ("content_safety.toxicity_judge", "privacy.pii_leakage_judge"):
            with self.subTest(rail=name):
                self.assertIn(name, body["rails_not_configured"])
                self.assertEqual([r for r in body["rails_unavailable"] if name in r], [])

    def test_they_are_still_named_as_judge_rails_without_a_judge(self):
        body = self.client().get("/healthz").json()
        self.assertIn("content_safety.toxicity_judge",
                      body["judge_rails_without_a_judge"])

    def test_they_do_not_make_the_gateway_degraded(self):
        body = self.client().get("/healthz").json()
        self.assertEqual(body["status"], "ok", body)

    def test_a_request_through_the_gateway_is_allowed_under_the_default(self):
        """The whole point, end to end: default escalation, no judge, benign
        request -> allow, Stage 3 visited, nothing unjudged."""
        from afni_rai.cascade.engine import DEFAULT_ESCALATION
        self.assertEqual(DEFAULT_ESCALATION, "full")
        payload = self.client().post("/v1/guard", json={
            "kind": "step/request", "step_id": "s", "agent_id": "a",
            "agent_type": "chat", "agent_workspace": "w", "agent_user": "u",
            "llm_protocol": "openai.chat",
            "payload": {"messages": [{"role": "user",
                                      "content": "What is the capital of France?"}]},
        }).json()
        self.assertEqual(payload["verdict"]["decision"], "allow", payload)
        # An empty `unjudged` is omitted on the wire; either spelling is "none".
        self.assertEqual(payload["verdict"].get("unjudged", []), [])


class StartupSaysStageThreeHasNoJudge(NoAzure):

    def _create(self, env):
        from afni_rai.gateway.app import create_app
        from afni_rai.tenets.content_safety import ToxicityJudge
        os.environ.setdefault("AFNI_AUDIT_DB", ":memory:")
        return create_app(warm=False, rails=[Clean(), ToxicityJudge()],
                          attributions={}, env=env)

    def test_full_with_no_judge_warns_and_names_the_fix(self):
        import logging
        with self.assertLogs("afni_rai.gateway", logging.WARNING) as logs:
            self._create({"AFNI_CASCADE_ESCALATION": "full"})
        joined = "\n".join(logs.output)
        self.assertIn("AFNI_JUDGE_PROVIDER", joined)
        self.assertIn("content_safety.toxicity_judge", joined)
        self.assertIn("CONTRIBUTES NOTHING", joined)

    def test_it_is_a_warning_not_the_blind_error(self):
        """An unbound judge rail is skipped, not blind. The ERROR that promises
        EVERY REQUEST WILL BLOCK must not fire for it."""
        import logging
        with self.assertNoLogs("afni_rai.gateway", logging.ERROR):
            self._create({"AFNI_CASCADE_ESCALATION": "full"})

    def test_under_stage2_there_is_no_such_warning(self):
        import logging
        logger = logging.getLogger("afni_rai.gateway")
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        try:
            self._create({"AFNI_CASCADE_ESCALATION": "stage2"})
        finally:
            logger.removeHandler(handler)
        self.assertEqual([r.getMessage() for r in records
                          if "CONTRIBUTES NOTHING" in r.getMessage()], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
