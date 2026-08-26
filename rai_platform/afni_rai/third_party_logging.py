# -*- coding: utf-8 -*-
"""
Quiet the vendored libraries' own stdout logging.

THE PROBLEM, observed rather than anticipated. Running the suite on a machine
with the Stage-2 models installed produced 174 lines of output, of which the test
summary was not one: llm-guard logs the full per-label score vector for every
single text it scans, at DEBUG, through structlog. The operator could not see
their own test results.

`llm_guard/util.py:30 configure_logger` exists but the library never calls it -
only `llm_guard_api` does. So an unconfigured structlog is in play, and
unconfigured structlog prints everything at every level.

WHY THIS IS NOT JUST NOISE. A representative line:

    [debug] Not toxicity found in the text results=[{'label': 'toxicity', ...},
      {'label': 'muslim', ...}, {'label': 'jewish', ...}, {'label': 'black', ...},
      {'label': 'homosexual_gay_or_lesbian', ...}, ...]

That is a 16-dimensional inference about protected characteristics, written to
stdout for every message the gateway sees, by a component of a platform whose
own audit trail deliberately stores no matched text at all. Whatever the merits
of the score itself, an uncontrolled second logging channel emitting it - into
whatever aggregates stdout in a given deployment - is not something a governance
layer should ship by default.

THE DECISION. Default the vendored loggers to ERROR. This platform's own audit
trail is the record of record; it is structured, it is queryable, and it stores
fingerprints rather than content. A duplicate uncontrolled channel adds risk and
no information. `AFNI_THIRD_PARTY_LOG_LEVEL` raises it again for debugging -
DEBUG there restores the original behaviour exactly.

Deliberately does NOT touch the root logger or a structlog configuration the host
application has already installed. A library that reconfigures the host's logging
on import is its own kind of rude, and this module exists because of one that
effectively does.
"""
from __future__ import annotations

import logging
import os

# The vendored libraries that log through the stdlib. `transformers` announces
# device selection and revision resolution on every pipeline construction;
# `presidio` and `spacy` are quieter but talk during model load.
_STDLIB_LOGGERS = (
    "llm_guard",
    "transformers",
    "presidio-analyzer",
    "presidio_analyzer",
    "spacy",
    "urllib3",
    "filelock",
    "huggingface_hub",
)

DEFAULT_LEVEL = "ERROR"
ENV_VAR = "AFNI_THIRD_PARTY_LOG_LEVEL"

_applied = False


def level() -> int:
    """The configured level, defaulting to ERROR. An unparseable value falls back
    rather than raising - a bad log setting must not stop a guardrail booting."""
    name = os.environ.get(ENV_VAR, DEFAULT_LEVEL).strip().upper()
    return getattr(logging, name, logging.ERROR) if name else logging.ERROR


def quieten(force: bool = False) -> None:
    """Apply the level to every vendored logger. Idempotent.

    Called from the two tenet packages that load these libraries, at import time
    rather than at first use - the flood starts with model construction, which
    happens inside the first request, and configuring it there would be one
    request too late.
    """
    global _applied
    if _applied and not force:
        return
    _applied = True
    threshold = level()

    for name in _STDLIB_LOGGERS:
        logging.getLogger(name).setLevel(threshold)

    # transformers keeps its own verbosity register, separate from the stdlib
    # logger it also uses. Setting only the latter leaves the progress bars and
    # the "Device set to use cpu" line in place.
    try:
        import transformers  # noqa: PLC0415

        transformers.logging.set_verbosity(threshold)
        transformers.logging.disable_progress_bar()
    except Exception:  # noqa: BLE001 - absent, or a changed API. Not fatal.
        pass

    # llm-guard logs through structlog, which prints EVERYTHING until someone
    # configures it. Only configure it if nobody has: a host application that
    # has set up its own structlog pipeline must keep it.
    try:
        import structlog  # noqa: PLC0415

        if force or not structlog.is_configured():
            structlog.configure(
                wrapper_class=structlog.make_filtering_bound_logger(threshold))
    except Exception:  # noqa: BLE001
        pass
