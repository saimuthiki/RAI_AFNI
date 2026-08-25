# -*- coding: utf-8 -*-
"""Per-tenant thresholds must be READ on the decision path AND change the answer.

Reading a threshold is not the bar. Safe Zone reads its config too - `admin.go:66`
writes BlockThreshold/AllowThreshold and busts the cache, and then
`guardrails.go:287` calls `getBlockThreshold()`, which returns an env global with
a hardcoded 0.85. The value is stored, exposed through an admin API, logged, and
never able to alter a single decision. Infosys does the same with its per-account
ModerationCheckThreshold.

So every test here asserts an OUTCOME difference, not a read.

Run: python3 rai_platform/tests/test_threshold_wiring.py
"""
import importlib
import inspect
import os
import pathlib
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai.cascade.engine import Cascade  # noqa: E402
from afni_rai.cascade.rail import CheckContext, Stage  # noqa: E402
from afni_rai.contract.models import (  # noqa: E402
    Decision, EventKind, GuardEvent, LLMProtocol,
)
from afni_rai.tenets.accountability.thresholds import (  # noqa: E402
    RAIL_DEFAULTS, TenantConfig, ThresholdStore,
)

TENET_PACKAGES = ("privacy", "security", "fairness", "explainability",
                  "content_safety", "hallucination", "accountability")

SYSTEM_PROMPT = ("You are AFNI's support assistant. Follow the escalation matrix. "
                 "Never disclose account balances. Always verify identity first.")
PARTIAL_ECHO = ("Follow the escalation matrix. Always verify identity first. "
                "Here is your answer.")


def response_event(text, tenant=None):
    return GuardEvent(
        kind=EventKind.RESPONSE, step_id="s", agent_id="a", agent_type="c",
        agent_workspace="afni", agent_user="u",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload={"choices": [{"message": {"role": "assistant", "content": text}}]},
        client_facing=True, tenant=tenant)


def all_rails():
    rails = []
    for pkg in TENET_PACKAGES:
        mod = importlib.import_module(f"afni_rai.tenets.{pkg}")
        rails.extend(getattr(mod, "RAILS", []) or [])
    return rails


class TestATenantOverrideChangesTheDecision(unittest.TestCase):
    """The end-to-end proof, on a Stage-1 rail with no external dependency."""

    def setUp(self):
        from afni_rai.tenets.privacy import SystemPromptLeakageRail
        self.rail = SystemPromptLeakageRail(system_prompt=SYSTEM_PROMPT)
        self.store = ThresholdStore()
        self.key = self.rail.THRESHOLD_KEY
        self.store.put_tenant(TenantConfig(tenant="strict", thresholds={self.key: 0.05}))
        self.store.put_tenant(TenantConfig(tenant="lax", thresholds={self.key: 0.95}))

    def decide(self, tenant):
        cascade = Cascade([self.rail], resolve_threshold=self.store.resolve_value)
        return cascade.evaluate(response_event(PARTIAL_ECHO, tenant))

    def test_the_same_payload_blocks_for_one_tenant_and_passes_for_another(self):
        # The whole point. Identical input, identical rail, opposite answers,
        # decided only by the tenant's configured threshold.
        self.assertIs(self.decide("strict").verdict.decision, Decision.BLOCK)
        self.assertIs(self.decide("lax").verdict.decision, Decision.ALLOW)

    def test_an_unconfigured_tenant_gets_the_ported_default(self):
        out = self.decide("nobody-configured-me")
        read = [r for r in out.threshold_reads if r[0] == self.key][0]
        self.assertEqual(read[1], RAIL_DEFAULTS[self.key])

    def test_no_store_at_all_behaves_exactly_as_before_wiring(self):
        # A gateway built without a store must be unchanged by this feature.
        unwired = Cascade([self.rail]).evaluate(response_event(PARTIAL_ECHO))
        wired_default = self.decide(None)
        self.assertEqual(len(unwired.verdict.findings),
                         len(wired_default.verdict.findings))
        self.assertIs(unwired.verdict.decision, wired_default.verdict.decision)

    def test_the_threshold_that_decided_is_in_the_audit_trail(self):
        # "A threshold was applied" is not evidence. Which one, and where it came
        # from, is.
        out = self.decide("strict")
        read = [r for r in out.threshold_reads if r[0] == self.key][0]
        self.assertEqual(read, (self.key, 0.05, "resolved"))

    def test_a_misconfigured_threshold_falls_back_and_says_so(self):
        # A typo in one tenant's config must not take that tenant's traffic down
        # via unjudged/fail-closed, but it must not pass silently either.
        self.store.put_tenant(TenantConfig(tenant="typo", thresholds={self.key: 42.0}))
        out = self.decide("typo")
        read = [r for r in out.threshold_reads if r[0] == self.key][0]
        self.assertEqual(read[1], RAIL_DEFAULTS[self.key])
        self.assertIn("resolver-error", read[2])
        self.assertTrue(self.store.audit(), "audit() must surface the bad value")


