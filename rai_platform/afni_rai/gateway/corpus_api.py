# -*- coding: utf-8 -*-
"""
`/v1/corpus` - browse the regression corpus and run a CONFIGURABLE SAMPLE of it.

Three routes:

    GET  /v1/corpus            what the corpus holds, and the run cap
    POST /v1/corpus/run        run a sample, return every row plus the aggregate
    POST /v1/corpus/run/stream run a sample, one SSE frame per record

The sample size is the point. The corpus is 11,369 records and a Stage-2 pass is
1-3 s each, so "run the corpus" from an HTTP request is an hour-long held-open
socket and a saturated box. `GET /v1/corpus` exists so a caller can size a run
before starting one: it reports the per-tenet and per-OWASP counts alongside
`max_sample`, so the number in the box is an informed number.

Two limits are enforced here and cannot be raised by the request - see
`afni_rai/regression.py` for why: `max_sample` (server-side capacity) and the
Stage-2 ceiling (corpus/WARNING.md forbids sending these prompts to a paid
third-party judge). Both are reported in the response rather than applied
silently: a run that was quietly downgraded from Stage 3 would look like
evidence that Stage 3 adds nothing.

The models live here rather than in `models.py` because nothing else uses them,
and a schema is easier to trust next to the only route that returns it.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import regression
from ..cascade.engine import Cascade

# --------------------------------------------------------------------------- #
# Schemas                                                                     #
# --------------------------------------------------------------------------- #
class RunRequest(BaseModel):
    """How much of the corpus to run, and how hard.

    `extra="forbid"` so a misspelled `per_tenets` is a 422 rather than a silent
    full-limit run. This body decides how much compute the server spends, which
    is the last place to be forgiving about typos.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [
            {"limit": 50, "seed": 0, "max_stage": 1},
            {"per_tenet": 20, "seed": 0, "max_stage": 2},
            {"limit": 100, "tenet": "Privacy", "seed": 0, "max_stage": 2},
            {"limit": 60, "owasp": "LLM01", "direction": "input", "seed": 0,
             "max_stage": 2},
            {"limit": 40, "direction": "output", "seed": -1, "max_stage": 2},
        ]})

    limit: int = Field(default=100, ge=1, le=100_000, description=(
        "How many records to run. Capped server-side by `max_sample` from "
        "`GET /v1/corpus` - a selection larger than the cap is a 422 naming the "
        "cap, not a truncated run, because silently running 500 of the 5,000 you "
        "asked for produces a pass rate you would misread."))
    per_tenet: int | None = Field(default=None, ge=1, le=5_000, description=(
        "Stratified sample: N per tenet, INSTEAD of `limit`. Prefer this for a "
        "headline number - the corpus is 42% Profanity / Content Safety, so an "
        "unstratified sample mostly measures one tenet."))
    tenet: str | None = Field(default=None, description=(
        "Restrict to one tenet. `(unmapped)` selects the records with no tenet."))
    owasp: str | None = Field(default=None, description=(
        "Restrict to one OWASP LLM Top 10 code, e.g. `LLM01`. Case-insensitive."))
    direction: Literal["input", "output"] | None = Field(
        default=None, description=(
            "`input` runs prompts through the input guardrail; `output` runs the "
            "519 affirmative target completions through the output guardrail. "
            "Omit for both."))
    seed: int = Field(default=0, description=(
        "Deterministic sample (default 0), so two runs of the same size are "
        "comparable. `-1` draws a genuinely random sample - useful for exploring, "
        "useless for regression testing."))
    max_stage: int = Field(default=2, ge=1, le=3, description=(
        "Cascade ceiling. `1` is free and sub-millisecond. `2` adds the local "
        "models and costs 1-3 s per record. `3` would call a paid third-party "
        "judge and is clamped to 2 unless the server sets "
        "`AFNI_CORPUS_ALLOW_CLOUD=1` - the response says so in `note` when it "
        "was clamped."))


class TenetCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenet: str
    records: int


class OwaspCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    records: int


class DirectionCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: str
    records: int


class CorpusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    records: int = Field(description="Total records in the corpus.")
    baselined: int = Field(description=(
        "How many carry a recorded `expected` verdict. Only these can drift."))
    max_sample: int = Field(description=(
        "The ceiling on one run. `AFNI_CORPUS_MAX_SAMPLE` on the server."))
    cloud_allowed: bool = Field(description=(
        "Whether `max_stage: 3` is permitted. False by default: these are real "
        "harmful prompts and a paid judge is a third party."))
    tenets: list[TenetCount]
    owasp: list[OwaspCount]
    directions: list[DirectionCount]


