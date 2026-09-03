# -*- coding: utf-8 -*-
"""
Tests for the Fairness & Bias tenet.

The invariants under test are unusual for this platform, because the tenet is
unusual: most of what has to hold is about what this package REFUSES to claim.
Eleven of the thirteen reviewed tools cannot run inline at all, so the tests
below check three families of thing:

  honesty     no capability is registered IMPLEMENTED that is not, the Stage 1
              rail never blocks and never carries a score, and the rail that
              maps to no capability row is registered against nothing.
  discipline  a protected-attribute detector is a false-positive machine unless
              it is anchored. `test_no_false_positive_storm` is the real test in
              this file: fifteen benign strings, zero findings.
  arithmetic  the stdlib port of Fairlearn's two disparity differences produces
              hand-checkable numbers, and reports `None` rather than 0.0 for an
              undefined rate.

Run: python3 rai_platform/run_tests.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai.cascade.engine import Cascade  # noqa: E402
from afni_rai.cascade.rail import Rail, RailResult, Stage  # noqa: E402
from afni_rai.contract.models import (  # noqa: E402
    Action, Decision, EventKind, GuardEvent, LLMProtocol, Severity, Tenet,
)
from afni_rai.registry.capabilities import CapabilityRegistry, Coverage  # noqa: E402
from afni_rai.tenets import fairness  # noqa: E402
from afni_rai.tenets.fairness import (  # noqa: E402
    AXES, BATCH_JOBS, CATEGORIES, CLOUD_RAILS, OFFLINE_JOB_SPECS, RAILS,
    BatchDataset, BatchReport, FairnessBatchJob, GenerativeBiasJudgeRail,
    GroupFairnessMetricsJob, LocalBiasClassifierRail,
    ProtectedAttributeReferenceRail, demographic_parity_difference, difference,
    equalized_odds_difference, false_positive_rate, job_for, selection_rate,
    true_positive_rate,
)

_CATEGORY_RE = re.compile(r"^(safety|security|privacy|x)(\.[a-z0-9_]+)+$")


def event(payload=None):
    return GuardEvent(
        kind=EventKind.REQUEST,
        step_id="step-1",
        agent_id="agent-1",
        agent_type="chat",
        agent_workspace="afni",
        agent_user="tester",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload=payload if payload is not None else {"text": "hello"},
    )


def fake_pipeline(label, score):
    """Stand-in for a transformers text-classification pipeline, so the Stage 2
    adapter's scoring arithmetic can be tested without torch."""
    return lambda _factory=None: (lambda text: [{"label": label, "score": score}])


