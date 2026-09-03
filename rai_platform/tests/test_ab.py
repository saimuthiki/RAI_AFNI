# -*- coding: utf-8 -*-
"""Guardrails off versus on.

AFNI asked for a before-and-after attack success rate to show as a demo. These
tests pin the four claims that would make it dishonest if they broke:

  * THE OFF ARM IS 100% BY DEFINITION, not by running an empty cascade. An empty
    cascade reports 100% BLOCKED - every path comes back `unjudged` and unjudged
    fails closed - which is the exact opposite. That trap has a test of its own.
  * EVERY ARM SEES THE SAME RECORDS. Re-drawing per arm would make the delta
    between two arms partly a sampling artefact, and on a corpus that is 42%
    content-safety a re-draw moves a rate by points.
  * AN ARM WITH A MISSING RAIL IS MARKED A FLOOR. On a host with no model
    weights the Stage-2 rung looks like a measurement and is not one.
  * THE LATENCY IS THE WARM NUMBER. Without a warm-up the Stage-2 rung's mean
    included spaCy's model load - measured as median 0.61 ms against a max of
    4644 ms, one record carrying the whole thing.
"""
from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai import ab, regression                              # noqa: E402
from afni_rai.cascade.rail import Stage                          # noqa: E402
from afni_rai.cli import load_tenets                             # noqa: E402

try:
    from fastapi.testclient import TestClient
    from afni_rai.gateway.app import create_app
    _HAVE_FASTAPI = True
except Exception:                                                # noqa: BLE001
    _HAVE_FASTAPI = False

_RAILS, _ATTRS, _PROBLEMS = load_tenets()


def _sample(n=40, seed=0, direction=None):
    records = regression.load()
    selection = regression.Selection(limit=n, seed=seed, direction=direction)
    return selection, regression.select(records, selection)


class TheOffArm(unittest.TestCase):
    """The framing that was wrong the first time."""

    def test_off_delivers_everything(self):
        _sel, records = _sample(30)
        arm = ab._off_arm(records)
        self.assertEqual(arm.delivered, len(records))
        self.assertEqual(arm.stopped, 0)
        self.assertEqual(arm.delivery_rate, 1.0)
        self.assertEqual(arm.rails, 0)

    def test_off_costs_nothing_to_compute(self):
        _sel, records = _sample(30)
        self.assertEqual(ab._off_arm(records).elapsed_ms, 0.0)

    def test_an_empty_cascade_allows_everything_and_unjudged_does_not_save_you(self):
        """The assumption that was wrong, now checked instead of repeated.

        It seemed obvious that an empty cascade would fail closed and block
        everything. It does not, and the reason matters well beyond this module:
        `unjudged` is populated only when a rail RUNS and cannot judge - the
        `if not result.judged` in `engine.py` sits inside the per-rail loop - so
        with zero rails nothing is unjudged, fail-closed never fires, and every
        message is allowed.

        FAIL-CLOSED PROTECTS AGAINST A RAIL THAT TRIED AND FAILED, NOT AGAINST A
        RAIL THAT WAS NEVER MOUNTED. This test pins that so nobody reasons from
        the comfortable assumption again, and `Gateway.__init__` logs a CRITICAL
        when nothing is mounted at Stage 1 because a log line is the only thing
        standing between an empty mount and silent allow-all.
        """
        from afni_rai.cascade.engine import Cascade
        _sel, records = _sample(5)
        cascade = Cascade([])
        results = [regression.judge(cascade, r) for r in records]
        self.assertEqual({r["decision"] for r in results}, {"allow"})
        self.assertEqual([r["unjudged"] for r in results], [False] * len(results),
                         "nothing was marked unjudged, which is exactly the gap")

    def test_the_gateway_shouts_when_nothing_is_mounted_at_stage_1(self):
        import logging
        from afni_rai.gateway.app import Gateway
        with self.assertLogs("afni_rai", level=logging.CRITICAL) as caught:
            Gateway(rails=[])
        self.assertTrue(any("no Stage-1 rail" in line for line in caught.output),
                        f"expected a CRITICAL naming the gap, got {caught.output}")


