# -*- coding: utf-8 -*-
"""
Tests for the guarded passthrough - `/v1/chat`, `/v1/chat/stream`, the target
adapter, and the judge chain's prefer-local reordering.

`/v1/guard` judges text somebody hands it. `/v1/chat` puts one guardrail on each
side of a real model and calls it. That difference creates failure modes the
guard endpoint cannot have, and every test here is about one of them:

  * the target being called anyway after the input guardrail said no - which
    would mean the input guardrail costs money and stops nothing
  * a blocked completion escaping - in the response body, in an SSE frame, in a
    log line, or in the audit database. Any one of those makes the block theatre
  * a guardrail that fails OPEN on an exception, which is worse than no
    guardrail because it is trusted
  * the API key reaching a log, a repr, an error message or /healthz
  * absent configuration 500ing, or taking the rest of the gateway down with it
  * a startup probe that can hang or fail a boot

Two transports are used deliberately. `httpx.MockTransport` covers the shapes and
the error codes exhaustively and cheaply. A real `http.server` on localhost
covers the actual httpx path - the request that gets built, the header that
carries the credential, a genuine connection refusal and a genuine timeout -
because the user's endpoint is on a private network this build environment
cannot reach, so a mock-only suite would be proving the mock.

MODEL IDS ARE UNVERIFIED THROUGHOUT. Nothing here has spoken to
`http://10.10.10.151:8506/v1`; every model id in this file is a string.

Run: python3 rai_platform/run_tests.py
"""
import ast
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai.cascade.rail import Direction, RailResult, Stage  # noqa: E402
from afni_rai.contract.models import (  # noqa: E402
    Action, Finding, Severity, Tenet,
)
from afni_rai.gateway import providers  # noqa: E402
from afni_rai.gateway.app import create_app  # noqa: E402
from afni_rai.gateway.passthrough import Passthrough  # noqa: E402
from afni_rai.target import (  # noqa: E402
    TargetClient, TargetConfig, TargetError, config_from_env, from_env,
    probe_endpoint,
)
from afni_rai.tenets.accountability.audit import VerdictStore, scan_for_leak  # noqa: E402

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"httpx is not installed: {exc}") from exc

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"fastapi is not installed: {exc}") from exc

# The sentinel the stub target answers with. Every "did the completion escape"
# assertion searches for this exact string, so it is deliberately unlike
# anything the platform emits on its own.
SECRET_ANSWER = "ZZ-COMPLETION-SENTINEL-4f19-do-not-leak"
BASE_URL = "http://target.invalid/v1"
MODEL = "qwen3-vl-8b-instruct"   # UNVERIFIED - a string, never confirmed here
API_KEY = "sk-target-key-do-not-log"


def setUpModule():
    """Silence the platform's own logging for this module.

    Several tests make a cascade raise on purpose, and the fail-closed path logs
    that with a traceback - correctly, since in production it is the only trace
    of a degraded decision. Printed into a passing suite it trains a reader to
    scroll past tracebacks. The tests that assert on log CONTENT re-enable their
    own capture locally.
    """
    logging.getLogger("afni_rai").setLevel(logging.CRITICAL)


# --------------------------------------------------------------------------- #
# Test doubles                                                                 #
# --------------------------------------------------------------------------- #
class MarkerRail:
    """A rail that blocks only on text containing its marker.

    A marker rather than a direction-restricted rail, because the thing under
    test is WHICH TEXT reached the guardrail - the prompt on the way in, the
    completion on the way back. One rail that answers both calls and blocks on
    exactly one of them proves the two calls carry different payloads, which a
    pair of one-sided rails would assume rather than demonstrate.
    """

    tenet = Tenet.PRIVACY
    stage = Stage.STAGE_1
    direction = Direction.BOTH

    def __init__(self, marker, name="test.marker", raises_on=None):
        self.name = name
        self.marker = marker
        self.raises_on = raises_on
        self.seen = []

    def check(self, path, text):
        self.seen.append(text)
        if self.raises_on is not None and self.raises_on in text:
            raise RuntimeError("rail exploded")
        if self.marker in text:
            return RailResult(judged=True, block=True, findings=[Finding(
                category="privacy.pii.us_ssn", severity=Severity.HIGH,
                action=Action.BLOCK, path=path, detector=self.name,
                fp="deadbeef")])
        return RailResult.clean()


class CleanRail(MarkerRail):
    """Blocks nothing. Used where the point is the target call, not the verdict."""

    def __init__(self, name="test.clean"):
        super().__init__(marker="\x00never-matches", name=name)


class ExplodingCascade:
    """An engine that fails, as distinct from a rail that fails - the engine
    already turns a raising rail into `unjudged`, so a rail cannot exercise the
    fail-closed path at the engine level."""

    def __init__(self):
        self.calls = 0

    def evaluate(self, event):
        self.calls += 1
        raise RuntimeError("engine exploded")

    def evaluate_iter(self, event):
        self.calls += 1
        raise RuntimeError("engine exploded")
        yield  # pragma: no cover - makes this a generator function


class CountingTransport:
    """An httpx transport that counts what it was asked for.

    `requests` is the assertion that matters most in this file: proving the
    input-blocked path never called the target means proving this list holds no
    `/chat/completions` entry.
    """

    def __init__(self, handler):
        self.requests = []
        self._transport = httpx.MockTransport(self._record)
        self._handler = handler

    def _record(self, request):
        self.requests.append(request)
        return self._handler(request)

    @property
    def transport(self):
        return self._transport

    def paths(self):
        return [request.url.path for request in self.requests]

    def completions(self):
        return [r for r in self.requests if r.url.path.endswith("/chat/completions")]


def answering(text=SECRET_ANSWER, *, status=200, body=None, model=MODEL,
              usage=None):
    """A handler that answers `/models` and `/chat/completions`."""
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        if body is not None:
            return httpx.Response(status, **body)
        return httpx.Response(status, json={
            "id": "chatcmpl-stub", "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "usage": usage if usage is not None else {
                "prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20},
        })
    return handler


def target(handler=None, *, base_url=BASE_URL, model=MODEL, api_key=None,
           timeout=60.0, max_tokens=None):
    """A `TargetClient` wired to a counting mock transport."""
    counting = CountingTransport(handler or answering())
    client = TargetClient(
        TargetConfig(base_url=base_url, model=model, timeout=timeout,
                     max_tokens=max_tokens, api_key=api_key),
        transport=counting.transport)
    return client, counting


def chat_app(rails, client, *, env=None, **kwargs):
    return TestClient(create_app(warm=False, rails=rails, attributions={},
                                 env={} if env is None else env,
                                 target=client, **kwargs))


def prompt(text="what is a guardrail?", **overrides):
    out = {"messages": [{"role": "user", "content": text}]}
    out.update(overrides)
    return out


def frames(response):
    """Parse an SSE body into `(event_name, object)` pairs, in order."""
    out = []
    name = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            name = line[len("event: "):]
        elif line.startswith("data: "):
            out.append((name, json.loads(line[len("data: "):])))
    return out


