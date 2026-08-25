# -*- coding: utf-8 -*-
"""
The capability registry and the coverage report.

"We cover all the capabilities" is a claim. This module turns it into a number
that can be checked, per tenet, and that reports gaps honestly instead of
rounding them up.

The target is not invented here - it is read from the analysis that already
exists: `analysis/data/capability_matrix_data.json`, the 65 capabilities across
the 7 tenets that back the deck's capability-matrix slides. A rail registers
against a capability by name; anything with no rail shows up as a gap.

Coverage status is deliberately five-valued rather than a bool, because
"covered" hides the distinction that actually matters when someone asks whether
AFNI is protected right now:

    IMPLEMENTED  an AFNI rail exists and runs today, no external anything
    DEPENDENCY   a rail exists but its library or model weights are not
                 installed, so it currently reports `unjudged` - honest, and
                 fail-closed will block on it, but it is not protection yet
    CLOUD        needs a paid managed service that is not configured
    OFFLINE      the only tool for it is a red-team or batch tool; it belongs in
                 CI, and claiming it as runtime cover would be false
    GAP          nothing implements it

A single "covered: 65/65" would be a lie in at least three of those states.
"""
from __future__ import annotations

import json
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum

from ..cascade.rail import Stage
from ..contract.explanation import RailAttribution
from ..contract.models import Tenet

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
CAPABILITY_MATRIX_PATH = os.path.join(
    _REPO_ROOT, "analysis", "data", "capability_matrix_data.json")
METHODOLOGY_PATH = os.path.join(
    _REPO_ROOT, "analysis", "data", "tenet_methodology_data.json")


class Coverage(str, Enum):
    IMPLEMENTED = "implemented"
    DEPENDENCY = "dependency-missing"
    CLOUD = "cloud-not-configured"
    OFFLINE = "offline-only"
    GAP = "gap"


@dataclass(frozen=True)
class Capability:
    """One row of a capability-matrix slide."""

    tenet: Tenet
    name: str
    best_pick: str


@dataclass
class Registration:
    capability: str
    tenet: Tenet
    status: Coverage
    attribution: RailAttribution | None = None
    note: str = ""


@dataclass
class CoverageReport:
    by_tenet: "OrderedDict[Tenet, list[Registration]]" = field(
        default_factory=OrderedDict)

    def counts(self, tenet: Tenet) -> dict[Coverage, int]:
        out = {c: 0 for c in Coverage}
        for reg in self.by_tenet.get(tenet, []):
            out[reg.status] += 1
        return out

    def total_counts(self) -> dict[Coverage, int]:
        out = {c: 0 for c in Coverage}
        for regs in self.by_tenet.values():
            for reg in regs:
                out[reg.status] += 1
        return out

    def render(self) -> str:
        lines = ["AFNI Responsible AI - capability coverage", ""]
        order = [Coverage.IMPLEMENTED, Coverage.DEPENDENCY, Coverage.CLOUD,
                 Coverage.OFFLINE, Coverage.GAP]
        head = f"{'Tenet':32s} " + " ".join(f"{c.value.split('-')[0][:5]:>6s}" for c in order)
        lines += [head, "-" * len(head)]
        for tenet, regs in self.by_tenet.items():
            c = self.counts(tenet)
            lines.append(f"{tenet.value:32s} " +
                         " ".join(f"{c[k]:6d}" for k in order) +
                         f"   ({len(regs)} total)")
        t = self.total_counts()
        lines += ["-" * len(head),
                  f"{'ALL':32s} " + " ".join(f"{t[k]:6d}" for k in order) +
                  f"   ({sum(t.values())} total)", ""]
        lines.append("implemented = runs today  ·  dependency = rail exists, library/weights "
                     "absent, reports unjudged")
        lines.append("cloud = paid service not configured  ·  offline = CI/red-team only, "
                     "not runtime cover  ·  gap = nothing yet")

        gaps = [(tenet, r) for tenet, regs in self.by_tenet.items()
                for r in regs if r.status is Coverage.GAP]
        if gaps:
            lines += ["", f"Gaps ({len(gaps)}):"]
            lines += [f"  {t.value:30s} {r.capability}" for t, r in gaps]
        return "\n".join(lines)


def load_capabilities() -> "OrderedDict[Tenet, list[Capability]]":
    """The 65 capabilities the deck's matrix slides assert, straight from the
    analysis data. Read, never hardcoded, so the platform's coverage target and
    the client-facing deck cannot drift apart."""
    with open(CAPABILITY_MATRIX_PATH, encoding="utf-8") as f:
        matrix = json.load(f)
    by_name = {t.value: t for t in Tenet}
    out: "OrderedDict[Tenet, list[Capability]]" = OrderedDict()
    for tenet_name, block in matrix.items():
        tenet = by_name[tenet_name]
        out[tenet] = [
            Capability(tenet=tenet, name=row["aspect"], best_pick=row.get("best", ""))
            for row in block["rows"]
        ]
    return out


class CapabilityRegistry:
    """Where rails declare what they cover, and where the gaps get counted."""

    def __init__(self) -> None:
        self._capabilities = load_capabilities()
        self._registrations: dict[tuple[Tenet, str], Registration] = {}

    @property
    def capabilities(self) -> "OrderedDict[Tenet, list[Capability]]":
        return self._capabilities

    def names(self, tenet: Tenet) -> list[str]:
        return [c.name for c in self._capabilities[tenet]]

    def register(self, tenet: Tenet, capability: str, status: Coverage,
                 attribution: RailAttribution | None = None, note: str = "") -> None:
        """Declare cover for one capability.

        Registering a name that is not in the matrix is an error, not a warning.
        A typo would otherwise quietly inflate the coverage number while leaving
        the real capability counted as a gap - the exact failure this report
        exists to prevent.
        """
        if capability not in self.names(tenet):
            raise KeyError(
                f"{capability!r} is not a {tenet.value} capability in "
                f"capability_matrix_data.json. Known: {self.names(tenet)}"
            )
        self._registrations[(tenet, capability)] = Registration(
            capability=capability, tenet=tenet, status=status,
            attribution=attribution, note=note)

    def register_rail(self, rail, attribution: RailAttribution,
                      available: bool = True, note: str = "") -> None:
        """Register from a rail plus its attribution, deriving the status.

        An OFFLINE-stage rail is recorded as OFFLINE cover no matter what it can
        do, because it is not in the request path. That keeps the report from
        counting a red-team tool as live protection.
        """
        if attribution.capability is None:
            raise ValueError(f"rail {rail.name!r} has no capability in its attribution")
        if rail.stage is Stage.OFFLINE:
            status = Coverage.OFFLINE
        elif not available:
            status = Coverage.DEPENDENCY
        else:
            status = Coverage.IMPLEMENTED
        self.register(rail.tenet, attribution.capability, status, attribution, note)

    def report(self) -> CoverageReport:
        report = CoverageReport()
        for tenet, caps in self._capabilities.items():
            rows: list[Registration] = []
            for cap in caps:
                rows.append(self._registrations.get(
                    (tenet, cap.name),
                    Registration(capability=cap.name, tenet=tenet, status=Coverage.GAP,
                                 note=f"best pick from the analysis: {cap.best_pick}"),
                ))
            report.by_tenet[tenet] = rows
        return report
