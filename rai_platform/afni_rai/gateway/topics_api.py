# -*- coding: utf-8 -*-
"""
`GET /v1/topics` and `PUT /v1/topics` - the topic policy, read and written.

THE ONLY WRITE ENDPOINT IN THIS PLATFORM, and that deserves saying out loud.

Everything else here either reads state or judges text. This one CHANGES WHAT
GETS BLOCKED, which makes it the one endpoint where an unauthenticated caller
could weaken the guardrail. Three things bound that:

  * The six ALWAYS topics are compiled into `topics.py` and are not represented
    in the policy file at all. There is no request, and no file edit, that turns
    them off - only a code change and a code review.
  * A PUT can only enable or disable topics FROM THE SHIPPED CATALOGUE. It cannot
    invent a pattern, so it cannot be used to make the gateway match something
    arbitrary, and it cannot be used to smuggle a regex.
  * `blocking` is intersected with `enabled` server-side, so "promote a topic I
    have not enabled" is not a reachable state.

What is NOT bound: the console has no authentication, because it is an operator
tool intended for localhost. Exposing this gateway on a network without putting
auth in front of it would mean anyone who can reach it can widen or narrow the
optional topic list. That is a deployment decision and it is stated in the
endpoint description rather than left for somebody to discover.

Rebuilding the rail after a write is deliberately a RESTART, not a hot swap - see
`_reload_note`.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import topics


class TopicPolicyRequest(BaseModel):
    """Which optional topics this deployment refuses to discuss.

    `extra="forbid"` for the same reason the corpus request forbids extras: a
    misspelled field in a body that changes what gets blocked must be a 422, not
    a silently ignored setting.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [
            {"enabled": ["politics", "religion", "legal_advice"], "blocking": []},
            {"enabled": ["credentials_request", "other_customers"],
             "blocking": ["credentials_request"]},
            {"enabled": [], "blocking": []},
        ]})

    enabled: list[str] = Field(default_factory=list, description=(
        "Topic ids from the OPTIONAL catalogue returned by `GET /v1/topics`. An "
        "unknown id is a 422 naming it - silently dropping it would leave an "
        "operator believing a topic was covered. The six `always` topics are not "
        "accepted here: they are compiled in and cannot be switched off."))
    blocking: list[str] = Field(default_factory=list, description=(
        "Subset of `enabled` to promote from FLAG to BLOCK. Default behaviour is "
        "to flag and escalate, because a keyword hit is evidence rather than a "
        "verdict; promote only a topic whose phrases cannot plausibly appear in "
        "legitimate work. An id here that is not in `enabled` is a 422."))


def _reload_note(changed: bool) -> str:
    """Why a write does not take effect immediately.

    The rail's pattern sets are compiled once at construction - split into words
    and phrases, sorted longest-first - precisely so the request path does no
    work. Rebuilding it under a live request would mean either a lock on the hot
    path or a torn read of a half-swapped lexicon.

    Neither is worth it for a control an operator changes a handful of times, so
    the honest answer is to say the policy is saved and the restart is what arms
    it. A UI that implied otherwise would have somebody testing a topic that was
    not yet live and concluding the feature was broken.
    """
    if not changed:
        return "No change - the saved policy already matched this request."
    return ("Policy saved. It arms on the next gateway restart: the rail compiles "
            "its word and phrase sets once at construction so the request path "
            "does no work, and swapping them under live traffic would need a lock "
            "on the hot path. Restart the gateway to apply.")


def topics_router(gateway: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/topics", tags=["introspection"],
                summary="The topic catalogue and this deployment's policy")
    def get_topics() -> JSONResponse:
        """Every topic this platform knows about, and which are in force here.

        `always` is the six compiled-in topics. They BLOCK, they are on with no
        configuration, and they cannot be switched off from here - a fresh
        install with no policy file still refuses them.

        `optional` is the catalogue an operator picks from, each with `enabled`
        and `blocking` for this deployment. Ships with none selected, because
        "off-topic" differs per application: a benefits helpdesk must discuss
        medical leave and a billing bot must not.

        `mounted` says whether the rail is actually in the running cascade. It
        should always be true, since the always-topics guarantee a non-empty
        lexicon; false means something failed and the topic cover is absent.
        """
        body = topics.summary()
        rail = getattr(gateway, "topic_rail", None)
        body["mounted"] = rail is not None
        body["rail"] = getattr(rail, "name", None)
        # The gateway's in-memory policy vs what is on disk. They differ exactly
        # when somebody has written a policy and not restarted, which is the one
        # confusing state this endpoint can be in - so it is reported.
        live = getattr(gateway, "topic_policy", None)
        on_disk = topics.load_policy()
        body["restart_pending"] = bool(
            live is not None and live.to_dict() != on_disk.to_dict())
        return JSONResponse(body)

    @router.put("/v1/topics", tags=["introspection"],
                summary="Set which optional topics this deployment refuses")
    def put_topics(body: TopicPolicyRequest) -> JSONResponse:
        """Save the optional topic selection.

        THIS CHANGES WHAT GETS BLOCKED. The console has no authentication and is
        meant for localhost; putting this gateway on a network without auth in
        front of it means anyone who can reach it can change the optional list.
        The six `always` topics are unreachable from here either way.

        Takes effect on the next restart - see the `note` in the response.
        """
        known = {t.id for t in topics.OPTIONAL}
        always = {t.id for t in topics.ALWAYS}

        unknown = [t for t in body.enabled if t not in known]
        if unknown:
            hint = ("those are the compiled-in `always` topics, which are on "
                    "unconditionally and cannot be set here"
                    if all(t in always for t in unknown)
                    else "see `GET /v1/topics` for the ids that exist")
            return JSONResponse(status_code=422, content={
                "code": "unknown_topic",
                "message": f"unknown topic id(s): {unknown} - {hint}.",
                "details": {"unknown": unknown}})

        orphan = [t for t in body.blocking if t not in set(body.enabled)]
        if orphan:
            return JSONResponse(status_code=422, content={
                "code": "blocking_not_enabled",
                "message": (f"cannot promote {orphan} to blocking without also "
                            f"enabling them - a topic that is not enabled is not "
                            f"matched at all, so 'blocking but not enabled' is "
                            f"not a state that means anything."),
                "details": {"orphan": orphan}})

        before = topics.load_policy()
        policy = topics.Policy(enabled=frozenset(body.enabled),
                               blocking=frozenset(body.blocking))
        topics.save_policy(policy)

        flagging, blocking = topics.patterns_for(policy)
        return JSONResponse({
            "saved": policy.to_dict(),
            "policy_path": str(topics.policy_path()),
            "patterns": {"flagging": len(flagging), "blocking": len(blocking)},
            "note": _reload_note(policy.to_dict() != before.to_dict()),
        })

    return router
