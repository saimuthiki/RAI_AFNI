# -*- coding: utf-8 -*-
"""
`AFNI_REVEAL_BLOCKED_COMPLETION`: the demonstration switch on the passthrough.

The default contract of `/v1/chat` is that a completion the output guardrail
blocked appears nowhere - not in the response, not in a frame, not in a log
line, not in the audit row. `test_passthrough.py` proves that. This file is
about the ONE exception the product owner asked for: "just for the demo, I want
to see the output of the target model too, and what kind of response is being
blocked by output guardrails".

The exception is built the way `AFNI_REVEAL_SUBJECT` is built - a server-side
flag, default off, no request field - and these tests hold it to exactly that:

  * off by default, both new keys null on all four decisions, `run()` and the
    streamed `final` frame alike
  * on, the blocked text appears under `withheld_completion` with the fixed note
    next to it, and ONLY on `blocked_on_output` - `completion` stays null, so a
    console can never mistake a withheld answer for a delivered one
  * on, the text still reaches no log line and no audit row
  * on, `target_done` and the `stage` frames still carry no text - the text is
    in `final` and nowhere else in the stream
  * reported on `/healthz`; a startup WARNING while it is on
  * not a request field, header or query parameter

Run: python3 rai_platform/run_tests.py
"""
import json
import logging
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai.gateway import passthrough as passthrough_module  # noqa: E402
from afni_rai.gateway.app import (  # noqa: E402
    ENV_REVEAL_COMPLETION, Gateway, create_app,
)
from afni_rai.gateway.models import ChatResponse, HealthResponse  # noqa: E402
from afni_rai.tenets.accountability.audit import VerdictStore, scan_for_leak  # noqa: E402

# The fixtures are the passthrough suite's own - the stub target, the marker
# rail, the SSE parser - imported as a module so pytest does not collect that
# file's test classes a second time under this module's name.
from tests import test_passthrough as pt  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"fastapi is not installed: {exc}") from exc

FLAG_ON = {ENV_REVEAL_COMPLETION: "1"}
NOTE = ("Shown because AFNI_REVEAL_BLOCKED_COMPLETION is on for this gateway. "
        "This text was blocked; your customer did not receive it. Demonstration "
        "setting - not for production.")
DECISIONS = ("allowed", "blocked_on_input", "blocked_on_output", "target_error")


def setUpModule():
    """Same reason as test_passthrough: the fail-closed paths log tracebacks on
    purpose. Tests that assert on log content re-enable capture locally."""
    logging.getLogger("afni_rai").setLevel(logging.CRITICAL)


def apps_for_every_decision(env=None, **kwargs):
    """One `(client, prompt)` per decision, with the given server environment.

    The same four set-ups `test_passthrough.TestTheDocumentedContract` uses:
    the decision is driven by which text the marker rail sees and by whether
    the stub target answers.
    """
    return {
        "allowed": (pt.chat_app([pt.CleanRail()], pt.target()[0], env=env, **kwargs),
                    pt.prompt()),
        "blocked_on_input": (pt.chat_app([pt.MarkerRail("BLOCKTHEPROMPT")],
                                         pt.target()[0], env=env, **kwargs),
                             pt.prompt("BLOCKTHEPROMPT")),
        "blocked_on_output": (pt.chat_app([pt.MarkerRail("SENTINEL-4f19")],
                                          pt.target()[0], env=env, **kwargs),
                              pt.prompt()),
        "target_error": (pt.chat_app([pt.CleanRail()],
                                     pt.target(pt.answering(status=500))[0],
                                     env=env, **kwargs),
                         pt.prompt()),
    }


def final_frame(app, body):
    return dict(pt.frames(app.post("/v1/chat/stream", json=body)))["final"]


# --------------------------------------------------------------------------- #
class TestTheNoteIsFixed(unittest.TestCase):
    """The console and the docs match this sentence verbatim, so it is pinned."""

    def test_the_note_text(self):
        self.assertEqual(passthrough_module.WITHHELD_COMPLETION_NOTE, NOTE)


