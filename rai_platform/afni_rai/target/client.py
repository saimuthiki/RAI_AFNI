# -*- coding: utf-8 -*-
"""
The TARGET adapter: the AI system the gateway sits in front of.

Everything else in this platform judges text somebody handed it. This module is
the one place that calls a model in order to get an answer rather than a score,
and it exists so that `/v1/chat` can be a real guarded passthrough:

    caller -> [input guardrail] -> THIS MODULE -> [output guardrail] -> caller

WHY THIS IS NOT `gateway/providers.py`

A judge and a target speak the same wire protocol and mean completely different
things, so sharing an implementation would mean sharing semantics that must not
be shared:

  retries        A judge chain falls through to the next key on a 429, because
                 another key answers the same question. A target has ONE
                 endpoint and one model; falling through would answer the
                 caller's question with a different model than the one the
                 audit record names. So there is no chain here, no retry, and a
                 failure is reported as `target_error` with no completion.

  the return     A judge returns a float in [0, 1] and anything else is
                 `unjudged`. A target returns prose, and there is no "unusable
                 answer" that can be salvaged into a number.

  what a failure means
                 A judge that cannot answer degrades one rail to `unjudged`.
                 A target that cannot answer means there is no interaction at
                 all, and the caller must be told so explicitly rather than
                 handed an empty completion that reads like a terse model.

CONFIGURATION - nothing here has a hardcoded default that reaches the network

    AFNI_TARGET_BASE_URL   required; no default. Unset means /v1/chat reports
                           `target_not_configured` and the rest of the gateway
                           is unaffected.
    AFNI_TARGET_MODEL      required when the base URL is set; no default,
                           because guessing someone else's model id produces a
                           404 that looks like an outage.
    AFNI_TARGET_API_KEY    optional - a local inference server usually has none.
    AFNI_TARGET_TIMEOUT    seconds, default 60. A generation is slower than a
                           judge call, hence the larger default.
    AFNI_TARGET_MAX_TOKENS optional cap, omitted from the request when unset.
    AFNI_TARGET_PROBE_TIMEOUT  seconds, default 2. The STARTUP reachability
                           probe only, which must never delay a boot.

THE CREDENTIAL NEVER APPEARS ANYWHERE BUT THE Authorization HEADER

`TargetConfig.api_key` is `repr=False`, `TargetClient.__repr__` is written by
hand, `describe()` reports the boolean `api_key_configured` and never a length,
and every error raised from here carries the exception TYPE and an HTTP status
and never the exception's own message - httpx puts the request URL in that
message, and a base URL is the one place a key could travel in a query string.

MODEL IDS ARE NOT VERIFIED FROM THE BUILD ENVIRONMENT. It cannot reach the
user's endpoint (private address, proxied egress), so `model_id_verified` is
False until a live call or a live `/models` listing says otherwise, and
`/healthz` says UNVERIFIED in those words.

No network at import: httpx is imported inside the client property.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field, replace
from typing import Any, Sequence

LOGGER = logging.getLogger("afni_rai.target")

ENV_BASE_URL = "AFNI_TARGET_BASE_URL"
ENV_MODEL = "AFNI_TARGET_MODEL"
ENV_API_KEY = "AFNI_TARGET_API_KEY"
ENV_TIMEOUT = "AFNI_TARGET_TIMEOUT"
ENV_MAX_TOKENS = "AFNI_TARGET_MAX_TOKENS"
ENV_PROBE_TIMEOUT = "AFNI_TARGET_PROBE_TIMEOUT"

DEFAULT_TIMEOUT = 60.0        # .env.example ships 60
DEFAULT_PROBE_TIMEOUT = 2.0   # startup only, and never on the request path

# Usage counters are copied out of the target's response as INTEGERS ONLY, and
# nested one level deep at most. The reason is not tidiness. When the output
# guardrail blocks, the completion must not reach the caller under ANY key, and
# `usage` is a dict the target server controls: a broken or hostile server that
# echoed the generated text into `usage.note` would otherwise have a channel
# straight through the block. An int cannot carry prose.
MAX_USAGE_DEPTH = 2


class TargetError(RuntimeError):
    """The target did not produce a usable completion.

    One class with a `kind`, rather than a hierarchy, because every kind has the
    same consequence: `decision: target_error`, no completion, and no output
    guard call (there is nothing to guard). The kind exists so an operator can
    tell a timeout from a wrong model id without reading prose.

      not_configured   no base URL, or no model id
      timeout          the request exceeded AFNI_TARGET_TIMEOUT
      transport        DNS, TLS, connection refused - the request never landed
      http_status      the endpoint answered with >= 400
      bad_response     a 2xx whose body carried no usable message content
    """

    def __init__(self, kind: str, message: str, *, status: int | None = None,
                 exception: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        # The exception TYPE name, never its message: httpx exception messages
        # embed the request URL.
        self.exception = exception

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": str(self), "status": self.status,
                "exception": self.exception}


@dataclass(frozen=True)
class TargetConfig:
    """Resolved target configuration. The credential is `repr=False`."""

    base_url: str
    model: str
    timeout: float = DEFAULT_TIMEOUT
    max_tokens: int | None = None
    api_key: str | None = field(default=None, repr=False, compare=False)

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key)

    def describe(self) -> dict[str, Any]:
        """What `/healthz` and an error body may safely say. No credential, and
        not its length either - a length is a hint."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout_s": self.timeout,
            "max_tokens": self.max_tokens,
            "api_key_configured": self.api_key_configured,
        }


