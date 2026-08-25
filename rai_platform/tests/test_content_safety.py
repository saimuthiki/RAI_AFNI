# -*- coding: utf-8 -*-
"""
Tests for the Profanity / Content Safety rails.

The bar for a wordlist filter is not "does it catch a swear word" - every one of
the five reviewed tools that ships a wordlist does that. The bar is whether it
can be left switched on, so most of what is tested here is *true negatives*: the
Scunthorpe family, snake_case identifiers, numeric columns, clinical anatomy, and
the terms in the vendored lists that double as ordinary technical English (`div`,
`prod`, `nonce`, `git`, `jap` as a locale code).

The false-positive claims in this file are not opinions. Each was found by
running the filter over the vendored repos and this platform's own tree - 10k+
files - and each fix is pinned by a test here.

Run: python3 rai_platform/run_tests.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai.cascade.engine import Cascade  # noqa: E402
from afni_rai.cascade.rail import RailResult, Stage  # noqa: E402
from afni_rai.contract.explanation import (  # noqa: E402
    CONFIDENCE_KINDS, explain,
)
from afni_rai.contract.models import (  # noqa: E402
    Action, Decision, EventKind, GuardEvent, LLMProtocol, Severity, Tenet,
)
from afni_rai.registry.capabilities import (  # noqa: E402
    CapabilityRegistry, Coverage,
)
from afni_rai.tenets import content_safety as cs  # noqa: E402

PATH = "payload.text"


def event(text, client_facing=True):
    return GuardEvent(
        kind=EventKind.REQUEST,
        step_id="step-1",
        agent_id="agent-1",
        agent_type="chat",
        agent_workspace="afni",
        agent_user="tester",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload={"text": text},
        client_facing=client_facing,
    )


def subjects(result):
    return sorted(f.subject for f in result.findings)


def categories(result):
    return sorted(f.category for f in result.findings)


# ------------------------------------------------------------- taxonomy -----
class TestHarmTaxonomy(unittest.TestCase):
    """The taxonomy is pure data ported from OpenGuardrails' spec. These tests
    exist so a silent drift from the spec - a dropped root, an id that no longer
    validates - fails here rather than in a client's compliance report."""

    def test_all_eleven_spec_roots_are_present(self):
        # taxonomy.md:10-26 defines exactly eleven safety.* ids.
        self.assertEqual(len(cs.SAFETY_ROOTS), 11)
        for root in cs.SAFETY_ROOTS:
            with self.subTest(root=root):
                self.assertIn(root, cs.SAFETY_CATEGORIES)

    def test_every_category_id_validates_against_the_contract(self):
        from afni_rai.contract.models import Finding
        for cat in cs.SAFETY_CATEGORIES:
            with self.subTest(cat=cat):
                Finding(category=cat)   # raises if the pattern rejects it

    def test_every_mapped_id_is_a_known_category(self):
        # A vendor label mapping to an id we do not define would create a
        # garbage bucket in the compliance rollup.
        for label, cat in cs.VENDOR_LABEL_MAP.items():
            with self.subTest(label=label):
                self.assertIn(cat, cs.SAFETY_CATEGORIES)

    def test_vendor_labels_map_to_the_spec_vocabulary(self):
        # llm-guard toxicity.py:28-36 head labels.
        self.assertEqual(cs.map_category("identity_attack"),
                         "safety.toxicity.hate")
        self.assertEqual(cs.map_category("sexual_explicit"), "safety.sexual")
        self.assertEqual(cs.map_category("threat"), "safety.violence.threat")
        # promptfoo plugins.ts:55-79 ids.
        self.assertEqual(cs.map_category("harmful:child-exploitation"),
                         "safety.sexual.minors")
        self.assertEqual(cs.map_category("harmful:specialized-advice"),
                         "safety.unsafe_advice")
        # garak ofcom column 1.
        self.assertEqual(cs.map_category("raceethnic"), "safety.toxicity.hate")

    def test_unknown_label_falls_back_rather_than_inventing_an_id(self):
        self.assertEqual(cs.map_category("no_such_label"), "safety.toxicity")
        self.assertEqual(cs.map_category("no_such_label", "safety.illicit"),
                         "safety.illicit")

    def test_rollup_falls_back_to_the_longest_known_prefix(self):
        # The spec's hierarchical rollup rule, taxonomy.md "Conventions".
        self.assertEqual(cs.rollup("safety.toxicity.hate.regional"),
                         "safety.toxicity.hate")
        self.assertEqual(cs.rollup("safety.sexual.minors"),
                         "safety.sexual.minors")
        self.assertEqual(cs.rollup("safety.brand.anything"), "safety.brand")

    def test_promptfoo_harmful_ids_are_covered(self):
        # All 26 harmful:* plugin ids from plugins.ts:55-79 must be mapped;
        # an unmapped one would silently become safety.toxicity in a report.
        harmful = [k for k in cs.VENDOR_LABEL_MAP if k.startswith("harmful:")]
        self.assertEqual(len(harmful), 26, harmful)


