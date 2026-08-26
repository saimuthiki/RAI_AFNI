# -*- coding: utf-8 -*-
"""
Tests for the HTTP gateway.

These cover the ways the gateway could quietly betray the cascade underneath it,
not the happy path:

  * a 500 that a caller's `try/except: pass` reads as "no findings"
  * a verdict with an AFNI field bolted on, which no longer validates against the
    schema every AFNI application was told it could rely on
  * a matched SSN echoed back to the caller, or written to the audit database
  * a "streaming" endpoint that computes everything and then dribbles it out, so
    a progress UI lies about where the latency and the money went
  * a threshold store that is configured, exposed, and never consulted - Safe
    Zone's bug, which the platform exists partly to avoid repeating

Run: python3 rai_platform/run_tests.py
"""
import json
import logging
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai.cascade.engine import Cascade, StageProgress  # noqa: E402
from afni_rai.cascade.rail import RailResult, Stage  # noqa: E402
from afni_rai.contract.models import (  # noqa: E402
    Action, Decision, EventKind, Finding, GuardEvent, LLMProtocol, Severity, Tenet,
)
from afni_rai.gateway import providers  # noqa: E402
from afni_rai.gateway.app import Gateway, create_app  # noqa: E402
from afni_rai.tenets.accountability.audit import VerdictStore, scan_for_leak  # noqa: E402
from afni_rai.tenets.accountability.thresholds import (  # noqa: E402
    TenantConfig, ThresholdStore,
)

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"fastapi is not installed: {exc}") from exc

# The schema is the contract, so the test reads the real file rather than a copy.
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
VERDICT_SCHEMA = os.path.join(
    _REPO_ROOT, "references", "openguardrails-main", "openguardrails-main",
    "schema", "verdict.schema.json")

SSN = "123-45-6789"


def setUpModule():
    """Silence the gateway's own logging for the duration of this module.

    Several tests deliberately make the cascade raise, and the fail-closed path
    logs that at exception level - correctly, because in production it is the
    only trace of a degraded decision. Left enabled it prints a traceback into
    the middle of a passing suite, which trains a reader to ignore tracebacks.
    """
    logging.getLogger("afni_rai").setLevel(logging.CRITICAL)


def body(text=f"my ssn is {SSN}", **overrides):
    """A minimal valid GuardEvent body, exactly the required set from
    guard-event.schema.json."""
    out = {
        "kind": "step/request",
        "step_id": "step-1",
        "agent_id": "agent-1",
        "agent_type": "chat",
        "agent_workspace": "afni",
        "agent_user": "tester",
        "llm_protocol": "openai.chat",
        "payload": {"messages": [{"role": "user", "content": text}]},
    }
    out.update(overrides)
    return out


def event(text="hello", client_facing=True, tenant=None):
    return GuardEvent(
        kind=EventKind.REQUEST, step_id="step-1", agent_id="a", agent_type="chat",
        agent_workspace="afni", agent_user="u",
        llm_protocol=LLMProtocol.OPENAI_CHAT,
        payload={"messages": [{"role": "user", "content": text}]},
        client_facing=client_facing, tenant=tenant)


# --------------------------------------------------------------------------- #
# Test doubles                                                                 #
# --------------------------------------------------------------------------- #
class StubRail:
    """A rail with a countable number of calls, so "stage 3 has not run yet" is
    an assertion rather than a hope."""

    def __init__(self, name, stage, result=None, tenet=Tenet.PRIVACY, raises=False):
        self.name = name
        self.stage = stage
        self.tenet = tenet
        self._result = result or RailResult.clean()
        self._raises = raises
        self.calls = 0

    def check(self, path, text):
        self.calls += 1
        if self._raises:
            raise RuntimeError("rail exploded")
        return self._result


class ExplodingCascade:
    """Stands in for a cascade whose engine itself fails - not a rail failing,
    which the engine already converts to `unjudged`."""

    def evaluate(self, event):
        raise RuntimeError("engine exploded")

    def evaluate_iter(self, event):
        raise RuntimeError("engine exploded")
        yield  # pragma: no cover - makes this a generator function


def escalating(name, stage):
    return StubRail(name, stage, RailResult(judged=True, escalate=True))


def flagging(name, stage, action=Action.FLAG, subject=None):
    finding = Finding(category="privacy.pii.us_ssn", severity=Severity.HIGH,
                      action=action, path="payload.messages[0].content",
                      detector=name, subject=subject, fp="deadbeef")
    return StubRail(name, stage, RailResult(judged=True, findings=[finding]))


def gateway(**kwargs):
    kwargs.setdefault("env", {})
    return Gateway(**kwargs)


def client(**kwargs):
    kwargs.setdefault("env", {})
    return TestClient(create_app(warm=False, **kwargs))


# --------------------------------------------------------------------------- #
class TestTheVerdictStaysSchemaValid(unittest.TestCase):
    """The verdict is the contract. Adding an AFNI field to it would break every
    application that was told it could rely on the upstream shape."""

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"jsonschema is not installed: {exc}") from exc
        with open(VERDICT_SCHEMA, encoding="utf-8") as handle:
            cls.schema = json.load(handle)
        # Held as the module, not as `cls.validate = jsonschema.validate`: a
        # plain function assigned to a class attribute becomes a bound method.
        cls.jsonschema = jsonschema

    def validate(self, verdict):
        self.jsonschema.validate(instance=verdict, schema=self.schema)

    def test_a_live_response_validates_against_the_upstream_schema(self):
        response = client().post("/v1/guard", json=body())
        self.assertEqual(response.status_code, 200)
        # Not "pydantic agrees with pydantic": the real schema file, the real
        # HTTP body.
        self.validate(response.json()["verdict"])

    def test_the_envelope_is_exactly_verdict_and_explanation(self):
        payload = client().post("/v1/guard", json=body()).json()
        self.assertEqual(sorted(payload), ["explanation", "verdict"])

    def test_a_fail_closed_error_verdict_is_also_schema_valid(self):
        app_client = client()
        app_client.app.state.gateway.cascade = ExplodingCascade()
        payload = app_client.post("/v1/guard", json=body()).json()
        self.validate(payload["verdict"])

    def test_every_stream_frame_carrying_a_verdict_validates(self):
        frames = read_stream(client(), body())
        verdicts = [f for f in frames if f["event"] == "verdict"]
        self.assertEqual(len(verdicts), 1)
        self.validate(verdicts[0]["verdict"])


