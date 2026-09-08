# -*- coding: utf-8 -*-
"""Does a structured judge reply get read, or refused - and never guessed?

`parse_json_object` is `_parse_score` for the omnibus moderation rail: one JSON
object with a score per check. Same doctrine - refusing beats parsing, and a
refusal becomes `unjudged`, which fails closed.

The counter-example it is written against is the Infosys moderation layer,
whose dispatcher catches a parse failure, returns None, and later crashes at
`sum(results, [])` (service.py:1033-1036, :1662): a malformed reply takes the
whole request down instead of resolving to any verdict. Here it resolves to
`unjudged`, loudly, every time.
"""
from __future__ import annotations

import unittest

from afni_rai.gateway.providers import JudgeUnavailable, parse_json_object

GOOD = '{"explanation": "no issues found", "prompt_injection": 3, "toxicity": 0}'


class ItReadsWhatAModelActuallyReturns(unittest.TestCase):

    def test_a_bare_object(self):
        self.assertEqual(parse_json_object(GOOD)["prompt_injection"], 3)

    def test_a_fenced_object(self):
        """Infosys asks the model to "exclude json markers" and small models
        emit them anyway. Stripping a fence is tolerance for a format, not for
        an ambiguity."""
        self.assertEqual(parse_json_object(f"```json\n{GOOD}\n```")["toxicity"], 0)

    def test_prose_around_the_object(self):
        self.assertEqual(
            parse_json_object(f"Here is my assessment:\n{GOOD}\nHope that helps.")
            ["prompt_injection"], 3)

    def test_nested_objects_inside_are_fine(self):
        raw = '{"explanation": "x", "toxicity": {"score": 12, "metrics": [{"a": 1}]}}'
        self.assertEqual(parse_json_object(raw)["toxicity"]["score"], 12)

    def test_whitespace_and_newlines_are_fine(self):
        self.assertEqual(parse_json_object(f"\n\n  {GOOD}  \n")["toxicity"], 0)


class ItRefusesAnythingThatIsNotOneObject(unittest.TestCase):

    def refuse(self, raw, fragment):
        with self.assertRaises(JudgeUnavailable) as caught:
            parse_json_object(raw)
        self.assertIn(fragment, str(caught.exception))

    def test_empty(self):
        self.refuse("", "empty reply")
        self.refuse("   \n", "empty reply")

    def test_prose_only(self):
        self.refuse("I cannot assess this content.", "no JSON object")

    def test_a_bare_number_is_not_an_object(self):
        """The narrow judges answer this way. The omnibus rail must not accept
        it, or a model that fell back to its bare-float habit would be read as
        an object with no checks in it - a clean verdict from nothing."""
        # The whole reply parses as JSON - a float - so the refusal names the
        # TYPE, which is the more useful message: the model answered in the
        # narrow judges' shape, not in this rail's.
        self.refuse("0.7", "not an object: float")

    def test_a_list_is_not_an_object(self):
        self.refuse('[{"toxicity": 90}]', "not an object")

    def test_malformed_json_is_refused_not_repaired(self):
        self.refuse('{"toxicity": 90, "profanity": }', "malformed JSON")

    def test_two_objects_are_ambiguous(self):
        self.refuse('{"toxicity": 90} {"toxicity": 0}', "malformed JSON")

    def test_a_trailing_second_object_is_ambiguous(self):
        """A valid object followed by a stray `{` slices cleanly to the first
        object - `rfind("}")` finds only that one - so the parse SUCCEEDS, and
        the tail check is what refuses. Reading the first object and ignoring
        the tail would be guessing which one was the verdict."""
        self.refuse('{"toxicity": 90}\nSecond opinion: {', "more than one JSON object")

    def test_an_essay_is_refused_by_length(self):
        self.refuse("{" + '"a": 1, ' * 2000 + '"b": 2}', "characters")

    def test_refusals_never_quote_more_than_a_snippet(self):
        """The reply is model output about text under judgement and lands in a
        log. Refusing must not echo the whole thing."""
        long = "not json " * 300
        with self.assertRaises(JudgeUnavailable) as caught:
            parse_json_object(long)
        self.assertLess(len(str(caught.exception)), 300)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
