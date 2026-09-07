# -*- coding: utf-8 -*-
"""Are the numbers in `docs/console-guide.md` the numbers the platform reports?

A tab-by-tab guide is only useful while its counts are true, and counts in prose
rot silently: nothing fails when a rail is added and the doc still says 33. The
same argument as `test_env_manifest` - a manifest maintained by hand drifts from
the code, and the drift is visible only to whoever is holding the manifest.

WHAT IS PINNED AND WHAT IS NOT. Only host-INDEPENDENT numbers. `implemented` and
`dependency-missing` in the coverage totals move with which model weights are
installed, so pinning them would fail on a machine with a full model cache and
teach whoever hit it to delete the test. Those are marked in the guide as
host-dependent instead. `gap` - capabilities not built at all - is structural,
and is pinned.
"""
from __future__ import annotations

import pathlib
import re
import unittest

_DOC = pathlib.Path(__file__).resolve().parents[2] / "docs" / "console-guide.md"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _flat() -> str:
    """The guide with every run of whitespace collapsed to one space.

    Sentence-level assertions use this rather than the raw text. Prose wraps at
    the margin, so a sentence naming three counts almost always has a newline
    somewhere inside it, and a raw substring check would then fail for the
    formatting rather than for the number - which trains whoever hits it to
    reflow the paragraph until the test passes.
    """
    return " ".join(_DOC.read_text(encoding="utf-8").split())


def _client():
    import os

    from fastapi.testclient import TestClient

    from afni_rai.gateway.app import create_app
    os.environ.setdefault("AFNI_AUDIT_DB", ":memory:")
    return TestClient(create_app(warm=False))


class TheGuideExists(unittest.TestCase):

    def test_every_console_tab_has_a_section(self):
        """A tab with no section is the gap this file was written to close - the
        previous walkthrough covered nine of the eleven screens."""
        views = (_DOC.parents[1] / "rai_platform" / "web" / "views")
        text = _text().lower()
        # view filename -> the heading it is documented under
        headings = {"live": "live check", "architecture": "how it works",
                    "tenets": "tenets", "rails": "rails", "topics": "topics",
                    "sensitivity": "sensitivity", "media": "media",
                    "corpus": "corpus", "beforeafter": "before and after",
                    "frameworks": "frameworks", "governance": "governance"}
        found = sorted(p.stem for p in views.glob("*.js"))
        self.assertEqual(found, sorted(headings),
                         "a console view was added or renamed; the guide's "
                         "contents table has to follow")
        for view, heading in headings.items():
            with self.subTest(view=view):
                self.assertIn(f"## {heading}", text)

    def test_it_leads_with_the_status_code_rule(self):
        """The single most misread thing about this API."""
        self.assertIn("Read the DECISION, not the HTTP status", _flat())