# --------------------------------------------------------------------------- #
class TestTheTargetIsNeverCalledWhenTheInputGuardBlocks(unittest.TestCase):
    """The whole commercial argument, as an assertion.

    A prompt refused at the input guardrail costs nothing because the model is
    never asked. If the target is called anyway - to "have the answer ready", or
    because the order got refactored - then the input guardrail costs money and
    prevents nothing, and the claim in `docs/architecture.md` section 1 is
    false. So this asserts the request COUNT, not merely the response.
    """

    def setUp(self):
        self.rail = MarkerRail("BLOCKTHEPROMPT")
        self.client, self.counting = target()
        self.app = chat_app([self.rail], self.client)
        self.response = self.app.post("/v1/chat",
                                      json=prompt("please BLOCKTHEPROMPT now"))
        self.payload = self.response.json()

    def test_the_stub_target_received_zero_completion_requests(self):
        self.assertEqual(self.counting.completions(), [],
                         "the target was called after the input guard blocked")

    def test_the_decision_names_the_side_that_blocked(self):
        self.assertEqual(self.payload["decision"], "blocked_on_input")

    def test_the_response_says_the_target_was_not_called_and_why(self):
        self.assertFalse(self.payload["target"]["called"])
        self.assertIn("input guardrail",
                      self.payload["target"]["not_called_because"])

    def test_the_saving_is_stated_rather_than_left_to_be_inferred(self):
        """`tokens_saved` is the selling point, so it is a field and not a
        deduction the caller has to make from `target.called`."""
        self.assertTrue(self.payload["tokens_saved"])
        self.assertIn("zero target tokens", self.payload["note"])

    def test_there_is_no_completion_and_no_output_verdict(self):
        """The output guardrail cannot have run: there is nothing to judge."""
        self.assertIsNone(self.payload["completion"])
        self.assertIsNone(self.payload["output_verdict"])
        self.assertIsNone(self.payload["output_explanation"])

    def test_the_input_verdict_is_a_block_with_the_finding_that_caused_it(self):
        self.assertEqual(self.payload["input_verdict"]["decision"], "block")
        self.assertEqual(
            [f["category"] for f in self.payload["input_explanation"]["blocked_by"]],
            ["privacy.pii.us_ssn"])

    def test_the_caller_gets_a_refusal_that_names_no_rail(self):
        """A refusal that explains itself is an oracle: a caller could probe it
        until it learned which detector fires on what, which is a map of the
        guardrail for whoever wants to route around it. The detail is in the
        verdict next to it, for the operator."""
        refusal = self.payload["refusal"]
        self.assertTrue(refusal)
        for leak in ("test.marker", "privacy", "BLOCKTHEPROMPT", "ssn"):
            self.assertNotIn(leak, refusal.lower())

    def test_it_is_still_a_200_because_a_block_is_a_decision(self):
        """A blocked prompt is a successful decision, not a transport failure. A
        4xx or 5xx here would be read as an outage by a caller with a
        `try/except: pass`, which is the bug this platform exists to prevent."""
        self.assertEqual(self.response.status_code, 200)

    def test_the_stream_never_emits_target_start(self):
        """The streaming contract makes the same promise visible: a client that
        never sees `target_start` knows nothing was spent."""
        rail = MarkerRail("BLOCKTHEPROMPT")
        client, counting = target()
        app = chat_app([rail], client)
        events = [name for name, _ in
                  frames(app.post("/v1/chat/stream",
                                  json=prompt("BLOCKTHEPROMPT")))]
        self.assertNotIn("target_start", events)
        self.assertNotIn("target_done", events)
        self.assertEqual(counting.completions(), [])
        self.assertEqual(events[-2:], ["final", "done"])


# --------------------------------------------------------------------------- #
class TestTheAllowedPath(unittest.TestCase):
    """Both guardrails allow: the caller gets the answer, and all four steps."""

    def setUp(self):
        self.client, self.counting = target()
        self.app = chat_app([CleanRail()], self.client)
        self.payload = self.app.post("/v1/chat", json=prompt()).json()

    def test_the_completion_is_returned(self):
        self.assertEqual(self.payload["decision"], "allowed")
        self.assertEqual(self.payload["completion"], SECRET_ANSWER)

    def test_the_target_was_called_exactly_once(self):
        """Once. A retry would bill twice for one interaction and could return a
        different answer than the one the verdicts and the audit row describe."""
        self.assertEqual(len(self.counting.completions()), 1)

    def test_the_request_went_to_chat_completions_with_the_configured_model(self):
        sent = json.loads(self.counting.completions()[0].content)
        self.assertEqual(sent["model"], MODEL)
        self.assertEqual(sent["messages"],
                         [{"role": "user", "content": "what is a guardrail?"}])

    def test_both_verdicts_are_present_and_share_one_step_id(self):
        """`step_id` binds the two halves of one model call, which is the only
        way the audit trail can answer "what did we send and what came back"."""
        self.assertEqual(self.payload["input_verdict"]["event_id"],
                         self.payload["output_verdict"]["event_id"])
        self.assertEqual(self.payload["step_id"],
                         self.payload["input_verdict"]["event_id"])

    def test_a_caller_supplied_step_id_is_used_for_both_halves(self):
        payload = self.app.post("/v1/chat",
                                json=prompt(step_id="caller-step-7")).json()
        self.assertEqual(payload["step_id"], "caller-step-7")
        self.assertEqual(payload["output_verdict"]["event_id"], "caller-step-7")

    def test_the_token_counters_come_back(self):
        self.assertEqual(self.payload["target"]["usage"]["total_tokens"], 20)
        self.assertFalse(self.payload["tokens_saved"])

    def test_the_cost_of_guarding_is_reported_next_to_the_cost_of_generating(self):
        timing = self.payload["timing_ms"]
        self.assertEqual(set(timing),
                         {"input_guard", "target", "output_guard", "total"})
        for key, value in timing.items():
            self.assertIsInstance(value, int, key)

    def test_the_output_guard_judged_the_completion_and_not_the_prompt(self):
        """Proof the second call carries the model's text: the same rail saw the
        completion as one of its inputs."""
        rail = CleanRail()
        client, _ = target()
        chat_app([rail], client).post("/v1/chat", json=prompt("a prompt"))
        self.assertIn("a prompt", rail.seen)
        self.assertIn(SECRET_ANSWER, rail.seen)


# --------------------------------------------------------------------------- #
class TestTheBlockedCompletionNeverEscapes(unittest.TestCase):
    """The output guardrail's promise: the answer does not reach the caller.

    Four surfaces, and a leak on any one of them makes the block theatre - the
    response body, the SSE frames, the process log, and the audit database. The
    audit store is checked against its own `scan_for_leak` helper rather than by
    inspecting columns, so the test asserts the platform's own guarantee.
    """

    def setUp(self):
        self.rail = MarkerRail("SENTINEL-4f19", name="test.output_marker")
        self.audit = VerdictStore(":memory:")
        self.client, self.counting = target()
        self.app = chat_app([self.rail], self.client, verdict_store=self.audit)
        self.response = self.app.post("/v1/chat", json=prompt())
        self.payload = self.response.json()

    def test_the_decision_names_the_side_that_blocked(self):
        self.assertEqual(self.payload["decision"], "blocked_on_output")

    def test_the_target_was_called_so_nothing_is_claimed_to_be_saved(self):
        """Honesty in the other direction: these tokens WERE spent, and a
        `tokens_saved: true` here would be a false economy claim."""
        self.assertEqual(len(self.counting.completions()), 1)
        self.assertTrue(self.payload["target"]["called"])
        self.assertFalse(self.payload["tokens_saved"])

    def test_the_completion_key_is_null(self):
        self.assertIsNone(self.payload["completion"])

    def test_the_completion_is_absent_from_the_ENTIRE_response_body(self):
        """Not just from `completion`. "Do not return the blocked text under any
        key" is checked against the serialised body, because a helpful extra
        field - an echo, a preview, a diff - is exactly how this leaks."""
        self.assertNotIn(SECRET_ANSWER, self.response.text)

    def test_the_output_verdict_explains_the_block(self):
        self.assertEqual(self.payload["output_verdict"]["decision"], "block")
        self.assertEqual(
            [f["category"] for f in self.payload["output_explanation"]["blocked_by"]],
            ["privacy.pii.us_ssn"])

    def test_the_input_verdict_is_still_reported_as_an_allow(self):
        """All four steps, whichever way it went: the console renders one shape."""
        self.assertEqual(self.payload["input_verdict"]["decision"], "allow")

    def test_the_completion_is_absent_from_every_sse_frame(self):
        response = self.app.post("/v1/chat/stream", json=prompt())
        self.assertNotIn(SECRET_ANSWER, response.text)
        names = [name for name, _ in frames(response)]
        self.assertIn("target_done", names)

    def test_target_done_reports_the_length_but_not_the_text(self):
        """The completion exists before the output guardrail has judged it.
        Streaming it in `target_done` would deliver it a beat before the guard
        that is supposed to be able to stop it."""
        done = dict(frames(self.app.post("/v1/chat/stream", json=prompt())))["target_done"]
        self.assertEqual(done["completion_chars"], len(SECRET_ANSWER))
        self.assertNotIn(SECRET_ANSWER, json.dumps(done))

    def test_the_audit_database_holds_no_completion_text(self):
        self.assertEqual(scan_for_leak(self.audit, [SECRET_ANSWER]), [])

    def test_the_audit_database_still_recorded_both_verdicts(self):
        """Withholding the text is not the same as not recording the decision.
        Two rows, one per direction, both keyed to the same step."""
        self.assertEqual(self.audit.count("verdicts"), 2)

    def test_nothing_logged_the_completion(self):
        """A log line is the leak nobody tests for, and it is the one that ends
        up in a shipped-off log aggregator. Captured at DEBUG across the whole
        `afni_rai` tree, including the fail-closed and audit paths."""
        logger = logging.getLogger("afni_rai")
        previous = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            with self.assertLogs("afni_rai", level="DEBUG") as captured:
                self.app.post("/v1/chat", json=prompt())
        finally:
            logger.setLevel(previous)
        for line in captured.output:
            self.assertNotIn(SECRET_ANSWER, line)