# ------------------------------------------------- profanity: true positives -
class TestProfanityTruePositives(unittest.TestCase):

    def setUp(self):
        self.rail = cs.PROFANITY_RAIL

    def test_stage_and_tenet(self):
        self.assertIs(self.rail.stage, Stage.STAGE_1)
        self.assertIs(self.rail.tenet, Tenet.CONTENT_SAFETY)

    def test_plain_expletive_is_flagged_not_blocked(self):
        out = self.rail.check(PATH, "this is a load of bollocks")
        self.assertFalse(out.block, "a mild expletive must not hard block")
        self.assertEqual(subjects(out), ["bollocks"])
        self.assertEqual(categories(out), ["safety.toxicity.profanity"])
        self.assertIs(out.findings[0].action, Action.FLAG)
        # Flag-tier hits ask for a context-aware second look.
        self.assertTrue(out.escalate)

    def test_slur_hard_blocks(self):
        out = self.rail.check(PATH, "he called me a nigger")
        self.assertTrue(out.block)
        self.assertEqual(categories(out), ["safety.toxicity.hate"])
        self.assertIs(out.findings[0].action, Action.BLOCK)
        self.assertIs(out.findings[0].severity, Severity.CRITICAL)

    def test_a_slur_and_an_expletive_are_not_the_same_finding(self):
        # The whole point of the graded tier: "damn" and a racial slur must not
        # produce the same action or the same severity.
        mild = self.rail.check(PATH, "damn it")
        slur = self.rail.check(PATH, "you golliwog")
        self.assertIs(mild.findings[0].action, Action.FLAG)
        self.assertIs(mild.findings[0].severity, Severity.LOW)
        self.assertIs(slur.findings[0].action, Action.BLOCK)
        self.assertIs(slur.findings[0].severity, Severity.CRITICAL)

    def test_leetspeak_substitutions_are_normalised(self):
        # The reverse of better_profanity's CHARS_MAPPING
        # (better_profanity/better_profanity.py:33-43).
        for text, want in [("what the f*ck", "fuck"),
                           ("holy $hit", "shit"),
                           ("@ss", "ass"),
                           ("4r5e", "4r5e"),
                           ("sh!t happens", "sh!t")]:
            with self.subTest(text=text):
                out = self.rail.check(PATH, text)
                self.assertIn(want, subjects(out), text)

    def test_punctuation_around_a_token_does_not_hide_it(self):
        for text in ("fuck!", "(shit)", "'bollocks'"):
            with self.subTest(text=text):
                self.assertTrue(self.rail.check(PATH, text).findings, text)

    def test_multiword_phrases_match_and_report_once(self):
        out = self.rail.check(PATH, "what a son of a bitch")
        self.assertEqual(subjects(out), ["son of a bitch"],
                         "phrase must report once, not also as 'bitch'")

    def test_hyphenated_terms_match_written_either_way(self):
        for text in ("he is a fudge-packer", "he is a fudge packer"):
            with self.subTest(text=text):
                out = self.rail.check(PATH, text)
                self.assertTrue(out.block)
                self.assertEqual(subjects(out), ["fudge-packer"])

    def test_case_is_irrelevant(self):
        self.assertTrue(self.rail.check(PATH, "BOLLOCKS").findings)
        self.assertTrue(self.rail.check(PATH, "Nigger").block)


