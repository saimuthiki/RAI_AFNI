# -*- coding: utf-8 -*-
"""Does a wrong-KIND credential get caught before it becomes `unjudged`?

WRITTEN FROM A REAL PASTE. A `GOOGLE_API_KEYS` value of the form `AQ.Ab8RN6…`
went into a `.env`. It is a genuine Google credential - an OAuth access token -
and it is not the thing `generativelanguage.googleapis.com?key=` accepts. The
platform built the link, `/healthz` reported `gemini[0]`, preflight said `set`,
and the only symptom would have been every Stage-3 judge rail reporting
`unjudged` and every escalated request failing closed.

The check is a WARNING and never a refusal. Only the vendor can say whether a key
works; a key that satisfies every rule here may be revoked, and one that fails
them may work against a gateway nobody here has heard of. So the value is still
tried, and these tests assert that too.
"""
from __future__ import annotations

import unittest

from afni_rai import keyshape

#: 39 characters: `AIza` + 35, the published AI Studio shape.
GOOD_GOOGLE = "AIza" + "K" * 35
#: The shape of an OAuth access token, which is what was actually pasted.
OAUTH_TOKEN = "AQ.Ab8RN6" + "Z" * 40
GOOD_OPENAI = "sk-proj-" + "Q" * 156
AZURE_OPENAI = "0123456789abcdef0123456789abcdef"


class GoogleKeys(unittest.TestCase):

    def test_an_ai_studio_key_passes(self):
        shape = keyshape.google_keys([GOOD_GOOGLE])
        self.assertTrue(shape.ok)
        self.assertFalse(shape.suspect)

    def test_an_oauth_token_is_suspect(self):
        shape = keyshape.google_keys([OAUTH_TOKEN])
        self.assertTrue(shape.suspect)
        self.assertIn("AI Studio", shape.detail)
        # The remedy has to say what to do, not just that it is wrong.
        self.assertIn("aistudio.google.com/apikey", shape.remedy)
        self.assertIn("ACCESS TOKEN", shape.remedy)

    def test_a_ya29_token_is_suspect_too(self):
        self.assertTrue(keyshape.google_keys(["ya29." + "a" * 60]).suspect)

    def test_the_right_prefix_at_the_wrong_length_is_suspect(self):
        """A truncated paste is the other half of this failure - the prefix
        survives a copy that stops early, so prefix alone is not enough."""
        self.assertTrue(keyshape.google_keys(["AIza" + "K" * 10]).suspect)

    def test_one_bad_entry_among_good_ones_is_named_by_position(self):
        shape = keyshape.google_keys([GOOD_GOOGLE, OAUTH_TOKEN, GOOD_GOOGLE])
        self.assertTrue(shape.suspect)
        self.assertIn("entry 2", shape.detail)

    def test_no_key_is_not_a_complaint(self):
        self.assertTrue(keyshape.google_keys([]).ok)


class OpenAIKeys(unittest.TestCase):

    def test_a_project_key_passes(self):
        self.assertTrue(keyshape.openai_keys(
            [GOOD_OPENAI], "https://api.openai.com/v1").ok)

    def test_every_openai_key_kind_passes(self):
        for kind in ("sk-", "sk-proj-", "sk-svcacct-", "sk-admin-"):
            with self.subTest(kind=kind):
                self.assertTrue(keyshape.openai_keys(
                    [kind + "x" * 48], "https://api.openai.com/v1").ok)

    def test_an_azure_key_against_openai_com_is_suspect(self):
        shape = keyshape.openai_keys([AZURE_OPENAI], "https://api.openai.com/v1")
        self.assertTrue(shape.suspect)
        self.assertIn("AZURE", shape.remedy)

    def test_the_same_key_against_an_azure_base_url_is_not_checked(self):
        """THE FALSE-POSITIVE THIS WOULD OTHERWISE CREATE. `OPENAI_API_KEYS`
        legitimately serves Azure OpenAI, LiteLLM and vLLM, whose key shapes are
        not OpenAI's to define. A check that fires on a correct Azure key is a
        check its reader learns to ignore."""
        shape = keyshape.openai_keys(
            [AZURE_OPENAI], "https://afni.openai.azure.com/openai")
        self.assertTrue(shape.ok)
        self.assertIn("shape not checked", shape.detail)

    def test_an_unset_base_url_falls_back_to_openais_own_shape(self):
        # Blank means the default, and the default is api.openai.com.
        self.assertTrue(keyshape.openai_keys([AZURE_OPENAI], "").suspect)


class AzureContentSafety(unittest.TestCase):

    def test_thirty_two_hex_characters_pass(self):
        self.assertTrue(keyshape.azure_content_safety_key(AZURE_OPENAI).ok)

    def test_an_endpoint_url_in_the_key_field_is_caught(self):
        shape = keyshape.azure_content_safety_key(
            "https://afni-cs.cognitiveservices.azure.com/")
        self.assertTrue(shape.suspect)
        self.assertIn("endpoint URL", shape.remedy)


