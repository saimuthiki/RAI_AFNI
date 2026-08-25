# -*- coding: utf-8 -*-
"""
On-fail remediation actions: the four mitigation branches, and a dispatcher.

WHY NOT JUST USE GUARDRAILS AI'S ENUM

Guardrails AI has the only real on-fail vocabulary in the reviewed set -
`guardrails/types/on_fail.py:24-31`, eight values:

    reask, fix, filter, refrain, noop, exception, fix_reask, custom

It is a well-designed enum for a *validator library*: every value is about what
to do with a Python value that failed validation. What it conspicuously does not
contain is `mask`, `allow` or `block` - because Guardrails AI is not an
enforcement point. There is no branch in it for "return a refusal to the caller",
and `filter` (drop the invalid value) is not the same thing as masking a span and
continuing, because filtering loses the surrounding text.

AFNI is an enforcement point, so the vocabulary comes from the deck's
request-flow slide instead (`knowledge/request-flow.md:37-41`), which names four
and only four branches for a response that is not safe:

    Toxic         -> Block / Refuse
    PII leak      -> Mask & Continue
    Not grounded  -> Flag / Regenerate
    Bad tool call -> Block

and the accompanying design note (`request-flow.md:55-57`) is emphatic that this
is not one branch wearing four hats: "'Not safe' is not one branch. Four distinct
mitigations, and only two of them block - PII leak masks and continues,
ungrounded flags or regenerates. Treating 'unsafe' as a single refuse path loses
most of the usable behaviour."

`ON_FAIL_INTEROP` below maps Guardrails AI's eight onto AFNI's five so an
application already written against `OnFailAction` keeps working, and so a
Guardrails AI validator mounted as a rail can declare its intent in its own
vocabulary. The mapping is lossy in one direction on purpose and the docstring
says which.

Zero third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Sequence

from ...contract.models import Action, EventKind, Finding, Severity, Verdict


class RemediationAction(str, Enum):
    """The four request-flow branches, plus the explicit do-nothing.

    NOOP is named rather than implied: "we looked, we flagged it, we did not
    remediate" is a real outcome that has to be distinguishable in the audit
    record from "nothing fired".
    """

    BLOCK_REFUSE = "block_refuse"        # request-flow.md:38 - Toxic -> Block/Refuse
    MASK_CONTINUE = "mask_continue"      # request-flow.md:39 - PII leak -> Mask & Continue
    FLAG_REGENERATE = "flag_regenerate"  # request-flow.md:40 - Not grounded -> Flag/Regenerate
    BLOCK_TOOL_CALL = "block_tool_call"  # request-flow.md:41 - Bad tool call -> Block
    NOOP = "noop"                        # recorded, not remediated

    @property
    def blocks(self) -> bool:
        """Two of the four block. This property is the guard against the mistake
        request-flow.md:55-57 warns about - collapsing four mitigations into one
        refuse path."""
        return self in (RemediationAction.BLOCK_REFUSE,
                        RemediationAction.BLOCK_TOOL_CALL)

    @property
    def continues(self) -> bool:
        return not self.blocks


# Guardrails AI on_fail.py:24-31 -> AFNI. Lossy where upstream is finer-grained
# than an enforcement point can be:
#   reask / fix_reask -> FLAG_REGENERATE  (both mean "ask the model again")
#   fix               -> MASK_CONTINUE    (upstream substitutes a static value;
#                                          for a gateway that is a masked span)
#   filter            -> MASK_CONTINUE    (closest available; upstream DROPS the
#                                          value, we replace it in place, because
#                                          dropping loses the surrounding text)
#   refrain           -> BLOCK_REFUSE     (upstream returns empty; a gateway
#                                          returns a refusal)
#   exception         -> BLOCK_REFUSE     (raising is not an option in-path; the
#                                          engine already turns a raise into
#                                          `unjudged`, and fail-closed blocks it)
#   noop              -> NOOP
#   custom            -> NOOP             (dispatch to a registered handler; with
#                                          no handler registered it must not
#                                          silently become a block)
ON_FAIL_INTEROP: dict[str, RemediationAction] = {
    "reask": RemediationAction.FLAG_REGENERATE,
    "fix_reask": RemediationAction.FLAG_REGENERATE,
    "fix": RemediationAction.MASK_CONTINUE,
    "filter": RemediationAction.MASK_CONTINUE,
    "refrain": RemediationAction.BLOCK_REFUSE,
    "exception": RemediationAction.BLOCK_REFUSE,
    "noop": RemediationAction.NOOP,
    "custom": RemediationAction.NOOP,
}


def from_on_fail_action(key: str | None,
                        default: RemediationAction = RemediationAction.NOOP
                        ) -> RemediationAction:
    """Guardrails AI's `OnFailAction.get` equivalent (on_fail.py:33-45).

    Upstream swallows a bad key, logs a warning and returns the default. Same
    behaviour here for interop, but the default is NOOP rather than None so a
    typo can never be read as a block.
    """
    if not key:
        return default
    return ON_FAIL_INTEROP.get(str(key).strip().lower(), default)


# Which categories mean "the answer is not grounded", i.e. regenerate rather than
# refuse. `safety.hallucination` is OpenGuardrails' own term
# (specification/taxonomy.md:25 - "Unsupported factual claim (where checkable)");
# the `x.afni.grounding.*` prefix is the extension namespace for AFNI's own NLI
# rails.
REGENERATE_CATEGORIES = ("safety.hallucination", "x.afni.grounding",
                         "x.afni.hallucination")

# Which categories mask rather than refuse. `privacy.pii.*` is "personal data
# crossing a boundary (often `redact`)" per taxonomy.md:110, which is exactly the
# Mask & Continue branch. `safety.pii` is the model saying someone's data out loud
# (taxonomy.md:22) and masks the same way.
MASK_CATEGORIES = ("privacy.pii", "safety.pii", "security.secret_leak")

# Payload paths that are a tool call rather than prose. `GuardEvent.texts()`
# builds these by walking the payload, so a tool call arrives as e.g.
# `payload.tool_calls[0].arguments`.
TOOL_CALL_PATH_MARKERS = ("tool_call", "tool_calls", "tools", "function_call",
                          "arguments", "mcp")


@dataclass(frozen=True)
class Remediation:
    """One decided mitigation. Carries the finding's category and fingerprint,
    never its subject - the same rule the audit store enforces."""

    action: RemediationAction
    category: str
    reason: str
    path: str | None = None
    fp: str | None = None
    detector: str | None = None
    severity: Severity | None = None

    @property
    def blocks(self) -> bool:
        return self.action.blocks

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action.value, "category": self.category,
                "reason": self.reason, "path": self.path, "fp": self.fp,
                "detector": self.detector,
                "severity": self.severity.value if self.severity else None}


@dataclass
class RemediationPlan:
    """Everything to do about one verdict, and the single outcome it implies."""

    remediations: list[Remediation] = field(default_factory=list)

    @property
    def blocking(self) -> list[Remediation]:
        return [r for r in self.remediations if r.blocks]

    @property
    def blocks(self) -> bool:
        return bool(self.blocking)

    @property
    def masks(self) -> list[Remediation]:
        return [r for r in self.remediations
                if r.action is RemediationAction.MASK_CONTINUE]

    @property
    def regenerates(self) -> list[Remediation]:
        return [r for r in self.remediations
                if r.action is RemediationAction.FLAG_REGENERATE]

    @property
    def terminal(self) -> RemediationAction:
        """The one action the caller performs. Blocks win over masks, masks win
        over regeneration: a response that must be refused is not also masked,
        and a response with a PII span is masked rather than thrown away and
        regenerated at model cost."""
        for action in (RemediationAction.BLOCK_TOOL_CALL,
                       RemediationAction.BLOCK_REFUSE,
                       RemediationAction.MASK_CONTINUE,
                       RemediationAction.FLAG_REGENERATE):
            if any(r.action is action for r in self.remediations):
                return action
        return RemediationAction.NOOP

    def render(self) -> str:
        if not self.remediations:
            return "no remediation required"
        lines = [f"terminal action: {self.terminal.value}"]
        lines += [f"  - {r.action.value:16s} {r.category:34s} {r.reason}"
                  for r in self.remediations]
        return "\n".join(lines)


class RemediationDispatcher:
    """Maps findings to the four branches, then runs the registered handler.

    Handlers are supplied by the caller - this module performs no I/O and calls no
    model. `dispatch()` is the pure decision, `run()` is decision plus handler
    invocation, so a gateway can plan first and act later (and a test can assert
    on the plan without side effects).
    """

    def __init__(self, tool_call_markers: Sequence[str] = TOOL_CALL_PATH_MARKERS,
                 mask_categories: Sequence[str] = MASK_CATEGORIES,
                 regenerate_categories: Sequence[str] = REGENERATE_CATEGORIES,
                 handlers: dict[RemediationAction, Callable[[Remediation], Any]]
                 | None = None) -> None:
        self._tool_markers = tuple(tool_call_markers)
        self._mask = tuple(mask_categories)
        self._regen = tuple(regenerate_categories)
        self._handlers: dict[RemediationAction, Callable[[Remediation], Any]] = \
            dict(handlers or {})

    def register(self, action: RemediationAction,
                 handler: Callable[[Remediation], Any]) -> None:
        self._handlers[action] = handler

    # ------------------------------------------------------------- resolution --
    def _is_tool_call(self, path: str | None) -> bool:
        if not path:
            return False
        lowered = path.lower()
        return any(marker in lowered for marker in self._tool_markers)

    @staticmethod
    def _prefixed(category: str, prefixes: Iterable[str]) -> bool:
        return any(category == p or category.startswith(p + ".") for p in prefixes)

    def resolve(self, finding: Finding, kind: EventKind | None = None
                ) -> Remediation:
        """One finding -> one branch.

        Order matters. A bad tool call is checked first because it is a distinct
        branch in the deck even when the finding's own action is only `flag`: a
        malformed or unauthorised tool call is blocked on the strength of *where*
        it is, not how confident the detector was.
        """
        category = finding.category
        common = dict(category=category, path=finding.path, fp=finding.fp,
                      detector=finding.detector, severity=finding.severity)

        if self._is_tool_call(finding.path) and finding.action is not None:
            return Remediation(
                action=RemediationAction.BLOCK_TOOL_CALL,
                reason=f"finding on tool-call path {finding.path!r}", **common)

        if finding.action is Action.REDACT:
            return Remediation(
                action=RemediationAction.MASK_CONTINUE,
                reason="detector asked for redaction", **common)

        if finding.action is Action.BLOCK:
            if self._prefixed(category, self._mask):
                # A PII/secret category that a detector marked `block` still
                # masks rather than refuses - request-flow.md:39. Escalating it to
                # a refusal is the collapse the design note warns about.
                return Remediation(
                    action=RemediationAction.MASK_CONTINUE,
                    reason="maskable category; masked rather than refused", **common)
            return Remediation(
                action=RemediationAction.BLOCK_REFUSE,
                reason="blocking finding", **common)

        if finding.action is Action.FLAG:
            if self._prefixed(category, self._regen):
                return Remediation(
                    action=RemediationAction.FLAG_REGENERATE,
                    reason="ungrounded answer; regenerate", **common)
            if kind is EventKind.RESPONSE:
                return Remediation(
                    action=RemediationAction.FLAG_REGENERATE,
                    reason="flagged on a response; regenerate", **common)
            # A flag on the *request* side has nothing to regenerate - the model
            # has not been called yet. Recorded, not remediated.
            return Remediation(
                action=RemediationAction.NOOP,
                reason="flagged on a request; recorded, not remediated", **common)

        return Remediation(action=RemediationAction.NOOP,
                           reason="finding carries no action", **common)

    def dispatch(self, verdict: Verdict, kind: EventKind | None = None
                 ) -> RemediationPlan:
        return RemediationPlan([self.resolve(f, kind) for f in verdict.findings])

    def run(self, verdict: Verdict, kind: EventKind | None = None
            ) -> tuple[RemediationPlan, list[tuple[Remediation, Any]]]:
        """Dispatch, then invoke handlers. A missing handler is not an error - the
        plan still says what should have happened, which is what the audit record
        needs. An exception from a handler propagates: a remediation that silently
        failed to apply is worse than a loud failure, and is exactly the Infosys
        try/except-and-continue pattern this framework refuses.
        """
        plan = self.dispatch(verdict, kind)
        results: list[tuple[Remediation, Any]] = []
        for remediation in plan.remediations:
            handler = self._handlers.get(remediation.action)
            if handler is None:
                continue
            results.append((remediation, handler(remediation)))
        return plan, results