# ------------------------------------------------- profanity: true negatives -
class TestProfanityTrueNegatives(unittest.TestCase):
    """A profanity filter with a bad false-positive rate is worse than none.
    Every case here is one the filter must stay silent on."""

    def setUp(self):
        self.rail = cs.PROFANITY_RAIL
        self.explicit = cs.EXPLICIT_RAIL

    def assertSilent(self, text):
        for rail in (self.rail, self.explicit):
            out = rail.check(PATH, text)
            self.assertEqual(out.findings, [],
                             f"{rail.name} fired on {text!r}: "
                             f"{subjects(out)}")
            self.assertFalse(out.block, f"{rail.name} blocked {text!r}")

    def test_the_scunthorpe_family(self):
        # Whole-token matching, ported from better_profanity's character walk
        # (better_profanity/better_profanity.py:168-214). Substring matching a
        # profanity list is the single most common way this check is got wrong.
        for text in ("Scunthorpe United", "the assessment is complete",
                     "a classic design", "Cockburn Sound", "class attendance",
                     "the analysis of the classification", "Penistone Road",
                     "he is a specialist", "Titsworth Avenue",
                     "shitake mushrooms are not shiitake"):
            with self.subTest(text=text):
                self.assertSilent(text)

    def test_snake_case_identifiers_are_not_words(self):
        # `_` is outside the token alphabet so `hand_job` still matches the
        # phrase - the cost is that `cum_sum_ratio` splits too. Measured firing
        # on deepchecks' own variable name before the fix.
        for text in ("cum_sum_ratio = df['count'].cumsum()",
                     "RID_GO_INJECT_1_CREDIT_CARD_xxx",
                     "self.ass_error = 0", "x = ass_thresholds[i]"):
            with self.subTest(text=text):
                self.assertSilent(text)

    def test_numbers_are_never_de_obfuscated(self):
        # 455 de-leets to "ass" (4->a, 5->s, 5->s) and fired on a column of
        # floats in a fairlearn test fixture. Leetspeak needs a letter.
        for text in ("1, 455.18, 440, 0.393661032",
                     "455 455 455", "5$5", "4r5"):
            with self.subTest(text=text):
                self.assertSilent(text)

    def test_engineering_vocabulary_from_the_ambiguity_tier(self):
        # Each of these terms IS in one of the three vendored wordlists. Firing
        # on them is how a profanity filter gets switched off for good.
        for text in ("wrap the row in a <div> and ship to prod",
                     "the nonce is regenerated for every request",
                     "git commit -m 'flaps and knob positions'",
                     "retard the ignition timing by two degrees",
                     "the slope of the regression line",
                     "a special case in the mental model",
                     "language: en,jap",
                     "call a spade a spade",
                     "this is a niggle, not a defect"):
            with self.subTest(text=text):
                self.assertSilent(text)

    def test_clinical_and_legal_registers_are_not_flagged(self):
        # A healthcare or safeguarding payload is full of these. Flagging them
        # is why the anatomy terms live in the ambiguity tier.
        for text in ("the patient's anus and rectum were examined",
                     "sexual harassment policy training",
                     "the alleged rape was reported to police",
                     "sex: F, age: 43",
                     "a nude study by Degas"):
            with self.subTest(text=text):
                self.assertSilent(text)

    def test_proper_names_are_not_slurs(self):
        for text in ("Nancy Pelosi", "Dick Cheney", "Van Dyke Parks",
                     "Attila the Hun", "Fanny Blankers-Koen",
                     "Jock Stein", "Taff Vale Railway"):
            with self.subTest(text=text):
                self.assertSilent(text)

    def test_empty_and_whitespace_are_clean_not_unjudged(self):
        for text in ("", "   ", "\n\t"):
            with self.subTest(text=text):
                out = self.rail.check(PATH, text)
                self.assertTrue(out.judged)
                self.assertEqual(out.findings, [])
                self.assertFalse(out.escalate)

    def test_ordinary_business_prose_is_silent_and_does_not_escalate(self):
        out = self.rail.check(
            PATH,
            "Please review the attached quarterly report and confirm the "
            "reconciliation figures before Friday's board meeting.")
        self.assertEqual(out.findings, [])
        self.assertFalse(out.escalate, "clean text must not pay for stage 2")
        self.assertTrue(out.judged)


# ---------------------------------------------------------- ambiguity tier --
class TestAmbiguityTier(unittest.TestCase):
    """The tier that deliberately does not fire, and hands the decision to the
    context-aware Stage-2 classifier instead."""

    def test_ambiguous_term_produces_no_finding_but_escalates(self):
        out = cs.PROFANITY_RAIL.check(PATH, "deploy the div to prod")
        self.assertEqual(out.findings, [])
        self.assertFalse(out.block)
        self.assertTrue(out.escalate,
                        "an ambiguous term must not be silently clean either")
        self.assertIn("Stage-2", out.reason or "")

    def test_ambiguous_terms_are_absent_from_both_lexicons(self):
        # A term in the ambiguity table must not also be matchable, or the
        # exclusion is cosmetic.
        for term in cs._AMBIGUOUS_TERMS:
            with self.subTest(term=term):
                self.assertNotIn(term, cs._TOXICITY_LEXICON)
                self.assertNotIn(term, cs._SEXUAL_LEXICON)

    def test_every_ambiguous_entry_carries_a_stated_reason(self):
        for term, reason in cs._AMBIGUOUS.items():
            with self.subTest(term=term):
                self.assertTrue(reason.strip(),
                                f"{term!r} excluded without a reason")

    def test_the_two_lexicons_are_disjoint(self):
        overlap = set(cs._TOXICITY_LEXICON) & set(cs._SEXUAL_LEXICON)
        self.assertEqual(overlap, set(),
                         "a term in both rails would double-report")

    def test_the_raw_infosys_junk_never_became_a_term(self):
        # Infosys' 917-row wordlist.csv contains these. A gateway that fired on
        # them would be unusable, and `len` would hit every line of Python.
        for word in ("len", "pot", "god", "kill", "fat", "pawn", "hemp",
                     "omg", "rum", "maxi", "ovum", "womb", "weed", "niggle"):
            with self.subTest(word=word):
                self.assertNotIn((word,), cs._TOXICITY_LEXICON)
                self.assertNotIn((word,), cs._SEXUAL_LEXICON)


