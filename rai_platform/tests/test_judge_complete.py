# -*- coding: utf-8 -*-
"""Can a judge answer with a STRUCTURE, not only one number?

The two narrow judge rails take `Callable[[str], float]` - one question, one
float. The omnibus moderation rail, ported from the Infosys Responsible AI
Toolkit's moderation layer, asks one question and needs a JSON object back with
a score per check. That needs the model's reply as TEXT, unparsed, with the
caller owning both the parsing and the refusal.

`complete()` is that. It must behave exactly like `score()` in everything except
what it returns: same credential header, same framing, same non-retryable
statuses, same fall-through across the chain. The chain enforces that by
construction - `score` and `complete` are one `_walk` with a different call.

ALSO FIXED HERE, found while adding it: the Gemini adapter appended
SCORE_INSTRUCTION to the prompt itself, from before the instruction moved into
`judge_system_prompt`. Gemini was receiving the four-point scale twice, and a
JSON-returning call would have had a bare-number demand stapled onto it. Both
adapters now send byte-identical prompt text.
"""
from __future__ import annotations

import json
import unittest

import httpx

from afni_rai.gateway import providers as P


def openai_transport(reply: str, seen: list[dict]):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append({"headers": dict(request.headers),
                     "body": json.loads(request.content)})
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": reply}}]})
    return httpx.MockTransport(handle)


def gemini_transport(reply: str, seen: list[dict]):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": reply}]}}]})
    return httpx.MockTransport(handle)


REPLY = '{"explanation": "clean", "score": 3}'


class OpenAICompatible(unittest.TestCase):

    def judge(self, reply=REPLY, key="k1"):
        seen: list[dict] = []
        j = P.OpenAICompatibleJudge(model="m", base_url="http://x/v1",
                                    api_key=key,
                                    transport=openai_transport(reply, seen))
        return j, seen

    def test_complete_returns_the_text_unparsed(self):
        j, _ = self.judge()
        self.assertEqual(j.complete("P", "T", max_tokens=400), REPLY)

    def test_max_tokens_is_the_callers_not_eight(self):
        """`score` caps at 8 because a bare float needs no more. A JSON object
        with a score per check does, and a cap of 8 would truncate it into
        something that never parses - which fails closed on every request.

        Two judges, because the mock returns one fixed reply: the JSON one
        would be refused by `score`'s parser (correctly), so the score half
        gets a mock that answers with a number."""
        j, seen = self.judge()
        j.complete("P", "T", max_tokens=400)
        self.assertEqual(seen[0]["body"]["max_tokens"], 400)
        k, seen_k = self.judge(reply="0.2")
        k.score("P", "T")
        self.assertEqual(seen_k[0]["body"]["max_tokens"], 8)

    def test_same_framing_and_credential_as_score(self):
        j, seen = self.judge()
        j.complete("P", "T", max_tokens=100)
        k, seen_k = self.judge(reply="0.5")
        k.score("P", "T")
        for call in (seen[0], seen_k[0]):
            self.assertEqual(call["headers"]["authorization"], "Bearer k1")
            self.assertEqual(call["body"]["messages"],
                             [{"role": "system", "content": "P"},
                              {"role": "user", "content": "T"}])
            self.assertEqual(call["body"]["temperature"], 0)

    def test_no_choices_is_unavailable_not_empty_string(self):
        seen: list[dict] = []
        def handle(request):
            return httpx.Response(200, json={"choices": []})
        j = P.OpenAICompatibleJudge(model="m", base_url="http://x/v1",
                                    transport=httpx.MockTransport(handle))
        with self.assertRaises(P.JudgeUnavailable):
            j.complete("P", "T", max_tokens=10)


