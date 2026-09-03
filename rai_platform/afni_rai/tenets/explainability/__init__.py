# -*- coding: utf-8 -*-
"""
Explainability & Transparency rails.

This tenet is the one where an honest answer looks thin. Of the 13 reviewed
tools that contribute to it (docs/frameworks.md, "Explainability &
Transparency"), six are Batch/Offline and two are LLM judges. SHAP, LIME and
AIF360's FACTS are classical-ML tooling whose cost scales with samples x
features; putting any of them in a request path would be a latency incident, and
tenets.md already says where they belong: *"Runs as: async `explain` endpoint
backed by a background job - SHAP is too slow for synchronous request
handling."* They are registered here as OFFLINE, deliberately, and no rail wraps
them.

What *is* genuinely runtime for this tenet is not model explanation at all. It is
explaining the **guardrail**:

  1. `SchemaExplainRail`      why a structured output failed its schema - which
                              field, what was expected, what type arrived
  2. `FormatValidatorRail`    the deterministic format family (length, regex,
                              choices, URL, one-line, numeric range, ...)
  3. `confidence_breakdown()` one per-check confidence table across every rail
                              that judged the request

A fourth, `RubricJudgeRail`, adapts DeepEval's G-Eval at Stage 3 and is written
but deliberately not mounted - it needs a paid judge, and it degrades to
`unjudged` rather than to clean when it cannot run.

(3) is not a rail. It consumes the finished `Verdict` and the rail attributions,
so it sits beside `contract/explanation.py` rather than inside the cascade. It is
a port of Safe Zone's `ConfidenceExplanation`
(references/safe-zone-main/safe-zone-main/internal/models/confidence_explanation.go:4-22),
generalised from that struct's two sources (regex_score, ai_score) to the four
`CONFIDENCE_KINDS` this platform actually has.

Every rail here is Stage 1 and pure stdlib - `json`, `re`, `hashlib`,
`unicodedata`, `urllib.parse`. Nothing in this module imports a third-party
package, at import time or later, and nothing touches the network.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ...cascade.rail import Direction, Rail, RailResult, Stage
from ...contract.explanation import RailAttribution, explain
from ...contract.models import Action, Decision, Finding, Severity, Tenet, Verdict
from ...registry.capabilities import Coverage

TENET = Tenet.EXPLAINABILITY

_MAX_VIOLATIONS = 25   # a malformed 10k-field payload must not emit 10k findings
_MAX_DEPTH = 12


def _fp(subject: str) -> str:
    """Fingerprint an operator keys a false-positive exception on.

    A hash, never the value - `contract/models.py` is explicit that findings MUST
    NOT carry per-span echoes of matched text.
    """
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]


# ===========================================================  schema explainer =
# Guardrails AI is the best pick for this capability and the reason is one
# function: `validate_against_schema`
# (references/guardrails-main/guardrails-main/guardrails/schema/validator.py:18-38)
# collects `{error.json_path: [messages]}` from a Draft-2020-12 validator instead
# of returning a bool. That per-field dict *is* the explanation, and it is what
# gets ported below - a stdlib subset of Draft 2020-12, because Stage 1 may not
# import `jsonschema`.
#
# Deliberately a subset. It covers the keywords an LLM output contract actually
# uses (type/required/properties/enum/const/bounds/pattern/items/
# additionalProperties) and silently ignores the rest ($ref, oneOf, allOf,
# if/then, unevaluated*). A schema using those is under-checked, not
# mis-checked, which is why `SchemaExplainRail` reports `strict_keywords_only`
# and a deployment with such a schema should escalate to the real `jsonschema`
# in an offline job.

_SUPPORTED_KEYWORDS = frozenset({
    "type", "required", "properties", "additionalProperties", "items",
    "enum", "const", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minLength", "maxLength", "pattern", "minItems",
    "maxItems", "title", "description", "default", "examples", "$schema",
    "$id",
})

_VIOLATION_CATEGORY = {
    "type": "x.afni.schema.type_mismatch",
    "required": "x.afni.schema.missing_required",
    "enum": "x.afni.schema.enum_violation",
    "const": "x.afni.schema.const_violation",
    "minimum": "x.afni.schema.range_violation",
    "maximum": "x.afni.schema.range_violation",
    "exclusiveMinimum": "x.afni.schema.range_violation",
    "exclusiveMaximum": "x.afni.schema.range_violation",
    "minLength": "x.afni.schema.length_violation",
    "maxLength": "x.afni.schema.length_violation",
    "pattern": "x.afni.schema.pattern_violation",
    "minItems": "x.afni.schema.item_count_violation",
    "maxItems": "x.afni.schema.item_count_violation",
    "additionalProperties": "x.afni.schema.unexpected_property",
    "json": "x.afni.schema.malformed_json",
}


@dataclass(frozen=True)
class SchemaViolation:
    """One reason a payload failed, at one location.

    `received` is a JSON *type name* or a *count*, never the value that arrived.
    That is the whole reason this dataclass exists rather than a string: the
    explanation has to be safe to log, and "expected integer, received string"
    is, while "expected integer, received 123-45-6789" is not.
    """

    json_path: str
    keyword: str
    expected: str
    received: str

    @property
    def category(self) -> str:
        return _VIOLATION_CATEGORY.get(self.keyword, "x.afni.schema.type_mismatch")

    @property
    def message(self) -> str:
        return f"{self.json_path}: expected {self.expected}, received {self.received}"


def _json_type(value: Any) -> str:
    """JSON Schema type name for a Python value.

    `bool` before `int` on purpose - `isinstance(True, int)` is True in Python,
    so the naive order reports `true` as an integer and lets a boolean through an
    `{"type": "integer"}` contract.
    """
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def _type_ok(value: Any, expected: str) -> bool:
    actual = _json_type(value)
    if expected == "number":          # every integer is a valid number
        return actual in ("integer", "number")
    return actual == expected


def _truncate(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def unsupported_keywords(schema: Any, _depth: int = 0) -> set[str]:
    """Schema keywords this stdlib subset does not implement.

    Reported rather than ignored: a deployment whose contract leans on `oneOf`
    needs to know it is being under-checked here, which is the difference
    between a gap it can see and one it cannot.
    """
    found: set[str] = set()
    if _depth > _MAX_DEPTH or not isinstance(schema, dict):
        return found
    for key, value in schema.items():
        if key not in _SUPPORTED_KEYWORDS:
            found.add(key)
        if key == "properties" and isinstance(value, dict):
            for sub in value.values():
                found |= unsupported_keywords(sub, _depth + 1)
        elif key in ("items", "additionalProperties"):
            found |= unsupported_keywords(value, _depth + 1)
    return found


def validate_schema(instance: Any, schema: Any, path: str = "$",
                    _depth: int = 0) -> list[SchemaViolation]:
    """A stdlib Draft-2020-12 subset that returns *why*, per field.

    Ported from Guardrails AI's `validate_against_schema`
    (references/guardrails-main/guardrails-main/guardrails/schema/validator.py:26-32),
    which iterates `validator.iter_errors(payload)` and keys the messages by
    `error.json_path`. Same shape, same `$.a.b[0]` path vocabulary, no
    dependency.
    """
    out: list[SchemaViolation] = []
    if not isinstance(schema, dict) or _depth > _MAX_DEPTH:
        return out

    if "type" in schema:
        allowed = schema["type"]
        allowed = [allowed] if isinstance(allowed, str) else list(allowed)
        if not any(_type_ok(instance, t) for t in allowed):
            # Return immediately: every other keyword on this node is written
            # for the declared type, so checking `maxLength` on an integer would
            # produce a second, misleading violation for one real error.
            return [SchemaViolation(path, "type", " or ".join(allowed),
                                    _json_type(instance))]

    if "const" in schema and instance != schema["const"]:
        out.append(SchemaViolation(path, "const", f"the constant {schema['const']!r}",
                                   f"a different {_json_type(instance)}"))
    if "enum" in schema and instance not in schema["enum"]:
        choices = _truncate(", ".join(repr(c) for c in schema["enum"]))
        out.append(SchemaViolation(path, "enum", f"one of [{choices}]",
                                   f"an unlisted {_json_type(instance)}"))

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            out.append(SchemaViolation(path, "minLength",
                                       f"at least {schema['minLength']} chars",
                                       f"{len(instance)} chars"))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            out.append(SchemaViolation(path, "maxLength",
                                       f"at most {schema['maxLength']} chars",
                                       f"{len(instance)} chars"))
        if "pattern" in schema:
            try:
                # JSON Schema `pattern` is a partial match, so `search`, not
                # `fullmatch` - the same distinction Guardrails AI's RegexMatch
                # exposes as `match_type`
                # (tests/integration_tests/test_assets/validators/regex_match.py:41-46).
                if re.search(schema["pattern"], instance) is None:
                    out.append(SchemaViolation(
                        path, "pattern", f"a match for /{schema['pattern']}/",
                        f"a non-matching string of {len(instance)} chars"))
            except re.error as exc:
                out.append(SchemaViolation(path, "pattern",
                                           "a compilable regex in the schema",
                                           f"re.error: {exc}"))

    if _json_type(instance) in ("integer", "number"):
        for key, ok, word in (("minimum", instance >= schema.get("minimum", instance), ">="),
                              ("maximum", instance <= schema.get("maximum", instance), "<="),
                              ("exclusiveMinimum",
                               instance > schema.get("exclusiveMinimum", instance - 1), ">"),
                              ("exclusiveMaximum",
                               instance < schema.get("exclusiveMaximum", instance + 1), "<")):
            if key in schema and not ok:
                out.append(SchemaViolation(path, key, f"a value {word} {schema[key]}",
                                           "an out-of-range number"))

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            out.append(SchemaViolation(path, "minItems",
                                       f"at least {schema['minItems']} items",
                                       f"{len(instance)} items"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            out.append(SchemaViolation(path, "maxItems",
                                       f"at most {schema['maxItems']} items",
                                       f"{len(instance)} items"))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                out += validate_schema(item, item_schema, f"{path}[{i}]", _depth + 1)

    if isinstance(instance, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or ():
            if key not in instance:
                out.append(SchemaViolation(f"{path}.{key}", "required",
                                           "the property to be present", "nothing"))
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    out.append(SchemaViolation(f"{path}.{key}", "additionalProperties",
                                               "no property beyond the declared set",
                                               "an undeclared property"))
        for key, sub_schema in properties.items():
            if key in instance:
                out += validate_schema(instance[key], sub_schema,
                                       f"{path}.{key}", _depth + 1)

    return out[:_MAX_VIOLATIONS]


def _looks_like_a_json_document(text: str) -> bool:
    """Conservative on purpose.

    LLM Guard's JSON scanner regex-hunts every `{...}` candidate anywhere in the
    output and validates each one
    (references/llm-guard-main/llm-guard-main/llm_guard/output_scanners/json.py:11,
    :35, :77). On free prose that finds braces in code samples and f-string
    placeholders and reports them as broken JSON - a false-positive storm on a
    rail that runs on 100% of traffic. So this only claims a payload *is* a JSON
    document when the whole trimmed string is delimited like one.
    """
    stripped = text.strip()
    return len(stripped) >= 2 and (
        (stripped[0] == "{" and stripped[-1] == "}")
        or (stripped[0] == "[" and stripped[-1] == "]")
    )


class SchemaExplainRail:
    """Stage 1. Explains *why* a structured output failed, not merely that it did.

    Two things it does, in order:

      no schema configured  a payload that is delimited like a whole JSON
                            document but does not parse is reported as
                            `x.afni.schema.malformed_json`. This is the zero-config
                            check and it is real - the JSON decoder's own message
                            ("Expecting ',' delimiter: line 1 column 10") names the
                            position and carries no payload content.
      schema configured     every failing field gets its own finding, categorised
                            by the keyword that failed, with `subject` reading
                            "$.items[0].price: expected integer, received string".

    `subject` is the only field carrying free text, per the platform rule, and it
    is safe to carry: a JSON path plus type names and counts. The value that
    arrived never appears anywhere in the finding.

    Coordination note - deliberate overlap, with a switch. The `hallucination`
    tenet's `StructuredOutputRail` owns Stage-1 *well-formedness*: JSON and XML,
    candidate spans, `expect` modes, `x.afni.structured_output.*`. This rail owns
    *schema conformance*, and explains it per field. The one place they meet is a
    malformed JSON document, which both would report - different categories,
    different detectors, one consolidated verdict, so an operator can tell them
    apart. A deployment running both and wanting a single voice on
    well-formedness constructs this one with `report_malformed=False`; it then
    speaks only about schema conformance.
    """

    name = "afni-schema-explain"
    tenet = TENET
    stage = Stage.STAGE_1
    # Explains which field of the MODEL's structured output failed
    # validation.
    direction = Direction.OUTPUT

    def __init__(self, schema: dict[str, Any] | None = None,
                 paths: Sequence[str] = (), block_on_failure: bool = False,
                 assume_json: bool = False, report_malformed: bool = True) -> None:
        self._schema = schema
        self._report_malformed = report_malformed
        self._paths = tuple(paths)
        self._block = block_on_failure
        # `assume_json` drops the delimiter heuristic for the paths this rail
        # applies to: a deployment that KNOWS a path carries JSON wants a
        # truncated stream ('{"a": 1' with no closing brace) reported, and the
        # heuristic cannot see that without also flagging every prose payload
        # that opens with a brace. Off by default, and pointless without
        # `paths` - so it raises rather than silently flagging all traffic.
        if assume_json and not paths:
            raise ValueError("assume_json needs explicit paths; enabling it for every "
                             "payload path would report all prose as malformed JSON")
        self._assume_json = assume_json
        self.unsupported = sorted(unsupported_keywords(schema)) if schema else []

    @property
    def configured(self) -> bool:
        return self._schema is not None

    def _applies(self, path: str) -> bool:
        if not self._paths:
            return True
        return any(path == p or path.endswith("." + p) for p in self._paths)

    def _finding(self, path: str, category: str, subject: str,
                 severity: Severity) -> Finding:
        return Finding(
            category=category,
            severity=severity,
            action=Action.BLOCK if self._block else Action.FLAG,
            path=path,
            detector=self.name,
            subject=subject,
            fp=_fp(subject),
        )

    def check(self, path: str, text: str) -> RailResult:
        if not self._applies(path):
            return RailResult.clean()
        if not (self._assume_json or _looks_like_a_json_document(text)):
            # Nothing to judge is not the same as a failure to judge: this rail
            # has an opinion only about payloads that claim to be structured.
            return RailResult.clean()

        try:
            parsed = json.loads(text)
        except ValueError as exc:
            if not self._report_malformed:
                # Handed over to the hallucination tenet's well-formedness rail.
                # Silent here, but not silent in the gateway - that rail reports
                # it, which is the whole point of handing the check over.
                return RailResult.clean()
            subject = f"{path}: not parseable as JSON - {exc}"
            return RailResult(
                findings=[self._finding(path, "x.afni.schema.malformed_json",
                                        subject, Severity.MEDIUM)],
                block=self._block,
                reason=subject,
            )

        if self._schema is None:
            return RailResult.clean()

        violations = validate_schema(parsed, self._schema)
        if not violations:
            return RailResult.clean()
        return RailResult(
            findings=[self._finding(path, v.category, f"{path} {v.message}",
                                    Severity.MEDIUM) for v in violations],
            block=self._block,
            reason=f"{len(violations)} schema violation(s) at {path}",
        )


# ========================================================  format validators ==
# The deterministic family. Guardrails AI carries these as integration-test
# fixtures rather than shipped validators
# (references/guardrails-main/guardrails-main/tests/integration_tests/test_assets/validators/),
# and Safe Zone dispatches BUILTIN / REGEX / SCHEMA validator types by name from
# a database row
# (references/safe-zone-main/safe-zone-main/internal/guardrails/validators.go:48-80).
# Neither is importable as a library. This is the same set, as data.

_WORDS_PER_MINUTE = 200   # reading_time.py:44 - len(value.split()) / 200


@dataclass(frozen=True)
class FormatRule:
    """One named deterministic check.

    `paths` empty means "every payload path". A URL rule that fires on prose is
    a false-positive machine, so a rule that is not universal must say where it
    applies.
    """

    name: str
    kind: str
    paths: tuple[str, ...] = ()
    severity: Severity = Severity.LOW
    action: Action = Action.FLAG
    min: float | None = None
    max: float | None = None
    pattern: str | None = None
    match_type: str = "fullmatch"      # regex_match.py:41-46
    choices: tuple[Any, ...] = ()

    def applies_to(self, path: str) -> bool:
        if not self.paths:
            return True
        return any(path == p or path.endswith("." + p) for p in self.paths)


def _v(rule: FormatRule, expected: str, received: str) -> str:
    return f"{rule.name}: expected {expected}, received {received}"


def _check_rule(rule: FormatRule, text: str) -> str | None:
    """Return a redaction-safe reason string, or None when the text passes.

    Every branch reports lengths, counts and type names. None of them report the
    text.
    """
    kind = rule.kind

    if kind == "length":                                     # valid_length.py:17
        n = len(text)
        if rule.min is not None and n < rule.min:
            return _v(rule, f"at least {int(rule.min)} chars", f"{n} chars")
        if rule.max is not None and n > rule.max:
            return _v(rule, f"at most {int(rule.max)} chars", f"{n} chars")
        return None

    if kind == "regex_match":                                # regex_match.py:16
        if rule.pattern is None:
            return None
        try:
            compiled = re.compile(rule.pattern)
        except re.error as exc:
            return _v(rule, "a compilable regex in the rule", f"re.error: {exc}")
        matcher = compiled.fullmatch if rule.match_type == "fullmatch" else compiled.search
        if matcher(text) is None:
            return _v(rule, f"a {rule.match_type} for /{rule.pattern}/",
                      f"a non-matching string of {len(text)} chars")
        return None

    if kind == "valid_choices":                              # valid_choices.py:13
        if text not in rule.choices:
            return _v(rule, f"one of {len(rule.choices)} allowed choice(s)",
                      "an unlisted value")
        return None

    if kind == "valid_url":                                  # valid_url.py:13
        try:
            parsed = urlparse(text.strip())
        except ValueError as exc:
            return _v(rule, "a parseable URL", f"ValueError: {exc}")
        if not parsed.scheme or not parsed.netloc:
            missing = "scheme" if not parsed.scheme else "netloc"
            return _v(rule, "a URL with a scheme and a netloc", f"no {missing}")
        return None

    if kind == "one_line":                                   # one_line.py:13
        lines = len(text.splitlines())
        if lines > 1:
            return _v(rule, "a single line", f"{lines} lines")
        return None

    if kind == "numeric_range":
        try:
            value = float(text.strip())
        except ValueError:
            return _v(rule, "a number", f"a non-numeric {len(text)}-char string")
        if rule.min is not None and value < rule.min:
            return _v(rule, f"a value >= {rule.min}", "a value below the minimum")
        if rule.max is not None and value > rule.max:
            return _v(rule, f"a value <= {rule.max}", "a value above the maximum")
        return None

    if kind == "lower_case":                                 # lower_case.py:13
        if text.lower() != text:
            return _v(rule, "lower case", "mixed or upper case")
        return None

    if kind == "two_words":                                  # two_words.py:15
        n = len(text.split())
        if n != 2:
            return _v(rule, "exactly two words", f"{n} words")
        return None

    if kind == "reading_time":                               # reading_time.py:44
        minutes = len(text.split()) / _WORDS_PER_MINUTE
        if rule.max is not None and minutes > rule.max:
            return _v(rule, f"readable within {rule.max} minute(s)",
                      f"{minutes:.1f} minutes at {_WORDS_PER_MINUTE} wpm")
        return None

    if kind == "valid_json":                                 # validators.go:58 BUILTIN JSON
        try:
            json.loads(text)
        except ValueError as exc:
            return _v(rule, "valid JSON", f"{type(exc).__name__}: {exc}")
        return None

    raise ValueError(f"unknown format rule kind {kind!r}")


FORMAT_KINDS = ("length", "regex_match", "valid_choices", "valid_url", "one_line",
                "numeric_range", "lower_case", "two_words", "reading_time",
                "valid_json")

# The two rules that are safe to mount with no knowledge of the deployment's
# output contract. Both are flag-only and both are about runaway generation
# rather than about a schema, so they cannot storm on ordinary traffic: a normal
# chat turn is a few hundred words, and the thresholds here are two orders of
# magnitude above that.
#
# Everything else in FORMAT_KINDS needs a contract to check against - a regex, a
# choice list, a numeric band - and inventing one would be worse than shipping
# nothing. A deployment adds them with
# `FormatValidatorRail(rules=[FormatRule("sentiment_label", "valid_choices", ...)])`.
DEFAULT_FORMAT_RULES: tuple[FormatRule, ...] = (
    FormatRule(name="reading_time_20min", kind="reading_time", max=20.0,
               severity=Severity.LOW, action=Action.FLAG),
    FormatRule(name="payload_length_100k", kind="length", max=100_000,
               severity=Severity.MEDIUM, action=Action.FLAG),
)


class FormatValidatorRail:
    """Stage 1, deterministic, zero dependency. No ML needed and none used."""

    name = "afni-format-validators"
    tenet = TENET
    stage = Stage.STAGE_1
    # Format validators check the model's output against the caller's
    # declared format. Input carries no such contract.
    direction = Direction.OUTPUT

    def __init__(self, rules: Sequence[FormatRule] = DEFAULT_FORMAT_RULES) -> None:
        for rule in rules:
            if rule.kind not in FORMAT_KINDS:
                raise ValueError(f"unknown format rule kind {rule.kind!r}; "
                                 f"known: {FORMAT_KINDS}")
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[FormatRule, ...]:
        return self._rules

    def check(self, path: str, text: str) -> RailResult:
        findings: list[Finding] = []
        block = False
        for rule in self._rules:
            if not rule.applies_to(path):
                continue
            reason = _check_rule(rule, text)
            if reason is None:
                continue
            subject = f"{path} {reason}"
            findings.append(Finding(
                category=f"x.afni.format.{rule.kind}",
                severity=rule.severity,
                action=rule.action,
                path=path,
                detector=self.name,
                subject=subject,
                fp=_fp(subject),
            ))
            if rule.action is Action.BLOCK:
                block = True
        if not findings:
            return RailResult.clean()
        return RailResult(findings=findings, block=block,
                          reason=f"{len(findings)} format rule(s) failed at {path}")


# ==============================================================  topic scope ==
# The Stage-1 half of "Ban-topics / on-topic scope". The real detectors are all
# further up the cascade:
#
#   Stage 2  LLM Guard BanTopics, zero-shot NLI against
#            MoritzLaurer/deberta-v3-large-zeroshot-v2.0 rev
#            cf44676c28ba7312e5c5f8f8d2c22b3e0c9cdae2
#            (references/llm-guard-main/llm-guard-main/llm_guard/input_scanners/ban_topics.py:13-27)
#   Stage 3  NeMo's topic_safety rail, an LLM judge to
#            nvidia/llama-3.1-nemoguard-8b-topic-control that must answer
#            "on-topic" or "off-topic"
#            (references/Guardrails-develop/nemoguardrails/library/topic_safety/actions.py:38-42,
#             examples/configs/nemoguards_v2/config.yml:11)
#
# What is free at Stage 1 is the lexicon: a banned-keyword list (LLM Guard's
# BanSubstrings, match_type "word") and an allowed-topic allowlist. Both are
# *policy*, and every reviewed tool makes the operator write it - NeMo in
# config.yml, DeepTeam as `TopicalGuard(allowed_topics=[...])`
# (references/deepteam-main/tests/test_guardrails/test_topical_guard.py:13). So
# this rail ships unconfigured and says nothing until AFNI supplies a lexicon,
# and `register()` records the capability as a GAP while that is true. An empty
# allowlist is not a judgement failure - it is an absent policy - so an
# unconfigured instance returns `clean()`, never `unjudged()`, which would
# fail-closed every client request in the gateway.

_WORD_SPLIT = re.compile(r"[^\w']+", re.UNICODE)


def _normalise(text: str) -> list[str]:
    """NFKC + casefold, then split to words. Same normalisation the privacy and
    security rails need, kept local so this module imports nothing of theirs."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return [w for w in _WORD_SPLIT.split(folded) if w]