# --------------------------------------------------------------------------- #
class TestFailClosed(unittest.TestCase):
    """Every failure on this path resolves to "no completion reaches the caller".

    A guardrail that fails open on an exception is worse than no guardrail,
    because something is relying on it. NeMo Guardrails' jailbreak rail ships
    fail-open (`docs/.../jailbreak-protection.mdx:112`), which is exactly why
    each of these is pinned rather than assumed.
    """

    def test_an_input_cascade_that_raises_blocks_and_never_calls_the_target(self):
        client, counting = target()
        app = chat_app([CleanRail()], client)
        app.app.state.gateway.cascade = ExplodingCascade()
        response = app.post("/v1/chat", json=prompt())
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["decision"], "blocked_on_input")
        self.assertEqual(counting.completions(), [],
                         "an exception in the input guard let the prompt through")
        self.assertIsNone(payload["completion"])

    def test_a_failed_guard_says_the_block_was_a_failure_and_not_a_judgement(self):
        """`degraded` is the difference between "we looked and refused" and "we
        could not look". Both block; only one is evidence about the payload."""
        client, _ = target()
        app = chat_app([CleanRail()], client)
        app.app.state.gateway.cascade = ExplodingCascade()
        response = app.post("/v1/chat", json=prompt())
        self.assertIn("input guard", response.json()["degraded"][0])
        self.assertIn("x-afni-degraded", response.headers)

    def test_an_output_cascade_that_raises_blocks_and_withholds_the_completion(self):
        """The dangerous half. The completion already exists here, so failing
        open would mean handing over text nothing judged."""
        client, _ = target()
        app = chat_app([CleanRail()], client)
        gateway = app.app.state.gateway
        real = gateway.cascade

        class RaisesOnResponse:
            """Judges the prompt, explodes on the completion."""

            def evaluate(self, event):
                if event.kind.value == "step/response":
                    raise RuntimeError("engine exploded on the response")
                return real.evaluate(event)

            def evaluate_iter(self, event):
                if event.kind.value == "step/response":
                    raise RuntimeError("engine exploded on the response")
                return real.evaluate_iter(event)

        gateway.cascade = RaisesOnResponse()
        response = app.post("/v1/chat", json=prompt())
        payload = response.json()
        self.assertEqual(payload["decision"], "blocked_on_output")
        self.assertIsNone(payload["completion"])
        self.assertNotIn(SECRET_ANSWER, response.text)
        self.assertIn("output guard", payload["degraded"][0])

    def test_a_rail_that_raises_is_unjudged_and_still_blocks(self):
        """The engine converts a raising RAIL into `unjudged`, and `unjudged` is
        always a block. Same outcome as a real finding, different mechanism."""
        client, counting = target()
        app = chat_app([MarkerRail("x", raises_on="what is a guardrail?")], client)
        payload = app.post("/v1/chat", json=prompt()).json()
        self.assertEqual(payload["decision"], "blocked_on_input")
        self.assertEqual(payload["input_explanation"]["could_not_judge"],
                         ["payload.messages[0].content"])
        self.assertEqual(counting.completions(), [])

    def test_a_stream_whose_input_guard_raises_reports_it_inside_the_stream(self):
        """The status line is long gone by then, so the failure has to be a
        frame. A client that saw two stages and then silence cannot tell a crash
        from an allow."""
        client, counting = target()
        app = chat_app([CleanRail()], client)
        app.app.state.gateway.cascade = ExplodingCascade()
        parsed = frames(app.post("/v1/chat/stream", json=prompt()))
        names = [name for name, _ in parsed]
        self.assertIn("error", names)
        self.assertNotIn("target_start", names)
        self.assertEqual(counting.completions(), [])
        final = dict(parsed)["final"]
        self.assertEqual(final["decision"], "blocked_on_input")

    # --- the target failing ------------------------------------------------- #
    def _target_error(self, handler, **kwargs):
        client, counting = target(handler, **kwargs)
        app = chat_app([CleanRail()], client)
        response = app.post("/v1/chat", json=prompt())
        return response, response.json(), counting

    def test_a_five_hundred_from_the_target_is_target_error_with_no_completion(self):
        response, payload, _ = self._target_error(answering(status=500))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["decision"], "target_error")
        self.assertIsNone(payload["completion"])
        self.assertEqual(payload["target"]["error"]["kind"], "http_status")
        self.assertEqual(payload["target"]["error"]["status"], 500)

    def test_a_target_error_does_not_pretend_the_output_guard_ran(self):
        """There was nothing to judge, so claiming an output verdict would be
        inventing one - the same class of lie as a guessed judge score."""
        _, payload, _ = self._target_error(answering(status=500))
        self.assertIsNone(payload["output_verdict"])
        self.assertIsNone(payload["output_explanation"])

    def test_a_connection_failure_is_target_error_and_names_only_the_type(self):
        def refused(request):
            raise httpx.ConnectError("connection refused")
        _, payload, _ = self._target_error(refused)
        self.assertEqual(payload["decision"], "target_error")
        self.assertEqual(payload["target"]["error"]["kind"], "transport")
        self.assertEqual(payload["target"]["error"]["exception"], "ConnectError")

    def test_a_timeout_is_reported_as_a_timeout_rather_than_a_transport_error(self):
        """An operator reads these two differently: one means the endpoint is
        unreachable, the other means it is thinking for too long."""
        def slow(request):
            raise httpx.ReadTimeout("too slow")
        _, payload, _ = self._target_error(slow)
        self.assertEqual(payload["target"]["error"]["kind"], "timeout")

    def test_a_404_points_at_the_model_id_because_that_is_what_causes_it(self):
        _, payload, _ = self._target_error(answering(status=404))
        self.assertIn("AFNI_TARGET_MODEL", payload["target"]["error"]["message"])

    def test_a_two_hundred_with_no_choices_is_a_failure_not_an_empty_answer(self):
        """An empty completion is indistinguishable from a terse model, so it
        must not be manufactured out of a malformed response."""
        _, payload, _ = self._target_error(
            answering(body={"json": {"model": MODEL, "choices": []}}))
        self.assertEqual(payload["target"]["error"]["kind"], "bad_response")
        self.assertIsNone(payload["completion"])

    def test_a_non_json_body_is_a_failure(self):
        _, payload, _ = self._target_error(
            answering(body={"text": "<html>gateway timeout</html>"}))
        self.assertEqual(payload["target"]["error"]["kind"], "bad_response")

    def test_a_target_error_still_reports_the_input_verdict_it_already_had(self):
        _, payload, _ = self._target_error(answering(status=500))
        self.assertEqual(payload["input_verdict"]["decision"], "allow")

    def test_the_stream_emits_target_error_then_final(self):
        client, _ = target(answering(status=503))
        app = chat_app([CleanRail()], client)
        parsed = frames(app.post("/v1/chat/stream", json=prompt()))
        names = [name for name, _ in parsed]
        self.assertEqual(names[-3:], ["target_error", "final", "done"])
        self.assertEqual(dict(parsed)["final"]["decision"], "target_error")


# --------------------------------------------------------------------------- #
class TestTheStreamOrderIsTheContract(unittest.TestCase):
    """`input stages -> target_start -> target_done -> output stages -> final`.

    The order is what a console renders as a journey, and it is also the proof
    that the guards run where they claim to: `target_start` after the input
    frames means the prompt was judged before the model saw it.
    """

    def setUp(self):
        self.client, self.counting = target()
        self.app = chat_app([CleanRail(), CleanRail("test.clean2")], self.client)
        self.parsed = frames(self.app.post("/v1/chat/stream", json=prompt()))

    def test_the_frames_arrive_in_the_documented_order(self):
        names = [name for name, _ in self.parsed]
        self.assertEqual(names[0], "stage")
        self.assertLess(names.index("target_start"), names.index("target_done"))
        self.assertEqual(names[-2:], ["final", "done"])

    def test_every_stage_frame_says_which_guardrail_it_belongs_to(self):
        """Both guardrails emit `stage` frames, so without `phase` a console
        would render six stages of one cascade instead of two cascades."""
        phases = [obj["phase"] for name, obj in self.parsed if name == "stage"]
        self.assertEqual(set(phases), {"input", "output"})
        self.assertEqual(phases, sorted(phases, key=["input", "output"].index),
                         "output stage frames arrived before the input ones")

    def test_the_input_stages_all_precede_target_start(self):
        names = [name for name, _ in self.parsed]
        start = names.index("target_start")
        first_output = min(i for i, (n, o) in enumerate(self.parsed)
                           if n == "stage" and o["phase"] == "output")
        self.assertTrue(all(obj["phase"] == "input"
                            for name, obj in self.parsed[:start] if name == "stage"))
        self.assertGreater(first_output, start)

    def test_a_stage_frame_keeps_the_shape_the_guard_stream_already_uses(self):
        """The console has a parser for `/v1/guard/stream` frames. Adding a key
        is additive; renaming or dropping one would need a second parser."""
        frame = next(obj for name, obj in self.parsed if name == "stage")
        for key in ("event", "stage", "ran", "rails_run", "rails_skipped",
                    "findings", "stage_findings", "unjudged", "short_circuited",
                    "will_escalate", "stage_latency_ms", "elapsed_ms"):
            self.assertIn(key, frame)

    def test_target_start_carries_the_model_and_endpoint_but_no_credential(self):
        start = dict(self.parsed)["target_start"]
        self.assertEqual(start["model"], MODEL)
        self.assertEqual(start["base_url"], BASE_URL)
        self.assertNotIn("api_key", json.dumps(start))

    def test_the_final_frame_is_the_same_object_the_json_endpoint_returns(self):
        """One shape for both endpoints, or a console has to learn two."""
        streamed = dict(self.parsed)["final"]
        posted = self.app.post("/v1/chat", json=prompt()).json()
        self.assertEqual(set(streamed) - {"event"}, set(posted))
        self.assertEqual(streamed["decision"], posted["decision"])
        self.assertEqual(streamed["completion"], posted["completion"])

    def test_the_content_type_is_event_stream(self):
        response = self.app.post("/v1/chat/stream", json=prompt())
        self.assertTrue(
            response.headers["content-type"].startswith("text/event-stream"))