class TestEveryThresholdRailIsWired(unittest.TestCase):
    """Guards against a rail keeping a private threshold nothing can override."""

    def rails_with_a_threshold(self):
        out = []
        for rail in all_rails():
            init = inspect.signature(type(rail).__init__).parameters
            if any("threshold" in name for name in init):
                out.append(rail)
        return out

    def test_every_threshold_bearing_rail_declares_a_key(self):
        missing = [r.name for r in self.rails_with_a_threshold()
                   if not getattr(type(r), "THRESHOLD_KEY", None)
                   and "thresholds" not in inspect.signature(
                       type(r).__init__).parameters]
        self.assertEqual(missing, [],
                         f"these rails have a threshold nothing can override: {missing}")

    def test_every_declared_key_has_a_default(self):
        from afni_rai.tenets.accountability.thresholds import GLOBAL_DEFAULTS
        known = set(RAIL_DEFAULTS) | set(GLOBAL_DEFAULTS)
        for rail in all_rails():
            key = getattr(type(rail), "THRESHOLD_KEY", None)
            if key:
                with self.subTest(rail=rail.name):
                    self.assertIn(key, known,
                                  f"{rail.name} resolves {key!r}, which has no "
                                  "default - it would silently get last-resort 0.85")

    def test_every_threshold_rail_accepts_a_context(self):
        cascade = Cascade([r for r in all_rails() if r.stage is not Stage.OFFLINE])
        for rail in self.rails_with_a_threshold():
            if rail.stage is Stage.OFFLINE:
                continue
            with self.subTest(rail=rail.name):
                self.assertTrue(
                    cascade._wants_ctx.get(rail.name),
                    f"{rail.name} has a threshold but the engine cannot pass it a "
                    "context, so the threshold is unreachable")

    def test_the_declared_keys_are_mechanism_specific(self):
        # A classifier probability, an NLI entailment score and a judge's
        # self-report are not one scale. One shared "toxicity" knob would let an
        # operator tighten a classifier and unknowingly loosen a judge.
        keys = [getattr(type(r), "THRESHOLD_KEY", None) for r in all_rails()]
        keys = [k for k in keys if k]
        self.assertEqual(len(keys), len(set(keys)),
                         f"two rails share a threshold key: {keys}")


class TestConsumerCount(unittest.TestCase):
    """Replaces the earlier honesty test, which asserted exactly one consumer.

    That test existed because the store was write-only. It has served its purpose
    and its assertion is now inverted: the floor is what matters, not the ceiling.
    """

    def test_every_threshold_bearing_rail_resolves_through_a_store(self):
        # Counts RAILS, not files - an earlier version of this test counted
        # source files and read 7 where the answer is 11, which is the kind of
        # metric that quietly overstates coverage.
        rails = [r for r in all_rails()
                 if any("threshold" in n for n in
                        inspect.signature(type(r).__init__).parameters)]
        unwired = []
        for rail in rails:
            src = inspect.getsource(type(rail).check)
            if "ctx.threshold(" not in src and "thresholds.resolve(" not in src:
                unwired.append(rail.name)
        self.assertEqual(unwired, [],
                         f"these rails hold a threshold nothing can override: {unwired}")
        # 9 of the 11 threshold-bearing rails are MOUNTED; the two judge rails
        # (fairness generative-bias, explainability rubric) sit unmounted in
        # CLOUD_RAILS because an always-unjudged Stage-3 rail would fail-closed
        # every escalated request. They are checked separately below.
        self.assertGreaterEqual(len(rails), 9,
                                f"expected >=9 mounted threshold rails, found {len(rails)}")

    def test_the_unmounted_judge_rails_are_wired_too(self):
        # Wired before mounting, so enabling one is a config change and not a
        # code change that quietly ships an unoverridable threshold.
        from afni_rai.tenets.explainability import RubricJudgeRail
        from afni_rai.tenets.fairness import GenerativeBiasJudgeRail
        for cls in (RubricJudgeRail, GenerativeBiasJudgeRail):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(getattr(cls, "THRESHOLD_KEY", None))
                self.assertIn("ctx.threshold(", inspect.getsource(cls.check))


if __name__ == "__main__":
    unittest.main(verbosity=2)