# ============================================================ Stage 1 rail ==
class TestProtectedAttributeRail(unittest.TestCase):

    def setUp(self):
        self.rail = ProtectedAttributeReferenceRail()

    def test_conforms_to_the_rail_protocol(self):
        self.assertIsInstance(self.rail, Rail)
        self.assertIs(self.rail.stage, Stage.STAGE_1)
        self.assertIs(self.rail.tenet, Tenet.FAIRNESS)

    def test_true_positives_across_every_axis(self):
        # One case per axis, each with a decision term present. The axes are
        # BBQ's eleven (deepeval/benchmarks/bbq/task.py:5-15) plus the two
        # statutory ones, so every axis this rail declares must actually fire.
        cases = {
            "race_ethnicity": "The Hispanic applicant was denied a mortgage.",
            "gender": "Approve the loan only for male borrowers.",
            "age": "Do not hire the elderly candidate for this role.",
            "disability": "The claim was rejected because of her disability.",
            "religion": "Scholarship eligibility is limited to Christian students.",
            "national_origin": "Reject the application due to the applicant's "
                               "national origin.",
            "sexual_orientation": "We declined to promote the gay employee.",
            "socioeconomic": "Deny bail based on the defendant's zip code.",
            "physical_appearance": "Screen out obese candidates before the interview.",
            "pregnancy": "We denied her mortgage because she is pregnant.",
            "veteran_status": "Do not promote veterans into client-facing roles.",
        }
        declared = {axis.name for axis in AXES}
        self.assertEqual(declared, set(cases),
                         "an axis is declared but untested, or vice versa")
        for axis, text in cases.items():
            with self.subTest(axis=axis):
                result = self.rail.check("payload.text", text)
                self.assertTrue(result.findings, f"{axis} did not fire")
                self.assertIn(axis, self.rail.axes_for(text))

    def test_no_false_positive_storm(self):
        # The whole rail lives or dies here. A protected-attribute detector that
        # fires on ordinary BPO traffic would be turned off within a week, and
        # then it protects nothing.
        benign = [
            "What is the weather in Boston today?",
            "Please approve the invoice for the vendor by Friday.",
            # promptfoo's own false-positive instruction: "Discussing diversity
            # and inclusion initiatives is typically appropriate"
            # (src/redteam/plugins/bias.ts:66-69).
            "Our diversity and inclusion training covers race and gender awareness.",
            "The customer's date of birth is on file.",
            # Ambiguous colour words with no person anchor nearby.
            "Approve the white paper before the board meeting.",
            "The black box test harness was rejected by CI.",
            "The zip file was rejected by the upload validator.",
            "Ship the parcel to the postal code on the label.",
            "Our old server rack was decommissioned and the new tier approved.",
            "We hired three engineers last quarter.",
            "The loan was approved after the credit check cleared.",
            "Reset the user's password and confirm the ticket.",
            "Interest rate changes are announced quarterly by the central bank.",
            "The premium plan tier was approved for launch next month.",
            "Please rank these support tickets by priority.",
        ]
        for text in benign:
            with self.subTest(text=text):
                self.assertEqual(self.rail.check("payload.text", text).findings, [],
                                 "false positive on benign traffic")

    def test_attribute_without_a_decision_is_silent(self):
        # Guard (1). Mentioning a protected class is not a governance signal;
        # conditioning an outcome on one is.
        for text in ("She is pregnant and doing well.",
                     "Our workforce includes veterans and people of color.",
                     "The patient is blind in one eye."):
            with self.subTest(text=text):
                self.assertEqual(self.rail.check("payload.text", text).findings, [])

    def test_decision_without_an_attribute_is_silent(self):
        for text in ("Approve the loan and notify underwriting.",
                     "The candidate was shortlisted for interview.",
                     "Deny the claim; the policy lapsed."):
            with self.subTest(text=text):
                self.assertEqual(self.rail.check("payload.text", text).findings, [])

    def test_ambiguous_terms_need_a_person_anchor(self):
        # Guard (2). Same decision verb, same ambiguous token; only the one
        # about a person fires.
        self.assertEqual(
            self.rail.check("p", "Approve the white paper for the board.").findings, [])
        self.assertTrue(
            self.rail.check("p", "Approve the white applicant, reject the "
                                 "others.").findings)

    def test_stated_causation_raises_severity_to_medium(self):
        # Guard (3). Adjacency is weaker evidence than a stated because-clause,
        # and the finding must say which it saw.
        low = self.rail.check("p", "Approve the loan for pregnant customers.")
        med = self.rail.check("p", "Deny the loan because the customer is pregnant.")
        self.assertEqual([f.severity for f in low.findings], [Severity.LOW])
        self.assertEqual([f.severity for f in med.findings], [Severity.MEDIUM])

    def test_multi_word_phrases_actually_match(self):
        # Regression guard. The phrase-alternation builder previously chained two
        # str.replace calls whose replacement text contained the second pattern,
        # which silently killed EVERY multi-word term and the whole connective
        # list while leaving single words working - so the rail looked fine.
        for text, subject in (
                ("Deny bail based on the defendant's zip code.", "zip code"),
                ("Do not admit non-white students.", "non-white"),
                ("Reject the application due to national origin.", "national origin"),
                ("The African American borrower was denied credit.",
                 "African American")):
            with self.subTest(text=text):
                subjects = [f.subject for f in
                            self.rail.check("p", text).findings]
                self.assertIn(subject, subjects)

    def test_connective_phrases_actually_match(self):
        for text in ("Deny the loan on the grounds of the customer's disability.",
                     "Reject him due to his age.",
                     "Approve her based on gender."):
            with self.subTest(text=text):
                findings = self.rail.check("p", text).findings
                self.assertTrue(findings)
                self.assertEqual(findings[0].severity, Severity.MEDIUM, text)

    def test_a_phrase_match_does_not_also_report_its_ambiguous_substring(self):
        findings = self.rail.check(
            "p", "The African American borrower was denied credit.").findings
        self.assertEqual([f.subject for f in findings], ["African American"])

    def test_it_never_blocks_and_never_scores(self):
        # Both are structural. This rail does not measure bias, so it has no
        # score to report, and blocking on a protected-class mention would be a
        # fabricated fairness claim.
        result = self.rail.check("p", "Deny the loan because she is pregnant.")
        self.assertFalse(result.block)
        for finding in result.findings:
            self.assertIs(finding.action, Action.FLAG)
            self.assertIsNone(finding.score)

    def test_it_does_not_escalate_by_default(self):
        # The load-bearing default: escalating would turn a flag into a hard
        # BLOCK on any box where the Stage 2 weights are absent, via the
        # engine's fail-closed rule.
        self.assertFalse(self.rail.check(
            "p", "Deny the loan because she is pregnant.").escalate)
        opted_in = ProtectedAttributeReferenceRail(escalate_on_hit=True)
        self.assertTrue(opted_in.check(
            "p", "Deny the loan because she is pregnant.").escalate)

    def test_matched_text_appears_only_in_subject(self):
        # Upstream forbids per-span echoes of matched text; `subject` is the one
        # permitted place, and `fp` must be a hash of it, never the value.
        import hashlib
        result = self.rail.check("payload.text",
                                 "Deny the loan because she is pregnant.")
        finding = result.findings[0]
        self.assertEqual(finding.subject, "pregnant")
        self.assertEqual(
            finding.fp,
            hashlib.sha256(b"pregnant").hexdigest()[:16])
        payload = finding.to_dict()
        payload.pop("subject")
        self.assertNotIn("pregnant", repr(payload).lower())

    def test_spans_point_at_the_matched_term(self):
        text = "Deny the loan because she is pregnant."
        finding = self.rail.check("payload.text", text).findings[0]
        self.assertEqual(text[finding.start:finding.end], "pregnant")

    def test_findings_are_capped_per_path(self):
        text = ("Deny the loan because the pregnant black female disabled "
                "elderly muslim immigrant gay obese veteran applicant asked. ")
        self.assertLessEqual(len(self.rail.check("p", text * 5).findings), 8)

    def test_empty_and_whitespace_are_judged_clean(self):
        for text in ("", "   ", "\n\t"):
            result = self.rail.check("p", text)
            self.assertTrue(result.judged)
            self.assertEqual(result.findings, [])

    def test_mounted_in_a_cascade_it_flags_without_blocking(self):
        out = Cascade([self.rail]).evaluate(
            event({"text": "Deny the loan because she is pregnant."}))
        self.assertIs(out.verdict.decision, Decision.ALLOW,
                      "a protected-attribute reference must never block")
        self.assertTrue(out.verdict.findings)
        self.assertFalse(out.verdict.could_not_judge)


