# -*- coding: utf-8 -*-
"""
Image and video moderation - the one media capability that is genuinely local.

WHY THIS EXISTS, AND WHAT WAS REJECTED

AFNI asked for media moderation, ported from the Infosys Responsible AI Toolkit
in `references/`, with an honest answer if it could not be done. Infosys ships
two media detectors and they are not equally portable:

  * `responsible-ai-safety/responsible-ai-toxicity/src/profanity/util/NudeNet/NudeNet.py`
    wraps the `nudenet` pip package's `NudeDetector`, gets 18 labelled bounding
    boxes back, and Gaussian-blurs the explicit ones. **Ported.** The package
    ships its own weights - `nudenet/320n.onnx`, 12 MB, INSIDE the wheel - so
    `pip install nudenet` is the whole model download. Nothing is fetched at
    runtime, which is why this works in an air-gapped deployment.

  * `.../nsfw_model/nsfw_detector/videonsfw.py` loads `../models/nsfw.299x299.h5`,
    a Keras InceptionV3 five-class classifier, through TensorFlow and
    tensorflow_hub. **Not ported.** The `.h5` is not in the toolkit repository -
    it is a separate several-hundred-MB download - and it drags in TensorFlow,
    which is a ~600 MB dependency for one check that NudeNet already covers with
    a 12 MB ONNX file. If AFNI later wants the five-way
    `drawings/hentai/neutral/porn/sexy` breakdown rather than body-part boxes,
    that is the file to revisit; the interface here would not change.

WHAT IS HONESTLY UNVERIFIED

The pipeline is verified end to end in this environment: the ONNX graph loads in
0.11 s, an inference costs ~87 ms on CPU, the 18-class head produces graded
per-anchor scores, and a benign image correctly yields no detections. What is
**not** verified here is detection *accuracy*, because doing so needs test
imagery and there is deliberately none in this repository and none may be
fetched. Treat the accuracy claims as NudeNet's, not as AFNI's measurements,
until AFNI runs its own labelled set. `docs/setup.md` says how.

THE GENDER LABELS ARE DELIBERATELY DISCARDED

The model emits `FACE_FEMALE` and `FACE_MALE`, and the exposed-breast classes are
also gender-split. This module collapses every face class to one `face` finding
and never propagates the gender guess. A binary gender inference from a
photograph is precisely the fairness harm this platform is built to catch, and
re-emitting it in a finding would put it into the audit record and the compliance
report. The detection is used, the demographic guess is dropped on the floor.

REDACTION IS REPORTED, NOT SPANNED

`contract.Span` is `(path, start, end, replacement)` - character offsets in a
string. An image region is a rectangle and does not fit, so this module reports
`regions` alongside the verdict instead of pretending. That is a real gap in the
protocol binding rather than something to paper over: an application that wants
the blurred image asks for it, and gets bytes back.

FAIL CLOSED APPLIES HERE TOO

If `nudenet` is not installed the module does not crash on import and does not
return "clean". It returns `unjudged`, which the platform turns into a block, for
the same reason every other Stage-2 rail does: "could not look" is not "found
nothing".

Cascade placement: **Stage 2.** Local model, ~87 ms per image on CPU, no network.
Video is **Offline** - see `moderate_video`.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any

from .contract.models import Action, Finding, Severity

#: The pip package that carries both the code and the weights.
PACKAGE = "nudenet"
#: The ONNX file inside that wheel. Named so an operator can confirm what ran.
MODEL_FILE = "320n.onnx"
DETECTOR_NAME = "nudenet-320n"

#: Explicit exposure. These block.
EXPLICIT: frozenset[str] = frozenset({
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED",
})

#: Covered-but-suggestive. These flag. Infosys's image path treats several of
#: these as blur-worthy at score > 0.5; that is too strict for a general
#: guardrail - a person in a swimsuit is not a policy violation everywhere - so
#: they are reported as evidence and the deployment decides.
SUGGESTIVE: frozenset[str] = frozenset({
    "FEMALE_GENITALIA_COVERED",
    "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
    "ANUS_COVERED",
    "MALE_BREAST_EXPOSED",
})

#: Faces. Reported as biometric PII, gender label discarded (see module docstring).
FACES: frozenset[str] = frozenset({"FACE_FEMALE", "FACE_MALE"})

#: Everything else the model emits - bellies, feet, armpits, covered or exposed.
#: Not reported at all. A visible ankle is not a finding, and filling the audit
#: record with them would bury the ones that matter.
IGNORED: frozenset[str] = frozenset({
    "FEET_EXPOSED", "FEET_COVERED", "BELLY_EXPOSED", "BELLY_COVERED",
    "ARMPITS_EXPOSED", "ARMPITS_COVERED",
})

ALL_LABELS: frozenset[str] = EXPLICIT | SUGGESTIVE | FACES | IGNORED

#: Threshold keys, resolved through `ThresholdStore` like every other rail's, so
#: an operator tunes media sensitivity in the same place as text sensitivity.
THRESHOLD_EXPLICIT = "safety.sexual.image_explicit"
THRESHOLD_SUGGESTIVE = "safety.sexual.image_suggestive"
THRESHOLD_FACE = "privacy.pii.face"

#: Ported from Infosys's own numbers: `NudeNet.py` uses score > 0.5 on the image
#: path. The suggestive band sits higher because it only flags, and a noisy flag
#: an operator learns to ignore is worse than no flag.
DEFAULT_EXPLICIT = 0.50
DEFAULT_SUGGESTIVE = 0.60
DEFAULT_FACE = 0.50

#: How many video frames to actually score. See `moderate_video`.
DEFAULT_FRAME_STRIDE = 15
DEFAULT_MAX_FRAMES = 120

#: Guard against a decompression bomb before handing bytes to OpenCV.
MAX_IMAGE_BYTES = 16 * 1024 * 1024
ENV_MAX_BYTES = "AFNI_MEDIA_MAX_BYTES"


class MediaUnavailable(RuntimeError):
    """`nudenet` is not installed, so nothing can be judged.

    Raised rather than returned so a caller cannot mistake it for a clean
    result. `moderate_image` catches it and produces `unjudged`.
    """


@dataclass(frozen=True)
class Region:
    """One rectangle the detector fired on, in ORIGINAL image pixels.

    `label` is the reported band (`explicit` / `suggestive` / `face`), never the
    raw model class for the face bands - see the module docstring on gender.
    """

    label: str
    band: str
    score: float
    x: int
    y: int
    width: int
    height: int
    frame: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {"label": self.label, "band": self.band, "score": round(self.score, 4),
               "x": self.x, "y": self.y, "width": self.width, "height": self.height}
        if self.frame is not None:
            out["frame"] = self.frame
        return out


@dataclass
class MediaResult:
    """What a media check produced, before the engine consolidates it.

    Deliberately not a `Verdict`: the engine owns the decision, and a rail that
    decided for itself would be the second place in the codebase that knows what
    fail-closed means.
    """

    findings: list[Finding] = field(default_factory=list)
    regions: list[Region] = field(default_factory=list)
    unjudged: list[str] = field(default_factory=list)
    detector: str | None = None
    latency_ms: int | None = None
    #: Frames actually scored, for video. None for a single image.
    frames_scored: int | None = None
    frames_total: int | None = None

    @property
    def blocked(self) -> bool:
        """True when a finding asked to block, or nothing could be judged."""
        return bool(self.unjudged) or any(
            f.action is Action.BLOCK for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "findings": [f.to_dict() for f in self.findings],
            "regions": [r.to_dict() for r in self.regions],
        }
        if self.unjudged:
            out["unjudged"] = list(self.unjudged)
        for key in ("detector", "latency_ms", "frames_scored", "frames_total"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


# --------------------------------------------------------------------------- #
# Loading the detector                                                        #
#                                                                             #
# Module-level cache, built on first use rather than at import. Importing this  #
# module must stay free: `load_tenets()` imports it to report availability, and #
# a 12 MB ONNX session on every CLI invocation that never touches an image     #
# would be pure waste.                                                        #
# --------------------------------------------------------------------------- #
_DETECTOR: Any = None
_LOAD_ERROR: str | None = None


def available() -> bool:
    """Whether media moderation can run at all, without loading the model."""
    try:
        import importlib.util
        return importlib.util.find_spec(PACKAGE) is not None
    except (ImportError, ValueError):
        return False


def model_path() -> str | None:
    """Absolute path of the ONNX file that will be used, for the status report.

    Reported so an operator can see *which* weights answered, which is the
    question "is the model installed?" actually means.
    """
    if not available():
        return None
    try:
        import nudenet
    except ImportError:
        return None
    candidate = os.path.join(os.path.dirname(nudenet.__file__), MODEL_FILE)
    return candidate if os.path.exists(candidate) else None


def detector() -> Any:
    """The cached `NudeDetector`. Raises `MediaUnavailable` if it cannot load."""
    global _DETECTOR, _LOAD_ERROR
    if _DETECTOR is not None:
        return _DETECTOR
    if _LOAD_ERROR is not None:
        raise MediaUnavailable(_LOAD_ERROR)
    try:
        from nudenet import NudeDetector
    except ImportError as exc:
        _LOAD_ERROR = (f"{PACKAGE} is not installed ({exc}). "
                       f"`pip install {PACKAGE}` - the 12 MB {MODEL_FILE} ships "
                       "inside the wheel, nothing is downloaded at runtime.")
        raise MediaUnavailable(_LOAD_ERROR) from exc
    try:
        _DETECTOR = NudeDetector()
    except Exception as exc:  # noqa: BLE001 - onnxruntime raises its own types
        # Broad, and justified: onnxruntime's failure modes are provider-specific
        # (`Fail`, `InvalidProtobuf`, a bare RuntimeError) and every one of them
        # means the same thing here - no detector, so unjudged, so blocked. This
        # is the one place a broad except is safe, because it does not swallow
        # the outcome: it converts it into a loud one.
        _LOAD_ERROR = f"{PACKAGE} failed to load its model: {exc}"
        raise MediaUnavailable(_LOAD_ERROR) from exc
    return _DETECTOR


def reset_detector() -> None:
    """Drop the cached detector and any load error. For tests."""
    global _DETECTOR, _LOAD_ERROR
    _DETECTOR = None
    _LOAD_ERROR = None


def status() -> dict[str, Any]:
    """What `GET /v1/media` reports. Never loads the model."""
    return {
        "available": available(),
        "package": PACKAGE,
        "model_file": MODEL_FILE,
        "model_path": model_path(),
        "detector": DETECTOR_NAME,
        "stage": "Stage 2 (local model, no network)",
        "labels": {
            "explicit_block": sorted(EXPLICIT),
            "suggestive_flag": sorted(SUGGESTIVE),
            "face_flag": ["face"],
            "ignored": sorted(IGNORED),
        },
        "thresholds": {
            THRESHOLD_EXPLICIT: DEFAULT_EXPLICIT,
            THRESHOLD_SUGGESTIVE: DEFAULT_SUGGESTIVE,
            THRESHOLD_FACE: DEFAULT_FACE,
        },
        "video": {
            "stage": "Offline",
            "frame_stride": DEFAULT_FRAME_STRIDE,
            "max_frames": DEFAULT_MAX_FRAMES,
        },
        "install_hint": f"pip install {PACKAGE}",
    }


# --------------------------------------------------------------------------- #
# Scoring                                                                     #
# --------------------------------------------------------------------------- #
def _max_bytes() -> int:
    raw = os.environ.get(ENV_MAX_BYTES, "").strip()
    try:
        return max(1, int(raw)) if raw else MAX_IMAGE_BYTES
    except ValueError:
        return MAX_IMAGE_BYTES


def _thresholds(resolve: Any = None) -> dict[str, float]:
    """Resolve the three thresholds, falling back to the ported defaults.

    Same contract as `CheckContext.resolve`: a callable that returns a float or
    None. None means "no usable configuration", and the ported default stands -
    the reasoning is in `thresholds.resolve_value`.
    """
    out = {THRESHOLD_EXPLICIT: DEFAULT_EXPLICIT,
           THRESHOLD_SUGGESTIVE: DEFAULT_SUGGESTIVE,
           THRESHOLD_FACE: DEFAULT_FACE}
    if resolve is None:
        return out
    for key in list(out):
        try:
            value = resolve(key)
        except Exception:  # noqa: BLE001 - a broken store must not block media
            value = None
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and 0.0 <= float(value) <= 1.0:
            out[key] = float(value)
    return out


def _band(label: str) -> str | None:
    if label in EXPLICIT:
        return "explicit"
    if label in SUGGESTIVE:
        return "suggestive"
    if label in FACES:
        return "face"
    return None


_BAND_SPEC = {
    # band -> (threshold key, category, severity, action, reported label)
    "explicit": (THRESHOLD_EXPLICIT, "safety.sexual", Severity.HIGH,
                 Action.BLOCK, None),
    "suggestive": (THRESHOLD_SUGGESTIVE, "safety.sexual", Severity.LOW,
                   Action.FLAG, None),
    # The reported label is hardcoded to "face": the model's gender split is
    # dropped here and nowhere else, so there is one line to audit.
    "face": (THRESHOLD_FACE, "privacy.pii", Severity.MEDIUM, Action.FLAG, "face"),
}


def _detections_to_result(detections: list[dict[str, Any]], path: str,
                          thresholds: dict[str, float],
                          frame: int | None = None) -> MediaResult:
    """Turn raw NudeNet output into findings and regions.

    One finding per BAND, not per box: three exposed regions in one photograph
    are one policy violation with three rectangles, and emitting three identical
    `safety.sexual` findings would treble the count in the compliance report
    without adding information.
    """
    result = MediaResult(detector=DETECTOR_NAME)
    best: dict[str, float] = {}
    for det in detections:
        label = str(det.get("class", ""))
        score = float(det.get("score", 0.0))
        band = _band(label)
        if band is None:
            continue  # IGNORED, or a label this version does not know
        key, _cat, _sev, _act, forced = _BAND_SPEC[band]
        if score < thresholds[key]:
            continue
        box = det.get("box") or [0, 0, 0, 0]
        x, y, w, h = (int(v) for v in box[:4])
        result.regions.append(Region(label=forced or label, band=band,
                                     score=score, x=x, y=y, width=w, height=h,
                                     frame=frame))
        if score > best.get(band, -1.0):
            best[band] = score

    for band, score in sorted(best.items()):
        _key, category, severity, action, _forced = _BAND_SPEC[band]
        result.findings.append(Finding(
            category=category, severity=severity, action=action, path=path,
            score=score, detector=DETECTOR_NAME))
    return result


def moderate_image(data: bytes, path: str = "payload.image",
                   resolve: Any = None) -> MediaResult:
    """Score one image. Never raises for a missing model - returns `unjudged`.

    `path` is what `Finding.path` and `unjudged` report, and follows the same
    convention as `GuardEvent.texts()` keys so a media finding and a text finding
    are addressed the same way.
    """
    import time
    started = time.perf_counter()
    limit = _max_bytes()
    if not data:
        return MediaResult(unjudged=[path], detector=None)
    if len(data) > limit:
        # Unjudged, not an error: an oversized upload is a thing that could not
        # be looked at, and the platform already knows what to do with that.
        return MediaResult(
            unjudged=[path], detector=None,
            latency_ms=int((time.perf_counter() - started) * 1000))
    try:
        det = detector()
    except MediaUnavailable:
        return MediaResult(
            unjudged=[path], detector=None,
            latency_ms=int((time.perf_counter() - started) * 1000))

    try:
        detections = det.detect(data)
    except Exception:  # noqa: BLE001 - a corrupt or unsupported file
        # Anything OpenCV cannot decode is unjudged, which fails closed. A
        # caller uploading a renamed .txt gets a block, not a pass.
        return MediaResult(
            unjudged=[path], detector=DETECTOR_NAME,
            latency_ms=int((time.perf_counter() - started) * 1000))

    result = _detections_to_result(list(detections or []), path,
                                   _thresholds(resolve))
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result


def blur(data: bytes, regions: list[Region], kernel: int = 75) -> bytes:
    """Return the image as PNG with every region Gaussian-blurred.

    Ported from `NudeNet.py`, including the 75x75 kernel, with one change: it
    blurs the regions it is GIVEN rather than re-running detection, so the same
    detection that produced the findings produces the redaction. Infosys detects
    twice and can in principle blur a region it did not report.
    """
    import cv2
    import numpy as np

    mat = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if mat is None:
        raise ValueError("could not decode image")
    k = kernel if kernel % 2 == 1 else kernel + 1
    height, width = mat.shape[:2]
    for region in regions:
        x0, y0 = max(0, region.x), max(0, region.y)
        x1 = min(width, region.x + region.width)
        y1 = min(height, region.y + region.height)
        if x1 <= x0 or y1 <= y0:
            continue
        roi = mat[y0:y1, x0:x1]
        mat[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (k, k), 0)
    ok, buf = cv2.imencode(".png", mat)
    if not ok:
        raise ValueError("could not re-encode image")
    return buf.tobytes()


def blur_base64(data: bytes, regions: list[Region], kernel: int = 75) -> str:
    return base64.b64encode(blur(data, regions, kernel)).decode("ascii")


def moderate_video(data: bytes, path: str = "payload.video",
                   resolve: Any = None,
                   frame_stride: int = DEFAULT_FRAME_STRIDE,
                   max_frames: int = DEFAULT_MAX_FRAMES) -> MediaResult:
    """Score sampled frames of a video. **Offline, not the request path.**

    THE COST IS THE WHOLE STORY. One frame is ~87 ms, so Infosys's approach -
    every frame of the video, `videonsfw.py` and `nudeNetVideo` both - is about
    78 seconds of CPU for a 30-second 30 fps clip. That is not a check you put
    in front of a user waiting for an answer, which is why this is classed
    Offline and why the default samples every 15th frame with a hard cap of 120.

    Sampling is a real reduction in coverage and is reported rather than hidden:
    `frames_scored` and `frames_total` come back so a reviewer can see that 120
    of 5,400 frames were looked at. A single explicit frame anywhere in the
    sample blocks the whole video - the union of what was seen, not an average,
    because averaging lets one bad frame in a long clean clip disappear.
    """
    import time
    started = time.perf_counter()
    try:
        det = detector()
    except MediaUnavailable:
        return MediaResult(unjudged=[path], detector=None)

    try:
        import cv2
        import numpy as np
    except ImportError:
        return MediaResult(unjudged=[path], detector=None)

    import tempfile
    thresholds = _thresholds(resolve)
    merged = MediaResult(detector=DETECTOR_NAME)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    try:
        tmp.write(data)
        tmp.close()
        cap = cv2.VideoCapture(tmp.name)
        if not cap.isOpened():
            return MediaResult(unjudged=[path], detector=DETECTOR_NAME)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        stride = max(1, int(frame_stride))
        scored = 0
        index = -1
        best: dict[str, float] = {}
        while scored < max(1, int(max_frames)):
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            index += 1
            if index % stride:
                continue
            ok_enc, buf = cv2.imencode(".jpg", frame)
            if not ok_enc:
                continue
            try:
                detections = det.detect(buf.tobytes())
            except Exception:  # noqa: BLE001 - one bad frame is not the video
                continue
            scored += 1
            part = _detections_to_result(list(detections or []), path,
                                         thresholds, frame=index)
            merged.regions.extend(part.regions)
            for finding in part.findings:
                band = "face" if finding.category == "privacy.pii" else (
                    "explicit" if finding.action is Action.BLOCK else "suggestive")
                if finding.score is not None and finding.score > best.get(band, -1.0):
                    best[band] = finding.score
        cap.release()
        merged.frames_scored = scored
        merged.frames_total = total or None
        if scored == 0:
            # Nothing was looked at, so nothing is known. Unjudged, not clean.
            merged.unjudged = [path]
        for band, score in sorted(best.items()):
            _key, category, severity, action, _forced = _BAND_SPEC[band]
            merged.findings.append(Finding(
                category=category, severity=severity, action=action, path=path,
                score=score, detector=DETECTOR_NAME))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    merged.latency_ms = int((time.perf_counter() - started) * 1000)
    return merged


__all__ = [
    "PACKAGE", "MODEL_FILE", "DETECTOR_NAME",
    "EXPLICIT", "SUGGESTIVE", "FACES", "IGNORED", "ALL_LABELS",
    "THRESHOLD_EXPLICIT", "THRESHOLD_SUGGESTIVE", "THRESHOLD_FACE",
    "DEFAULT_EXPLICIT", "DEFAULT_SUGGESTIVE", "DEFAULT_FACE",
    "MediaUnavailable", "Region", "MediaResult",
    "available", "model_path", "detector", "reset_detector", "status",
    "moderate_image", "moderate_video", "blur", "blur_base64",
]