class TheLadder(unittest.TestCase):

    def setUp(self):
        self.selection, self.records = _sample(40)

    def test_arms_are_in_ascending_order_starting_at_off(self):
        result = ab.compare(_RAILS, self.records, "test", "stage_1_only",
                            max_stage=2)
        self.assertEqual([a.name for a in result.arms],
                         ["off", "stage_1", "stage_1_2"])
        self.assertEqual([a.ceiling for a in result.arms], [0, 1, 2])

    def test_every_arm_sees_the_same_records(self):
        result = ab.compare(_RAILS, self.records, "test", "stage_1_only",
                            max_stage=2)
        sizes = {a.sample for a in result.arms}
        self.assertEqual(sizes, {len(self.records)},
                         "a differing sample size makes the delta a sampling "
                         "artefact")

    def test_stopped_plus_delivered_is_the_sample(self):
        result = ab.compare(_RAILS, self.records, "test", "stage_1_only",
                            max_stage=2)
        for arm in result.arms:
            with self.subTest(arm=arm.name):
                self.assertEqual(arm.stopped + arm.delivered, arm.sample)

    def test_a_higher_rung_never_stops_fewer(self):
        # Monotone by construction: each rung is a superset of the rails below
        # it, and a rail can only add a block. A violation means the cascade is
        # short-circuiting something it should not.
        result = ab.compare(_RAILS, self.records, "test", "stage_1_only",
                            max_stage=2)
        stops = [a.stopped for a in result.arms]
        self.assertEqual(stops, sorted(stops))

    def test_max_stage_1_gives_two_rungs(self):
        result = ab.compare(_RAILS, self.records, "test", "stage_1_only",
                            max_stage=1)
        self.assertEqual([a.name for a in result.arms], ["off", "stage_1"])

    def test_stage_3_is_dropped_not_duplicated_when_cloud_is_off(self):
        # Dropped rather than downgraded to a copy of Stage 2: a flat rung would
        # read as "Stage 3 adds nothing", which is a claim nobody measured.
        arms = ab.arms_for(3)
        if not regression.cloud_allowed():
            self.assertEqual([a[0] for a in arms],
                             ["off", "stage_1", "stage_1_2"])

    def test_deltas_line_up_with_the_arms(self):
        result = ab.compare(_RAILS, self.records, "test", "stage_1_only",
                            max_stage=2)
        deltas = ab._deltas(result.arms)
        self.assertEqual(len(deltas), len(result.arms) - 1)
        for delta, (previous, arm) in zip(deltas,
                                          zip(result.arms, result.arms[1:])):
            with self.subTest(delta=delta["to"]):
                self.assertEqual(delta["extra_stopped"],
                                 arm.stopped - previous.stopped)

    def test_the_headline_arithmetic_matches_the_arms(self):
        result = ab.compare(_RAILS, self.records, "test", "stage_1_only",
                            max_stage=2)
        head = ab.headline(result.arms)
        self.assertEqual(head["prevented"],
                         result.arms[0].delivered - result.arms[-1].delivered)
        self.assertEqual(head["sample"], len(self.records))

    def test_an_error_counts_as_stopped_not_delivered(self):
        # An engine that threw forwarded nothing. Counting it as delivered would
        # flatter the off arm; counting it as neither breaks the arithmetic.
        arm = ab.Arm(name="stage_1", ceiling=1, label="x")
        arm.sample, arm.stopped, arm.delivered, arm.errors = 1, 1, 0, 1
        self.assertEqual(arm.stopped + arm.delivered, arm.sample)


class MissingRailsAreMarked(unittest.TestCase):

    def test_cannot_judge_names_rails_rather_than_summarising_a_tier(self):
        stage_2 = [r for r in _RAILS if r.stage is Stage.STAGE_2]
        absent = ab.cannot_judge(stage_2)
        self.assertIsInstance(absent, list)
        self.assertEqual(absent, sorted(absent))
        for name in absent:
            self.assertIn(name, {r.name for r in stage_2})

    def test_an_arm_with_a_missing_rail_is_not_measured(self):
        _sel, records = _sample(20)
        result = ab.compare(_RAILS, records, "test", "stage_1_and_2",
                            max_stage=2)
        for arm in result.arms:
            with self.subTest(arm=arm.name):
                self.assertEqual(arm.to_dict()["measured"],
                                 not arm.rails_unavailable)

    def test_a_note_names_the_missing_rails(self):
        _sel, records = _sample(20)
        result = ab.compare(_RAILS, records, "test", "stage_1_and_2",
                            max_stage=2)
        for arm in result.arms:
            if not arm.rails_unavailable:
                continue
            joined = " ".join(result.notes)
            for name in arm.rails_unavailable:
                with self.subTest(rail=name):
                    self.assertIn(name, joined)
            self.assertIn("FLOOR", joined)


