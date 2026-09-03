# -*- coding: utf-8 -*-
"""
`/v1/media` - image and video moderation.

    GET  /v1/media          is it installed, what does it look for, what blocks
    POST /v1/media/image    score one image, optionally get it back blurred
    POST /v1/media/video    score sampled frames of a video (OFFLINE cost)

BASE64 IN THE BODY, NOT MULTIPART, and that is a dependency decision rather than
a style one. FastAPI's `UploadFile` needs `python-multipart`, which this gateway
does not otherwise require; the whole media feature is meant to be an optional
extra that a deployment can skip, so it must not add a hard dependency to the
gateway for people who never send an image. Base64 costs 33% on the wire and
buys a gateway that still boots with nothing installed.

WHY THIS IS NOT A RAIL

Every other check is a `Rail` over `GuardEvent.texts()` - strings keyed by
payload path. An image is not a string, and forcing one through that interface
would mean either base64 in a text field (which every text rail would then
uselessly scan) or a second meaning for `texts()`. So media gets its own route
and returns the same `Finding` shapes, which is what actually needs to be
shared: the audit record, the compliance grouping and the severity vocabulary.

The consequence is stated rather than hidden: **a `POST /v1/guard` does not check
images.** An application that accepts uploads has to call this route as well.
`GET /v1/media` says so in its description.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import media

#: A generous ceiling on the base64 STRING, checked before decoding so a huge
#: body is rejected without allocating the decoded bytes. `media._max_bytes()`
#: then bounds the decoded size, which is the number that actually matters.
MAX_B64_CHARS = 32 * 1024 * 1024


class ImageRequest(BaseModel):
    """One image, base64-encoded.

    `extra="forbid"`: a misspelled `blurr` that silently returned an unblurred
    image would have an operator believe redaction was applied.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"image_base64": "iVBORw0KGgo...", "blur": False},
        {"image_base64": "iVBORw0KGgo...", "blur": True, "path": "payload.avatar"},
    ]})

    image_base64: str = Field(description=(
        "The image bytes, base64. A `data:image/png;base64,` prefix is accepted "
        "and stripped, because that is what a browser's FileReader produces and "
        "making every caller strip it is a needless trap."))
    blur: bool = Field(default=False, description=(
        "Return the image with every detected region Gaussian-blurred, base64, "
        "in `blurred_base64`. Off by default: it costs a re-encode, and a "
        "caller that only wants the verdict should not pay for pixels."))
    path: str = Field(default="payload.image", description=(
        "What `Finding.path` and `unjudged` report. Defaults to `payload.image` "
        "so it reads the same as a text finding's path."))