class TopicScopeRail:
    """Stage 1 keyword/phrase scope check, with the action chosen per topic.

    TWO KINDS OF PATTERN, because one is not enough to be useful.

    A single-word keyword is matched against the word SET - exact, fast, and
    unable to match across a word boundary. That is the right shape for a slur
    or a product name, and the wrong shape for a topic: `bomb` as a bare word
    fires on "I bombed the interview", and "drug synthesis" cannot match at all
    because it is two words.

    So a pattern containing a space is matched as a PHRASE against the
    normalised text instead. That is what makes a topic list expressible without
    it being a false-positive generator.

    TWO ACTIONS, chosen per topic rather than fixed.

    The original version always emitted FLAG, on the reasoning that a lexicon hit
    is evidence for a judge rather than a verdict. That reasoning holds for a
    fuzzy topic - "is this financial advice?" genuinely needs a model - and does
    NOT hold for an unambiguous one: a request for explosive synthesis
    instructions does not need a second opinion.

    So the deployment decides. Default FLAG, which keeps the cautious behaviour
    for anything an operator merely ticks; BLOCK where the operator has said the
    phrase is unambiguous. The trade is stated in the console next to the
    control, because a blocking keyword list is the single easiest way to build a
    guardrail that refuses ordinary work.
    """

    name = "afni-topic-scope"
    tenet = TENET
    stage = Stage.STAGE_1

    def __init__(self, banned_keywords: Sequence[str] = (),
                 allowed_topic_lexicons: dict[str, Sequence[str]] | None = None,
                 min_words_for_scope: int = 8,
                 blocking_keywords: Sequence[str] = ()) -> None:
        self._banned = self._split(banned_keywords)
        self._blocking = self._split(blocking_keywords)
        self._allowed = {
            topic: {w.casefold() for w in words}
            for topic, words in (allowed_topic_lexicons or {}).items()
        }
        self._min_words = min_words_for_scope

    @staticmethod
    def _split(patterns: Sequence[str]) -> tuple[set[str], tuple[str, ...]]:
        """(single words, phrases). Split once at construction, not per request."""
        words, phrases = set(), []
        for raw in patterns:
            pat = unicodedata.normalize("NFKC", raw).casefold().strip()
            if not pat:
                continue
            if " " in pat:
                phrases.append(pat)
            else:
                words.add(pat)
        # Longest phrase first, so the most specific match is the one reported.
        return words, tuple(sorted(phrases, key=len, reverse=True))

    @property
    def configured(self) -> bool:
        return bool(self._banned[0] or self._banned[1]
                    or self._blocking[0] or self._blocking[1] or self._allowed)

    @staticmethod
    def _hits(lexicon: tuple[set[str], tuple[str, ...]],
              word_set: set[str], joined: str) -> list[str]:
        found = sorted(lexicon[0] & word_set)
        found += [p for p in lexicon[1] if p in joined]
        return found

    def check(self, path: str, text: str) -> RailResult:
        if not self.configured:
            return RailResult.clean()

        words = _normalise(text)
        word_set = set(words)
        # Re-joined with single spaces so a phrase matches regardless of the
        # original whitespace or punctuation between its words.
        joined = " ".join(words)

        # Blocking patterns are checked FIRST: when a text trips both lists the
        # stronger action is the honest one to report.
        blocked = self._hits(self._blocking, word_set, joined)
        if blocked:
            subject = (f"{path}: {len(blocked)} blocked-topic pattern(s), "
                       f"first {blocked[0]!r}")
            return RailResult(
                findings=[Finding(
                    category="safety.topic_violation",
                    severity=Severity.HIGH, action=Action.BLOCK, path=path,
                    detector=self.name, subject=subject, fp=_fp(subject),
                )],
                reason=subject,
            )

        hit = self._hits(self._banned, word_set, joined)
        if hit:
            subject = f"{path}: {len(hit)} banned-topic keyword(s), first {hit[0]!r}"
            return RailResult(
                findings=[Finding(
                    category="safety.topic_violation",
                    severity=Severity.MEDIUM, action=Action.FLAG, path=path,
                    detector=self.name, subject=subject, fp=_fp(subject),
                )],
                escalate=True,
                reason=subject,
            )

        if self._allowed and len(words) >= self._min_words:
            matched = sorted(t for t, lex in self._allowed.items() if lex & word_set)
            if not matched:
                subject = (f"{path}: {len(words)} words matched none of "
                           f"{len(self._allowed)} allowed-topic lexicon(s)")
                return RailResult(
                    findings=[Finding(
                        category="safety.topic_violation",
                        severity=Severity.LOW, action=Action.FLAG, path=path,
                        detector=self.name, subject=subject, fp=_fp(subject),
                    )],
                    # A keyword allowlist cannot tell "off-topic" from "on-topic
                    # in words I don't have". That is exactly what the Stage-3
                    # topic-control judge is for, so ask for it rather than
                    # asserting a violation.
                    escalate=True,
                    reason=subject,
                )
        return RailResult.clean()


