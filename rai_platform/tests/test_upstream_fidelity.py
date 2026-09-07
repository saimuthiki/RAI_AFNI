# -*- coding: utf-8 -*-
"""Where this platform diverges from the code it cites, is the divergence meant?

Every rail here is a port, and each one names the upstream file and line it came
from. That citation is the platform's main claim to being reviewable - so a
DEFAULT that quietly differs from the source it cites is worse than an obvious
gap: the evidence string still points at upstream, and the behaviour no longer
matches it.

Two such divergences were found by reading the vendored sources, and both had
already cost something measurable:

  llm-guard's `DEFAULT_ENTITY_TYPES` does NOT include `LOCATION`
  (references/llm-guard-main/.../input_scanners/anonymize.py:27-41). This
  platform's list did. The consequence appeared on the benign control - "What
  are your office hours in Amsterdam, and do you support iDEAL?" produced
  `privacy.pii.address` at 0.85 on "Amsterdam", actioned `redact` - because
  `ner_mapping.py:202-209` folds STREET, CITY, ZIPCODE, STATE and COUNTY all
  into LOCATION, and the published taxonomy has no coarser bucket
  (`taxonomy.md:160`: LOCATION -> privacy.pii.address).

  `BanTopics(topics: list[str])` takes topics as a REQUIRED positional argument
  (ban_topics.py:100-107) - no default, no None. `ZeroShotTopics()` was
  constructed with none, so the rail could only ever return clean.

These tests read the vendored files at run time rather than hard-coding what
they say, so a reference update that changes upstream's mind shows up here.
"""
from __future__ import annotations

import pathlib
import re
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_REFS = _ROOT / "references"
_LLM_GUARD = (_REFS / "llm-guard-main" / "llm-guard-main" / "llm_guard")


def _skip_unless(path: pathlib.Path, test: unittest.TestCase) -> str:
    """The references folder is large and a checkout may not carry it."""
    if not path.exists():
        test.skipTest(f"vendored source not present: {path}")
    return path.read_text(encoding="utf-8")


class ThePresidioEntityListMatchesUpstream(unittest.TestCase):

    SOURCE = _LLM_GUARD / "input_scanners" / "anonymize.py"

    def upstream(self) -> list[str]:
        text = _skip_unless(self.SOURCE, self)
        block = re.search(r"DEFAULT_ENTITY_TYPES[^=]*=\s*\[(.*?)\]", text, re.S)
        self.assertIsNotNone(block, "upstream's default list moved or was renamed")
        return re.findall(r'"([A-Z_]+)"', block.group(1))

    def test_upstream_does_not_default_to_LOCATION(self):
        """If this ever fails, upstream changed its mind and the comment in
        `_PRESIDIO_ENTITIES` needs rewriting - not the tuple silently."""
        self.assertNotIn("LOCATION", self.upstream())

    def test_this_platform_does_not_either(self):
        from afni_rai.tenets.privacy import _PRESIDIO_ENTITIES
        self.assertNotIn("LOCATION", _PRESIDIO_ENTITIES)

    def test_every_entity_we_do_enable_is_one_upstream_enables(self):
        """The divergence must run one way only. Enabling something upstream
        does not is the case that needs an argument written down; enabling FEWER
        is just declining an opt-in."""
        from afni_rai.tenets.privacy import _PRESIDIO_ENTITIES
        upstream = set(self.upstream())
        for entity in _PRESIDIO_ENTITIES:
            with self.subTest(entity=entity):
                self.assertIn(entity, upstream)

    def test_the_recognizer_still_supports_it_so_this_is_opt_in_not_absent(self):
        """The distinction the comment rests on: upstream omits LOCATION from a
        DEFAULT, it does not fail to support it."""
        mapping = _LLM_GUARD / "input_scanners" / "anonymize_helpers" / "ner_mapping.py"
        text = _skip_unless(mapping, self)
        self.assertIn("LOCATION", text)

    def test_the_reason_upstream_omits_it_is_still_true(self):
        """Coarse geography folded into the same entity as a street address is
        WHY it is opt-in. If upstream stops folding CITY and STATE into
        LOCATION, the argument for excluding it weakens."""
        mapping = _LLM_GUARD / "input_scanners" / "anonymize_helpers" / "ner_mapping.py"
        text = _skip_unless(mapping, self)
        for coarse in ("CITY", "STATE", "COUNTY", "ZIPCODE"):
            with self.subTest(coarse=coarse):
                self.assertRegex(text, rf'"{coarse}":\s*"LOCATION"')

    def test_the_benign_control_no_longer_trips_a_city_name(self):
        """The measurement that started this. Presidio itself is not installed
        in every environment, so this asserts the CONFIGURATION rather than
        re-running the model: with LOCATION absent, no entity in the list can
        match a bare place name."""
        from afni_rai.tenets.privacy import PRESIDIO_TO_CATEGORY, _PRESIDIO_ENTITIES
        addresses = [e for e in _PRESIDIO_ENTITIES
                     if PRESIDIO_TO_CATEGORY.get(e) == "privacy.pii.address"]
        self.assertEqual(addresses, [],
                         "an entity mapping to privacy.pii.address is enabled, "
                         "so a city name will be redacted again")

    def test_the_mapping_itself_is_kept_for_an_operator_who_opts_in(self):
        """Removing the entity from the default must not remove the ability to
        turn it on - the mapping is the taxonomy's, not ours to drop."""
        from afni_rai.tenets.privacy import PRESIDIO_TO_CATEGORY
        self.assertEqual(PRESIDIO_TO_CATEGORY["LOCATION"], "privacy.pii.address")