class TheWalkthroughCoversEveryScreenToo(unittest.TestCase):
    """`ui-walkthrough.html` is the plain-English tour, and NOTHING VALIDATED IT.

    That is how it came to say "The nine screens, one at a time" while the
    console had eleven: Before-and-after and Governance were added to the menu
    and the tour was never told. A walkthrough that silently omits two screens
    is worse than one that omits them loudly, because a reader who finishes it
    believes they have seen the whole product.
    """

    HTML = _DOC.parent / "ui-walkthrough.html"

    def views(self) -> list[str]:
        return sorted(path.stem for path in
                      (_DOC.parents[1] / "rai_platform" / "web" / "views")
                      .glob("*.js"))

    def html(self) -> str:
        return self.HTML.read_text(encoding="utf-8")

    def test_it_has_one_numbered_section_per_console_view(self):
        ids = set(re.findall(r'id="(v\d+)"', self.html()))
        self.assertEqual(len(ids), len(self.views()),
                         f"{len(self.views())} console views, {len(ids)} "
                         f"walkthrough sections: {sorted(ids)}")

    def test_the_count_in_the_prose_matches_the_sections(self):
        """The heading is what a reader checks their progress against."""
        words = {9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
        text = self.html()
        self.assertIn(f"The {words[len(self.views())]} screens", text)
        for number, word in words.items():
            if number != len(self.views()):
                with self.subTest(word=word):
                    self.assertNotIn(f"The {word} screens", text)

    def test_every_view_is_reachable_by_its_console_route(self):
        """The `#/route` string is what a reader types. A section describing a
        screen without naming its route sends them hunting for it."""
        text = self.html()
        for view in self.views():
            with self.subTest(view=view):
                self.assertIn(f"#/{view}", text)


class TheRailCountsMatch(unittest.TestCase):

    def setUp(self):
        rails = _client().get("/v1/rails").json()
        self.rows = rails if isinstance(rails, list) else rails["rails"]

    def test_the_total(self):
        """ASSERTS THE ABSENCE, not just the presence.

        `assertIn("33 rails")` alone passes on the wrong document: "33 rails"
        also appears under Governance ("33 rails mounted") and inside the
        per-stage sentence, so a Rails section edited to say 34 still satisfied
        it. Checked by mutation - changing the Rails heading to 34 did not fail
        the test - which is the whole reason a doc test can be worse than no
        doc test. So the neighbouring counts must be ABSENT.
        """
        total = len(self.rows)
        flat = _flat()
        self.assertIn(f"**What you should see:** {total} rails", flat)
        for wrong in (total - 1, total + 1):
            with self.subTest(wrong=wrong):
                self.assertNotIn(f"{wrong} rails", flat)

    def test_the_per_stage_split(self):
        from collections import Counter
        by_stage = Counter(r["stage"] for r in self.rows)
        self.assertIn(f"{by_stage[1]} rails at Stage 1, {by_stage[2]} at "
                      f"Stage 2, {by_stage[3]} at Stage 3", _flat())
        # And in the cascade table, where the cost of each stage is stated.
        self.assertIn(f"| 1 | {by_stage[1]} rails", _text())

    def test_the_per_direction_split(self):
        from collections import Counter
        d = Counter(r["direction"] for r in self.rows)
        self.assertIn(f"{d['both']} rails apply to both sides, {d['output']} "
                      f"are output-only, {d['input']} is input-only", _flat())


class TheTopicCountsMatch(unittest.TestCase):

    def test_the_four_counts(self):
        counts = _client().get("/v1/topics").json()["counts"]
        text = _text()
        for key in ("always", "optional_available", "blocking_patterns",
                    "semantic_classes"):
            with self.subTest(key=key):
                self.assertIn(f"`{key}: {counts[key]}`", text)

    def test_the_guide_says_topics_need_a_restart(self):
        """The most common "my change did nothing" on these screens."""
        self.assertIn("Topics arm on RESTART", _text())


class TheThresholdCountsMatch(unittest.TestCase):

    def test_the_number_of_thresholds_and_the_presets(self):
        body = _client().get("/v1/thresholds").json()
        text = _text()
        self.assertIn(f"{len(body['thresholds'])} thresholds", text)
        for preset in body["presets"]:
            with self.subTest(preset=preset["name"]):
                self.assertIn(f"`{preset['name']}`", text)
                if preset["touches"]:
                    self.assertIn(str(preset["touches"]), text)

    def test_the_shipped_injection_threshold_in_the_worked_example(self):
        """The example tells the reader to raise this above a measured 0.9847,
        so a changed shipped value would make the instruction wrong."""
        body = _client().get("/v1/thresholds").json()
        row = next(t for t in body["thresholds"]
                   if t["key"] == "security.prompt_injection.classifier")
        self.assertIn(f"= **{row['shipped']}**", _text())

    def test_it_warns_that_the_override_map_replaces(self):
        self.assertIn("**replaces** the whole override map", _flat())


class TheCorpusFiguresMatch(unittest.TestCase):

    def setUp(self):
        self.body = _client().get("/v1/corpus").json()

    def test_the_record_and_baseline_counts(self):
        text = _text()
        self.assertIn(f"{self.body['records']:,}", text)
        self.assertIn(f"{self.body['baselined']} — only these can drift", text)

    def test_the_per_tenet_table_is_complete_and_exact(self):
        text = _text()
        for row in self.body["tenets"]:
            with self.subTest(tenet=row["tenet"]):
                self.assertIn(f"| {row['tenet']} | {row['records']:,} |", text)

    def test_the_output_direction_count(self):
        out = next(d["records"] for d in self.body["directions"]
                   if d["direction"] == "output")
        self.assertIn(f"{out} affirmative completions", _text())

    def test_it_says_an_allow_is_a_miss(self):
        """The one sentence that stops a reader celebrating a 98% allow rate on
        a corpus where every record is a harmful prompt."""
        self.assertIn("an `allow` is a MISS", _text())

    def test_it_carries_the_handling_rule(self):
        self.assertIn("Cite the record `id`, never the text", _text())
        self.assertFalse(self.body["cloud_allowed"],
                         "AFNI_CORPUS_ALLOW_CLOUD is on; the guide says it is "
                         "off and explains why it should be")


class TheFrameworkAndCoverageFiguresMatch(unittest.TestCase):

    def test_the_adoption_group_sizes(self):
        body = _client().get("/v1/repositories").json()
        text = _text()
        for group in body["groups"]:
            with self.subTest(verdict=group["adoption"]):
                self.assertIn(f"| {group['adoption']} | {len(group['repos'])} |",
                              text)

    def test_the_unlinkable_count(self):
        body = _client().get("/v1/repositories").json()
        self.assertIn(f"{len(body['unlinkable'])} of them", _text())

    def test_the_structural_gap_count(self):
        """`gap` is "not built", which no install changes - unlike
        `implemented` and `dependency-missing`, which the guide marks as
        host-dependent rather than pinning here."""
        totals = _client().get("/v1/coverage").json()["totals"]
        self.assertIn(f"| `gap` | {totals['gap']} | **not built** |", _text())


class TheMediaFiguresMatch(unittest.TestCase):

    def test_the_detector_and_every_label_group(self):
        body = _client().get("/v1/media").json()
        text = _text()
        self.assertIn(f"`{body['detector']}`", text)
        self.assertIn(f"`{body['package']}`", text)
        for label in body["labels"]["explicit_block"]:
            with self.subTest(label=label):
                self.assertIn(f"`{label}`", text)

    def test_it_says_oversized_is_unjudged_not_an_error(self):
        self.assertIn("reported `unjudged`", _text())


class TheGovernanceGuidanceIsRight(unittest.TestCase):

    def test_it_steers_to_contact_rather_than_domain(self):
        """DOMAIN generates seven aliases. If they do not exist, the register
        carries seven bouncing addresses."""
        text = _text()
        self.assertIn("Set **CONTACT** unless those seven aliases actually "
                      "exist", _flat())

    def test_the_counts_match(self):
        counts = _client().get("/v1/governance").json()["counts"]
        self.assertIn(f"{counts['tenets']} tenets, {counts['rails_mounted']} "
                      f"rails mounted, {counts['thresholds_listed']} "
                      f"thresholds listed", _flat())


class TheTroubleshootingTableIsUsable(unittest.TestCase):

    def test_it_names_the_real_symptoms_seen_on_afnis_host(self):
        text = _text()
        for symptom in ("local[nokey]", "topics arm on **restart**",
                        "`stages_run` never reaches 3", "degraded"):
            with self.subTest(symptom=symptom):
                self.assertIn(symptom, text)

    def test_every_related_document_it_points_at_exists(self):
        """A guide whose "see also" is broken is worse than one with none."""
        for match in re.findall(r"`(docs/[\w.\-]+)`", _text()):
            with self.subTest(path=match):
                self.assertTrue((_DOC.parents[1] / match).exists(), match)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
