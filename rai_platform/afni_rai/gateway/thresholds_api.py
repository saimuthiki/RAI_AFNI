# -*- coding: utf-8 -*-
"""
`/v1/thresholds` - the sensitivity knobs, read and written.

    GET  /v1/thresholds   every tunable threshold, its shipped default, and the
                          value a rail would actually get right now
    PUT  /v1/thresholds   set overrides, or apply a preset

The SECOND write endpoint in this platform, and it deserves the same warning as
the first: this changes what gets blocked, and the console has no
authentication because it is a localhost operator tool.

What bounds it:

  * The key set is CLOSED - `sensitivity.KNOWN`, built from the two default maps
    in `thresholds.py`. An override for a key no rail resolves is write-only
    config, so an unknown key is a 422 naming it rather than a stored value
    nobody will ever read.
  * Every value must be a score in [0, 1]. A detector score is compared against
    this number; 42.0 is not a threshold, it is a way to turn a check off while
    the UI still shows it as configured.
  * Raising a threshold is ALLOWED and that is deliberate. This endpoint is not
    a safety boundary - the code's defaults are, and a request cannot change
    them. What an operator can do here, a code reviewer has already agreed they
    should be able to do.

UNLIKE THE TOPIC POLICY, THIS TAKES EFFECT IMMEDIATELY. `ThresholdStore` does
not cache, on purpose: "a threshold change must take effect on the next
request". So there is no restart note here, and the response says so - giving
one hedged "restart to apply" answer for both endpoints would have an operator
restarting a gateway for no reason, or worse, not trusting the one that does
need it.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import sensitivity


class ThresholdRequest(BaseModel):
    """Either a preset, or an explicit override map. Not both.

    `extra="forbid"`: a misspelled field in a body that changes what gets
    blocked must be a 422, not a silently ignored setting.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"preset": "balanced"},
        {"preset": "strict"},
        {"thresholds": {"safety.toxicity": 0.45,
                        "privacy.pii.ner_score": 0.35}},
        {"thresholds": {}},
    ]})

    preset: str | None = Field(default=None, description=(
        "One of the names from `GET /v1/thresholds` → `presets`. A preset is a "
        "bulk write of the same override map you could type by hand - there is "
        "nothing it can set that you cannot then un-set one row at a time. "
        "`balanced` clears every override and returns to the shipped defaults."))
    thresholds: dict[str, float] | None = Field(default=None, description=(
        "Explicit overrides, keyed by the `key` field from "
        "`GET /v1/thresholds`. REPLACES the whole saved map rather than merging "
        "into it, so what you send is what is in force - a merge would make "
        "'remove this override' impossible to express."))

    @model_validator(mode="after")
    def _one_of(self) -> "ThresholdRequest":
        if self.preset is not None and self.thresholds is not None:
            raise ValueError(
                "send `preset` or `thresholds`, not both - a preset writes the "
                "whole map, so combining them would leave it ambiguous which "
                "one won")
        if self.preset is None and self.thresholds is None:
            raise ValueError(
                "send either `preset` or `thresholds`. An empty body would be "
                "indistinguishable from `{\"thresholds\": {}}`, which CLEARS "
                "every override - too destructive to be the default reading of "
                "a malformed request.")
        return self


