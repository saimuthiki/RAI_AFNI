# -*- coding: utf-8 -*-
"""Threshold overrides: the catalogue, the presets, and the write endpoint.

AFNI asked whether thresholds belong in the UI or in the code and asked for a
recommendation. The answer shipped here is three layers - code ships the
defaults, the console overrides them, a request can never set one - and these
tests pin the four things that would make that answer false:

  * THE CATALOGUE MUST COVER EVERY LIVE KEY. A threshold the engine resolves but
    the console does not list is invisible while still being in force, which is
    how an operator ends up believing they tuned something they did not.
  * AN OVERRIDE MUST REACH A DECISION, not just the summary. This whole
    subsystem is a reaction to Safe Zone's admin UI, which persisted thresholds
    that the detection path never read.
  * THE PRESETS MUST SKIP THE THREE NON-DETECTION KNOBS. Dragging the refusal
    detector or either half of the confidence envelope down with everything else
    changes what they measure rather than tightening anything.
  * A REJECTED VALUE MUST BE REPORTED, not silently dropped. An operator who
    typed 1.7 needs to know it is not in force.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai import sensitivity                                  # noqa: E402
from afni_rai.tenets.accountability.thresholds import (           # noqa: E402
    GLOBAL_DEFAULTS, LAST_RESORT_THRESHOLD, RAIL_DEFAULTS, ThresholdStore)

try:
    from fastapi.testclient import TestClient
    from afni_rai.gateway.app import create_app
    _HAVE_FASTAPI = True
except Exception:                                                 # noqa: BLE001
    _HAVE_FASTAPI = False


def _policy_file(case, payload=None):
    """Point AFNI_THRESHOLD_POLICY at a throwaway file for one test."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
    if payload is not None:
        json.dump(payload, handle)
    handle.close()
    before = os.environ.get(sensitivity.ENV_POLICY_PATH)
    os.environ[sensitivity.ENV_POLICY_PATH] = handle.name

    def restore():
        if before is None:
            os.environ.pop(sensitivity.ENV_POLICY_PATH, None)
        else:
            os.environ[sensitivity.ENV_POLICY_PATH] = before
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    case.addCleanup(restore)
    return Path(handle.name)


class Catalogue(unittest.TestCase):

    def test_every_live_threshold_is_listed(self):
        live = set(GLOBAL_DEFAULTS) | set(RAIL_DEFAULTS)
        self.assertEqual(set(sensitivity.BY_KEY), live,
                         "a knob the engine resolves but the console does not "
                         "list is in force and invisible")

    def test_no_knob_is_listed_twice(self):
        keys = [k.key for k in sensitivity.KNOBS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_knob_has_a_group_and_a_sentence(self):
        for knob in sensitivity.KNOBS:
            with self.subTest(key=knob.key):
                self.assertTrue(knob.label.strip())
                self.assertTrue(knob.group.strip())
                self.assertTrue(knob.judges.strip().endswith('.'),
                                "the description is read by an operator, so it "
                                "is a sentence")

    def test_shipped_matches_what_the_store_would_resolve(self):
        store = ThresholdStore()
        for knob in sensitivity.KNOBS:
            with self.subTest(key=knob.key):
                self.assertEqual(sensitivity.shipped(knob.key),
                                 store.resolve(knob.key).value,
                                 "the UI would show a number the engine does "
                                 "not use")

    def test_shipped_falls_back_to_the_last_resort_for_an_unknown_key(self):
        self.assertEqual(sensitivity.shipped("x.afni.not.a.real.key"),
                         LAST_RESORT_THRESHOLD)

    def test_direction_is_one_of_three_values(self):
        for knob in sensitivity.KNOBS:
            with self.subTest(key=knob.key):
                self.assertIn(knob.direction,
                              ("lower-is-stricter", "envelope", "not-a-detection"))


class Presets(unittest.TestCase):

    def test_balanced_clears_everything(self):
        self.assertEqual(sensitivity.preset_overrides("balanced"), {})

    def test_strict_is_below_shipped_everywhere_it_touches(self):
        for key, value in sensitivity.preset_overrides("strict").items():
            with self.subTest(key=key):
                self.assertLess(value, sensitivity.shipped(key))

    def test_maximum_reaches_its_floor(self):
        values = set(sensitivity.preset_overrides("maximum").values())
        self.assertEqual(values, {0.10})

    def test_presets_skip_the_three_non_detection_knobs(self):
        excluded = {k.key for k in sensitivity.KNOBS
                    if k.direction != "lower-is-stricter"}
        self.assertEqual(len(excluded), 3)
        for name in ("strict", "maximum"):
            with self.subTest(preset=name):
                touched = set(sensitivity.preset_overrides(name))
                self.assertEqual(touched & excluded, set(),
                                 "a preset must not move a knob that is not "
                                 "'how strict'")

    def test_every_preset_value_is_a_usable_score(self):
        for name in sensitivity.PRESETS:
            for key, value in sensitivity.preset_overrides(name).items():
                with self.subTest(preset=name, key=key):
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)

    def test_an_unknown_preset_raises(self):
        with self.assertRaises(KeyError):
            sensitivity.preset_overrides("aggressive")


