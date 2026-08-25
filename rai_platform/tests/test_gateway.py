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
    return TestClient(create_app(**kwargs))


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
        return TestClient(create_app(rails=rails, attributions={}, env=env))

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
        app_client = TestClient(create_app(rails=rails, attributions={},
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
        app_client = TestClient(create_app(
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
            TestClient(create_app(rails=rails, attributions={}, env={})), body())
        self.assertEqual([f["event"] for f in frames],
                         ["stage", "stage", "stage", "verdict", "done"])
        self.assertEqual([f["stage"] for f in frames if f["event"] == "stage"],
                         [1, 2, 3])

    def test_a_skipped_stage_is_reported_as_not_run(self):
        """"Stage 2 never ran" is the cost argument becoming visible, so it is
        reported rather than omitted."""
        rails = [StubRail("s1", Stage.STAGE_1), StubRail("s2", Stage.STAGE_2)]
        frames = read_stream(
            TestClient(create_app(rails=rails, attributions={}, env={})), body())
        stages = [f for f in frames if f["event"] == "stage"]
        self.assertTrue(stages[0]["ran"])
        self.assertFalse(stages[1]["ran"])
        self.assertEqual(stages[1]["rails_skipped"], ["s2"])

    def test_a_stage_1_block_short_circuits_and_says_so(self):
        stage_2 = StubRail("s2", Stage.STAGE_2)
        rails = [StubRail("s1", Stage.STAGE_1,
                          RailResult(judged=True, block=True)), stage_2]
        frames = read_stream(
            TestClient(create_app(rails=rails, attributions={}, env={})), body())
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
            TestClient(create_app(rails=rails, attributions={}, env={})), body())
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
        return TestClient(create_app(rails=[self.ThresholdRail()], attributions={},
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
        app_client = TestClient(create_app(env={
            "AFNI_JUDGE_PROVIDER": "openai", "OPENAI_API_KEY": "sk-secret-value"}))
        text = app_client.get("/healthz").text
        self.assertNotIn("sk-secret-value", text)
        self.assertEqual(app_client.app.state.gateway.health()
                         ["judge_provider"]["provider"], "openai")

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

    def test_an_unknown_field_is_rejected_rather_than_ignored(self):
        response = self.client.post("/v1/guard", json=body(client_facng=False))
        self.assertEqual(response.status_code, 422)

    def test_client_facing_defaults_to_true_so_omitting_it_fails_closed(self):
        app_client = TestClient(create_app(
            rails=[StubRail("s1", Stage.STAGE_1, RailResult.unjudged("no model"))],
            attributions={}, env={}))
        payload = app_client.post("/v1/guard", json=body()).json()
        self.assertEqual(payload["verdict"]["decision"], "block")

    def test_internal_traffic_is_allowed_but_still_reports_the_gap(self):
        app_client = TestClient(create_app(
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

    def test_a_named_provider_without_its_credential_refuses_to_boot(self):
        for env in ({"AFNI_JUDGE_PROVIDER": "openai"},
                    {"AFNI_JUDGE_PROVIDER": "gemini"},
                    {"AFNI_JUDGE_PROVIDER": "local"}):
            with self.subTest(env=env):
                with self.assertRaises(ValueError):
                    providers.from_env(env)

    def test_selecting_each_provider_builds_an_adapter_without_a_network_call(self):
        openai = providers.from_env({"AFNI_JUDGE_PROVIDER": "openai",
                                     "OPENAI_API_KEY": "k"})
        gemini = providers.from_env({"AFNI_JUDGE_PROVIDER": "gemini",
                                     "GOOGLE_API_KEY": "k"})
        local = providers.from_env({"AFNI_JUDGE_PROVIDER": "local",
                                    "LOCAL_BASE_URL": "http://127.0.0.1:11434/v1"})
        self.assertEqual([p.name for p in (openai, gemini, local)],
                         ["openai", "gemini", "local"])
        for provider in (openai, gemini, local):
            self.assertFalse(provider.describe()["model_id_verified"])

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

        app_client = TestClient(create_app(
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

        app_client = TestClient(create_app(
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
def read_stream(app_client, payload):
    """Parse an SSE response into the list of JSON objects on its `data:` lines."""
    response = app_client.post("/v1/guard/stream", json=payload)
    frames = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            frames.append(json.loads(line[len("data: "):]))
    return frames


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
