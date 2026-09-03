# -*- coding: utf-8 -*-
"""
Threshold configuration - one of the three things the analysis says AFNI has to
build itself, because no reviewed repo provides it.

THE PATTERN COMES FROM INFOSYS, THE BUG DOES NOT.

Infosys's admin service is the right shape and the only one in the 23 repos:
`responsible-ai-admin/.../mappers/FmConfigMapper.py:66-113` defines
`ModerationCheckThreshold` (PromptinjectionThreshold 0.7, JailbreakThreshold 0.7,
RefusalThreshold 0.7, the seven ToxicityThreshold fields at 0.6, ...) and
`:116-123` wraps it in `FMConfigRequest(...)`. AFNI takes the shipped numbers and
the "prove it was read" discipline, and deliberately NOT the account/portfolio
scoping: a scope no request can select is write-only config, which is the very
bug the next paragraph describes.

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
    # --- Media moderation -------------------------------------------------
    # Infosys NudeNet.py:47 uses `score > 0.5` on the image path; the covered /
    # suggestive band sits higher because it only flags, and a noisy flag an
    # operator learns to ignore is worse than no flag.
    #
    # These three MUST be here rather than left to the last-resort fallback.
    # Without them `resolve("safety.sexual.image_explicit")` returns 0.85 -
    # nothing in this dict prefix-matches it - which would silently raise the
    # explicit-nudity threshold from the ported 0.50 to 0.85 and quietly halve
    # the detector's sensitivity. That is exactly the write-only-config class of
    # bug this module was built to prevent, arriving from the other direction.
    "safety.sexual.image_explicit": 0.50,
    "safety.sexual.image_suggestive": 0.60,
    # Faces are biometric PII. Flag, never block: a photograph of a person is
    # not a policy violation, it is something an operator may need to know about.
    "privacy.pii.face": 0.50,
}


# --- Rail thresholds, keyed by MECHANISM as well as by what is judged --------
# Scores from different mechanisms are not on one scale: a DeBERTa probability, a
# zero-shot NLI entailment score and an LLM judge's self-report mean different
# things, which is why `CONFIDENCE_KINDS` exists in the contract. Collapsing them
# onto one "toxicity" knob would let an operator tighten a classifier and
# unknowingly loosen a judge.
#
# Every value here is the default the rail was PORTED WITH, cited below, so
# wiring the store changed no detection behaviour. Overriding is a deliberate act.
RAIL_DEFAULTS: Mapping[str, float] = {
    # llm-guard input_scanners/toxicity.py (MATCH_TYPE threshold arg default)
    "safety.toxicity.classifier": 0.5,
    # hai-guardrails src/guards/profanity.guard.ts:21-27 / toxic.guard.ts
    "safety.toxicity.judge": 0.8,
    # llm-guard input_scanners/ban_topics.py:104
    "safety.topic_violation.zeroshot": 0.6,
    # llm-guard input_scanners/prompt_injection.py (as mounted here)
    "security.prompt_injection.classifier": 0.9,
    # llm-guard anonymize_helpers default_score_threshold
    "privacy.pii.ner_score": 0.5,
    # deepteam metrics/pii/pii.py
    "privacy.pii.leakage_judge": 0.5,
    # garak resources/matching.py n-gram containment, as mounted here
    "privacy.system_prompt_leakage": 0.6,
    # llm-guard output_scanners/bias.py:15
    "x.afni.bias.classifier": 0.7,
    # hai-guardrails src/guards/bias-detection.guard.ts:74-103
    "x.afni.bias.judge": 0.7,
    # deepeval G-Eval, as mounted here
    "x.afni.rubric": 0.5,
}

# Safe Zone thresholds.go:23 - the fallback used when no key matches at all.
LAST_RESORT_THRESHOLD = 0.85


class ThresholdMisconfigured(ValueError):
    """A configured threshold is not a usable score.

    Raised from the *resolution* path, not from config ingestion, and that is
    deliberate. Config arrives from an admin service that may not have validated
    it (Infosys's FMConfigRequest is pydantic-typed as `float` and accepts 1.7
    happily). A rail catches this and returns `RailResult.unjudged(...)`, which
    fail-closed then turns into a block - a misconfigured threshold becomes
    loudly visible instead of quietly permissive.
    """


class ThresholdScope(str, Enum):
    """Where a resolved value came from. Returned to the caller so an operator
    can see *which* level of config won, which is the question the Safe Zone
    admin UI could not answer."""

    OVERRIDE = "override"
    OVERRIDE_PREFIX = "override-prefix"
    GLOBAL = "global"
    LAST_RESORT = "last-resort"


@dataclass(frozen=True)
class ThresholdRead:
    """One resolution performed by the detection path.

    This exists so a test can prove consultation. See the module docstring.
    """

    key: str
    value: float
    scope: ThresholdScope
    source: str
    at: float


@dataclass
class ThresholdOverrides:
    """The operator's overrides on top of the shipped defaults.

    There is ONE of these per gateway. An earlier revision keyed overrides by
    account and portfolio, mirroring Infosys's AccountName/PortfolioName pair;
    that dimension was removed because nothing could set it on a request, and a
    scope nobody can select is the write-only-config bug this module exists to
    prevent, merely relocated.

    `thresholds` keys are AFNI `Finding.category` paths, or a category prefix
    ending in `.*` - the same glob shape OpenGuardrails uses for per-category
    configuration in `specification/degraded-mode.md:27-30`.
    """

    thresholds: Mapping[str, float] = field(default_factory=dict)
    # Which checks run at all. An empty set means "no opinion, run everything
    # mounted"; declaring a set is opt-in narrowing.
    checks_enabled: frozenset[str] = frozenset()
    # Per-category fail_mode overrides, consumed by policy.FailurePolicy.
    fail_modes: Mapping[str, str] = field(default_factory=dict)
    label: str = ""

    def audit(self) -> list[str]:
        """Admin-time validation. Returns human-readable problems rather than
        raising, because an admin UI wants to show all of them at once."""
        problems: list[str] = []
        for key, value in self.thresholds.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"{key}: {value!r} is not a number")
            elif not 0.0 <= float(value) <= 1.0:
                problems.append(
                    f"{key}: {value} is outside [0, 1] and cannot be "
                    "compared against a detector score")
        return problems


def _prefix_match(keys: Iterable[str], key: str) -> str | None:
    """Longest-prefix wildcard match. `security.*` matches
    `security.prompt_injection`; the longest matching pattern wins, so an
    operator can set a broad default and a narrow exception."""
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
    """Resolves a threshold for a category, and records that it did.

    Resolution order, narrowest first:

        override exact -> override prefix -> global default -> last resort

    Nothing here caches: a threshold change must take effect on the next request,
    which is the one thing Safe Zone's `cache.ClearCache` call at admin.go:75 got
    right even though the value it invalidated was never read.
    """

    def __init__(self, defaults: Mapping[str, float] | None = None,
                 last_resort: float = LAST_RESORT_THRESHOLD) -> None:
        # RAIL_DEFAULTS first so an explicit GLOBAL_DEFAULTS entry wins on a
        # key collision; both are overridable by the override layer above.
        self._defaults: dict[str, float] = dict(RAIL_DEFAULTS)
        self._defaults.update(GLOBAL_DEFAULTS if defaults is None else defaults)
        self._last_resort = float(last_resort)
        self._overrides: ThresholdOverrides | None = None
        self._reads: list[ThresholdRead] = []

    # ------------------------------------------------------------------ admin --
    def put_overrides(self, config: ThresholdOverrides) -> None:
        self._overrides = config

    def overrides(self) -> ThresholdOverrides | None:
        return self._overrides

    def audit(self) -> list[str]:
        """Every misconfiguration in the override layer. This is what an admin
        service should call before persisting, and what nobody in the reviewed
        set actually does."""
        return list(self._overrides.audit()) if self._overrides is not None else []

    # -------------------------------------------------------------- detection --
    @property
    def reads(self) -> list[ThresholdRead]:
        """Every resolution the detection path has performed. Read by the test
        that proves a configured threshold is genuinely consulted."""
        return list(self._reads)

    def read_count(self, key: str | None = None) -> int:
        return sum(1 for r in self._reads if key is None or r.key == key)

    def clear_reads(self) -> None:
        self._reads.clear()

    def resolve(self, key: str) -> ThresholdRead:
        """The detection path's only entry point. Always logs.

        Raises `ThresholdMisconfigured` when the winning value is not a score in
        [0, 1]. The caller must translate that into `unjudged`, never into a
        default - silently substituting 0.85 for a bad config is how a tuned
        threshold turns into a lie.
        """
        value, scope, source = self._lookup(key)
        read = ThresholdRead(key=key, value=float(value), scope=scope,
                             source=source, at=time.time())
        # Logged before validation on purpose: an attempted read of a broken
        # threshold is exactly the event an operator needs to see.
        self._reads.append(read)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ThresholdMisconfigured(
                f"threshold {key!r} is {value!r}, not a number (source {source})")
        if not 0.0 <= float(value) <= 1.0:
            raise ThresholdMisconfigured(
                f"threshold {key!r} is {value}, outside [0, 1] (source {source}) "
                "- cannot be compared against a detector score")
        return read

    def _lookup(self, key: str) -> tuple[float, ThresholdScope, str]:
        cfg = self._overrides
        if cfg is not None:
            if key in cfg.thresholds:
                return cfg.thresholds[key], ThresholdScope.OVERRIDE, "override"
            pattern = _prefix_match(cfg.thresholds, key)
            if pattern is not None:
                return (cfg.thresholds[pattern], ThresholdScope.OVERRIDE_PREFIX,
                        f"override:{pattern}")

        if key in self._defaults:
            return self._defaults[key], ThresholdScope.GLOBAL, "global-default"
        pattern = _prefix_match(self._defaults, key)
        if pattern is not None:
            return (self._defaults[pattern], ThresholdScope.GLOBAL,
                    f"global-default:{pattern}")
        return self._last_resort, ThresholdScope.LAST_RESORT, "last-resort"

    def resolve_value(self, key: str) -> float | None:
        """The callable the cascade injects into `CheckContext.resolve`.

        Returns the resolved score, or **None** when the stored value is
        unusable, so the rail falls back to the threshold it was ported with.

        That is a deliberate softening of `resolve()`'s contract, and worth
        stating rather than burying. `resolve()` argues a bad config must become
        `unjudged`, never a default, because silently substituting a number turns
        a tuned threshold into a lie. The argument is right about the lie and
        wrong about the remedy at this particular seam: `unjudged` fails closed,
        so a single typo in the override layer would take all traffic down.

        So the fallback happens, and is made loud in two places instead of one:
        the store's own read log records the attempted read of the broken value
        (it logs before validating, on purpose), and `CheckContext.reads` records
        the source as `rail-default-after-resolver-error`, which lands in
        `CascadeOutcome.threshold_reads` and from there in the audit record. An
        operator sees that their value did not take effect; traffic keeps
        flowing. `audit()` is the surface that should page someone.

        `ThresholdMisconfigured` is deliberately NOT caught here. Swallowing it
        into a None would make a rejected value indistinguishable from a value
        nobody ever set - both would land in the read log as plain
        "rail-default", so an operator who typed 42.0 would see exactly what one
        who configured nothing sees. `CheckContext.threshold` catches it and
        labels the read `rail-default-after-resolver-error`, which keeps the two
        cases tellable apart in the audit trail.
        """
        return self.resolve(key).value

    def check_enabled(self, check: str) -> bool:
        """Infosys FMConfigRequest.ModerationChecks, collapsed to one scope. No
        declared set runs everything mounted; declaring a set is opt-in
        narrowing."""
        cfg = self._overrides
        if cfg is None or not cfg.checks_enabled:
            return True
        return check in cfg.checks_enabled

    def render(self) -> str:
        cfg = self._overrides
        lines = ["Threshold configuration",
                 f"  global defaults : {len(self._defaults)} keys "
                 f"(last resort {self._last_resort})",
                 f"  overrides       : "
                 f"{len(cfg.thresholds) if cfg else 0} keys",
                 f"  resolutions     : {len(self._reads)} recorded"]
        problems = self.audit()
        if problems:
            lines.append(f"  MISCONFIGURED   : {len(problems)}")
            lines += [f"    - {p}" for p in problems]
        return "\n".join(lines)
