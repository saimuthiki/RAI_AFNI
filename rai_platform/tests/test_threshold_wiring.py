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
    RAIL_DEFAULTS, ThresholdOverrides, ThresholdStore,
)

TENET_PACKAGES = ("privacy", "security", "fairness", "explainability",
                  "content_safety", "hallucination", "accountability")

SYSTEM_PROMPT = ("You are AFNI's support assistant. Follow the escalation matrix. "
                 "Never disclose account balances. Always verify identity first.")
PARTIAL_ECHO = ("Follow the escalation matrix. Always verify identity first. "
                "Here is your answer.")


def response_event(text):
    return GuardEvent(
        kind=EventKind.RESPONSE, step_id="s", agent_id="a", agent_type="c",
        agent_workspace="afni", agent_user="u",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload={"choices": [{"message": {"role": "assistant", "content": text}}]})


def all_rails():
    rails = []
    for pkg in TENET_PACKAGES:
        mod = importlib.import_module(f"afni_rai.tenets.{pkg}")
        rails.extend(getattr(mod, "RAILS", []) or [])
    return rails


class TestAThresholdOverrideChangesTheDecision(unittest.TestCase):
    """The end-to-end proof, on a Stage-1 rail with no external dependency.

    This used to drive two TENANTS through one rail. The tenant dimension was
    removed, so the proof is now the same rail and the same payload at two
    CONFIGURED thresholds - which is what the assertion was always really about:
    a stored threshold that changes an outcome, rather than one that is merely
    stored and read.
    """

    def setUp(self):
        from afni_rai.tenets.privacy import SystemPromptLeakageRail
        self.rail = SystemPromptLeakageRail(system_prompt=SYSTEM_PROMPT)
        self.store = ThresholdStore()
        self.key = self.rail.THRESHOLD_KEY

    def configure(self, value):
        self.store.put_overrides(ThresholdOverrides(thresholds={self.key: value}))

    def decide(self):
        cascade = Cascade([self.rail], resolve_threshold=self.store.resolve_value)
        return cascade.evaluate(response_event(PARTIAL_ECHO))

    def test_the_same_payload_blocks_at_one_threshold_and_passes_at_another(self):
        # The whole point. Identical input, identical rail, opposite answers,
        # decided only by the configured threshold.
        self.configure(0.05)
        self.assertIs(self.decide().verdict.decision, Decision.BLOCK)
        self.configure(0.95)
        self.assertIs(self.decide().verdict.decision, Decision.ALLOW)

    def test_an_unconfigured_store_gets_the_ported_default(self):
        out = self.decide()
        read = [r for r in out.threshold_reads if r[0] == self.key][0]
        self.assertEqual(read[1], RAIL_DEFAULTS[self.key])

    def test_no_store_at_all_behaves_exactly_as_before_wiring(self):
        # A gateway built without a store must be unchanged by this feature.
        unwired = Cascade([self.rail]).evaluate(response_event(PARTIAL_ECHO))
        wired_default = self.decide()
        self.assertEqual(len(unwired.verdict.findings),
                         len(wired_default.verdict.findings))
        self.assertIs(unwired.verdict.decision, wired_default.verdict.decision)

    def test_the_threshold_that_decided_is_in_the_audit_trail(self):
        # "A threshold was applied" is not evidence. Which one, and where it came
        # from, is.
        self.configure(0.05)
        out = self.decide()
        read = [r for r in out.threshold_reads if r[0] == self.key][0]
        self.assertEqual(read, (self.key, 0.05, "resolved"))

    def test_a_misconfigured_threshold_falls_back_and_says_so(self):
        # A typo in the config must not take traffic down via
        # unjudged/fail-closed, but it must not pass silently either.
        self.configure(42.0)
        out = self.decide()
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