# --------------------------------------------------------------------------- #
class TestAbsentConfigurationDegradesHonestly(unittest.TestCase):
    """No target configured is a supported state, not a broken one.

    The gateway shipped as a judge-only service and still is one. So the two
    chat endpoints have to fail legibly while every other endpoint keeps working,
    and neither may 500 - a 500 sends whoever reads it looking for a bug in the
    cascade.
    """

    def setUp(self):
        self.app = TestClient(create_app(warm=False, rails=[CleanRail()],
                                         attributions={}, env={}))

    def test_chat_is_a_503_in_the_one_error_shape(self):
        response = self.app.post("/v1/chat", json=prompt())
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["code"], "target_not_configured")
        self.assertEqual(set(payload) - {"details", "request_id"},
                         {"code", "message"})

    def test_the_error_names_the_variables_to_set(self):
        details = self.app.post("/v1/chat", json=prompt()).json()["details"]
        self.assertEqual(details["set"],
                         ["AFNI_TARGET_BASE_URL", "AFNI_TARGET_MODEL"])

    def test_the_stream_endpoint_refuses_the_same_way(self):
        response = self.app.post("/v1/chat/stream", json=prompt())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "target_not_configured")

    def test_it_is_not_a_500(self):
        for path in ("/v1/chat", "/v1/chat/stream"):
            with self.subTest(path=path):
                self.assertLess(self.app.post(path, json=prompt()).status_code, 504)

    def test_the_rest_of_the_gateway_is_unaffected(self):
        self.assertEqual(self.app.get("/healthz").status_code, 200)
        self.assertEqual(self.app.get("/v1/rails").status_code, 200)
        guard = self.app.post("/v1/guard", json={
            "kind": "step/request", "step_id": "s1", "agent_id": "a",
            "agent_type": "chat", "agent_workspace": "afni", "agent_user": "u",
            "llm_protocol": "openai.chat",
            "payload": {"messages": [{"role": "user", "content": "hello"}]}})
        self.assertEqual(guard.status_code, 200)
        self.assertEqual(guard.json()["verdict"]["decision"], "allow")

    def test_a_base_url_with_no_model_id_is_refused_rather_than_guessed(self):
        """A guessed model id is a 404 per request, which reads as an outage.
        Half-configured therefore means not configured, loudly."""
        self.assertIsNone(config_from_env({"AFNI_TARGET_BASE_URL": BASE_URL}))
        self.assertIsNone(from_env({"AFNI_TARGET_BASE_URL": BASE_URL}))

    def test_an_empty_environment_configures_no_target_and_makes_no_call(self):
        self.assertIsNone(from_env({}))

    def test_a_request_with_no_messages_is_a_422_not_a_500(self):
        client, counting = target()
        app = chat_app([CleanRail()], client)
        self.assertEqual(app.post("/v1/chat", json={"messages": []}).status_code,
                         422)
        self.assertEqual(counting.completions(), [])

    def test_an_unknown_field_is_rejected_rather_than_ignored(self):
        """`extra=forbid`, matching `/v1/guard`. A silently ignored field means
        a caller believing they configured something the gateway never saw."""
        client, _ = target()
        app = chat_app([CleanRail()], client)
        response = app.post("/v1/chat",
                            json=prompt(client_facin=False))
        self.assertEqual(response.status_code, 422)

    def test_the_model_is_not_a_request_field(self):
        """A caller who can choose the model can route around whichever model the
        deployment was reviewed and priced against. Same reasoning as
        AFNI_REVEAL_SUBJECT being server-side only."""
        client, counting = target()
        app = chat_app([CleanRail()], client)
        response = app.post("/v1/chat", json=prompt(model="some-other-model"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(counting.completions(), [])


# --------------------------------------------------------------------------- #
class TestTheCredentialNeverEscapes(unittest.TestCase):
    """The API key is used in exactly one place - an Authorization header - and
    appears nowhere else. A key in a log is a rotated key."""

    def setUp(self):
        self.client, self.counting = target(api_key=API_KEY)
        self.app = chat_app([CleanRail()], self.client)

    def test_it_is_sent_as_a_bearer_header(self):
        self.app.post("/v1/chat", json=prompt())
        sent = self.counting.completions()[0]
        self.assertEqual(sent.headers["authorization"], f"Bearer {API_KEY}")

    def test_it_is_absent_from_the_response_body(self):
        response = self.app.post("/v1/chat", json=prompt())
        self.assertNotIn(API_KEY, response.text)

    def test_it_is_absent_from_healthz_which_reports_only_a_boolean(self):
        response = self.app.get("/healthz")
        self.assertNotIn(API_KEY, response.text)
        self.assertTrue(response.json()["target"]["api_key_configured"])

    def test_it_is_absent_from_a_target_error_body(self):
        """The error path is where a credential usually leaks, via an exception
        message carrying the request URL."""
        client, _ = target(answering(status=401), api_key=API_KEY)
        payload = chat_app([CleanRail()], client).post(
            "/v1/chat", json=prompt()).json()
        self.assertEqual(payload["decision"], "target_error")
        self.assertNotIn(API_KEY, json.dumps(payload))

    def test_it_is_absent_from_the_client_repr_that_a_traceback_would_print(self):
        self.assertNotIn(API_KEY, repr(self.client))
        self.assertNotIn(API_KEY, repr(self.client.config))
        self.assertNotIn(API_KEY, json.dumps(self.client.describe()))

    def test_no_length_hint_is_published_either(self):
        described = self.client.describe()
        self.assertIs(described["api_key_configured"], True)
        self.assertNotIn(str(len(API_KEY)), json.dumps(described))

    def test_no_authorization_header_is_sent_when_no_key_is_configured(self):
        """An empty Bearer header is rejected by some local servers, so absent
        must mean absent rather than empty."""
        client, counting = target()
        chat_app([CleanRail()], client).post("/v1/chat", json=prompt())
        self.assertNotIn("authorization", counting.completions()[0].headers)

    def test_nothing_logs_the_credential(self):
        logger = logging.getLogger("afni_rai")
        previous = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            with self.assertLogs("afni_rai", level="DEBUG") as captured:
                self.app.post("/v1/chat", json=prompt())
                self.app.get("/healthz")
        finally:
            logger.setLevel(previous)
        for line in captured.output:
            self.assertNotIn(API_KEY, line)


# --------------------------------------------------------------------------- #
class TestTheTargetAdapter(unittest.TestCase):
    """The adapter itself: configuration, parsing, and the leak barriers."""

    def test_every_value_comes_from_the_environment(self):
        config = config_from_env({
            "AFNI_TARGET_BASE_URL": "http://10.10.10.151:8506/v1/",
            "AFNI_TARGET_MODEL": MODEL,
            "AFNI_TARGET_API_KEY": API_KEY,
            "AFNI_TARGET_TIMEOUT": "12.5",
            "AFNI_TARGET_MAX_TOKENS": "256"})
        self.assertEqual(config.base_url, "http://10.10.10.151:8506/v1")
        self.assertEqual(config.model, MODEL)
        self.assertEqual(config.timeout, 12.5)
        self.assertEqual(config.max_tokens, 256)
        self.assertTrue(config.api_key_configured)

    def test_the_defaults_are_the_documented_ones_and_nothing_is_invented(self):
        config = config_from_env({"AFNI_TARGET_BASE_URL": BASE_URL,
                                  "AFNI_TARGET_MODEL": MODEL})
        self.assertEqual(config.timeout, 60.0)     # .env.example ships 60
        self.assertIsNone(config.max_tokens)
        self.assertIsNone(config.api_key)

    def test_a_nonsense_timeout_falls_back_rather_than_crashing_the_boot(self):
        for bad in ("abc", "-5", "0"):
            with self.subTest(bad=bad):
                config = config_from_env({"AFNI_TARGET_BASE_URL": BASE_URL,
                                          "AFNI_TARGET_MODEL": MODEL,
                                          "AFNI_TARGET_TIMEOUT": bad})
                self.assertEqual(config.timeout, 60.0)

    def test_max_tokens_is_only_sent_when_it_is_configured(self):
        client, counting = target()
        client.complete([{"role": "user", "content": "hi"}])
        self.assertNotIn("max_tokens", json.loads(counting.completions()[0].content))
        client, counting = target(max_tokens=64)
        client.complete([{"role": "user", "content": "hi"}])
        self.assertEqual(json.loads(counting.completions()[0].content)["max_tokens"], 64)

    def test_a_list_shaped_content_is_read_rather_than_rejected(self):
        """A vision-language model - which `qwen3-vl-8b-instruct` is - can answer
        with content parts. Dropping that shape would turn a good answer into
        `bad_response`."""
        client, _ = target(answering(body={"json": {
            "model": MODEL,
            "choices": [{"message": {"role": "assistant", "content": [
                {"type": "text", "text": "part one "},
                {"type": "text", "text": "part two"}]}}]}}))
        self.assertEqual(client.complete([{"role": "user", "content": "hi"}]).text,
                         "part one part two")

    def test_the_model_id_is_verified_only_by_the_endpoints_own_answer(self):
        client, _ = target(answering(model=MODEL))
        self.assertTrue(client.complete([{"role": "user", "content": "x"}])
                        .model_id_verified)
        client, _ = target(answering(model="something-else"))
        self.assertFalse(client.complete([{"role": "user", "content": "x"}])
                         .model_id_verified)

    def test_the_reported_model_is_ours_and_never_the_servers_string(self):
        """The response's `model` field is text the target server controls.
        Echoing it would put server-controlled content into a response whose
        whole job is to withhold server-controlled content on a block."""
        client, _ = target(answering(model="../../etc/passwd"))
        completion = client.complete([{"role": "user", "content": "x"}])
        self.assertEqual(completion.model, MODEL)
        self.assertFalse(completion.model_id_verified)

    def test_usage_carries_integers_only_so_it_cannot_carry_a_completion(self):
        """`usage` is a dict the target server controls. If prose could ride in
        it, a blocked completion would have a channel straight through the
        block."""
        client, _ = target(answering(usage={
            "prompt_tokens": 5, "completion_tokens": 7,
            "note": SECRET_ANSWER,
            "completion_tokens_details": {"reasoning_tokens": 3,
                                          "leak": SECRET_ANSWER}}))
        usage = client.complete([{"role": "user", "content": "x"}]).usage
        self.assertEqual(usage, {"prompt_tokens": 5, "completion_tokens": 7,
                                 "completion_tokens_details":
                                     {"reasoning_tokens": 3}})
        self.assertNotIn(SECRET_ANSWER, json.dumps(usage))

    def test_a_target_error_message_never_carries_the_exception_message(self):
        """httpx exception messages embed the request URL, and a base URL is the
        one place a credential could travel in a query string. Only the TYPE is
        reported."""
        def boom(request):
            raise httpx.ConnectError(f"failed connecting to {BASE_URL}?key={API_KEY}")
        client, _ = target(boom)
        with self.assertRaises(TargetError) as caught:
            client.complete([{"role": "user", "content": "x"}])
        self.assertNotIn(API_KEY, str(caught.exception))
        self.assertNotIn(BASE_URL, str(caught.exception))
        self.assertEqual(caught.exception.exception, "ConnectError")

    def test_the_post_goes_to_chat_completions_under_the_configured_base_url(self):
        client, counting = target()
        client.complete([{"role": "user", "content": "x"}])
        self.assertEqual(str(counting.completions()[0].url),
                         f"{BASE_URL}/chat/completions")

    def test_a_probe_never_raises_whatever_the_endpoint_does(self):
        """A probe that can raise is a probe that can stop a boot."""
        def boom(request):
            raise httpx.ConnectError("refused")
        client, _ = target(boom)
        probe = client.probe(0.1)
        self.assertFalse(probe.reachable)
        self.assertIn("ConnectError", probe.detail)

    def test_a_probe_verifies_the_model_id_from_a_models_listing(self):
        client, _ = target()
        probe = client.probe(1.0)
        self.assertTrue(probe.reachable)
        self.assertTrue(probe.model_id_verified)
        self.assertEqual(probe.models_listed, 1)

    def test_a_probe_of_an_endpoint_without_a_models_route_is_still_reachable(self):
        """Not every OpenAI-compatible server implements /models. A 404 means the
        server answered, which is what reachable means - it just cannot verify
        the id."""
        def no_models(request):
            return httpx.Response(404, json={"error": "not found"})
        client, _ = target(no_models)
        probe = client.probe(1.0)
        self.assertTrue(probe.reachable)
        self.assertFalse(probe.model_id_verified)

    def test_a_five_hundred_from_the_probe_is_not_reachable(self):
        def broken(request):
            return httpx.Response(503, text="upstream down")
        client, _ = target(broken)
        self.assertFalse(client.probe(1.0).reachable)


# --------------------------------------------------------------------------- #
class TestHealthzReportsTheTarget(unittest.TestCase):
    """An operator asking "is the passthrough working" must get the answer in
    one call, without it becoming a call to someone else's model server."""

    def test_an_absent_target_is_reported_as_absent_not_as_unreachable(self):
        """Three-valued on purpose: `reachable: null` means nobody asked. False
        would report an outage on a correctly configured judge-only gateway."""
        app = TestClient(create_app(warm=False, rails=[CleanRail()],
                                    attributions={}, env={}))
        block = app.get("/healthz").json()["target"]
        self.assertFalse(block["configured"])
        self.assertIsNone(block["reachable"])
        self.assertIn("AFNI_TARGET_BASE_URL", block["note"])

    def test_an_absent_target_does_not_make_the_gateway_degraded(self):
        app = TestClient(create_app(warm=False, rails=[CleanRail()],
                                    attributions={}, env={}))
        self.assertEqual(app.get("/healthz").json()["status"], "ok")

    def test_a_reachable_target_is_reported_with_its_model_and_endpoint(self):
        client, _ = target()
        block = chat_app([CleanRail()], client).get("/healthz").json()["target"]
        self.assertTrue(block["configured"])
        self.assertTrue(block["reachable"])
        self.assertEqual(block["model"], MODEL)
        self.assertEqual(block["base_url"], BASE_URL)
        self.assertEqual(block["provider"], "local")

    def test_an_unreachable_configured_target_is_a_degradation(self):
        """`/v1/chat` cannot work until it comes back, and `degraded` still
        serves - so this is a degradation and not an outage."""
        def refused(request):
            raise httpx.ConnectError("refused")
        client, _ = target(refused)
        health = chat_app([CleanRail()], client).get("/healthz").json()
        self.assertEqual(health["status"], "degraded")
        self.assertFalse(health["target"]["reachable"])

    def test_an_unverified_model_id_says_so_in_those_words(self):
        """Nothing in this build environment has spoken to the user's endpoint,
        so the id is configuration rather than a fact - and the health block has
        to say which."""
        def no_models(request):
            if request.url.path.endswith("/models"):
                return httpx.Response(404)
            return answering()(request)
        client, _ = target(no_models)
        block = chat_app([CleanRail()], client).get("/healthz").json()["target"]
        self.assertFalse(block["model_id_verified"])
        self.assertIn("UNVERIFIED", block["note"])

    def test_a_verified_model_id_is_reported_as_verified(self):
        client, _ = target()
        block = chat_app([CleanRail()], client).get("/healthz").json()["target"]
        self.assertTrue(block["model_id_verified"])
        self.assertIn("VERIFIED", block["note"])

    def test_the_probe_is_not_repeated_per_healthz_hit(self):
        """A liveness endpoint that reaches out per hit makes this gateway's
        health depend on a third party's, and points every monitoring poll at
        someone's inference server."""
        client, counting = target()
        app = chat_app([CleanRail()], client)
        before = len(counting.requests)
        for _ in range(5):
            app.get("/healthz")
        self.assertEqual(len(counting.requests), before)

    def test_the_startup_probe_can_be_skipped_entirely(self):
        client, counting = target()
        chat_app([CleanRail()], client, probe=False)
        self.assertEqual(counting.requests, [])

    def test_a_probe_that_never_ran_is_not_reported_as_unreachable(self):
        client, _ = target()
        block = chat_app([CleanRail()], client,
                         probe=False).get("/healthz").json()["target"]
        self.assertIsNone(block["reachable"])
        self.assertEqual(block["probe"]["detail"], "not probed")


# --------------------------------------------------------------------------- #
# A real HTTP server, for the real httpx path                                  #
# --------------------------------------------------------------------------- #
class StubTargetServer:
    """A tiny OpenAI-compatible server on localhost.

    `httpx.MockTransport` covers response shapes exhaustively and cheaply, but it
    substitutes the transport - so it cannot prove the request httpx actually
    builds, the header that carries the credential, a real connection refusal or
    a real timeout. The user's endpoint is on a private network this build
    environment cannot reach, so without this the httpx path would be entirely
    untested and the suite would be proving the mock.
    """

    def __init__(self, *, answer=SECRET_ANSWER, status=200, delay=0.0,
                 models=(MODEL,), body=None):
        self.answer = answer
        self.status = status
        self.delay = delay
        self.models = list(models)
        self.body = body
        self.requests = []          # (method, path, has_auth)
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _send(self, code, payload):
                blob = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)

            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's name
                stub.requests.append(("GET", self.path,
                                      "authorization" in
                                      {k.lower() for k in self.headers}))
                if self.path.endswith("/models"):
                    self._send(200, {"data": [{"id": m} for m in stub.models]})
                    return
                self._send(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length)
                stub.requests.append(("POST", self.path,
                                      "authorization" in
                                      {k.lower() for k in self.headers}))
                stub.last_body = json.loads(raw or b"{}")
                if stub.delay:
                    time.sleep(stub.delay)
                if stub.body is not None:
                    self._send(stub.status, stub.body)
                    return
                self._send(stub.status, {
                    "id": "chatcmpl-stub", "model": MODEL,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant",
                                             "content": stub.answer}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 5,
                              "total_tokens": 12}})

            def log_message(self, *args):  # keep the suite's output readable
                pass

        class Quiet(ThreadingHTTPServer):
            """Swallows the BrokenPipeError the timeout test necessarily causes.

            That test abandons the request while this server is still writing the
            reply, which is the correct behaviour on both sides - but the default
            handler prints a traceback into the middle of a passing suite, and a
            suite that prints tracebacks teaches its reader to ignore them.
            """

            daemon_threads = True

            def handle_error(self, request, client_address):
                pass

        self._server = Quiet(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def completions(self):
        return [r for r in self.requests if r[1].endswith("/chat/completions")]

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def free_port():
    """A port nothing is listening on, for the connection-refused tests."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestAgainstARealHttpServer(unittest.TestCase):
    """The httpx path, end to end, over a real socket."""

    @classmethod
    def setUpClass(cls):
        cls.stub = StubTargetServer()

    @classmethod
    def tearDownClass(cls):
        cls.stub.close()

    def app(self, rails, **env_extra):
        env = {"AFNI_TARGET_BASE_URL": self.stub.base_url,
               "AFNI_TARGET_MODEL": MODEL,
               "AFNI_TARGET_API_KEY": API_KEY}
        env.update(env_extra)
        return TestClient(create_app(warm=False, rails=rails, attributions={},
                                     env=env))

    def test_the_target_is_built_from_the_environment_alone(self):
        """Nothing hardcoded: the client under test here was constructed by
        `from_env` off a dict, exactly as it is at boot."""
        client = from_env({"AFNI_TARGET_BASE_URL": self.stub.base_url,
                           "AFNI_TARGET_MODEL": MODEL})
        self.addCleanup(client.close)   # or the pooled socket outlives the suite
        completion = client.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(completion.text, SECRET_ANSWER)
        self.assertEqual(completion.model, MODEL)
        self.assertTrue(completion.model_id_verified)
        self.assertEqual(completion.usage["total_tokens"], 12)

    def test_a_real_request_carries_the_bearer_header(self):
        before = len(self.stub.completions())
        payload = self.app([CleanRail()]).post("/v1/chat", json=prompt()).json()
        self.assertEqual(payload["decision"], "allowed")
        self.assertEqual(payload["completion"], SECRET_ANSWER)
        method, path, has_auth = self.stub.completions()[before]
        self.assertEqual((method, path), ("POST", "/v1/chat/completions"))
        self.assertTrue(has_auth)

    def test_an_input_block_leaves_the_real_server_untouched(self):
        """The same assertion as the mocked one, over a socket: the stub's own
        request count does not move."""
        before = len(self.stub.completions())
        payload = self.app([MarkerRail("BLOCKTHEPROMPT")]).post(
            "/v1/chat", json=prompt("BLOCKTHEPROMPT")).json()
        self.assertEqual(payload["decision"], "blocked_on_input")
        self.assertEqual(len(self.stub.completions()), before)

    def test_an_output_block_withholds_a_real_completion(self):
        response = self.app([MarkerRail("SENTINEL-4f19")]).post(
            "/v1/chat", json=prompt())
        self.assertEqual(response.json()["decision"], "blocked_on_output")
        self.assertNotIn(SECRET_ANSWER, response.text)

    def test_a_target_that_is_not_listening_is_target_error(self):
        """A genuine connection refusal, not a simulated one."""
        env = {"AFNI_TARGET_BASE_URL": f"http://127.0.0.1:{free_port()}/v1",
               "AFNI_TARGET_MODEL": MODEL}
        app = TestClient(create_app(warm=False, rails=[CleanRail()],
                                    attributions={}, env=env))
        payload = app.post("/v1/chat", json=prompt()).json()
        self.assertEqual(payload["decision"], "target_error")
        self.assertEqual(payload["target"]["error"]["kind"], "transport")
        self.assertIsNone(payload["completion"])

    def test_an_unreachable_target_does_not_stop_the_gateway_booting(self):
        """The startup probe against a dead endpoint must degrade, not raise -
        the same precedent as a keyless judge provider being skipped."""
        env = {"AFNI_TARGET_BASE_URL": f"http://127.0.0.1:{free_port()}/v1",
               "AFNI_TARGET_MODEL": MODEL, "AFNI_TARGET_PROBE_TIMEOUT": "0.5"}
        app = TestClient(create_app(warm=False, rails=[CleanRail()],
                                    attributions={}, env=env))
        health = app.get("/healthz").json()
        self.assertEqual(health["status"], "degraded")
        self.assertFalse(health["target"]["reachable"])
        self.assertEqual(app.get("/v1/rails").status_code, 200)

    def test_a_real_timeout_is_reported_as_a_timeout_and_yields_no_completion(self):
        slow = StubTargetServer(delay=1.0)
        try:
            env = {"AFNI_TARGET_BASE_URL": slow.base_url,
                   "AFNI_TARGET_MODEL": MODEL,
                   "AFNI_TARGET_TIMEOUT": "0.2"}
            app = TestClient(create_app(warm=False, rails=[CleanRail()],
                                        attributions={}, env=env))
            payload = app.post("/v1/chat", json=prompt()).json()
            self.assertEqual(payload["decision"], "target_error")
            self.assertEqual(payload["target"]["error"]["kind"], "timeout")
            self.assertIsNone(payload["completion"])
        finally:
            # The abandoned request leaves a socket that outlives the client
            # object, so close it explicitly rather than leaving a
            # ResourceWarning in the suite's output.
            app.app.state.gateway.target.close()
            slow.close()

    def test_the_streamed_frames_survive_a_real_round_trip(self):
        response = self.app([CleanRail()]).post("/v1/chat/stream", json=prompt())
        names = [name for name, _ in frames(response)]
        self.assertIn("target_start", names)
        self.assertIn("target_done", names)
        self.assertEqual(names[-2:], ["final", "done"])


# --------------------------------------------------------------------------- #
class TestPreferLocalReordersTheJudgeChain(unittest.TestCase):
    """`AFNI_JUDGE_PREFER_LOCAL`: use the local model for Stage-3 judging
    whenever it is up, and fall back to the paid keys when it is not.

    Chain order is not a performance setting. A judge call sends the FLAGGED
    CONTENT to whoever serves it, so which link is first decides whose network
    that content crosses - which is why the flag is opt-in and why what it did is
    reported rather than only logged.

    These use the real stub server, because the probe is the thing under test.
    """

    @classmethod
    def setUpClass(cls):
        cls.stub = StubTargetServer()

    @classmethod
    def tearDownClass(cls):
        cls.stub.close()

    def chain(self, **env):
        skipped = []
        return providers.from_env(env, skipped), skipped

    def test_the_order_is_static_when_the_flag_is_off(self):
        """Nothing may change for a deployment that did not ask for this - and
        no probe means no traffic, which the stub's request count proves."""
        before = len(self.stub.requests)
        chain, _ = self.chain(AFNI_JUDGE_PROVIDER="openai,gemini",
                              OPENAI_API_KEYS="k1", GOOGLE_API_KEYS="k2",
                              LOCAL_BASE_URL=self.stub.base_url)
        self.assertEqual(chain.links, ["openai[0]", "gemini[0]"])
        self.assertIsNone(chain.describe().get("prefer_local"))
        self.assertEqual(len(self.stub.requests), before)

    def test_a_reachable_local_endpoint_moves_to_the_front(self):
        chain, _ = self.chain(AFNI_JUDGE_PROVIDER="openai,gemini,local",
                              OPENAI_API_KEYS="k1", GOOGLE_API_KEYS="k2",
                              LOCAL_BASE_URL=self.stub.base_url,
                              LOCAL_MODEL=MODEL,
                              AFNI_JUDGE_PREFER_LOCAL="true")
        self.assertEqual(chain.links,
                         ["local[nokey]", "openai[0]", "gemini[0]"])
        preference = chain.describe()["prefer_local"]
        self.assertEqual(preference["action"], "moved to the front")
        self.assertTrue(preference["reachable"])

    def test_it_is_inserted_when_the_configured_chain_never_named_it(self):
        """The operator's `AFNI_JUDGE_PROVIDER` is their FALLBACK list once this
        flag is on. Only reordering an already-present name would make the flag
        do nothing for the configuration it exists to serve."""
        chain, _ = self.chain(AFNI_JUDGE_PROVIDER="openai,gemini",
                              OPENAI_API_KEYS="k1", GOOGLE_API_KEYS="k2",
                              LOCAL_BASE_URL=self.stub.base_url,
                              AFNI_JUDGE_PREFER_LOCAL="1")
        self.assertEqual(chain.links[0], "local[nokey]")
        self.assertEqual(chain.links[1:], ["openai[0]", "gemini[0]"])
        self.assertEqual(chain.describe()["prefer_local"]["action"],
                         "inserted at the front")

    def test_an_unreachable_local_endpoint_leaves_the_paid_chain_as_configured(self):
        """The fallback the user asked for: their OpenAI and Gemini keys, in
        their order, when the local box is down."""
        chain, _ = self.chain(
            AFNI_JUDGE_PROVIDER="openai,gemini",
            OPENAI_API_KEYS="k1", GOOGLE_API_KEYS="k2",
            LOCAL_BASE_URL=f"http://127.0.0.1:{free_port()}/v1",
            AFNI_JUDGE_PREFER_LOCAL="true",
            AFNI_JUDGE_PREFER_LOCAL_TIMEOUT="0.5")
        self.assertEqual(chain.links, ["openai[0]", "gemini[0]"])
        preference = chain.describe()["prefer_local"]
        self.assertFalse(preference["reachable"])
        self.assertEqual(preference["action"], "left the chain unchanged")

    def test_a_down_local_endpoint_never_stops_the_gateway_booting(self):
        """The rule this whole feature has to obey. A probe that can fail a boot
        would let a demo-only setting take Stage 1 and Stage 2 offline."""
        env = {"AFNI_JUDGE_PROVIDER": "openai",
               "OPENAI_API_KEYS": "k1",
               "LOCAL_BASE_URL": f"http://127.0.0.1:{free_port()}/v1",
               "AFNI_JUDGE_PREFER_LOCAL": "true",
               "AFNI_JUDGE_PREFER_LOCAL_TIMEOUT": "0.5"}
        app = TestClient(create_app(warm=False, rails=[CleanRail()],
                                    attributions={}, env=env))
        self.assertEqual(app.get("/healthz").status_code, 200)
        self.assertEqual(app.get("/healthz").json()["judge_provider"]["chain"],
                         ["openai[0]"])

    def test_it_inherits_the_target_endpoint_when_local_base_url_is_unset(self):
        """The user configures one machine, not two. When only the target is
        set, the local judge is that machine - reported, not silent."""
        chain, _ = self.chain(AFNI_JUDGE_PROVIDER="openai",
                              OPENAI_API_KEYS="k1",
                              AFNI_TARGET_BASE_URL=self.stub.base_url,
                              AFNI_TARGET_MODEL=MODEL,
                              AFNI_JUDGE_PREFER_LOCAL="true")
        self.assertEqual(chain.links[0], "local[nokey]")
        preference = chain.describe()["prefer_local"]
        self.assertTrue(preference["inherited_from_target"])
        self.assertEqual(preference["model"], MODEL)

    def test_the_local_judge_actually_points_at_the_probed_endpoint(self):
        """Reordering a name is worthless if the link behind it is misconfigured,
        so this asserts the adapter's own base URL and model."""
        chain, _ = self.chain(AFNI_JUDGE_PROVIDER="openai",
                              OPENAI_API_KEYS="k1",
                              AFNI_TARGET_BASE_URL=self.stub.base_url,
                              AFNI_TARGET_MODEL=MODEL,
                              AFNI_JUDGE_PREFER_LOCAL="true")
        models = {row["link"]: row["model"] for row in chain.describe()["models"]}
        self.assertEqual(models["local[nokey]"], MODEL)

    def test_the_flag_alone_stands_up_a_local_only_chain(self):
        """An operator who sets the flag has said "judge locally when local is
        up". With no paid chain configured that means local, not nothing."""
        chain, _ = self.chain(AFNI_JUDGE_PREFER_LOCAL="true",
                              LOCAL_BASE_URL=self.stub.base_url,
                              LOCAL_MODEL=MODEL)
        self.assertEqual(chain.links, ["local[nokey]"])

    def test_the_flag_with_nothing_to_probe_changes_nothing(self):
        chain, _ = self.chain(AFNI_JUDGE_PROVIDER="openai",
                              OPENAI_API_KEYS="k1",
                              AFNI_JUDGE_PREFER_LOCAL="true")
        self.assertEqual(chain.links, ["openai[0]"])
        self.assertEqual(chain.describe()["prefer_local"]["action"],
                         "no local endpoint configured")

    def test_the_reordering_and_its_reason_are_logged(self):
        """An operator who cannot see the order change cannot audit where the
        flagged content went."""
        logger = logging.getLogger("afni_rai.gateway.providers")
        previous = logger.level
        logger.setLevel(logging.INFO)
        try:
            with self.assertLogs("afni_rai.gateway.providers",
                                 level="INFO") as captured:
                self.chain(AFNI_JUDGE_PROVIDER="openai,gemini",
                           OPENAI_API_KEYS="k1", GOOGLE_API_KEYS="k2",
                           LOCAL_BASE_URL=self.stub.base_url,
                           AFNI_JUDGE_PREFER_LOCAL="true")
        finally:
            logger.setLevel(previous)
        blob = "\n".join(captured.output)
        self.assertIn("inserted at the front", blob)
        self.assertIn("FLAGGED CONTENT", blob)

    def test_the_probe_never_logs_a_credential(self):
        logger = logging.getLogger("afni_rai")
        previous = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            with self.assertLogs("afni_rai", level="DEBUG") as captured:
                self.chain(AFNI_JUDGE_PROVIDER="openai",
                           OPENAI_API_KEYS="k1",
                           LOCAL_BASE_URL=self.stub.base_url,
                           LOCAL_API_KEY=API_KEY,
                           AFNI_JUDGE_PREFER_LOCAL="true")
        finally:
            logger.setLevel(previous)
        for line in captured.output:
            self.assertNotIn(API_KEY, line)

    def test_the_probe_does_not_mutate_the_environment_it_was_handed(self):
        """`from_env` is handed `os.environ` in production. A chain-ordering
        decision that wrote LOCAL_BASE_URL back into the process environment
        would leak into every other reader of it."""
        env = {"AFNI_JUDGE_PROVIDER": "openai", "OPENAI_API_KEYS": "k1",
               "AFNI_TARGET_BASE_URL": self.stub.base_url,
               "AFNI_TARGET_MODEL": MODEL,
               "AFNI_JUDGE_PREFER_LOCAL": "true"}
        snapshot = dict(env)
        providers.from_env(env, [])
        self.assertEqual(env, snapshot)

    def test_probe_endpoint_reports_an_unconfigured_url_rather_than_raising(self):
        probe = probe_endpoint("")
        self.assertFalse(probe.configured)
        self.assertIsNone(probe.reachable)


# --------------------------------------------------------------------------- #
class TestTheAuditTrailRecordsBothHalves(unittest.TestCase):
    """One interaction, two verdicts, one step id - and no content in either.

    The audit store is the record of record for this platform. If the
    passthrough recorded only the half that blocked, an incident review could not
    reconstruct what was sent versus what came back.
    """

    def setUp(self):
        self.audit = VerdictStore(":memory:")
        self.client, self.counting = target()
        self.app = chat_app([CleanRail()], self.client, verdict_store=self.audit)

    def test_an_allowed_interaction_writes_two_rows(self):
        self.app.post("/v1/chat", json=prompt())
        self.assertEqual(self.audit.count("verdicts"), 2)

    def test_an_input_block_writes_one_row_because_there_was_one_decision(self):
        audit = VerdictStore(":memory:")
        client, _ = target()
        app = chat_app([MarkerRail("BLOCKTHEPROMPT")], client,
                       verdict_store=audit)
        app.post("/v1/chat", json=prompt("BLOCKTHEPROMPT"))
        self.assertEqual(audit.count("verdicts"), 1)

    def test_neither_the_prompt_nor_the_completion_is_stored(self):
        """`FORBIDDEN_FINDING_FIELDS` and the absent `subject` column are the
        store's own guarantee; this asserts the passthrough did not find a way
        around it."""
        self.app.post("/v1/chat", json=prompt("a very distinctive prompt 8812"))
        self.assertEqual(
            scan_for_leak(self.audit,
                          [SECRET_ANSWER, "a very distinctive prompt 8812"]),
            [])

    def test_a_target_error_still_records_the_input_verdict(self):
        audit = VerdictStore(":memory:")
        client, _ = target(answering(status=500))
        app = chat_app([CleanRail()], client, verdict_store=audit)
        app.post("/v1/chat", json=prompt())
        self.assertEqual(audit.count("verdicts"), 1)


# --------------------------------------------------------------------------- #
class TestTheDocumentedContract(unittest.TestCase):
    """The things a reader of the docs or the OpenAPI page is promised."""

    def setUp(self):
        self.client, _ = target()
        self.app = chat_app([CleanRail()], self.client)

    def test_both_chat_routes_are_in_the_openapi_document(self):
        paths = self.app.get("/openapi.json").json()["paths"]
        self.assertIn("/v1/chat", paths)
        self.assertIn("/v1/chat/stream", paths)

    def test_the_four_decisions_are_the_documented_ones(self):
        """Exhaustive: every path through `Passthrough.run` ends on one of these,
        and `NOTES` has a sentence for each, so a missing one is a KeyError at
        the moment of the decision rather than a silent blank."""
        from afni_rai.gateway import passthrough as module
        self.assertEqual(
            sorted(module.NOTES),
            sorted([module.ALLOWED, module.BLOCKED_ON_INPUT,
                    module.BLOCKED_ON_OUTPUT, module.TARGET_ERROR]))

    def test_the_response_shape_is_the_same_on_every_decision(self):
        """A console renders one shape. Branching on the decision to find out
        which keys exist is how a UI ends up with four renderers."""
        blocking = MarkerRail("BLOCKTHEPROMPT")
        cases = {
            "allowed": (self.app, prompt()),
            "blocked_on_input": (chat_app([blocking], target()[0]),
                                 prompt("BLOCKTHEPROMPT")),
            "blocked_on_output": (chat_app([MarkerRail("SENTINEL-4f19")],
                                           target()[0]), prompt()),
            "target_error": (chat_app([CleanRail()],
                                      target(answering(status=500))[0]),
                             prompt()),
        }
        shapes = {}
        for decision, (app, body) in cases.items():
            payload = app.post("/v1/chat", json=body).json()
            self.assertEqual(payload["decision"], decision)
            shapes[decision] = set(payload)
        self.assertEqual(len(set(map(frozenset, shapes.values()))), 1,
                         f"the response shape varies by decision: {shapes}")

    def test_the_docs_describe_the_endpoint(self):
        """`docs/architecture.md` section 1 draws this topology, so the
        passthrough has to be findable from it - a topology diagram with no
        endpoint next to it is where the "does it actually sit in front of the
        model" question comes from."""
        # Repo root, not rai_platform/: all documentation moved into one
        # top-level docs/ folder on 2026-09-03.
        path = os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                            "docs", "architecture.md")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("/v1/chat", text)
        self.assertIn("AFNI_TARGET_BASE_URL", text)

    def test_env_example_documents_every_variable_the_target_reads(self):
        """A setting that only exists in code is a setting nobody sets."""
        path = os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                            ".env.example")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for name in ("AFNI_TARGET_BASE_URL", "AFNI_TARGET_MODEL",
                     "AFNI_TARGET_API_KEY", "AFNI_TARGET_TIMEOUT",
                     "AFNI_TARGET_MAX_TOKENS", "AFNI_TARGET_PROBE_TIMEOUT",
                     "AFNI_JUDGE_PREFER_LOCAL"):
            with self.subTest(name=name):
                self.assertRegex(text, re.compile(rf"^{re.escape(name)}=",
                                                  re.M))

    def test_nothing_in_the_target_adapter_hardcodes_the_users_endpoint(self):
        """The private address in the brief is an example, not a default. A
        hardcoded one would make every other deployment reach for a machine it
        does not have.

        Docstrings are excluded deliberately - naming the user's model in prose
        is documentation, and the thing that would be a bug is a string constant
        the code can actually reach for. So this walks the AST and inspects only
        the non-docstring literals.
        """
        path = os.path.join(os.path.dirname(_HERE), "afni_rai", "target",
                            "client.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        docstrings = {ast.get_docstring(node, clean=False)
                      for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.ClassDef,
                                           ast.FunctionDef))} - {None}
        self.assertTrue(docstrings, "the AST walk found nothing to exclude, so "
                                    "this test is not checking what it claims")
        literals = [node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value not in docstrings]
        blob = "\n".join(literals)
        for literal in ("10.10.10.151", "8506", "test-key-123", MODEL):
            self.assertNotIn(literal, blob)

    def test_the_passthrough_reads_no_configuration_of_its_own(self):
        """One trust boundary, not two.

        `AFNI_REVEAL_SUBJECT`, the thresholds and the fail_mode are the
        Gateway's, and the passthrough borrows them - `reveal_subject` through
        the same `_stage_frame` call the guard stream uses. A module that read
        its own environment here could disagree with the gateway about whether
        matched values may be echoed, which is the one disagreement that must be
        impossible.
        """
        source_path = os.path.join(os.path.dirname(_HERE), "afni_rai", "gateway",
                                   "passthrough.py")
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        for reader in ("os.environ", "os.getenv", "getenv("):
            self.assertNotIn(reader, code)
        self.assertIn("self.gateway.reveal_subject", code)