# ----------------------------------------------------------- explicit rail --
class TestExplicitContent(unittest.TestCase):

    def setUp(self):
        self.rail = cs.EXPLICIT_RAIL

    def test_explicit_vocabulary_is_flagged_as_safety_sexual(self):
        out = self.rail.check(PATH, "send me some hardcore hentai")
        self.assertEqual(categories(out), ["safety.sexual"])
        self.assertIs(out.findings[0].action, Action.FLAG)
        self.assertTrue(out.escalate)

    def test_multiword_explicit_phrase(self):
        out = self.rail.check(PATH, "a golden shower video")
        self.assertEqual(subjects(out), ["golden shower"])

    def test_it_does_not_claim_the_minors_class(self):
        # No safety.sexual.minors tier exists at stage 1: the only candidate
        # terms in the vendored lists cannot distinguish solicitation from
        # safeguarding discussion, and "Shota" is a common given name.
        for entry in cs._SEXUAL_LEXICON.values():
            with self.subTest(term=entry.term):
                self.assertNotEqual(entry.category, "safety.sexual.minors")

    def test_the_profanity_rail_does_not_report_sexual_categories(self):
        for entry in cs._TOXICITY_LEXICON.values():
            with self.subTest(term=entry.term):
                self.assertTrue(entry.category.startswith("safety.toxicity"))


# ------------------------------------------------------ banned substrings ----
class TestBannedSubstrings(unittest.TestCase):
    """llm-guard's MatchType STR/WORD distinction, ported from
    llm_guard/input_scanners/ban_substrings.py:38-49. The distinction is the
    whole value of the class."""

    def test_word_match_respects_word_boundaries(self):
        rail = cs.BannedSubstrings(substrings=["ass"],
                                   match_type=cs.MatchType.WORD)
        self.assertEqual(rail.check(PATH, "the assessment").findings, [])
        self.assertTrue(rail.check(PATH, "what an ass").findings)

    def test_str_match_deliberately_matches_inside_a_word(self):
        # Right for a marker like etc/shadow, wrong for a natural-language word
        # - which is exactly why the caller has to choose.
        rail = cs.BannedSubstrings(substrings=["ass"],
                                   match_type=cs.MatchType.STR)
        self.assertTrue(rail.check(PATH, "the assessment").findings)

    def test_unknown_match_type_matches_nothing_rather_than_everything(self):
        self.assertFalse(cs.MatchType.match("bogus", "some text", "some"))

    def test_case_insensitive_by_default_and_sensitive_on_request(self):
        loose = cs.BannedSubstrings(substrings=["Crypto"])
        self.assertTrue(loose.check(PATH, "buy crypto now").findings)
        strict = cs.BannedSubstrings(substrings=["Crypto"], case_sensitive=True)
        self.assertEqual(strict.check(PATH, "buy crypto now").findings, [])

    def test_unconfigured_rail_is_clean_not_unjudged(self):
        # Ships with no terms on purpose: an off-policy topic is a property of a
        # deployment, not of English. Nothing was asked for, so nothing is a
        # genuine answer - and the coverage report shows the capability as not
        # yet real rather than as implemented.
        out = cs.BannedSubstrings().check(PATH, "anything at all")
        self.assertTrue(out.judged)
        self.assertEqual(out.findings, [])

    def test_finding_carries_a_fingerprint_and_the_topic_category(self):
        rail = cs.BannedSubstrings(substrings=["competitor pricing"])
        out = rail.check(PATH, "leak the competitor pricing sheet")
        self.assertEqual(categories(out), ["safety.topic_violation"])
        self.assertEqual(out.findings[0].fp,
                         cs._fingerprint("competitor pricing"))