# ==========================================================  rubric judge ====
# Stage 3, and the only rail in this tenet that touches a third party. DeepEval's
# GEval takes a written rubric (`criteria`) and returns a score AND a reason
# (references/deepeval-main/deepeval/metrics/g_eval/g_eval.py:49-92, :153-161) -
# a versioned, reviewable policy judgment, which is what makes it this tenet's
# best pick for rubric judging.
#
# It is expensive in the two ways that matter. `initialize_model(model)` at
# g_eval.py:79 resolves to a paid OpenAI judge when no model is named, so a
# misconfigured deployment silently starts billing per request; and an LLM call
# per payload is a High-latency check, which the methodology classes as Batch for
# this tenet. So this rail exists as a declared mount point and is deliberately
# NOT in `RAILS`. Its capability registers as CLOUD.
#
# Every failure path returns `unjudged`. A rubric judge that cannot run must not
# read as "the output met the rubric" - the engine turns
# that into a block, which is the correct outcome.


class RubricJudgeRail:
    THRESHOLD_KEY = "x.afni.rubric"
    """Stage 3 G-Eval adapter. Degrades to `unjudged`, never to clean."""

    name = "afni-rubric-judge"
    tenet = TENET
    stage = Stage.STAGE_3

    def __init__(self, rubric: str = "", judge_model: str | None = None,
                 threshold: float = 0.5, rubric_name: str = "afni-policy") -> None:
        self._rubric = rubric
        self._model = judge_model
        self._threshold = threshold
        self._rubric_name = rubric_name

    @property
    def configured(self) -> bool:
        return bool(self._rubric and self._model)

    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Configured threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self._threshold)
                     if ctx is not None else self._threshold)
        if not self._rubric:
            return RailResult.unjudged(
                f"{self.name}: no G-Eval rubric configured")
        try:
            # Lazy, and inside the try: importing deepeval at module scope would
            # make this whole tenet unimportable without it, and Stage 1 must
            # run with nothing installed.
            from deepeval.metrics import GEval
            from deepeval.test_case import LLMTestCase, SingleTurnParams
        # `Exception`, not `ImportError`: a dependency that is installed but
        # BROKEN is as unusable as an absent one and does not raise
        # ImportError. deepeval pulls in the same numpy/pandas/sklearn stack
        # that produced a bare RuntimeError on a numpy-2-vs-numpy-1 mismatch on
        # 2026-09-03, and a rail is supposed to RETURN `unjudged` rather than
        # raise - see the long note in tenets/security.
        except Exception as exc:  # noqa: BLE001 - absent OR broken
            return RailResult.unjudged(
                f"{self.name}: deepeval unusable ({exc.__class__.__name__}: "
                f"{exc}) - G-Eval rubric judge unavailable")
        if self._model is None:
            # g_eval.py:79 - initialize_model(None) resolves to a paid OpenAI
            # judge. Defaulting into someone's bill is not a degradation this
            # rail is willing to make on its own.
            return RailResult.unjudged(
                f"{self.name}: deepeval is installed but no judge model is named; "
                "GEval defaults to a paid OpenAI judge, so the model must be explicit")
        try:
            metric = GEval(name=self._rubric_name, criteria=self._rubric,
                           model=self._model, threshold=threshold,
                           evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT])
            metric.measure(LLMTestCase(input="", actual_output=text))
            score = float(metric.score)
        except Exception as exc:  # noqa: BLE001 - any judge failure is unjudged
            return RailResult.unjudged(
                f"{self.name}: G-Eval judge failed - {type(exc).__name__}: {exc}")

        if score >= threshold:
            return RailResult.clean()
        # `metric.reason` is the judge's written explanation of *this payload* and
        # is deliberately not carried into the finding - it is model-generated
        # prose about the text, which is the one thing a finding must not echo.
        subject = (f"{path} {self._rubric_name}: G-Eval scored {score:.2f}, "
                   f"below threshold {threshold}")
        return RailResult(
            findings=[Finding(
                category="x.afni.rubric.violation",
                severity=Severity.MEDIUM, action=Action.FLAG, path=path,
                score=round(1.0 - score, 4), detector=self.name,
                subject=subject, fp=_fp(subject),
            )],
            reason=subject,
        )