class Latency(unittest.TestCase):

    def test_the_median_and_p95_are_reported_alongside_the_mean(self):
        _sel, records = _sample(30)
        result = ab.compare(_RAILS, records, "test", "stage_1_only",
                            max_stage=2)
        for arm in result.arms[1:]:
            row = arm.to_dict()
            with self.subTest(arm=arm.name):
                self.assertIsNotNone(row["median_ms_per_record"])
                self.assertIsNotNone(row["p95_ms_per_record"])
                self.assertLessEqual(row["median_ms_per_record"],
                                     row["p95_ms_per_record"])

    def test_the_off_arm_has_no_latency_to_report(self):
        _sel, records = _sample(10)
        row = ab._off_arm(records).to_dict()
        self.assertIsNone(row["median_ms_per_record"])

    def test_median_of_an_even_sample_averages_the_middle_pair(self):
        self.assertEqual(ab._median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_median_of_nothing_is_none(self):
        self.assertIsNone(ab._median([]))

    def test_the_percentile_does_not_interpolate(self):
        # Nearest-rank on purpose: an interpolated p95 of a 30-record sample
        # implies a precision the sample does not have.
        values = [float(i) for i in range(1, 21)]
        self.assertIn(ab._percentile(values, 0.95), (19.0, 20.0))


class Pipeline(unittest.TestCase):

    def test_the_estimate_is_the_product_of_the_two_halves(self):
        left = ab.Arm(name="a", ceiling=1, label="", sample=10, delivered=8,
                      stopped=2)
        right = ab.Arm(name="b", ceiling=1, label="", sample=10, delivered=5,
                       stopped=5)
        out = ab.pipeline_estimate([], left, right)
        self.assertTrue(out["available"])
        self.assertAlmostEqual(out["end_to_end_success_rate"], 0.4)
        self.assertAlmostEqual(out["reduction"], 0.6)

    def test_it_states_its_assumptions_rather_than_hiding_them(self):
        left = ab.Arm(name="a", ceiling=1, label="", sample=4, delivered=4)
        out = ab.pipeline_estimate([], left, left)
        self.assertEqual(len(out["assumes"]), 2)
        joined = " ".join(out["assumes"]).lower()
        self.assertIn("worst case", joined)
        self.assertIn("independent", joined)

    def test_an_empty_half_is_unavailable_with_a_reason(self):
        empty = ab.Arm(name="a", ceiling=1, label="", sample=0)
        full = ab.Arm(name="b", ceiling=1, label="", sample=4, delivered=4)
        out = ab.pipeline_estimate([], empty, full)
        self.assertFalse(out["available"])
        self.assertIn("direction", out["why"])

    def test_split_by_direction_treats_a_missing_direction_as_input(self):
        ins, outs = ab.split_by_direction([
            {"id": "a"}, {"id": "b", "direction": "input"},
            {"id": "c", "direction": "output"}])
        self.assertEqual([r["id"] for r in ins], ["a", "b"])
        self.assertEqual([r["id"] for r in outs], ["c"])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi is not installed")
class Endpoint(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(create_app())

    def test_it_returns_a_ladder_with_the_caveat_attached(self):
        body = self.client.post("/v1/corpus/compare",
                                json={"limit": 20, "seed": 0,
                                      "max_stage": 1}).json()
        self.assertEqual([a["arm"] for a in body["arms"]], ["off", "stage_1"])
        self.assertIn("DELIVERY, not compliance", body["measures"])
        self.assertIn("sentence", body["headline"])

    def test_the_off_arm_is_always_a_full_delivery_rate(self):
        body = self.client.post("/v1/corpus/compare",
                                json={"limit": 20, "max_stage": 1}).json()
        self.assertEqual(body["arms"][0]["delivery_rate"], 1.0)

    def test_a_sample_over_the_cap_is_a_422_naming_the_cap(self):
        body = self.client.post("/v1/corpus/compare",
                                json={"limit": 99_999}).json()
        self.assertEqual(body["code"], "sample_too_large")
        self.assertIn("cap", body["details"])

    def test_a_filter_that_matches_nothing_is_a_422(self):
        body = self.client.post("/v1/corpus/compare",
                                json={"limit": 10,
                                      "tenet": "Not A Tenet"}).json()
        self.assertEqual(body["code"], "empty_selection")

    def test_a_misspelled_field_is_a_422(self):
        response = self.client.post("/v1/corpus/compare",
                                    json={"limitt": 10})
        self.assertEqual(response.status_code, 422)

    def test_pipeline_mode_draws_both_direction_pools(self):
        body = self.client.post("/v1/corpus/compare",
                                json={"limit": 20, "max_stage": 1,
                                      "pipeline": True}).json()
        pipe = body["pipeline"]
        self.assertTrue(pipe["available"])
        # Both halves are drawn direction-filtered, so both should be the full
        # requested size rather than whatever an unfiltered draw happened to
        # contain - only 519 of 11,369 records are output-direction.
        self.assertEqual(pipe["input_sample"], 20)
        self.assertEqual(pipe["output_sample"], 20)

    def test_the_route_is_in_the_openapi_document(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/v1/corpus/compare", paths)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