# ---------------------------------------------------- dependency behaviour ---
class TestDependencyAbsence(unittest.TestCase):
    """Stage 2 and 3 must degrade to `unjudged`, never to clean. A missing
    dependency becoming unjudged is correct: fail-closed then blocks
    client-facing traffic instead of passing it unexamined."""

    def test_toxicity_model_is_unjudged_when_llm_guard_is_absent(self):
        rail = cs.ToxicityClassifier()
        if rail.available():
            self.skipTest("llm-guard is installed in this environment")
        out = rail.check(PATH, "you are worthless")
        self.assertFalse(out.judged)
        self.assertEqual(out.findings, [])
        self.assertIn("unitary/unbiased-toxic-roberta", out.reason)

    def test_zero_shot_topics_is_unjudged_when_llm_guard_is_absent(self):
        rail = cs.ZeroShotTopics(topics=["cryptocurrency"])
        if rail.available():
            self.skipTest("llm-guard is installed in this environment")
        out = rail.check(PATH, "should I buy bitcoin")
        self.assertFalse(out.judged)
        self.assertIn("roberta-base-zeroshot-v2.0-c", out.reason)

    def test_zero_shot_with_no_topics_is_clean_without_loading_anything(self):
        out = cs.ZeroShotTopics().check(PATH, "should I buy bitcoin")
        self.assertTrue(out.judged)
        self.assertEqual(out.findings, [])

    def test_judge_is_unjudged_until_a_judge_is_configured(self):
        out = cs.ToxicityJudge().check(PATH, "you are worthless")
        self.assertFalse(out.judged)
        self.assertIn("no LLM judge configured", out.reason)

    def test_a_configured_judge_scores_and_blocks_above_threshold(self):
        rail = cs.ToxicityJudge(judge=lambda text: 0.93)
        out = rail.check(PATH, "anything")
        self.assertTrue(out.judged)
        self.assertTrue(out.block)
        self.assertAlmostEqual(out.findings[0].score, 0.93)
        below = cs.ToxicityJudge(judge=lambda text: 0.2).check(PATH, "anything")
        self.assertTrue(below.judged)
        self.assertEqual(below.findings, [])

    def test_a_raising_judge_is_unjudged_not_clean(self):
        def boom(_text):
            raise RuntimeError("429 rate limited")

        out = cs.ToxicityJudge(judge=boom).check(PATH, "anything")
        self.assertFalse(out.judged)
        self.assertIn("RuntimeError", out.reason)

    def test_importing_this_package_pulls_no_heavy_dependency(self):
        # No model download and no torch import as a side effect of importing
        # the module. Run in a subprocess so the harness's own already-imported
        # modules cannot mask the answer.
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            "import sys; sys.path.insert(0, %r);"
            "import afni_rai.tenets.content_safety;"
            "bad=[m for m in sys.modules if m.split('.')[0] in "
            "('torch','transformers','llm_guard','numpy','requests',"
            "'urllib3','httpx')];"
            "print(','.join(sorted(bad)))" % root
        )
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "",
                         "importing content_safety pulled a heavy dependency")

    def test_availability_probe_does_not_construct_a_scanner(self):
        # `_scanners` is keyed by threshold rather than a single `_scanner`,
        # because llm-guard takes the threshold at construction and a per-tenant
        # value has to reach the constructor to have any effect.
        for rail in (cs.ToxicityClassifier(), cs.ZeroShotTopics(topics=("x",))):
            with self.subTest(rail=rail.name):
                rail.available()
                self.assertEqual(rail._scanners, {},
                                 "available() must not download weights")


# ----------------------------------------------------- findings discipline ---
class TestFindingDiscipline(unittest.TestCase):
    """Rule 5 of the platform: matched text appears nowhere in a finding except
    `subject`, and `fp` is a hash of it. A guardrail that logs what it caught has
    defeated itself."""

    def test_fp_is_a_sha256_prefix_of_the_subject(self):
        import hashlib
        out = cs.PROFANITY_RAIL.check(PATH, "utter bollocks")
        finding = out.findings[0]
        want = hashlib.sha256(
            finding.subject.encode("utf-8")).hexdigest()[:16]
        self.assertEqual(finding.fp, want)
        self.assertNotIn(finding.subject, finding.fp)

    def test_subject_is_the_canonical_term_not_the_raw_span(self):
        out = cs.PROFANITY_RAIL.check(PATH, "what the F*CK")
        self.assertEqual(subjects(out), ["fuck"])

    def test_offsets_point_at_the_match(self):
        text = "you utter bollocks, mate"
        out = cs.PROFANITY_RAIL.check(PATH, text)
        f = out.findings[0]
        self.assertEqual(text[f.start:f.end].lower(), "bollocks")

    def test_deterministic_rails_emit_no_score(self):
        # A regex match at "1.0" invites comparison with a classifier
        # probability. The attribution's confidence_kind says deterministic.
        out = cs.PROFANITY_RAIL.check(PATH, "utter bollocks")
        self.assertIsNone(out.findings[0].score)

    def test_no_finding_field_other_than_subject_echoes_the_text(self):
        out = cs.PROFANITY_RAIL.check(PATH, "you nigger")
        d = out.findings[0].to_dict()
        for key, value in d.items():
            if key == "subject":
                continue
            with self.subTest(key=key):
                self.assertNotIn("nigger", str(value).lower())

    def test_every_finding_names_its_detector_for_attribution(self):
        for rail, text in ((cs.PROFANITY_RAIL, "utter bollocks"),
                           (cs.EXPLICIT_RAIL, "some hentai"),
                           (cs.BannedSubstrings(substrings=["bitcoin"]),
                            "buy bitcoin")):
            with self.subTest(rail=rail.name):
                out = rail.check(PATH, text)
                self.assertTrue(out.findings)
                for f in out.findings:
                    self.assertEqual(f.detector, rail.name)


