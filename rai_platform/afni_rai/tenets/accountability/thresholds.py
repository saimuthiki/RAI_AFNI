# -*- coding: utf-8 -*-
"""
Per-tenant threshold configuration - one of the three things the analysis says
AFNI has to build itself, because no reviewed repo provides it.

THE PATTERN COMES FROM INFOSYS, THE BUG DOES NOT.

Infosys's admin service is the right shape and the only one in the 23 repos:
`responsible-ai-admin/.../mappers/FmConfigMapper.py:66-113` defines
`ModerationCheckThreshold` (PromptinjectionThreshold 0.7, JailbreakThreshold 0.7,
RefusalThreshold 0.7, the seven ToxicityThreshold fields at 0.6, ...) and
`:116-123` wraps it in `FMConfigRequest(AccountName, PortfolioName,
ModerationChecks, ModerationCheckThresholds)` - a threshold set scoped to an
account *and* a portfolio. That two-level scope is exactly what AFNI needs: a
default per business unit, overridden per client.

The bug to avoid was found in Safe Zone. Its per-pattern thresholds are stored
and API-exposed - `internal/handlers/admin.go:66-67` writes
`pattern.BlockThreshold` / `pattern.AllowThreshold` to the database and busts the
cache "so policy is applied immediately" - but nothing in the detection path ever
reads them. `internal/guardrails/guardrails.go:287-288`, inside `Detector.Detect` (guardrails.go:61), calls
`getBlockThreshold()` / `getAllowThreshold()`, which are
`internal/guardrails/thresholds.go:8-24`: environment variables with hardcoded
0.85 / 0.30 fallbacks and no reference to the stored pattern at all. An operator
can tune a threshold in the admin UI, watch it persist, and change nothing about
what gets blocked.

So this module keeps a `reads` log of every resolution the detection path
performs, and `test_accountability.py` asserts against it. A configured threshold
that is never consulted is a silent lie, and the only way to keep it honest is to
make "was it actually read?" a testable fact rather than an intention.

Zero third-party dependencies.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

# --------------------------------------------------------------------------- #
# Defaults. Every value here is a number read out of the vendored source, not a
# guess. Where a repo ships a threshold as a pydantic `Field(example=...)` that
# is what its own service defaults to, and it is cited as such.
# --------------------------------------------------------------------------- #
GLOBAL_DEFAULTS: dict[str, float] = {
    # Infosys FmConfigMapper.py:67-68 - ModerationCheckThreshold
    "security.prompt_injection": 0.70,
    "security.jailbreak": 0.70,
    # Infosys FmConfigMapper.py:105 - RefusalThreshold
    "x.afni.refusal": 0.70,
    # Infosys FmConfigMapper.py:23-29 - all seven ToxicityThreshold fields are 0.6
    "safety.toxicity": 0.60,
    # Infosys FmConfigMapper.py:32 - RestrictedtopicThreshold
    "safety.topic_violation": 0.70,
    # Infosys FmConfigMapper.py:57 - GibberishThreshold
    "x.afni.gibberish": 0.70,
    # Infosys FmConfigMapper.py:113 - BanCodeThreshold
    "x.afni.ban_code": 0.70,
    # hai-guardrails copyrightGuard ships threshold 0.8 (methodology.md, Accountability row)
    "x.afni.copyright": 0.80,
    # JCB eval_utils.py:247 - "0.6 works well"; near-duplicate Jaccard over word sets
    "x.afni.attack_corpus.similarity": 0.60,
    # Safe Zone internal/guardrails/thresholds.go:14,23 - the two envelope bounds
    "x.afni.confidence.allow": 0.30,
    "x.afni.confidence.block": 0.85,
}

# Safe Zone thresholds.go:23 - the fallback used when no key matches at all.
LAST_RESORT_THRESHOLD = 0.85


class ThresholdMisconfigured(ValueError):
    """A configured threshold is not a usable score.

    Raised from the *resolution* path, not from config ingestion, and that is
    deliberate. Config arrives from an admin service that may not have validated
    it (Infosys's FMConfigRequest is pydantic-typed as `float` and accepts 1.7
    happily). A rail catches this and returns `RailResult.unjudged(...)`, which
    fail-closed then turns into a block on client-facing traffic - a
    misconfigured threshold becomes loudly visible instead of quietly permissive.
    """


class ThresholdScope(str, Enum):
    """Where a resolved value came from. Returned to the caller so an operator
    can see *which* level of config won, which is the question the Safe Zone
    admin UI could not answer."""

    TENANT = "tenant"
    TENANT_PREFIX = "tenant-prefix"
    PORTFOLIO = "portfolio"
    PORTFOLIO_PREFIX = "portfolio-prefix"
    GLOBAL = "global"
    LAST_RESORT = "last-resort"


@dataclass(frozen=True)
class ThresholdRead:
    """One resolution performed by the detection path.

    This exists so a test can prove consultation. See the module docstring.
    """

    tenant: str | None
    key: str
    value: float
    scope: ThresholdScope
    source: str
    at: float


@dataclass
class TenantConfig:
    """One account's overrides. Modelled on Infosys FMConfigRequest
    (FmConfigMapper.py:116-123): an account name, the portfolio it inherits from,
    the set of checks it has enabled, and the threshold overrides.

    `thresholds` keys are AFNI `Finding.category` paths, or a category prefix
    ending in `.*` - the same glob shape OpenGuardrails uses for per-category
    configuration in `specification/degraded-mode.md:27-30`.
    """

    tenant: str
    portfolio: str | None = None
    thresholds: Mapping[str, float] = field(default_factory=dict)
    # Infosys FMConfigRequest.ModerationChecks - which checks this account runs
    # at all. An empty set means "no opinion, run everything mounted".
    checks_enabled: frozenset[str] = frozenset()
    # Per-category fail_mode overrides, consumed by policy.FailurePolicy. Kept on
    # the same object so a client's risk posture is one record, not two.
    fail_modes: Mapping[str, str] = field(default_factory=dict)
    label: str = ""

    def audit(self) -> list[str]:
        """Admin-time validation. Returns human-readable problems rather than
        raising, because an admin UI wants to show all of them at once."""
        problems: list[str] = []
        for key, value in self.thresholds.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"{self.tenant}/{key}: {value!r} is not a number")
            elif not 0.0 <= float(value) <= 1.0:
                problems.append(
                    f"{self.tenant}/{key}: {value} is outside [0, 1] and cannot be "
                    "compared against a detector score")
        return problems


def _prefix_match(keys: Iterable[str], key: str) -> str | None:
    """Longest-prefix wildcard match. `security.*` matches
    `security.prompt_injection`; the longest matching pattern wins, so a tenant
    can set a broad default and a narrow exception."""
    best: str | None = None
    for pattern in keys:
        if not pattern.endswith(".*"):
            continue
        stem = pattern[:-2]
        if key == stem or key.startswith(stem + "."):
            if best is None or len(pattern) > len(best):
                best = pattern
    return best


class ThresholdStore:
    """Resolves a threshold for (tenant, category), and records that it did.

    Resolution order, narrowest first:

        tenant exact -> tenant prefix -> portfolio exact -> portfolio prefix
        -> global default -> last resort

    Nothing here caches: a threshold change must take effect on the next request,
    which is the one thing Safe Zone's `cache.ClearCache` call at admin.go:75 got
    right even though the value it invalidated was never read.
    """

    def __init__(self, defaults: Mapping[str, float] | None = None,
                 last_resort: float = LAST_RESORT_THRESHOLD) -> None:
        self._defaults: dict[str, float] = dict(
            GLOBAL_DEFAULTS if defaults is None else defaults)
        self._last_resort = float(last_resort)
        self._tenants: dict[str, TenantConfig] = {}
        self._portfolios: dict[str, TenantConfig] = {}
        self._reads: list[ThresholdRead] = []

    # ------------------------------------------------------------------ admin --
    def put_tenant(self, config: TenantConfig) -> None:
        self._tenants[config.tenant] = config

    def put_portfolio(self, config: TenantConfig) -> None:
        """A portfolio is just a TenantConfig used as a parent, mirroring
        Infosys's AccountName/PortfolioName pair."""
        self._portfolios[config.tenant] = config

    def tenant(self, tenant: str | None) -> TenantConfig | None:
        return self._tenants.get(tenant) if tenant else None

    def audit(self) -> list[str]:
        """Every misconfiguration across every registered account. This is what
        an admin service should call before persisting, and what nobody in the
        reviewed set actually does."""
        problems: list[str] = []
        for cfg in list(self._portfolios.values()) + list(self._tenants.values()):
            problems.extend(cfg.audit())
        return problems

    # -------------------------------------------------------------- detection --
    @property
    def reads(self) -> list[ThresholdRead]:
        """Every resolution the detection path has performed. Read by the test
        that proves a configured threshold is genuinely consulted."""
        return list(self._reads)

    def read_count(self, tenant: str | None = None, key: str | None = None) -> int:
        return sum(1 for r in self._reads
                   if (tenant is None or r.tenant == tenant)
                   and (key is None or r.key == key))

    def clear_reads(self) -> None:
        self._reads.clear()

    def resolve(self, tenant: str | None, key: str) -> ThresholdRead:
        """The detection path's only entry point. Always logs.

        Raises `ThresholdMisconfigured` when the winning value is not a score in
        [0, 1]. The caller must translate that into `unjudged`, never into a
        default - silently substituting 0.85 for a bad config is how a tuned
        threshold turns into a lie.
        """
        value, scope, source = self._lookup(tenant, key)
        read = ThresholdRead(tenant=tenant, key=key, value=float(value), scope=scope,
                             source=source, at=time.time())
        # Logged before validation on purpose: an attempted read of a broken
        # threshold is exactly the event an operator needs to see.
        self._reads.append(read)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ThresholdMisconfigured(
                f"threshold {key!r} for tenant {tenant!r} is {value!r}, not a number "
                f"(source {source})")
        if not 0.0 <= float(value) <= 1.0:
            raise ThresholdMisconfigured(
                f"threshold {key!r} for tenant {tenant!r} is {value}, outside [0, 1] "
                f"(source {source}) - cannot be compared against a detector score")
        return read

    def _lookup(self, tenant: str | None, key: str
                ) -> tuple[float, ThresholdScope, str]:
        cfg = self._tenants.get(tenant) if tenant else None
        if cfg is not None:
            if key in cfg.thresholds:
                return cfg.thresholds[key], ThresholdScope.TENANT, f"tenant:{cfg.tenant}"
            pattern = _prefix_match(cfg.thresholds, key)
            if pattern is not None:
                return (cfg.thresholds[pattern], ThresholdScope.TENANT_PREFIX,
                        f"tenant:{cfg.tenant}:{pattern}")

        parent_name = cfg.portfolio if cfg is not None else None
        parent = self._portfolios.get(parent_name) if parent_name else None
        if parent is not None:
            if key in parent.thresholds:
                return (parent.thresholds[key], ThresholdScope.PORTFOLIO,
                        f"portfolio:{parent.tenant}")
            pattern = _prefix_match(parent.thresholds, key)
            if pattern is not None:
                return (parent.thresholds[pattern], ThresholdScope.PORTFOLIO_PREFIX,
                        f"portfolio:{parent.tenant}:{pattern}")

        if key in self._defaults:
            return self._defaults[key], ThresholdScope.GLOBAL, "global-default"
        pattern = _prefix_match(self._defaults, key)
        if pattern is not None:
            return (self._defaults[pattern], ThresholdScope.GLOBAL,
                    f"global-default:{pattern}")
        return self._last_resort, ThresholdScope.LAST_RESORT, "last-resort"

    def check_enabled(self, tenant: str | None, check: str) -> bool:
        """Infosys FMConfigRequest.ModerationChecks. An account with no declared
        set runs everything mounted; declaring a set is opt-in narrowing."""
        cfg = self._tenants.get(tenant) if tenant else None
        if cfg is None or not cfg.checks_enabled:
            return True
        return check in cfg.checks_enabled

    def render(self) -> str:
        lines = ["Per-tenant threshold configuration",
                 f"  global defaults : {len(self._defaults)} keys "
                 f"(last resort {self._last_resort})",
                 f"  portfolios      : {sorted(self._portfolios)}",
                 f"  accounts        : {sorted(self._tenants)}",
                 f"  resolutions     : {len(self._reads)} recorded"]
        problems = self.audit()
        if problems:
            lines.append(f"  MISCONFIGURED   : {len(problems)}")
            lines += [f"    - {p}" for p in problems]
        return "\n".join(lines)