# --------------------------------------------------------------------------- #
class TestFailClosedOnError(unittest.TestCase):
    """A 500 is ambiguous, and an ambiguous guardrail failure is read as a pass
    by the next `try/except` up the stack."""

    def setUp(self):
        self.client = client()
        self.client.app.state.gateway.cascade = ExplodingCascade()

    def test_a_raising_cascade_returns_200_and_a_block(self):
        response = self.client.post("/v1/guard", json=body())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["verdict"]["decision"], "block")

    def test_the_payload_path_lands_in_unjudged(self):
        verdict = self.client.post("/v1/guard", json=body()).json()["verdict"]
        self.assertEqual(verdict["unjudged"], ["payload.messages[0].content"])

    def test_unjudged_is_never_empty_on_the_error_path(self):
        """An empty `unjudged` would read as "every path was judged", which is
        the one thing an error path must never say."""
        verdict = self.client.post(
            "/v1/guard", json=body(**{"payload": {}})).json()["verdict"]
        self.assertEqual(verdict["unjudged"], ["payload"])

    def test_the_degradation_is_announced_in_a_header(self):
        response = self.client.post("/v1/guard", json=body())
        self.assertIn("cascade raised", response.headers["x-afni-degraded"])

    def test_internal_traffic_also_blocks_when_the_engine_itself_fails(self):
        """fail_mode=open is a statement about one rail that could not look. It
        is not consent to serve a request nothing evaluated at all."""
        payload = self.client.post(
            "/v1/guard", json=body(client_facing=False)).json()
        self.assertEqual(payload["verdict"]["decision"], "block")

    def test_a_stream_that_fails_mid_flight_still_ends_in_a_block(self):
        frames = read_stream(self.client, body())
        kinds = [f["event"] for f in frames]
        self.assertEqual(kinds[-3:], ["error", "verdict", "done"])
        self.assertEqual(frames[-2]["verdict"]["decision"], "block")
        self.assertEqual(frames[-3]["error"]["code"], "cascade_failed")


# --------------------------------------------------------------------------- #
class TestTheTrustBoundary(unittest.TestCase):
    """A caller must not be able to ask the gateway to echo back the secret it
    just caught."""

    def _client(self, **env):
        rails = [flagging("privacy.stub", Stage.STAGE_1, subject=SSN)]
        return TestClient(create_app(warm=False, rails=rails, attributions={}, env=env))

    def test_the_subject_is_withheld_by_default(self):
        payload = self._client().post("/v1/guard", json=body()).json()
        self.assertNotIn(SSN, json.dumps(payload))

    def test_the_finding_still_carries_the_fingerprint(self):
        """Withheld, not erased. `fp` is what a false-positive exception keys on,
        so removing the subject must not cost the operator their handle."""
        verdict = self._client().post("/v1/guard", json=body()).json()["verdict"]
        self.assertEqual(verdict["findings"][0]["fp"], "deadbeef")
        self.assertNotIn("subject", verdict["findings"][0])

    def test_no_request_field_can_turn_revealing_on(self):
        """The forbidden-extras rule is what makes this a 422 rather than a
        silently ignored parameter that a reviewer might believe worked."""
        for attempt in ({"reveal": True}, {"reveal_subject": True},
                        {"AFNI_REVEAL_SUBJECT": "1"}):
            with self.subTest(attempt=attempt):
                response = self._client().post("/v1/guard", json=body(**attempt))
                self.assertEqual(response.status_code, 422)

    def test_no_query_parameter_or_header_can_turn_revealing_on(self):
        app_client = self._client()
        for kwargs in ({"params": {"reveal": "true"}},
                       {"headers": {"x-afni-reveal-subject": "1"}}):
            with self.subTest(kwargs=kwargs):
                response = app_client.post("/v1/guard", json=body(), **kwargs)
                self.assertNotIn(SSN, response.text)

    def test_the_server_side_flag_is_the_only_way_in(self):
        payload = self._client(AFNI_REVEAL_SUBJECT="1").post(
            "/v1/guard", json=body()).json()
        self.assertIn(SSN, json.dumps(payload))

    def test_stream_frames_withhold_the_subject_too(self):
        """A streaming client must not be the way a matched secret gets out."""
        frames = read_stream(self._client(), body())
        self.assertNotIn(SSN, json.dumps(frames))