# ==================================================  per-check confidence ====
# Safe Zone is the best pick for this capability and
# `internal/models/confidence_explanation.go:4-22` is why: a struct that carries
# the raw signals (regex_score, ai_score, regex_hit_count), the policy applied
# (block/allow threshold and where the threshold came from) and the fusion
# (hybrid_applied, final_score) - so a score can be re-derived rather than
# trusted. Its fusion is a two-source mean, `(regexScore + aiScore) / 2` for the
# PII category only
# (references/safe-zone-main/safe-zone-main/internal/guardrails/guardrails.go:200-205).
#
# Two things are generalised in the port. First, this platform has four
# confidence kinds, not two (`contract/explanation.py` CONFIDENCE_KINDS), so the
# breakdown buckets by kind instead of by regex-vs-AI. Second, Safe Zone
# explains one detection; a gateway verdict is the union of every rail that ran,
# so this aggregates across rails and - the part no reviewed tool does - counts
# the rails that could NOT judge into the same table. A confidence report that
# omits the checks that never ran is the failure mode this platform exists to
# stop.


@dataclass(frozen=True)
class CheckConfidence:
    """One rail's contribution to the decision, and how much it is worth."""

    rail: str
    source_repo: str
    category: str
    stage: int
    confidence_kind: str
    score: float | None
    action: str | None
    evidence: str
    fingerprint: str | None = None

    @property
    def weight(self) -> float:
        """What this check's number is worth as evidence.

        Not a probability - an ordering. A checksum that matched is not 0.9
        confident, it matched; an LLM judge's self-reported 0.9 is the softest
        number in the system. `CONFIDENCE_KINDS` says exactly that and this makes
        it arithmetic so a fused score cannot be assembled from
        incomparable inputs.
        """
        if self.confidence_kind == "deterministic":
            return 1.0
        return {"classifier": 0.8, "entailment": 0.7, "judge": 0.5}.get(
            self.confidence_kind, 0.5)