class TheEscalationPolarityMatchesUpstreamConsensus(unittest.TestCase):
    """A SURVEY OF ALL 23 VENDORED PROJECTS SETTLED THE DIRECTION OF THIS RULE.

    Every short-circuit in every upstream project fires on a POSITIVE
    DETECTION, and not one of them skips an expensive check because a cheap
    check came back clean:

      llm-guard      `fail_fast` breaks on `not is_valid` only - and defaults
                     to False, so every scanner runs on every prompt
                     (`llm_guard/evaluate.py:49-64`, `:24`).
      openguardrails `short_circuit: true  # stop at first block; skip costlier
                     providers` (`specification/composition.md:32-35`).
      giskard        `AllOf` - "a PASS falls through to the next check; the
                     first failing check stops evaluation"
                     (`checks/builtin/composition.py:61-71`).
      NeMo           rails run in order and a rail stops the chain only by
                     `abort`/`stop` after detecting a violation
                     (`library/jailbreak_detection/flows.v1.co:11-16`).
      guardrails-ai  returns early only for `Refrain`/`Filter`/`ReAsk` - a
                     `PassResult` never stops the chain
                     (`validator_service/sequential_validator_service.py:399`).
      Infosys        the one production stage gate: `status == "FAILED"` skips
                     the LLM tier, `"PASSED"` escalates into it
                     (`responsible-ai-moderationlayer/src/service/service.py:1920`,
                     `:1957`).

    So the rule this platform shipped with - a CLEAN stage ends the cascade -
    was the divergence, and AFNI was right to call it out. These tests pin the
    polarity so it cannot drift back.
    """

    def rails(self, r1, r2):
        from afni_rai.cascade.rail import RailResult, Stage

        class Stub:
            tenet = "Privacy"

            def __init__(self, name, stage, result):
                self.name, self.stage = name, stage
                self._result, self.ran = result, 0

            def check(self, path, text):
                self.ran += 1
                return self._result

        del RailResult  # only imported for the caller's convenience
        return [Stub("cheap", Stage.STAGE_1, r1),
                Stub("expensive", Stage.STAGE_2, r2)]

    def evaluate(self, rails):
        from afni_rai.cascade.engine import Cascade
        from afni_rai.contract.models import EventKind, GuardEvent
        Cascade(rails).evaluate(GuardEvent(
            kind=EventKind.REQUEST, step_id="s", agent_id="a",
            agent_type="chat", agent_workspace="w", agent_user="u",
            llm_protocol="openai.chat",
            payload={"messages": [{"role": "user", "content": "x"}]}))
        return rails

    def test_a_clean_cheap_tier_does_not_skip_the_expensive_one(self):
        """The upstream consensus, in one assertion. `llm_guard/evaluate.py:24`
        - `fail_fast` defaults to False, so upstream's cheap tier coming back
        clean buys you nothing at all."""
        from afni_rai.cascade.rail import RailResult
        rails = self.evaluate(self.rails(RailResult.clean(), RailResult.clean()))
        self.assertEqual(rails[1].ran, 1)

    def test_a_blocking_cheap_tier_does_skip_it(self):
        """The other half, which upstream agrees on unanimously - and which
        AFNI stated in the same words: "if the initial phase itself is saying it
        has blocked then we're happy to block it then and there"."""
        from afni_rai.cascade.rail import Finding, RailResult
        from afni_rai.contract.models import Action, Severity
        block = RailResult(findings=[Finding(
            category="privacy.pii", severity=Severity.CRITICAL,
            action=Action.BLOCK, path="p", detector="stub")])
        rails = self.evaluate(self.rails(block, RailResult.clean()))
        self.assertEqual(rails[1].ran, 0)

    def test_openguardrails_still_specifies_the_same_polarity(self):
        """Read from the vendored spec rather than quoted, so an updated
        reference that changed its mind shows up here."""
        spec = (_REFS / "openguardrails-main" / "openguardrails-main"
                / "specification" / "composition.md")
        text = _skip_unless(spec, self)
        self.assertIn("stop at first block", text)
        self.assertIn("skip costlier providers", text)


class TheTopicRailMatchesUpstreamsContract(unittest.TestCase):

    SOURCE = _LLM_GUARD / "input_scanners" / "ban_topics.py"

    def test_upstream_requires_topics_positionally(self):
        """The fact that makes an empty `ZeroShotTopics()` a porting bug rather
        than a configuration choice: upstream gives no way to construct one
        without topics."""
        text = _skip_unless(self.SOURCE, self)
        signature = re.search(r"def __init__\(\s*self,\s*(.*?)\)\s*->", text, re.S)
        self.assertIsNotNone(signature)
        first = signature.group(1).split(",")[0].strip()
        self.assertTrue(first.startswith("topics"), first)
        self.assertNotIn("=", first,
                         "upstream gained a default topic list; the port should "
                         "follow it rather than keep its own")

    def test_the_mounted_rail_therefore_has_topics(self):
        from afni_rai import cli
        from afni_rai.tenets.content_safety import ZeroShotTopics
        rails, _, _ = cli.load_tenets()
        rail = next(r for r in rails if r.name == ZeroShotTopics.name)
        self.assertTrue(rail.topics)

    def test_the_threshold_matches_the_line_it_cites(self):
        """The docstring in this rail cites upstream's default threshold. Two
        numbers in one repository that are supposed to be the same number."""
        from afni_rai.tenets.content_safety import ZeroShotTopics
        text = _skip_unless(self.SOURCE, self)
        upstream = re.search(r"threshold:\s*float\s*=\s*([\d.]+)", text)
        self.assertIsNotNone(upstream)
        self.assertAlmostEqual(ZeroShotTopics().threshold,
                               float(upstream.group(1)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