# ------------------------------------------------------------- attribution ---
class TestAttribution(unittest.TestCase):

    def test_every_rail_has_an_attribution_keyed_by_its_name(self):
        for rail in cs.RAILS:
            with self.subTest(rail=rail.name):
                self.assertIn(rail.name, cs.ATTRIBUTIONS)
                self.assertEqual(cs.ATTRIBUTIONS[rail.name].rail, rail.name)

    def test_attribution_stage_matches_the_rail_stage(self):
        for rail in cs.RAILS:
            with self.subTest(rail=rail.name):
                self.assertEqual(cs.ATTRIBUTIONS[rail.name].stage,
                                 int(rail.stage))

    def test_confidence_kinds_are_from_the_contract_vocabulary(self):
        for attr in list(cs.ATTRIBUTIONS.values()) + [cs.TAXONOMY_ATTRIBUTION]:
            with self.subTest(rail=attr.rail):
                self.assertIn(attr.confidence_kind, CONFIDENCE_KINDS)

    def test_stage_1_rails_claim_deterministic_confidence(self):
        for rail in cs.RAILS:
            if rail.stage is not Stage.STAGE_1:
                continue
            with self.subTest(rail=rail.name):
                self.assertEqual(cs.ATTRIBUTIONS[rail.name].confidence_kind,
                                 "deterministic")

    def test_every_attribution_cites_evidence(self):
        for attr in list(cs.ATTRIBUTIONS.values()) + [cs.TAXONOMY_ATTRIBUTION]:
            with self.subTest(rail=attr.rail):
                self.assertGreater(len(attr.evidence), 40, attr.rail)
                self.assertTrue(attr.capability)

    def test_explanation_joins_a_finding_to_its_source_repo(self):
        cascade = Cascade([cs.PROFANITY_RAIL])
        out = cascade.evaluate(event("you nigger"))
        exp = explain(out.verdict, cs.ATTRIBUTIONS, out.stages_run)
        self.assertIs(exp.decision, Decision.BLOCK)
        self.assertEqual(len(exp.blocked_by), 1)
        sentence = exp.blocked_by[0].sentence()
        self.assertIn("garak", sentence)
        # Redacted by default: the slur must not appear in the explanation.
        self.assertNotIn("nigger", sentence)
        self.assertIn("value withheld", sentence)