# --------------------------------------------------------------------------- #
class TestPassthroughInternals(unittest.TestCase):
    """The two payload shapes, because the rails' `path` strings depend on them."""

    def setUp(self):
        client, _ = target()
        self.app = chat_app([CleanRail()], client)
        self.passthrough = Passthrough(self.app.app.state.gateway)

    def test_the_prompt_is_judged_in_the_providers_own_request_shape(self):
        payload = self.passthrough.request_payload(
            [{"role": "user", "content": "hi"}])
        self.assertEqual(payload, {"messages": [{"role": "user", "content": "hi"}]})

    def test_the_completion_is_judged_in_the_providers_own_response_shape(self):
        """`payload.choices[0].message.content` is the path the output-side rails
        and the docs already speak, so a passthrough finding reads the same as a
        `/v1/guard` one."""
        payload = self.passthrough.response_payload("an answer")
        self.assertEqual(payload["choices"][0]["message"]["content"], "an answer")

    def test_a_missing_verdict_reads_as_blocked(self):
        """Fail-closed at the seam too: an unreadable verdict is not an allow."""
        from afni_rai.gateway.passthrough import _blocked
        self.assertTrue(_blocked({}))
        self.assertTrue(_blocked({"verdict": {}}))
        self.assertFalse(_blocked({"verdict": {"decision": "allow"}}))

    def test_a_minted_step_id_is_unique_per_interaction(self):
        class Body:
            step_id = None
        ids = {self.passthrough.step_id(Body()) for _ in range(50)}
        self.assertEqual(len(ids), 50)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