class PolicyFile(unittest.TestCase):

    def test_a_missing_file_is_empty_with_no_complaint(self):
        path = _policy_file(self)
        os.unlink(path)
        overrides, problems = sensitivity.load()
        self.assertEqual(overrides, {})
        self.assertEqual(problems, [])

    def test_corrupt_json_degrades_to_shipped_and_says_so(self):
        path = _policy_file(self)
        path.write_text("{not json", encoding="utf-8")
        overrides, problems = sensitivity.load()
        self.assertEqual(overrides, {})
        self.assertTrue(any("not valid JSON" in p for p in problems))

    def test_an_unknown_key_is_reported_not_stored(self):
        _policy_file(self, {"thresholds": {"nonsense.key": 0.5,
                                           "safety.toxicity": 0.4}})
        overrides, problems = sensitivity.load()
        self.assertEqual(overrides, {"safety.toxicity": 0.4})
        self.assertTrue(any("nonsense.key" in p for p in problems))

    def test_an_out_of_range_value_is_reported_not_stored(self):
        _policy_file(self, {"thresholds": {"safety.toxicity": 1.7}})
        overrides, problems = sensitivity.load()
        self.assertEqual(overrides, {})
        self.assertTrue(any("outside [0, 1]" in p for p in problems))

    def test_a_boolean_is_not_a_threshold(self):
        _policy_file(self, {"thresholds": {"safety.toxicity": True}})
        overrides, problems = sensitivity.load()
        self.assertEqual(overrides, {})
        self.assertTrue(any("not a number" in p for p in problems))

    def test_save_then_load_round_trips(self):
        _policy_file(self)
        sensitivity.save({"safety.toxicity": 0.33}, preset="strict")
        overrides, problems = sensitivity.load()
        self.assertEqual(overrides, {"safety.toxicity": 0.33})
        self.assertEqual(problems, [])

    def test_the_saved_preset_name_is_a_note_not_a_source_of_truth(self):
        path = _policy_file(self)
        sensitivity.save({"safety.toxicity": 0.11}, preset="maximum")
        body = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(body["preset_applied"], "maximum")
        # Editing a row by hand must not leave the file claiming a preset it no
        # longer matches, which is why nothing reads this field back.
        overrides, _ = sensitivity.load()
        self.assertEqual(overrides, {"safety.toxicity": 0.11})

    def test_apply_to_pushes_into_a_live_store(self):
        _policy_file(self, {"thresholds": {"safety.toxicity": 0.2}})
        store = ThresholdStore()
        problems = sensitivity.apply_to(store)
        self.assertEqual(problems, [])
        self.assertEqual(store.resolve("safety.toxicity").value, 0.2)
        self.assertEqual(store.resolve("safety.toxicity").scope.value, "override")


class Summary(unittest.TestCase):

    def test_effective_comes_from_the_store(self):
        _policy_file(self, {"thresholds": {"safety.toxicity": 0.15}})
        body = sensitivity.summary()
        row = next(r for r in body["thresholds"] if r["key"] == "safety.toxicity")
        self.assertEqual(row["effective"], 0.15)
        self.assertEqual(row["shipped"], GLOBAL_DEFAULTS["safety.toxicity"])
        self.assertTrue(row["overridden"])
        self.assertEqual(row["scope"], "override")

    def test_the_summary_does_not_pollute_the_audit_read_log(self):
        # Only the DETECTION path's reads are evidence of anything. A console
        # page refresh must not look like traffic.
        store = ThresholdStore()
        sensitivity.summary(store)
        self.assertEqual(store.reads, [])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi is not installed")
