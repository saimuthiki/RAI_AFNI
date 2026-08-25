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
from typing import Any, Callable, Iterable, Protocol, Sequence, runtime_checkable

LOGGER = logging.getLogger("afni_rai.gateway.providers")

# Environment variable names, in one place so the docs above and the code below
# cannot drift.
ENV_PROVIDER = "AFNI_JUDGE_PROVIDER"
ENV_TIMEOUT = "AFNI_JUDGE_TIMEOUT"

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


class JudgeUnavailable(RuntimeError):
    """The judge could not produce a usable score.

    Raised for a timeout, a transport error, an HTTP error, a missing choice in
    the response, and an unparseable or out-of-range number - all of them the
    same fact as far as the cascade is concerned: nobody looked. The rails catch
    this and return `RailResult.unjudged(...)`, so it becomes a block on
    client-facing traffic instead of a silent pass.
    """


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


def _timeout_from_env(default: float = DEFAULT_TIMEOUT) -> float:
    raw = os.environ.get(ENV_TIMEOUT)
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

    def __init__(self, *, model: str, base_url: str, timeout: float) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self._client: Any = None

    # httpx is imported inside the property so that importing this module - which
    # `app.py` does unconditionally - needs nothing installed.
    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx  # noqa: PLC0415 - deliberately lazy

            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _post(self, url: str, *, json: dict, headers: dict) -> dict:
        try:
            response = self.client.post(url, json=json, headers=headers)
        except Exception as exc:  # noqa: BLE001 - httpx errors, DNS, TLS, timeout
            # `exc` may name the host but never a credential: keys travel in
            # headers and query params that are not echoed here.
            raise JudgeUnavailable(
                f"{self.name} judge call failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise JudgeUnavailable(
                f"{self.name} judge returned HTTP {response.status_code}")
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
                 name: str = "openai") -> None:
        super().__init__(model=model, base_url=base_url, timeout=timeout)
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
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__(model=model, base_url=base_url, timeout=timeout)
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
                timeout: float = DEFAULT_TIMEOUT) -> OpenAICompatibleJudge:
    """A local inference server - Ollama, vLLM, llama.cpp - reached over the
    OpenAI-compatible shape they all expose.

    A function rather than a class because there is genuinely no behaviour
    difference from `OpenAICompatibleJudge`; a subclass would exist only to hold
    a different name, and a second implementation of the same POST would be one
    more place for the two to diverge.
    """
    return OpenAICompatibleJudge(model=model, base_url=base_url,
                                 api_key=api_key, timeout=timeout, name="local")


# --------------------------------------------------------------------------- #
# Selection                                                                    #
# --------------------------------------------------------------------------- #
KNOWN_PROVIDERS = ("none", "openai", "gemini", "local")


def from_env(env: dict[str, str] | None = None) -> JudgeProvider | None:
    """Build the configured judge, or None.

    None is the default and a legitimate steady state: it means every judge rail
    reports `unjudged`, the coverage report says `cloud-not-configured`, and
    client-facing traffic that escalates to Stage 3 is blocked rather than passed
    unexamined. That is the honest behaviour of a gateway with no key.

    An unrecognised provider name, or a named provider with no credential, raises
    `ValueError`. Both are configuration mistakes, and a gateway should refuse to
    boot on them rather than serve traffic that quietly never reaches a judge.
    """
    env = os.environ if env is None else env
    name = (env.get(ENV_PROVIDER) or "none").strip().lower()
    if name in ("", "none", "off", "disabled"):
        LOGGER.info("no judge provider configured (%s unset): every Stage-3 "
                    "judge rail will report unjudged, which fails closed",
                    ENV_PROVIDER)
        return None
    if name not in KNOWN_PROVIDERS:
        raise ValueError(
            f"{ENV_PROVIDER}={name!r} is not one of {list(KNOWN_PROVIDERS)}")

    timeout = _timeout_from_env()

    if name == "openai":
        key = env.get("OPENAI_API_KEY")
        if not key:
            raise ValueError(
                f"{ENV_PROVIDER}=openai but OPENAI_API_KEY is unset - refusing to "
                "boot a gateway that believes it has a judge and does not")
        provider: JudgeProvider = OpenAICompatibleJudge(
            model=env.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
            base_url=env.get("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL,
            api_key=key, timeout=timeout)
    elif name == "gemini":
        key = env.get("GOOGLE_API_KEY")
        if not key:
            raise ValueError(
                f"{ENV_PROVIDER}=gemini but GOOGLE_API_KEY is unset - refusing to "
                "boot a gateway that believes it has a judge and does not")
        provider = GeminiJudge(
            api_key=key,
            model=env.get("GOOGLE_MODEL") or DEFAULT_GEMINI_MODEL,
            base_url=env.get("GOOGLE_BASE_URL") or DEFAULT_GEMINI_BASE_URL,
            timeout=timeout)
    else:  # local
        base_url = env.get("LOCAL_BASE_URL")
        if not base_url:
            raise ValueError(
                f"{ENV_PROVIDER}=local but LOCAL_BASE_URL is unset - there is no "
                "sensible default for someone else's inference server")
        provider = local_judge(
            base_url=base_url,
            model=env.get("LOCAL_MODEL") or DEFAULT_LOCAL_MODEL,
            api_key=env.get("LOCAL_API_KEY"),
            timeout=timeout)

    LOGGER.info("judge provider %s configured, model %s (model id NOT verified "
                "against a live endpoint)", name, getattr(provider, "model", "?"))
    return provider


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
