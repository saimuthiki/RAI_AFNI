# -*- coding: utf-8 -*-
"""Does the GUARDED model get a frame, and does the guardrail not see it?

The target is an AI system, not a rail, and until now it was called with
whatever messages arrived and nothing else - so a bare `/v1/chat` asked an
un-framed base model to answer. `AFNI_TARGET_SYSTEM_PROMPT` fixes that, and the
two rules that make it safe are both tested here:

  IT GOES FIRST, AND DOES NOT REPLACE THE CALLER'S. The frame the guarded model
  answers under is a deployment decision. If a caller's own system message could
  displace it, any caller could strip it by sending one.

  IT IS NOT IN THE GUARD EVENT. The rails judge what the CALLER wrote. Adding
  our own boilerplate to the event would score text the client never sent and
  put our prompt in the audit record as if a user had typed it.

And one thing it deliberately is NOT: a safety policy. Refusals produced by the
target's own system prompt are invisible to the cascade - no finding, no
attribution, no audit row - so a demo whose blocks came from here would be
measuring the target's training instead of the rails.
"""
from __future__ import annotations

import json
import unittest

from afni_rai.target import client as target


class Recorder:
    """An httpx transport that records the body and answers 200."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def handle_request(self, request):  # noqa: ANN001 - httpx transport protocol
        import httpx
        self.bodies.append(json.loads(request.content or b"{}"))
        return httpx.Response(
            200, json={"model": "m", "choices": [
                {"message": {"role": "assistant", "content": "an answer"}}]},
            request=request)


def call(messages, **env):
    recorder = Recorder()
    import httpx
    config = target.config_from_env({
        target.ENV_BASE_URL: "http://endpoint.invalid/v1",
        target.ENV_MODEL: "qwen3-vl-8b-instruct", **env})
    client = target.TargetClient(
        config, transport=httpx.MockTransport(recorder.handle_request))
    client.complete(messages)
    return recorder.bodies[0], config


class TheDefaultFrame(unittest.TestCase):

    def test_a_system_prompt_is_sent_even_when_the_caller_sends_none(self):
        body, _ = call([{"role": "user", "content": "hello"}])
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][0]["content"],
                         target.DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(body["messages"][1],
                         {"role": "user", "content": "hello"})

    def test_the_default_is_a_plain_assistant_frame_and_not_a_policy(self):
        """A safety rule here would be a second, unauditable guardrail in front
        of the model - one whose refusals produce no finding and no audit row."""
        text = target.DEFAULT_SYSTEM_PROMPT.lower()
        self.assertIn("helpful", text)
        for policy_word in ("refuse", "must not", "never discuss", "guardrail",
                            "policy", "block"):
            with self.subTest(word=policy_word):
                self.assertNotIn(policy_word, text)

    def test_a_blank_environment_value_means_the_default(self):
        """Blank means the shipped default everywhere else in this block, and a
        variable whose empty value meant something different would be a trap."""
        body, _ = call([{"role": "user", "content": "hi"}],
                       **{target.ENV_SYSTEM_PROMPT: "   "})
        self.assertEqual(body["messages"][0]["content"],
                         target.DEFAULT_SYSTEM_PROMPT)


class AnOperatorsOwnFrame(unittest.TestCase):

    def test_the_configured_value_is_used_verbatim(self):
        body, config = call([{"role": "user", "content": "hi"}],
                            **{target.ENV_SYSTEM_PROMPT:
                               "You are Corptax support. Answer in one line."})
        self.assertEqual(body["messages"][0]["content"],
                         "You are Corptax support. Answer in one line.")
        self.assertEqual(config.system_prompt,
                         "You are Corptax support. Answer in one line.")

    def test_it_is_reported_by_describe(self):
        """Not a credential, and an operator has to be able to read the frame
        their model is answering under - a hidden system prompt is a hidden
        behaviour change."""
        _, config = call([{"role": "user", "content": "hi"}],
                         **{target.ENV_SYSTEM_PROMPT: "be terse"})
        self.assertEqual(config.describe()["system_prompt"], "be terse")

    def test_describe_still_withholds_the_credential(self):
        _, config = call([{"role": "user", "content": "hi"}],
                         **{target.ENV_API_KEY: "test-key-123"})
        blob = json.dumps(config.describe())
        self.assertNotIn("test-key-123", blob)
        self.assertTrue(config.describe()["api_key_configured"])


class ACallerSuppliedSystemMessage(unittest.TestCase):

    def test_ours_goes_first_and_theirs_is_kept(self):
        """FIRST, not INSTEAD OF. Dropping theirs would silently discard an
        instruction visible in their own request; letting theirs displace ours
        would let any caller strip the deployment's frame."""
        body, _ = call([{"role": "system", "content": "Reply in French."},
                        {"role": "user", "content": "hello"}])
        self.assertEqual([m["role"] for m in body["messages"]],
                         ["system", "system", "user"])
        self.assertEqual(body["messages"][0]["content"],
                         target.DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(body["messages"][1]["content"], "Reply in French.")

    def test_the_callers_messages_are_not_mutated(self):
        """`complete` is handed the same list the passthrough judged. Mutating
        it would change what the audit record says was sent."""
        messages = [{"role": "user", "content": "hello"}]
        call(messages)
        self.assertEqual(messages, [{"role": "user", "content": "hello"}])


class TheGuardEventDoesNotCarryIt(unittest.TestCase):
    """The whole reason the frame is applied in `complete` and not in
    `passthrough.run`."""

    def test_the_input_verdict_judges_only_what_the_caller_sent(self):
        import httpx
        from afni_rai.gateway.app import create_app
        from fastapi.testclient import TestClient

        recorder = Recorder()
        config = target.config_from_env({
            target.ENV_BASE_URL: "http://endpoint.invalid/v1",
            target.ENV_MODEL: "m",
            target.ENV_SYSTEM_PROMPT: "SENTINEL-FRAME-DO-NOT-JUDGE-ME"})
        app = create_app(
            target=target.TargetClient(
                config,
                transport=httpx.MockTransport(recorder.handle_request)))
        body = TestClient(app).post(
            "/v1/chat",
            json={"messages": [{"role": "user", "content": "what is a rail?"}]}
        ).json()
        # It reached the model... (the startup probe is a GET with no body, so
        # the generation is found by shape rather than by position)
        sent = [b for b in recorder.bodies if "messages" in b]
        self.assertTrue(sent, f"the target was never called: {body}")
        self.assertEqual(sent[0]["messages"][0]["content"],
                         "SENTINEL-FRAME-DO-NOT-JUDGE-ME")
        # ...and appears nowhere in either verdict or the audit-facing payload.
        self.assertNotIn("SENTINEL-FRAME-DO-NOT-JUDGE-ME", json.dumps(body))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
