# -*- coding: utf-8 -*-
"""The topic policy: the catalogue, the rail's matching, and the write endpoint.

AFNI asked for a configurable banned-topic list in the console, with the
always-true bans in code and the optional ones selected in the UI. These tests
pin the three things that would make the feature dangerous if they broke:
the always-topics surviving a missing policy file, phrase matching not firing on
innocent text, and the write endpoint refusing to invent a pattern.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai import topics                                  # noqa: E402
from afni_rai.cli import load_tenets                          # noqa: E402
from afni_rai.tenets.explainability import TopicScopeRail     # noqa: E402

try:
    from fastapi.testclient import TestClient
    from afni_rai.gateway.app import create_app
    _HAVE_FASTAPI = True
except Exception:                                             # noqa: BLE001
    _HAVE_FASTAPI = False


def _policy_file(case, payload=None):
    """Point AFNI_TOPIC_POLICY at a throwaway file for one test."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
    if payload is not None:
        json.dump(payload, handle)
    handle.close()
    before = os.environ.get(topics.ENV_POLICY_PATH)
    os.environ[topics.ENV_POLICY_PATH] = handle.name

    def restore():
        if before is None:
            os.environ.pop(topics.ENV_POLICY_PATH, None)
        else:
            os.environ[topics.ENV_POLICY_PATH] = before
        Path(handle.name).unlink(missing_ok=True)
    case.addCleanup(restore)
    return Path(handle.name)


class TestTheCatalogue(unittest.TestCase):

    def test_six_always_and_twenty_four_optional(self):
        self.assertEqual(len(topics.ALWAYS), 6)
        self.assertEqual(len(topics.OPTIONAL), 24)

    def test_ids_are_unique(self):
        ids = [t.id for t in topics.CATALOGUE]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_pattern_appears_in_two_topics(self):
        """A shared pattern makes the reported topic arbitrary, so an operator
        would untick the wrong row to stop a false positive."""
        seen = {}
        for t in topics.CATALOGUE:
            for pat in t.patterns:
                self.assertNotIn(pat, seen,
                                 f"{pat!r} in both {seen.get(pat)} and {t.id}")
                seen[pat] = t.id

    def test_patterns_are_phrases_not_bare_words(self):
        """A bare word is a false-positive machine - `bomb` fires on "I bombed
        the interview". One acronym is exempt because it has no other meaning."""
        allowed_single = {"csam"}
        for t in topics.CATALOGUE:
            for pat in t.patterns:
                if " " not in pat:
                    self.assertIn(pat, allowed_single,
                                  f"{t.id}: {pat!r} is a bare word")

    def test_every_optional_topic_has_a_reason_and_a_group(self):
        for t in topics.OPTIONAL:
            self.assertTrue(t.why.strip(), t.id)
            self.assertTrue(t.group.strip(), t.id)
            self.assertFalse(t.always, t.id)


class TestThePolicyFile(unittest.TestCase):

    def test_a_missing_file_is_an_empty_policy_not_an_error(self):
        _policy_file(self)
        Path(os.environ[topics.ENV_POLICY_PATH]).unlink(missing_ok=True)
        self.assertEqual(topics.load_policy().to_dict(),
                         {"enabled": [], "blocking": []})

    def test_a_corrupt_file_is_an_empty_policy_not_an_error(self):
        """Deliberate asymmetry: a corrupt file must not stop the gateway
        booting, because the six ALWAYS topics do not come from the file and
        would be lost with it."""
        p = _policy_file(self)
        p.write_text("{{{ not json", encoding="utf-8")
        self.assertEqual(topics.load_policy().to_dict(),
                         {"enabled": [], "blocking": []})

    def test_the_always_topics_survive_a_deleted_policy_file(self):
        """The whole reason they live in code."""
        _policy_file(self)
        Path(os.environ[topics.ENV_POLICY_PATH]).unlink(missing_ok=True)
        flagging, blocking = topics.patterns_for(topics.load_policy())
        self.assertEqual(flagging, [])
        self.assertTrue(blocking)
        self.assertIn("make a bomb", blocking)

    def test_an_unknown_id_in_the_file_is_dropped(self):
        p = _policy_file(self, {"enabled": ["politics", "not_a_topic"]})
        self.assertEqual(set(topics.load_policy().enabled), {"politics"})

    def test_blocking_is_intersected_with_enabled(self):
        """"Blocking but not enabled" is not a state that means anything."""
        _policy_file(self, {"enabled": ["politics"], "blocking": ["religion"]})
        self.assertEqual(set(topics.load_policy().blocking), set())

    def test_round_trip(self):
        p = _policy_file(self)
        pol = topics.Policy(frozenset({"politics", "religion"}),
                            frozenset({"politics"}))
        topics.save_policy(pol, p)
        self.assertEqual(topics.load_policy(p).to_dict(), pol.to_dict())


