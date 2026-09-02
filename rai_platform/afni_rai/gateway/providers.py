# -*- coding: utf-8 -*-
"""
The model-call abstraction for Stage-3 judge rails.

Stage 3 is the only tier in the cascade that needs a language model, and it is
the tier that costs money per call. Everything about this module is arranged so
that an unconfigured gateway *cannot* accidentally start making paid calls, and
so that an unconfigured judge rail reports `unjudged` - which fails closed on
client-facing traffic - rather than guessing.

THE RULE THIS MODULE EXISTS TO ENFORCE

    With no provider configured, every judge rail returns `unjudged`.

There is no heuristic fallback, no "if we can't reach the judge, assume clean",
and no default provider. That is deliberate. A guessing fallback here would be
the NeMo Guardrails jailbreak-rail failure mode
(`references/Guardrails-develop/docs/configure-rails/guardrail-catalog/jailbreak-protection.mdx:112`,
documented fail-open) reintroduced at the provider seam, one layer below where
the engine can see it. The engine's fail-closed rule only works if a rail that
could not look says so.

WHAT A JUDGE IS, ON THE WIRE

`JudgeProvider.score(prompt, text) -> float` in [0, 1]. One float, because that
is what the rails consume: `PiiLeakageJudgeRail` and `ToxicityJudge` both take
`judge: Callable[[str], float]` and compare the result to a per-tenant
threshold. The prompt is the rail's question; the text is the payload string
under judgement. Anything the model returns that is not a parseable float in
[0, 1] raises `JudgeUnavailable`, which the rails turn into `unjudged`.

Fairness's `hai_guardrails.bias_detection` wants a dict-shaped judge rather than
a float and is not mounted in `RAILS` at all, so it is deliberately not bound
here. Binding a differently-shaped judge to it would be worse than leaving it
`unjudged`.

CONFIGURATION - AN ORDERED FALLBACK CHAIN

    AFNI_JUDGE_PROVIDER   none (default) | a comma-separated, ORDERED chain,
                          e.g. "openai,gemini" or "local,openai"
    AFNI_JUDGE_TIMEOUT    seconds, default 20.0 - every call has one

    openai   OPENAI_API_KEYS (comma-separated, ordered), OPENAI_BASE_URL,
             OPENAI_MODEL     [OPENAI_API_KEY is accepted as a single-key alias]
    gemini   GOOGLE_API_KEYS (comma-separated, ordered), GOOGLE_BASE_URL,
             GOOGLE_MODEL     [GOOGLE_API_KEY is accepted as a single-key alias]
    local    LOCAL_BASE_URL (required), LOCAL_MODEL, LOCAL_API_KEY (optional)

    AFNI_JUDGE_PREFER_LOCAL  off (default) | true. When on, the local endpoint is
                          probed ONCE at startup and, if it answers, `local` is
                          moved - or inserted - at the front of the chain. It is
                          opt-in because chain order decides which network the
                          flagged content in a judge call travels to. The probe
                          cannot block or fail a boot: an endpoint that is down
                          leaves the configured order untouched. See
                          `_prefer_local`.

The chain is walked in order - every key of the first provider, then every key of
the second - and the first link that ANSWERS wins. The full contract is in
`.env.example`; these are the semantics that make it correct:

  fall through ONLY on infrastructural failure
      401, 403, 408, 429, any 5xx, a timeout, or a connection error. The link
      could not answer, so asking the next one is asking the same question again.

  NEVER fall through on a low score
      A judge returning 0.1 has ANSWERED. Retrying that against another key would
      be shopping for a verdict until one agrees - a detector whose result depends
      on how many keys are configured is not a detector. The first usable number
      is the answer, full stop.

  never fall through on a bad request
      A 400 or a 404 means the model id is wrong or the body was rejected, and
      the next key will fail identically. Falling through would hide a
      configuration mistake behind whichever provider happens to work, so it is
      reported as `unjudged` instead.

  an exhausted chain is `unjudged`, never a guess
      Every link failed means nobody looked, and "could not look" is not "found
      nothing". The rail reports `unjudged` and client-facing traffic blocks.

  the audit trail records WHICH link served the call
      Provider name and key INDEX - `openai[1]` - never the key, not even
      truncated, not even its length. `JudgeChain.last_attempts` carries the
      per-call trail and `JudgeChain.counters` the cumulative one, which
      `/healthz` reports.

MODEL IDS ARE NOT VERIFIED HERE. The defaults below are placeholders read from
the environment, and none of them has been checked against a live endpoint from
this machine - its proxy blocks outbound provider traffic. Set the model id
explicitly for any real deployment and treat the default as a documented guess.

No network at import: httpx clients are constructed lazily on first call.
"""
from __future__ import annotations

import copy
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol, Sequence, runtime_checkable