# --------------------------------------------------------------------------- #
class TestNoMatchedValueReachesTheDatabase(unittest.TestCase):
    """The audit store is the evidence pack handed to a client reviewer. A
    guardrail that files the SSN it caught has defeated itself."""

    def test_the_store_contains_no_subject_after_a_request(self):
        store = VerdictStore(":memory:")
        rails = [flagging("privacy.stub", Stage.STAGE_1, subject=SSN)]
        app_client = TestClient(create_app(warm=False, rails=rails, attributions={},
                                           verdict_store=store, env={}))
        app_client.post("/v1/guard", json=body())
        self.assertEqual(store.count("verdicts"), 1)
        self.assertEqual(scan_for_leak(store, [SSN]), [])

    def test_it_is_still_clean_when_revealing_is_switched_on(self):
        """`AFNI_REVEAL_SUBJECT` governs the response. It must not reach through
        into the record - the two are separate decisions and only one of them is
        reversible."""
        store = VerdictStore(":memory:")
        rails = [flagging("privacy.stub", Stage.STAGE_1, subject=SSN)]
        app_client = TestClient(create_app(warm=False, 
            rails=rails, attributions={}, verdict_store=store,
            env={"AFNI_REVEAL_SUBJECT": "1"}))
        app_client.post("/v1/guard", json=body())
        self.assertEqual(scan_for_leak(store, [SSN]), [])

    def test_every_decision_is_persisted_including_the_fail_closed_ones(self):
        store = VerdictStore(":memory:")
        app_client = client(verdict_store=store)
        app_client.post("/v1/guard", json=body("hello"))
        app_client.app.state.gateway.cascade = ExplodingCascade()
        app_client.post("/v1/guard", json=body("hello"))
        self.assertEqual(store.count("verdicts"), 2)

    def test_a_streamed_decision_is_persisted_once(self):
        store = VerdictStore(":memory:")
        app_client = client(verdict_store=store)
        read_stream(app_client, body("hello"))
        self.assertEqual(store.count("verdicts"), 1)

    def test_the_record_carries_both_the_engine_and_enforced_decision(self):
        store = VerdictStore(":memory:")
        client(verdict_store=store).post("/v1/guard", json=body())
        row = store.db.execute(
            "SELECT decision, enforced, fail_mode FROM verdicts").fetchone()
        self.assertEqual(row[0], row[1])          # nothing overrode it
        self.assertEqual(row[2], "closed")        # client-facing default


# --------------------------------------------------------------------------- #
class TestStreamingIsReal(unittest.TestCase):
    """The whole point of the SSE endpoint. If the cascade finished before the
    first frame went out, the stage numbers and timings shown to an operator
    would be theatre."""

    def test_evaluate_iter_yields_before_the_next_stage_runs(self):
        stage_2 = StubRail("s2", Stage.STAGE_2)
        stage_3 = StubRail("s3", Stage.STAGE_3)
        cascade = Cascade([escalating("s1", Stage.STAGE_1), stage_2, stage_3])
        generator = cascade.evaluate_iter(event())

        first = next(generator)
        self.assertEqual(int(first.stage), 1)
        self.assertEqual(stage_2.calls, 0, "stage 2 ran before its frame was sent")
        self.assertEqual(stage_3.calls, 0, "stage 3 ran before its frame was sent")

        second = next(generator)
        self.assertEqual(int(second.stage), 2)
        self.assertEqual(stage_2.calls, 1)
        self.assertEqual(stage_3.calls, 0, "stage 3 ran before its frame was sent")

    def test_the_generator_returns_the_outcome_not_a_final_yield(self):
        cascade = Cascade([StubRail("s1", Stage.STAGE_1)])
        generator = cascade.evaluate_iter(event())
        yielded = []
        while True:
            try:
                yielded.append(next(generator))
            except StopIteration as stop:
                outcome = stop.value
                break
        self.assertTrue(all(isinstance(item, StageProgress) for item in yielded))
        self.assertIs(outcome.verdict.decision, Decision.ALLOW)

    def test_evaluate_is_a_wrapper_over_evaluate_iter(self):
        """One implementation, not two. If these ever diverge, a UI disagrees
        with the audit record and neither can be trusted."""
        rails = [flagging("privacy.stub", Stage.STAGE_1), StubRail("s2", Stage.STAGE_2)]
        cascade = Cascade(rails)
        blocking = cascade.evaluate(event("x"))

        generator = cascade.evaluate_iter(event("x"))
        while True:
            try:
                next(generator)
            except StopIteration as stop:
                streamed = stop.value
                break
        self.assertEqual(blocking.verdict.to_dict(), streamed.verdict.to_dict())
        self.assertEqual([t.rails_run for t in blocking.trace],
                         [t.rails_run for t in streamed.trace])

    def test_one_frame_per_stage_then_verdict_then_done(self):
        rails = [StubRail("s1", Stage.STAGE_1), StubRail("s2", Stage.STAGE_2),
                 StubRail("s3", Stage.STAGE_3)]
        frames = read_stream(
            TestClient(create_app(warm=False, rails=rails, attributions={}, env={})), body())
        self.assertEqual([f["event"] for f in frames],
                         ["stage", "stage", "stage", "verdict", "done"])
        self.assertEqual([f["stage"] for f in frames if f["event"] == "stage"],
                         [1, 2, 3])

    def test_a_skipped_stage_is_reported_as_not_run(self):
        """"Stage 2 never ran" is the cost argument becoming visible, so it is
        reported rather than omitted."""
        rails = [StubRail("s1", Stage.STAGE_1), StubRail("s2", Stage.STAGE_2)]
        frames = read_stream(
            TestClient(create_app(warm=False, rails=rails, attributions={}, env={})), body())
        stages = [f for f in frames if f["event"] == "stage"]
        self.assertTrue(stages[0]["ran"])
        self.assertFalse(stages[1]["ran"])
        self.assertEqual(stages[1]["rails_skipped"], ["s2"])

    def test_a_stage_1_block_short_circuits_and_says_so(self):
        stage_2 = StubRail("s2", Stage.STAGE_2)
        rails = [StubRail("s1", Stage.STAGE_1,
                          RailResult(judged=True, block=True)), stage_2]
        frames = read_stream(
            TestClient(create_app(warm=False, rails=rails, attributions={}, env={})), body())
        stages = [f for f in frames if f["event"] == "stage"]
        self.assertTrue(stages[0]["short_circuited"])
        self.assertFalse(stages[1]["ran"])
        self.assertEqual(stage_2.calls, 0)

    def test_the_content_type_is_event_stream_and_frames_are_json_data_lines(self):
        response = client().post("/v1/guard/stream", json=body())
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        data_lines = [line for line in response.text.splitlines()
                      if line.startswith("data: ")]
        self.assertTrue(data_lines)
        for line in data_lines:
            json.loads(line[len("data: "):])   # every one is a JSON object

    def test_frames_are_findings_so_far_not_the_final_set(self):
        rails = [escalating("s1", Stage.STAGE_1),
                 flagging("s2", Stage.STAGE_2)]
        frames = read_stream(
            TestClient(create_app(warm=False, rails=rails, attributions={}, env={})), body())
        stages = [f for f in frames if f["event"] == "stage"]
        self.assertEqual(stages[0]["findings"], [])
        self.assertEqual(len(stages[1]["findings"]), 1)


