# -*- coding: utf-8 -*-
"""Image and video moderation.

AFNI asked for media moderation ported from the Infosys toolkit, with an honest
answer if it was not possible. It was possible - `nudenet` ships its own 12 MB
ONNX model inside the wheel - so these tests pin the four things that would make
the feature a liability if they broke:

  * a MISSING MODEL must produce `unjudged`, never "clean". The whole platform's
    posture rests on "could not look" never collapsing into "found nothing".
  * the model's GENDER LABELS must not reach a finding. It emits FACE_FEMALE /
    FACE_MALE and gender-split breast classes; propagating a binary gender guess
    from a photograph into an audit record is the fairness harm this platform
    exists to catch.
  * the THRESHOLDS must resolve to the ported Infosys numbers, not to the
    last-resort 0.85. Nothing prefix-matches `safety.sexual.image_explicit`, so
    omitting it from GLOBAL_DEFAULTS would silently raise the explicit threshold
    from 0.50 to 0.85 and halve the detector's sensitivity.
  * BLUR must touch only the regions it was handed, and must not write a file
    that implies redaction happened when nothing was detected.

Detection ACCURACY is deliberately not tested: it needs labelled imagery, there
is none in this repository on purpose, and none may be fetched. So the band
mapping is tested against a fake detector - which is the honest scope - and the
real model is only asserted to load and run.
"""
from __future__ import annotations

import base64
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai import media                                       # noqa: E402
from afni_rai.contract.models import Action, Severity            # noqa: E402
from afni_rai.tenets.accountability.thresholds import (          # noqa: E402
    GLOBAL_DEFAULTS, ThresholdOverrides, ThresholdStore)

try:
    import cv2
    import numpy as np
    _HAVE_CV2 = True
except Exception:                                                # noqa: BLE001
    _HAVE_CV2 = False


def _png(width: int = 320, height: int = 240, seed: int = 0) -> bytes:
    """A noisy PNG. Noise rather than flat colour so a blur is DETECTABLE - a
    uniform image blurs to itself and would make the blur test pass vacuously.
    """
    rng = np.random.default_rng(seed)
    frame = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", frame)
    assert ok
    return buf.tobytes()