# ---------------------------------------------------------------- cascade ----
class TestInTheCascade(unittest.TestCase):

    def test_no_offline_rail_is_exported_for_mounting(self):
        # The red-team capability is registered as OFFLINE coverage instead.
        for rail in cs.RAILS:
            with self.subTest(rail=rail.name):
                self.assertIsNot(rail.stage, Stage.OFFLINE)
        Cascade(cs.RAILS)   # would raise if one slipped through

    def test_stage_1_slur_block_never_pays_for_stage_2_or_3(self):
        cascade = Cascade(cs.RAILS)
        out = cascade.evaluate(event("you golliwog"))
        self.assertIs(out.verdict.decision, Decision.BLOCK)
        self.assertEqual(out.verdict.unjudged, [],
                         "a stage-1 block must not leave an unjudged path")
        self.assertTrue(out.trace[-1].short_circuited)

    def test_clean_text_fails_closed_only_if_a_later_stage_actually_ran(self):
        # Clean stage 1 does not escalate, so the absent stage-2 model is never
        # consulted and the request is allowed.
        out = Cascade(cs.RAILS).evaluate(
            event("Please confirm the reconciliation figures."))
        self.assertIs(out.verdict.decision, Decision.ALLOW)
        self.assertEqual(out.verdict.unjudged, [])

    def test_a_flag_tier_hit_escalates_and_then_fails_closed(self):
        # This is the honest consequence of the model being absent: a borderline
        # payload escalates, stage 2 cannot judge, and client-facing traffic is
        # blocked rather than passed.
        if cs.TOXICITY_MODEL_RAIL.available():
            self.skipTest("llm-guard is installed; stage 2 can judge")
        out = Cascade(cs.RAILS).evaluate(event("this is bollocks"))
        self.assertTrue(out.verdict.could_not_judge)
        self.assertIs(out.verdict.decision, Decision.BLOCK)

    def test_the_same_payload_is_allowed_on_internal_traffic(self):
        if cs.TOXICITY_MODEL_RAIL.available():
            self.skipTest("llm-guard is installed; stage 2 can judge")
        out = Cascade(cs.RAILS).evaluate(
            event("this is bollocks", client_facing=False))
        self.assertIs(out.verdict.decision, Decision.ALLOW)
        # Allowed, but the gap is still on the record.
        self.assertTrue(out.verdict.could_not_judge)

    def test_rails_never_raise_on_awkward_input(self):
        weird = ["", " ", "\x00\x01", "a" * 20000, "😀" * 50,
                 " fuck ", "%s %r {} [] \\", "0" * 500,
                 "_" * 100, "@$*!+'\"" * 20]
        for rail in cs.RAILS:
            for text in weird:
                with self.subTest(rail=rail.name, text=text[:20]):
                    out = rail.check(PATH, text)
                    self.assertIsInstance(out, RailResult)


# --------------------------------------------------------------- coverage ----
class TestCoverageRegistration(unittest.TestCase):

    def setUp(self):
        self.registry = CapabilityRegistry()
        cs.register(self.registry)
        self.report = self.registry.report()
        self.rows = self.report.by_tenet[Tenet.CONTENT_SAFETY]

    def status(self, capability):
        for row in self.rows:
            if row.capability == capability:
                return row.status
        self.fail(f"{capability!r} not in the report")

    def test_every_capability_of_the_tenet_is_accounted_for(self):
        names = self.registry.names(Tenet.CONTENT_SAFETY)
        self.assertEqual(len(self.rows), len(names))
        self.assertEqual(sorted(r.capability for r in self.rows),
                         sorted(names))

    def test_no_capability_is_left_unregistered_by_accident(self):
        # Exactly one honest gap, and it is a stated one.
        gaps = [r.capability for r in self.rows
                if r.status is Coverage.GAP]
        self.assertEqual(gaps, ["NSFW image/video detection"])

    def test_the_stdlib_rails_are_the_implemented_ones(self):
        self.assertIs(self.status("Profanity / banned-word filter"),
                      Coverage.IMPLEMENTED)
        self.assertIs(self.status("Adult / explicit content"),
                      Coverage.IMPLEMENTED)
        self.assertIs(self.status("Multi-category harm taxonomy"),
                      Coverage.IMPLEMENTED)

    def test_model_backed_capabilities_are_dependency_not_implemented(self):
        if cs.TOXICITY_MODEL_RAIL.available():
            self.skipTest("llm-guard is installed in this environment")
        self.assertIs(self.status("Toxicity / hate-speech (model)"),
                      Coverage.DEPENDENCY)
        self.assertIs(self.status("Zero-shot restricted-topic filter"),
                      Coverage.DEPENDENCY)
        self.assertIs(self.status("Toxicity (LLM judge)"),
                      Coverage.DEPENDENCY)

    def test_cloud_and_offline_are_not_counted_as_runtime_cover(self):
        self.assertIs(self.status("Managed safety-model routing"),
                      Coverage.CLOUD)
        self.assertIs(self.status("Harmful-content red-team sets"),
                      Coverage.OFFLINE)

    def test_every_registration_carries_a_note(self):
        for row in self.rows:
            with self.subTest(capability=row.capability):
                self.assertTrue(row.note.strip(),
                                f"{row.capability} registered without a note")

    def test_implemented_registrations_have_an_attribution_with_evidence(self):
        for row in self.rows:
            if row.status is not Coverage.IMPLEMENTED:
                continue
            with self.subTest(capability=row.capability):
                self.assertIsNotNone(row.attribution)
                self.assertEqual(row.attribution.capability, row.capability)
                self.assertGreater(len(row.attribution.evidence), 40)

    def test_counts_add_up_and_the_report_renders(self):
        counts = self.report.counts(Tenet.CONTENT_SAFETY)
        self.assertEqual(sum(counts.values()), len(self.rows))
        self.assertEqual(counts[Coverage.IMPLEMENTED], 3)
        self.assertEqual(counts[Coverage.CLOUD], 1)
        self.assertEqual(counts[Coverage.OFFLINE], 1)
        self.assertEqual(counts[Coverage.GAP], 1)
        self.assertIn("Profanity / Content Safety", self.report.render())

    def test_registering_a_typo_is_a_hard_error(self):
        # A typo would inflate the coverage number while leaving the real
        # capability counted as a gap.
        with self.assertRaises(KeyError):
            self.registry.register(
                Tenet.CONTENT_SAFETY, "Profanity filter",
                Coverage.IMPLEMENTED)

    def test_registration_is_idempotent(self):
        cs.register(self.registry)
        again = self.registry.report().by_tenet[Tenet.CONTENT_SAFETY]
        self.assertEqual(len(again), len(self.rows))