# --------------------------------------------------------------------------- #
class TestThresholdStoreIsWired(unittest.TestCase):
    """Configured, exposed through an API, and never consulted is Safe Zone's
    bug (`admin.go:66` writes it, `guardrails.go:287` reads an env global). The
    only defence is asserting the read happened on the HTTP path."""

    class ThresholdRail:
        name = "privacy.threshold_stub"
        tenet = Tenet.PRIVACY
        stage = Stage.STAGE_1
        KEY = "privacy.pii.ner_score"

        def check(self, path, text, ctx=None):
            value = ctx.threshold(self.KEY, 0.5) if ctx else 0.5
            if value < 0.4:
                return RailResult(judged=True, findings=[Finding(
                    category="privacy.pii.us_ssn", action=Action.BLOCK,
                    path=path, detector=self.name)])
            return RailResult.clean()

    def _client(self, store):
        return TestClient(create_app(warm=False, rails=[self.ThresholdRail()], attributions={},
                                     threshold_store=store, env={}))

    def test_a_tenant_override_changes_the_http_answer(self):
        store = ThresholdStore()
        store.put_tenant(TenantConfig(tenant="acme",
                                      thresholds={self.ThresholdRail.KEY: 0.1}))
        app_client = self._client(store)

        default = app_client.post("/v1/guard", json=body(tenant=None)).json()
        acme = app_client.post("/v1/guard", json=body(tenant="acme")).json()
        self.assertEqual(default["verdict"]["decision"], "allow")
        self.assertEqual(acme["verdict"]["decision"], "block")

    def test_the_read_is_recorded_against_the_requesting_tenant(self):
        store = ThresholdStore()
        store.put_tenant(TenantConfig(tenant="acme",
                                      thresholds={self.ThresholdRail.KEY: 0.1}))
        self._client(store).post("/v1/guard", json=body(tenant="acme"))
        reads = [r for r in store.reads if r.tenant == "acme"]
        self.assertTrue(reads, "the request path never consulted the store")
        self.assertEqual(reads[-1].value, 0.1)