@dataclass
class ConfidenceBreakdown:
    """The per-check table behind one verdict."""

    decision: str
    checks: list[CheckConfidence] = field(default_factory=list)
    unjudged: list[str] = field(default_factory=list)
    unattributed: list[str] = field(default_factory=list)
    stages_run: int = 0
    final_score: float | None = None
    fusion: str = "NONE"
    hybrid_applied: bool = False

    @property
    def blind(self) -> bool:
        """True when at least one path was never judged. Kept as a property with
        this name so a caller cannot read the table as complete by accident."""
        return bool(self.unjudged)

    def by_kind(self) -> dict[str, list[CheckConfidence]]:
        out: dict[str, list[CheckConfidence]] = {}
        for check in self.checks:
            out.setdefault(check.confidence_kind, []).append(check)
        return out

    def render(self) -> str:
        lines = [f"decision={self.decision}  stages_run={self.stages_run}  "
                 f"fusion={self.fusion}  final_score="
                 + ("n/a" if self.final_score is None else f"{self.final_score:.2f}")]
        if self.blind:
            lines.append(f"  COULD NOT JUDGE {len(self.unjudged)} path(s): "
                         + ", ".join(self.unjudged)
                         + "  <- the table below is incomplete")
        if not self.checks:
            lines.append("  no check contributed a finding")
        for kind, checks in self.by_kind().items():
            lines.append(f"  {kind} (evidence weight {checks[0].weight:.2f}):")
            for c in checks:
                score = "no score" if c.score is None else f"{c.score:.2f}"
                lines.append(f"    - {c.rail:26s} stage {c.stage}  {c.category:34s} "
                             f"{score:>9s}  action={c.action or 'none'}  [{c.source_repo}]")
        if self.unattributed:
            lines.append("  unattributed detectors (no RailAttribution registered): "
                         + ", ".join(sorted(set(self.unattributed))))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "stages_run": self.stages_run,
            "final_score": self.final_score,
            "fusion": self.fusion,
            "hybrid_applied": self.hybrid_applied,
            "could_not_judge": list(self.unjudged),
            "unattributed_detectors": sorted(set(self.unattributed)),
            "checks": [
                {"rail": c.rail, "source_repo": c.source_repo, "category": c.category,
                 "stage": c.stage, "confidence_kind": c.confidence_kind,
                 "evidence_weight": c.weight, "score": c.score, "action": c.action,
                 "evidence": c.evidence, "fp": c.fingerprint}
                for c in self.checks
            ],
        }


