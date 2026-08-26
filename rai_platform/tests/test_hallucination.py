# -*- coding: utf-8 -*-
"""
Tests for the Hallucination / Reliability rails.

Two things are being defended here, and the second one matters as much as the
first. Every Stage-1 rail gets a true positive *and* a true negative, because a
rail that runs on 100% of traffic and fires on ordinary prose is worse than no
rail - the findings get ignored, and then the real ones get ignored too. Several
of the negatives are the exact strings the upstream lists misfire on, kept as
regression tests against a future "let's just use the whole AdvBench list".

Run: python3 rai_platform/run_tests.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai.cascade.engine import Cascade  # noqa: E402
from afni_rai.cascade.rail import Rail, Stage  # noqa: E402
from afni_rai.contract.explanation import CONFIDENCE_KINDS  # noqa: E402
from afni_rai.contract.models import (  # noqa: E402
    Action, Decision, EventKind, LLMProtocol, GuardEvent, Severity, Tenet,
)
from afni_rai.registry.capabilities import CapabilityRegistry, Coverage  # noqa: E402
from afni_rai.tenets import hallucination as H  # noqa: E402


def event(payload=None, client_facing=True):
    return GuardEvent(
        kind=EventKind.RESPONSE,
        step_id="step-1",
        agent_id="agent-1",
        agent_type="chat",
        agent_workspace="afni",
        agent_user="tester",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload=payload if payload is not None else {"output": "hello"},
        client_facing=client_facing,
    )


def categories(result):
    return [f.category for f in result.findings]


# ----------------------------------------------- structured output, stage 1 --
class TestStructuredOutputWellformedness(unittest.TestCase):
    """Ported from Safe Zone validators.go:16/:21 and LLM Guard json.py:35."""

    def setUp(self):
        self.rail = H.StructuredOutputRail()
        self.strict = H.StructuredOutputRail(expect="json")

    # -- true positives --
    def test_trailing_comma_object_is_malformed(self):
        out = self.rail.check("payload.output", 'result: {"a": 1, "b": 2,}')
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.malformed_json"])

    def test_truncated_object_is_malformed(self):
        # A length-capped generation is a real failure mode, and the balanced
        # scan has to notice the payload ran out rather than silently pass.
        out = self.rail.check("payload.output", '{"name": "widget", "price": 1')
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.malformed_json"])

    def test_fenced_json_block_is_validated_even_without_a_quoted_key(self):
        out = self.rail.check("payload.output", "```json\n[1, 2,]\n```")
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.malformed_json"])

    def test_single_quoted_keys_are_not_json(self):
        out = self.rail.check("payload.output", "```json\n{'a': 1}\n```")
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.malformed_json"])

    # -- true negatives --
    def test_prose_with_braces_is_not_flagged(self):
        # LLM Guard's scanner (json.py:77) validates every balanced {...} it
        # finds and would report all three of these as invalid JSON.
        for benign in ("use {placeholder} in the template",
                       "the set {a, b, c} is closed under addition",
                       "f(x) = {x if x > 0}"):
            with self.subTest(benign=benign):
                out = self.rail.check("payload.output", benign)
                self.assertEqual(out.findings, [], benign)

    def test_valid_json_in_prose_is_clean(self):
        out = self.rail.check(
            "payload.output", 'here you go: {"a": 1, "b": [2, 3]} - hope that helps')
        self.assertEqual(out.findings, [])

    def test_empty_and_plain_prose_are_clean(self):
        self.assertEqual(self.rail.check("payload.output", "").findings, [])
        self.assertEqual(
            self.rail.check("payload.output", "The capital is Paris.").findings, [])

    # -- strict mode --
    def test_strict_mode_blocks_a_non_json_payload(self):
        out = self.strict.check("payload.output", "Sure! Here is your JSON.")
        self.assertTrue(out.block)
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.malformed_json"])
        self.assertIs(out.findings[0].action, Action.BLOCK)
        self.assertIs(out.findings[0].severity, Severity.HIGH)

    def test_strict_mode_rejects_an_empty_payload(self):
        # LLM Guard treats an empty output as valid (json.py:73). On a route that
        # contracts for JSON, an empty body is a broken contract.
        out = self.strict.check("payload.output", "   ")
        self.assertTrue(out.block)

    def test_strict_mode_accepts_valid_json(self):
        out = self.strict.check("payload.output", '  {"a": [1, 2, 3]}  ')
        self.assertEqual(out.findings, [])
        self.assertFalse(out.block)

    def test_expect_must_be_a_known_format(self):
        with self.assertRaises(ValueError):
            H.StructuredOutputRail(expect="yaml")


class TestXmlWellformedness(unittest.TestCase):

    def setUp(self):
        self.rail = H.StructuredOutputRail()
        self.strict = H.StructuredOutputRail(expect="xml")

    def test_unclosed_tag_is_malformed(self):
        out = self.rail.check("payload.output", "```xml\n<a><b></a>\n```")
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.malformed_xml"])

    def test_valid_xml_is_clean(self):
        out = self.rail.check("payload.output", "```xml\n<a><b>1</b></a>\n```")
        self.assertEqual(out.findings, [])

    def test_a_dtd_is_reported_and_never_parsed(self):
        # The billion-laughs shape. The guardrail must not be the thing that
        # expands it, so the fragment is refused rather than handed to
        # ElementTree - and it is reported, not silently dropped.
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
                '<!ENTITY lol2 "&lol;&lol;&lol;">]><lolz>&lol2;</lolz>')
        out = self.rail.check("payload.output", bomb)
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.xml_entity_declaration"])

    def test_unfenced_xml_is_only_checked_behind_an_xml_prologue(self):
        # An HTML-ish snippet is not an XML claim; flagging it would be an FP.
        out = self.rail.check("payload.output", "<p>hello <br> world</p>")
        self.assertEqual(out.findings, [])
        out = self.rail.check("payload.output", '<?xml version="1.0"?><a><b></a>')
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.malformed_xml"])

    def test_strict_xml_blocks(self):
        out = self.strict.check("payload.output", "<a><b></a>")
        self.assertTrue(out.block)

    def test_oversized_xml_is_unjudged_not_clean(self):
        rail = H.StructuredOutputRail(expect="xml", max_xml_bytes=64)
        out = rail.check("payload.output", "<a>" + "x" * 200 + "</a>")
        self.assertFalse(out.judged)
        self.assertIn("not parsed", out.reason)


class TestJsonSchemaRail(unittest.TestCase):
    """Safe Zone validators.go:28/:71 - well-formed JSON first, then the schema."""

    SCHEMA = {"type": "object",
              "properties": {"n": {"type": "integer"}},
              "required": ["n"]}

    def setUp(self):
        self.rail = H.JsonSchemaRail(schemas={"payload.output": self.SCHEMA})

    def test_a_path_with_no_schema_has_no_contract_to_violate(self):
        out = self.rail.check("payload.other", "anything at all")
        self.assertTrue(out.judged)
        self.assertEqual(out.findings, [])

    def test_conforming_document_is_clean(self):
        out = self.rail.check("payload.output", '{"n": 7}')
        self.assertEqual(out.findings, [])

    def test_wrong_type_violates_the_schema(self):
        out = self.rail.check("payload.output", '{"n": "seven"}')
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.schema_violation"])
        self.assertTrue(out.block)

    def test_missing_required_property_violates_the_schema(self):
        out = self.rail.check("payload.output", '{"m": 1}')
        self.assertTrue(out.block)

    def test_unparseable_json_under_a_schema_contract_is_a_violation(self):
        out = self.rail.check("payload.output", "not json at all")
        self.assertEqual(categories(out),
                         ["x.afni.structured_output.schema_violation"])
        self.assertTrue(out.block)

    def test_a_broken_schema_is_our_bug_and_reads_as_unjudged(self):
        rail = H.JsonSchemaRail(default_schema={"type": "not-a-type"})
        out = rail.check("payload.output", '{"n": 1}')
        self.assertFalse(out.judged)
        self.assertIn("invalid JSON Schema", out.reason)

    def test_missing_jsonschema_is_unjudged_never_clean(self):
        # The dependency-absent path. Safe Zone's disabled-feature branch
        # (validators.go:72) returns true and skips the check; that is the silent
        # pass this platform exists to refuse.
        rail = H.JsonSchemaRail(default_schema=self.SCHEMA)
        rail._validator = staticmethod(lambda: None)
        out = rail.check("payload.output", '{"n": "seven"}')
        self.assertFalse(out.judged)
        self.assertIn("jsonschema not installed", out.reason)
        self.assertEqual(out.findings, [])


# --------------------------------------------------------- refusal, stage 1 --
class TestRefusalDetection(unittest.TestCase):
    """promptfoo util.ts:136/:155/:305, llm-guard no_refusal.py:110."""

    def setUp(self):
        self.rail = H.RefusalRail()

    # -- true positives --
    def test_prefix_refusals_are_detected(self):
        for text in ("I'm sorry, I can't do that.",
                     "Sorry - that is not something I will do.",
                     "I cannot comply with this request.",
                     "I can't help with that."):
            with self.subTest(text=text):
                out = self.rail.check("payload.output", text)
                self.assertIn("x.afni.refusal.detected", categories(out), text)

    def test_mid_response_refusal_phrases_are_detected(self):
        text = ("Thanks for the detailed question. Unfortunately I cannot provide "
                "instructions for that, and I would rather not speculate.")
        out = self.rail.check("payload.output", text)
        self.assertIn("x.afni.refusal.detected", categories(out))

    def test_curly_apostrophes_do_not_slip_past(self):
        # promptfoo normalises apostrophes at util.ts:132 for exactly this reason.
        out = self.rail.check("payload.output", "I can’t assist with that.")
        self.assertIn("x.afni.refusal.detected", categories(out))

    def test_empty_response_counts_as_a_refusal(self):
        for text in ("", "   ", "{}", "null"):
            with self.subTest(text=text):
                out = self.rail.check("payload.output", text)
                self.assertIn("x.afni.refusal.detected", categories(out), text)

    # -- true negatives: the strings the upstream lists misfire on --
    def test_benign_prose_containing_upstream_tokens_is_not_a_refusal(self):
        for benign in (
            "OpenAI released a new model today, and it scores well.",
            "Hello! Here is the summary you asked for.",
            "I booked it as an Airbnb rather than a hotel.",
            "Downloading pirated films is illegal in most jurisdictions.",
            "I'm an engineer, so I'll walk through the design.",
            "I'm just finishing the migration script now.",
            "Sorting the list first makes the search faster.",
            "The report discusses bias and ethics in hiring models.",
        ):
            with self.subTest(benign=benign):
                out = self.rail.check("payload.output", benign)
                self.assertEqual(out.findings, [], benign)

    def test_every_excluded_marker_has_a_documented_reason(self):
        self.assertTrue(H._EXCLUDED_MARKERS)
        for marker, reason in H._EXCLUDED_MARKERS.items():
            with self.subTest(marker=marker):
                self.assertTrue(reason.strip(), marker)
                self.assertNotIn(marker, H._REFUSAL_PHRASES)

    # -- over-refusal --
    def test_templated_decline_with_no_alternative_is_over_refusal(self):
        text = ("I'm sorry, but I cannot help with that. It is important to "
                "prioritize safety and adhere to ethical guidelines.")
        out = self.rail.check("payload.output", text)
        self.assertEqual(sorted(set(categories(out))),
                         ["x.afni.refusal.detected", "x.afni.refusal.over_refusal"])
        self.assertTrue(out.escalate, "an over-refusal deserves a second opinion")

    def test_a_decline_that_offers_an_alternative_is_not_over_refusal(self):
        text = ("I can't provide the internal credentials, but here is the public "
                "API documentation instead, and you can request scoped access "
                "through the service desk if you need more.")
        out = self.rail.check("payload.output", text)
        self.assertIn("x.afni.refusal.detected", categories(out))
        self.assertNotIn("x.afni.refusal.over_refusal", categories(out))

    def test_a_route_asserted_never_to_refuse_reports_any_refusal_as_over_refusal(self):
        rail = H.RefusalRail(expect_refusal=False)
        text = ("I cannot provide that information. " + "Details follow. " * 60
                + "Instead, consider the alternative below.")
        out = rail.check("payload.output", text)
        self.assertIn("x.afni.refusal.over_refusal", categories(out))

    # -- under-refusal --
    def test_under_refusal_is_opt_in_and_flags_a_missing_mitigation(self):
        # garak's MitigationBypass, inverted at mitigation.py:193: a hit is the
        # ABSENCE of a mitigation message.
        rail = H.RefusalRail(expect_refusal=True)
        out = rail.check("payload.output", "Step 1: acquire the precursor. Step 2: ...")
        self.assertEqual(categories(out), ["x.afni.refusal.under_refusal"])
        self.assertIs(out.findings[0].severity, Severity.HIGH)

    def test_under_refusal_does_not_fire_when_the_model_did_refuse(self):
        rail = H.RefusalRail(expect_refusal=True)
        out = rail.check("payload.output", "I cannot help with that request.")
        self.assertNotIn("x.afni.refusal.under_refusal", categories(out))

    def test_the_default_mount_never_claims_under_refusal(self):
        # One string cannot tell the rail the request was harmful, so the
        # default must not guess.
        out = self.rail.check("payload.output", "Here is the answer: 42.")
        self.assertEqual(out.findings, [])

    # -- path discrimination --
    def test_request_shaped_paths_are_not_judged(self):
        for path in ("payload.messages[0].content", "payload.prompt",
                     "payload.input", "payload.system", "payload.query"):
            with self.subTest(path=path):
                out = self.rail.check(path, "I'm sorry, could you re-send that?")
                self.assertEqual(out.findings, [], path)

    def test_response_shaped_paths_are_judged(self):
        for path in ("payload.output", "payload.choices[0].message.content",
                     "payload.completion", "payload.text"):
            with self.subTest(path=path):
                out = self.rail.check(path, "I cannot assist with that.")
                self.assertIn("x.afni.refusal.detected", categories(out), path)

    def test_unrelated_payload_strings_are_left_alone(self):
        out = self.rail.check("payload.metadata.tag", "")
        self.assertEqual(out.findings, [])

    def test_a_refusal_never_blocks(self):
        out = self.rail.check("payload.output", "I'm sorry, I cannot do that.")
        self.assertFalse(out.block)
        self.assertNotIn(Action.BLOCK, [f.action for f in out.findings])


# --------------------------------------------- package hallucination, stage 1 --
class TestPackageHallucination(unittest.TestCase):
    """garak packagehallucination.py:141/:156/:158, PyRIT port :77/:134/:186."""

    def setUp(self):
        self.rail = H.PackageHallucinationRail()

    # -- true positives --
    def test_an_unresolvable_import_is_flagged(self):
        code = "import os\nimport quantum_flux_helper\nfrom json import loads\n"
        out = self.rail.check("payload.output", code)
        self.assertEqual(categories(out),
                         ["security.supply_chain.hallucinated_package"])
        self.assertEqual(out.findings[0].subject, "quantum_flux_helper")

    def test_from_imports_are_extracted_too(self):
        out = self.rail.check("payload.output", "from notarealpkg import thing\n")
        self.assertEqual(len(out.findings), 1)
        self.assertEqual(out.findings[0].subject, "notarealpkg")

    # -- true negatives --
    def test_stdlib_imports_are_provably_fine(self):
        code = ("import os\nimport sys\nimport json\nimport re\n"
                "import hashlib\nfrom collections import OrderedDict\n"
                "import os.path\n")
        out = self.rail.check("payload.output", code)
        self.assertEqual(out.findings, [], "a stdlib import was called hallucinated")

    def test_prose_is_not_mined_for_packages(self):
        for benign in ("Please import the CSV into the sheet.",
                       "The team will require sign-off from legal.",
                       "We can use requests from the client."):
            with self.subTest(benign=benign):
                out = self.rail.check("payload.output", benign)
                self.assertEqual(out.findings, [], benign)

    def test_an_allowlisted_package_is_not_flagged(self):
        rail = H.PackageHallucinationRail(allowlist=("afni_internal_sdk",))
        out = rail.check("payload.output", "import afni_internal_sdk\n")
        self.assertEqual(out.findings, [])

    # -- confidence is not faked --
    def test_environment_registry_findings_carry_no_score(self):
        # "Does not resolve here" is not "does not exist". There is no honest
        # number for that, so there is no number.
        out = self.rail.check("payload.output", "import quantum_flux_helper\n")
        self.assertIsNone(out.findings[0].score)
        self.assertIs(out.findings[0].severity, Severity.LOW)

    def test_an_injected_registry_upgrades_the_claim(self):
        rail = H.PackageHallucinationRail(
            known_packages={"python": {"requests", "numpy"}},
            use_environment_registry=False)
        out = rail.check("payload.output", "import requests\nimport quantum_flux\n")
        self.assertEqual(len(out.findings), 1)
        self.assertEqual(out.findings[0].subject, "quantum_flux")
        self.assertEqual(out.findings[0].score, 1.0)
        self.assertIs(out.findings[0].severity, Severity.MEDIUM)

    def test_an_ecosystem_with_no_registry_is_unjudged_not_clean(self):
        rail = H.PackageHallucinationRail(ecosystems=("ruby",))
        out = rail.check("payload.output", "require 'nokogiri'\n")
        self.assertFalse(out.judged)
        self.assertIn("no ruby package registry", out.reason)

    def test_a_ruby_registry_makes_the_ecosystem_judgeable(self):
        rail = H.PackageHallucinationRail(
            ecosystems=("ruby",), known_packages={"ruby": {"nokogiri"}})
        self.assertEqual(rail.check("payload.output", "require 'nokogiri'\n").findings, [])
        out = rail.check("payload.output", "require 'notagem'\n")
        self.assertEqual(len(out.findings), 1)

    def test_an_unknown_ecosystem_is_a_configuration_error(self):
        with self.assertRaises(ValueError):
            H.PackageHallucinationRail(ecosystems=("cobol",))

    def test_findings_are_capped_so_one_reply_cannot_flood_the_verdict(self):
        code = "".join(f"import fakepkg_{i}\n" for i in range(50))
        rail = H.PackageHallucinationRail(max_findings=5)
        self.assertLessEqual(len(rail.check("payload.output", code).findings), 5)


# ------------------------------------------------------ groundedness, stage 2 --
class TestNliGroundedness(unittest.TestCase):
    """llm-guard factual_consistency.py:56, threshold 0.75, ban_topics.py:32."""

    SOURCE = "The invoice total is 412 EUR and it was paid on 3 March."

    def test_missing_dependency_is_unjudged_never_clean(self):
        if H.nli_backend_available():  # pragma: no cover - provisioned machine
            self.skipTest("transformers/torch and the weights are present; the "
                          "degrade path cannot be exercised here")
        rail = H.NliGroundednessRail(context=self.SOURCE)
        out = rail.check("payload.output", "The invoice total is 9000 EUR.")
        self.assertFalse(out.judged)
        self.assertEqual(out.findings, [])
        self.assertIn("MoritzLaurer/deberta-v3-base-zeroshot-v2.0", out.reason)

    def test_with_the_backend_present_it_returns_a_judgement(self):
        """The complementary half. Between this and the test above, one always
        runs - so neither a bare box nor a provisioned one leaves the rail's
        behaviour unasserted."""
        if not H.nli_backend_available():
            self.skipTest("no NLI backend on this machine")
        rail = H.NliGroundednessRail(context=self.SOURCE)
        out = rail.check("payload.output", "The invoice total is 9000 EUR.")
        self.assertTrue(out.judged,
                        f"backend is present but the rail still cannot look: "
                        f"{out.reason}")

    def test_the_model_id_and_revision_are_pinned(self):
        self.assertEqual(H.NliGroundednessRail.MODEL_ID,
                         "MoritzLaurer/deberta-v3-base-zeroshot-v2.0")
        self.assertEqual(H.NliGroundednessRail.MODEL_REVISION,
                         "8e7e5af5983a0ddb1a5b45a38b129ab69e2258e8")
        self.assertEqual(H.NliGroundednessRail.LABELS,
                         ("entailment", "not_entailment"))

    def test_no_grounding_source_is_not_applicable_and_not_a_pass(self):
        """Three states, not two, and this is the third.

        With no retrieved source there is nothing to be grounded in, so the rail
        has neither found the output clean nor failed to assess it. It declines.

        This used to report `unjudged`, which stamped COULD NOT JUDGE on every
        request carrying no RAG context - most of them - and a fail-loud warning
        that fires on all traffic conveys nothing. But it must not read as
        `clean` either: that asserts "I looked and found nothing", which a rail
        with no input to compare against has not earned.
        """
        rail = H.NliGroundednessRail(entailment_scorer=lambda s, o: 0.99)
        out = rail.check("payload.output", "The invoice total is 412 EUR.")
        self.assertTrue(out.judged, "a declined check must not fail closed")
        self.assertTrue(out.inapplicable, "the decline must be recorded as such")
        self.assertEqual(out.findings, [])
        self.assertIn("groundedness is a relation", out.reason)

    def test_declining_is_distinguishable_from_finding_nothing(self):
        """The two must not be the same object, or the trace cannot tell an
        operator which happened."""
        from afni_rai.cascade.rail import RailResult

        declined = H.NliGroundednessRail(
            entailment_scorer=lambda s, o: 0.99).check("payload.output", "x")
        looked = H.NliGroundednessRail(
            context=self.SOURCE,
            entailment_scorer=lambda s, o: 0.99).check("payload.output", "x")
        self.assertTrue(declined.inapplicable)
        self.assertFalse(looked.inapplicable)
        self.assertNotEqual(declined, RailResult.clean())
        self.assertEqual(looked, RailResult.clean())

    def test_entailed_output_is_clean(self):
        rail = H.NliGroundednessRail(context=self.SOURCE,
                                    entailment_scorer=lambda s, o: 0.91)
        out = rail.check("payload.output", "The invoice was 412 EUR.")
        self.assertTrue(out.judged)
        self.assertEqual(out.findings, [])

    def test_unsupported_output_is_flagged_with_the_not_entailment_score(self):
        rail = H.NliGroundednessRail(context=self.SOURCE,
                                    entailment_scorer=lambda s, o: 0.20)
        out = rail.check("payload.output", "The invoice total is 9000 EUR.")
        self.assertEqual(categories(out), ["safety.hallucination"])
        self.assertAlmostEqual(out.findings[0].score, 0.80, places=2)
        self.assertIs(out.findings[0].severity, Severity.HIGH)
        self.assertTrue(out.escalate)

    def test_a_borderline_score_is_medium_not_high(self):
        rail = H.NliGroundednessRail(context=self.SOURCE,
                                    entailment_scorer=lambda s, o: 0.60)
        out = rail.check("payload.output", "The invoice total was about 400 EUR.")
        self.assertIs(out.findings[0].severity, Severity.MEDIUM)

    def test_a_failing_backend_is_unjudged(self):
        def boom(source, output):
            raise RuntimeError("cuda oom")

        rail = H.NliGroundednessRail(context=self.SOURCE, entailment_scorer=boom)
        out = rail.check("payload.output", "anything")
        self.assertFalse(out.judged)
        self.assertIn("cuda oom", out.reason)

    def test_a_context_provider_is_consulted_per_path(self):
        seen = []

        def provider(path):
            seen.append(path)
            return self.SOURCE if path == "payload.output" else None

        rail = H.NliGroundednessRail(context_provider=provider,
                                    entailment_scorer=lambda s, o: 0.10)
        self.assertEqual(categories(rail.check("payload.output", "x")),
                         ["safety.hallucination"])
        # A path the provider has no source for is DECLINED, not failed - see
        # test_no_grounding_source_is_not_applicable_and_not_a_pass.
        other = rail.check("payload.other", "x")
        self.assertTrue(other.judged)
        self.assertTrue(other.inapplicable)
        self.assertEqual(seen, ["payload.output", "payload.other"])

    def test_threshold_bounds_are_validated(self):
        with self.assertRaises(ValueError):
            H.NliGroundednessRail(minimum_score=0.0)
        with self.assertRaises(ValueError):
            H.NliGroundednessRail(minimum_score=1.5)


# ------------------------------------------------------------- the contract --
class TestFindingHygiene(unittest.TestCase):
    """Upstream forbids per-span echoes of matched text, and a fingerprint is a
    hash of the subject rather than the subject."""

    CASES = [
        (H.StructuredOutputRail(), "payload.output", '{"a": 1,}'),
        (H.StructuredOutputRail(expect="json"), "payload.output", "nope"),
        (H.RefusalRail(), "payload.output",
         "I'm sorry, I cannot help. It is important to prioritize safety."),
        (H.RefusalRail(expect_refusal=True), "payload.output", "Step 1: do it."),
        (H.PackageHallucinationRail(), "payload.output", "import quantum_flux_helper\n"),
        (H.JsonSchemaRail(default_schema={"type": "object",
                                          "required": ["n"]}),
         "payload.output", '{"m": 1}'),
        (H.NliGroundednessRail(context="a source sentence",
                              entailment_scorer=lambda s, o: 0.1),
         "payload.output", "an unsupported claim"),
    ]

    def test_every_rail_emits_at_least_one_finding_for_its_positive_case(self):
        for rail, path, text in self.CASES:
            with self.subTest(rail=rail.name):
                self.assertTrue(rail.check(path, text).findings, rail.name)

    def test_fp_is_a_sha256_prefix_of_the_subject(self):
        import hashlib
        for rail, path, text in self.CASES:
            for finding in rail.check(path, text).findings:
                if finding.subject is None:
                    self.assertIsNone(finding.fp, rail.name)
                    continue
                with self.subTest(rail=rail.name, category=finding.category):
                    expected = hashlib.sha256(
                        finding.subject.encode("utf-8")).hexdigest()[:16]
                    self.assertEqual(finding.fp, expected)
                    self.assertNotEqual(finding.fp, finding.subject)

    def test_the_payload_is_never_echoed_into_a_finding(self):
        secret = "quantum_flux_helper"
        payload = f'import {secret}\n{{"a": 1,}}\n'
        for rail in (H.StructuredOutputRail(), H.RefusalRail()):
            for finding in rail.check("payload.output", payload).findings:
                with self.subTest(rail=rail.name):
                    self.assertNotIn(secret, str(finding.to_dict()))

    def test_every_category_is_a_valid_taxonomy_path(self):
        # Finding.__post_init__ enforces the pattern, so producing one at all is
        # the assertion; this pins the taxonomy choices themselves.
        emitted = set()
        for rail, path, text in self.CASES:
            emitted.update(f.category for f in rail.check(path, text).findings)
        self.assertEqual(emitted, {
            "x.afni.structured_output.malformed_json",
            "x.afni.structured_output.schema_violation",
            "x.afni.refusal.detected",
            "x.afni.refusal.over_refusal",
            "x.afni.refusal.under_refusal",
            "security.supply_chain.hallucinated_package",
            "safety.hallucination",
        })

    def test_every_finding_names_its_detector(self):
        for rail, path, text in self.CASES:
            for finding in rail.check(path, text).findings:
                with self.subTest(rail=rail.name):
                    self.assertEqual(finding.detector, rail.name)


# ---------------------------------------------------------- rails and stages --
class TestRailsAndStages(unittest.TestCase):

    def test_every_rail_satisfies_the_protocol(self):
        for rail in H.RAILS:
            with self.subTest(rail=rail.name):
                self.assertIsInstance(rail, Rail)
                self.assertIs(rail.tenet, Tenet.HALLUCINATION)

    def test_no_offline_rail_is_exported_for_mounting(self):
        # The Cascade constructor raises on an OFFLINE rail; RAILS must never
        # contain one in the first place.
        for rail in H.RAILS:
            self.assertIsNot(rail.stage, Stage.OFFLINE, rail.name)
        Cascade(H.RAILS)

    def test_stage_1_rails_import_nothing_third_party(self):
        # The whole point of Stage 1: it works before anyone installs torch.
        # These three run here, in this interpreter, with stdlib only.
        stage_1 = [r for r in H.RAILS if r.stage is Stage.STAGE_1]
        self.assertEqual({r.name for r in stage_1},
                         {"structured-output-wellformed", "refusal-phrases",
                          "package-hallucination"})
        for rail in stage_1:
            with self.subTest(rail=rail.name):
                self.assertTrue(rail.check("payload.output", "plain text").judged)

    def test_names_are_unique(self):
        names = [r.name for r in H.RAILS]
        self.assertEqual(len(names), len(set(names)))

    def test_a_clean_response_produces_an_allow_on_internal_traffic(self):
        # Stage 2 reports unjudged (no weights), so client-facing traffic is
        # blocked by design. Internal traffic is allowed and the gap is still
        # on the record - that is the fail-loud contract, not a bug.
        out = Cascade(H.RAILS).evaluate(
            event({"output": "The capital of France is Paris."}, client_facing=False))
        self.assertIs(out.verdict.decision, Decision.ALLOW)

    def test_a_malformed_structured_response_reaches_the_verdict(self):
        out = Cascade(H.RAILS).evaluate(
            event({"output": 'here: {"a": 1,}'}, client_facing=False))
        self.assertIn("x.afni.structured_output.malformed_json",
                      [f.category for f in out.verdict.findings])


class TestAttributions(unittest.TestCase):

    def test_every_rail_has_an_attribution_with_real_evidence(self):
        self.assertEqual(set(H.ATTRIBUTIONS), {r.name for r in H.RAILS})
        for name, attribution in H.ATTRIBUTIONS.items():
            with self.subTest(rail=name):
                self.assertIn(attribution.confidence_kind, CONFIDENCE_KINDS)
                self.assertIsNotNone(attribution.capability)
                # Evidence must be a citation, not a sentence of prose.
                self.assertRegex(attribution.evidence, r"[\w/.\-]+\.(?:go|py|ts):\d+")

    def test_the_stage_in_an_attribution_matches_the_rail(self):
        by_name = {r.name: r for r in H.RAILS}
        for name, attribution in H.ATTRIBUTIONS.items():
            with self.subTest(rail=name):
                self.assertEqual(attribution.stage, int(by_name[name].stage))

    def test_deterministic_rails_do_not_claim_a_model_confidence(self):
        for name, attribution in H.ATTRIBUTIONS.items():
            with self.subTest(rail=name):
                expected = ("entailment" if name == "groundedness-nli"
                            else "deterministic")
                self.assertEqual(attribution.confidence_kind, expected)


# ------------------------------------------------------------------ registry --
class TestRegistration(unittest.TestCase):

    def setUp(self):
        self.registry = CapabilityRegistry()
        H.register(self.registry)
        self.report = self.registry.report()
        self.rows = self.report.by_tenet[Tenet.HALLUCINATION]

    def test_every_capability_of_the_tenet_is_accounted_for(self):
        names = self.registry.names(Tenet.HALLUCINATION)
        self.assertEqual(len(names), 10)
        self.assertEqual([r.capability for r in self.rows], names)

    def test_the_counts_add_up(self):
        counts = self.report.counts(Tenet.HALLUCINATION)
        self.assertEqual(sum(counts.values()), 10)
        # The NLI capability moves between IMPLEMENTED and DEPENDENCY with its
        # weights, so those two are asserted as a sum. Pinning the unprovisioned
        # numbers turned this red the moment the models were installed - which is
        # the documented next step, not an unusual state.
        self.assertEqual(counts[Coverage.IMPLEMENTED] + counts[Coverage.DEPENDENCY], 4)
        self.assertGreaterEqual(counts[Coverage.IMPLEMENTED], 3)
        self.assertEqual(counts[Coverage.CLOUD], 1)
        self.assertEqual(counts[Coverage.OFFLINE], 4)
        self.assertEqual(counts[Coverage.GAP], 1)

    def test_only_the_stage_1_rails_and_a_provisioned_nli_are_implemented(self):
        implemented = {r.capability for r in self.rows
                       if r.status is Coverage.IMPLEMENTED}
        stdlib = {H.CAP_STRUCTURED, H.CAP_REFUSAL, H.CAP_PACKAGE}
        self.assertTrue(stdlib <= implemented,
                        f"stdlib capabilities not implemented: {stdlib - implemented}")
        # Only the NLI capability may join them, and only with its weights there.
        extra = implemented - stdlib
        self.assertTrue(extra <= {H.CAP_NLI},
                        f"unexpected IMPLEMENTED capabilities: {extra}")
        if extra:
            self.assertTrue(H.nli_backend_available(),
                            "NLI is claimed IMPLEMENTED with no backend present")

    def test_the_nli_rail_is_dependency_missing_not_implemented(self):
        # It has a rail and it reports unjudged today. Claiming IMPLEMENTED
        # would be the exact overstatement the five-valued status exists to stop.
        row = next(r for r in self.rows if r.capability == H.CAP_NLI)
        expected = (Coverage.IMPLEMENTED if H.nli_backend_available()
                    else Coverage.DEPENDENCY)
        self.assertIs(row.status, expected)
        self.assertIsNotNone(row.attribution)

    def test_no_capability_is_claimed_by_an_offline_or_absent_rail(self):
        for row in self.rows:
            with self.subTest(capability=row.capability):
                if row.status is Coverage.IMPLEMENTED:
                    self.assertIsNotNone(row.attribution)
                    self.assertLess(row.attribution.stage, int(Stage.OFFLINE))
                if row.status in (Coverage.OFFLINE, Coverage.CLOUD, Coverage.GAP):
                    # No rail may be attributed to a capability we do not run.
                    self.assertIsNone(row.attribution, row.capability)

    def test_every_row_carries_a_note_explaining_its_state(self):
        for row in self.rows:
            with self.subTest(capability=row.capability):
                self.assertTrue(row.note.strip(), row.capability)

    def test_offline_notes_name_the_tool_that_does_the_work_in_ci(self):
        expected = {H.CAP_RAG: "DeepEval", H.CAP_REGRESSION: "romptfoo",
                    H.CAP_TRUTHFULNESS: "DeepEval", H.CAP_FABRICATION: "DeepTeam"}
        for row in self.rows:
            if row.capability in expected:
                with self.subTest(capability=row.capability):
                    self.assertIs(row.status, Coverage.OFFLINE)
                    self.assertIn(expected[row.capability], row.note)

    def test_registering_twice_is_idempotent(self):
        H.register(self.registry)
        self.assertEqual(sum(self.registry.report()
                             .counts(Tenet.HALLUCINATION).values()), 10)

    def test_a_forgotten_capability_fails_loudly(self):
        class Trap(CapabilityRegistry):
            def names(self, tenet):
                return super().names(tenet) + ["Some new capability"]

        with self.assertRaises(RuntimeError):
            H.register(Trap())

    def test_a_typo_in_a_capability_name_is_an_error_not_a_silent_gap(self):
        with self.assertRaises(KeyError):
            self.registry.register(Tenet.HALLUCINATION,
                                   "Groundedness (NLI entailment)",
                                   Coverage.IMPLEMENTED)

    def test_this_tenet_does_not_touch_another_tenets_rows(self):
        for tenet, rows in self.report.by_tenet.items():
            if tenet is Tenet.HALLUCINATION:
                continue
            with self.subTest(tenet=tenet.value):
                self.assertTrue(all(r.status is Coverage.GAP for r in rows))

    def test_the_report_renders(self):
        text = self.report.render()
        self.assertIn("Hallucination / Reliability", text)
        self.assertIn("Dedicated hallucination models", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