class VideoRequest(BaseModel):
    """One video, base64-encoded. Read `GET /v1/media` on cost first."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"video_base64": "AAAAIGZ0eX...", "frame_stride": 15, "max_frames": 60},
    ]})

    video_base64: str = Field(description="The video bytes, base64.")
    frame_stride: int = Field(default=media.DEFAULT_FRAME_STRIDE, ge=1, le=1000,
                              description=(
        "Score every Nth frame. 1 means every frame, which for a 30-second "
        "30 fps clip is about 78 seconds of CPU - that is why the default is 15."))
    max_frames: int = Field(default=media.DEFAULT_MAX_FRAMES, ge=1, le=2000,
                            description=(
        "Hard cap on frames scored, so a long upload cannot pin a worker. The "
        "response reports `frames_scored` against `frames_total` so the "
        "coverage gap is visible."))
    path: str = Field(default="payload.video")


def _decode(raw: str, field: str) -> tuple[bytes | None, JSONResponse | None]:
    """Base64 -> bytes, or a 422 explaining which part was wrong.

    Returns a tuple rather than raising because both outcomes are ordinary here
    and a caller pasting a truncated data-URL is the common case.
    """
    if len(raw) > MAX_B64_CHARS:
        return None, JSONResponse(status_code=413, content={
            "code": "payload_too_large",
            "message": (f"{field} is {len(raw)} base64 characters, over the "
                        f"{MAX_B64_CHARS} limit."),
            "details": {"limit_base64_chars": MAX_B64_CHARS}})
    body = raw.strip()
    if body.startswith("data:"):
        # `data:image/png;base64,AAAA` - keep what follows the comma.
        _, _, body = body.partition(",")
    try:
        data = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError) as exc:
        return None, JSONResponse(status_code=422, content={
            "code": "bad_base64",
            "message": f"{field} is not valid base64: {exc}",
            "details": {"hint": "a `data:...;base64,` prefix is accepted"}})
    if not data:
        return None, JSONResponse(status_code=422, content={
            "code": "empty_payload",
            "message": f"{field} decoded to zero bytes."})
    return data, None


def _verdict(result: media.MediaResult) -> dict[str, Any]:
    """The result plus the DECISION, spelled out in a sentence.

    The sentence is not decoration. `allow` with a flagged region and `block`
    because nothing could be judged look identical if you read only the word,
    and the four-outcome confusion is the single most common misreading of this
    platform - so the reason travels with the decision here as it does on
    `/v1/guard`.
    """
    body = result.to_dict()
    blocked = result.blocked
    body["decision"] = "block" if blocked else "allow"
    if result.unjudged:
        body["reason"] = ("BLOCKED because nothing could be judged - the model "
                          "is missing, or the file could not be decoded. This is "
                          "a coverage gap, not a detection. Fail closed is "
                          "unconditional here as everywhere.")
    elif blocked:
        body["reason"] = ("BLOCKED: explicit content detected above the "
                          "configured threshold.")
    elif result.findings:
        body["reason"] = ("ALLOWED with findings - regions were flagged for "
                          "review, not refused. Read `findings`; do not treat "
                          "`allow` as 'nothing found'.")
    else:
        body["reason"] = "ALLOWED: nothing detected above the thresholds."
    return body


def media_router(gateway: Any) -> APIRouter:
    router = APIRouter()

    def _resolve():
        """The threshold resolver, so media sensitivity is tuned in the same
        place as text sensitivity rather than in a second config file."""
        store = getattr(gateway, "thresholds", None)
        return getattr(store, "resolve_value", None) if store is not None else None

    @router.get("/v1/media", tags=["introspection"],
                summary="Image and video moderation: availability and policy")
    def get_media() -> JSONResponse:
        """Whether media moderation can run, and exactly what it looks for.

        **`POST /v1/guard` does not check images.** Text and media are separate
        routes, because a `GuardEvent` payload is strings. An application that
        accepts uploads must call `POST /v1/media/image` as well.

        `available: false` means the `nudenet` package is absent. Nothing
        degrades to "clean" in that state - every image comes back `unjudged`,
        which blocks. `install_hint` is the fix; the 12 MB ONNX model ships
        inside the wheel, so there is no separate model download and no network
        call at runtime.
        """
        body = media.status()
        body["note"] = ("POST /v1/guard checks text only. Images and video go to "
                        "POST /v1/media/image and POST /v1/media/video.")
        body["accuracy_note"] = (
            "The detector is NudeNet's, and so are its accuracy claims - AFNI "
            "has not measured them against a labelled set. The pipeline is "
            "verified; the numbers are not AFNI's.")
        return JSONResponse(body)

    @router.post("/v1/media/image", tags=["guard"],
                 summary="Moderate one image")
    def post_image(body: ImageRequest) -> JSONResponse:
        """Score an image, and optionally get it back with regions blurred.

        Findings use the same categories as text: `safety.sexual` for exposure,
        `privacy.pii` for a detected face. Faces FLAG and never block - a
        photograph of a person is not a policy violation, it is something an
        operator may need to know about.

        The model's gender labels are discarded. It emits `FACE_FEMALE` /
        `FACE_MALE` and gender-split breast classes; a binary gender inference
        from a photograph is the fairness harm this platform exists to catch, so
        it is not propagated into a finding, an audit record or a report.

        `regions` are rectangles in original-image pixels. They are reported
        separately from `modifications.spans` because a span is character
        offsets in a string and an image region is not - see the module note.
        """
        data, error = _decode(body.image_base64, "image_base64")
        if error is not None:
            return error
        result = media.moderate_image(data, path=body.path,
                                      resolve=_resolve())
        out = _verdict(result)
        if body.blur and result.regions:
            try:
                out["blurred_base64"] = media.blur_base64(data, result.regions)
            except (ValueError, ImportError) as exc:
                # The verdict still stands; only the redaction failed, and
                # saying so beats returning the original as if it were blurred.
                out["blur_error"] = str(exc)
        elif body.blur:
            out["blurred_base64"] = None
            out["blur_note"] = "nothing to blur - no regions were detected."
        return JSONResponse(out)

    @router.post("/v1/media/video", tags=["guard"],
                 summary="Moderate sampled frames of a video (offline cost)")
    def post_video(body: VideoRequest) -> JSONResponse:
        """Score sampled frames. **This is an offline check, not a live one.**

        One frame costs ~87 ms on CPU, so scoring every frame of a 30-second
        30 fps clip is about 78 seconds. The default samples every 15th frame
        and caps at 120, and `frames_scored` / `frames_total` come back so the
        coverage gap is visible rather than implied.

        A single explicit frame anywhere in the sample blocks the whole video -
        the union of what was seen, not an average, because an average lets one
        bad frame in a long clean clip disappear.
        """
        data, error = _decode(body.video_base64, "video_base64")
        if error is not None:
            return error
        result = media.moderate_video(
            data, path=body.path, resolve=_resolve(),
            frame_stride=body.frame_stride, max_frames=body.max_frames)
        return JSONResponse(_verdict(result))

    return router