class TheReportNeverCarriesAValue(unittest.TestCase):
    """THE RULE THIS MODULE MOST HAS TO KEEP.

    A shape report is written to describe a credential, and it is going to end
    up in a log, a screenshot and a support thread. `TargetConfig.describe()`
    already refuses to report even a key's LENGTH for that reason; length is
    allowed here only because "39 expected, 48 given" is often the whole
    diagnosis. Any part of the value itself is not.
    """

    def blob(self, env):
        report = keyshape.report(env)
        return " ".join(f"{s.detail} {s.remedy}" for s in report.values())

    def test_no_run_of_the_value_survives_into_the_report(self):
        secret = "AQ.zqXW7fLm4RvT9bKpNd3sYhJ2cEuA6gVn"
        blob = self.blob({"GOOGLE_API_KEYS": secret})
        self.assertTrue(blob, "the report was empty - this test proves nothing")
        for start in range(len(secret) - 5):
            with self.subTest(fragment=start):
                self.assertNotIn(secret[start:start + 6], blob)

    def test_the_openai_path_keeps_the_rule_too(self):
        secret = "pk-live-4Kd9wQ2mZv"
        self.assertNotIn(secret[3:12], self.blob({"OPENAI_API_KEYS": secret}))


class TheReport(unittest.TestCase):

    def test_an_empty_environment_produces_no_complaints(self):
        self.assertEqual(keyshape.report({}), {})

    def test_only_variables_that_are_set_appear(self):
        report = keyshape.report({"GOOGLE_API_KEYS": OAUTH_TOKEN})
        self.assertEqual(list(report), ["GOOGLE_API_KEYS"])
        self.assertTrue(report["GOOGLE_API_KEYS"].suspect)

    def test_the_singular_alias_is_read(self):
        # `*_API_KEY` is accepted everywhere else in the platform, so a shape
        # check that only read the plural would silently skip those deployments.
        report = keyshape.report({"GOOGLE_API_KEY": OAUTH_TOKEN})
        self.assertTrue(report["GOOGLE_API_KEYS"].suspect)

    def test_whitespace_around_a_comma_is_not_a_key(self):
        report = keyshape.report({"GOOGLE_API_KEYS": f"{GOOD_GOOGLE}, "})
        self.assertIn("1 key(s)", report["GOOGLE_API_KEYS"].detail)
        self.assertTrue(report["GOOGLE_API_KEYS"].ok)


class TheGatewayWarnsButStillTries(unittest.TestCase):
    """A shape check that could stop a key being used would be a shape check
    that can take a working gateway offline over a format it has not heard of."""

    def chain(self, env):
        from afni_rai.gateway import providers
        return providers.from_env(env, [])

    def test_a_suspect_key_is_still_built_into_the_chain(self):
        chain = self.chain({"AFNI_JUDGE_PROVIDER": "gemini",
                            "GOOGLE_API_KEYS": OAUTH_TOKEN})
        self.assertEqual(chain.links, ["gemini[0]"])

    def test_it_is_logged_once_at_warning(self):
        with self.assertLogs("afni_rai.gateway.providers", "WARNING") as caught:
            self.chain({"AFNI_JUDGE_PROVIDER": "gemini",
                        "GOOGLE_API_KEYS": OAUTH_TOKEN})
        lines = [l for l in caught.output if "does not look right" in l]
        self.assertEqual(len(lines), 1, caught.output)
        self.assertIn("GOOGLE_API_KEYS", lines[0])
        # It must not read as a refusal.
        self.assertIn("still", lines[0].lower())

    def test_a_good_key_logs_nothing(self):
        with self.assertLogs("afni_rai.gateway.providers", "INFO") as caught:
            self.chain({"AFNI_JUDGE_PROVIDER": "gemini",
                        "GOOGLE_API_KEYS": GOOD_GOOGLE})
        self.assertEqual(
            [l for l in caught.output if "does not look right" in l], [])

    def test_the_warning_never_carries_the_key(self):
        secret = "AQ.7hTnRs2WqLxE9dKmYbVc4gZuJf6pAo3N"
        with self.assertLogs("afni_rai.gateway.providers", "WARNING") as caught:
            self.chain({"AFNI_JUDGE_PROVIDER": "gemini",
                        "GOOGLE_API_KEYS": secret})
        blob = "\n".join(caught.output)
        for start in range(len(secret) - 5):
            with self.subTest(fragment=start):
                self.assertNotIn(secret[start:start + 6], blob)


class PreflightReportsIt(unittest.TestCase):

    def render(self, **env):
        import os
        from afni_rai import preflight
        previous = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            return preflight.render()
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_a_suspect_credential_renders_as_warn_not_ok(self):
        text = self.render(GOOGLE_API_KEYS=OAUTH_TOKEN)
        self.assertIn("[WARN] GOOGLE_API_KEYS", text)
        self.assertIn("SET BUT SUSPECT", text)
        self.assertIn("are SET but do not match the format", text)

    def test_a_good_credential_renders_as_ok(self):
        text = self.render(GOOGLE_API_KEYS=GOOD_GOOGLE)
        self.assertIn("[OK  ] GOOGLE_API_KEYS", text)
        self.assertNotIn("SET BUT SUSPECT", text)

    def test_a_suspect_credential_is_not_counted_as_outstanding(self):
        """It IS configured. Reporting it as missing would be a second wrong
        answer stacked on the first, and would make the outstanding count -
        which is the number people act on - wrong."""
        import re
        good = self.render(GOOGLE_API_KEYS=GOOD_GOOGLE)
        suspect = self.render(GOOGLE_API_KEYS=OAUTH_TOKEN)
        pattern = re.compile(r"(\d+) item\(s\) outstanding")
        self.assertEqual(pattern.search(good).group(1),
                         pattern.search(suspect).group(1))

    def test_preflight_never_prints_the_key(self):
        secret = "AQ.Xb4NvQ8sTmKd2WjLp7RcYh5gEuZa9FoI"
        text = self.render(GOOGLE_API_KEYS=secret)
        for start in range(len(secret) - 5):
            with self.subTest(fragment=start):
                self.assertNotIn(secret[start:start + 6], text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