def _mp4(frames: int = 40, seed: int = 0) -> bytes:
    import tempfile
    rng = np.random.default_rng(seed)
    handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    handle.close()
    writer = cv2.VideoWriter(handle.name, cv2.VideoWriter_fourcc(*"mp4v"),
                             10, (160, 120))
    for _ in range(frames):
        writer.write(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    writer.release()
    try:
        return open(handle.name, "rb").read()
    finally:
        os.unlink(handle.name)


class FakeDetector:
    """Returns whatever detections a test asks for.

    This is how the band mapping gets tested without imagery. It is not a
    substitute for measuring the model - see the module docstring.
    """

    def __init__(self, detections):
        self.detections = detections
        self.calls = 0

    def detect(self, _data):
        self.calls += 1
        return list(self.detections)


def _with_detector(case, detections):
    """Swap in a fake detector for the duration of one test."""
    fake = FakeDetector(detections)
    media._DETECTOR = fake
    media._LOAD_ERROR = None
    case.addCleanup(media.reset_detector)
    return fake


def _box(label, score, x=10, y=20, w=30, h=40):
    return {"class": label, "score": score, "box": [x, y, w, h]}


# --------------------------------------------------------------------------- #
class MissingModelFailsClosed(unittest.TestCase):
    """The single most important behaviour in this module."""

    def test_no_package_means_unjudged_not_clean(self):
        media.reset_detector()
        media._LOAD_ERROR = "pretend nudenet is absent"
        self.addCleanup(media.reset_detector)
        result = media.moderate_image(b"\x89PNG-ish")
        self.assertEqual(result.unjudged, ["payload.image"])
        self.assertEqual(result.findings, [])
        self.assertTrue(result.blocked,
                        "a missing model must block, never allow")

    def test_unjudged_is_blocked_even_with_no_findings(self):
        result = media.MediaResult(unjudged=["payload.image"])
        self.assertTrue(result.blocked)

    def test_empty_bytes_are_unjudged(self):
        self.assertEqual(media.moderate_image(b"").unjudged, ["payload.image"])

    def test_oversized_upload_is_unjudged_not_an_error(self):
        before = os.environ.get(media.ENV_MAX_BYTES)
        os.environ[media.ENV_MAX_BYTES] = "10"

        def restore():
            if before is None:
                os.environ.pop(media.ENV_MAX_BYTES, None)
            else:
                os.environ[media.ENV_MAX_BYTES] = before
        self.addCleanup(restore)
        result = media.moderate_image(b"x" * 100)
        self.assertEqual(result.unjudged, ["payload.image"])

    def test_a_broken_max_bytes_env_falls_back_rather_than_crashing(self):
        before = os.environ.get(media.ENV_MAX_BYTES)
        os.environ[media.ENV_MAX_BYTES] = "not-a-number"

        def restore():
            if before is None:
                os.environ.pop(media.ENV_MAX_BYTES, None)
            else:
                os.environ[media.ENV_MAX_BYTES] = before
        self.addCleanup(restore)
        self.assertEqual(media._max_bytes(), media.MAX_IMAGE_BYTES)


# --------------------------------------------------------------------------- #
class BandMapping(unittest.TestCase):
    """Which labels block, which flag, and which are dropped."""

    def test_explicit_blocks(self):
        _with_detector(self, [_box("FEMALE_GENITALIA_EXPOSED", 0.91)])
        result = media.moderate_image(b"bytes")
        self.assertTrue(result.blocked)
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.category, "safety.sexual")
        self.assertIs(finding.action, Action.BLOCK)
        self.assertIs(finding.severity, Severity.HIGH)
        self.assertEqual(finding.detector, media.DETECTOR_NAME)

    def test_suggestive_flags_and_does_not_block(self):
        _with_detector(self, [_box("FEMALE_BREAST_COVERED", 0.95)])
        result = media.moderate_image(b"bytes")
        self.assertFalse(result.blocked)
        self.assertIs(result.findings[0].action, Action.FLAG)

    def test_ignored_labels_produce_nothing_at_all(self):
        _with_detector(self, [_box(label, 0.99) for label in media.IGNORED])
        result = media.moderate_image(b"bytes")
        self.assertEqual(result.findings, [])
        self.assertEqual(result.regions, [])
        self.assertFalse(result.blocked)

    def test_an_unknown_future_label_is_ignored_not_crashed_on(self):
        _with_detector(self, [_box("SOME_NEW_LABEL_v4", 0.99)])
        result = media.moderate_image(b"bytes")
        self.assertEqual(result.findings, [])

    def test_a_detection_below_threshold_produces_nothing(self):
        _with_detector(self, [_box("FEMALE_GENITALIA_EXPOSED",
                                   media.DEFAULT_EXPLICIT - 0.01)])
        result = media.moderate_image(b"bytes")
        self.assertEqual(result.findings, [])
        self.assertFalse(result.blocked)

    def test_one_finding_per_band_however_many_boxes(self):
        _with_detector(self, [
            _box("FEMALE_GENITALIA_EXPOSED", 0.7, x=0),
            _box("BUTTOCKS_EXPOSED", 0.9, x=100),
            _box("ANUS_EXPOSED", 0.8, x=200),
        ])
        result = media.moderate_image(b"bytes")
        self.assertEqual(len(result.findings), 1,
                         "three boxes in one photograph are one violation")
        self.assertEqual(len(result.regions), 3, "but three rectangles")
        self.assertAlmostEqual(result.findings[0].score, 0.9,
                               msg="the finding carries the strongest box")

    def test_bands_are_reported_separately(self):
        _with_detector(self, [
            _box("FEMALE_GENITALIA_EXPOSED", 0.9),
            _box("FEMALE_BREAST_COVERED", 0.8),
            _box("FACE_MALE", 0.7),
        ])
        result = media.moderate_image(b"bytes")
        self.assertEqual({f.category for f in result.findings},
                         {"safety.sexual", "privacy.pii"})
        self.assertEqual(len(result.findings), 3)

    def test_regions_carry_original_pixel_geometry(self):
        _with_detector(self, [_box("BUTTOCKS_EXPOSED", 0.9, 11, 22, 33, 44)])
        region = media.moderate_image(b"bytes").regions[0]
        self.assertEqual((region.x, region.y, region.width, region.height),
                         (11, 22, 33, 44))
        self.assertIsNone(region.frame, "frame is for video only")

    def test_every_known_label_is_classified_exactly_once(self):
        bands = (media.EXPLICIT, media.SUGGESTIVE, media.FACES, media.IGNORED)
        for i, left in enumerate(bands):
            for right in bands[i + 1:]:
                self.assertEqual(left & right, frozenset(),
                                 "a label in two bands has undefined behaviour")
        self.assertEqual(len(media.ALL_LABELS), 18,
                         "NudeNet 3.4.2 emits 18 classes; a change here means "
                         "the package changed and the bands need re-reading")


