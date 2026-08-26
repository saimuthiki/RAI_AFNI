# -*- coding: utf-8 -*-
"""
Tests for the Stage-2 warm-up.

Prompted by a measurement, not a theory: the first check on a freshly
provisioned machine took 15,568 ms, because three transformer models were being
constructed serially inside the request. The documented Stage-2 latency class is
10-500 ms, which is true of a warm model and wildly false of a cold one.

What is pinned here: warming never raises, a rail that cannot warm is reported
rather than fatal, and every Stage-2 rail actually exposes the hook - the last
one being the property that decays silently as rails are added.

Run: python3 rai_platform/run_tests.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai.cascade.rail import RailResult, Stage  # noqa: E402
from afni_rai.cli import load_tenets  # noqa: E402
from afni_rai.warmup import warm, warm_all  # noqa: E402


class _Rail:
    tenet = None
    stage = Stage.STAGE_2

    def __init__(self, name, behaviour):
        self.name = name
        self._behaviour = behaviour
        self.calls = 0

    def check(self, path, text):
        return RailResult.clean()

    def preload(self):
        self.calls += 1
        if self._behaviour == "raise":
            raise RuntimeError("weights are corrupt")
        return self._behaviour == "ok"


class _NoHook:
    name, tenet, stage = "stage1.regex", None, Stage.STAGE_1

    def check(self, path, text):
        return RailResult.clean()


class TestWarmingOneRail(unittest.TestCase):

    def test_a_successful_warm_is_reported(self):
        result = warm(_Rail("ok", "ok"))
        self.assertTrue(result.warmed)
        self.assertEqual(result.detail, "")

    def test_a_rail_that_cannot_warm_is_reported_not_raised(self):
        """Absent weights must degrade, not stop the gateway booting - the rail
        will report `unjudged` at request time and fail closed, which is the same
        honest behaviour as never having had the weights."""
        result = warm(_Rail("cold", "false"))
        self.assertFalse(result.warmed)
        self.assertIn("unjudged", result.detail)

    def test_a_raising_preload_is_caught(self):
        result = warm(_Rail("broken", "raise"))
        self.assertFalse(result.warmed)
        self.assertIn("RuntimeError", result.detail)
        self.assertIn("corrupt", result.detail)

    def test_a_rail_with_no_hook_is_skipped_not_poked(self):
        # Reaching into a private `_load` from the warm-up would break every time
        # a rail refactors. No hook means nothing to warm.
        result = warm(_NoHook())
        self.assertFalse(result.warmed)
        self.assertIn("nothing to warm", result.detail)


class TestWarmingEverything(unittest.TestCase):

    def test_each_rail_is_warmed_exactly_once(self):
        rails = [_Rail("a", "ok"), _Rail("b", "false"), _Rail("c", "raise")]
        results = warm_all(rails, log=False)
        self.assertEqual(len(results), 3)
        for rail in rails:
            self.assertEqual(rail.calls, 1, rail.name)

    def test_one_failure_does_not_stop_the_others(self):
        rails = [_Rail("a", "raise"), _Rail("b", "ok")]
        warmed = {r.rail: r.warmed for r in warm_all(rails, log=False)}
        self.assertFalse(warmed["a"])
        self.assertTrue(warmed["b"])

    def test_results_are_ordered_by_stage(self):
        rails = [_Rail("s2", "ok"), _NoHook()]
        order = [r.rail for r in warm_all(rails, log=False)]
        self.assertEqual(order, ["stage1.regex", "s2"])


class TestEveryStage2RailExposesTheHook(unittest.TestCase):
    """The property that decays silently. A Stage-2 rail added without a
    `preload` still works - it just quietly moves its model load back into the
    first request, which is exactly the regression this module exists to stop,
    and nothing else would notice."""

    def test_no_stage_2_rail_lacks_a_preload_hook(self):
        rails, _, problems = load_tenets()
        self.assertEqual(problems, [])
        missing = [r.name for r in rails
                   if r.stage is Stage.STAGE_2 and not callable(
                       getattr(r, "preload", None))]
        self.assertEqual(
            missing, [],
            "these Stage-2 rails will load their model inside the first "
            f"request: {missing}")

    def test_warming_the_real_rails_never_raises(self):
        rails, _, _ = load_tenets()
        results = warm_all(rails, log=False)
        self.assertEqual(len(results), len(rails))
        # Whatever is or is not installed on this machine, every rail must have
        # produced a result rather than an exception.
        for result in results:
            self.assertIsInstance(result.warmed, bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
