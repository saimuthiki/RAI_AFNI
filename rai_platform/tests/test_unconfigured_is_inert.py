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
        for k, v in self._saved.items():
            if v is not None:
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
        with self.assertNoLogs("afni_rai.gateway.app", logging.ERROR):
            create_app(warm=False, rails=[Clean(), PromptShieldsRail()],
                       attributions={},
                       env={"AFNI_CASCADE_ESCALATION": "full"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