# --------------------------------------------------------------------------- #
class GenderLabelsAreDiscarded(unittest.TestCase):
    """The model guesses gender from a face. That guess must not travel."""

    def test_face_findings_do_not_name_a_gender(self):
        for label in ("FACE_FEMALE", "FACE_MALE"):
            with self.subTest(label=label):
                _with_detector(self, [_box(label, 0.9)])
                result = media.moderate_image(b"bytes")
                self.assertEqual(result.regions[0].label, "face")
                blob = str(result.to_dict()).upper()
                self.assertNotIn("FEMALE", blob)
                self.assertNotIn("MALE", blob)
                media.reset_detector()

    def test_a_face_flags_and_never_blocks(self):
        _with_detector(self, [_box("FACE_FEMALE", 1.0)])
        result = media.moderate_image(b"bytes")
        self.assertFalse(result.blocked,
                         "a photograph of a person is not a policy violation")
        self.assertEqual(result.findings[0].category, "privacy.pii")
        self.assertIs(result.findings[0].action, Action.FLAG)


# --------------------------------------------------------------------------- #
class Thresholds(unittest.TestCase):
    """The regression that would silently halve sensitivity."""

    def test_media_keys_are_in_the_shipped_defaults(self):
        for key, expected in ((media.THRESHOLD_EXPLICIT, media.DEFAULT_EXPLICIT),
                              (media.THRESHOLD_SUGGESTIVE,
                               media.DEFAULT_SUGGESTIVE),
                              (media.THRESHOLD_FACE, media.DEFAULT_FACE)):
            with self.subTest(key=key):
                self.assertIn(key, GLOBAL_DEFAULTS)
                self.assertEqual(GLOBAL_DEFAULTS[key], expected)

    def test_the_store_resolves_them_rather_than_the_last_resort(self):
        store = ThresholdStore()
        for key in (media.THRESHOLD_EXPLICIT, media.THRESHOLD_SUGGESTIVE,
                    media.THRESHOLD_FACE):
            with self.subTest(key=key):
                read = store.resolve(key)
                self.assertNotEqual(read.value, 0.85,
                                    "0.85 is the last-resort fallback - this key "
                                    "is not reaching a real default")

    def test_an_operator_override_actually_changes_the_outcome(self):
        _with_detector(self, [_box("FEMALE_GENITALIA_EXPOSED", 0.55)])
        store = ThresholdStore()

        loose = media.moderate_image(b"bytes", resolve=store.resolve_value)
        self.assertTrue(loose.blocked, "0.55 clears the shipped 0.50")

        store.put_overrides(ThresholdOverrides(
            thresholds={media.THRESHOLD_EXPLICIT: 0.90}))
        strict = media.moderate_image(b"bytes", resolve=store.resolve_value)
        self.assertFalse(strict.blocked, "0.55 does not clear 0.90")

    def test_a_broken_resolver_falls_back_instead_of_blocking_everything(self):
        def explode(_key):
            raise RuntimeError("store is broken")
        resolved = media._thresholds(explode)
        self.assertEqual(resolved[media.THRESHOLD_EXPLICIT],
                         media.DEFAULT_EXPLICIT)

    def test_an_out_of_range_override_is_ignored(self):
        resolved = media._thresholds(lambda _k: 1.7)
        self.assertEqual(resolved[media.THRESHOLD_EXPLICIT],
                         media.DEFAULT_EXPLICIT)

    def test_a_boolean_override_is_not_treated_as_a_number(self):
        resolved = media._thresholds(lambda _k: True)
        self.assertEqual(resolved[media.THRESHOLD_EXPLICIT],
                         media.DEFAULT_EXPLICIT)