# --------------------------------------------------------------------------- #
class TestOffByDefaultTheKeysArePresentAndNull(unittest.TestCase):
    """The default is the invariant: two keys, always present, always null."""

    def test_run_has_both_keys_null_on_every_decision(self):
        for decision, (app, body) in apps_for_every_decision().items():
            with self.subTest(decision=decision):
                payload = app.post("/v1/chat", json=body).json()
                self.assertEqual(payload["decision"], decision)
                self.assertIn("withheld_completion", payload)
                self.assertIn("withheld_completion_note", payload)
                self.assertIsNone(payload["withheld_completion"])
                self.assertIsNone(payload["withheld_completion_note"])

    def test_the_streamed_final_frame_has_both_keys_null_on_every_decision(self):
        for decision, (app, body) in apps_for_every_decision().items():
            with self.subTest(decision=decision):
                final = final_frame(app, body)
                self.assertEqual(final["decision"], decision)
                self.assertIn("withheld_completion", final)
                self.assertIsNone(final["withheld_completion"])
                self.assertIsNone(final["withheld_completion_note"])

    def test_a_blocked_completion_is_still_absent_from_the_whole_body(self):
        """The existing promise, re-asserted here so a regression in the gating
        shows up in the file that introduced the gate."""
        app, body = apps_for_every_decision()["blocked_on_output"]
        self.assertNotIn(pt.SECRET_ANSWER, app.post("/v1/chat", json=body).text)
        self.assertNotIn(pt.SECRET_ANSWER,
                         app.post("/v1/chat/stream", json=body).text)

    def test_an_explicitly_false_value_is_off(self):
        for value in ("false", "0", "no", "off", ""):
            with self.subTest(value=value):
                app, body = apps_for_every_decision(
                    env={ENV_REVEAL_COMPLETION: value})["blocked_on_output"]
                payload = app.post("/v1/chat", json=body).json()
                self.assertIsNone(payload["withheld_completion"])
                self.assertFalse(app.get("/healthz").json()["reveal_blocked_completion"])