@dataclass(frozen=True)
class TargetCompletion:
    """One answer from the target, with the cost and latency of getting it.

    `model_id_verified` is True only when the endpoint echoed back the model id
    we asked for. That is the only verification available without trusting a
    server-supplied string, and it is the one the demo needs: it distinguishes
    "we configured qwen3-vl-8b-instruct" from "qwen3-vl-8b-instruct answered".
    """

    text: str
    model: str
    provider: str
    latency_ms: int
    usage: dict[str, Any] = field(default_factory=dict)
    model_id_verified: bool = False


@dataclass(frozen=True)
class EndpointProbe:
    """The result of ONE cheap reachability check, made at startup.

    Held rather than repeated: `/healthz` must not turn a monitoring poll into
    traffic against someone's inference server, and a probe per healthz hit
    would make a liveness check depend on a third party being up.

    `reachable is None` means "not probed" - nobody asked - which is a different
    fact from "probed and did not answer" and must not be rendered as False.
    """

    configured: bool
    reachable: bool | None = None
    base_url: str | None = None
    model: str | None = None
    model_id_verified: bool = False
    models_listed: int = 0
    status: int | None = None
    detail: str = "not probed"
    latency_ms: int | None = None

    @property
    def unauthorized(self) -> bool:
        """The endpoint answered, and REFUSED the credential it was given.

        Deliberately separate from `reachable` rather than folded into it. A 401
        proves the server is there, which is exactly what `reachable` reports,
        and collapsing the two would make a missing key look like a dead host.
        What a 401 also proves is that the endpoint is UNUSABLE: every real call
        carries the same header and gets the same refusal. Both facts are true at
        once, so both have to be askable.

        This was AFNI's machine: `AFNI_TARGET_API_KEY` was present but empty,
        `GET /models` answered `HTTP 401`, and every reader downstream saw only
        `reachable=True` and treated the endpoint as good.
        """
        return self.status in (401, 403)

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "reachable": self.reachable,
            "unauthorized": self.unauthorized,
            "base_url": self.base_url,
            "model": self.model,
            "model_id_verified": self.model_id_verified,
            "models_listed": self.models_listed,
            "status": self.status,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
        }