def thresholds_router(gateway: Any) -> APIRouter:
    router = APIRouter()

    def _store():
        return getattr(gateway, "thresholds", None)

    @router.get("/v1/thresholds", tags=["introspection"],
                summary="Every tunable threshold and the value in force")
    def get_thresholds() -> JSONResponse:
        """The sensitivity catalogue.

        `shipped` is what the code ports, cited in `thresholds.py` to the
        repository it came from. `effective` is what a rail would get on the
        next request, and it comes from the live store rather than from
        arithmetic here - recomputing resolution in a second place is how the
        two drift.

        `direction` matters when reading this. Most keys are
        `lower-is-stricter`. Three are not: the refusal detector measures the
        MODEL's behaviour rather than a user's, and the two confidence-envelope
        bounds are a matched pair. Presets deliberately skip all three, and
        `preset_excludes` names them.

        `problems` lists values in the saved file that were REJECTED - an
        unknown key, a non-number, a value outside [0, 1]. They are reported
        rather than dropped silently, because an operator who typed 1.7 needs to
        know it is not in force.
        """
        body = sensitivity.summary(_store())
        body["note"] = (
            "A saved threshold applies on the NEXT REQUEST - no restart. The "
            "store does not cache, on purpose. (The topic policy does need a "
            "restart, because that rail compiles its pattern sets once at "
            "construction. Two mechanisms, two answers.)")
        body["honesty"] = (
            "Lowering a threshold does not find more harm. It lowers the bar "
            "for calling something harm - the detector's ranking is unchanged. "
            "What changes is that more legitimate work gets refused, and a "
            "guardrail that refuses legitimate work gets switched off by the "
            "business. `maximum` is a red-team and demonstration setting.")
        return JSONResponse(body)

    @router.put("/v1/thresholds", tags=["introspection"],
                summary="Set threshold overrides, or apply a preset")
    def put_thresholds(body: ThresholdRequest) -> JSONResponse:
        """Save overrides and push them into the live store.

        THIS CHANGES WHAT GETS BLOCKED, IMMEDIATELY. The console has no
        authentication and is meant for localhost.

        `thresholds` REPLACES the saved map. That is not a merge, and it is the
        only way "remove this override" can be expressed at all.
        """
        if body.preset is not None:
            if body.preset not in sensitivity.PRESETS:
                return JSONResponse(status_code=422, content={
                    "code": "unknown_preset",
                    "message": (f"unknown preset {body.preset!r} - the names "
                                f"are {sorted(sensitivity.PRESETS)}."),
                    "details": {"known": sorted(sensitivity.PRESETS)}})
            overrides = sensitivity.preset_overrides(body.preset)
            applied = body.preset
        else:
            overrides = dict(body.thresholds or {})
            applied = None

            unknown = sorted(k for k in overrides if k not in sensitivity.BY_KEY)
            if unknown:
                return JSONResponse(status_code=422, content={
                    "code": "unknown_threshold",
                    "message": (
                        f"no rail resolves {unknown} - an override for a key "
                        f"nothing reads is write-only configuration, which is "
                        f"exactly the bug this subsystem exists to prevent. See "
                        f"GET /v1/thresholds for the keys that exist."),
                    "details": {"unknown": unknown}})

            bad = sorted(
                k for k, v in overrides.items()
                if isinstance(v, bool) or not 0.0 <= float(v) <= 1.0)
            if bad:
                return JSONResponse(status_code=422, content={
                    "code": "threshold_out_of_range",
                    "message": (
                        f"{bad} must be a score in [0, 1] - this number is "
                        f"compared against a detector score, so a value "
                        f"outside that range turns the check off while the UI "
                        f"still shows it as configured."),
                    "details": {"keys": bad}})

        before, _problems = sensitivity.load()
        sensitivity.save(overrides, preset=applied)

        # Push into the LIVE store, not just the file. Saving without this would
        # leave the endpoint changing a file that the running process never
        # reads until it restarts - which is the write-only-config bug wearing a
        # different hat.
        store = _store()
        if store is not None:
            store.put_overrides(sensitivity.as_overrides(
                overrides, label=str(sensitivity.policy_path())))

        changed = overrides != before
        return JSONResponse({
            "saved": {"thresholds": {k: overrides[k] for k in sorted(overrides)},
                      "preset_applied": applied},
            "policy_path": str(sensitivity.policy_path()),
            "overridden": len(overrides),
            "changed": changed,
            "live": store is not None,
            "note": ("In force on the next request - no restart."
                     if store is not None else
                     "Saved to disk. No live store was reachable, so it applies "
                     "when the gateway next reads the file."),
        })

    return router