# --------------------------------------------------------------------------- #
class TestOnTheBlockedTextIsShownLabelledAndOnlyThere(unittest.TestCase):

    def setUp(self):
        self.cases = apps_for_every_decision(env=FLAG_ON)

    def test_run_populates_both_keys_on_blocked_on_output_only(self):
        for decision, (app, body) in self.cases.items():
            with self.subTest(decision=decision):
                payload = app.post("/v1/chat", json=body).json()
                self.assertEqual(payload["decision"], decision)
                if decision == "blocked_on_output":
                    self.assertEqual(payload["withheld_completion"], pt.SECRET_ANSWER)
                    self.assertEqual(payload["withheld_completion_note"], NOTE)
                else:
                    self.assertIsNone(payload["withheld_completion"])
                    self.assertIsNone(payload["withheld_completion_note"])

    def test_the_streamed_final_frame_matches_run(self):
        for decision, (app, body) in self.cases.items():
            with self.subTest(decision=decision):
                final = final_frame(app, body)
                self.assertEqual(final["decision"], decision)
                if decision == "blocked_on_output":
                    self.assertEqual(final["withheld_completion"], pt.SECRET_ANSWER)
                    self.assertEqual(final["withheld_completion_note"], NOTE)
                else:
                    self.assertIsNone(final["withheld_completion"])
                    self.assertIsNone(final["withheld_completion_note"])

    def test_completion_stays_null_when_the_text_is_withheld(self):
        """Mutually exclusive by construction. A console that renders
        `completion` as the delivered answer must never be handed a withheld
        one under that key, flag or no flag."""
        app, body = self.cases["blocked_on_output"]
        payload = app.post("/v1/chat", json=body).json()
        self.assertIsNone(payload["completion"])
        self.assertEqual(payload["refusal"], passthrough_module.REFUSAL_OUTPUT)
        self.assertEqual(payload["output_verdict"]["decision"], "block")

    def test_an_allowed_answer_is_under_completion_not_withheld_completion(self):
        app, body = self.cases["allowed"]
        payload = app.post("/v1/chat", json=body).json()
        self.assertEqual(payload["completion"], pt.SECRET_ANSWER)
        self.assertIsNone(payload["withheld_completion"])

    def test_in_the_stream_the_text_is_in_final_and_in_no_other_frame(self):
        """`target_done` and the `stage` frames exist before or during the
        judgement; the flag does not move the text forward in the stream."""
        app, body = self.cases["blocked_on_output"]
        for name, frame in pt.frames(app.post("/v1/chat/stream", json=body)):
            with self.subTest(frame=name):
                if name == "final":
                    self.assertEqual(frame["withheld_completion"], pt.SECRET_ANSWER)
                else:
                    self.assertNotIn(pt.SECRET_ANSWER, json.dumps(frame))

    def test_the_response_still_validates_against_the_documented_model(self):
        """`ChatResponse` is `extra=forbid`: a key the model does not declare
        would make the OpenAPI page lie about the shape."""
        app, body = self.cases["blocked_on_output"]
        model = ChatResponse.model_validate(app.post("/v1/chat", json=body).json())
        self.assertEqual(model.withheld_completion, pt.SECRET_ANSWER)
        self.assertEqual(model.withheld_completion_note, NOTE)

    def test_the_constructor_override_works_like_reveal_subject(self):
        """A test or an embedding process can set it without touching the
        environment, exactly as `reveal_subject` can - and the override wins
        over the environment in both directions."""
        app, body = apps_for_every_decision(
            env={}, reveal_blocked_completion=True)["blocked_on_output"]
        self.assertEqual(app.post("/v1/chat", json=body).json()["withheld_completion"],
                         pt.SECRET_ANSWER)
        app, body = apps_for_every_decision(
            env=FLAG_ON, reveal_blocked_completion=False)["blocked_on_output"]
        self.assertIsNone(app.post("/v1/chat", json=body).json()["withheld_completion"])

    def test_every_truthy_spelling_turns_it_on(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                gateway = Gateway(rails=[pt.CleanRail()], attributions={},
                                  env={ENV_REVEAL_COMPLETION: value})
                self.assertTrue(gateway.reveal_blocked_completion)


# --------------------------------------------------------------------------- #
class TestOnTheTextStillReachesNoLogAndNoAuditRow(unittest.TestCase):
    """The flag widens exactly one surface - the response. The two surfaces that
    outlive the request keep the default contract."""

    def setUp(self):
        self.audit = VerdictStore(":memory:")
        self.client, _ = pt.target()
        self.app = pt.chat_app([pt.MarkerRail("SENTINEL-4f19")], self.client,
                               env=FLAG_ON, verdict_store=self.audit)

    def _captured(self, logger_name):
        logger = logging.getLogger("afni_rai")
        previous = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            with self.assertLogs(logger_name, level="DEBUG") as captured:
                payload = self.app.post("/v1/chat", json=pt.prompt()).json()
                self.app.post("/v1/chat/stream", json=pt.prompt())
        finally:
            logger.setLevel(previous)
        # The flag did its job on the response...
        self.assertEqual(payload["withheld_completion"], pt.SECRET_ANSWER)
        return captured.output

    def test_the_passthrough_logger_never_carries_the_text(self):
        lines = self._captured("afni_rai.gateway.passthrough")
        self.assertTrue(lines)
        for line in lines:
            self.assertNotIn(pt.SECRET_ANSWER, line)
        # ...and the withhold is still logged as a length, not a value.
        self.assertTrue(any("blocked on OUTPUT" in line for line in lines))

    def test_nothing_in_the_whole_tree_logs_the_text(self):
        for line in self._captured("afni_rai"):
            self.assertNotIn(pt.SECRET_ANSWER, line)

    def test_the_audit_database_holds_no_completion_text(self):
        payload = self.app.post("/v1/chat", json=pt.prompt()).json()
        self.assertEqual(payload["withheld_completion"], pt.SECRET_ANSWER)
        self.assertEqual(scan_for_leak(self.audit, [pt.SECRET_ANSWER, NOTE]), [])

    def test_the_audit_database_still_recorded_both_verdicts(self):
        self.app.post("/v1/chat", json=pt.prompt())
        self.assertEqual(self.audit.count("verdicts"), 2)


# --------------------------------------------------------------------------- #
class TestHealthzAndStartupSayWhenItIsOn(unittest.TestCase):

    def test_healthz_reports_off_by_default(self):
        app = pt.chat_app([pt.CleanRail()], pt.target()[0])
        payload = app.get("/healthz").json()
        self.assertIn("reveal_blocked_completion", payload)
        self.assertFalse(payload["reveal_blocked_completion"])
        HealthResponse.model_validate(payload)

    def test_healthz_reports_on_next_to_reveal_subject(self):
        app = pt.chat_app([pt.CleanRail()], pt.target()[0], env=FLAG_ON)
        payload = app.get("/healthz").json()
        self.assertTrue(payload["reveal_blocked_completion"])
        self.assertFalse(payload["reveal_subject"])
        HealthResponse.model_validate(payload)

    def test_healthz_reports_it_without_a_target_too(self):
        """The flag is a gateway property, not a target one."""
        app = TestClient(create_app(warm=False, rails=[pt.CleanRail()],
                                    attributions={}, env=FLAG_ON))
        self.assertTrue(app.get("/healthz").json()["reveal_blocked_completion"])

    def test_a_warning_is_logged_at_startup_when_on(self):
        logger = logging.getLogger("afni_rai")
        previous = logger.level
        logger.setLevel(logging.WARNING)
        try:
            with self.assertLogs("afni_rai.gateway", level="WARNING") as captured:
                Gateway(rails=[pt.CleanRail()], attributions={}, env=FLAG_ON)
        finally:
            logger.setLevel(previous)
        line = next(l for l in captured.output if ENV_REVEAL_COMPLETION in l)
        self.assertIn("withheld_completion", line)
        self.assertIn("/v1/chat", line)
        self.assertIn("demonstration", line.lower())
        self.assertTrue(line.startswith("WARNING:"))

    def test_no_such_warning_when_off(self):
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger = logging.getLogger("afni_rai.gateway")
        previous = logger.level
        logger.setLevel(logging.WARNING)
        logger.addHandler(handler)
        try:
            Gateway(rails=[pt.CleanRail()], attributions={}, env={})
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)
        self.assertFalse([r for r in records
                          if ENV_REVEAL_COMPLETION in r.getMessage()])