def _fuse(checks: list[CheckConfidence]) -> tuple[float | None, str, bool]:
    """Resolve many per-check numbers into one, and name the rule used.

    Reported alongside the inputs, never instead of them - the point of the port
    is that a reader can re-derive the number.
    """
    if not checks:
        return None, "NONE", False
    if any(c.confidence_kind == "deterministic" for c in checks):
        # A checksum or an exact match either fired or it did not. Averaging it
        # with a soft judge score would only ever dilute a certainty.
        return 1.0, "DETERMINISTIC", False
    scored = [c for c in checks if c.score is not None]
    if not scored:
        return None, "NO_SCORE_REPORTED", False
    kinds = {c.confidence_kind for c in scored}
    if len(kinds) > 1:
        # Safe Zone's hybrid: mean of the sources, weighted here by the evidence
        # weight of each kind so a judge cannot outvote a classifier.
        total = sum(c.score * c.weight for c in scored)
        return round(total / sum(c.weight for c in scored), 4), "HYBRID", True
    return round(max(c.score for c in scored), 4), "SINGLE_SOURCE", False


def confidence_breakdown(verdict: Verdict,
                         attributions: dict[str, RailAttribution],
                         stages_run: int = 0) -> ConfidenceBreakdown:
    """Aggregate every rail's contribution to one verdict into one table.

    Built on `contract.explanation.explain()` rather than beside it: that
    function already owns the finding-to-rail join (on `Finding.detector`) and
    already keeps unattributed findings instead of dropping them. This adds the
    confidence arithmetic on top.
    """
    explanation = explain(verdict, attributions, stages_run=stages_run)
    checks: list[CheckConfidence] = []
    unattributed: list[str] = []
    for fe in explanation.findings:
        attr = fe.attribution
        if attr is None:
            unattributed.append(fe.finding.detector or "unknown")
            continue
        checks.append(CheckConfidence(
            rail=attr.rail,
            source_repo=attr.source_repo,
            category=fe.finding.category,
            stage=attr.stage,
            confidence_kind=attr.confidence_kind,
            score=fe.finding.score,
            action=fe.finding.action.value if fe.finding.action else None,
            evidence=attr.evidence,
            fingerprint=fe.finding.fp,
        ))
    final, fusion, hybrid = _fuse(checks)
    return ConfidenceBreakdown(
        decision=verdict.decision.value if isinstance(verdict.decision, Decision)
        else str(verdict.decision),
        checks=checks,
        unjudged=list(verdict.unjudged),
        unattributed=unattributed,
        stages_run=stages_run,
        final_score=final,
        fusion=fusion,
        hybrid_applied=hybrid,
    )


