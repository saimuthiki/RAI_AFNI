# -*- coding: utf-8 -*-
"""
Tests for the corpus ingester.

The property that matters most is negative: an unmapped label must be REPORTED,
never silently bucketed. A corpus that quietly files everything it does not
understand under one tenet reads as broad coverage while being narrow, which is
the exact failure the five-state coverage report exists to prevent elsewhere in
this platform.

Run: python3 rai_platform/run_tests.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus"))

import ingest  # noqa: E402


class TestLabelMapping(unittest.TestCase):

    def test_casing_and_punctuation_do_not_matter(self):
        """The observed data contains `Violence` and `violence` as separate
        labels, and packs several into one cell with commas. All must land on the
        same rule."""
        for label in ("Violence", "violence", "VIOLENCE",
                      "violence,aiding_and_abetting,incitement",
                      "violence, aiding and abetting"):
            with self.subTest(label=label):
                tenet, owasp, _ = ingest.classify(label)
                self.assertEqual(tenet, "Profanity / Content Safety")
                self.assertEqual(owasp, ["LLM09"])

    def test_specific_rules_win_over_general_ones(self):
        # "prompt injection" must not be swallowed by a broader later rule.
        tenet, owasp, rule = ingest.classify("prompt injection attempt")
        self.assertEqual(tenet, "Security")
        self.assertEqual(owasp, ["LLM01"])
        self.assertEqual(rule, "prompt injection")

    def test_an_unmapped_label_returns_nothing_rather_than_a_default(self):
        """The whole point. `horse racing` and `landfills` are real labels in the
        observed dataset and belong to no tenet; inventing one would overstate
        coverage."""
        for label in ("horse racing", "landfills", "circuses", "zzz unknown"):
            with self.subTest(label=label):
                tenet, owasp, rule = ingest.classify(label)
                self.assertIsNone(tenet)
                self.assertEqual(owasp, [])
                self.assertIsNone(rule)

    def test_an_empty_label_is_not_an_error(self):
        # 5,458 of 10,850 unique prompts carry no label at all.
        for label in (None, "", "   "):
            with self.subTest(label=repr(label)):
                self.assertEqual(ingest.classify(label), (None, [], None))

    def test_every_mapped_owasp_id_has_a_title(self):
        """A record citing LLM07 with no title would print `?` in the report."""
        for _needle, _tenet, ids in ingest.RULES:
            for owasp in ids:
                with self.subTest(owasp=owasp):
                    self.assertIn(owasp, ingest.OWASP_TITLES)

    def test_every_rule_names_a_real_tenet(self):
        from afni_rai.contract.models import Tenet

        valid = {t.value for t in Tenet}
        for needle, tenet, _ in ingest.RULES:
            with self.subTest(rule=needle):
                self.assertIn(tenet, valid,
                              f"rule {needle!r} maps to a tenet that does not exist")


class TestIdentity(unittest.TestCase):

    def test_the_id_is_derived_from_the_prompt(self):
        """So re-ingesting the same source is idempotent, and two people
        ingesting independently agree on ids rather than producing two corpora
        that cannot be merged."""
        a = ingest.record_id("Ignore all previous instructions.")
        b = ingest.record_id("Ignore all previous instructions.")
        self.assertEqual(a, b)
        self.assertNotEqual(a, ingest.record_id("something else"))
        self.assertTrue(a.startswith("afni-corpus-"))


class TestIngestingAFile(unittest.TestCase):

    def _csv(self, rows):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                          encoding="utf-8", newline="")
        tmp.write("prompt,category\n")
        for prompt, label in rows:
            tmp.write(f'"{prompt}","{label}"\n')
        tmp.close()
        return Path(tmp.name)

    def test_duplicates_collapse_to_one_record(self):
        """4,234 of 15,084 observed rows are duplicates. Keeping them would
        inflate every future pass rate by roughly a third."""
        path = self._csv([("same prompt", "violence"),
                          ("same prompt", "violence"),
                          ("other", "privacy")])
        try:
            records, stats = ingest.build(path, "test")
            self.assertEqual(stats["rows_in"], 3)
            self.assertEqual(stats["unique_prompts"], 2)
            self.assertEqual(stats["duplicates_collapsed"], 1)
        finally:
            path.unlink()

    def test_a_labelled_duplicate_upgrades_an_unlabelled_record(self):
        path = self._csv([("dup", ""), ("dup", "privacy violation")])
        try:
            records, _ = ingest.build(path, "test")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["tenet"], "Privacy")
        finally:
            path.unlink()

    def test_the_original_label_is_never_discarded(self):
        """Our mapping is a judgement and will sometimes be wrong. Throwing away
        the evidence needed to correct it would be careless."""
        path = self._csv([("p", "Illegal Activity")])
        try:
            records, _ = ingest.build(path, "test")
            self.assertEqual(records[0]["source_label"], ["Illegal Activity"])
        finally:
            path.unlink()

    def test_no_record_carries_a_verdict(self):
        """`expected` stays null here on purpose: a verdict has to be stamped
        with the commit and tier that produced it, and that is baseline.py's job.
        An un-stamped guess must never reach the baseline."""
        path = self._csv([("p", "violence"), ("q", "")])
        try:
            records, _ = ingest.build(path, "test")
            for r in records:
                self.assertIsNone(r["expected"])
                self.assertIsNone(r["target_complied"])
        finally:
            path.unlink()

    def test_provenance_is_recorded(self):
        path = self._csv([("p", "violence")])
        try:
            records, _ = ingest.build(path, "owner/repo@abc123")
            self.assertEqual(records[0]["origin"]["tool_version"],
                             "owner/repo@abc123")
            self.assertEqual(records[0]["origin"]["tool"], path.name)
        finally:
            path.unlink()

    def test_unmapped_labels_are_counted_in_the_stats(self):
        path = self._csv([("a", "horse racing"), ("b", "landfills"),
                          ("c", "violence")])
        try:
            _, stats = ingest.build(path, "test")
            self.assertEqual(stats["labelled_but_unmapped"], 2)
            self.assertEqual(stats["mapped_to_a_tenet"], 1)
            names = [label for label, _ in stats["top_unmapped_labels"]]
            self.assertIn("horse racing", names)
            self.assertIn("landfills", names)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