def _float_env(env: dict[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        LOGGER.warning("%s=%r is not a number; using %.1fs", name, raw, default)
        return default
    if value <= 0:
        LOGGER.warning("%s=%r is not positive; using %.1fs", name, raw, default)
        return default
    return value


def _int_env(env: dict[str, str], name: str) -> int | None:
    raw = (env.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        LOGGER.warning("%s=%r is not an integer; ignoring it", name, raw)
        return None
    if value <= 0:
        LOGGER.warning("%s=%r is not positive; ignoring it", name, raw)
        return None
    return value


def config_from_env(env: dict[str, str] | None = None) -> TargetConfig | None:
    """The configured target, or None.

    None is a legitimate steady state and NOT an error: it means this gateway is
    the judge-only deployment it has always been. `/v1/chat` reports
    `target_not_configured` and every other endpoint is untouched. Making an
    absent target fatal would mean a demo-only setting could stop the gateway
    guarding anything, which is the same trade `providers._links_for` refuses.

    A base URL with no model id is a half-configuration and returns None with an
    ERROR, because there is no model id worth guessing: a wrong one produces a
    404 per request, which reads as an outage rather than a misconfiguration.
    """
    env = os.environ if env is None else env
    base_url = (env.get(ENV_BASE_URL) or "").strip()
    if not base_url:
        return None
    model = (env.get(ENV_MODEL) or "").strip()
    if not model:
        LOGGER.error("%s is set but %s is empty: refusing to guess a model id, so "
                     "/v1/chat will report target_not_configured. Every other "
                     "endpoint is unaffected.", ENV_BASE_URL, ENV_MODEL)
        return None
    return TargetConfig(
        base_url=base_url.rstrip("/"),
        model=model,
        timeout=_float_env(env, ENV_TIMEOUT, DEFAULT_TIMEOUT),
        max_tokens=_int_env(env, ENV_MAX_TOKENS),
        api_key=(env.get(ENV_API_KEY) or "").strip() or None,
    )


class TargetClient:
    """One OpenAI-compatible chat endpoint, reached with `httpx` directly.

    httpx rather than the `openai` SDK for two reasons that are not stylistic:
    httpx is already a dependency of this platform and the SDK is not, so the
    SDK would add an install step to a guardrail gateway in order to make one
    POST; and the SDK retries and rewrites errors by default, which would put
    retry policy for the target inside a vendor library instead of in this
    module where the audit record can see it.
    """

    provider = "local"  # the deployment shape this adapter is for

    def __init__(self, config: TargetConfig, *, transport: Any = None,
                 provider: str | None = None) -> None:
        self.config = config
        if provider:
            self.provider = provider
        # An httpx transport, injected. It is the only way this adapter can be
        # tested - the real endpoint is on a private network the build
        # environment cannot reach - and it doubles as the seam for a
        # deployment that needs a proxy or a client certificate.
        self._transport = transport
        self._client: Any = None
        self._api_key = config.api_key

    def __repr__(self) -> str:
        """Hand-written so a traceback frame cannot print the credential.

        A dataclass-style auto repr on this object would put `_api_key` in every
        exception rendering that includes local variables, and a key that
        reaches a log is a rotated key.
        """
        return (f"TargetClient(base_url={self.config.base_url!r}, "
                f"model={self.config.model!r}, "
                f"api_key_configured={self.config.api_key_configured})")

    # httpx is imported here so that importing this module needs nothing
    # installed - `app.py` imports it unconditionally.
    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx  # noqa: PLC0415 - deliberately lazy

            self._client = httpx.Client(timeout=self.config.timeout,
                                        transport=self._transport)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            # The ONE place the credential is used. Absent means no header at
            # all, rather than a header carrying an empty string - a local
            # server with no auth rejects the latter.
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # ------------------------------------------------------------ generation --
    def complete(self, messages: Sequence[dict[str, Any]]) -> TargetCompletion:
        """POST `{base_url}/chat/completions` once and return the answer.

        Once. No retry, no fallback endpoint. A retried generation would bill
        twice for one interaction and could return a different answer than the
        one the guardrail verdicts and the audit record are about.

        Raises `TargetError` for every failure, which the passthrough turns into
        `decision: target_error` with no completion. There is no empty-string
        fallback: an empty completion is indistinguishable from a terse model,
        and a caller cannot tell a failure from an answer.
        """
        if not messages:
            raise TargetError("bad_request", "no messages to send to the target")
        body: dict[str, Any] = {"model": self.config.model,
                                "messages": list(messages)}
        if self.config.max_tokens is not None:
            body["max_tokens"] = self.config.max_tokens

        started = time.perf_counter()
        try:
            response = self.client.post(
                f"{self.config.base_url}/chat/completions",
                json=body, headers=self._headers())
        except Exception as exc:  # noqa: BLE001 - httpx errors, DNS, TLS, timeout
            elapsed = int((time.perf_counter() - started) * 1000)
            name = type(exc).__name__
            kind = "timeout" if "Timeout" in name else "transport"
            # Only the TYPE. httpx puts the request URL in the message.
            raise TargetError(
                kind,
                f"the target did not answer ({name}) after {elapsed} ms",
                exception=name) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        status = response.status_code
        if status >= 400:
            raise TargetError(
                "http_status",
                f"the target answered HTTP {status}"
                + (" - check AFNI_TARGET_MODEL against the model ids the endpoint "
                   "serves" if status in (400, 404) else ""),
                status=status)
        try:
            payload = response.json()
        except ValueError as exc:
            raise TargetError("bad_response",
                              "the target answered 2xx with a non-JSON body",
                              status=status) from exc
        return self._completion(payload, latency_ms=latency_ms, status=status)

    def _completion(self, payload: Any, *, latency_ms: int,
                    status: int) -> TargetCompletion:
        if not isinstance(payload, dict):
            raise TargetError("bad_response",
                              "the target answered 2xx with a body that is not a "
                              "JSON object", status=status)
        choices = payload.get("choices") or []
        if not isinstance(choices, list) or not choices:
            raise TargetError("bad_response",
                              "the target answered 2xx with no choices",
                              status=status)
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        text = _content_text(message.get("content"))
        if text is None:
            raise TargetError("bad_response",
                              "the target answered 2xx with no message content",
                              status=status)
        # The model id reported is OUR configured one, never the server's string.
        # `model_id_verified` is the comparison instead: a boolean derived from
        # the server's answer carries no server-controlled text.
        echoed = payload.get("model")
        verified = isinstance(echoed, str) and echoed == self.config.model
        return TargetCompletion(
            text=text,
            model=self.config.model,
            provider=self.provider,
            latency_ms=latency_ms,
            usage=_safe_usage(payload.get("usage")),
            model_id_verified=verified,
        )

    # ----------------------------------------------------------------- probe --
    def probe(self, timeout: float | None = None) -> EndpointProbe:
        """One cheap `GET {base_url}/models`, for startup and `/healthz`.

        Never raises. A probe that could raise would be a probe that can stop a
        boot, and an unreachable model server must not stop a guardrail gateway
        from guarding the traffic it can still see - the same rule
        `providers.from_env` follows for a keyless judge provider.

        Any HTTP answer below 500 counts as reachable, including a 404: a server
        that replies has been reached, and not every OpenAI-compatible server
        implements `/models`. When it does and the listing contains the
        configured model id, `model_id_verified` becomes True - the only
        verification this build environment could ever produce, and it cannot,
        because it has no route to the endpoint.
        """
        seconds = self.config.timeout if timeout is None else timeout
        started = time.perf_counter()
        try:
            import httpx  # noqa: PLC0415 - deliberately lazy

            with httpx.Client(timeout=seconds, transport=self._transport) as client:
                response = client.get(f"{self.config.base_url}/models",
                                      headers=self._headers())
        except Exception as exc:  # noqa: BLE001 - a probe must not raise, ever
            return EndpointProbe(
                configured=True, reachable=False,
                base_url=self.config.base_url, model=self.config.model,
                detail=f"GET /models failed: {type(exc).__name__}",
                latency_ms=int((time.perf_counter() - started) * 1000))
        latency_ms = int((time.perf_counter() - started) * 1000)
        status = response.status_code
        ids = _model_ids(response)
        return EndpointProbe(
            configured=True,
            reachable=status < 500,
            base_url=self.config.base_url,
            model=self.config.model,
            model_id_verified=self.config.model in ids,
            models_listed=len(ids),
            status=status,
            detail=f"GET /models -> HTTP {status}",
            latency_ms=latency_ms)

    def describe(self) -> dict[str, Any]:
        return {"provider": self.provider, **self.config.describe()}


def _content_text(content: Any) -> str | None:
    """The assistant's text, from either shape a chat completion uses.

    A string is the usual answer. A list of content parts is what a
    vision-language model returns when it answers with structured parts, and
    `qwen3-vl-8b-instruct` is such a model - dropping that shape would turn a
    perfectly good answer into `bad_response`.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text") for part in content
                 if isinstance(part, dict) and isinstance(part.get("text"), str)]
        if parts:
            return "".join(parts)
    return None


def _safe_usage(usage: Any, depth: int = 1) -> dict[str, Any]:
    """Token counters, integers only.

    See MAX_USAGE_DEPTH: this is a leak barrier, not a formatter. The response
    that carries `usage` also carries the completion, and the completion must
    not reach a caller whose output guardrail blocked it - so nothing that could
    hold prose is copied out of this object.
    """
    if not isinstance(usage, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in usage.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out[key] = value
        elif isinstance(value, dict) and depth < MAX_USAGE_DEPTH:
            nested = _safe_usage(value, depth + 1)
            if nested:
                out[key] = nested
    return out


def _model_ids(response: Any) -> list[str]:
    """The model ids in a `/models` listing, or an empty list.

    Tolerant on purpose: this is used to VERIFY a configured id, so an
    unexpected body shape must produce "could not verify" rather than an
    exception on a health path.
    """
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return []
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [row["id"] for row in rows
            if isinstance(row, dict) and isinstance(row.get("id"), str)]


def probe_timeout_from_env(env: dict[str, str] | None = None) -> float:
    """The STARTUP probe timeout. Short by default and separate from the request
    timeout: a 60-second generation budget is reasonable, and a 60-second boot
    delay because a model server is down is not."""
    env = os.environ if env is None else env
    return _float_env(env, ENV_PROBE_TIMEOUT, DEFAULT_PROBE_TIMEOUT)


def from_env(env: dict[str, str] | None = None, *,
             transport: Any = None) -> TargetClient | None:
    """The configured `TargetClient`, or None when no target is configured."""
    config = config_from_env(env)
    if config is None:
        return None
    LOGGER.info("target configured: %s model=%s timeout=%.1fs api_key=%s "
                "(model id NOT verified against a live endpoint)",
                config.base_url, config.model, config.timeout,
                "set" if config.api_key_configured else "absent")
    return TargetClient(config, transport=transport)


def probe_endpoint(base_url: str, *, model: str = "", api_key: str | None = None,
                   timeout: float = DEFAULT_PROBE_TIMEOUT,
                   transport: Any = None) -> EndpointProbe:
    """Probe an arbitrary OpenAI-compatible base URL. Never raises.

    Used by the judge chain's `AFNI_JUDGE_PREFER_LOCAL` reordering, which needs
    the same question answered about a different endpoint. Reusing this rather
    than writing a second probe keeps one definition of "the endpoint answered",
    so `/healthz` and the chain-ordering log cannot disagree about it.
    """
    if not base_url:
        return EndpointProbe(configured=False, detail="no base URL configured")
    config = TargetConfig(base_url=base_url.rstrip("/"), model=model or "?",
                          timeout=timeout, api_key=api_key)
    probe = TargetClient(config, transport=transport).probe(timeout)
    if not model:
        # No id was offered, so there was nothing to verify. Reporting False
        # would read as "verified and wrong".
        #
        # `replace`, not `EndpointProbe(**probe.to_dict(), ...)`: `to_dict` is the
        # REPORTING shape and now carries the derived `unauthorized` key, which is
        # not a field. Splatting it back into the constructor raised TypeError the
        # moment that key was added, so the round trip through the report is not a
        # safe way to copy a probe.
        probe = replace(probe, model=None, model_id_verified=False)
    return probe