# ============================================================ Stage 2 rail ==
class TestLocalBiasClassifierRail(unittest.TestCase):

    def test_returns_unjudged_when_the_dependency_is_absent(self):
        # The core fail-loud contract: a missing model is "could not look",
        # never "found nothing".
        rail = LocalBiasClassifierRail()
        if rail.dependency_available():
            self.skipTest("transformers/torch installed; absent-path not exercisable")
        result = rail.check("payload.text", "Older employees struggle with tech.")
        self.assertFalse(result.judged)
        self.assertEqual(result.findings, [])
        self.assertIn("llm_guard.bias", result.reason)

    def test_unjudged_fails_closed(self):
        rail = LocalBiasClassifierRail()
        if rail.dependency_available():
            self.skipTest("transformers/torch installed")
        # Stage 1 asks for escalation so Stage 2 is actually reached.
        stage1 = ProtectedAttributeReferenceRail(escalate_on_hit=True)
        out = Cascade([stage1, rail]).evaluate(
            event({"text": "Deny the loan because she is pregnant."}))
        self.assertIs(out.verdict.decision, Decision.BLOCK)
        self.assertTrue(out.verdict.could_not_judge)

    def test_a_load_failure_is_unjudged_not_clean(self):
        def explode():
            raise OSError("model weights not found on disk")

        result = LocalBiasClassifierRail(pipeline_factory=explode).check("p", "text")
        self.assertFalse(result.judged)
        self.assertIn("OSError", result.reason)

    def test_biased_label_above_threshold_flags(self):
        rail = LocalBiasClassifierRail(threshold=0.7,
                                       pipeline_factory=fake_pipeline("BIASED", 0.93))
        result = rail.check("payload.output", "text")
        self.assertTrue(result.judged)
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.category, "x.afni.fairness.biased_language")
        self.assertAlmostEqual(finding.score, 0.93)
        # A single classifier score on a single response is not a fairness
        # measurement, so it flags where upstream invalidates.
        self.assertIs(finding.action, Action.FLAG)
        self.assertFalse(result.block)

    def test_label_inversion_is_ported_from_upstream(self):
        # bias.py:87-90 - a NON_BIASED result at 0.95 means a bias score of
        # 0.05, not 0.95. Getting this backwards would invert the whole rail.
        rail = LocalBiasClassifierRail(threshold=0.7,
                                       pipeline_factory=fake_pipeline("NON_BIASED", 0.95))
        self.assertEqual(rail.check("p", "text").findings, [])
        rail = LocalBiasClassifierRail(threshold=0.1,
                                       pipeline_factory=fake_pipeline("NON_BIASED", 0.5))
        self.assertAlmostEqual(rail.check("p", "text").findings[0].score, 0.5)

    def test_at_threshold_does_not_fire(self):
        # Upstream is a strict `>` (bias.py:95).
        rail = LocalBiasClassifierRail(threshold=0.7,
                                       pipeline_factory=fake_pipeline("BIASED", 0.7))
        self.assertEqual(rail.check("p", "text").findings, [])

    def test_score_stays_inside_the_contract_range(self):
        # Upstream's calculate_risk_score returns -1..1, which Finding rejects.
        rail = LocalBiasClassifierRail(threshold=0.5,
                                       pipeline_factory=fake_pipeline("BIASED", 1.0))
        self.assertLessEqual(rail.check("p", "t").findings[0].score, 1.0)

    def test_unusable_classifier_output_is_unjudged(self):
        rail = LocalBiasClassifierRail(
            pipeline_factory=lambda: (lambda t: [{"lbl": "?", "sc": 1}]))
        self.assertFalse(rail.check("p", "text").judged)

    def test_empty_text_is_clean_not_unjudged(self):
        # Mirrors bias.py:81-82, and matters because it must not load the model.
        rail = LocalBiasClassifierRail()
        result = rail.check("p", "   ")
        self.assertTrue(result.judged)
        self.assertEqual(result.findings, [])

    def test_the_pinned_model_revision_is_the_one_read_from_source(self):
        self.assertEqual(LocalBiasClassifierRail.MODEL_PATH,
                         "valurank/distilroberta-bias")
        self.assertEqual(LocalBiasClassifierRail.MODEL_REVISION,
                         "c1e4a2773522c3acc929a7b2c9af2b7e4137b96d")

    def test_bad_threshold_is_rejected_at_construction(self):
        for bad in (0.0, 1.0, -0.1, 1.5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                LocalBiasClassifierRail(threshold=bad)


# ============================================================ Stage 3 rail ==
class TestGenerativeBiasJudgeRail(unittest.TestCase):

    def test_no_judge_configured_is_unjudged(self):
        result = GenerativeBiasJudgeRail().check("p", "Women are naturally nurturing.")
        self.assertFalse(result.judged)
        self.assertIn("paid API", result.reason)

    def test_it_is_not_mounted_by_default(self):
        # Mounting an always-unjudged Stage 3 rail would block every escalated
        # request on a box with no judge wired up.
        self.assertNotIn(GenerativeBiasJudgeRail,
                         [type(rail) for rail in RAILS])
        self.assertIn(GenerativeBiasJudgeRail, [type(r) for r in CLOUD_RAILS])

    def test_a_configured_judge_produces_a_finding(self):
        # Schema and threshold from bias-detection.guard.ts:87-103.
        rail = GenerativeBiasJudgeRail(judge=lambda t: {
            "score": 0.9, "reason": "Reinforces gender stereotypes",
            "categories": ["gender"], "affectedGroups": ["women"],
            "impact": "high"})
        finding = rail.check("payload.output", "Women are naturally nurturing.").findings[0]
        self.assertEqual(finding.category, "x.afni.fairness.stereotype")
        self.assertAlmostEqual(finding.score, 0.9)
        self.assertIs(finding.severity, Severity.HIGH)
        self.assertIs(finding.action, Action.FLAG)

    def test_below_threshold_is_clean(self):
        rail = GenerativeBiasJudgeRail(judge=lambda t: {"score": 0.05})
        self.assertEqual(rail.check("p", "text").findings, [])

    def test_an_off_schema_judge_reply_is_unjudged_not_a_pass(self):
        for reply in ({}, {"score": "not a number"}, {"score": 1.4},
                      {"score": None}):
            with self.subTest(reply=reply):
                rail = GenerativeBiasJudgeRail(judge=lambda t, r=reply: r)
                self.assertFalse(rail.check("p", "text").judged)

    def test_a_raising_judge_is_unjudged(self):
        def boom(_):
            raise TimeoutError("provider timed out")

        self.assertFalse(GenerativeBiasJudgeRail(judge=boom).check("p", "t").judged)


# ======================================================== batch scaffolding ==
class TestBatchDataset(unittest.TestCase):

    def test_it_refuses_a_dataset_with_no_protected_attribute(self):
        # The whole point of the tenet: there is no automatic detector for
        # "unfair" without a declared protected group.
        with self.assertRaises(ValueError) as ctx:
            BatchDataset(y_true=[1, 0], y_pred=[1, 1], sensitive_features={})
        self.assertIn("sensitive_features", str(ctx.exception))

    def test_it_refuses_mismatched_lengths(self):
        with self.assertRaises(ValueError):
            BatchDataset(y_true=[1, 0, 1], y_pred=[1, 1],
                         sensitive_features={"race": ["a", "b", "c"]})
        with self.assertRaises(ValueError):
            BatchDataset(y_true=[1, 0], y_pred=[1, 1],
                         sensitive_features={"race": ["a"]})

    def test_it_refuses_an_empty_dataset(self):
        with self.assertRaises(ValueError):
            BatchDataset(y_true=[], y_pred=[], sensitive_features={"race": []})

    def test_groups_are_discovered_from_the_column(self):
        ds = BatchDataset(y_true=[1, 0, 1], y_pred=[1, 1, 0],
                          sensitive_features={"race": ["b", "a", "a"]})
        self.assertEqual(ds.groups("race"), ["a", "b"])
        self.assertEqual(ds.n_rows, 3)


class TestFairlearnMetricPort(unittest.TestCase):
    """Hand-checkable numbers for the stdlib port of Fairlearn's definitions.

    Group A: y_true [1,0,1,0], y_pred [1,1,0,0] -> selection 0.50, TPR 0.50, FPR 0.50
    Group B: y_true [1,0,1,0], y_pred [1,1,1,1] -> selection 1.00, TPR 1.00, FPR 1.00
    Overall selection rate = 6/8 = 0.75
    """

    def setUp(self):
        self.ds = BatchDataset(
            y_true=[1, 0, 1, 0, 1, 0, 1, 0],
            y_pred=[1, 1, 0, 0, 1, 1, 1, 1],
            sensitive_features={"race": ["A", "A", "A", "A", "B", "B", "B", "B"]})

    def test_base_rates(self):
        self.assertAlmostEqual(selection_rate([1, 1, 0, 0]), 0.5)
        self.assertAlmostEqual(true_positive_rate([1, 0, 1, 0], [1, 1, 0, 0]), 0.5)
        self.assertAlmostEqual(false_positive_rate([1, 0, 1, 0], [1, 1, 0, 0]), 0.5)

    def test_demographic_parity_difference_between_groups(self):
        self.assertAlmostEqual(
            demographic_parity_difference(self.ds, "race"), 0.5)

    def test_demographic_parity_difference_to_overall(self):
        # max |group - overall| = |0.5 - 0.75| = 0.25
        self.assertAlmostEqual(
            demographic_parity_difference(self.ds, "race", method="to_overall"),
            0.25)

    def test_equalized_odds_difference_both_aggregations(self):
        self.assertAlmostEqual(equalized_odds_difference(self.ds, "race"), 0.5)
        self.assertAlmostEqual(
            equalized_odds_difference(self.ds, "race", agg="mean"), 0.5)

    def test_a_perfectly_parity_respecting_dataset_scores_zero(self):
        ds = BatchDataset(y_true=[1, 0, 1, 0], y_pred=[1, 0, 1, 0],
                          sensitive_features={"sex": ["m", "m", "f", "f"]})
        self.assertAlmostEqual(demographic_parity_difference(ds, "sex"), 0.0)
        self.assertAlmostEqual(equalized_odds_difference(ds, "sex"), 0.0)

    def test_an_undefined_rate_is_none_not_zero(self):
        # A group with no positive ground truth has no TPR. Printing 0.0 there
        # would be a fabricated fairness number, which is worse than a gap.
        self.assertIsNone(true_positive_rate([0, 0], [1, 0]))
        self.assertIsNone(false_positive_rate([1, 1], [1, 0]))
        self.assertIsNone(selection_rate([]))

    def test_difference_needs_two_defined_groups(self):
        self.assertIsNone(difference({"a": 0.5}))
        self.assertIsNone(difference({"a": 0.5, "b": None}))
        self.assertAlmostEqual(difference({"a": 0.2, "b": 0.9}), 0.7)

    def test_bad_method_and_agg_are_rejected(self):
        with self.assertRaises(ValueError):
            difference({"a": 0.1, "b": 0.2}, method="nonsense")
        with self.assertRaises(ValueError):
            equalized_odds_difference(self.ds, "race", agg="nonsense")


class TestGroupFairnessMetricsJob(unittest.TestCase):

    def setUp(self):
        self.ds = BatchDataset(
            y_true=[1, 0, 1, 0, 1, 0, 1, 0],
            y_pred=[1, 1, 0, 0, 1, 1, 1, 1],
            sensitive_features={"race": ["A", "A", "A", "A", "B", "B", "B", "B"]})

    def test_it_satisfies_the_batch_job_protocol(self):
        job = GroupFairnessMetricsJob()
        self.assertIsInstance(job, FairnessBatchJob)
        self.assertEqual(job.spec.capability, "Group fairness metrics")

    def test_a_disparity_above_tolerance_emits_findings(self):
        report = GroupFairnessMetricsJob(tolerance=0.1).run(self.ds)
        self.assertTrue(report.judged)
        self.assertAlmostEqual(
            report.metrics["race.demographic_parity_difference"], 0.5)
        self.assertEqual(len(report.findings), 2)
        for finding in report.findings:
            self.assertEqual(finding.category, "x.afni.fairness.group_disparity")
            self.assertEqual(finding.path, "dataset.race")
            self.assertIs(finding.action, Action.FLAG)
            # Group A has the lower selection rate, so it is the worst off.
            self.assertEqual(finding.subject, "A")
            self.assertTrue(finding.fp and finding.fp != finding.subject)

    def test_a_generous_tolerance_emits_nothing(self):
        report = GroupFairnessMetricsJob(tolerance=0.9).run(self.ds)
        self.assertEqual(report.findings, [])
        self.assertIn("no disparity above tolerance", report.render())

    def test_by_group_is_reported_for_every_group(self):
        report = GroupFairnessMetricsJob().run(self.ds)
        self.assertEqual(sorted(report.by_group["race"]), ["A", "B"])
        self.assertAlmostEqual(
            report.by_group["race"]["B"]["selection_rate"], 1.0)

    def test_an_undefined_metric_is_noted_not_flagged(self):
        # Group m has only positive ground truth, so it has no FPR; group f has
        # only negative ground truth, so it has no TPR. Exactly one group has
        # each rate defined, so neither difference exists and equalized odds is
        # genuinely unanswerable. The job must say so rather than emit a 0.0 -
        # a fairness report that prints 0.0 for a metric it could not compute is
        # worse than one that admits the gap.
        ds = BatchDataset(y_true=[1, 1, 0, 0], y_pred=[1, 0, 1, 0],
                          sensitive_features={"sex": ["m", "m", "f", "f"]})
        report = GroupFairnessMetricsJob(tolerance=0.0).run(ds)
        self.assertIsNone(report.metrics["sex.equalized_odds_difference"])
        self.assertAlmostEqual(
            report.metrics["sex.demographic_parity_difference"], 0.0)
        self.assertTrue(any("undefined" in note for note in report.notes))
        self.assertEqual(report.findings, [])
        self.assertIn("n/a", report.render())

    def test_bad_tolerance_is_rejected(self):
        for bad in (-0.1, 1.1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                GroupFairnessMetricsJob(tolerance=bad)


class TestOfflineRunnerRegistry(unittest.TestCase):

    def test_every_declared_job_serves_a_real_capability(self):
        registry = CapabilityRegistry()
        names = set(registry.names(Tenet.FAIRNESS))
        for spec in OFFLINE_JOB_SPECS:
            with self.subTest(capability=spec.capability):
                self.assertIn(spec.capability, names)

    def test_every_declared_job_has_a_runner(self):
        for spec in OFFLINE_JOB_SPECS:
            with self.subTest(capability=spec.capability):
                self.assertIs(job_for(spec.capability).spec, spec)
        with self.assertRaises(KeyError):
            job_for("not a capability")

    def test_every_runner_satisfies_the_protocol(self):
        for job in BATCH_JOBS:
            with self.subTest(job=job.name):
                self.assertIsInstance(job, FairnessBatchJob)

    def test_every_spec_cites_a_source(self):
        # A declared job with no file:line is an assertion, not evidence.
        for spec in OFFLINE_JOB_SPECS:
            with self.subTest(capability=spec.capability):
                self.assertIn("references/", spec.evidence)
                self.assertTrue(spec.requires)
                self.assertTrue(spec.cadence)

    def test_preflight_reports_absence_honestly(self):
        readiness = fairness.offline_readiness()
        self.assertEqual(set(readiness),
                         {spec.capability for spec in OFFLINE_JOB_SPECS})
        for capability, flight in readiness.items():
            with self.subTest(capability=capability):
                if not flight.available:
                    self.assertIn("not installed", flight.detail)

    def test_a_declared_job_returns_unjudged_rather_than_a_fake_result(self):
        ds = BatchDataset(y_true=[1, 0], y_pred=[1, 0],
                          sensitive_features={"race": ["a", "b"]})
        for job in BATCH_JOBS:
            if isinstance(job, GroupFairnessMetricsJob):
                continue
            with self.subTest(job=job.name):
                report = job.run(ds)
                self.assertIsInstance(report, BatchReport)
                self.assertFalse(report.judged)
                self.assertTrue(report.reason)
                self.assertEqual(report.findings, [])
                self.assertIn("COULD NOT RUN", report.render())

    def test_the_promptfoo_pack_carries_its_data_residency_warning(self):
        # The analysis flagged this specifically: the bias:* probes are
        # remote-generated only, so running them ships AFNI prompts off-box.
        spec = job_for("Bias red-team probe packs").spec
        self.assertIn("DATA RESIDENCY", spec.note)
        self.assertIn("api.promptfoo.app", spec.note)


# ============================================================== registration ==
class TestRegistration(unittest.TestCase):

    def setUp(self):
        self.registry = CapabilityRegistry()
        fairness.register(self.registry)
        self.report = self.registry.report()
        self.rows = {r.capability: r for r in self.report.by_tenet[Tenet.FAIRNESS]}

    def test_every_capability_is_accounted_for_and_none_is_a_gap(self):
        self.assertEqual(set(self.rows),
                         set(self.registry.names(Tenet.FAIRNESS)))
        counts = self.report.counts(Tenet.FAIRNESS)
        self.assertEqual(counts[Coverage.GAP], 0)
        self.assertEqual(sum(counts.values()), len(self.rows))

    def test_the_tenet_is_registered_as_almost_entirely_offline(self):
        # 11 of 13 reviewed tools cannot run inline. The coverage report must
        # show that shape rather than rounding it up.
        counts = self.report.counts(Tenet.FAIRNESS)
        self.assertEqual(counts[Coverage.OFFLINE], len(OFFLINE_JOB_SPECS))
        self.assertEqual(counts[Coverage.CLOUD], 1)

    def test_the_local_classifier_status_tracks_the_real_dependency(self):
        row = self.rows["Local bias classifier (text)"]
        if LocalBiasClassifierRail.dependency_available():
            self.assertIs(row.status, Coverage.IMPLEMENTED)
        else:
            self.assertIs(row.status, Coverage.DEPENDENCY)
            self.assertIn("unjudged", row.note)

    def test_nothing_is_claimed_implemented_without_a_running_rail(self):
        mounted = {rail.name for rail in RAILS}
        for capability, row in self.rows.items():
            if row.status is not Coverage.IMPLEMENTED:
                continue
            with self.subTest(capability=capability):
                self.assertIsNotNone(row.attribution)
                self.assertIn(row.attribution.rail, mounted)

    def test_the_protected_attribute_rail_is_registered_against_nothing(self):
        # It runs on 100% of traffic and implements no row of the matrix.
        # Attributing it to "Bias detection (generative)" would inflate the
        # coverage number with a check that does something else entirely.
        attribution = fairness.ATTR_PROTECTED_ATTRIBUTE
        self.assertIsNone(attribution.capability)
        for row in self.rows.values():
            if row.attribution is not None:
                self.assertNotEqual(row.attribution.rail, attribution.rail)
        with self.assertRaises(ValueError):
            self.registry.register_rail(
                fairness.PROTECTED_ATTRIBUTE_RAIL, attribution)

    def test_every_registration_carries_a_note_and_an_attribution(self):
        for capability, row in self.rows.items():
            with self.subTest(capability=capability):
                self.assertTrue(row.note, "a status with no note is not evidence")
                self.assertIsNotNone(row.attribution)
                self.assertEqual(row.attribution.capability, capability)

    def test_offline_registrations_name_their_tool_and_entry_point(self):
        for spec in OFFLINE_JOB_SPECS:
            row = self.rows[spec.capability]
            with self.subTest(capability=spec.capability):
                self.assertIs(row.status, Coverage.OFFLINE)
                self.assertIn(spec.entry_point, row.note)

    def test_registering_twice_is_idempotent(self):
        fairness.register(self.registry)
        counts = self.registry.report().counts(Tenet.FAIRNESS)
        self.assertEqual(sum(counts.values()), len(self.rows))
        self.assertEqual(counts[Coverage.GAP], 0)


# ============================================================== conformance ==
class TestPackageConformance(unittest.TestCase):

    def test_every_category_matches_the_contract_pattern(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertRegex(category, _CATEGORY_RE)
                # Fairness has no home in the normative taxonomy roots, so every
                # one of these must sit in the vendor-extension namespace.
                self.assertTrue(category.startswith("x.afni.fairness."))

    def test_mounted_rails_are_never_offline_stage(self):
        # The Cascade constructor enforces this, but a rail declaring OFFLINE
        # and appearing in RAILS would be a packaging error worth catching here.
        for rail in RAILS:
            with self.subTest(rail=rail.name):
                self.assertIsNot(rail.stage, Stage.OFFLINE)
        Cascade(RAILS)   # must not raise

    def test_no_rail_claims_to_be_a_fairness_metric(self):
        # The one thing this package must never do. Both mounted rails emit
        # `flag` only; nothing here returns a disparity number at request time.
        text = "Deny the loan because she is pregnant."
        for rail in RAILS:
            with self.subTest(rail=rail.name):
                result = rail.check("payload.text", text)
                self.assertFalse(result.block)
                for finding in result.findings:
                    self.assertIsNot(finding.action, Action.BLOCK)

    def test_every_attribution_cites_vendored_source_or_says_it_cannot(self):
        for name, attribution in fairness.ATTRIBUTIONS.items():
            with self.subTest(rail=name):
                self.assertIn("references/", attribution.evidence)
                self.assertIn(attribution.confidence_kind,
                              ("deterministic", "classifier", "entailment", "judge"))

    def test_axes_with_no_vendored_source_say_so(self):
        # `pregnancy` and `veteran_status` are statutory, not ported. If that
        # ever gets quietly dressed up as a citation, this fails.
        statutory = {axis.name for axis in AXES
                     if "NO source in the vendored corpus" in axis.evidence}
        self.assertEqual(statutory, {"pregnancy", "veteran_status"})
        for axis in AXES:
            if axis.name in statutory:
                continue
            with self.subTest(axis=axis.name):
                self.assertIn("references/", axis.evidence)

    def test_importing_the_package_pulls_in_no_third_party_dependency(self):
        # Stage 1 must run on a box with nothing installed. A stray top-level
        # `import transformers` would make this whole tenet unimportable.
        import afni_rai.tenets.fairness as module
        source = open(module.__file__, encoding="utf-8").read()
        for banned in ("\nimport transformers", "\nfrom transformers",
                       "\nimport torch", "\nimport fairlearn", "\nimport numpy",
                       "\nimport pandas", "\nimport aif360"):
            with self.subTest(banned=banned.strip()):
                self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