class RunRow(BaseModel):
    """One record's result.

    `prompt` is TRUNCATED to 120 characters unless `AFNI_REVEAL_SUBJECT` is set
    on the server. The server chose these prompts, not the caller, so echoing
    11,369 harmful prompts in full into whatever logs this response reaches is a
    disclosure rather than a reply. `id` is always complete - cite that.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    direction: str
    tenet: str | None
    owasp: list[str]
    harm_label: str | None
    decision: str = Field(description=(
        "`allow`, `block`, `flag`, or `error` if the cascade raised on this "
        "record. An error is counted separately from a block: it is a broken "
        "check, not a caught prompt."))
    blocking_rail: str | None
    blocking_category: str | None
    findings: int
    unjudged: bool
    stages_run: int = Field(description=(
        "How many stages executed a rail for this record - a count, not a list. "
        "Skipped and short-circuited stages are deliberately not counted, or a "
        "clean request would report as having cost three stages."))
    top_stage: int | None = Field(description=(
        "The highest stage that had to run. `1` everywhere means Stage 1 "
        "short-circuited everything, which is the cascade paying for itself."))
    error: str | None
    expected_decision: str | None
    expected_tier: str | None
    agrees: bool | None = Field(description=(
        "Whether this matches the recorded baseline. `null` means there was "
        "nothing comparable to match - no baseline, or one taken on a different "
        "tier - which is NOT the same as agreement."))


class RunStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample: int
    selection: str
    tier: str = Field(description=(
        "Which tiers can actually judge on this host: `stage_1_only`, "
        "`stage_1_and_2`, `all_stages`. A run is only comparable to a baseline "
        "taken on the same tier."))
    elapsed_ms: float
    ms_per_record: float
    decisions: dict[str, int]
    block_rate: float | None
    unjudged: int
    errors: int
    blocked_by: dict[str, int]
    top_stage: dict[str, int] = Field(description=(
        "How many records stopped at each stage. The free-first ordering is only "
        "worth having if most of the sample stops at 1."))
    baseline_compared: int
    baseline_drift: int
    drifted_ids: list[str]


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stats: RunStats
    rows: list[RunRow]
    note: str | None = Field(default=None, description=(
        "Set when the request was modified - e.g. `max_stage: 3` clamped to 2. "
        "Never silent: a downgraded run must not read as a completed one."))


RUN_BODY = Body(..., description="Which slice of the corpus to run.")

CORPUS_EXAMPLE = {
    "path": "rai_platform/corpus/harm-intents.jsonl",
    "records": 11369, "baselined": 280, "max_sample": 500,
    "cloud_allowed": False,
    "tenets": [{"tenet": "(unmapped)", "records": 5170},
               {"tenet": "Profanity / Content Safety", "records": 4815},
               {"tenet": "Security", "records": 452},
               {"tenet": "Hallucination / Reliability", "records": 321},
               {"tenet": "Privacy", "records": 264},
               {"tenet": "Explainability & Transparency", "records": 246},
               {"tenet": "Fairness & Bias", "records": 101}],
    "owasp": [{"code": "LLM01", "records": 332}, {"code": "LLM02", "records": 264},
              {"code": "LLM05", "records": 120}, {"code": "LLM06", "records": 246},
              {"code": "LLM09", "records": 5237}],
    "directions": [{"direction": "input", "records": 10850},
                   {"direction": "output", "records": 519}],
}

STREAM_EXAMPLE = (
    "event: start\n"
    'data: {"event": "start", "total": 50, "selection": "limit 50, seed=0, '
    'max stage 1", "tier": "stage_1_only"}\n\n'
    "event: row\n"
    'data: {"event": "row", "index": 1, "total": 50, "row": {"id": '
    '"afni-corpus-0004f37b0860", "decision": "allow", "agrees": true}}\n\n'
    "event: summary\n"
    'data: {"event": "summary", "stats": {"sample": 50, "decisions": '
    '{"allow": 49, "block": 1}, "block_rate": 0.02}}\n\n'
    "event: done\ndata: {\"event\": \"done\"}\n\n")


def _error(code: str, message: str, status: int,
           details: dict[str, Any] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status)


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #
def corpus_router(gateway: Any) -> APIRouter:
    """Routes bound to one gateway. Mirrors `_router()` in app.py: a factory
    rather than module-level decorators, so a test can stand up two gateways in
    one interpreter."""
    router = APIRouter()
    # Cascades trimmed to a stage ceiling, built once per ceiling rather than per
    # request. `resolve_threshold` is threaded through so a corpus run honours the
    # same thresholds as live traffic - a regression suite judged by
    # different thresholds than production is measuring the wrong thing.
    cascades: dict[int, Cascade] = {}

    def cascade_for(ceiling: int) -> tuple[Cascade, list[Any]]:
        rails = regression.rails_for(ceiling, gateway.rails)
        if ceiling not in cascades:
            cascades[ceiling] = Cascade(
                rails, resolve_threshold=gateway.thresholds.resolve_value)
        return cascades[ceiling], rails

    @router.get("/v1/corpus", tags=["corpus"], response_model=CorpusResponse,
                summary="What the regression corpus holds, and the run cap",
                responses={200: {"content": {"application/json": {
                    "example": CORPUS_EXAMPLE}}}})
    def corpus() -> JSONResponse:
        """Size a run before you start one.

        The per-tenet counts are here because the corpus is not balanced - 42% of
        it is Profanity / Content Safety - so an unstratified sample of 100
        mostly measures one tenet. Use `per_tenet` for a headline number and
        `tenet` to drill in.

        Loads no rails, so this answers on a bare host with no model weights.
        """
        try:
            return JSONResponse(regression.summary())
        except FileNotFoundError as exc:
            return _error("corpus_missing", str(exc), 503)

    @router.post("/v1/corpus/run", tags=["corpus"], response_model=RunResponse,
                 summary="Run a configurable sample and return every row",
                 response_description=(
                     "Every row plus the aggregate. Read `stats.block_rate` for "
                     "the headline and `stats.baseline_drift` for whether "
                     "anything changed since the recorded baseline."),
                 responses={
                     422: {"description":
                           "The selection is larger than `max_sample`. "
                           "`details.cap` names the ceiling."},
                     503: {"description": "The corpus file is not present."}})
    def corpus_run(body: RunRequest = RUN_BODY) -> JSONResponse:
        """Judge a sample of the corpus and report what the guardrail decided.

        Synchronous, so keep the sample small: at Stage 1 this is under a
        millisecond per record and 500 records finish in half a second, but at
        Stage 2 the same 500 records is roughly twenty minutes of held-open
        request. Use `/v1/corpus/run/stream` for anything you want to watch.
        """
        try:
            records = regression.load()
        except FileNotFoundError as exc:
            return _error("corpus_missing", str(exc), 503)

        ceiling, note = regression.effective_max_stage(body.max_stage)
        selection = regression.Selection(
            limit=body.limit, per_tenet=body.per_tenet, tenet=body.tenet,
            owasp=body.owasp, direction=body.direction, seed=body.seed,
            max_stage=ceiling)
        try:
            chosen = regression.select(records, selection)
        except regression.SampleTooLarge as exc:
            return _error("sample_too_large", str(exc), 422,
                          {"cap": regression.max_sample()})
        if not chosen:
            return _error(
                "empty_selection",
                "no corpus records match that selection. Check `GET /v1/corpus` "
                "for the tenet, OWASP and direction values that exist.", 422,
                {"tenet": body.tenet, "owasp": body.owasp,
                 "direction": body.direction})

        cascade, rails = cascade_for(ceiling)
        result = regression.run(
            cascade, chosen, selection, regression.tier_label(rails),
            reveal=gateway.reveal_subject, note=note)
        return JSONResponse({"stats": result.stats, "rows": result.rows,
                             "note": result.note})

    @router.post("/v1/corpus/run/stream", tags=["corpus"],
                 response_class=StreamingResponse,
                 summary="Run a configurable sample, one SSE frame per record",
                 responses={200: {
                     "description":
                         "`text/event-stream`. One `start` frame, then one `row` "
                         "frame per record AS IT IS JUDGED, then `summary`, then "
                         "`done`. The row frames are what make a Stage-2 run "
                         "watchable - 200 records is ten minutes, and a browser "
                         "given no frames for ten minutes has already given up.",
                     "content": {"text/event-stream": {
                         "schema": {"type": "string"},
                         "example": STREAM_EXAMPLE}}}})
    def corpus_run_stream(body: RunRequest = RUN_BODY) -> Any:
        """The same run, streamed. Errors still come back as JSON with a status
        code, because a 422 delivered as an SSE frame inside a 200 is a 422
        nobody handles."""
        try:
            records = regression.load()
        except FileNotFoundError as exc:
            return _error("corpus_missing", str(exc), 503)

        ceiling, note = regression.effective_max_stage(body.max_stage)
        selection = regression.Selection(
            limit=body.limit, per_tenet=body.per_tenet, tenet=body.tenet,
            owasp=body.owasp, direction=body.direction, seed=body.seed,
            max_stage=ceiling)
        try:
            chosen = regression.select(records, selection)
        except regression.SampleTooLarge as exc:
            return _error("sample_too_large", str(exc), 422,
                          {"cap": regression.max_sample()})
        if not chosen:
            return _error(
                "empty_selection",
                "no corpus records match that selection. Check `GET /v1/corpus` "
                "for the tenet, OWASP and direction values that exist.", 422,
                {"tenet": body.tenet, "owasp": body.owasp,
                 "direction": body.direction})

        cascade, rails = cascade_for(ceiling)
        tier = regression.tier_label(rails)

        def frames() -> Any:
            yield _sse("start", {"total": len(chosen),
                                 "selection": selection.describe(),
                                 "tier": tier, "note": note})
            for frame in regression.iter_run(
                    cascade, chosen, selection, tier,
                    reveal=gateway.reveal_subject):
                kind = frame.pop("kind")
                yield _sse(kind, frame)
            yield _sse("done", {})

        return StreamingResponse(
            frames(), media_type="text/event-stream",
            headers={"cache-control": "no-cache",
                     # Buffering here would defeat the entire point.
                     "x-accel-buffering": "no",
                     "connection": "keep-alive"})

    return router


def _sse(name: str, payload: dict[str, Any]) -> str:
    """One SSE frame, with the event name repeated inside the JSON.

    Same shape as `/v1/guard/stream`: the name is in the `event:` line for
    EventSource and inside the object for anything reading the body as text.
    """
    body = json.dumps({"event": name, **payload}, ensure_ascii=False)
    return f"event: {name}\ndata: {body}\n\n"