# --------------------------------------------------------------------------- #
class TestItIsNotARequestField(unittest.TestCase):
    """The trust boundary. Same test shape as `AFNI_REVEAL_SUBJECT`'s."""

    def setUp(self):
        self.app, self.body = apps_for_every_decision()["blocked_on_output"]

    def test_a_request_field_is_a_422_not_a_silently_ignored_parameter(self):
        for attempt in ({"reveal_blocked_completion": True},
                        {"withheld_completion": True},
                        {"reveal": True},
                        {ENV_REVEAL_COMPLETION: "1"}):
            with self.subTest(attempt=attempt):
                response = self.app.post("/v1/chat", json=pt.prompt(**attempt))
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(pt.SECRET_ANSWER, response.text)
                stream = self.app.post("/v1/chat/stream", json=pt.prompt(**attempt))
                self.assertEqual(stream.status_code, 422)

    def test_no_query_parameter_or_header_turns_it_on(self):
        for kwargs in ({"params": {"reveal_blocked_completion": "true"}},
                       {"params": {ENV_REVEAL_COMPLETION: "1"}},
                       {"headers": {"x-afni-reveal-blocked-completion": "1"}}):
            with self.subTest(kwargs=kwargs):
                response = self.app.post("/v1/chat", json=self.body, **kwargs)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["withheld_completion"])
                self.assertNotIn(pt.SECRET_ANSWER, response.text)

    def test_the_openapi_page_names_the_exception(self):
        """The response description used to promise "under any key"; it now
        names the one server-side flag that changes that, so a reader of the
        docs is not surprised by the key when they see it."""
        spec = self.app.get("/openapi.json").json()
        description = spec["paths"]["/v1/chat"]["post"]["responses"]["200"]["description"]
        self.assertIn(ENV_REVEAL_COMPLETION, description)
        self.assertIn("withheld_completion", description)
        schema = spec["components"]["schemas"]["ChatResponse"]["properties"]
        self.assertIn("withheld_completion", schema)
        self.assertIn("withheld_completion_note", schema)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
