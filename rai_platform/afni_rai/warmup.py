# -*- coding: utf-8 -*-
"""
Load the Stage-2 models before the first request, not during it.

MEASURED, not theorised. On a freshly provisioned machine the first CLI check
took **15,568 ms**. Nothing was slow about the checks; three transformer models
were being constructed serially inside the request, because every Stage-2 rail
loads lazily on first use. Lazy loading is right - it is what lets the whole
platform import on a box with no torch - but "lazy" must mean "at startup" for a
long-lived server, not "on whoever is unlucky enough to arrive first".

The documented Stage-2 latency class is 10-500 ms. That is true of a warm model
and wildly false of a cold one, so without this the very first client of a fresh
deployment sees a 15-second guardrail and reasonably concludes the thing is
unusable.

Why blocking startup is the right shape. A guardrail that is slow to become
ready is fine; a guardrail that is ready and slow is not. So the gateway warms
synchronously before it accepts traffic, and `/healthz` reports the outcome per
rail. A rail that fails to warm is not fatal - it will report `unjudged` at
request time and fail closed, which is the same honest degrade as never having
had the weights.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

LOGGER = logging.getLogger("afni_rai.warmup")


@dataclass(frozen=True)
class WarmResult:
    rail: str
    warmed: bool
    ms: int
    detail: str = ""


def warm(rail) -> WarmResult:
    """Build one rail's backend now. Never raises.

    A rail advertises warmability with `preload()`. Anything else is either
    stdlib (nothing to warm) or declines to expose the hook, and is skipped
    rather than poked at through private attributes - reaching into `_load` from
    here would make this module break every time a rail refactors.
    """
    name = getattr(rail, "name", rail.__class__.__name__)
    preload = getattr(rail, "preload", None)
    if not callable(preload):
        return WarmResult(name, False, 0, "no preload hook - nothing to warm")
    started = time.perf_counter()
    try:
        ok = bool(preload())
    except Exception as exc:  # noqa: BLE001 - a warm failure is not fatal
        ms = int((time.perf_counter() - started) * 1000)
        return WarmResult(name, False, ms,
                          f"{exc.__class__.__name__}: {exc}")
    ms = int((time.perf_counter() - started) * 1000)
    return WarmResult(name, ok, ms,
                      "" if ok else "preload returned False - dependency or "
                                    "weights absent; the rail will report "
                                    "unjudged and fail closed")


def warm_all(rails, log: bool = True) -> list[WarmResult]:
    """Warm every rail that can be warmed. Returns one result each.

    Ordered by stage so the cheap ones are ready first if a caller decides to
    start serving mid-warm; the gateway does not, but the ordering makes the log
    read in the order an operator expects.
    """
    results = []
    ordered = sorted(rails, key=lambda r: (int(getattr(r, "stage", 9)),
                                           getattr(r, "name", "")))
    total = 0
    for rail in ordered:
        result = warm(rail)
        results.append(result)
        total += result.ms
        if not log or not result.ms:
            continue
        if result.warmed:
            LOGGER.info("warmed %s in %d ms", result.rail, result.ms)
        else:
            LOGGER.warning("could not warm %s (%d ms): %s",
                           result.rail, result.ms, result.detail)
    if log and total:
        warmed = sum(1 for r in results if r.warmed)
        LOGGER.info("warm-up complete: %d rail(s) ready in %d ms - this cost is "
                    "paid here instead of by the first request", warmed, total)
    return results