class Gemini(unittest.TestCase):

    def judge(self, reply=REPLY):
        seen: list[dict] = []
        j = P.GeminiJudge(api_key="AIza" + "K" * 35, model="g",
                          base_url="http://g/v1beta",
                          transport=gemini_transport(reply, seen))
        return j, seen

    def test_complete_returns_the_text_unparsed(self):
        j, _ = self.judge()
        self.assertEqual(j.complete("P", "T", max_tokens=400), REPLY)

    def test_the_prompt_is_sent_as_given_not_with_the_scale_appended(self):
        """THE LATENT BUG. The four-point scale lives in `judge_system_prompt`
        now; this adapter still appended it, so Gemini saw it twice - and a
        JSON call would have carried a bare-number demand."""
        j, seen = self.judge()
        j.complete("P", "T", max_tokens=100)
        sent = seen[0]["body"]["system_instruction"]["parts"][0]["text"]
        self.assertEqual(sent, "P")
        self.assertNotIn("single floating point number", sent)

    def test_score_and_complete_send_identical_prompt_text(self):
        j, seen = self.judge()
        j.complete("P", "T", max_tokens=100)
        k, seen_k = self.judge(reply="0.5")
        k.score("P", "T")
        a = seen[0]["body"]["system_instruction"]["parts"][0]["text"]
        b = seen_k[0]["body"]["system_instruction"]["parts"][0]["text"]
        self.assertEqual(a, b)

    def test_max_output_tokens_follows_the_caller(self):
        j, seen = self.judge()
        j.complete("P", "T", max_tokens=400)
        self.assertEqual(seen[0]["body"]["generationConfig"]["maxOutputTokens"], 400)


class TheTwoAdaptersAgree(unittest.TestCase):
    """The OpenAI-compatible adapter never appended the scale; Gemini did. After
    the fix both send the same bytes, which is the property a chain that falls
    through between them depends on."""

    def test_identical_system_text_across_adapters(self):
        seen_o: list[dict] = []
        seen_g: list[dict] = []
        P.OpenAICompatibleJudge(model="m", base_url="http://x/v1",
                                transport=openai_transport(REPLY, seen_o)
                                ).complete("PROMPT", "T", max_tokens=50)
        P.GeminiJudge(api_key="AIza" + "K" * 35, base_url="http://g/v1beta",
                      transport=gemini_transport(REPLY, seen_g)
                      ).complete("PROMPT", "T", max_tokens=50)
        self.assertEqual(seen_o[0]["body"]["messages"][0]["content"],
                         seen_g[0]["body"]["system_instruction"]["parts"][0]["text"])


class TheChainFallsThroughTheSameWay(unittest.TestCase):

    class Refusing:
        name = "refusing"
        def score(self, p, t): raise P.JudgeLinkFailed("401", status=401)
        def complete(self, p, t, *, max_tokens): raise P.JudgeLinkFailed("401", status=401)

    class Answering:
        name = "answering"
        def __init__(self): self.calls = []
        def score(self, p, t): self.calls.append(("score", p, t)); return 0.4
        def complete(self, p, t, *, max_tokens):
            self.calls.append(("complete", p, t, max_tokens)); return REPLY

    class Terminal:
        name = "terminal"
        def score(self, p, t): raise P.JudgeUnavailable("400 bad model")
        def complete(self, p, t, *, max_tokens): raise P.JudgeUnavailable("400 bad model")

    def test_a_refused_link_falls_through_to_the_next(self):
        answering = self.Answering()
        chain = P.JudgeChain([(self.Refusing(), "local", 0), (answering, "openai", 0)])
        self.assertEqual(chain.complete("P", "T", max_tokens=300), REPLY)
        self.assertEqual(answering.calls, [("complete", "P", "T", 300)])
        self.assertEqual([a.link for a in chain.last_attempts if a.served],
                         ["openai[0]"])

    def test_a_terminal_failure_does_not_fall_through(self):
        """Same rule as `score`: a 400 means the next key fails identically, and
        trying it would hide a configuration error behind a fallback."""
        answering = self.Answering()
        chain = P.JudgeChain([(self.Terminal(), "local", 0), (answering, "openai", 0)])
        with self.assertRaises(P.JudgeUnavailable):
            chain.complete("P", "T", max_tokens=300)
        self.assertEqual(answering.calls, [])

    def test_an_exhausted_chain_is_unavailable_not_empty(self):
        chain = P.JudgeChain([(self.Refusing(), "local", 0), (self.Refusing(), "openai", 0)])
        with self.assertRaises(P.JudgeUnavailable) as caught:
            chain.complete("P", "T", max_tokens=300)
        self.assertIn("nobody looked", str(caught.exception))

    def test_score_still_works_through_the_shared_walk(self):
        answering = self.Answering()
        chain = P.JudgeChain([(answering, "local", 0)])
        self.assertEqual(chain.score("P", "T"), 0.4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