# ============================================================  attributions ===
SCHEMA_ATTRIBUTION = RailAttribution(
    rail=SchemaExplainRail.name,
    source_repo="guardrails-main",
    display_name="Guardrails AI schema validation (stdlib port)",
    mechanism="Module + Keyword/Regex - Draft-2020-12 subset, per-field json_path "
              "explanation of which keyword failed",
    stage=int(Stage.STAGE_1),
    confidence_kind="deterministic",
    evidence="references/guardrails-main/guardrails-main/guardrails/schema/validator.py:18-38 "
             "(validate_against_schema collects {error.json_path: [messages]}); "
             "malformed-JSON detection from "
             "references/llm-guard-main/llm-guard-main/llm_guard/output_scanners/json.py:35",
    capability="Structured-output / schema validity",
)

FORMAT_ATTRIBUTION = RailAttribution(
    rail=FormatValidatorRail.name,
    source_repo="guardrails-main",
    display_name="Deterministic format validators (Guardrails AI + Safe Zone)",
    mechanism="Keyword/Regex - length, regex_match, valid_choices, valid_url, "
              "one_line, numeric_range, lower_case, two_words, reading_time, valid_json",
    stage=int(Stage.STAGE_1),
    confidence_kind="deterministic",
    evidence="references/guardrails-main/guardrails-main/tests/integration_tests/"
             "test_assets/validators/regex_match.py:16, valid_url.py:13, "
             "valid_length.py:17, valid_choices.py:13, one_line.py:13, "
             "reading_time.py:44; dispatch shape from "
             "references/safe-zone-main/safe-zone-main/internal/guardrails/validators.go:48-80",
    capability="Deterministic format validators",
)

TOPIC_ATTRIBUTION = RailAttribution(
    rail=TopicScopeRail.name,
    source_repo="llm-guard-main",
    display_name="Ban-topics / on-topic scope (Stage-1 lexicon)",
    mechanism="Keyword/Regex - NFKC+casefold word-boundary banned list and "
              "allowed-topic allowlist; escalates to the Stage-3 judge",
    stage=int(Stage.STAGE_1),
    confidence_kind="deterministic",
    evidence="references/llm-guard-main/llm-guard-main/llm_guard/input_scanners/"
             "ban_substrings.py:61-86 (word match_type); zero-shot escalation target "
             "MoritzLaurer/deberta-v3-large-zeroshot-v2.0 at ban_topics.py:13-27; "
             "Stage-3 judge nvidia/llama-3.1-nemoguard-8b-topic-control at "
             "references/Guardrails-develop/nemoguardrails/library/topic_safety/actions.py:38-42",
    capability="Ban-topics / on-topic scope",
)

RUBRIC_ATTRIBUTION = RailAttribution(
    rail=RubricJudgeRail.name,
    source_repo="deepeval-main",
    display_name="DeepEval G-Eval rubric judge",
    mechanism="LLM-judge - a written, versioned rubric scored by a judge model, "
              "returning a score and a reason",
    stage=int(Stage.STAGE_3),
    confidence_kind="judge",
    evidence="references/deepeval-main/deepeval/metrics/g_eval/g_eval.py:49-92 "
             "(GEval(name, criteria, model, threshold)); :79 initialize_model() "
             "defaults to a paid OpenAI judge; :153-161 sets score and reason",
    capability="Custom rubric judges (G-Eval)",
)

BREAKDOWN_ATTRIBUTION = RailAttribution(
    rail="afni-confidence-breakdown",
    source_repo="safe-zone-main",
    display_name="Per-check confidence breakdown (Safe Zone ConfidenceExplanation port)",
    mechanism="Module - aggregates every rail's score, kind and evidence into one "
              "table, fuses by confidence kind, and counts the checks that could "
              "not run",
    stage=int(Stage.STAGE_1),
    confidence_kind="deterministic",
    evidence="references/safe-zone-main/safe-zone-main/internal/models/"
             "confidence_explanation.go:4-22 (regex_score/ai_score/final_score, "
             "threshold_source, hybrid_applied); fusion from "
             "internal/guardrails/guardrails.go:200-205",
    capability="Per-check confidence breakdown",
)

ATTRIBUTIONS: dict[str, RailAttribution] = {
    SCHEMA_ATTRIBUTION.rail: SCHEMA_ATTRIBUTION,
    FORMAT_ATTRIBUTION.rail: FORMAT_ATTRIBUTION,
    TOPIC_ATTRIBUTION.rail: TOPIC_ATTRIBUTION,
    RUBRIC_ATTRIBUTION.rail: RUBRIC_ATTRIBUTION,
    BREAKDOWN_ATTRIBUTION.rail: BREAKDOWN_ATTRIBUTION,
}


# ===================================================================  mount ===
# Only the rails that do real work with no deployment configuration. The topic
# rail is deliberately absent: an unconfigured lexicon makes it a no-op, and
# mounting a no-op would put a rail name in the trace that judged nothing.
RAILS: list[Rail] = [
    SchemaExplainRail(),
    FormatValidatorRail(),
]