# ------------------------------------------------------------- lexicon data --
class TestLexiconProvenance(unittest.TestCase):
    """The tier tables are a port of vendored data. These tests pin the shape of
    that port so a later edit cannot quietly change what the gateway blocks."""

    def test_the_ofcom_table_is_ported_whole(self):
        # garak/data/ofcom-potentially-offensive.txt, 150 rows.
        self.assertEqual(len(cs._OFCOM), 150)
        categories = {row[0] for row in cs._OFCOM}
        self.assertEqual(categories, {"general", "sexual", "raceethnic",
                                      "sexgender", "discriminatory",
                                      "mentalhealth"})
        for cat, term, strength in cs._OFCOM:
            with self.subTest(term=term):
                self.assertIn(strength, (0, 1, 2, 3, 4))
                self.assertEqual(term, term.lower())

    def test_strength_zero_terms_are_never_compiled(self):
        # OFCOM grades "gay" 0. A zero-strength term is not a finding.
        for cat, term, strength in cs._OFCOM:
            if strength == 0:
                with self.subTest(term=term):
                    self.assertNotIn(cs._phrase(term), cs._TOXICITY_LEXICON)
                    self.assertNotIn(cs._phrase(term), cs._SEXUAL_LEXICON)

    def test_only_identity_slurs_at_strength_three_or_more_hard_block(self):
        for key, entry in cs._TOXICITY_LEXICON.items():
            if entry.action is not Action.BLOCK:
                continue
            with self.subTest(term=entry.term):
                self.assertEqual(entry.category, "safety.toxicity.hate",
                                 f"{entry.term} blocks but is not a slur")
                self.assertIn(entry.severity,
                              (Severity.HIGH, Severity.CRITICAL))

    def test_the_sexual_lexicon_never_hard_blocks(self):
        # Lexical explicit-content detection is a flag, not a block: it cannot
        # tell an explicit request from a clinical or literary discussion.
        for entry in cs._SEXUAL_LEXICON.values():
            with self.subTest(term=entry.term):
                self.assertIsNot(entry.action, Action.BLOCK)

    def test_every_compiled_term_records_where_it_came_from(self):
        for entry in list(cs._TOXICITY_LEXICON.values()) + \
                list(cs._SEXUAL_LEXICON.values()):
            with self.subTest(term=entry.term):
                self.assertTrue(entry.source.strip())

    def test_the_confirmed_lists_come_from_two_independent_sources(self):
        # 159 terms confirmed by both Infosys' wordlist.csv and garak's
        # ldnoobw-en.txt. The union of our four partitions must cover them.
        partitioned = (set(cs._SLUR_CONFIRMED) | set(cs._EXPLICIT_CONFIRMED)
                       | set(cs._PROFANITY_CONFIRMED))
        overlaps = [
            (a, b) for a, b in (
                (set(cs._SLUR_CONFIRMED), set(cs._EXPLICIT_CONFIRMED)),
                (set(cs._SLUR_CONFIRMED), set(cs._PROFANITY_CONFIRMED)),
                (set(cs._EXPLICIT_CONFIRMED), set(cs._PROFANITY_CONFIRMED)),
            ) if a & b
        ]
        self.assertEqual(overlaps, [], "a term is in two tiers at once")
        self.assertGreater(len(partitioned), 120)

    def test_variant_families_inherit_their_stem_tier(self):
        stem = cs._TOXICITY_LEXICON[("fuck",)]
        for variant in ("fucktard", "phuk", "fvck", "fux"):
            with self.subTest(variant=variant):
                entry = cs._TOXICITY_LEXICON[cs._phrase(variant)]
                self.assertEqual(entry.action, stem.action)
                self.assertEqual(entry.category, stem.category)

    def test_the_lexicons_are_not_empty(self):
        self.assertGreater(len(cs._TOXICITY_LEXICON), 150)
        self.assertGreater(len(cs._SEXUAL_LEXICON), 80)
        self.assertGreater(len(cs._AMBIGUOUS_TERMS), 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