# --------------------------------------------------------------------------- #
@unittest.skipUnless(_HAVE_CV2, "opencv is not installed")
class Blur(unittest.TestCase):

    def test_only_the_named_region_changes(self):
        data = _png(seed=1)
        original = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        region = media.Region("face", "face", 0.9, 50, 50, 100, 100)
        out = cv2.imdecode(np.frombuffer(media.blur(data, [region]), np.uint8),
                           cv2.IMREAD_COLOR)
        self.assertFalse(np.array_equal(out[50:150, 50:150],
                                        original[50:150, 50:150]))
        self.assertTrue(np.array_equal(out[180:240, 200:320],
                                       original[180:240, 200:320]))

    def test_a_region_outside_the_image_is_clipped_not_fatal(self):
        data = _png()
        region = media.Region("x", "explicit", 1.0, -50, -50, 10_000, 10_000)
        self.assertGreater(len(media.blur(data, [region])), 0)

    def test_a_zero_area_region_is_skipped(self):
        data = _png()
        region = media.Region("x", "explicit", 1.0, 10, 10, 0, 0)
        self.assertGreater(len(media.blur(data, [region])), 0)

    def test_an_even_kernel_is_made_odd(self):
        # cv2.GaussianBlur rejects an even kernel. Passing one through would be
        # a crash on a valid-looking argument.
        self.assertGreater(len(media.blur(_png(), [
            media.Region("x", "face", 0.9, 10, 10, 40, 40)], kernel=74)), 0)

    def test_undecodable_bytes_raise_rather_than_return_the_input(self):
        with self.assertRaises(ValueError):
            media.blur(b"definitely not an image", [])

    def test_base64_helper_round_trips(self):
        encoded = media.blur_base64(_png(), [])
        self.assertGreater(len(base64.b64decode(encoded)), 0)


# --------------------------------------------------------------------------- #
@unittest.skipUnless(_HAVE_CV2, "opencv is not installed")
class Video(unittest.TestCase):

    def test_sampling_is_reported_not_hidden(self):
        _with_detector(self, [])
        result = media.moderate_video(_mp4(frames=40), frame_stride=10)
        self.assertEqual(result.frames_scored, 4)
        self.assertEqual(result.frames_total, 40)
        self.assertFalse(result.unjudged)

    def test_the_frame_cap_bounds_the_work(self):
        _with_detector(self, [])
        result = media.moderate_video(_mp4(frames=40), frame_stride=1,
                                      max_frames=5)
        self.assertEqual(result.frames_scored, 5)

    def test_one_explicit_frame_blocks_the_whole_video(self):
        _with_detector(self, [_box("BUTTOCKS_EXPOSED", 0.95)])
        result = media.moderate_video(_mp4(frames=20), frame_stride=10)
        self.assertTrue(result.blocked)
        self.assertTrue(all(r.frame is not None for r in result.regions),
                        "a video region must say which frame it came from")

    def test_an_undecodable_video_is_unjudged(self):
        _with_detector(self, [])
        result = media.moderate_video(b"not a video")
        self.assertEqual(result.unjudged, ["payload.video"])

    def test_a_missing_model_is_unjudged_for_video_too(self):
        media.reset_detector()
        media._LOAD_ERROR = "pretend absent"
        self.addCleanup(media.reset_detector)
        self.assertEqual(media.moderate_video(_mp4(frames=5)).unjudged,
                         ["payload.video"])


# --------------------------------------------------------------------------- #
class RealModel(unittest.TestCase):
    """The model itself loads and runs. Not its accuracy - see the docstring."""

    @unittest.skipUnless(media.available(), "nudenet is not installed")
    def test_status_names_the_weights_that_will_answer(self):
        status = media.status()
        self.assertTrue(status["available"])
        self.assertTrue(str(status["model_path"]).endswith(media.MODEL_FILE))
        self.assertTrue(os.path.exists(status["model_path"]))

    @unittest.skipUnless(media.available() and _HAVE_CV2, "needs nudenet + cv2")
    def test_a_benign_image_is_allowed_by_the_real_detector(self):
        media.reset_detector()
        self.addCleanup(media.reset_detector)
        result = media.moderate_image(_png(seed=7))
        self.assertFalse(result.blocked)
        self.assertEqual(result.unjudged, [])
        self.assertEqual(result.detector, media.DETECTOR_NAME)
        self.assertIsNotNone(result.latency_ms)

    @unittest.skipUnless(media.available() and _HAVE_CV2, "needs nudenet + cv2")
    def test_corrupt_bytes_reach_the_detector_and_come_back_unjudged(self):
        media.reset_detector()
        self.addCleanup(media.reset_detector)
        result = media.moderate_image(base64.b64decode("aGVsbG8="))
        self.assertEqual(result.unjudged, ["payload.image"])

    def test_status_never_loads_the_model(self):
        media.reset_detector()
        self.addCleanup(media.reset_detector)
        media.status()
        self.assertIsNone(media._DETECTOR,
                          "status() must stay free - it is called by /v1/media "
                          "on a gateway that may never see an image")


