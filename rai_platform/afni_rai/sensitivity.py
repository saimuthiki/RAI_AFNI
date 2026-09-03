# -*- coding: utf-8 -*-
"""
Sensitivity - the operator's threshold overrides, and where they belong.

AFNI asked whether thresholds should live in the UI or in the code, and asked for
a recommendation rather than just an implementation. The recommendation is
BOTH, in three layers, and only the middle one is in the UI:

  1. THE CODE ships every default, each one cited to the source repo it was
     ported from (`thresholds.py`). Changing one is a code change and a code
     review. This is the floor: a deployment that never opens the console still
     runs on real, defensible numbers rather than zeros.

  2. THE CONSOLE overrides them per deployment, saved to a JSON file on the
     server and applied on the next request. Tuning is an operational act -
     "toxicity is too noisy on our support queue" is learned in production, not
     at review time - so it must not need a deploy.

  3. A REQUEST CANNOT SET ONE. Not a field, not a header, not a query
     parameter. Same reasoning as the topic policy and `AFNI_REVEAL_SUBJECT`: a
     caller who can raise a threshold can route around the guardrail, and the
     guardrail exists precisely because the caller is not trusted.

WHY THIS IS SAFE TO PUT IN A UI WHEN THE TOPIC LIST NEEDED A RESTART

`ThresholdStore` deliberately does not cache: "a threshold change must take
effect on the next request". So a saved value is live immediately. The topic
rail compiles its word and phrase sets once at construction and therefore needs
a restart. Two different mechanisms, two different answers, and the UI says which
is which rather than giving one hedged answer for both.

MAXIMUM SENSITIVITY IS NOT MAXIMUM SAFETY, AND THE UI SAYS SO

AFNI asked whether they could just "set the maximum sensitivity". They can - the
`maximum` preset here does exactly that - but it is worth being blunt about the
trade rather than shipping a button that sounds free. Lowering a threshold does
not find more harm; it lowers the bar for calling something harm. The detector's
ranking is unchanged. What changes is that more legitimate work gets refused, and
a guardrail that refuses legitimate work gets switched off by the business inside
a fortnight. That is a worse outcome than a threshold at 0.7.

So the presets are offered with the number of false-positive-prone keys they
touch, and `maximum` is labelled what it is: a red-team and demonstration
setting.

Zero third-party dependencies.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .tenets.accountability.thresholds import (
    GLOBAL_DEFAULTS, LAST_RESORT_THRESHOLD, RAIL_DEFAULTS, ThresholdOverrides,
    ThresholdStore)

ENV_POLICY_PATH = "AFNI_THRESHOLD_POLICY"
DEFAULT_POLICY_FILENAME = "afni_thresholds.json"

#: Every key an operator may override. Deliberately a CLOSED set built from the
#: two default maps: an override for a key no rail resolves is write-only
#: config, which is the exact bug `thresholds.py` was written to prevent.
KNOWN: tuple[str, ...] = tuple(sorted(set(GLOBAL_DEFAULTS) | set(RAIL_DEFAULTS)))


@dataclass(frozen=True)
class Knob:
    """One tunable threshold, described for somebody deciding rather than
    debugging.

    `direction` is the honest part. For most keys a lower number means "call
    more things a violation", and calling that "stricter" is fair. For three of
    them it does not mean that, and a preset that dragged every number down
    would quietly change what those three mean - so they are excluded from the
    presets and labelled.
    """

    key: str
    label: str
    group: str
    judges: str
    #: "lower-is-stricter" | "envelope" | "not-a-detection"
    direction: str = "lower-is-stricter"
    #: False-positive-prone: tightening this one is what an operator will regret.
    noisy: bool = False


#: The catalogue. Every key in `KNOWN` must appear here exactly once - asserted
#: at import, because a knob missing from this list would be invisible in the UI
#: while still being live in the engine.
KNOBS: tuple[Knob, ...] = (
    # ---- Prompt attacks -----------------------------------------------------
    Knob("security.prompt_injection", "Prompt injection", "Prompt attacks",
         "A message trying to override its own instructions.", noisy=True),
    Knob("security.prompt_injection.classifier",
         "Prompt injection — classifier", "Prompt attacks",
         "The DeBERTa model's own confidence, before the category threshold.",
         noisy=True),
    Knob("security.jailbreak", "Jailbreak", "Prompt attacks",
         "A message trying to escape the model's safety training.", noisy=True),
    Knob("x.afni.attack_corpus.similarity", "Repeat-attack similarity",
         "Prompt attacks",
         "How near-identical a message must be to a known attack to count as "
         "the same one. Jaccard over word sets."),

    # ---- Content safety -----------------------------------------------------
    Knob("safety.toxicity", "Toxicity", "Content safety",
         "Abuse, hate and harassment, as a category verdict.", noisy=True),
    Knob("safety.toxicity.classifier", "Toxicity — classifier",
         "Content safety", "The local model's own score.", noisy=True),
    Knob("safety.toxicity.judge", "Toxicity — LLM judge", "Content safety",
         "A Stage-3 judge's self-reported confidence. Costs money per call."),
    Knob("safety.topic_violation", "Off-topic", "Content safety",
         "A message outside what this application is for.", noisy=True),
    Knob("safety.topic_violation.zeroshot", "Off-topic — zero-shot",
         "Content safety",
         "Entailment score from the zero-shot classifier.", noisy=True),

    # ---- Media --------------------------------------------------------------
    Knob("safety.sexual.image_explicit", "Image — explicit", "Media",
         "Exposure in an image or video frame. This one BLOCKS."),
    Knob("safety.sexual.image_suggestive", "Image — suggestive", "Media",
         "Covered but suggestive. Flags only, never blocks.", noisy=True),
    Knob("privacy.pii.face", "Image — face", "Media",
         "A detected face, reported as biometric PII. Flags only."),

    # ---- Privacy ------------------------------------------------------------
    Knob("privacy.pii.ner_score", "PII — name recognition", "Privacy",
         "How confident the entity model must be that a span is a person, "
         "place or organisation.", noisy=True),
    Knob("privacy.pii.leakage_judge", "PII — leakage judge", "Privacy",
         "A judge deciding whether a response leaked personal data."),
    Knob("privacy.system_prompt_leakage", "System-prompt leakage", "Privacy",
         "How much of the system prompt must appear in a response to count as "
         "a leak. N-gram containment."),

    # ---- Fairness -----------------------------------------------------------
    Knob("x.afni.bias.classifier", "Bias — classifier", "Fairness",
         "The local bias model's score on a response."),
    Knob("x.afni.bias.judge", "Bias — LLM judge", "Fairness",
         "A judge's confidence that a response is biased."),

    # ---- Reliability --------------------------------------------------------
    Knob("x.afni.rubric", "Rubric score", "Reliability",
         "The pass mark for a G-Eval style rubric."),
    Knob("x.afni.gibberish", "Gibberish", "Reliability",
         "How confident before a response is called incoherent."),
    Knob("x.afni.ban_code", "Code in a response", "Reliability",
         "How confident before a response is treated as containing code."),
    Knob("x.afni.copyright", "Copyright", "Reliability",
         "How close to known copyrighted text before it is flagged."),

    # ---- The three that are not simple detections ---------------------------
    Knob("x.afni.refusal", "Refusal detection", "Not a detection",
         "How confident before a response is classed as a refusal. This "
         "measures the MODEL's behaviour, not a user's - lowering it does not "
         "make anything stricter, it makes more answers get called refusals.",
         direction="not-a-detection"),
    Knob("x.afni.confidence.allow", "Envelope — allow below", "Not a detection",
         "Scores under this are allowed without escalating. One half of a "
         "two-sided envelope, so it moves with its partner or not at all.",
         direction="envelope"),
    Knob("x.afni.confidence.block", "Envelope — block above", "Not a detection",
         "Scores over this are blocked without escalating. The other half.",
         direction="envelope"),
)

BY_KEY: dict[str, Knob] = {k.key: k for k in KNOBS}

# A knob missing here is a threshold that is live in the engine and invisible in
# the console, which is how an operator ends up believing they have tuned
# something they have not. Loud at import rather than subtle at runtime.
_missing = sorted(set(KNOWN) - set(BY_KEY))
_extra = sorted(set(BY_KEY) - set(KNOWN))
if _missing or _extra:  # pragma: no cover - a coding error, not a runtime state
    raise RuntimeError(
        f"sensitivity.KNOBS is out of step with thresholds.py: "
        f"missing {_missing}, unknown {_extra}")


def groups() -> list[str]:
    """Group names in catalogue order, deduplicated."""
    seen: dict[str, None] = {}
    for knob in KNOBS:
        seen.setdefault(knob.group, None)
    return list(seen)


def shipped(key: str) -> float:
    """The default this key resolves to with no overrides at all.

    RAIL_DEFAULTS first then GLOBAL_DEFAULTS, matching `ThresholdStore.__init__`
    exactly - if the two disagreed the UI would show a number the engine does
    not use.
    """
    merged = dict(RAIL_DEFAULTS)
    merged.update(GLOBAL_DEFAULTS)
    return float(merged.get(key, LAST_RESORT_THRESHOLD))


# --------------------------------------------------------------------------- #
# Presets                                                                     #
#                                                                             #
# A preset is not a separate mechanism. It is a bulk write of the same override #
# map an operator could type by hand, which is why there is nothing here that   #
# can be set by a preset and not un-set by editing one row.                    #
# --------------------------------------------------------------------------- #
#: Multipliers, not absolute numbers, so a preset stays correct when a shipped
#: default changes. `balanced` is the empty override map: it means "use what the
#: code ships", not "0.7 everywhere".
PRESETS: dict[str, dict[str, Any]] = {
    "balanced": {
        "label": "Balanced (shipped)",
        "factor": None,
        "why": "Every threshold as ported, each one cited to the repository it "
               "came from. Clears all overrides.",
    },
    "strict": {
        "label": "Strict",
        "factor": 0.75,
        "floor": 0.25,
        "why": "Every detection threshold at three quarters of its shipped "
               "value. Catches more, refuses more legitimate work.",
    },
    "maximum": {
        "label": "Maximum sensitivity",
        "factor": 0.0,
        "floor": 0.10,
        "why": "Every detection threshold at 0.10. This is a red-team and "
               "demonstration setting, not a production one: at 0.10 a "
               "classifier's noise floor becomes a finding.",
    },
}


def preset_overrides(name: str) -> dict[str, float]:
    """The override map a preset writes.

    The three `direction != "lower-is-stricter"` knobs are EXCLUDED. Dragging
    the refusal detector or either half of the confidence envelope down with
    everything else would not make the platform stricter; it would change what
    those three measure, which is not what an operator pressing "stricter"
    is asking for.
    """
    spec = PRESETS.get(name)
    if spec is None:
        raise KeyError(name)
    factor = spec.get("factor")
    if factor is None:
        return {}
    floor = float(spec.get("floor", 0.0))
    out: dict[str, float] = {}
    for knob in KNOBS:
        if knob.direction != "lower-is-stricter":
            continue
        value = max(floor, round(shipped(knob.key) * float(factor), 2))
        out[knob.key] = min(1.0, value)
    return out


def preset_targets() -> list[str]:
    """Which keys a preset touches. Reported so the exclusions are visible."""
    return [k.key for k in KNOBS if k.direction == "lower-is-stricter"]


# --------------------------------------------------------------------------- #
# The policy file                                                             #
# --------------------------------------------------------------------------- #
def policy_path() -> Path:
    override = os.environ.get(ENV_POLICY_PATH, "").strip()
    return Path(override) if override else Path(DEFAULT_POLICY_FILENAME)


def load(path: Path | None = None) -> tuple[dict[str, float], list[str]]:
    """Read the saved overrides. Returns (overrides, problems).

    A missing or corrupt file is an EMPTY override map plus a problem string,
    never an exception. The same asymmetry as the topic policy and for the same
    reason: the shipped defaults do not come from this file, so a broken file
    must degrade to "use the code's numbers" rather than stop the gateway
    booting. The problems list is what `GET /v1/thresholds` reports, so a
    rejected value is visible rather than silently absent.
    """
    p = policy_path() if path is None else path
    problems: list[str] = []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, problems
    except OSError as exc:
        return {}, [f"{p} could not be read ({exc}) - shipped defaults are in use"]
    except ValueError as exc:
        return {}, [f"{p} is not valid JSON ({exc}) - shipped defaults are in use"]
    if not isinstance(raw, dict):
        return {}, [f"{p} does not hold a JSON object - shipped defaults are in use"]

    out: dict[str, float] = {}
    for key, value in (raw.get("thresholds") or {}).items():
        if key not in BY_KEY:
            problems.append(
                f"{key!r} is not a threshold this platform resolves, so an "
                f"override for it would never be read - ignored")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{key}: {value!r} is not a number - ignored")
            continue
        if not 0.0 <= float(value) <= 1.0:
            problems.append(
                f"{key}: {value} is outside [0, 1] and cannot be compared "
                f"against a detector score - ignored")
            continue
        out[key] = float(value)
    return out, problems


def save(overrides: Mapping[str, float], path: Path | None = None,
         preset: str | None = None) -> None:
    p = policy_path() if path is None else path
    body: dict[str, Any] = {"thresholds": {k: overrides[k]
                                           for k in sorted(overrides)}}
    if preset:
        # Recorded for the operator's benefit only. It is NOT read back to
        # recompute anything: the thresholds map is the truth, so editing one row
        # by hand cannot leave the file claiming a preset it no longer matches.
        body["preset_applied"] = preset
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def as_overrides(overrides: Mapping[str, float],
                 label: str = "") -> ThresholdOverrides:
    return ThresholdOverrides(thresholds=dict(overrides), label=label)


def apply_to(store: ThresholdStore, path: Path | None = None) -> list[str]:
    """Load the file and push it into a live store. Returns any problems.

    Called at gateway construction. Without it the console could write a policy
    file that nothing ever read - write-only config, the bug this whole
    subsystem is a reaction to.
    """
    overrides, problems = load(path)
    store.put_overrides(as_overrides(overrides, label=str(policy_path())))
    return problems


def summary(store: ThresholdStore | None = None) -> dict[str, Any]:
    """The whole catalogue plus what is in force - `GET /v1/thresholds`.

    `effective` and `scope` come from the STORE, not from arithmetic on the file,
    so the number shown is the number a rail would get. Recomputing it here
    would be a second implementation of resolution and the two would drift.
    """
    saved, problems = load()
    resolver = store if store is not None else ThresholdStore()
    if store is None:
        resolver.put_overrides(as_overrides(saved))

    rows = []
    for knob in KNOBS:
        read = resolver.resolve(knob.key)
        rows.append({
            "key": knob.key,
            "label": knob.label,
            "group": knob.group,
            "judges": knob.judges,
            "direction": knob.direction,
            "noisy": knob.noisy,
            "shipped": shipped(knob.key),
            "effective": read.value,
            "scope": read.scope.value,
            "overridden": knob.key in saved,
        })
    # The reads this summary itself performed are noise in the audit log, so they
    # are dropped - only the DETECTION path's reads are evidence of anything.
    resolver.clear_reads()

    return {
        "policy_path": str(policy_path()),
        "policy_exists": policy_path().exists(),
        "groups": groups(),
        "thresholds": rows,
        "problems": problems,
        "presets": [dict(spec, name=name,
                         touches=len(preset_overrides(name)) if
                         spec.get("factor") is not None else 0)
                    for name, spec in PRESETS.items()],
        "preset_excludes": [k.key for k in KNOBS
                            if k.direction != "lower-is-stricter"],
        "counts": {
            "tunable": len(KNOBS),
            "overridden": len(saved),
            "noisy": sum(1 for k in KNOBS if k.noisy),
        },
        "live_immediately": True,
    }


__all__ = [
    "ENV_POLICY_PATH", "KNOWN", "KNOBS", "BY_KEY", "PRESETS",
    "Knob", "groups", "shipped", "preset_overrides", "preset_targets",
    "policy_path", "load", "save", "as_overrides", "apply_to", "summary",
]