LOGGER = logging.getLogger("afni_rai.gateway.providers")

# Environment variable names, in one place so the docs above and the code below
# cannot drift.
ENV_PROVIDER = "AFNI_JUDGE_PROVIDER"
ENV_TIMEOUT = "AFNI_JUDGE_TIMEOUT"
ENV_PREFER_LOCAL = "AFNI_JUDGE_PREFER_LOCAL"
ENV_PREFER_LOCAL_TIMEOUT = "AFNI_JUDGE_PREFER_LOCAL_TIMEOUT"

DEFAULT_PREFER_LOCAL_TIMEOUT = 2.0  # startup only; never on the request path

DEFAULT_TIMEOUT = 20.0  # .env.example ships 20

# --- Unverified model-id defaults ------------------------------------------- #
# Each of these is a plausible current id for its provider and NOTHING MORE. No
# call has been made against any of them from this environment, because no key is
# configured here. Override via the matching env var in any deployment.
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"        # UNVERIFIED
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"  # UNVERIFIED
DEFAULT_LOCAL_MODEL = "llama3"              # UNVERIFIED - an Ollama tag guess

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# How a judge is asked for a number. Appended to the rail's own prompt so the
# parsing contract lives with the parser rather than in each rail's prose.
SCORE_INSTRUCTION = (
    "Answer with a single number between 0 and 1 and nothing else. "
    "0 means the text is clearly fine; 1 means the text is clearly a violation. "
    "Do not explain."
)

_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+")


def truthy(value: str | None) -> bool:
    """Is this environment flag on?

    The one definition in the gateway - `app.py` imports it rather than keeping a
    second copy, because two readings of "true" that could diverge is exactly how
    a security flag ends up on in one module and off in another.
    """
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


class JudgeUnavailable(RuntimeError):
    """The judge could not produce a usable score.

    Raised for a timeout, a transport error, an HTTP error, a missing choice in
    the response, and an unparseable or out-of-range number - all of them the
    same fact as far as the cascade is concerned: nobody looked. The rails catch
    this and return `RailResult.unjudged(...)`, so it becomes a block on
    client-facing traffic instead of a silent pass.
    """


