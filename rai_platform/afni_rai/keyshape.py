# -*- coding: utf-8 -*-
"""Does this credential LOOK like the credential this provider wants?

WHY THIS EXISTS. A key of the wrong shape is indistinguishable, at boot, from a
key of the right shape. `from_env` builds the link, `/healthz` reports the chain,
preflight says `set` - and then every Stage-3 judge call fails at call time with
`JudgeLinkFailed`, the rail reports `unjudged`, and the request fails closed. The
symptom is "the platform blocks everything", three layers away from the cause.

That happened here with a Google credential of the form `AQ.…` - an OAuth access
token, which is a real Google credential and not the one AI Studio's
`?key=` parameter accepts. It is a class of mistake worth one line at startup.

WHAT THIS IS NOT. It is not validation and it cannot be: only the vendor can say
whether a key is live, and a key that matches every rule here may still be
revoked. So nothing raises, nothing is skipped, and a key that fails these
checks is still tried against the provider - the vendor's 401 remains the
authority. This narrows "it doesn't work" to "it isn't the right kind of thing",
which is the part a person can act on without a support ticket.

THE VALUE NEVER APPEARS IN THE OUTPUT. Not the key, not a prefix of it, not a
masked form. Only its LENGTH and a verdict, because a shape report that quotes
the first eight characters of a credential is a shape report that ends up in a
log, a screenshot and a support thread. Length is already the most this should
say - it is why `TargetConfig.describe()` reports a boolean rather than a length
- and it is included only because "39 expected, 48 given" is often the whole
diagnosis.

Formats are the vendors' published ones. Where a variable legitimately serves
more than one vendor - `OPENAI_API_KEYS` also covers Azure OpenAI and any
OpenAI-compatible gateway - the expectation is DROPPED rather than guessed, since
a check that fires on a correct Azure key teaches its reader to ignore it.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Google AI Studio keys: `AIza` + 35 more.
_AI_STUDIO_PREFIX = "AIza"
_AI_STUDIO_LENGTH = 39

#: Every OpenAI key kind: user, project, service account, admin.
_OPENAI_PREFIX = "sk-"

#: api.openai.com is the only host whose key shape is OpenAI's to define. Azure
#: OpenAI (32 hex chars) and LiteLLM/vLLM gateways (anything at all) use the same
#: variable, so pointing the base URL elsewhere drops the prefix expectation.
_OPENAI_HOSTS = ("api.openai.com",)


@dataclass(frozen=True)
class Shape:
    """One verdict. `ok=True` also covers "no expectation to check against"."""

    ok: bool
    #: Safe to log: a verdict and a length, never any part of the value.
    detail: str
    #: What to do about it, when there is something to do.
    remedy: str = ""

    @property
    def suspect(self) -> bool:
        return not self.ok


def _lengths(values: list[str]) -> str:
    return ", ".join(f"{len(v)} chars" for v in values)


def openai_keys(values: list[str], base_url: str = "") -> Shape:
    if not values:
        return Shape(True, "no key set")
    host = base_url.split("//")[-1].split("/")[0].lower()
    if host and host not in _OPENAI_HOSTS:
        # Azure OpenAI, LiteLLM, vLLM, or any other OpenAI-compatible gateway.
        # Their key shapes are not OpenAI's to define, so there is nothing to
        # check and saying so beats inventing a rule.
        return Shape(True, f"{len(values)} key(s), {_lengths(values)} - shape not "
                           f"checked: OPENAI_BASE_URL points at {host}, not "
                           f"api.openai.com")
    wrong = [i for i, v in enumerate(values) if not v.startswith(_OPENAI_PREFIX)]
    if wrong:
        return Shape(
            False,
            f"{len(values)} key(s), {_lengths(values)}; entry "
            f"{', '.join(str(i + 1) for i in wrong)} does not begin `sk-`",
            "Every OpenAI key kind begins `sk-` (`sk-proj-` for a project key). "
            "A 32-character hex string is an AZURE OpenAI key - correct, but "
            "then OPENAI_BASE_URL must point at your Azure resource.")
    return Shape(True, f"{len(values)} key(s), {_lengths(values)}, `sk-` prefix")


def google_keys(values: list[str]) -> Shape:
    """AI Studio keys only. The key travels in the URL as `?key=`, which is
    exactly where an OAuth bearer token does not work."""
    if not values:
        return Shape(True, "no key set")
    wrong = [i for i, v in enumerate(values)
             if not (v.startswith(_AI_STUDIO_PREFIX)
                     and len(v) == _AI_STUDIO_LENGTH)]
    if wrong:
        return Shape(
            False,
            f"{len(values)} key(s), {_lengths(values)}; entry "
            f"{', '.join(str(i + 1) for i in wrong)} is not the shape of a "
            f"Google AI Studio key ({_AI_STUDIO_PREFIX}… , "
            f"{_AI_STUDIO_LENGTH} chars)",
            "Create an API key at aistudio.google.com/apikey - it looks like "
            "`AIza…`. An `AQ.…` or `ya29.…` value is an OAuth ACCESS TOKEN: a "
            "real Google credential, but this platform sends the key as "
            "`?key=` on generativelanguage.googleapis.com, which accepts an API "
            "key only. A token would also expire within the hour. Vertex AI "
            "does use OAuth, and this platform has no Vertex adapter.")
    return Shape(True, f"{len(values)} key(s), {_AI_STUDIO_LENGTH} chars, "
                       f"`{_AI_STUDIO_PREFIX}` prefix")


def azure_content_safety_key(value: str) -> Shape:
    """32 hex characters. Azure's portal shows two, either of which works."""
    if not value:
        return Shape(True, "no key set")
    hexish = len(value) == 32 and all(c in "0123456789abcdefABCDEF" for c in value)
    if not hexish:
        return Shape(
            False, f"{len(value)} chars; not the 32 hex characters an Azure "
                   f"Content Safety key is",
            "Copy KEY 1 from the resource's Keys and Endpoint blade. An "
            "endpoint URL pasted into the key field is the usual cause.")
    return Shape(True, "32 hex chars")


def report(env: dict[str, str]) -> dict[str, Shape]:
    """Every credential this platform reads, keyed by variable name.

    Only variables that are SET appear, so an unconfigured platform produces an
    empty report rather than a list of complaints about optional providers.
    """
    def split(name: str, alias: str) -> list[str]:
        raw = env.get(name) or env.get(alias) or ""
        return [part.strip() for part in raw.split(",") if part.strip()]

    out: dict[str, Shape] = {}
    openai = split("OPENAI_API_KEYS", "OPENAI_API_KEY")
    if openai:
        out["OPENAI_API_KEYS"] = openai_keys(
            openai, (env.get("OPENAI_BASE_URL") or "").strip())
    google = split("GOOGLE_API_KEYS", "GOOGLE_API_KEY")
    if google:
        out["GOOGLE_API_KEYS"] = google_keys(google)
    azure = (env.get("AZURE_CONTENT_SAFETY_KEY") or "").strip()
    if azure:
        out["AZURE_CONTENT_SAFETY_KEY"] = azure_content_safety_key(azure)
    return out
