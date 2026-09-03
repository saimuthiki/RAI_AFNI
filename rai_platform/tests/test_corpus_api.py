# -*- coding: utf-8 -*-
"""
Tests for the corpus sampler: `afni_rai/regression.py` and the `/v1/corpus`
routes.

The subject here is a control surface that decides how much compute the server
spends, so these cover the ways it could quietly spend too much or measure the
wrong thing:

  * a selection larger than the cap running anyway, or - worse - running
    truncated, which produces a pass rate over a sample nobody chose
  * `max_stage: 3` sending 11,369 genuinely harmful prompts to a paid third-party
    judge, which corpus/WARNING.md forbids
  * a "deterministic" sample that moves when the corpus file is regenerated, so
    two runs of the same size are not comparable and no regression is detectable
  * a record with no baseline, or a baseline from a different tier, being
    reported as agreement
  * one record raising and taking the other 199 down with it
  * the full text of a harmful prompt echoed into every log the response reaches

Run: python3 rai_platform/run_tests.py
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai import regression  # noqa: E402
from afni_rai.cascade.rail import Stage  # noqa: E402
from afni_rai.gateway.app import create_app  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"fastapi is not installed: {exc}") from exc


def record(rid, prompt="hello", tenet=None, owasp=None, direction="input",
           expected=None):
    return {"id": rid, "prompt": prompt, "direction": direction, "tenet": tenet,
            "owasp": list(owasp or []), "harm_label": None, "source_label": [],
            "label_source": None, "target_completion": None,
            "origin": {"tool": "test"}, "expected": expected,
            "target_complied": None, "notes": ""}


def write_corpus(case, records):
    """A throwaway corpus on disk, with AFNI_CORPUS_PATH pointed at it.

    On disk rather than injected because `load()` caches on (path, mtime, size)
    and the cache is part of what is being tested - an in-memory list would skip
    the code that decides whether to re-read.
    """
    import tempfile
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".jsonl", delete=False, encoding="utf-8")
    for rec in records:
        handle.write(json.dumps(rec) + "\n")
    handle.close()
    case.addCleanup(os.unlink, handle.name)
    old = os.environ.get("AFNI_CORPUS_PATH")
    os.environ["AFNI_CORPUS_PATH"] = handle.name

    def restore():
        if old is None:
            os.environ.pop("AFNI_CORPUS_PATH", None)
        else:
            os.environ["AFNI_CORPUS_PATH"] = old
    case.addCleanup(restore)
    return handle.name


def setenv(case, name, value):
    old = os.environ.get(name)

    def restore():
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old
    case.addCleanup(restore)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


# --------------------------------------------------------------------------- #
# The cap                                                                     #
# --------------------------------------------------------------------------- #
class TestSampleCap(unittest.TestCase):
    """The cap is the whole reason this module exists. A guardrail console that
    lets someone start a nine-hour job with one click is a denial-of-service
    button with a friendly label."""

    def setUp(self):
        self.records = [record(f"r{i:04d}") for i in range(1000)]
        write_corpus(self, self.records)
        regression._CACHE.clear()

    def test_over_cap_raises_rather_than_truncating(self):
        """Truncation would be worse than refusing.

        A request for 5,000 that silently ran 500 would report a pass rate over a
        sample the caller did not choose and cannot reconstruct - which is a
        wrong number, not a smaller one.
        """
        with self.assertRaises(regression.SampleTooLarge) as ctx:
            regression.select(self.records, regression.Selection(limit=900), cap=500)
        self.assertIn("capped at 500", str(ctx.exception))

    def test_the_message_names_the_cap_and_the_cost(self):
        try:
            regression.select(self.records, regression.Selection(limit=900), cap=500)
        except regression.SampleTooLarge as exc:
            message = str(exc)
        self.assertIn("AFNI_CORPUS_MAX_SAMPLE", message,
                      "the message must name the knob, or the operator cannot "
                      "act on it")
        self.assertIn("baseline.py", message,
                      "refusing without naming the offline alternative leaves "
                      "the caller with no way to do the thing they wanted")

    def test_cap_is_checked_against_what_would_be_returned(self):
        """`limit=5000` over a 12-record pool is fine.

        Checking the requested limit rather than the resulting sample would force
        someone filtering to one small tenet to also guess a small enough number.
        """
        small = [record(f"t{i}", tenet="Privacy") for i in range(12)]
        chosen = regression.select(
            small + self.records,
            regression.Selection(limit=5000, tenet="Privacy"), cap=500)
        self.assertEqual(len(chosen), 12)

    def test_per_tenet_multiplies_and_is_still_capped(self):
        buckets = [record(f"a{i}", tenet="Privacy") for i in range(300)] + \
                  [record(f"b{i}", tenet="Security") for i in range(300)]
        with self.assertRaises(regression.SampleTooLarge):
            regression.select(buckets, regression.Selection(per_tenet=300), cap=500)

    def test_env_override_is_read(self):
        setenv(self, "AFNI_CORPUS_MAX_SAMPLE", "7")
        self.assertEqual(regression.max_sample(), 7)

    def test_nonsense_override_falls_back_to_the_default(self):
        """An unparseable or non-positive cap must not become "no cap"."""
        for bad in ("nonsense", "0", "-5", ""):
            setenv(self, "AFNI_CORPUS_MAX_SAMPLE", bad)
            self.assertEqual(regression.max_sample(),
                             regression.MAX_SAMPLE_DEFAULT, bad)


# --------------------------------------------------------------------------- #
# Stage 3 and the corpus disclosure rule                                     #
# --------------------------------------------------------------------------- #
class TestCloudCeiling(unittest.TestCase):
    """corpus/WARNING.md: these prompts do not go to a third party. That has to
    be enforced in code, not in the document."""

    class Rail:
        def __init__(self, stage):
            self.stage = stage
            self.name = f"stub.stage{int(stage)}"

    def rails(self):
        return [self.Rail(Stage.STAGE_1), self.Rail(Stage.STAGE_2),
                self.Rail(Stage.STAGE_3)]

    def test_stage_3_is_dropped_by_default(self):
        setenv(self, "AFNI_CORPUS_ALLOW_CLOUD", None)
        kept = regression.rails_for(3, self.rails())
        self.assertEqual([int(r.stage) for r in kept], [1, 2])

    def test_stage_3_survives_when_the_server_allows_it(self):
        setenv(self, "AFNI_CORPUS_ALLOW_CLOUD", "1")
        kept = regression.rails_for(3, self.rails())
        self.assertEqual([int(r.stage) for r in kept], [1, 2, 3])

    def test_the_downgrade_is_reported_not_silent(self):
        """A run quietly downgraded from Stage 3 would read as evidence that
        Stage 3 adds nothing - the exact wrong conclusion."""
        setenv(self, "AFNI_CORPUS_ALLOW_CLOUD", None)
        ceiling, note = regression.effective_max_stage(3)
        self.assertEqual(ceiling, 2)
        self.assertIsNotNone(note)
        self.assertIn("WARNING.md", note)
        self.assertIn("AFNI_CORPUS_ALLOW_CLOUD", note)

    def test_stage_2_request_gets_no_note(self):
        ceiling, note = regression.effective_max_stage(2)
        self.assertEqual((ceiling, note), (2, None))

    def test_allow_flag_only_honours_real_truthy_values(self):
        for value, expect in (("1", True), ("true", True), ("YES", True),
                              ("on", True), ("0", False), ("false", False),
                              ("", False), ("maybe", False)):
            setenv(self, "AFNI_CORPUS_ALLOW_CLOUD", value)
            self.assertIs(regression.cloud_allowed(), expect, value)


# --------------------------------------------------------------------------- #
# Determinism                                                                 #
# --------------------------------------------------------------------------- #
class TestDeterminism(unittest.TestCase):

    def test_same_seed_same_sample(self):
        records = [record(f"r{i:04d}") for i in range(400)]
        a = regression.select(records, regression.Selection(limit=25, seed=0))
        b = regression.select(records, regression.Selection(limit=25, seed=0))
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])

    def test_file_order_does_not_change_the_sample(self):
        """THE POINT of sorting by id before shuffling.

        The corpus file's line order is an artefact of the ingest run. If the
        sample depended on it, regenerating the corpus would silently change
        which records "seed 0" means - and a regression corpus whose sample moves
        when you rebuild it cannot detect a regression.
        """
        records = [record(f"r{i:04d}") for i in range(400)]
        forward = regression.select(records, regression.Selection(limit=25, seed=0))
        backward = regression.select(list(reversed(records)),
                                     regression.Selection(limit=25, seed=0))
        self.assertEqual([r["id"] for r in forward], [r["id"] for r in backward])

    def test_different_seeds_differ(self):
        records = [record(f"r{i:04d}") for i in range(400)]
        a = regression.select(records, regression.Selection(limit=25, seed=0))
        b = regression.select(records, regression.Selection(limit=25, seed=7))
        self.assertNotEqual([r["id"] for r in a], [r["id"] for r in b])

    def test_negative_seed_is_random(self):
        records = [record(f"r{i:04d}") for i in range(400)]
        draws = {tuple(r["id"] for r in regression.select(
            records, regression.Selection(limit=25, seed=-1))) for _ in range(6)}
        self.assertGreater(len(draws), 1,
                           "seed=-1 must be a genuinely random draw")


# --------------------------------------------------------------------------- #
# Filtering                                                                   #
# --------------------------------------------------------------------------- #
class TestFiltering(unittest.TestCase):

    def setUp(self):
        self.records = [
            record("p1", tenet="Privacy", owasp=["LLM02"]),
            record("p2", tenet="Privacy", owasp=["LLM02", "LLM06"]),
            record("s1", tenet="Security", owasp=["LLM01"]),
            record("u1", tenet=None, owasp=[]),
            record("o1", tenet="Security", owasp=["LLM01"], direction="output"),
        ]

    def test_tenet_filter(self):
        chosen = regression.select(self.records,
                                   regression.Selection(limit=99, tenet="Privacy"))
        self.assertEqual({r["id"] for r in chosen}, {"p1", "p2"})

    def test_unmapped_is_selectable_by_name(self):
        """The records with no tenet are 45% of the corpus. If the only way to
        reach them were "all tenets", the largest slice would be unsamplable on
        its own."""
        chosen = regression.select(
            self.records, regression.Selection(limit=99,
                                               tenet=regression.UNMAPPED))
        self.assertEqual({r["id"] for r in chosen}, {"u1"})

    def test_owasp_filter_is_case_insensitive(self):
        chosen = regression.select(self.records,
                                   regression.Selection(limit=99, owasp="llm01"))
        self.assertEqual({r["id"] for r in chosen}, {"s1", "o1"})

    def test_direction_filter(self):
        chosen = regression.select(
            self.records, regression.Selection(limit=99, direction="output"))
        self.assertEqual({r["id"] for r in chosen}, {"o1"})

    def test_filters_compose(self):
        chosen = regression.select(self.records, regression.Selection(
            limit=99, tenet="Security", owasp="LLM01", direction="input"))
        self.assertEqual({r["id"] for r in chosen}, {"s1"})

    def test_per_tenet_is_stratified_not_top_heavy(self):
        """The corpus is 42% one tenet. An unstratified sample of it mostly
        measures that one tenet, which is why per_tenet exists."""
        lopsided = ([record(f"big{i}", tenet="Profanity / Content Safety")
                     for i in range(200)]
                    + [record(f"small{i}", tenet="Fairness & Bias") for i in range(5)])
        chosen = regression.select(lopsided, regression.Selection(per_tenet=5))
        by_tenet = {}
        for r in chosen:
            by_tenet[r["tenet"]] = by_tenet.get(r["tenet"], 0) + 1
        self.assertEqual(by_tenet, {"Profanity / Content Safety": 5,
                                    "Fairness & Bias": 5})


# --------------------------------------------------------------------------- #
# Judging, and the four states of a row                                      #
# --------------------------------------------------------------------------- #
class Boom:
    """A cascade that always raises. One bad record must not lose the rest."""

    def evaluate(self, event):
        raise RuntimeError("detector exploded")


class TestJudge(unittest.TestCase):

    def test_a_raising_cascade_is_a_row_not_a_lost_run(self):
        rows = regression.run(Boom(), [record("r1"), record("r2")],
                              regression.Selection(limit=2), "stage_1_only")
        self.assertEqual(len(rows.rows), 2)
        self.assertEqual({r["decision"] for r in rows.rows}, {"error"})
        self.assertEqual(rows.stats["errors"], 2)

    def test_an_error_is_counted_separately_from_a_block(self):
        """A broken check is not a caught prompt. Folding errors into blocks
        would make a cascade that crashes on everything look like a cascade that
        catches everything."""
        rows = regression.run(Boom(), [record("r1")],
                              regression.Selection(limit=1), "stage_1_only")
        self.assertEqual(rows.stats["decisions"].get("block", 0), 0)
        self.assertEqual(rows.stats["errors"], 1)

    def test_an_error_row_names_the_exception(self):
        rows = regression.run(Boom(), [record("r1")],
                              regression.Selection(limit=1), "stage_1_only")
        self.assertIn("RuntimeError", rows.rows[0]["error"])

    def test_an_error_row_is_unjudged(self):
        """It has to be. `unjudged` is what fails closed, and a record the engine
        threw on was not inspected."""
        rows = regression.run(Boom(), [record("r1")],
                              regression.Selection(limit=1), "stage_1_only")
        self.assertTrue(rows.rows[0]["unjudged"])

    def test_output_records_arrive_as_responses(self):
        """An affirmative completion sent as a REQUEST would be scored by the
        input rails, which will never see that text in production."""
        from afni_rai.contract.models import EventKind
        event = regression.event_for(record("o1", direction="output"))
        self.assertIs(event.kind, EventKind.RESPONSE)
        self.assertIn("choices", event.payload)

    def test_input_records_arrive_as_requests(self):
        from afni_rai.contract.models import EventKind
        event = regression.event_for(record("i1"))
        self.assertIs(event.kind, EventKind.REQUEST)
        self.assertIn("messages", event.payload)

    def test_the_step_id_is_the_record_id(self):
        """So an audit row can be traced back to the corpus record that produced
        it without a second lookup table."""
        event = regression.event_for(record("afni-corpus-abc123"))
        self.assertEqual(event.step_id, "afni-corpus-abc123")


# --------------------------------------------------------------------------- #
# Baseline agreement                                                          #
# --------------------------------------------------------------------------- #
class Allow:
    def evaluate(self, event):
        from afni_rai.cascade.engine import Cascade
        return Cascade([]).evaluate(event)


class TestAgreement(unittest.TestCase):
    """`agrees` is tri-state. Collapsing "nothing to compare" into `True` would
    let a run with no baseline at all report as fully clean."""

    def row_for(self, expected):
        actual = {"decision": "allow", "blocking_rail": None,
                  "blocking_category": None, "findings": 0, "unjudged": False,
                  "stages_run": 1, "top_stage": 1, "error": None}
        return regression.row(record("r1", expected=expected), actual)

    def test_no_baseline_is_none_not_true(self):
        self.assertIsNone(self.row_for(None)["agrees"])

    def test_matching_baseline_is_true(self):
        self.assertIs(self.row_for({"decision": "allow",
                                    "tier": "stage_1_only"})["agrees"], True)

    def test_changed_verdict_is_false(self):
        self.assertIs(self.row_for({"decision": "block",
                                    "tier": "stage_1_only"})["agrees"], False)

    def test_a_baseline_with_no_decision_is_not_agreement(self):
        self.assertIsNone(self.row_for({"tier": "stage_1_only"})["agrees"])

    def test_unbaselined_rows_are_excluded_from_both_denominators(self):
        rows = [self.row_for(None), self.row_for(None),
                self.row_for({"decision": "block", "tier": "stage_1_only"})]
        stats = regression.aggregate(rows, 1.0, regression.Selection(limit=3),
                                     "stage_1_only")
        self.assertEqual(stats["baseline_compared"], 1)
        self.assertEqual(stats["baseline_drift"], 1)

    def test_block_rate_is_over_the_sample_not_over_the_baselined(self):
        """Two different denominators, deliberately. A single percentage would
        treat "no baseline" as "no drift"."""
        rows = [self.row_for(None) for _ in range(4)]
        stats = regression.aggregate(rows, 1.0, regression.Selection(limit=4),
                                     "stage_1_only")
        self.assertEqual(stats["block_rate"], 0.0)
        self.assertEqual(stats["baseline_compared"], 0)


# --------------------------------------------------------------------------- #
# Prompt disclosure                                                           #
# --------------------------------------------------------------------------- #
class TestPreview(unittest.TestCase):
    """The server picks these prompts, not the caller, so echoing 11,369 harmful
    prompts in full into every log the response reaches is a disclosure rather
    than a reply."""

    LONG = "x" * 500

    def test_long_prompts_are_truncated_by_default(self):
        out = regression.preview(self.LONG, reveal=False)
        self.assertEqual(len(out), regression.PREVIEW_CHARS)
        self.assertTrue(out.endswith("…"))

    def test_short_prompts_are_untouched(self):
        self.assertEqual(regression.preview("short one", reveal=False),
                         "short one")

    def test_reveal_returns_the_whole_thing(self):
        self.assertEqual(regression.preview(self.LONG, reveal=True), self.LONG)

    def test_reveal_defaults_to_the_env_flag(self):
        setenv(self, "AFNI_REVEAL_SUBJECT", None)
        self.assertLess(len(regression.preview(self.LONG)), len(self.LONG))
        setenv(self, "AFNI_REVEAL_SUBJECT", "1")
        self.assertEqual(len(regression.preview(self.LONG)), len(self.LONG))


# --------------------------------------------------------------------------- #
# Loading and the cache                                                       #
# --------------------------------------------------------------------------- #
class TestLoad(unittest.TestCase):

    def setUp(self):
        regression._CACHE.clear()

    def test_missing_corpus_names_how_to_get_one(self):
        setenv(self, "AFNI_CORPUS_PATH", "/nonexistent/corpus.jsonl")
        with self.assertRaises(FileNotFoundError) as ctx:
            regression.load()
        self.assertIn("ingest.py", str(ctx.exception))

    def test_cache_is_invalidated_when_the_file_changes(self):
        """Keyed on mtime AND size so a regenerated corpus is picked up without
        a restart. A stale read here would mean a run that reports on records the
        file no longer holds."""
        import time
        path = write_corpus(self, [record("a"), record("b")])
        self.assertEqual(len(regression.load()), 2)
        time.sleep(0.01)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record("c")) + "\n")
        self.assertEqual(len(regression.load()), 3)

    def test_summary_counts_without_loading_a_single_rail(self):
        """A bare host with no model weights still has to render the picker."""
        write_corpus(self, [record("a", tenet="Privacy", owasp=["LLM02"]),
                            record("b", tenet=None),
                            record("c", tenet="Privacy", direction="output",
                                   expected={"decision": "allow",
                                             "tier": "stage_1_only"})])
        summary = regression.summary()
        self.assertEqual(summary["records"], 3)
        self.assertEqual(summary["baselined"], 1)
        self.assertEqual({t["tenet"]: t["records"] for t in summary["tenets"]},
                         {"Privacy": 2, regression.UNMAPPED: 1})
        self.assertEqual({d["direction"]: d["records"]
                          for d in summary["directions"]},
                         {"input": 2, "output": 1})


# --------------------------------------------------------------------------- #
# The routes                                                                  #
# --------------------------------------------------------------------------- #
class TestRoutes(unittest.TestCase):

    def setUp(self):
        regression._CACHE.clear()
        write_corpus(self, [
            record(f"afni-corpus-{i:012x}", prompt=f"prompt number {i}",
                   tenet="Privacy" if i % 2 else "Security",
                   owasp=["LLM02"] if i % 2 else ["LLM01"])
            for i in range(60)])
        self.client = TestClient(create_app(warm=False, probe=False))

    def test_get_corpus_reports_the_cap(self):
        body = self.client.get("/v1/corpus").json()
        self.assertEqual(body["records"], 60)
        self.assertEqual(body["max_sample"], regression.max_sample())
        self.assertIn("cloud_allowed", body)

    def test_run_returns_rows_and_stats(self):
        body = self.client.post(
            "/v1/corpus/run", json={"limit": 5, "seed": 0, "max_stage": 1}).json()
        self.assertEqual(len(body["rows"]), 5)
        self.assertEqual(body["stats"]["sample"], 5)

    def test_over_cap_is_422_and_names_the_cap_in_details(self):
        setenv(self, "AFNI_CORPUS_MAX_SAMPLE", "4")
        response = self.client.post("/v1/corpus/run", json={"limit": 50})
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(body["code"], "sample_too_large")
        self.assertEqual(body["details"]["cap"], 4)

    def test_an_empty_selection_is_422_not_an_empty_success(self):
        """A 200 with zero rows reads as "nothing was wrong", which is the one
        answer a filter typo must never produce."""
        response = self.client.post("/v1/corpus/run",
                                    json={"limit": 5, "tenet": "Nope"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "empty_selection")

    def test_unknown_field_is_rejected(self):
        """`extra="forbid"` because this body decides how much compute the server
        spends. A misspelled `per_tenets` silently running the flat limit is a
        much bigger run than the caller asked for."""
        response = self.client.post("/v1/corpus/run",
                                    json={"limit": 5, "per_tenets": 3})
        self.assertEqual(response.status_code, 422)

    def test_stage_3_without_the_flag_is_capped_and_says_so(self):
        setenv(self, "AFNI_CORPUS_ALLOW_CLOUD", None)
        body = self.client.post(
            "/v1/corpus/run", json={"limit": 3, "max_stage": 3}).json()
        self.assertIsNotNone(body["note"])
        self.assertIn("Stage 2", body["note"])

    def test_stage_2_request_carries_no_note(self):
        body = self.client.post(
            "/v1/corpus/run", json={"limit": 3, "max_stage": 2}).json()
        self.assertIsNone(body["note"])

    def test_missing_corpus_is_503_not_500(self):
        setenv(self, "AFNI_CORPUS_PATH", "/nonexistent/corpus.jsonl")
        regression._CACHE.clear()
        for path in ("/v1/corpus", "/v1/corpus/run"):
            response = (self.client.get(path) if path == "/v1/corpus"
                        else self.client.post(path, json={"limit": 2}))
            self.assertEqual(response.status_code, 503, path)
            self.assertEqual(response.json()["code"], "corpus_missing", path)

    def test_prompts_are_truncated_in_the_response_by_default(self):
        long_prompt = "y" * 400
        regression._CACHE.clear()
        write_corpus(self, [record("afni-corpus-long", prompt=long_prompt)])
        client = TestClient(create_app(warm=False, probe=False,
                                       reveal_subject=False))
        row = client.post("/v1/corpus/run",
                          json={"limit": 1, "max_stage": 1}).json()["rows"][0]
        self.assertLess(len(row["prompt"]), len(long_prompt))
        self.assertEqual(row["id"], "afni-corpus-long",
                         "the id is never truncated - it is what people cite")

    def test_reveal_subject_on_the_gateway_returns_full_prompts(self):
        long_prompt = "y" * 400
        regression._CACHE.clear()
        write_corpus(self, [record("afni-corpus-long", prompt=long_prompt)])
        client = TestClient(create_app(warm=False, probe=False,
                                       reveal_subject=True))
        row = client.post("/v1/corpus/run",
                          json={"limit": 1, "max_stage": 1}).json()["rows"][0]
        self.assertEqual(row["prompt"], long_prompt)


class TestStreamRoute(unittest.TestCase):
    """The stream exists because a 200-record Stage-2 run is ten minutes, and a
    browser given no frames for ten minutes has already given up."""

    def setUp(self):
        regression._CACHE.clear()
        write_corpus(self, [record(f"afni-corpus-{i:012x}") for i in range(8)])
        self.client = TestClient(create_app(warm=False, probe=False))

    def frames(self, payload):
        out = []
        with self.client.stream("POST", "/v1/corpus/run/stream",
                                json=payload) as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            for line in response.iter_lines():
                if line.startswith("data:"):
                    out.append(json.loads(line[5:]))
        return out

    def test_one_row_frame_per_record_then_summary_then_done(self):
        frames = self.frames({"limit": 4, "seed": 0, "max_stage": 1})
        kinds = [f["event"] for f in frames]
        self.assertEqual(kinds, ["start", "row", "row", "row", "row",
                                 "summary", "done"])

    def test_the_start_frame_states_the_total_and_the_tier(self):
        """Without the total up front, a progress bar cannot exist - and a run
        with no progress bar is a run people reload the page on."""
        start = self.frames({"limit": 4, "seed": 0, "max_stage": 1})[0]
        self.assertEqual(start["total"], 4)
        self.assertIn("tier", start)
        self.assertIn("selection", start)

    def test_row_frames_carry_a_running_index(self):
        frames = self.frames({"limit": 4, "seed": 0, "max_stage": 1})
        rows = [f for f in frames if f["event"] == "row"]
        self.assertEqual([r["index"] for r in rows], [1, 2, 3, 4])

    def test_buffering_is_disabled_on_the_response(self):
        """A proxy that buffers turns this back into the synchronous endpoint."""
        with self.client.stream("POST", "/v1/corpus/run/stream",
                                json={"limit": 2, "max_stage": 1}) as response:
            self.assertEqual(response.headers.get("x-accel-buffering"), "no")
            response.read()

    def test_a_rejected_selection_is_a_real_status_code(self):
        """Not a 200 carrying an error frame. A 422 delivered inside a 200 is a
        422 nobody handles."""
        setenv(self, "AFNI_CORPUS_MAX_SAMPLE", "2")
        with self.client.stream("POST", "/v1/corpus/run/stream",
                                json={"limit": 50}) as response:
            self.assertEqual(response.status_code, 422)
            self.assertEqual(json.loads(response.read())["code"],
                             "sample_too_large")


# --------------------------------------------------------- positional range -- #
class TestPositionalRange(unittest.TestCase):
    """`start`/`end`: run the Nth to the Mth record, 1-based and INCLUSIVE.

    AFNI's ask: "if the corpus is having 8000 records and the user is wishing to
    test 10th to 20th, he would be able to configure that in the UI."
    """

    def setUp(self):
        self.records = [
            record(f"afni-corpus-{i:012x}", prompt=f"prompt number {i}",
                   tenet="Privacy" if i % 2 else "Security")
            for i in range(60)]

    def test_ten_to_twenty_is_eleven_records_not_ten(self):
        """The off-by-one that would be read as a corpus bug rather than an
        indexing one, so it is pinned rather than assumed."""
        got = regression.select(self.records, regression.Selection(start=10, end=20))
        self.assertEqual(len(got), 11)

    def test_it_is_one_based(self):
        first = regression.select(self.records, regression.Selection(start=1, end=1))
        ordered = sorted(self.records, key=lambda r: r["id"])
        self.assertEqual(first[0]["id"], ordered[0]["id"])

    def test_the_range_ignores_the_seed_entirely(self):
        """The property the whole feature rests on. If the seed moved a range,
        "the 10th record" would name a different record per seed and the number
        would be meaningless."""
        ids = [tuple(r["id"] for r in regression.select(
                   self.records, regression.Selection(start=5, end=15, seed=s)))
               for s in (0, 1, 42, -1)]
        self.assertEqual(len(set(ids)), 1, "a range moved when the seed changed")

    def test_the_range_ignores_the_files_line_order(self):
        """Same reasoning as `_shuffled` sorting by id first: the corpus file's
        line order is an artefact of the ingest run, so a range over raw line
        order would move if the corpus were regenerated."""
        import random as _r
        shuffled = list(self.records)
        _r.Random(7).shuffle(shuffled)
        a = [r["id"] for r in regression.select(
            self.records, regression.Selection(start=10, end=20))]
        b = [r["id"] for r in regression.select(
            shuffled, regression.Selection(start=10, end=20))]
        self.assertEqual(a, b)

    def test_a_filter_is_applied_before_the_range(self):
        pool = [r for r in self.records if (r.get("tenet") or "") == "Privacy"]
        if len(pool) < 3:
            self.skipTest("fixture holds too few Privacy records")
        got = regression.select(
            self.records, regression.Selection(start=1, end=2, tenet="Privacy"))
        self.assertEqual(len(got), 2)
        self.assertTrue(all(r.get("tenet") == "Privacy" for r in got))

    def test_end_may_be_omitted(self):
        got = regression.select(self.records, regression.Selection(start=55),
                                cap=len(self.records))
        self.assertEqual(len(got), len(self.records) - 54)

    def test_start_zero_is_rejected_as_a_one_based_mistake(self):
        with self.assertRaises(regression.RangeOutOfBounds) as cm:
            regression.select(self.records, regression.Selection(start=0))
        self.assertIn("1-based", str(cm.exception))

    def test_an_inverted_range_is_rejected(self):
        with self.assertRaises(regression.RangeOutOfBounds) as cm:
            regression.select(self.records, regression.Selection(start=20, end=10))
        self.assertIn("forwards", str(cm.exception))

    def test_a_start_past_the_end_names_the_pool_size(self):
        """And reports the RIGHT problem. An earlier version checked inversion
        first, so start=99999 was told its range ran backwards - true of the
        defaulted end, and the wrong diagnosis."""
        with self.assertRaises(regression.RangeOutOfBounds) as cm:
            regression.select(self.records, regression.Selection(start=99_999))
        msg = str(cm.exception)
        self.assertIn(f"{len(self.records):,}", msg)
        self.assertNotIn("forwards", msg)

    def test_a_range_does_not_combine_with_per_tenet(self):
        with self.assertRaises(regression.RangeOutOfBounds) as cm:
            regression.select(self.records,
                              regression.Selection(start=1, end=5, per_tenet=2))
        self.assertIn("do not combine", str(cm.exception))

    def test_the_cap_still_applies_to_a_range(self):
        with self.assertRaises(regression.SampleTooLarge):
            regression.select(self.records, regression.Selection(start=1, end=60),
                              cap=10)

    def test_describe_names_the_range_and_omits_the_seed(self):
        text = regression.Selection(start=10, end=20).describe()
        self.assertIn("records 10-20", text)
        self.assertNotIn("seed", text,
                         "a seed printed beside a range implies it changed the sample")


class TestRangeOverTheApi(unittest.TestCase):

    def setUp(self):
        regression._CACHE.clear()
        write_corpus(self, [
            record(f"afni-corpus-{i:012x}", prompt=f"prompt number {i}",
                   tenet="Privacy" if i % 2 else "Security")
            for i in range(60)])
        self.client = TestClient(create_app(warm=False, probe=False))

    def test_a_range_runs_and_reports_itself(self):
        r = self.client.post("/v1/corpus/run",
                             json={"start": 10, "end": 20, "max_stage": 1})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["rows"]), 11)
        self.assertIn("records 10-20", body["stats"]["selection"])

    def test_a_bad_range_is_its_own_error_code(self):
        """Not `empty_selection`: a typo'd range is a mistake to fix, an empty
        filter is an answer."""
        r = self.client.post("/v1/corpus/run",
                             json={"start": 99_999, "max_stage": 1})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["code"], "range_out_of_bounds")

    def test_the_stream_endpoint_accepts_a_range_too(self):
        r = self.client.post("/v1/corpus/run/stream",
                             json={"start": 1, "end": 3, "max_stage": 1})
        self.assertEqual(r.status_code, 200)
        self.assertIn("records 1-3", r.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