class TestTheResolvedThresholdReachesItsConsumer(unittest.TestCase):
    """Per rail, prove the resolved value reaches whatever actually decides.

    This class exists because of a real miss. The first version of this file
    proved a tenant override changed the outcome for exactly one rail
    (SystemPromptLeakageRail, which compares `score >= threshold` in its own
    body) and I generalised from it. An automated review then found three rails
    where the resolved threshold was computed, logged, and ignored:

      ToxicityClassifier and ZeroShotTopics  - llm-guard takes the threshold at
        CONSTRUCTION, and `scan()` returns a threshold-RELATIVE risk, so the
        local variable could never affect `valid`
      PresidioPiiRail - AnalyzerEngine was built with the constructor default and
        `analyze()` was called without a threshold, so no entity was ever dropped

    All three were the Safe Zone bug again, in the very commit that claimed to
    have fixed that class of bug. So the bar here is per-rail and mechanical: the
    threshold must demonstrably reach the consumer, for every rail that has one.
    """

    def store_with(self, key, value):
        store = ThresholdStore()
        store.put_overrides(ThresholdOverrides(thresholds={key: value}))
        return store

    def ctx_for(self, rail, value):
        store = self.store_with(rail.THRESHOLD_KEY, value)
        return CheckContext(resolve=store.resolve_value)

    # -- the two llm-guard scanners: the threshold must reach the CONSTRUCTOR ---
    def test_llm_guard_scanners_build_with_the_resolved_threshold(self):
        from afni_rai.tenets.content_safety import ToxicityClassifier, ZeroShotTopics
        for rail in (ToxicityClassifier(), ZeroShotTopics(topics=("weapons",))):
            with self.subTest(rail=rail.name):
                seen = []

                class Fake:
                    def scan(self, text):
                        return text, True, -1.0

                def fake_load(threshold=None, _seen=seen):
                    _seen.append(threshold)
                    return Fake()

                rail._load = fake_load
                rail.check("payload.text", "some text", self.ctx_for(rail, 0.23))
                self.assertEqual(
                    seen, [0.23],
                    f"{rail.name} did not pass the resolved threshold to its "
                    "scanner constructor - the tenant's value is decorative")

    # -- presidio: the threshold must reach analyze() AND drop entities ---------
    def test_presidio_passes_the_threshold_and_drops_low_scoring_entities(self):
        from afni_rai.tenets.privacy import PresidioPiiRail

        class Res:
            def __init__(self, score):
                self.entity_type, self.start, self.end, self.score = "US_SSN", 0, 11, score

        captured = {}

        class FakeEngine:
            def analyze(self, text, language, entities, score_threshold=None):
                captured["score_threshold"] = score_threshold
                # Deliberately ignores its own argument, so the per-finding
                # filter is what has to work.
                return [Res(0.40), Res(0.95)]

        rail = PresidioPiiRail()
        rail._engine = lambda: FakeEngine()

        loose = rail.check("payload.text", "123-45-6789", self.ctx_for(rail, 0.10))
        self.assertEqual(captured["score_threshold"], 0.10,
                         "the resolved threshold never reached analyze()")
        self.assertEqual(len(loose.findings), 2)

        strict = rail.check("payload.text", "123-45-6789", self.ctx_for(rail, 0.90))
        self.assertEqual(len(strict.findings), 1,
                         "tightening the threshold dropped no entity, so the "
                         "threshold is decorative")

    # -- the judge rails: score vs threshold decides the finding ----------------
    def test_judge_rails_respect_the_resolved_threshold(self):
        from afni_rai.tenets.content_safety import ToxicityJudge
        from afni_rai.tenets.privacy import PiiLeakageJudgeRail
        for rail in (ToxicityJudge(judge=lambda text: 0.55),
                     PiiLeakageJudgeRail(judge=lambda text: 0.55)):
            with self.subTest(rail=rail.name):
                lax = rail.check("payload.text", "x", self.ctx_for(rail, 0.90))
                strict = rail.check("payload.text", "x", self.ctx_for(rail, 0.10))
                self.assertEqual(
                    len(lax.findings), 0,
                    f"{rail.name}: a 0.55 score fired against a 0.90 threshold")
                self.assertGreater(
                    len(strict.findings), 0,
                    f"{rail.name}: a 0.55 score did not fire against a 0.10 "
                    "threshold, so the threshold is not consulted")

    # -- structural sweep: nothing may resolve a threshold and then ignore it ---
    def test_no_rail_resolves_a_threshold_it_then_ignores(self):
        """The generalisation guard.

        A rail that computes `threshold` and never mentions it again is the
        signature of the bug this class was written for. Requiring at least two
        references - the assignment plus one use - catches it without needing to
        understand each rail's internals.
        """
        offenders = []
        for rail in all_rails():
            key = getattr(type(rail), "THRESHOLD_KEY", None)
            if not key:
                continue
            src = inspect.getsource(type(rail).check)
            if "ctx.threshold(" not in src:
                continue
            uses = src.count("threshold")
            # assignment mentions it twice (local + ctx.threshold(...)), plus the
            # THRESHOLD_KEY reference; anything at or below that never used it.
            if uses <= 3:
                offenders.append((rail.name, uses))
        self.assertEqual(offenders, [],
                         f"these rails resolve a threshold and never use it: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
