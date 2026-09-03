# -*- coding: utf-8 -*-
"""
The governance register - generated, not typed in.

WHY THERE ARE NO PEOPLE'S NAMES IN HERE

The build plan asked AFNI for "one accountable owner per tenet - seven names",
and AFNI pushed back: the framework comes with all of this, so why does it need
names? The push-back is right, and the answer is a design change rather than a
default value.

**A person's name in a governance register is stale the moment they change
team.** Seven names collected once become seven wrong names within a year, and a
register with a wrong escalation path is worse than one with an honest gap: the
first sends an incident to somebody who left, the second sends it nowhere and is
visibly unfinished.

What governance actually needs is an ESCALATION PATH, and a role plus an address
is an escalation path. So this module generates a **role** per tenet with no
configuration at all, and takes **one** setting - a mail domain - instead of
seven names. If AFNI later wants real people, `AFNI_GOVERNANCE_OWNERS` accepts
them, per tenet, without a code change.

NO DOMAIN IS INVENTED

Until `AFNI_GOVERNANCE_DOMAIN` is set, each owner has a group alias
(`rai-privacy`) and no domain, and the register says the escalation address is
unconfigured. Making one up would put a plausible-looking address into a
compliance artefact that silently goes nowhere, which is precisely the failure
the paragraph above is arguing against.

WHAT THE REGISTER IS FOR

Build-plan item 21 wants "the seven tenets and their current thresholds in a
single governance register". So the register is not a contact list: it is the
tenet, its accountable role, its escalation address, its coverage counts, the
rails actually mounted for it, the thresholds in force RIGHT NOW, and its
fail-mode. Generated from the live platform, so it cannot describe a
configuration that is not running.

Zero third-party dependencies.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from .contract.models import Tenet

ENV_DOMAIN = "AFNI_GOVERNANCE_DOMAIN"
ENV_OWNERS = "AFNI_GOVERNANCE_OWNERS"

#: The alias local-part per tenet. Short, stable, and derived from the tenet
#: rather than from anybody's name.
ALIAS: dict[Tenet, str] = {
    Tenet.PRIVACY: "rai-privacy",
    Tenet.SECURITY: "rai-security",
    Tenet.FAIRNESS: "rai-fairness",
    Tenet.EXPLAINABILITY: "rai-explainability",
    Tenet.CONTENT_SAFETY: "rai-content-safety",
    Tenet.HALLUCINATION: "rai-reliability",
    Tenet.ACCOUNTABILITY: "rai-accountability",
}

#: What the role is accountable FOR. One sentence per tenet, because "owner of
#: Privacy" is not an accountability - it is a label. An escalation path needs to
#: say what arriving at it means.
ACCOUNTABLE_FOR: dict[Tenet, str] = {
    Tenet.PRIVACY: (
        "Deciding what counts as personal data in an AFNI AI application, and "
        "signing off the redaction behaviour - including that a redaction an "
        "application ignores is a leak the guardrail cannot prevent."),
    Tenet.SECURITY: (
        "Owning the response to a prompt-injection or exfiltration finding, and "
        "deciding when a detection becomes an incident rather than a metric."),
    Tenet.FAIRNESS: (
        "Commissioning the population-level fairness runs. Seven of the nine "
        "fairness capabilities are offline-only because fairness is arithmetic "
        "over a population and one response is not a population, so nobody "
        "watching live traffic will ever see this tenet fail."),
    Tenet.EXPLAINABILITY: (
        "Deciding what an AFNI application must be able to tell a customer "
        "about a refusal, and approving the per-application topic scope."),
    Tenet.CONTENT_SAFETY: (
        "Setting the toxicity and topic thresholds against real AFNI traffic, "
        "and owning the false-positive rate that tuning them produces."),
    Tenet.HALLUCINATION: (
        "Deciding what groundedness AFNI requires of an answer, and owning the "
        "consequences of a confident wrong answer reaching a customer."),
    Tenet.ACCOUNTABILITY: (
        "Owning the audit trail and the loud-failure posture: that `unjudged` "
        "always blocks, and that no request field or console switch can relax "
        "it."),
}

#: The one setting AFNI has to make, and what happens without it.
DOMAIN_UNSET_NOTE = (
    f"{ENV_DOMAIN} is not set, so the escalation addresses are aliases without "
    f"a domain. One setting arms all seven. Nothing is invented in the "
    f"meantime: a plausible-looking address that goes nowhere is worse in a "
    f"compliance artefact than a visibly unfinished one.")


@dataclass(frozen=True)
class Owner:
    tenet: Tenet
    role: str
    alias: str
    domain: str | None
    accountable_for: str
    #: "generated" | "configured"
    source: str = "generated"

    @property
    def contact(self) -> str:
        return f"{self.alias}@{self.domain}" if self.domain else self.alias

    @property
    def resolved(self) -> bool:
        """Whether this owner has a reachable escalation address."""
        return bool(self.domain) or self.source == "configured"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenet": self.tenet.value,
            "role": self.role,
            "contact": self.contact,
            "resolved": self.resolved,
            "source": self.source,
            "accountable_for": self.accountable_for,
        }


def domain() -> str | None:
    value = os.environ.get(ENV_DOMAIN, "").strip().lstrip("@")
    return value or None


def _configured() -> dict[str, str]:
    """`AFNI_GOVERNANCE_OWNERS` as `{tenet: contact}`.

    JSON, and a malformed value is IGNORED rather than fatal - a typo in an
    optional governance setting must not stop a guardrail gateway booting. The
    register reports that it was ignored, so the typo is visible.
    """
    raw = os.environ.get(ENV_OWNERS, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    known = {t.value for t in Tenet}
    return {k: str(v) for k, v in parsed.items()
            if k in known and isinstance(v, str) and v.strip()}


def owners() -> list[Owner]:
    """One owner per tenet. Generated unless explicitly configured."""
    configured = _configured()
    out: list[Owner] = []
    for tenet in Tenet:
        # "steward", not "owner". An owner sounds like a person; a steward is a
        # role somebody holds, which is what survives them changing team.
        role = f"{tenet.value} steward — AFNI Responsible AI"
        if tenet.value in configured:
            contact = configured[tenet.value]
            alias, _, dom = contact.partition("@")
            out.append(Owner(tenet=tenet, role=role, alias=alias,
                             domain=dom or None,
                             accountable_for=ACCOUNTABLE_FOR[tenet],
                             source="configured"))
        else:
            out.append(Owner(tenet=tenet, role=role, alias=ALIAS[tenet],
                             domain=domain(),
                             accountable_for=ACCOUNTABLE_FOR[tenet]))
    return out


def _owner_problems() -> list[str]:
    problems: list[str] = []
    raw = os.environ.get(ENV_OWNERS, "").strip()
    if raw and not _configured():
        problems.append(
            f"{ENV_OWNERS} is set but could not be read as a JSON object of "
            f"{{tenet: contact}} with known tenet names, so it was IGNORED and "
            f"the generated roles are in force. Reported rather than fatal: a "
            f"typo in an optional governance setting must not stop a guardrail "
            f"gateway booting.")
    if not domain() and not _configured():
        problems.append(DOMAIN_UNSET_NOTE)
    return problems


# --------------------------------------------------------------------------- #
# The register                                                                #
# --------------------------------------------------------------------------- #
def register(rails: list[Any] | None = None,
             thresholds: Any = None,
             coverage: Any = None) -> dict[str, Any]:
    """The whole register, generated from the LIVE platform.

    Every argument is optional and discovered when omitted, so the CLI, the
    gateway and a test all produce the same document. Discovered rather than
    required because a register assembled from arguments a caller chose is a
    register that can describe a configuration nobody is running.
    """
    from . import sensitivity                                    # noqa: PLC0415

    if rails is None:
        from .cli import load_tenets                             # noqa: PLC0415
        rails, _attrs, _problems = load_tenets()
    if thresholds is None:
        from .tenets.accountability.thresholds import (          # noqa: PLC0415
            ThresholdStore)
        thresholds = ThresholdStore()
        sensitivity.apply_to(thresholds)
    if coverage is None:
        coverage = _coverage()

    by_tenet: dict[str, list[Any]] = {}
    for rail in rails:
        by_tenet.setdefault(rail.tenet.value, []).append(rail)

    saved, _problems = sensitivity.load()
    knobs_by_tenet = _knobs_by_tenet()

    rows = []
    for owner in owners():
        tenet_rails = by_tenet.get(owner.tenet.value, [])
        counts = coverage.get(owner.tenet.value, {}) if coverage else {}
        knobs = []
        for key in knobs_by_tenet.get(owner.tenet.value, []):
            read = thresholds.resolve(key)
            knobs.append({
                "key": key,
                "label": sensitivity.BY_KEY[key].label,
                "effective": read.value,
                "shipped": sensitivity.shipped(key),
                "overridden": key in saved,
            })
        rows.append({
            **owner.to_dict(),
            "coverage": counts,
            "rails_mounted": len(tenet_rails),
            "rails": sorted(r.name for r in tenet_rails),
            "stages": sorted({int(r.stage) for r in tenet_rails}),
            "thresholds": knobs,
        })
    # Reads performed to BUILD the register are not detection-path reads, so
    # they are not evidence of anything and would otherwise pollute the audit
    # log every time somebody opened the page.
    if hasattr(thresholds, "clear_reads"):
        thresholds.clear_reads()

    return {
        "generated": True,
        "tenets": rows,
        "domain": domain(),
        "domain_env": ENV_DOMAIN,
        "owners_env": ENV_OWNERS,
        "problems": _owner_problems(),
        "fail_mode": "closed, unconditionally",
        "fail_mode_note": (
            "There is no request field and no console switch that relaxes it. A "
            "`fail_mode` can be set per risk category by the deployment, but "
            "the fallback is closed and a caller cannot change it."),
        "why_no_names": (
            "Roles, not people. A person's name in a governance register is "
            "stale the moment they change team, and a register with a wrong "
            "escalation path is worse than one with an honest gap. Set "
            f"{ENV_DOMAIN} to arm all seven addresses at once, or "
            f"{ENV_OWNERS} to name individuals per tenet."),
        "counts": {
            "tenets": len(rows),
            "resolved": sum(1 for r in rows if r["resolved"]),
            "rails_mounted": sum(r["rails_mounted"] for r in rows),
            "thresholds_listed": sum(len(r["thresholds"]) for r in rows),
        },
    }


def _knobs_by_tenet() -> dict[str, list[str]]:
    """Map the sensitivity catalogue's groups onto tenets.

    The catalogue is grouped for an OPERATOR ("Prompt attacks", "Media"), and the
    register is grouped for a REVIEWER (the seven tenets). Two audiences, two
    groupings, one mapping - rather than forcing either side to adopt the
    other's vocabulary.
    """
    from . import sensitivity                                    # noqa: PLC0415

    group_to_tenet = {
        "Prompt attacks": Tenet.SECURITY,
        "Content safety": Tenet.CONTENT_SAFETY,
        "Media": Tenet.CONTENT_SAFETY,
        "Privacy": Tenet.PRIVACY,
        "Fairness": Tenet.FAIRNESS,
        "Reliability": Tenet.HALLUCINATION,
        "Not a detection": Tenet.ACCOUNTABILITY,
    }
    # A group added to the catalogue without a tenet here would silently vanish
    # from the register, so it is loud instead.
    missing = sorted(set(sensitivity.groups()) - set(group_to_tenet))
    if missing:  # pragma: no cover - a coding error, not a runtime state
        raise RuntimeError(
            f"sensitivity groups with no tenet in governance._knobs_by_tenet: "
            f"{missing}")
    out: dict[str, list[str]] = {}
    for knob in sensitivity.KNOBS:
        out.setdefault(group_to_tenet[knob.group].value, []).append(knob.key)
    return out


def _coverage() -> dict[str, dict[str, int]]:
    """Capability counts per tenet, from the live registry."""
    import importlib                                             # noqa: PLC0415

    from .registry.capabilities import CapabilityRegistry        # noqa: PLC0415
    from .cli import TENET_PACKAGES                              # noqa: PLC0415

    registry = CapabilityRegistry()
    for pkg in TENET_PACKAGES:
        try:
            module = importlib.import_module(f"{__package__}.tenets.{pkg}")
            module.register(registry)
        except Exception:  # noqa: BLE001 - a tenet that cannot load is a gap,
            continue        # and the coverage report is where that shows up
    report = registry.report()
    out: dict[str, dict[str, int]] = {}
    for tenet, _regs in report.by_tenet.items():
        out[tenet.value] = {status.value: count
                            for status, count in report.counts(tenet).items()}
    return out


def render(body: dict[str, Any] | None = None) -> str:
    """The register as Markdown, for the client approval pack."""
    doc = register() if body is None else body
    lines = ["# AFNI Responsible AI — governance register", ""]
    lines.append("**Generated from the running platform.** It cannot describe a "
                 "configuration that is not in force.")
    lines.append("")
    lines.append(f"Fail mode: **{doc['fail_mode']}**. {doc['fail_mode_note']}")
    lines.append("")
    lines.append("## Why roles rather than names")
    lines.append("")
    lines.append(doc["why_no_names"])
    for problem in doc["problems"]:
        lines += ["", f"> **Unconfigured.** {problem}"]
    lines.append("")

    for row in doc["tenets"]:
        lines.append(f"## {row['tenet']}")
        lines.append("")
        lines.append(f"| | |")
        lines.append(f"|---|---|")
        lines.append(f"| Accountable role | {row['role']} |")
        lines.append(f"| Escalation | `{row['contact']}`"
                     f"{'' if row['resolved'] else ' — **domain unset**'} |")
        lines.append(f"| Rails mounted | {row['rails_mounted']} "
                     f"(stages {', '.join(str(s) for s in row['stages']) or '—'}) |")
        for status, count in sorted(row["coverage"].items()):
            if count:
                lines.append(f"| {status} | {count} |")
        lines.append("")
        lines.append(f"**Accountable for.** {row['accountable_for']}")
        lines.append("")
        if row["thresholds"]:
            lines.append("| Threshold | In force | Shipped | |")
            lines.append("|---|---|---|---|")
            for knob in row["thresholds"]:
                mark = "overridden" if knob["overridden"] else ""
                lines.append(f"| {knob['label']} (`{knob['key']}`) | "
                             f"{knob['effective']} | {knob['shipped']} | {mark} |")
            lines.append("")
    return "\n".join(lines)


__all__ = ["ENV_DOMAIN", "ENV_OWNERS", "ALIAS", "ACCOUNTABLE_FOR", "Owner",
           "domain", "owners", "register", "render"]
