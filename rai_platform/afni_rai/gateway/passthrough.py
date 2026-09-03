# -*- coding: utf-8 -*-
"""
The guarded passthrough: one interaction, two guardrails, one model between them.

    caller -> [INPUT guardrail] -> target model -> [OUTPUT guardrail] -> caller

`/v1/guard` judges text somebody hands it. This is the same cascade wired in
front of and behind a real AI system, which is the topology `docs/architecture.md`
section 1 draws. The order is not an implementation detail, it IS the product:

  1. guard the prompt          `EventKind.REQUEST`
  2. if that blocked, STOP     the target is never called, so the refused prompt
                               costs nothing. This is the commercial argument in
                               executable form, and it is reported explicitly:
                               `target.called: false` and `tokens_saved: true`.
  3. call the target           once, no retry
  4. guard the completion      `EventKind.RESPONSE`
  5. if that blocked, WITHHOLD the completion is not in the response, under any
                               key, in any frame, in any log line, in the audit
                               row. The caller gets the verdict that withheld it.

FAIL CLOSED, EVERYWHERE

Every failure on this path resolves to "no completion reaches the caller":

  the input cascade raises   -> BLOCK (via `Gateway.fail_closed`), target never
                               called. An exception in the guard must never be
                               the reason a prompt reaches the model.
  the target errors/times out-> `target_error`, no completion, and the output
                               guard is not run because there is nothing to run
                               it on.
  the output cascade raises  -> BLOCK and the completion is withheld. A guardrail
                               that fails open on an exception is worse than no
                               guardrail, because it is trusted.

WHY THE REFUSAL IS NEUTRAL

The refusal text names no rail, no category, no matched value and no threshold.
A refusal that explains itself turns the endpoint into an oracle: a caller can
probe it until it learns which detector fired on what, which is a map of the
guardrail handed to whoever wants to route around it. The verdict and explanation
next to it carry the detail, for the operator, on the same response - the split
is about who is reading, not about hiding anything.

WHY `target_done` CARRIES NO TEXT

On the streaming endpoint the target's answer exists before the output guardrail
has judged it. Emitting it in the `target_done` frame would deliver the
completion to the caller a beat before the guard that is supposed to be able to
stop it - the block would be theatre. So `target_done` carries latency, token
counts and nothing that could be a completion, and the text appears only in the
`final` frame, only when the output guard allowed it.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Iterator, Sequence

from ..contract.models import EventKind, GuardEvent, LLMProtocol
from ..target import TargetClient, TargetError
from .models import Error

LOGGER = logging.getLogger("afni_rai.gateway.passthrough")

# The four outcomes. Exhaustive: every path through `run` ends on one of them.
ALLOWED = "allowed"
BLOCKED_ON_INPUT = "blocked_on_input"
BLOCKED_ON_OUTPUT = "blocked_on_output"
TARGET_ERROR = "target_error"

REFUSAL_INPUT = ("I can't help with that request. It was stopped by a policy "
                 "check before it reached the model.")
REFUSAL_OUTPUT = ("I can't share that answer. The model's response was stopped "
                  "by a policy check before it reached you.")
REFUSAL_TARGET_ERROR = ("I couldn't get an answer from the model just now. "
                        "Nothing was returned, so nothing was shown to you "
                        "unchecked.")

NOTES = {
    ALLOWED:
        "both guardrails allowed this interaction",
    BLOCKED_ON_INPUT:
        "the input guardrail blocked this prompt, so the target was NEVER "
        "called - this interaction cost zero target tokens",
    BLOCKED_ON_OUTPUT:
        "the output guardrail blocked the completion, so it was withheld and "
        "appears nowhere in this response",
    TARGET_ERROR:
        "the target did not answer, so there is no completion and the output "
        "guardrail had nothing to judge",
}


def _blocked(body: dict[str, Any]) -> bool:
    """Read the decision out of a `/v1/guard` body.

    Defaults to blocked when the key is missing. That default is the whole
    fail-closed rule at this seam: an unreadable verdict is not an allow.
    """
    return (body.get("verdict") or {}).get("decision", "block") == "block"


class Passthrough:
    """One guarded interaction, built per request from the process-wide Gateway.

    Holds no state of its own. It borrows the Gateway's cascade, policy, audit
    store and trust boundary rather than re-deriving any of them, so a
    passthrough decision is the same decision `/v1/guard` would have made about
    the same text - including the configured thresholds and fail_mode, and
    including `AFNI_REVEAL_SUBJECT`.
    """

    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    @property
    def target(self) -> TargetClient:
        target = getattr(self.gateway, "target", None)
        if target is None:  # pragma: no cover - the routes check this first
            raise TargetError("not_configured",
                              "no target is configured; see AFNI_TARGET_BASE_URL")
        return target

    # ------------------------------------------------------------- plumbing --
    @staticmethod
    def step_id(body: Any) -> str:
        """One id for BOTH halves of the interaction.

        `step_id` is defined upstream as the producer-minted id that binds the
        request and response halves of one model call, so the input verdict and
        the output verdict share it. Two ids would make the audit trail unable to
        answer "what did we send, and what came back" - which is the only
        question anyone asks it after an incident.
        """
        return getattr(body, "step_id", None) or f"chat-{uuid.uuid4().hex[:12]}"

    def event(self, body: Any, kind: EventKind, payload: dict[str, Any],
              step_id: str) -> GuardEvent:
        return GuardEvent(
            kind=kind,
            step_id=step_id,
            agent_id=getattr(body, "agent_id", "") or "",
            agent_type=getattr(body, "agent_type", "") or "chat",
            agent_workspace=getattr(body, "agent_workspace", "") or "",
            agent_user=getattr(body, "agent_user", "") or "",
            llm_protocol=LLMProtocol.OPENAI_CHAT,
            payload=payload,
            integration=getattr(body, "integration", None),
        )

    @staticmethod
    def request_payload(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
        """The prompt, in the provider's own request shape.

        `{"messages": [...]}` is what an `openai.chat` request body looks like,
        which is what `llm_protocol` claims and what the payload walker's path
        names (`payload.messages[0].content`) assume. Inventing a private shape
        here would make a passthrough finding's `path` unrecognisable next to a
        `/v1/guard` one.
        """
        return {"messages": list(messages)}

    @staticmethod
    def response_payload(text: str) -> dict[str, Any]:
        """The completion, in the provider's own response shape.

        Same reason: `payload.choices[0].message.content` is the path the
        output-side rails and the docs already speak.
        """
        return {"choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": text}}]}

    def _guard(self, event: GuardEvent) -> tuple[dict[str, Any], str | None]:
        """Run one cascade and render it exactly as `/v1/guard` would.

        Returns `(body, degraded)`. `degraded` is non-None when the cascade
        itself raised, in which case `body` already carries the fail-closed
        BLOCK - see `Gateway.fail_closed`.
        """
        degraded: str | None = None
        try:
            outcome = self.gateway.cascade.evaluate(event)
        except Exception as exc:  # noqa: BLE001 - fail closed, never a 500
            outcome = self.gateway.fail_closed(event, exc)
            degraded = f"cascade raised {type(exc).__name__}"
        body, _ = self.gateway.finish(event, outcome, degraded=degraded)
        return body, degraded

    def _guard_frames(self, event: GuardEvent, phase: str) -> Iterator[str]:
        """The streaming form of `_guard`: yields SSE strings, returns
        `(body, degraded)`.

        The return value is picked up with `yield from`, which is what lets one
        generator emit another's frames and still get its result. The frames are
        `app._stage_frame` verbatim plus a `phase` key, so a console that already
        renders `/v1/guard/stream` frames renders these without a second parser
        and can still label which guardrail it is watching.
        """
        from .app import _sse, _stage_frame  # noqa: PLC0415 - avoids an import cycle

        generator = self.gateway.cascade.evaluate_iter(event)
        outcome = None
        degraded: str | None = None
        while True:
            try:
                progress = next(generator)
            except StopIteration as stop:
                outcome = stop.value
                break
            except Exception as exc:  # noqa: BLE001 - fail closed, mid-stream
                outcome = self.gateway.fail_closed(event, exc)
                degraded = f"cascade raised {type(exc).__name__}"
                # The same `Error` shape as every other failure surface in this
                # API - one error shape, no exceptions, including inside a
                # stream where the status line is long gone.
                yield _sse("error", {
                    "event": "error", "phase": phase,
                    "error": Error(
                        code="cascade_failed",
                        message="the cascade raised; failing closed with a BLOCK "
                                "verdict and every payload path unjudged",
                        details={"exception": type(exc).__name__,
                                 "phase": phase},
                    ).model_dump(exclude_none=True)})
                break
            frame = _stage_frame(progress, self.gateway.reveal_subject)
            frame["phase"] = phase
            yield _sse("stage", frame)

        body, _ = self.gateway.finish(event, outcome, degraded=degraded)
        return body, degraded

    # --------------------------------------------------------- the response --
    def target_block(self, *, called: bool, completion: Any = None,
                     error: TargetError | None = None,
                     because: str | None = None) -> dict[str, Any]:
        """The `target` block: what was called, what it cost, what went wrong.

        Present on every response, including the ones where nothing was called -
        `called: false` with a reason is the fact the caller most wants, and an
        absent block would leave them inferring it.
        """
        config = self.target.config
        return {
            "called": called,
            "model": config.model,
            "provider": self.target.provider,
            "base_url": config.base_url,
            "latency_ms": getattr(completion, "latency_ms", None),
            "usage": getattr(completion, "usage", None),
            # False until the endpoint itself confirms the id. Nothing in the
            # build environment has ever spoken to it - see /healthz.
            "model_id_verified": bool(getattr(completion, "model_id_verified", False)),
            "error": error.to_dict() if error is not None else None,
            "not_called_because": because,
        }

    def response(self, *, decision: str, step_id: str,
                 input_body: dict[str, Any] | None = None,
                 output_body: dict[str, Any] | None = None,
                 target: dict[str, Any],
                 completion: str | None = None,
                 timing: dict[str, int | None],
                 degraded: list[str] | None = None) -> dict[str, Any]:
        """Assemble the one object that shows all four steps.

        `completion` is the ONLY key that ever carries model text, and it is
        `None` on every decision but `allowed`. Nothing else in this object is
        derived from the completion string.
        """
        refusal = {BLOCKED_ON_INPUT: REFUSAL_INPUT,
                   BLOCKED_ON_OUTPUT: REFUSAL_OUTPUT,
                   TARGET_ERROR: REFUSAL_TARGET_ERROR}.get(decision)
        return {
            "decision": decision,
            "step_id": step_id,
            "note": NOTES[decision],
            "refusal": refusal,
            "input_verdict": (input_body or {}).get("verdict"),
            "input_explanation": (input_body or {}).get("explanation"),
            "output_verdict": (output_body or {}).get("verdict"),
            "output_explanation": (output_body or {}).get("explanation"),
            "target": target,
            "completion": completion if decision == ALLOWED else None,
            # "no target token was spent on this interaction". True exactly when
            # the target was never called, which is the input-block saving and
            # the not-configured case.
            "tokens_saved": not target["called"],
            "timing_ms": timing,
            "degraded": list(degraded or []),
        }

    # -------------------------------------------------------------- the flow --
    def run(self, body: Any) -> dict[str, Any]:
        """Guard, call, guard - and stop at the first block."""
        step_id = self.step_id(body)
        messages = [dict(message) for message in body.messages_as_dicts()]
        degraded: list[str] = []
        timing: dict[str, int | None] = {"input_guard": None, "target": None,
                                         "output_guard": None, "total": None}
        started = time.perf_counter()

        # --- 1 - the prompt ---------------------------------------------------
        mark = time.perf_counter()
        input_event = self.event(body, EventKind.REQUEST,
                                 self.request_payload(messages), step_id)
        input_body, input_degraded = self._guard(input_event)
        timing["input_guard"] = int((time.perf_counter() - mark) * 1000)
        if input_degraded:
            degraded.append(f"input guard: {input_degraded}")

        if _blocked(input_body):
            # THE STEP THAT MATTERS. No target call happens after this return,
            # and there is no code path from here to `self.target.complete`.
            timing["total"] = int((time.perf_counter() - started) * 1000)
            LOGGER.info("event %s blocked on INPUT: the target was not called",
                        step_id)
            return self.response(
                decision=BLOCKED_ON_INPUT, step_id=step_id,
                input_body=input_body,
                target=self.target_block(
                    called=False,
                    because="the input guardrail blocked this prompt"),
                timing=timing, degraded=degraded)

        # --- 2 - the target ---------------------------------------------------
        mark = time.perf_counter()
        try:
            completion = self.target.complete(messages)
        except TargetError as exc:
            timing["target"] = int((time.perf_counter() - mark) * 1000)
            timing["total"] = int((time.perf_counter() - started) * 1000)
            # `exc` carries a kind, a status and an exception type name. It
            # carries no URL and no credential, by construction in target/client.
            LOGGER.warning("event %s target error (%s): %s", step_id, exc.kind, exc)
            return self.response(
                decision=TARGET_ERROR, step_id=step_id, input_body=input_body,
                target=self.target_block(called=True, error=exc),
                timing=timing, degraded=degraded)
        timing["target"] = completion.latency_ms

        # --- 3 - the completion -----------------------------------------------
        mark = time.perf_counter()
        output_event = self.event(body, EventKind.RESPONSE,
                                  self.response_payload(completion.text), step_id)
        output_body, output_degraded = self._guard(output_event)
        timing["output_guard"] = int((time.perf_counter() - mark) * 1000)
        if output_degraded:
            degraded.append(f"output guard: {output_degraded}")
        timing["total"] = int((time.perf_counter() - started) * 1000)

        target = self.target_block(called=True, completion=completion)

        # --- 4 - withhold, or hand it over ------------------------------------
        if _blocked(output_body):
            LOGGER.info("event %s blocked on OUTPUT: the completion was withheld "
                        "(%d chars, not logged)", step_id, len(completion.text))
            return self.response(
                decision=BLOCKED_ON_OUTPUT, step_id=step_id,
                input_body=input_body, output_body=output_body,
                target=target, timing=timing, degraded=degraded)

        return self.response(
            decision=ALLOWED, step_id=step_id, input_body=input_body,
            output_body=output_body, target=target,
            completion=completion.text, timing=timing, degraded=degraded)

    # ----------------------------------------------------------- the stream --
    def stream(self, body: Any) -> Iterator[str]:
        """The same four steps, as Server-Sent Events.

        Frame order is the contract: input `stage` frames, `target_start`,
        `target_done` (or `target_error`), output `stage` frames, `final`,
        `done`. A client that sees `target_start` knows the input guardrail
        allowed the prompt; a client that never sees it knows the prompt was
        refused before anything was spent.
        """
        from .app import _sse  # noqa: PLC0415 - avoids an import cycle

        step_id = self.step_id(body)
        messages = [dict(message) for message in body.messages_as_dicts()]
        degraded: list[str] = []
        timing: dict[str, int | None] = {"input_guard": None, "target": None,
                                         "output_guard": None, "total": None}
        started = time.perf_counter()

        mark = time.perf_counter()
        input_event = self.event(body, EventKind.REQUEST,
                                 self.request_payload(messages), step_id)
        input_body, input_degraded = yield from self._guard_frames(input_event,
                                                                  "input")
        timing["input_guard"] = int((time.perf_counter() - mark) * 1000)
        if input_degraded:
            degraded.append(f"input guard: {input_degraded}")

        if _blocked(input_body):
            timing["total"] = int((time.perf_counter() - started) * 1000)
            final = self.response(
                decision=BLOCKED_ON_INPUT, step_id=step_id, input_body=input_body,
                target=self.target_block(
                    called=False,
                    because="the input guardrail blocked this prompt"),
                timing=timing, degraded=degraded)
            yield _sse("final", {"event": "final", **final})
            yield _sse("done", {"event": "done"})
            return

        config = self.target.config
        yield _sse("target_start", {"event": "target_start", "model": config.model,
                                    "provider": self.target.provider,
                                    "base_url": config.base_url,
                                    "timeout_s": config.timeout})
        mark = time.perf_counter()
        try:
            completion = self.target.complete(messages)
        except TargetError as exc:
            timing["target"] = int((time.perf_counter() - mark) * 1000)
            timing["total"] = int((time.perf_counter() - started) * 1000)
            LOGGER.warning("event %s target error (%s): %s", step_id, exc.kind, exc)
            yield _sse("target_error", {"event": "target_error",
                                        "error": exc.to_dict()})
            final = self.response(
                decision=TARGET_ERROR, step_id=step_id, input_body=input_body,
                target=self.target_block(called=True, error=exc),
                timing=timing, degraded=degraded)
            yield _sse("final", {"event": "final", **final})
            yield _sse("done", {"event": "done"})
            return
        timing["target"] = completion.latency_ms

        # Metadata only. See the module docstring: the text cannot go out here,
        # because the guard that may withhold it has not run yet.
        yield _sse("target_done", {
            "event": "target_done", "model": completion.model,
            "provider": completion.provider, "latency_ms": completion.latency_ms,
            "usage": completion.usage,
            "model_id_verified": completion.model_id_verified,
            "completion_chars": len(completion.text),
            "note": "the completion is withheld until the output guardrail "
                    "has judged it"})

        mark = time.perf_counter()
        output_event = self.event(body, EventKind.RESPONSE,
                                  self.response_payload(completion.text), step_id)
        output_body, output_degraded = yield from self._guard_frames(output_event,
                                                                    "output")
        timing["output_guard"] = int((time.perf_counter() - mark) * 1000)
        if output_degraded:
            degraded.append(f"output guard: {output_degraded}")
        timing["total"] = int((time.perf_counter() - started) * 1000)

        target = self.target_block(called=True, completion=completion)
        if _blocked(output_body):
            LOGGER.info("event %s blocked on OUTPUT: the completion was withheld "
                        "(%d chars, not logged)", step_id, len(completion.text))
            final = self.response(
                decision=BLOCKED_ON_OUTPUT, step_id=step_id,
                input_body=input_body, output_body=output_body, target=target,
                timing=timing, degraded=degraded)
        else:
            final = self.response(
                decision=ALLOWED, step_id=step_id, input_body=input_body,
                output_body=output_body, target=target,
                completion=completion.text, timing=timing, degraded=degraded)
        yield _sse("final", {"event": "final", **final})
        yield _sse("done", {"event": "done"})
