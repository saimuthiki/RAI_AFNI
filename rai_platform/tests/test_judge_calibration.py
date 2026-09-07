# -*- coding: utf-8 -*-
"""Does the judge get asked a question a SMALL model can actually answer?

WRITTEN FROM A MEASURED FAILURE ON AFNI'S OWN BOX. `qwen3-vl-8b-instruct`,
serving `local[0]` at the front of the judge chain, was asked how TOXIC this is:

    "My SSN is 123-45-6789 and my card is 4111111111111111. Email
     jane.doe@example.com, phone 555-0100."

and answered 1.00 - the maximum. There is nothing toxic in that text. The
`privacy.pii_leakage_judge` scored the same text 1.00, correctly, and the two
identical scores are the tell: the model was not answering the question it was
asked, it was rating how bad the text looked.

The old instruction named only the endpoints - "0 means clearly fine, 1 means
clearly a violation" - so a model with any doubt had no scale to answer on and
answered at the top. Both judge rails share that instruction, so one such reply
blocks every escalated request while `/healthz` reports a working judge chain.

Nothing here can prove a model's ANSWERS improve - that needs the endpoint, and
it is on a private network this build environment cannot reach. What is testable
is the contract: the question excludes the other tenets, the scale has middle
points, and a reply that does not follow the contract is REFUSED rather than
turned into a verdict. The last one is the part that fails closed.
"""
from __future__ import annotations

import unittest

from afni_rai.gateway import providers
from afni_rai.gateway.providers import JudgeUnavailable, _parse_score


class TheScoreInstructionGivesTheModelAScale(unittest.TestCase):

    def test_it_names_intermediate_anchors(self):
        """A model that cannot choose between 0 and 1 can still choose 0.3."""
        for anchor in ("0.0", "0.3", "0.7", "1.0"):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, providers.SCORE_INSTRUCTION)

    def test_it_says_another_tenets_violation_scores_zero_here(self):
        """THE OBSERVED MISTAKE, addressed in the shared instruction as well as
        in each prompt: the model saw text that was obviously a violation of
        SOMETHING and scored it 1 on whichever question it was handed."""
        text = providers.SCORE_INSTRUCTION.lower()
        self.assertIn("other", text)
        self.assertIn("0.0", text)
        self.assertIn("do not answer 1.0 unless", text)

    def test_it_still_demands_a_bare_number(self):
        self.assertIn("nothing else", providers.SCORE_INSTRUCTION.lower())


class EachPromptExcludesTheOtherTenets(unittest.TestCase):
    """Each rail judges ONE tenet. The cascade has separate rails for the
    others and reports their findings separately, so a judge that scores every
    kind of harm on every question makes all of them the same detector."""

    def test_the_toxicity_judge_excludes_personal_data(self):
        prompt = providers.JUDGE_PROMPTS["content_safety.toxicity_judge"].lower()
        self.assertIn("not toxicity", prompt)
        for excluded in ("card numbers", "id numbers", "manipulate an\nai system"):
            with self.subTest(excluded=excluded):
                self.assertIn(excluded.replace("\n", " "),
                              " ".join(prompt.split()))

    def test_the_privacy_judge_excludes_toxicity(self):
        prompt = providers.JUDGE_PROMPTS["privacy.pii_leakage_judge"].lower()
        self.assertIn("not disclosure", prompt)
        self.assertIn("toxic", prompt)

    def test_both_ask_for_strictness(self):
        for name, prompt in providers.JUDGE_PROMPTS.items():
            with self.subTest(rail=name):
                self.assertIn("strict", prompt.lower())

    def test_the_prompts_still_cover_exactly_the_bound_rails(self):
        """A renamed rail with no prompt is a rail bound to `None`, which
        reports `unjudged` forever and reads as a broken judge."""
        self.assertEqual(set(providers.JUDGE_PROMPTS),
                         {"content_safety.toxicity_judge",
                          "privacy.pii_leakage_judge"})


class AReplyThatIsNotAScoreIsRefused(unittest.TestCase):
    """Refusing beats parsing. Every refusal here becomes `unjudged`, which
    blocks; every wrong parse becomes a verdict nobody produced."""

    def test_a_bare_number_is_accepted(self):
        for raw, expected in (("0.85", 0.85), (" 0.7 ", 0.7), ("1", 1.0),
                              ("0", 0.0), ("**0.85**", 0.85),
                              ("Score: 0.4", 0.4)):
            with self.subTest(raw=raw):
                self.assertAlmostEqual(_parse_score(raw), expected)

    def test_a_recited_scale_is_refused_and_not_read_as_clean(self):
        """THE REGRESSION THIS FILE EXISTS FOR.

        `SCORE_INSTRUCTION` now recites a four-point scale, and the failure mode
        of a small model handed a scale is to recite it back. That reply opens
        with a number - `0.0` - so a "first number wins" parser turns it into a
        CLEAN verdict invented from a non-answer, on the rail whose whole job is
        to refuse exactly that.
        """
        with self.assertRaises(JudgeUnavailable) as caught:
            _parse_score("0.0 the text does not do this at all")
        self.assertIn("bare number", str(caught.exception))

    def test_two_numbers_are_refused_rather_than_resolved(self):
        with self.assertRaises(JudgeUnavailable) as caught:
            _parse_score("0.7/1.0")
        self.assertIn("2 numbers", str(caught.exception))

    def test_prose_with_no_number_is_still_refused(self):
        with self.assertRaises(JudgeUnavailable):
            _parse_score("I cannot assess this")

    def test_out_of_range_is_still_refused(self):
        with self.assertRaises(JudgeUnavailable):
            _parse_score("2.5")

    def test_an_empty_reply_is_refused(self):
        for raw in ("", "   ", None):
            with self.subTest(raw=raw):
                with self.assertRaises(JudgeUnavailable):
                    _parse_score(raw)  # type: ignore[arg-type]

    def test_a_refusal_never_quotes_more_than_a_snippet(self):
        """The reply is model output about text under judgement, and it lands in
        a log. A judge echoing the payload must not put all of it there."""
        long = "0.0 " + ("the text does not do this at all " * 40)
        with self.assertRaises(JudgeUnavailable) as caught:
            _parse_score(long)
        self.assertLess(len(str(caught.exception)), 260)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