class JudgeLinkFailed(JudgeUnavailable):
    """An INFRASTRUCTURAL failure: this link could not answer at all.

    The distinction from plain `JudgeUnavailable` is the whole correctness of the
    fallback chain. This one means "ask the next key" - the request never reached
    a model, or the model never replied. Its parent means "stop": either a model
    answered and its answer was unusable, or the request itself is wrong and the
    next key will reject it identically.

    Getting this backwards in either direction is a real bug. Retrying a usable
    answer would be shopping for a verdict; retrying a 404 would hide a bad model
    id behind whichever provider happens to work.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# Statuses that mean "this key or this endpoint, right now" rather than "this
# request". Everything else is terminal.
RETRYABLE_STATUS = frozenset({401, 403, 408, 425, 429, 500, 502, 503, 504, 529})


def _is_retryable(status: int) -> bool:
    return status in RETRYABLE_STATUS or status >= 500


@dataclass(frozen=True)
class JudgeAttempt:
    """One link tried, and what came of it.

    `key_index` is an INDEX into the configured key list and never the key. -1
    means the link has no key at all, which is the normal case for a local
    inference server.
    """

    provider: str
    key_index: int
    served: bool
    detail: str = ""
    status: int | None = None

    @property
    def link(self) -> str:
        return (f"{self.provider}[{self.key_index}]" if self.key_index >= 0
                else f"{self.provider}[nokey]")

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "key_index": self.key_index,
                "link": self.link, "served": self.served,
                "detail": self.detail, "status": self.status}


@runtime_checkable
class JudgeProvider(Protocol):
    """One model call, one number.

    Structural on purpose, matching `Rail`: a test double or a future adapter is
    a judge if it has these two members, without importing anything from here.
    """

    name: str

    def score(self, prompt: str, text: str) -> float:
        """Score `text` against `prompt`, in [0, 1]. Raise `JudgeUnavailable`
        rather than returning a guess."""
        ...


# --------------------------------------------------------------------------- #
# Shared plumbing                                                              #
# --------------------------------------------------------------------------- #
def _parse_score(raw: str) -> float:
    """Pull a [0, 1] float out of a model's reply, or refuse.

    Refusing matters more than parsing. A judge that answers "I cannot assess
    this" must not become 0.0 - that is a clean verdict invented out of a
    non-answer, which is exactly the class of bug this platform exists to stop.
    """
    match = _FLOAT_RE.search(raw or "")
    if match is None:
        raise JudgeUnavailable(f"judge returned no number: {raw[:120]!r}")
    try:
        value = float(match.group(0))
    except ValueError as exc:  # pragma: no cover - regex guarantees a number
        raise JudgeUnavailable(f"judge returned unparseable score: {raw[:120]!r}") from exc
    if not 0.0 <= value <= 1.0:
        raise JudgeUnavailable(f"judge returned {value}, outside [0, 1]")
    return value


def _timeout_from_env(default: float = DEFAULT_TIMEOUT,
                      env: dict[str, str] | None = None) -> float:
    """The per-judge-call timeout.

    Takes the env explicitly so `from_env` reads the SAME mapping it was handed
    for everything else - a test that injects a dict was previously overridden
    here by the real process environment for this one value.
    """
    env = os.environ if env is None else env
    raw = env.get(ENV_TIMEOUT)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        LOGGER.warning("%s=%r is not a number; using %.1fs", ENV_TIMEOUT, raw, default)
        return default
    if value <= 0:
        LOGGER.warning("%s=%r is not positive; using %.1fs", ENV_TIMEOUT, raw, default)
        return default
    return value


class _HttpJudge:
    """Base for the HTTP adapters: one lazily-built client, one timeout, no
    import-time network and no credential ever logged."""

    name = "http"

    def __init__(self, *, model: str, base_url: str, timeout: float,
                 transport: Any = None) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        # An httpx transport, injected. The reason it exists is testing - the
        # adapters must be exercised against every status code in
        # RETRYABLE_STATUS without a network - and it doubles as the seam for a
        # deployment that needs a proxy or client certificates.
        self._transport = transport
        self._client: Any = None

    # httpx is imported inside the property so that importing this module - which
    # `app.py` does unconditionally - needs nothing installed.
    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx  # noqa: PLC0415 - deliberately lazy

            self._client = httpx.Client(timeout=self.timeout,
                                        transport=self._transport)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _post(self, url: str, *, json: dict, headers: dict) -> dict:
        try:
            response = self.client.post(url, json=json, headers=headers)
        except Exception as exc:  # noqa: BLE001 - httpx errors, DNS, TLS, timeout
            # Only the exception TYPE is reported. The message can contain the
            # request URL, and a Gemini URL carries the key in a query parameter.
            raise JudgeLinkFailed(
                f"{self.name} judge call failed: {type(exc).__name__}") from exc
        status = response.status_code
        if status >= 400:
            message = f"{self.name} judge returned HTTP {status}"
            if _is_retryable(status):
                raise JudgeLinkFailed(message, status=status)
            # A 400 or 404 is a configuration mistake - wrong model id, rejected
            # body - and the next key would fail identically. Reported rather
            # than papered over with a fallback.
            raise JudgeUnavailable(
                f"{message} (not retryable: this is a request or configuration "
                "error, not a key problem)")
        try:
            return response.json()
        except ValueError as exc:
            raise JudgeUnavailable(f"{self.name} judge returned non-JSON") from exc

    def describe(self) -> dict[str, Any]:
        """What `/healthz` may safely say about this provider. No credential,
        not even its length."""
        return {"provider": self.name, "model": self.model,
                "base_url": self.base_url, "timeout_s": self.timeout,
                "model_id_verified": False}


# --------------------------------------------------------------------------- #
# Adapters                                                                     #
# --------------------------------------------------------------------------- #
class OpenAICompatibleJudge(_HttpJudge):
    """`POST {base_url}/chat/completions` - OpenAI's own API and everything that
    speaks its shape (vLLM, Ollama's compat endpoint, LiteLLM, Together).

    `api_key` is optional precisely because a local server usually has none;
    when it is absent no Authorization header is sent, rather than one carrying
    an empty string.
    """

    def __init__(self, *, model: str = DEFAULT_OPENAI_MODEL,
                 base_url: str = DEFAULT_OPENAI_BASE_URL,
                 api_key: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 name: str = "openai",
                 transport: Any = None) -> None:
        super().__init__(model=model, base_url=base_url, timeout=timeout,
                         transport=transport)
        self.name = name
        self._api_key = api_key

    def score(self, prompt: str, text: str) -> float:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 8,
            "messages": [
                {"role": "system", "content": f"{prompt}\n\n{SCORE_INSTRUCTION}"},
                {"role": "user", "content": text},
            ],
        }
        payload = self._post(f"{self.base_url}/chat/completions",
                             json=body, headers=headers)
        choices = payload.get("choices") or []
        if not choices:
            raise JudgeUnavailable(f"{self.name} judge returned no choices")
        content = (choices[0].get("message") or {}).get("content")
        if not isinstance(content, str):
            raise JudgeUnavailable(f"{self.name} judge returned no message content")
        return _parse_score(content)


class GeminiJudge(_HttpJudge):
    """`POST {base_url}/models/{model}:generateContent` with the key as a query
    parameter, which is what the Generative Language API takes.

    The key is in the URL, so the URL is never logged and never returned by
    `describe()`. That is the whole reason this adapter builds its own URL
    string rather than letting the base class hold it.
    """

    name = "gemini"

    def __init__(self, *, api_key: str,
                 model: str = DEFAULT_GEMINI_MODEL,
                 base_url: str = DEFAULT_GEMINI_BASE_URL,
                 timeout: float = DEFAULT_TIMEOUT,
                 transport: Any = None) -> None:
        super().__init__(model=model, base_url=base_url, timeout=timeout,
                         transport=transport)
        if not api_key:
            raise ValueError("GeminiJudge requires an API key")
        self._api_key = api_key

    def score(self, prompt: str, text: str) -> float:
        url = (f"{self.base_url}/models/{self.model}:generateContent"
               f"?key={self._api_key}")
        body = {
            "system_instruction": {
                "parts": [{"text": f"{prompt}\n\n{SCORE_INSTRUCTION}"}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 8},
        }
        payload = self._post(url, json=body,
                             headers={"Content-Type": "application/json"})
        candidates = payload.get("candidates") or []
        if not candidates:
            raise JudgeUnavailable("gemini judge returned no candidates")
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        for part in parts:
            value = part.get("text")
            if isinstance(value, str) and value.strip():
                return _parse_score(value)
        raise JudgeUnavailable("gemini judge returned no text part")


def local_judge(*, base_url: str, model: str = DEFAULT_LOCAL_MODEL,
                api_key: str | None = None,
                timeout: float = DEFAULT_TIMEOUT,
                transport: Any = None) -> OpenAICompatibleJudge:
    """A local inference server - Ollama, vLLM, llama.cpp - reached over the
    OpenAI-compatible shape they all expose.

    A function rather than a class because there is genuinely no behaviour
    difference from `OpenAICompatibleJudge`; a subclass would exist only to hold
    a different name, and a second implementation of the same POST would be one
    more place for the two to diverge.
    """
    return OpenAICompatibleJudge(model=model, base_url=base_url, api_key=api_key,
                                 timeout=timeout, name="local", transport=transport)


# --------------------------------------------------------------------------- #
# The fallback chain                                                           #
# --------------------------------------------------------------------------- #
KNOWN_PROVIDERS = ("openai", "gemini", "local")
DISABLED_NAMES = ("", "none", "off", "disabled")


class JudgeChain:
    """An ordered list of judges. The first one that ANSWERS wins.

    Two failure classes, and the difference is the point:

      `JudgeLinkFailed`  this key could not answer - 401, 429, a timeout, a 5xx.
                         Move to the next link.
      `JudgeUnavailable` stop. Either a model answered unusably, or the request
                         is wrong and every remaining link will reject it too.

    A low score is not a failure of either kind. `score()` returns the first
    number it gets, so the answer does not depend on how many keys are
    configured - a detector whose verdict shifts with the length of a key list is
    not a detector.

    Exhausting the chain raises `JudgeUnavailable`, which the rails turn into
    `unjudged` and the engine turns into a block on client-facing traffic. There
    is no guessed score at the end of this function.
    """

    name = "chain"

    def __init__(self, links: Sequence[tuple[JudgeProvider, str, int]],
                 prefer_local: "LocalPreference | None" = None) -> None:
        if not links:
            raise ValueError("a JudgeChain needs at least one link")
        self._links = list(links)
        # How this order was arrived at, when AFNI_JUDGE_PREFER_LOCAL had a say.
        # Reported by /healthz: chain order decides which network the flagged
        # content in a judge call travels to, so "why is local first" has to be
        # answerable without reading the boot log.
        self.prefer_local = prefer_local
        # Per-call trail, per thread: the gateway serves requests on a threadpool
        # and one shared list would interleave two requests' attempts into one
        # unusable audit record.
        self._local = threading.local()
        self._counter_lock = threading.Lock()
        self._counters: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------- reporting --
    @property
    def last_attempts(self) -> list[JudgeAttempt]:
        """The attempt trail of THIS thread's most recent `score()` call."""
        return list(getattr(self._local, "attempts", ()))

    @property
    def counters(self) -> dict[str, dict[str, int]]:
        """Cumulative served/failed per link, for `/healthz`.

        Keyed by `provider[index]`, so an operator can see that `openai[0]` is
        being rate limited into `openai[1]` on every request without a key ever
        appearing anywhere.
        """
        with self._counter_lock:
            return {link: dict(counts) for link, counts in self._counters.items()}

    @property
    def links(self) -> list[str]:
        return [JudgeAttempt(name, index, False).link
                for _, name, index in self._links]

    def _count(self, attempt: JudgeAttempt) -> None:
        with self._counter_lock:
            row = self._counters.setdefault(attempt.link, {"served": 0, "failed": 0})
            row["served" if attempt.served else "failed"] += 1

    def describe(self) -> dict[str, Any]:
        """What `/healthz` may safely say. No credential, no key length, no URL
        that could carry one."""
        described = {
            "provider": "chain",
            "chain": self.links,
            "models": [{"link": JudgeAttempt(name, index, False).link,
                        "model": getattr(judge, "model", "?")}
                       for judge, name, index in self._links],
            "model_id_verified": False,
            "attempts": self.counters,
        }
        if self.prefer_local is not None:
            described["prefer_local"] = self.prefer_local.to_dict()
        return described

    # ----------------------------------------------------------------- score --
    def score(self, prompt: str, text: str) -> float:
        attempts: list[JudgeAttempt] = []
        self._local.attempts = attempts
        for judge, name, index in self._links:
            try:
                value = judge.score(prompt, text)
            except JudgeLinkFailed as exc:
                attempt = JudgeAttempt(name, index, False, str(exc),
                                       getattr(exc, "status", None))
                attempts.append(attempt)
                self._count(attempt)
                LOGGER.warning("judge link %s could not answer (%s); trying the "
                               "next link", attempt.link, exc)
                continue
            except JudgeUnavailable as exc:
                # Terminal. Falling through here would hide a configuration
                # error, or shop for a second opinion on a usable answer.
                attempt = JudgeAttempt(name, index, False, str(exc))
                attempts.append(attempt)
                self._count(attempt)
                LOGGER.error("judge link %s failed terminally: %s", attempt.link, exc)
                raise
            attempt = JudgeAttempt(name, index, True, "served")
            attempts.append(attempt)
            self._count(attempt)
            LOGGER.info("judge served by %s", attempt.link)
            return value

        trail = ", ".join(f"{a.link}: {a.detail}" for a in attempts)
        raise JudgeUnavailable(
            f"every judge link failed, so nobody looked ({trail}) - reporting "
            "unjudged rather than guessing a score")


def _keys(env: dict[str, str], plural: str, singular: str) -> list[str]:
    """The ordered key list for one provider.

    `*_API_KEYS` is the contract in `.env.example`; the singular `*_API_KEY` is
    accepted as an alias because it is the near-universal convention and a
    deployment that sets only it should work rather than refuse to boot.
    Blank entries are dropped, so a trailing comma is not a phantom key.
    """
    raw = env.get(plural) or env.get(singular) or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


class UnusableProvider(ValueError):
    """A provider named in the chain that cannot contribute a single link."""


def _links_for(name: str, env: dict[str, str], timeout: float
               ) -> list[tuple[JudgeProvider, str, int]]:
    """Every link one provider contributes, in order.

    Raises `UnusableProvider` when it can contribute none. `from_env` SKIPS such
    a provider loudly rather than refusing to boot, and the reasoning is worth
    stating because the opposite is tempting:

    A missing judge credential is already a fully handled state in this platform -
    the judge rail reports `unjudged`, the engine fails closed, and the coverage
    report says `cloud-not-configured`. Turning it into a boot failure would take
    Stage 1 and Stage 2 down with it, so an unmounted secret or a rotated key
    would stop the gateway guarding ANYTHING. For a guardrail, no gateway is
    strictly worse than a gateway with no judge: one degradation is documented and
    fails closed, the other is an outage that fails open by absence.

    An unrecognised provider NAME is different and stays fatal in `from_env`: it
    cannot be interpreted at all, the operator's intent is unknowable, and it is a
    deploy-time typo the first boot in CI should catch.
    """
    if name == "openai":
        keys = _keys(env, "OPENAI_API_KEYS", "OPENAI_API_KEY")
        if not keys:
            raise UnusableProvider(
                "openai is in the chain but OPENAI_API_KEYS is empty")
        base_url = env.get("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
        model = env.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        return [(OpenAICompatibleJudge(model=model, base_url=base_url, api_key=key,
                                       timeout=timeout, name="openai"), "openai", i)
                for i, key in enumerate(keys)]

    if name == "gemini":
        keys = _keys(env, "GOOGLE_API_KEYS", "GOOGLE_API_KEY")
        if not keys:
            raise UnusableProvider(
                "gemini is in the chain but GOOGLE_API_KEYS is empty")
        base_url = env.get("GOOGLE_BASE_URL") or DEFAULT_GEMINI_BASE_URL
        model = env.get("GOOGLE_MODEL") or DEFAULT_GEMINI_MODEL
        return [(GeminiJudge(api_key=key, model=model, base_url=base_url,
                             timeout=timeout), "gemini", i)
                for i, key in enumerate(keys)]

    base_url = env.get("LOCAL_BASE_URL")
    if not base_url:
        raise UnusableProvider(
            "local is in the chain but LOCAL_BASE_URL is unset - there is no "
            "sensible default for someone else's inference server")
    keys = _keys(env, "LOCAL_API_KEYS", "LOCAL_API_KEY")
    model = env.get("LOCAL_MODEL") or DEFAULT_LOCAL_MODEL
    if not keys:
        # The normal case: a local server with no auth. One link, no key index.
        return [(local_judge(base_url=base_url, model=model, timeout=timeout),
                 "local", -1)]
    return [(local_judge(base_url=base_url, model=model, api_key=key,
                         timeout=timeout), "local", i)
            for i, key in enumerate(keys)]


@dataclass(frozen=True)
class LocalPreference:
    """What `AFNI_JUDGE_PREFER_LOCAL` did to the chain order, and why.

    Recorded rather than merely logged, because the chain order decides WHERE
    flagged content is sent for judging. A judge call ships the flagged text to
    whoever serves it, so "did local actually win" is a data-residency question,
    not a performance note, and `/healthz` has to be able to answer it.
    """

    enabled: bool
    probed: bool = False
    reachable: bool | None = None
    base_url: str | None = None
    model: str | None = None
    inherited_from_target: bool = False
    action: str = "disabled"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "probed": self.probed,
                "reachable": self.reachable, "base_url": self.base_url,
                "model": self.model,
                "inherited_from_target": self.inherited_from_target,
                "action": self.action, "detail": self.detail}


def _prefer_local(env: dict[str, str], names: list[str]
                  ) -> tuple[dict[str, str], list[str], LocalPreference | None]:
    """Opt-in: probe the local endpoint once and, if it answers, put it first.

    Why an OPT-IN flag and not the default: chain order is a data-residency
    decision. Silently reordering it would move the flagged content a judge call
    carries onto a different network than the operator configured, which is
    exactly the kind of change that must be typed out rather than inferred.

    Why a PROBE and not a try-it-and-see: the chain already falls through a dead
    link on the first request, but it does so per request, paying a connect
    timeout each time before the paid provider answers. One probe at startup
    turns that into one decision.

    Why the probe CANNOT block the boot: `probe_endpoint` never raises and takes
    a short timeout of its own (default 2 s, `AFNI_JUDGE_PREFER_LOCAL_TIMEOUT`).
    A local endpoint that is down leaves the configured chain exactly as it was,
    logs a warning, and the gateway serves - the same precedent as a keyless
    provider being skipped rather than fatal.

    When the endpoint answers, `local` is moved to the front, and INSERTED if it
    was not in the chain at all. Inserting is the point of the flag: the operator
    who sets it is saying "use the local model for judging whenever it is up",
    and their `AFNI_JUDGE_PROVIDER` is the fallback list for when it is not.

    `LOCAL_BASE_URL` is optional here alone: when it is unset and a target IS
    configured, the local judge inherits the target's endpoint and model, since
    that is the machine the operator just pointed the gateway at. The inheritance
    is confined to this opt-in path - `_links_for` still requires
    `LOCAL_BASE_URL` - and it is reported in `inherited_from_target` rather than
    left to be discovered.
    """
    if not truthy(env.get(ENV_PREFER_LOCAL)):
        return env, names, None

    from ..target.client import (  # noqa: PLC0415 - startup path, lazy on purpose
        ENV_API_KEY as TARGET_API_KEY,
        ENV_BASE_URL as TARGET_BASE_URL,
        ENV_MODEL as TARGET_MODEL,
        probe_endpoint,
    )

    base_url = (env.get("LOCAL_BASE_URL") or "").strip()
    model = (env.get("LOCAL_MODEL") or "").strip()
    inherited = False
    api_key = (_keys(env, "LOCAL_API_KEYS", "LOCAL_API_KEY") or [None])[0]
    if not base_url:
        base_url = (env.get(TARGET_BASE_URL) or "").strip()
        model = model or (env.get(TARGET_MODEL) or "").strip()
        api_key = api_key or (env.get(TARGET_API_KEY) or "").strip() or None
        inherited = bool(base_url)

    if not base_url:
        LOGGER.warning(
            "%s is on but neither LOCAL_BASE_URL nor %s is set, so there is no "
            "local endpoint to prefer; the chain order is unchanged",
            ENV_PREFER_LOCAL, TARGET_BASE_URL)
        return env, names, LocalPreference(
            enabled=True, action="no local endpoint configured",
            detail=f"set LOCAL_BASE_URL or {TARGET_BASE_URL}")

    timeout = DEFAULT_PREFER_LOCAL_TIMEOUT
    raw = (env.get(ENV_PREFER_LOCAL_TIMEOUT) or "").strip()
    if raw:
        try:
            timeout = float(raw) if float(raw) > 0 else timeout
        except ValueError:
            LOGGER.warning("%s=%r is not a number; using %.1fs",
                           ENV_PREFER_LOCAL_TIMEOUT, raw, timeout)

    probe = probe_endpoint(base_url, model=model, api_key=api_key,
                           timeout=timeout)
    if not probe.reachable:
        LOGGER.warning(
            "%s is on but the local endpoint %s did not answer (%s); leaving the "
            "chain as configured: %s. The gateway serves either way - a local "
            "endpoint that is down must not stop it booting.",
            ENV_PREFER_LOCAL, base_url, probe.detail, ",".join(names) or "empty")
        return env, names, LocalPreference(
            enabled=True, probed=True, reachable=False, base_url=base_url,
            model=model or None, inherited_from_target=inherited,
            action="left the chain unchanged", detail=probe.detail)

    if not model:
        # The link will be built with DEFAULT_LOCAL_MODEL, which is a guess and
        # documented as one. Said out loud here because the symptom otherwise is
        # every Stage-3 judge call 404ing against the endpoint that was just
        # confirmed to be up, which reads as a platform fault rather than a
        # missing variable.
        LOGGER.warning(
            "%s put %s at the front of the judge chain but no LOCAL_MODEL (or "
            "%s) is set, so judge calls will use the UNVERIFIED default %r - set "
            "the model id this endpoint actually serves",
            ENV_PREFER_LOCAL, base_url, TARGET_MODEL, DEFAULT_LOCAL_MODEL)

    action = ("moved to the front" if "local" in names
              else "inserted at the front")
    reordered = ["local"] + [name for name in names if name != "local"]
    if inherited:
        # A COPY. Mutating the caller's env - which is `os.environ` in the
        # default case - would make a chain-ordering decision leak into every
        # other reader of the process environment.
        env = {**env, "LOCAL_BASE_URL": base_url}
        if model:
            env["LOCAL_MODEL"] = model
        if api_key:
            env["LOCAL_API_KEY"] = api_key
    LOGGER.info(
        "%s: the local endpoint %s answered (%s), so `local` was %s of the judge "
        "chain: %s -> %s. Reason: judge calls send the FLAGGED CONTENT to "
        "whichever provider serves them, and local is the only one that keeps it "
        "on this network.%s",
        ENV_PREFER_LOCAL, base_url, probe.detail, action,
        ",".join(names) or "empty", ",".join(reordered),
        f" LOCAL_BASE_URL was unset, so it inherited {TARGET_BASE_URL}."
        if inherited else "")
    return env, reordered, LocalPreference(
        enabled=True, probed=True, reachable=True, base_url=base_url,
        model=model or None, inherited_from_target=inherited, action=action,
        detail=probe.detail)


def from_env(env: dict[str, str] | None = None,
             skipped: list[str] | None = None) -> JudgeProvider | None:
    """Build the configured chain, or None.

    None is the default and a legitimate steady state: it means every judge rail
    reports `unjudged`, the coverage report says `cloud-not-configured`, and
    client-facing traffic that escalates to Stage 3 is blocked rather than passed
    unexamined. That is the honest behaviour of a gateway with no key.

    A provider named in the chain with no usable credential is SKIPPED, at WARNING
    level, and appended to `skipped` so `/healthz` can name it - see
    `_links_for`'s docstring for why that is not a boot failure. If nothing in the
    chain is usable the result is None, logged at ERROR: the operator configured a
    judge and has none, and every judge rail will report `unjudged` until they
    fix it.

    An unrecognised or repeated provider NAME does raise `ValueError`. Neither can
    be interpreted, and both are deploy-time typos rather than operational states.
    """
    env = os.environ if env is None else env
    raw = (env.get(ENV_PROVIDER) or "").strip().lower()
    names = [part.strip() for part in raw.split(",") if part.strip()]
    names = [n for n in names if n not in DISABLED_NAMES]

    # BEFORE the empty check and before any link is built, because this decides
    # the ORDER links are built in - and an operator who set the flag with an
    # empty AFNI_JUDGE_PROVIDER has still said "judge locally when local is up",
    # so a reachable local endpoint stands up a local-only chain rather than
    # nothing. A local endpoint that does not answer leaves every path below
    # exactly as it was.
    env, names, preference = _prefer_local(env, names)

    if not names:
        LOGGER.info("no judge provider configured (%s unset or none): every "
                    "Stage-3 judge rail will report unjudged, which fails closed",
                    ENV_PROVIDER)
        return None

    unknown = [n for n in names if n not in KNOWN_PROVIDERS]
    if unknown:
        raise ValueError(
            f"{ENV_PROVIDER} names unknown provider(s) {unknown}; known: "
            f"{list(KNOWN_PROVIDERS)}")
    if len(set(names)) != len(names):
        # A repeated provider would mean the same keys tried twice, which is a
        # config mistake rather than extra resilience.
        raise ValueError(f"{ENV_PROVIDER}={raw!r} repeats a provider")

    timeout = _timeout_from_env(env=env)
    links: list[tuple[JudgeProvider, str, int]] = []
    skipped = [] if skipped is None else skipped
    for name in names:
        try:
            links.extend(_links_for(name, env, timeout))
        except UnusableProvider as exc:
            skipped.append(str(exc))
            LOGGER.warning("skipping judge provider %s: %s - the remaining chain "
                           "still serves, and every judge rail reports unjudged if "
                           "none of it does", name, exc)

    if not links:
        LOGGER.error("%s=%r but no provider in it is usable (%s): every Stage-3 "
                     "judge rail will report unjudged, which fails closed. Stage 1 "
                     "and Stage 2 are unaffected and this gateway still serves.",
                     ENV_PROVIDER, raw, "; ".join(skipped))
        return None

    chain = JudgeChain(links, prefer_local=preference)
    LOGGER.info("judge chain configured: %s (model ids NOT verified against a "
                "live endpoint)", " -> ".join(chain.links))
    return chain


# --------------------------------------------------------------------------- #
# Binding a provider to the judge rails                                        #
# --------------------------------------------------------------------------- #
# The question each mounted Stage-3 judge rail asks, keyed by rail name.
#
# An explicit map rather than duck-typing over "has a `judge` attribute", for two
# reasons. A judge needs a question, and a generic binder would have nothing to
# ask. And the judge signatures are not interchangeable: Fairness's
# `hai_guardrails.bias_detection` returns a dict, so handing it a float judge
# would raise inside the rail on every request. A rail absent from this map keeps
# `judge=None` and reports `unjudged`, which is the fail-closed default.
#
# Prompts follow the upstream wording the rails cite, so the question a paid model
# is asked matches the detector the platform claims to be running.
JUDGE_PROMPTS: dict[str, str] = {
    # hai-guardrails src/guards/toxic.guard.ts / profanity.guard.ts:21-27 - an
    # LLM prompt with a 0-1 score and no wordlist behind it.
    "content_safety.toxicity_judge": (
        "You are a content-safety judge. Rate how toxic, hateful, harassing, "
        "sexually explicit or profane the user's text is."
    ),
    # deepteam/metrics/pii/pii.py:27 - "did the output DISCLOSE personal data",
    # which is a different question from "does this contain an SSN".
    "privacy.pii_leakage_judge": (
        "You are a privacy judge. Rate the extent to which the text discloses "
        "personal data about an identifiable person - including confirming or "
        "denying facts about them - rather than merely mentioning that such "
        "data exists."
    ),
}


def make_judge(provider: JudgeProvider, prompt: str) -> Callable[[str], float]:
    """Adapt `score(prompt, text)` to the `Callable[[str], float]` the rails take.

    Exceptions are NOT caught here. The rails already wrap their judge call and
    turn any failure into `RailResult.unjudged(...)`; swallowing it here would
    have to invent a number to return, and there is no honest number for "the
    judge did not answer".
    """
    def judge(text: str) -> float:
        return provider.score(prompt, text)

    judge.__doc__ = f"{getattr(provider, 'name', 'judge')} judge for: {prompt[:60]}"
    return judge


def bind_judges(rails: Sequence[Any], provider: JudgeProvider | None,
                prompts: dict[str, str] | None = None) -> list[Any]:
    """Return the rail list with a judge attached to every rail that takes one.

    Returns COPIES of the affected rails. The tenet packages expose module-level
    singletons (`TOXICITY_JUDGE_RAIL`, `JUDGE_RAIL`), and mutating those would
    reconfigure every other consumer in the process - the CLI, the test suite,
    another app instance in the same worker. `copy.copy` gives this gateway its
    own instance with its own `judge` and leaves the singleton untouched.

    With `provider=None` the list comes back unchanged, so an unconfigured
    gateway is bit-for-bit the gateway that existed before this module.
    """
    if provider is None:
        return list(rails)
    prompts = JUDGE_PROMPTS if prompts is None else prompts
    out: list[Any] = []
    for rail in rails:
        prompt = prompts.get(getattr(rail, "name", ""))
        if prompt is None or not hasattr(rail, "judge"):
            out.append(rail)
            continue
        bound = copy.copy(rail)
        bound.judge = make_judge(provider, prompt)
        LOGGER.info("bound %s judge to rail %s", getattr(provider, "name", "?"),
                    rail.name)
        out.append(bound)
    return out


def unbound_judge_rails(rails: Iterable[Any]) -> list[str]:
    """Names of the rails that take a judge and do not have one.

    This is what `/healthz` reports. Each of these returns `unjudged` for every
    payload string it is handed, which on client-facing traffic is a block - so
    it is a fact an operator needs before wondering why Stage 3 blocks
    everything.
    """
    return sorted(rail.name for rail in rails
                  if hasattr(rail, "judge") and getattr(rail, "judge") is None)
