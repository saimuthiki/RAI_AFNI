# -*- coding: utf-8 -*-
"""
The fail-closed / unjudged policy, made configurable per tenant.

THE ENGINE ALREADY IMPLEMENTS THE RULE. THIS FILE DOES NOT REIMPLEMENT IT.

`afni_rai/cascade/engine.py` is where the invariant lives, and it is already
correct:

  * `Cascade._run` catches any rail exception and converts it to
    `RailResult.unjudged(...)` rather than dropping the check - the deliberate
    refusal of the Infosys dispatcher's broad try/except-log-return-None.
  * `Cascade.evaluate` adds the payload path of every unjudged rail to
    `Verdict.unjudged` - fail loud.
  * `Cascade._decide` returns `Decision.BLOCK` when `unjudged` is non-empty and
    `event.client_facing` is true - fail closed.

That is the whole rule, in the engine, once, for every rail. Duplicating it here
would create a second copy that could disagree with the first, which is worse
than having none.

WHAT THIS FILE ADDS

The engine's rule is hardcoded to one axis: `client_facing`. OpenGuardrails'
`specification/degraded-mode.md` is explicit that a conformant enforcement point
must go further - `:46-49`:

    "An integration MUST apply its configured `fail_mode` without any runtime
     round-trip. An integration MUST make its fail mode configurable so a
     deployment CAN choose `closed`; it MUST NOT hard-code open as the only
     behavior."

and `:22-35` gives the shape: `fail_mode` configured per risk category or
category prefix, with a `default`, where `open` permits and records and `closed`
denies. Upstream's default is `open` (`:8-16`, "the minimal integration is an
observability instrument first"). AFNI inverts that default for client-facing
traffic and keeps `open` for internal traffic - which is exactly the requirement:
client-facing fails closed, internal fails open but *always reports*.

So `FailurePolicy` consumes the engine's `CascadeOutcome` and adjusts only the
one branch the engine could not know about - what a given tenant wants done about
an unjudged path. It never touches a decision that a real blocking finding
produced, and `open` never suppresses the report. Losing the report would be the
Infosys failure mode arriving through the front door.

Contrast worth keeping: NeMo Guardrails' own jailbreak rail is documented
fail-OPEN by default at
`references/Guardrails-develop/docs/configure-rails/guardrail-catalog/jailbreak-protection.mdx:112`,
which is why this is a gateway-level policy object and not a per-rail setting.

Zero third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence

from ...cascade.engine import CascadeOutcome
from ...contract.models import Action, Decision, Finding, GuardEvent, Verdict
from .thresholds import ThresholdStore, _prefix_match


class FailMode(str, Enum):
    """OpenGuardrails degraded-mode.md:32-35, verbatim semantics.

    open   - permit the action; record locally that it went unjudged
    closed - deny the gated action until the check can run again
    """

    OPEN = "open"
    CLOSED = "closed"


# degraded-mode.md:37 - "A category with no entry uses `default`; an absent
# `default` is `open`." AFNI keeps upstream's key name but not its default value:
# for client-facing traffic the default is CLOSED, which is the deck's Phase-1
# flip. Internal traffic keeps upstream's OPEN so an internal experiment is not
# halted by a missing model file - but it is still reported.
DEFAULT_KEY = "default"
CLIENT_FACING_DEFAULT = FailMode.CLOSED
INTERNAL_DEFAULT = FailMode.OPEN


@dataclass(frozen=True)
class ModeDecision:
    """Which fail_mode won, and why. The `source` is what an auditor asks for
    when a request was allowed through with an unjudged path."""

    mode: FailMode
    source: str
    category: str | None = None


@dataclass
class PolicyOutcome:
    """The gateway's final answer, plus everything needed to justify it.

    `decision` is what the caller enforces. `engine_decision` is what the cascade
    said on its own. When they differ, `overridden` is true and `reason` names the
    configuration that did it - so a policy override is always visible in the
    record rather than being indistinguishable from a clean allow.
    """

    decision: Decision
    engine_decision: Decision
    fail_mode: FailMode
    mode_source: str
    unjudged: list[str] = field(default_factory=list)
    blocking_findings: int = 0
    reason: str = ""
    tenant: str | None = None
    client_facing: bool = True

    @property
    def overridden(self) -> bool:
        return self.decision is not self.engine_decision

    @property
    def could_not_judge(self) -> bool:
        """Never derived from the decision. An allowed request with unjudged
        paths is the single most important thing this object reports."""
        return bool(self.unjudged)

    @property
    def needs_review(self) -> bool:
        """True when the gateway let something through that it could not judge.
        This is the queue an operator works, and the reason `open` is not the same
        thing as `clean`."""
        return self.decision is Decision.ALLOW and bool(self.unjudged)

    def report_line(self) -> str:
        """Always produced, in both modes. Fail loud is not conditional on
        failing closed."""
        head = f"{self.decision.value.upper()}"
        if self.overridden:
            head += f" (engine said {self.engine_decision.value}, policy overrode)"
        parts = [head, f"fail_mode={self.fail_mode.value} via {self.mode_source}"]
        if self.unjudged:
            parts.append("COULD NOT JUDGE " + ",".join(self.unjudged)
                         + "  <- not the same as 'found nothing'")
        if self.blocking_findings:
            parts.append(f"blocking findings={self.blocking_findings}")
        if self.reason:
            parts.append(self.reason)
        return " | ".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "engine_decision": self.engine_decision.value,
            "overridden": self.overridden,
            "fail_mode": self.fail_mode.value,
            "mode_source": self.mode_source,
            "could_not_judge": list(self.unjudged),
            "needs_review": self.needs_review,
            "blocking_findings": self.blocking_findings,
            "tenant": self.tenant,
            "client_facing": self.client_facing,
            "reason": self.reason,
        }


class FailurePolicy:
    """Per-tenant fail_mode resolution, applied on top of the engine's verdict.

    Construct with a `ThresholdStore` and every tenant's `fail_modes` mapping
    (`TenantConfig.fail_modes`) becomes the per-category configuration
    degraded-mode.md:24-30 describes. Without a store, the two defaults apply.
    """

    def __init__(self, thresholds: ThresholdStore | None = None,
                 client_facing_default: FailMode = CLIENT_FACING_DEFAULT,
                 internal_default: FailMode = INTERNAL_DEFAULT,
                 global_modes: Mapping[str, str] | None = None) -> None:
        self._thresholds = thresholds
        self._client_facing_default = FailMode(client_facing_default)
        self._internal_default = FailMode(internal_default)
        self._global: dict[str, str] = dict(global_modes or {})

    # ------------------------------------------------------------ resolution --
    def fail_mode_for(self, tenant: str | None, category: str | None = None,
                      client_facing: bool = True) -> ModeDecision:
        """Resolve one (tenant, category) pair.

        Order: tenant exact -> tenant prefix -> tenant `default` -> global exact
        -> global prefix -> global `default` -> the client_facing / internal
        default. Exactly degraded-mode.md:37's "a category with no entry uses
        `default`", with an AFNI-chosen final fallback instead of hard `open`.
        """
        cfg = self._thresholds.tenant(tenant) if self._thresholds else None
        scopes: list[tuple[Mapping[str, str], str]] = []
        if cfg is not None and cfg.fail_modes:
            scopes.append((cfg.fail_modes, f"tenant:{cfg.tenant}"))
        if self._global:
            scopes.append((self._global, "global"))

        for modes, label in scopes:
            if category is not None and category in modes:
                return ModeDecision(FailMode(modes[category]),
                                    f"{label}:{category}", category)
            if category is not None:
                pattern = _prefix_match(modes, category)
                if pattern is not None:
                    return ModeDecision(FailMode(modes[pattern]),
                                        f"{label}:{pattern}", category)
            if DEFAULT_KEY in modes:
                return ModeDecision(FailMode(modes[DEFAULT_KEY]),
                                    f"{label}:{DEFAULT_KEY}", category)

        if client_facing:
            return ModeDecision(self._client_facing_default,
                                "afni-default:client_facing", category)
        return ModeDecision(self._internal_default, "afni-default:internal", category)

    def strictest(self, tenant: str | None, categories: Iterable[str],
                  client_facing: bool = True) -> ModeDecision:
        """degraded-mode.md:38-42 treats a timeout, an outage and an `unjudged`
        path as "the same situation at three sizes". When several categories are
        in play, the strictest wins: one gated category configured `closed` is
        enough to deny, because permitting it would make the `closed` setting
        meaningless."""
        resolved = [self.fail_mode_for(tenant, c, client_facing) for c in categories]
        if not resolved:
            return self.fail_mode_for(tenant, None, client_facing)
        for decision in resolved:
            if decision.mode is FailMode.CLOSED:
                return decision
        return resolved[0]

    # ---------------------------------------------------------- enforcement --
    def apply(self, event: GuardEvent, outcome: CascadeOutcome,
              unjudged_categories: Sequence[str] = ()) -> PolicyOutcome:
        """Turn the engine's verdict into the gateway's enforced decision.

        `unjudged_categories` is what the caller knows and the verdict does not:
        which risk categories the rails that failed would have covered.
        `Verdict.unjudged` carries payload *paths*, because that is what
        OpenGuardrails v0.8 defines it as
        (`schema/verdict.schema.json:140`), while `fail_mode` is configured per
        risk *category*. The gateway holds the rail->category mapping, so it
        passes it in; with nothing passed, the tenant/traffic default applies.
        That gap is a real limitation of the v0.8 wire shape and is stated here
        rather than papered over.
        """
        verdict = outcome.verdict
        blocking = [f for f in verdict.findings if f.action is Action.BLOCK]
        tenant = event.tenant

        if blocking:
            # A real finding blocked this. No fail_mode setting may relax it -
            # `open` is about "could not look", never about "looked and found".
            mode = self.fail_mode_for(tenant, blocking[0].category,
                                      event.client_facing)
            return PolicyOutcome(
                decision=Decision.BLOCK,
                engine_decision=verdict.decision,
                fail_mode=mode.mode,
                mode_source=mode.source,
                unjudged=list(verdict.unjudged),
                blocking_findings=len(blocking),
                reason=f"blocking finding {blocking[0].category}",
                tenant=tenant,
                client_facing=event.client_facing,
            )

        if not verdict.unjudged:
            mode = self.fail_mode_for(tenant, None, event.client_facing)
            return PolicyOutcome(
                decision=Decision.ALLOW,
                engine_decision=verdict.decision,
                fail_mode=mode.mode,
                mode_source=mode.source,
                reason="every mounted rail judged every payload path",
                tenant=tenant,
                client_facing=event.client_facing,
            )

        mode = self.strictest(tenant, unjudged_categories, event.client_facing)
        if mode.mode is FailMode.CLOSED:
            decision = Decision.BLOCK
            reason = (f"{len(verdict.unjudged)} unjudged path(s) and fail_mode="
                      "closed - 'could not look' is not 'found nothing'")
        else:
            decision = Decision.ALLOW
            reason = (f"{len(verdict.unjudged)} unjudged path(s) permitted under "
                      "fail_mode=open - RECORDED AS UNJUDGED, queued for review")
        return PolicyOutcome(
            decision=decision,
            engine_decision=verdict.decision,
            fail_mode=mode.mode,
            mode_source=mode.source,
            unjudged=list(verdict.unjudged),
            blocking_findings=0,
            reason=reason,
            tenant=tenant,
            client_facing=event.client_facing,
        )


def engine_enforces_fail_closed(verdict: Verdict, client_facing: bool) -> bool:
    """A read-only assertion helper, not a second implementation.

    Returns what `Cascade._decide` must already have concluded for this verdict.
    The test suite uses it to prove the engine's behaviour is what this module
    documents, so a future edit to `engine.py` that quietly flips the default
    breaks a test in the tenet that owns the policy rather than passing silently.
    """
    if any(f.action is Action.BLOCK for f in verdict.findings):
        return verdict.decision is Decision.BLOCK
    if verdict.unjudged and client_facing:
        return verdict.decision is Decision.BLOCK
    return verdict.decision is Decision.ALLOW


def categories_of(findings: Iterable[Finding]) -> list[str]:
    """De-duplicated category list, order preserved - the input `apply()` wants
    when the caller has findings but no explicit category list."""
    seen: dict[str, None] = {}
    for f in findings:
        seen.setdefault(f.category, None)
    return list(seen)