# --------------------------------------------------------------------------- #
class TestIntrospectionEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = client()

    def test_healthz_reports_liveness_and_what_is_missing(self):
        payload = self.client.get("/healthz").json()
        self.assertIn(payload["status"], ("ok", "degraded"))
        self.assertEqual(payload["protocol_version"], "0.8")
        self.assertIsInstance(payload["tenets_not_loaded"], list)
        self.assertIsInstance(payload["dependencies_absent"], list)
        self.assertIsInstance(payload["rails_unavailable"], list)

    def test_healthz_never_reports_a_credential(self):
        app_client = TestClient(create_app(warm=False, env={
            "AFNI_JUDGE_PROVIDER": "openai,gemini",
            "OPENAI_API_KEYS": "sk-secret-one,sk-secret-two",
            "GOOGLE_API_KEYS": "goog-secret"}))
        text = app_client.get("/healthz").text
        for secret in ("sk-secret-one", "sk-secret-two", "goog-secret"):
            self.assertNotIn(secret, text)
        judge = app_client.get("/healthz").json()["judge_provider"]
        # Key INDEXES, never keys.
        self.assertEqual(judge["chain"], ["openai[0]", "openai[1]", "gemini[0]"])

    def test_healthz_names_the_judge_rails_that_cannot_judge(self):
        payload = self.client.get("/healthz").json()
        self.assertIn("content_safety.toxicity_judge",
                      payload["judge_rails_without_a_judge"])

    def test_healthz_says_revealing_is_off(self):
        self.assertFalse(self.client.get("/healthz").json()["reveal_subject"])

    def test_coverage_counts_all_65_capabilities_and_names_the_gaps(self):
        payload = self.client.get("/v1/coverage").json()
        self.assertEqual(sum(payload["totals"].values()), 65)
        self.assertEqual(len(payload["tenets"]), 7)
        self.assertIn("gap", payload["totals"])

    def test_coverage_status_values_are_the_five_documented_states(self):
        payload = self.client.get("/v1/coverage").json()
        allowed = {"implemented", "dependency-missing", "cloud-not-configured",
                   "offline-only", "gap"}
        for tenet in payload["tenets"]:
            for row in tenet["rows"]:
                self.assertIn(row["status"], allowed)

    def test_phases_cross_references_the_roadmap(self):
        payload = self.client.get("/v1/phases").json()
        self.assertIn("Phase 1 (0-30 days)", payload)
        phase_1 = payload["Phase 1 (0-30 days)"]
        self.assertTrue(phase_1["repos"])
        self.assertIn("present_in_platform", phase_1["repos"][0])

    def test_rails_lists_every_rail_with_its_attribution(self):
        payload = self.client.get("/v1/rails").json()
        self.assertEqual(payload["mounted"], len(payload["rails"]))
        self.assertTrue(payload["rails"])
        attributed = [r for r in payload["rails"] if r["attribution"]]
        self.assertTrue(attributed)
        one = attributed[0]["attribution"]
        for key in ("repo", "mechanism", "evidence", "confidence_kind"):
            self.assertIn(key, one)

    def test_no_offline_rail_is_ever_mounted(self):
        """An offline red-team tool in the request path is a latency and cost
        incident. The engine refuses it; this proves the HTTP surface agrees."""
        stages = {r["stage"] for r in self.client.get("/v1/rails").json()["rails"]}
        self.assertNotIn(4, stages)

    def test_the_openapi_document_is_generated(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for path in ("/v1/guard", "/v1/guard/stream", "/v1/coverage",
                     "/v1/phases", "/v1/rails", "/healthz"):
            self.assertIn(path, paths)


# --------------------------------------------------------------------------- #
class TestRequestContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = client()

    def test_a_missing_required_field_is_a_422_in_the_one_error_shape(self):
        payload = dict(body())
        del payload["step_id"]
        response = self.client.post("/v1/guard", json=payload)
        self.assertEqual(response.status_code, 422)
        error = response.json()
        self.assertEqual(error["code"], "invalid_guard_event")
        self.assertIn("message", error)
        self.assertIn("fields", error["details"])
        self.assertEqual(error["request_id"], response.headers["x-request-id"])

    def test_a_422_does_not_echo_the_payload_back(self):
        """Pydantic puts the offending `input` in every error, which here is the
        caller's prompt. The field name makes the error debuggable; the value
        would only put the SSN into an error body and every log downstream."""
        payload = body(f"my ssn is {SSN}")
        del payload["step_id"]
        response = self.client.post("/v1/guard", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(SSN, response.text)
        first = response.json()["details"]["fields"][0]
        self.assertEqual(sorted(first), ["loc", "msg", "type"])

    def test_an_unknown_field_is_rejected_rather_than_ignored(self):
        response = self.client.post("/v1/guard", json=body(client_facng=False))
        self.assertEqual(response.status_code, 422)

    def test_client_facing_defaults_to_true_so_omitting_it_fails_closed(self):
        app_client = TestClient(create_app(warm=False, 
            rails=[StubRail("s1", Stage.STAGE_1, RailResult.unjudged("no model"))],
            attributions={}, env={}))
        payload = app_client.post("/v1/guard", json=body()).json()
        self.assertEqual(payload["verdict"]["decision"], "block")

    def test_internal_traffic_is_allowed_but_still_reports_the_gap(self):
        app_client = TestClient(create_app(warm=False, 
            rails=[StubRail("s1", Stage.STAGE_1, RailResult.unjudged("no model"))],
            attributions={}, env={}))
        payload = app_client.post(
            "/v1/guard", json=body(client_facing=False)).json()
        self.assertEqual(payload["verdict"]["decision"], "allow")
        self.assertTrue(payload["verdict"]["unjudged"])
        self.assertTrue(payload["explanation"]["could_not_judge"])

    def test_every_response_carries_a_request_id(self):
        for path in ("/healthz", "/v1/rails"):
            with self.subTest(path=path):
                self.assertIn("x-request-id", self.client.get(path).headers)

    def test_a_caller_supplied_request_id_is_echoed(self):
        response = self.client.get("/healthz", headers={"x-request-id": "req-abc"})
        self.assertEqual(response.headers["x-request-id"], "req-abc")

    def test_the_explanation_never_contradicts_the_verdict(self):
        payload = self.client.post("/v1/guard", json=body()).json()
        self.assertEqual(payload["explanation"]["decision"],
                         payload["verdict"]["decision"])


# --------------------------------------------------------------------------- #
class TestJudgeProviders(unittest.TestCase):
    """With nothing configured, every judge rail must report `unjudged`. A
    guessing fallback here would reintroduce fail-open one layer below where the
    engine can see it."""

    def test_no_provider_is_configured_by_default(self):
        self.assertIsNone(providers.from_env({}))

    def test_a_judge_rail_with_no_provider_reports_unjudged(self):
        gw = gateway()
        judge_rails = [r for r in gw.rails if hasattr(r, "judge")]
        self.assertTrue(judge_rails, "expected at least one judge rail mounted")
        for rail in judge_rails:
            with self.subTest(rail=rail.name):
                self.assertIsNone(rail.judge)
                self.assertFalse(rail.check("payload.text", "anything").judged)

    def test_an_unknown_provider_name_refuses_to_boot(self):
        with self.assertRaises(ValueError):
            providers.from_env({"AFNI_JUDGE_PROVIDER": "magic"})

    def test_an_uncredentialed_provider_is_skipped_not_fatal(self):
        """A missing paid key must not take Stage 1 and Stage 2 down with it. No
        gateway is strictly worse than a gateway with no judge: one degradation
        is documented and fails closed, the other fails open by absence."""
        skipped = []
        chain = providers.from_env({"AFNI_JUDGE_PROVIDER": "openai,gemini",
                                    "GOOGLE_API_KEYS": "g"}, skipped)
        self.assertEqual(chain.links, ["gemini[0]"])
        self.assertEqual(len(skipped), 1)
        self.assertIn("OPENAI_API_KEYS", skipped[0])

    def test_a_wholly_unusable_chain_degrades_to_no_judge(self):
        skipped = []
        self.assertIsNone(providers.from_env(
            {"AFNI_JUDGE_PROVIDER": "openai,gemini,local"}, skipped))
        self.assertEqual(len(skipped), 3)

    def test_the_gateway_still_serves_with_an_unusable_chain(self):
        app_client = TestClient(create_app(warm=False, 
            env={"AFNI_JUDGE_PROVIDER": "openai,gemini"}))
        health = app_client.get("/healthz").json()
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(len(health["judge_providers_skipped"]), 2)
        # Still guarding: Stage 1 is untouched by a missing judge credential.
        self.assertEqual(app_client.post("/v1/guard", json=body()).status_code, 200)

    def test_an_unusable_provider_never_names_a_key_in_what_it_reports(self):
        skipped = []
        providers.from_env({"AFNI_JUDGE_PROVIDER": "openai,gemini",
                            "OPENAI_API_KEYS": "sk-secret-value"}, skipped)
        self.assertNotIn("sk-secret-value", " ".join(skipped))

    def test_selecting_each_provider_builds_an_adapter_without_a_network_call(self):
        chains = [
            providers.from_env({"AFNI_JUDGE_PROVIDER": "openai",
                                "OPENAI_API_KEYS": "k"}),
            providers.from_env({"AFNI_JUDGE_PROVIDER": "gemini",
                                "GOOGLE_API_KEYS": "k"}),
            providers.from_env({"AFNI_JUDGE_PROVIDER": "local",
                                "LOCAL_BASE_URL": "http://127.0.0.1:11434/v1"}),
        ]
        self.assertEqual([c.links for c in chains],
                         [["openai[0]"], ["gemini[0]"], ["local[nokey]"]])
        for chain in chains:
            # No model id in this platform has been checked against a live
            # endpoint, and /healthz says so rather than implying otherwise.
            self.assertFalse(chain.describe()["model_id_verified"])

    def test_the_singular_api_key_variable_is_accepted_as_an_alias(self):
        chain = providers.from_env({"AFNI_JUDGE_PROVIDER": "openai",
                                    "OPENAI_API_KEY": "k"})
        self.assertEqual(chain.links, ["openai[0]"])

    def test_a_repeated_provider_is_a_configuration_error(self):
        with self.assertRaises(ValueError):
            providers.from_env({"AFNI_JUDGE_PROVIDER": "openai,openai",
                                "OPENAI_API_KEYS": "k"})

    def test_the_chain_order_follows_the_configured_order(self):
        chain = providers.from_env({"AFNI_JUDGE_PROVIDER": "gemini,openai",
                                    "OPENAI_API_KEYS": "a,b",
                                    "GOOGLE_API_KEYS": "g"})
        self.assertEqual(chain.links, ["gemini[0]", "openai[0]", "openai[1]"])

    def test_a_blank_entry_in_a_key_list_is_not_a_phantom_key(self):
        chain = providers.from_env({"AFNI_JUDGE_PROVIDER": "openai",
                                    "OPENAI_API_KEYS": "a, ,b,"})
        self.assertEqual(chain.links, ["openai[0]", "openai[1]"])

    def test_binding_a_provider_does_not_mutate_the_tenet_singletons(self):
        """The tenet packages export module-level rail singletons. Mutating them
        would reconfigure the CLI and every other app in this process."""
        from afni_rai.tenets.content_safety import TOXICITY_JUDGE_RAIL

        provider = StubJudge(0.9)
        bound = providers.bind_judges([TOXICITY_JUDGE_RAIL], provider)
        self.assertIsNot(bound[0], TOXICITY_JUDGE_RAIL)
        self.assertIsNotNone(bound[0].judge)
        self.assertIsNone(TOXICITY_JUDGE_RAIL.judge)

    def test_a_bound_judge_produces_a_finding_over_http(self):
        from afni_rai.tenets.content_safety import TOXICITY_JUDGE_RAIL

        app_client = TestClient(create_app(warm=False, 
            rails=[escalating("s1", Stage.STAGE_1), TOXICITY_JUDGE_RAIL],
            attributions={}, judge_provider=StubJudge(0.99), env={}))
        payload = app_client.post("/v1/guard", json=body("you are awful")).json()
        categories = [f["category"] for f in payload["verdict"]["findings"]]
        self.assertTrue(categories, "the bound judge produced nothing")

    def test_a_judge_that_answers_prose_is_unjudged_not_clean(self):
        """A judge replying "I cannot assess this" must not become 0.0. That
        would be a clean verdict invented from a non-answer."""
        with self.assertRaises(providers.JudgeUnavailable):
            providers._parse_score("I cannot assess this")

    def test_a_score_outside_zero_to_one_is_refused(self):
        for raw in ("1.4", "-0.2", "42"):
            with self.subTest(raw=raw):
                with self.assertRaises(providers.JudgeUnavailable):
                    providers._parse_score(raw)

    def test_a_judge_failure_becomes_unjudged_over_http(self):
        from afni_rai.tenets.content_safety import TOXICITY_JUDGE_RAIL

        app_client = TestClient(create_app(warm=False, 
            rails=[escalating("s1", Stage.STAGE_1), TOXICITY_JUDGE_RAIL],
            attributions={}, judge_provider=BrokenJudge(), env={}))
        payload = app_client.post("/v1/guard", json=body("anything")).json()
        self.assertEqual(payload["verdict"]["decision"], "block")
        self.assertTrue(payload["verdict"]["unjudged"])


class StubJudge:
    """A judge that never touches the network - the point of the protocol."""

    name = "stub"

    def __init__(self, value):
        self.value = value
        self.calls = []

    def score(self, prompt, text):
        self.calls.append((prompt, text))
        return self.value

    def describe(self):
        return {"provider": "stub", "model": "stub", "model_id_verified": False}


class BrokenJudge(StubJudge):
    def __init__(self):
        super().__init__(0.0)

    def score(self, prompt, text):
        raise providers.JudgeUnavailable("judge is down")


# --------------------------------------------------------------------------- #
class TestTheFallbackChain(unittest.TestCase):
    """The chain is only correct if it falls through on the right things.

    Falling through on a usable answer would be shopping for a verdict until a
    key agrees. Not falling through on a 429 would waste a configured key. Both
    are asserted here against a mocked transport - no network is touched, and
    none can be from this environment anyway.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"httpx is not installed: {exc}") from exc
        cls.httpx = httpx

    def openai(self, status, body, name="openai"):
        """An OpenAI-shaped adapter wired to a canned response."""
        def handler(request):
            return self.httpx.Response(status, json=body)

        return providers.OpenAICompatibleJudge(
            api_key="unused-in-a-mock", name=name,
            transport=self.httpx.MockTransport(handler))

    ANSWER = {"choices": [{"message": {"content": "0.87"}}]}
    LOW = {"choices": [{"message": {"content": "0.10"}}]}

    def test_a_rate_limited_key_falls_through_to_the_next_one(self):
        chain = providers.JudgeChain([
            (self.openai(429, {"error": "slow down"}), "openai", 0),
            (self.openai(200, self.ANSWER), "openai", 1)])
        self.assertEqual(chain.score("prompt", "text"), 0.87)
        self.assertEqual([a.link for a in chain.last_attempts],
                         ["openai[0]", "openai[1]"])

    def test_every_infrastructural_status_falls_through(self):
        for status in (401, 403, 408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                chain = providers.JudgeChain([
                    (self.openai(status, {}), "openai", 0),
                    (self.openai(200, self.ANSWER), "openai", 1)])
                self.assertEqual(chain.score("p", "t"), 0.87)

    def test_it_falls_through_across_providers_not_just_keys(self):
        def gemini_handler(request):
            return self.httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "0.42"}]}}]})

        gemini = providers.GeminiJudge(
            api_key="unused-in-a-mock",
            transport=self.httpx.MockTransport(gemini_handler))
        chain = providers.JudgeChain([
            (self.openai(429, {}), "openai", 0),
            (self.openai(429, {}), "openai", 1),
            (gemini, "gemini", 0)])
        self.assertEqual(chain.score("p", "t"), 0.42)
        self.assertTrue(chain.last_attempts[-1].served)
        self.assertEqual(chain.last_attempts[-1].link, "gemini[0]")

    def test_a_connection_error_falls_through(self):
        def boom(request):
            raise self.httpx.ConnectError("no route to host")

        broken = providers.OpenAICompatibleJudge(
            api_key="unused-in-a-mock",
            transport=self.httpx.MockTransport(boom))
        chain = providers.JudgeChain([(broken, "openai", 0),
                                      (self.openai(200, self.ANSWER), "openai", 1)])
        self.assertEqual(chain.score("p", "t"), 0.87)

    def test_a_LOW_SCORE_IS_AN_ANSWER_and_never_falls_through(self):
        """The one that matters most. A judge returning 0.1 has answered; asking
        another key is shopping for a verdict, and a detector whose result
        depends on how many keys are configured is not a detector."""
        second = self.openai(200, self.ANSWER)
        chain = providers.JudgeChain([(self.openai(200, self.LOW), "openai", 0),
                                      (second, "openai", 1)])
        self.assertEqual(chain.score("p", "t"), 0.10)
        self.assertEqual(len(chain.last_attempts), 1)
        # The second link has no counter at all, because it was never asked.
        self.assertNotIn("openai[1]", chain.counters)

    def test_a_bad_request_does_not_fall_through(self):
        """A 400 or 404 is a wrong model id or a rejected body. The next key
        fails identically, and falling through would hide the mistake behind
        whichever provider happens to work."""
        for status in (400, 404, 422):
            with self.subTest(status=status):
                chain = providers.JudgeChain([
                    (self.openai(status, {}), "openai", 0),
                    (self.openai(200, self.ANSWER), "openai", 1)])
                with self.assertRaises(providers.JudgeUnavailable):
                    chain.score("p", "t")

    def test_an_exhausted_chain_raises_rather_than_guessing(self):
        chain = providers.JudgeChain([(self.openai(429, {}), "openai", 0),
                                      (self.openai(503, {}), "openai", 1)])
        with self.assertRaises(providers.JudgeUnavailable):
            chain.score("p", "t")

    def test_an_exhausted_chain_makes_the_rail_unjudged_over_http(self):
        from afni_rai.tenets.content_safety import TOXICITY_JUDGE_RAIL

        chain = providers.JudgeChain([(self.openai(429, {}), "openai", 0),
                                      (self.openai(429, {}), "openai", 1)])
        app_client = TestClient(create_app(warm=False, 
            rails=[escalating("s1", Stage.STAGE_1), TOXICITY_JUDGE_RAIL],
            attributions={}, judge_provider=chain, env={}))
        payload = app_client.post("/v1/guard", json=body("anything")).json()
        self.assertEqual(payload["verdict"]["decision"], "block")
        self.assertTrue(payload["verdict"]["unjudged"])

    def test_the_trail_records_the_key_index_and_never_the_key(self):
        chain = providers.JudgeChain([
            (self.openai(429, {}), "openai", 0),
            (self.openai(200, self.ANSWER), "openai", 1)])
        chain.score("p", "t")
        served = [a for a in chain.last_attempts if a.served]
        self.assertEqual([a.to_dict()["key_index"] for a in served], [1])
        blob = json.dumps([a.to_dict() for a in chain.last_attempts])
        self.assertNotIn("unused-in-a-mock", blob)

    def test_the_counters_are_cumulative_per_link(self):
        chain = providers.JudgeChain([
            (self.openai(429, {}), "openai", 0),
            (self.openai(200, self.ANSWER), "openai", 1)])
        chain.score("p", "t")
        chain.score("p", "t")
        self.assertEqual(chain.counters["openai[0]"], {"served": 0, "failed": 2})
        self.assertEqual(chain.counters["openai[1]"], {"served": 2, "failed": 0})

    def test_healthz_reports_the_chain_and_its_attempt_counters(self):
        chain = providers.JudgeChain([
            (self.openai(429, {}), "openai", 0),
            (self.openai(200, self.ANSWER), "openai", 1)])
        chain.score("p", "t")
        app_client = TestClient(create_app(warm=False, rails=[], attributions={},
                                           judge_provider=chain, env={}))
        judge = app_client.get("/healthz").json()["judge_provider"]
        self.assertEqual(judge["chain"], ["openai[0]", "openai[1]"])
        self.assertEqual(judge["attempts"]["openai[1]"]["served"], 1)


# --------------------------------------------------------------------------- #
class TestTheSamplePayloads(unittest.TestCase):
    """Every shipped sample must actually trip the tenet it claims.

    A sample that does not is worse than no sample: it teaches whoever tries it
    that the rail does not work, and it rots silently because nothing else reads
    the file.
    """

    @classmethod
    def setUpClass(cls):
        from afni_rai.gateway.app import load_samples

        cls.document = load_samples()
        cls.client = client()

    def test_the_samples_file_is_present_and_covers_every_tenet(self):
        tenets = {s["tenet"] for s in self.document["samples"]}
        for tenet in (Tenet.PRIVACY, Tenet.SECURITY, Tenet.FAIRNESS,
                      Tenet.EXPLAINABILITY, Tenet.CONTENT_SAFETY,
                      Tenet.HALLUCINATION, Tenet.ACCOUNTABILITY):
            with self.subTest(tenet=tenet.value):
                self.assertIn(tenet.value, tenets)

    def test_every_sample_body_is_a_valid_guard_event(self):
        for sample in self.document["samples"]:
            with self.subTest(sample=sample["name"]):
                response = self.client.post("/v1/guard", json=sample["body"])
                self.assertEqual(response.status_code, 200, response.text)

    def test_every_sample_trips_the_detectors_it_claims(self):
        for sample in self.document["samples"]:
            with self.subTest(sample=sample["name"]):
                payload = dict(sample["body"])
                # Internal traffic, so the answer is the FINDING rather than the
                # fail-closed block that a missing Stage-2 model would produce.
                payload["client_facing"] = False
                verdict = self.client.post(
                    "/v1/guard", json=payload).json()["verdict"]
                fired = {f["detector"] for f in verdict.get("findings", [])}
                for detector in sample["expect_detectors"]:
                    self.assertIn(detector, fired)

    def test_the_benign_control_trips_nothing_at_all(self):
        control = next(s for s in self.document["samples"]
                       if s["name"] == "benign_control")
        payload = self.client.post("/v1/guard", json=control["body"]).json()
        self.assertEqual(payload["verdict"].get("findings", []), [])

    def test_no_sample_carries_a_plausible_live_credential(self):
        """Everything in the file is synthetic, and it is committed. The AWS
        strings are AWS's own published documentation examples."""
        blob = json.dumps(self.document)
        for prefix in ("sk-proj-", "sk-ant-", "AIzaSy", "ghp_", "xoxb-"):
            self.assertNotIn(prefix, blob)

    def test_the_samples_are_the_named_examples_in_the_openapi_document(self):
        spec = self.client.get("/openapi.json").json()
        for path in ("/v1/guard", "/v1/guard/stream"):
            with self.subTest(path=path):
                examples = (spec["paths"][path]["post"]["requestBody"]
                            ["content"]["application/json"]["examples"])
                self.assertEqual(sorted(examples),
                                 sorted(s["name"] for s in self.document["samples"]))

    def test_the_swagger_ui_and_the_schema_are_served(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)

    def test_every_route_has_a_summary_so_the_docs_are_navigable(self):
        spec = self.client.get("/openapi.json").json()
        for path, operations in spec["paths"].items():
            for method, operation in operations.items():
                with self.subTest(route=f"{method.upper()} {path}"):
                    self.assertTrue(operation.get("summary"))
                    self.assertTrue(operation.get("tags"))


# --------------------------------------------------------------------------- #
def read_stream(app_client, payload):
    """Parse an SSE response into the list of JSON objects on its `data:` lines."""
    response = app_client.post("/v1/guard/stream", json=payload)
    frames = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            frames.append(json.loads(line[len("data: "):]))
    return frames


class TestTheOperatorConsoleIsServed(unittest.TestCase):
    """A mount at `/` matches every path, so its ORDER is the whole test.

    Registered before the router it would shadow `/v1/guard`, `/healthz` and
    `/docs` - the API would 404 while the console served happily, which is the
    kind of break that looks like a deployment problem for a day. So this asserts
    both halves: the console serves, and every API route still does.

    Same-origin is also a security property, not a convenience. The console posts
    to `/v1/guard`; the alternative to serving it from here is a CORS header, and
    a guardrail gateway that sends `Access-Control-Allow-Origin` is one any page
    on the internet can drive with the operator's session. No CORS middleware
    should ever appear in this app.
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        from afni_rai.gateway.app import create_app
        self.client = TestClient(create_app(warm=False))

    def test_the_console_is_served_from_the_gateway_origin(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_the_console_assets_are_served_with_usable_mime_types(self):
        # A .js served as text/plain is refused by the browser as an ES module,
        # which fails as a blank page rather than an error anyone can read.
        for path, expected in (("/styles.css", "text/css"),
                               ("/api.js", "javascript"),
                               ("/views/live.js", "javascript")):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn(expected, response.headers["content-type"])

    def test_the_mount_does_not_shadow_the_api(self):
        for path in ("/healthz", "/v1/rails", "/v1/coverage", "/v1/phases",
                     "/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_the_mount_does_not_shadow_the_docs(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_no_cors_header_is_sent(self):
        response = self.client.get("/healthz",
                                   headers={"origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_an_absent_console_directory_does_not_stop_the_api(self):
        """The gateway's job is judging events. A missing console must degrade to
        a 404 on `/`, never to a gateway that will not start.

        Driven by pointing the lookup at a real empty directory rather than by
        mocking `Path`, so the test exercises the actual `is_file()` branch.
        """
        import tempfile
        from fastapi import FastAPI
        import afni_rai.gateway.app as app_module

        app = FastAPI()

        @app.get("/healthz")
        def _health():  # noqa: ANN202 - test stub
            return {"status": "ok"}

        with tempfile.TemporaryDirectory() as empty:
            original = app_module.Path
            try:
                # `_mount_console` derives the directory from __file__; redirect
                # only that derivation, leaving Path itself intact elsewhere.
                app_module.Path = lambda *a, **k: original(empty) / "nowhere"
                app_module._mount_console(app)
            finally:
                app_module.Path = original

        mounted = [r for r in app.routes if getattr(r, "name", "") == "console"]
        self.assertEqual(mounted, [], "a missing console directory was mounted")
        from fastapi.testclient import TestClient
        self.assertEqual(TestClient(app).get("/healthz").status_code, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