# --------------------------------------------------------------------------- #
try:
    from fastapi.testclient import TestClient
    from afni_rai.gateway.app import create_app
    _HAVE_FASTAPI = True
except Exception:                                                # noqa: BLE001
    _HAVE_FASTAPI = False


@unittest.skipUnless(_HAVE_FASTAPI and _HAVE_CV2, "needs fastapi + cv2")
class Endpoints(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(create_app())

    def test_get_media_says_guard_does_not_check_images(self):
        body = self.client.get("/v1/media").json()
        # The single most likely misuse of this platform is an application that
        # accepts uploads, calls /v1/guard, and believes its images were checked.
        self.assertIn("/v1/guard", body["note"])
        self.assertIn("text only", body["note"])
        self.assertIn("install_hint", body)

    def test_get_media_does_not_claim_afni_measured_the_accuracy(self):
        body = self.client.get("/v1/media").json()
        self.assertIn("has not measured", body["accuracy_note"])

    def test_a_benign_image_is_allowed_with_a_reason_sentence(self):
        body = self.client.post("/v1/media/image",
                                json={"image_base64": base64.b64encode(
                                    _png(seed=11)).decode()}).json()
        self.assertEqual(body["decision"], "allow")
        self.assertIn("reason", body)

    def test_a_data_url_prefix_is_accepted(self):
        encoded = "data:image/png;base64," + base64.b64encode(_png()).decode()
        response = self.client.post("/v1/media/image",
                                    json={"image_base64": encoded})
        self.assertEqual(response.status_code, 200)

    def test_bad_base64_is_a_422_that_names_the_field(self):
        body = self.client.post("/v1/media/image",
                                json={"image_base64": "!!!not base64!!!"}).json()
        self.assertEqual(body["code"], "bad_base64")
        self.assertIn("image_base64", body["message"])

    def test_an_empty_payload_is_a_422(self):
        body = self.client.post("/v1/media/image",
                                json={"image_base64": ""}).json()
        self.assertEqual(body["code"], "empty_payload")

    def test_a_misspelled_field_is_a_422_not_a_silent_default(self):
        response = self.client.post("/v1/media/image", json={
            "image_base64": base64.b64encode(_png()).decode(), "blurr": True})
        self.assertEqual(response.status_code, 422)

    def test_undecodable_bytes_block_and_say_it_is_a_coverage_gap(self):
        body = self.client.post("/v1/media/image", json={
            "image_base64": base64.b64encode(b"hello there").decode()}).json()
        self.assertEqual(body["decision"], "block")
        self.assertIn("coverage gap", body["reason"])
        self.assertEqual(body["unjudged"], ["payload.image"])

    def test_blur_requested_with_nothing_detected_says_so(self):
        body = self.client.post("/v1/media/image", json={
            "image_base64": base64.b64encode(_png(seed=3)).decode(),
            "blur": True}).json()
        self.assertIsNone(body["blurred_base64"])
        self.assertIn("nothing to blur", body["blur_note"])

    def test_blur_returns_a_decodable_image_when_regions_exist(self):
        _with_detector(self, [_box("FEMALE_BREAST_EXPOSED", 0.9, 10, 10, 60, 60)])
        body = self.client.post("/v1/media/image", json={
            "image_base64": base64.b64encode(_png(seed=4)).decode(),
            "blur": True}).json()
        self.assertEqual(body["decision"], "block")
        blurred = base64.b64decode(body["blurred_base64"])
        self.assertIsNotNone(
            cv2.imdecode(np.frombuffer(blurred, np.uint8), cv2.IMREAD_COLOR))

    def test_video_reports_its_coverage(self):
        _with_detector(self, [])
        body = self.client.post("/v1/media/video", json={
            "video_base64": base64.b64encode(_mp4(frames=30)).decode(),
            "frame_stride": 10}).json()
        self.assertEqual(body["frames_scored"], 3)
        self.assertEqual(body["frames_total"], 30)

    def test_a_zero_frame_stride_is_rejected_by_the_schema(self):
        response = self.client.post("/v1/media/video", json={
            "video_base64": base64.b64encode(_mp4(frames=5)).decode(),
            "frame_stride": 0})
        self.assertEqual(response.status_code, 422)

    def test_the_routes_are_in_the_openapi_document(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for route in ("/v1/media", "/v1/media/image", "/v1/media/video"):
            self.assertIn(route, paths)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