class Endpoint(unittest.TestCase):

    def setUp(self):
        _policy_file(self)
        self.client = TestClient(create_app())

    def test_get_lists_every_knob_and_names_the_exclusions(self):
        body = self.client.get("/v1/thresholds").json()
        self.assertEqual(len(body["thresholds"]), len(sensitivity.KNOBS))
        self.assertEqual(len(body["preset_excludes"]), 3)
        self.assertIn("no restart", body["note"])
        self.assertIn("does not find more harm", body["honesty"])

    def test_a_preset_is_saved_and_live(self):
        response = self.client.put("/v1/thresholds", json={"preset": "strict"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["live"])
        body = self.client.get("/v1/thresholds").json()
        row = next(r for r in body["thresholds"] if r["key"] == "safety.toxicity")
        self.assertLess(row["effective"], row["shipped"])

    def test_thresholds_replace_rather_than_merge(self):
        self.client.put("/v1/thresholds", json={"preset": "strict"})
        self.client.put("/v1/thresholds",
                        json={"thresholds": {"safety.toxicity": 0.4}})
        body = self.client.get("/v1/thresholds").json()
        overridden = [r["key"] for r in body["thresholds"] if r["overridden"]]
        self.assertEqual(overridden, ["safety.toxicity"],
                         "a merge would make 'remove this override' "
                         "inexpressible")

    def test_balanced_clears_and_the_effective_value_returns_to_shipped(self):
        self.client.put("/v1/thresholds", json={"preset": "maximum"})
        self.client.put("/v1/thresholds", json={"preset": "balanced"})
        body = self.client.get("/v1/thresholds").json()
        self.assertEqual(body["counts"]["overridden"], 0)
        for row in body["thresholds"]:
            with self.subTest(key=row["key"]):
                self.assertEqual(row["effective"], row["shipped"])

    def test_an_unknown_key_is_a_422_that_explains_why(self):
        body = self.client.put(
            "/v1/thresholds",
            json={"thresholds": {"safety.made_up": 0.5}}).json()
        self.assertEqual(body["code"], "unknown_threshold")
        self.assertIn("write-only", body["message"])

    def test_an_out_of_range_value_is_a_422(self):
        body = self.client.put(
            "/v1/thresholds",
            json={"thresholds": {"safety.toxicity": 2.0}}).json()
        self.assertEqual(body["code"], "threshold_out_of_range")

    def test_an_unknown_preset_is_a_422_that_lists_the_real_ones(self):
        body = self.client.put("/v1/thresholds",
                               json={"preset": "aggressive"}).json()
        self.assertEqual(body["code"], "unknown_preset")
        self.assertIn("balanced", body["message"])

    def test_both_fields_is_a_422(self):
        response = self.client.put("/v1/thresholds", json={
            "preset": "strict", "thresholds": {}})
        self.assertEqual(response.status_code, 422)

    def test_neither_field_is_a_422_rather_than_a_destructive_clear(self):
        response = self.client.put("/v1/thresholds", json={})
        self.assertEqual(response.status_code, 422)

    def test_a_misspelled_field_is_a_422(self):
        response = self.client.put("/v1/thresholds",
                                   json={"presett": "strict"})
        self.assertEqual(response.status_code, 422)

    def test_the_routes_are_in_the_openapi_document(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/v1/thresholds", paths)
        self.assertIn("get", paths["/v1/thresholds"])
        self.assertIn("put", paths["/v1/thresholds"])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi is not installed")
class ItReachesADecision(unittest.TestCase):
    """The test this whole subsystem exists for.

    Safe Zone's admin UI persisted per-pattern thresholds and its detection path
    read an environment variable instead - an operator could tune a threshold,
    watch it save, and change nothing about what got blocked. Proving the
    opposite needs a detector whose score is fixed, which is what the fake makes
    possible.
    """

    def setUp(self):
        _policy_file(self)
        from afni_rai import media
        self.addCleanup(media.reset_detector)

        class Fake:
            def detect(self, _data):
                return [{"class": "FEMALE_GENITALIA_EXPOSED", "score": 0.55,
                         "box": [1, 1, 10, 10]}]

        media._DETECTOR = Fake()
        self.client = TestClient(create_app())

    def _decide(self):
        import base64
        # A 1x1 PNG. The bytes never reach a decoder - the fake detector ignores
        # them - so the smallest valid-looking payload is enough.
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAA"
            "AAYAAjCB0C8AAAAASUVORK5CYII=")
        return self.client.post("/v1/media/image", json={
            "image_base64": base64.b64encode(png).decode()}).json()["decision"]

    def test_raising_the_threshold_flips_block_to_allow(self):
        self.client.put("/v1/thresholds", json={"preset": "balanced"})
        self.assertEqual(self._decide(), "block", "0.55 clears the shipped 0.50")

        self.client.put("/v1/thresholds", json={
            "thresholds": {"safety.sexual.image_explicit": 0.90}})
        self.assertEqual(self._decide(), "allow",
                         "the saved override never reached the detection path")

        self.client.put("/v1/thresholds", json={"preset": "maximum"})
        self.assertEqual(self._decide(), "block")

    def test_it_takes_effect_with_no_restart(self):
        # Same client, same process, same gateway instance throughout.
        self.client.put("/v1/thresholds", json={
            "thresholds": {"safety.sexual.image_explicit": 0.99}})
        self.assertEqual(self._decide(), "allow")
        self.client.put("/v1/thresholds", json={
            "thresholds": {"safety.sexual.image_explicit": 0.10}})
        self.assertEqual(self._decide(), "block")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