def register(registry, rails: Sequence[Rail] = ()) -> None:
    """Register all nine Explainability capabilities.

    Three run today. Two need a paid judge. Three are offline batch tools that
    must never be mounted. One is a gap. That distribution is the finding, not a
    shortfall: this tenet is about explaining decisions, and most of the reviewed
    tooling for it explains *models*, in a notebook, over a labelled dataset.

    `rails` lets a deployment pass its own configured instances - a
    `TopicScopeRail` with an actual lexicon flips that capability from GAP to
    IMPLEMENTED, and nothing else can.
    """
    mounted = list(rails) or list(RAILS)
    by_name = {r.name: r for r in mounted}

    # ---- implemented, runs today -------------------------------------------
    schema_rail = by_name.get(SchemaExplainRail.name)
    if schema_rail is not None:
        registry.register_rail(
            schema_rail, SCHEMA_ATTRIBUTION, available=True,
            note="Explains WHY, per field: json_path + failed keyword + expected vs "
                 "received type. Zero-config it reports malformed JSON only; give it "
                 "a schema and it reports every failing field. Draft-2020-12 SUBSET - "
                 "$ref/oneOf/allOf/if-then are not evaluated, so a schema using them "
                 "is under-checked (SchemaExplainRail.unsupported lists them). "
                 "OVERLAP: the hallucination tenet's StructuredOutputRail owns Stage-1 "
                 "well-formedness (JSON and XML, candidate spans) under its own "
                 "capability 'Structured-output validation'. Both would report a "
                 "malformed JSON document; construct SchemaExplainRail("
                 "report_malformed=False) to hand that check over and keep only the "
                 "per-field schema explanation here.")
    else:
        registry.register(
            TENET, "Structured-output / schema validity", Coverage.GAP,
            note="SchemaExplainRail exists but was not mounted.")

    format_rail = by_name.get(FormatValidatorRail.name)
    if format_rail is not None:
        n = len(getattr(format_rail, "rules", ()))
        registry.register_rail(
            format_rail, FORMAT_ATTRIBUTION, available=True,
            note=f"10 validator kinds implemented, {n} rule(s) mounted by default "
                 f"(reading_time 20min, length 100k chars - both flag-only, both "
                 f"about runaway generation). The contract-specific kinds "
                 f"(regex_match, valid_choices, valid_url, numeric_range, one_line) "
                 f"need the deployment's output contract; inventing one would be "
                 f"worse than shipping none.")
    else:
        registry.register(
            TENET, "Deterministic format validators", Coverage.GAP,
            note="FormatValidatorRail exists but was not mounted.")

    registry.register(
        TENET, "Per-check confidence breakdown", Coverage.IMPLEMENTED,
        attribution=BREAKDOWN_ATTRIBUTION,
        note="confidence_breakdown(verdict, attributions) - not a rail. Runs after "
             "the cascade on every verdict, buckets each contributing rail by "
             "confidence kind, fuses to one score by a named rule, and counts the "
             "paths that were never judged into the same table. Port of Safe Zone's "
             "ConfidenceExplanation, generalised from its two sources to this "
             "platform's four CONFIDENCE_KINDS.")

    # ---- gap: mechanism built, policy absent -------------------------------
    topic_rail = by_name.get(TopicScopeRail.name)
    if topic_rail is not None and getattr(topic_rail, "configured", False):
        registry.register_rail(
            topic_rail, TOPIC_ATTRIBUTION, available=True,
            note="Stage-1 lexicon scope check with a deployment-supplied policy. "
                 "Flags and escalates; the Stage-2 zero-shot and Stage-3 "
                 "topic-control judge are the confident layers and are not "
                 "configured.")
    else:
        registry.register(
            TENET, "Ban-topics / on-topic scope", Coverage.GAP,
            note="TopicScopeRail implements the Stage-1 mechanism and is unit-tested, "
                 "but it ships with an empty lexicon and is therefore NOT MOUNTED - "
                 "there is no topic cover today. 'On-topic' is deployment policy in "
                 "every reviewed tool (NeMo config.yml, DeepTeam "
                 "TopicalGuard(allowed_topics=[...])), so AFNI must author the "
                 "lexicon; pass a configured TopicScopeRail to register() to flip "
                 "this to IMPLEMENTED. Stage 2 = LLM Guard BanTopics zero-shot "
                 "(MoritzLaurer/deberta-v3-large-zeroshot-v2.0), Stage 3 = "
                 "nvidia/llama-3.1-nemoguard-8b-topic-control.")

    # ---- cloud: needs a paid judge -----------------------------------------
    rubric_rail = by_name.get(RubricJudgeRail.name)
    if rubric_rail is not None and getattr(rubric_rail, "configured", False):
        registry.register_rail(
            rubric_rail, RUBRIC_ATTRIBUTION, available=True,
            note="A configured G-Eval rubric judge was mounted at Stage 3. Every "
                 "request that reaches it costs a judge call; the cascade only "
                 "escalates there when a cheaper stage asked.")
    else:
        registry.register(
            TENET, "Custom rubric judges (G-Eval)", Coverage.CLOUD,
            attribution=RUBRIC_ATTRIBUTION,
            note="RubricJudgeRail is written and degrades honestly - no deepeval, no "
                 "judge model, or a failed call all return unjudged, never clean. It "
                 "is NOT mounted: GEval resolves its judge through "
                 "initialize_model() with a paid OpenAI default "
                 "(references/deepeval-main/deepeval/metrics/g_eval/g_eval.py:79), so "
                 "an unconfigured mount would bill per request, and the methodology "
                 "classes DeepEval as Batch for this tenet. Mount it by passing a "
                 "configured RubricJudgeRail(rubric=..., judge_model=...) to "
                 "register().")

    registry.register(
        TENET, "Token-level attribution", Coverage.CLOUD,
        note="Infosys LLM-Explain asks GPT-4 to score the importance of every token "
             "in the prompt and return a Token/Importance Score/Position JSON "
             "(references/Infosys-Responsible-AI-Toolkit-master/"
             "responsible-ai-llm-explain/responsible-ai-llm-explain/src/llm_explain/"
             "utility/prompt_utils.py:84). Stage 3, paid, and prompt-based rather "
             "than gradient-based - the model self-reports its own attributions, "
             "which is the softest of the four confidence kinds. SHAP's Text masker "
             "is the real-attribution alternative and is OFFLINE.")

    # ---- offline: batch tools, never in the request path -------------------
    registry.register(
        TENET, "Feature attribution (SHAP)", Coverage.OFFLINE,
        note="SHAP KernelExplainer (references/shap-master/shap/explainers/"
             "_kernel.py:41) costs nsamples x features model evaluations per "
             "explanation. tenets.md: 'Runs as: async explain endpoint backed by a "
             "background job - SHAP is too slow for synchronous request handling.' "
             "Belongs behind an async /explain endpoint feeding a job queue; the "
             "Cascade constructor refuses to mount an OFFLINE rail, and that is "
             "correct here.")

    registry.register(
        TENET, "LIME local explanations", Coverage.OFFLINE,
        note="LimeTabularExplainer, used inside the Infosys explainability service "
             "(references/Infosys-Responsible-AI-Toolkit-master/"
             "responsible-ai-explain/responsible-ai-explain/src/explain/service/"
             "responsible_ai_explain.py:19,404). Classical-ML, tabular, and it "
             "perturbs-and-refits per explanation. Same async /explain endpoint as "
             "SHAP, same background job, never the request path.")

    registry.register(
        TENET, "Counterfactual / recourse analysis", Coverage.OFFLINE,
        note="AIF360 FACTS mines if-then recourse rules over frequent itemsets "
             "(references/AIF360-main/aif360/sklearn/detectors/facts/misc.py:178 "
             "valid_ifthens, :61 freqitemsets_with_supports). Needs the full "
             "dataset, a fitted model and a defined protected group - none of which "
             "exist for a single request. Batch only; MetricTextExplainer/"
             "MetricJSONExplainer (aif360/explainers/metric_text_explainer.py:5) "
             "render the results for a report.")


__all__ = [
    "TENET", "RAILS", "register", "ATTRIBUTIONS",
    "SchemaViolation", "validate_schema", "unsupported_keywords",
    "SchemaExplainRail", "FormatRule", "FORMAT_KINDS", "DEFAULT_FORMAT_RULES",
    "FormatValidatorRail", "TopicScopeRail", "RubricJudgeRail",
    "CheckConfidence", "ConfidenceBreakdown", "confidence_breakdown",
    "SCHEMA_ATTRIBUTION", "FORMAT_ATTRIBUTION", "TOPIC_ATTRIBUTION",
    "RUBRIC_ATTRIBUTION", "BREAKDOWN_ATTRIBUTION",
]