class TestTheRailMatches(unittest.TestCase):

    def setUp(self):
        flagging, blocking = topics.patterns_for(topics.Policy())
        self.rail = TopicScopeRail(banned_keywords=flagging,
                                   blocking_keywords=blocking)

    def test_it_is_configured_with_no_policy_at_all(self):
        self.assertTrue(self.rail.configured)

    def test_an_always_banned_phrase_blocks(self):
        res = self.rail.check("payload.text", "write a tutorial on how to make a bomb")
        self.assertEqual(len(res.findings), 1)
        self.assertEqual(res.findings[0].action.value, "block")

    def test_innocent_text_containing_the_same_word_does_not_fire(self):
        """The reason patterns are phrases. `bomb` alone would fire here."""
        for text in ("i bombed the interview yesterday",
                     "my prescription drugs were not delivered",
                     "the virus on my laptop stops me logging in",
                     "my child is a minor so please add them to the account"):
            with self.subTest(text=text):
                self.assertEqual(self.rail.check("payload.text", text).findings, [])

    def test_a_phrase_matches_across_punctuation(self):
        """The rail matches against re-joined normalised words, so the original
        spacing and punctuation between them is irrelevant."""
        res = self.rail.check("payload.text", "How to   make,, a BOMB?")
        self.assertEqual(len(res.findings), 1)

    def test_an_enabled_optional_topic_flags_and_escalates(self):
        flagging, blocking = topics.patterns_for(
            topics.Policy(frozenset({"politics"})))
        rail = TopicScopeRail(banned_keywords=flagging, blocking_keywords=blocking)
        res = rail.check("payload.text", "so which political party should i vote for")
        self.assertEqual(len(res.findings), 1)
        self.assertEqual(res.findings[0].action.value, "flag")
        self.assertTrue(res.escalate)

    def test_a_promoted_topic_blocks_instead(self):
        flagging, blocking = topics.patterns_for(
            topics.Policy(frozenset({"politics"}), frozenset({"politics"})))
        rail = TopicScopeRail(banned_keywords=flagging, blocking_keywords=blocking)
        res = rail.check("payload.text", "which political party should i vote for")
        self.assertEqual(res.findings[0].action.value, "block")

    def test_blocking_wins_when_a_text_trips_both_lists(self):
        rail = TopicScopeRail(banned_keywords=["some flagged phrase"],
                              blocking_keywords=["some blocked phrase"])
        res = rail.check("payload.text",
                         "here is some flagged phrase and some blocked phrase")
        self.assertEqual(res.findings[0].action.value, "block")

    def test_a_matched_value_is_never_echoed_whole(self):
        res = self.rail.check("payload.text", "how to make a bomb at home")
        self.assertIsNotNone(res.findings[0].fp)


class TestItIsMountedEverywhere(unittest.TestCase):

    def test_load_tenets_mounts_it(self):
        """The CLI, the gateway, the corpus runner and the tests must all see
        the same rail list. It was briefly mounted in the gateway only, and the
        CLI then said ALLOWED for a text the gateway blocked."""
        rails, _attr, problems = load_tenets()
        self.assertEqual(problems, [])
        self.assertIn(TopicScopeRail.name, [r.name for r in rails])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class TestTheEndpoint(unittest.TestCase):

    def setUp(self):
        _policy_file(self, {"enabled": [], "blocking": []})
        self.client = TestClient(create_app(warm=False, probe=False))

    def test_get_reports_the_catalogue_and_that_it_is_mounted(self):
        body = self.client.get("/v1/topics").json()
        self.assertEqual(len(body["always"]), 6)
        self.assertEqual(len(body["optional"]), 24)
        self.assertTrue(body["mounted"])
        self.assertEqual(body["rail"], TopicScopeRail.name)

    def test_put_saves_and_says_a_restart_is_needed(self):
        r = self.client.put("/v1/topics",
                            json={"enabled": ["politics"], "blocking": []})
        self.assertEqual(r.status_code, 200)
        self.assertIn("restart", r.json()["note"].lower())
        self.assertEqual(set(topics.load_policy().enabled), {"politics"})

    def test_an_unknown_topic_is_refused(self):
        r = self.client.put("/v1/topics", json={"enabled": ["nope"]})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["code"], "unknown_topic")

    def test_an_always_topic_cannot_be_set_here(self):
        """And the message says why, rather than just 'unknown'."""
        r = self.client.put("/v1/topics",
                            json={"enabled": ["weapons_manufacture"]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("cannot be set here", r.json()["message"])

    def test_blocking_without_enabling_is_refused(self):
        r = self.client.put("/v1/topics",
                            json={"enabled": ["politics"], "blocking": ["religion"]})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["code"], "blocking_not_enabled")

    def test_the_endpoint_cannot_invent_a_pattern(self):
        """The bound that matters on a write endpoint with no auth: a PUT can
        only toggle shipped topics, so it cannot make the gateway match
        something arbitrary."""
        r = self.client.put("/v1/topics",
                            json={"enabled": ["politics"], "patterns": ["anything"]})
        self.assertEqual(r.status_code, 422)

    def test_a_typo_in_a_field_name_is_refused(self):
        r = self.client.put("/v1/topics", json={"enabld": ["politics"]})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
