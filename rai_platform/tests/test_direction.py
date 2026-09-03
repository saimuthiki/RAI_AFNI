# -*- coding: utf-8 -*-
"""
Input guardrail vs output guardrail.

The gateway is called twice per interaction:

    user -> [INPUT guardrail] -> AI system -> [OUTPUT guardrail] -> user

Most rails belong on both sides - an SSN is an SSN whichever way it is
travelling. Some are coherent in only one direction, and until the gate existed
they ran in both. Two observable consequences, neither theoretical:

  * `groundedness-nli` reported `unjudged` on every request with no retrieved
    context, stamping COULD NOT JUDGE on nearly all traffic and rendering the
    loudest signal in the product meaningless.
  * `InsecureOutputRail` flagged a support agent ASKING about SQL injection as
    an attack. A test in test_security asserted that false positive as correct
    behaviour until this gate exposed it.

Narrowing a rail REMOVES protection, so the tests here are as much about what
must NOT be narrowed as about what was.

Run: python3 rai_platform/run_tests.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai.cascade.engine import Cascade  # noqa: E402
from afni_rai.cascade.rail import Direction, RailResult, Stage  # noqa: E402
from afni_rai.cli import load_tenets  # noqa: E402
from afni_rai.contract.models import (  # noqa: E402
    Decision, EventKind, GuardEvent, LLMProtocol, Tenet,
)


def request(text):
    return GuardEvent(
        kind=EventKind.REQUEST, step_id="s", agent_id="a", agent_type="chat",
        agent_workspace="afni", agent_user="u",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload={"messages": [{"role": "user", "content": text}]})


def response(text):
    return GuardEvent(
        kind=EventKind.RESPONSE, step_id="s", agent_id="a", agent_type="chat",
        agent_workspace="afni", agent_user="u",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload={"choices": [{"message": {"role": "assistant",
                                          "content": text}}]})


class TestTheEnum(unittest.TestCase):

    def test_both_covers_either_direction(self):
        for kind in (EventKind.REQUEST, EventKind.RESPONSE):
            self.assertTrue(Direction.BOTH.covers(kind))

    def test_input_covers_only_requests(self):
        self.assertTrue(Direction.INPUT.covers(EventKind.REQUEST))
        self.assertFalse(Direction.INPUT.covers(EventKind.RESPONSE))

    def test_output_covers_only_responses(self):
        self.assertTrue(Direction.OUTPUT.covers(EventKind.RESPONSE))
        self.assertFalse(Direction.OUTPUT.covers(EventKind.REQUEST))


class TestTheGate(unittest.TestCase):

    def _rail(self, direction):
        class Probe:
            name = f"probe.{direction.value}"
            tenet = Tenet.SECURITY
            stage = Stage.STAGE_1

            def __init__(self):
                self.calls = []

            def check(inner, path, text):  # noqa: N805 - probe, not a method
                inner.calls.append(path)
                return RailResult.clean()

        probe = Probe()
        probe.direction = direction
        return probe

    def test_an_input_rail_does_not_run_on_a_response(self):
        rail = self._rail(Direction.INPUT)
        Cascade([rail]).evaluate(response("anything"))
        self.assertEqual(rail.calls, [])

    def test_an_output_rail_does_not_run_on_a_request(self):
        rail = self._rail(Direction.OUTPUT)
        Cascade([rail]).evaluate(request("anything"))
        self.assertEqual(rail.calls, [])

    def test_a_both_rail_runs_in_either_direction(self):
        for event in (request("x"), response("x")):
            rail = self._rail(Direction.BOTH)
            Cascade([rail]).evaluate(event)
            self.assertEqual(len(rail.calls), 1)

    def test_a_rail_with_no_direction_attribute_still_runs(self):
        """The safe default. An absent declaration must never silently REMOVE a
        check - that is the difference between a conservative gate and a hole."""
        class Legacy:
            name, tenet, stage = "legacy", Tenet.SECURITY, Stage.STAGE_1

            def __init__(self):
                self.calls = 0

            def check(inner, path, text):  # noqa: N805
                inner.calls += 1
                return RailResult.clean()

        for event in (request("x"), response("x")):
            rail = Legacy()
            Cascade([rail]).evaluate(event)
            self.assertEqual(rail.calls, 1, "a rail with no direction was skipped")

    def test_a_skipped_rail_is_reported_as_skipped_not_as_unjudged(self):
        """The distinction that fixes the false COULD NOT JUDGE. A rail that does
        not apply has not failed to look - there was nothing for it to look at."""
        rail = self._rail(Direction.OUTPUT)
        outcome = Cascade([rail]).evaluate(request("anything"))
        self.assertEqual(outcome.verdict.unjudged, [])
        self.assertIn("probe.output", outcome.trace[0].rails_skipped)
        self.assertNotIn("probe.output", outcome.trace[0].rails_run)

    def test_a_skipped_rail_cannot_cause_a_fail_closed_block(self):
        # A request with only an inapplicable rail mounted must be ALLOWED. If a
        # direction mismatch fed `unjudged`, every request would block on the
        # output rails - a total outage dressed up as caution. This matters more
        # now than it did: fail-closed is unconditional, so there is no switch
        # left to work around a mistake here.
        rail = self._rail(Direction.OUTPUT)
        event = request("perfectly ordinary support question")
        self.assertIs(Cascade([rail]).evaluate(event).verdict.decision,
                      Decision.ALLOW)


class TestTheRealRails(unittest.TestCase):

    def setUp(self):
        self.rails, _, problems = load_tenets()
        self.assertEqual(problems, [])

    def _by_direction(self, direction):
        return sorted(r.name for r in self.rails
                      if getattr(r, "direction", Direction.BOTH) is direction)

    def test_the_output_only_rails_are_exactly_the_ones_intended(self):
        """Pinned as an exact set, because both errors are costly: a rail wrongly
        narrowed loses coverage silently, and a rail wrongly left BOTH generates
        the false positives the gate exists to stop."""
        self.assertEqual(self._by_direction(Direction.OUTPUT), [
            "afni-format-validators",
            "afni-schema-explain",
            "groundedness-nli",
            "package-hallucination",
            "refusal-phrases",
            "security.insecure_output",
            "structured-output-schema",
            "structured-output-wellformed",
        ])

    def test_the_input_only_rails_are_exactly_the_ones_intended(self):
        self.assertEqual(self._by_direction(Direction.INPUT),
                         ["attack-corpus-repeat"])

    def test_the_pii_and_secret_rails_are_never_narrowed(self):
        """The rails that MUST run both ways. An SSN leaving the model is worse
        than one arriving, and a leaked API key is a leak in either direction."""
        must_be_both = {
            "privacy.credit_card", "privacy.healthcare_phi",
            "privacy.pii_entities", "privacy.region_ids",
            "privacy.presidio_ner", "security.secrets",
            "content_safety.profanity", "content_safety.toxicity_model",
        }
        narrowed = must_be_both.intersection(
            self._by_direction(Direction.INPUT) + self._by_direction(Direction.OUTPUT))
        self.assertEqual(narrowed, set(),
                         f"these must run in both directions: {narrowed}")

    # Which tenets have runtime rails on which side. Three are single-direction,
    # and each for a reason that is architecture rather than oversight:
    #
    #   Explainability - both its rails validate the shape of a MODEL's output
    #     against the caller's declared format. A user's prompt carries no such
    #     contract, so there is nothing to validate or explain on the way in.
    #   Hallucination  - hallucination is a property of a GENERATED answer.
    #     A user cannot hallucinate, invent an import, or refuse.
    #   Accountability - its one runtime rail is the confirmed-attack corpus,
    #     which holds PROMPTS. The tenet's real work (audit trail, per-tenant
    #     thresholds, compliance mapping) covers both directions but is
    #     infrastructure rather than a rail, so it does not appear here.
    #
    # Asserted as an exact map so a future accidental narrowing is caught while
    # these three stay documented as deliberate.
    EXPECTED_COVER = {
        "Privacy": {"request", "response"},
        "Security": {"request", "response"},
        "Fairness & Bias": {"request", "response"},
        "Profanity / Content Safety": {"request", "response"},
        "Explainability & Transparency": {"response"},
        "Hallucination / Reliability": {"response"},
        "Accountability": {"request"},
    }

    def test_per_tenet_direction_cover_is_exactly_as_designed(self):
        actual = {}
        for tenet in Tenet:
            sides = set()
            for kind, label in ((EventKind.REQUEST, "request"),
                                (EventKind.RESPONSE, "response")):
                if any(getattr(r, "direction", Direction.BOTH).covers(kind)
                       for r in self.rails if r.tenet is tenet):
                    sides.add(label)
            actual[tenet.value] = sides
        self.assertEqual(actual, self.EXPECTED_COVER)

    def test_no_tenet_has_lost_every_rail(self):
        """Weaker than the map above, and the one that would catch a catastrophe:
        a tenet with rails but none reachable in either direction."""
        for tenet in Tenet:
            mounted = [r for r in self.rails if r.tenet is tenet]
            with self.subTest(tenet=tenet.value):
                self.assertTrue(mounted, f"{tenet.value} has no rails at all")
                reachable = [
                    r for r in mounted
                    if getattr(r, "direction", Direction.BOTH).covers(EventKind.REQUEST)
                    or getattr(r, "direction", Direction.BOTH).covers(EventKind.RESPONSE)]
                self.assertEqual(len(reachable), len(mounted),
                                 f"{tenet.value} has a rail reachable in "
                                 f"NEITHER direction")

    def test_the_four_both_direction_tenets_carry_the_bulk_of_the_cover(self):
        """Sanity on the shape: privacy, security, fairness and content safety
        are the tenets that must guard traffic in both directions, and between
        them they account for most of the mounted rails."""
        both_way_tenets = {Tenet.PRIVACY, Tenet.SECURITY, Tenet.FAIRNESS,
                           Tenet.CONTENT_SAFETY}
        in_both = [r for r in self.rails if r.tenet in both_way_tenets]
        self.assertGreaterEqual(len(in_both), 20,
                                "the both-direction tenets have thinned out")

    def test_no_request_reports_a_false_coverage_gap_from_direction(self):
        """The regression that started this. A benign prompt through every
        mounted rail must report NO unjudged path attributable to direction.

        Stage-2 rails whose weights are absent legitimately report unjudged, so
        this mounts Stage 1 only - where nothing should be unjudged at all."""
        stage_1 = [r for r in self.rails if r.stage is Stage.STAGE_1]
        outcome = Cascade(stage_1).evaluate(
            request("Please summarise the attached invoice for the finance team."))
        self.assertEqual(outcome.verdict.unjudged, [])
        self.assertIs(outcome.verdict.decision, Decision.ALLOW)


class TestSecretsBlockInBothDirections(unittest.TestCase):
    """A leaked credential must block as hard leaving the model as arriving.

    Written because a reviewer reported the opposite: that `security.secrets`
    fired on a prompt and not on a response, which would have been a real hole
    in the direction split. It did not reproduce. The reported string was
    `sk-live-9f2c41ab7d5e0c1874bbaa03e1`, which matches NO pattern in either
    direction - Stripe's live key is `sk_live_` with UNDERSCORES, and OpenAI's
    are `sk-proj-` / `sk-svcacct-` / `sk-admin-` or legacy `sk-` plus 32
    alphanumerics. `sk-live-` with hyphens is a shape no vendor issues.

    So the finding was a false alarm - but a plausible-looking one, and the only
    way to retire that doubt permanently is a test that pins the property
    instead of an argument that it holds.
    """

    KEY = "sk-proj-Xq7SvT2mNbLp9RdKzWyE4HcJ8FgAuQ3T"

    def setUp(self):
        from afni_rai.tenets.security import SecretsRail
        self.rail = SecretsRail()

    def test_the_rail_is_declared_both(self):
        self.assertIs(getattr(self.rail, "direction", Direction.BOTH),
                      Direction.BOTH)

    def test_a_real_key_blocks_as_a_prompt_and_as_a_response(self):
        stage_1 = [r for r in load_tenets()[0] if r.stage is Stage.STAGE_1]
        text = f"the admin credential is {self.KEY}"
        for build, label in ((request, "prompt"), (response, "response")):
            with self.subTest(direction=label):
                outcome = Cascade(stage_1).evaluate(build(text))
                self.assertIs(outcome.verdict.decision, Decision.BLOCK,
                              f"a leaked key did not block as a {label}")
                blocking = [f for f in outcome.verdict.findings
                            if f.detector == "security.secrets"
                            and f.action is not None
                            and f.action.value == "block"]
                self.assertTrue(blocking,
                                f"nothing from security.secrets blocked the "
                                f"{label}")

    def test_the_block_is_the_secrets_rail_and_not_fail_closed(self):
        """The distinction the false report turned on. A block caused by an
        unjudged path looks identical from outside, so assert the finding."""
        stage_1 = [r for r in load_tenets()[0] if r.stage is Stage.STAGE_1]
        outcome = Cascade(stage_1).evaluate(response(f"key: {self.KEY}"))
        self.assertEqual(outcome.verdict.unjudged, [],
                         "this must block on the FINDING, not on a gap")
        self.assertIn("security.secret_leak.api_key",
                      [f.category for f in outcome.verdict.findings])

    def test_a_vendor_shape_nobody_issues_is_not_a_finding_either_way(self):
        """The reported string, pinned as a non-finding in BOTH directions - so
        this cannot be misread as a direction bug again."""
        text = "the admin credential is sk-live-9f2c41ab7d5e0c1874bbaa03e1"
        for build, label in ((request, "prompt"), (response, "response")):
            with self.subTest(direction=label):
                self.assertEqual(self.rail.check("p", text).findings, [],
                                 f"sk-live- matched something as a {label}")


class TestTheRailsEndpointExposesDirection(unittest.TestCase):
    """The console could not tell which rails guard a prompt and which guard a
    response without making a live request and reading `rails_skipped` back out
    of the trace. The engine has gated on direction since the split; the
    endpoint simply did not report it."""

    def setUp(self):
        from afni_rai.gateway.app import Gateway
        self.rows = Gateway().rail_rows()  # `warm` is a create_app kwarg, not a Gateway one

    def test_every_row_carries_a_direction(self):
        for row in self.rows:
            with self.subTest(rail=row["name"]):
                self.assertIn(row["direction"], ("input", "output", "both"))

    def test_the_counts_match_the_mounted_rails(self):
        from collections import Counter

        counts = Counter(row["direction"] for row in self.rows)
        self.assertEqual(counts["output"], 8)
        self.assertEqual(counts["input"], 1)
        self.assertEqual(counts["both"], len(self.rows) - 9)

    def test_it_agrees_with_the_rails_themselves(self):
        rails = {r.name: getattr(r, "direction", Direction.BOTH)
                 for r in load_tenets()[0]}
        for row in self.rows:
            with self.subTest(rail=row["name"]):
                self.assertEqual(row["direction"], rails[row["name"]].value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
