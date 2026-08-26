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
import sys

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
    """Configure the vendored loggers WITHOUT IMPORTING ANY OF THEM.

    That constraint is the whole design, and the first version of this module
    violated it: it called `import transformers` to reach that library's own
    verbosity register, and since the tenet packages call this at import time,
    importing the Security tenet started pulling in transformers, torch and
    numpy. That breaks the Stage-1 promise - 22 stdlib rails usable before
    anyone installs a model - and `test_stage_1_rails_import_nothing_third_party`
    caught it, which is precisely why that test runs in a subprocess.

    So everything here is import-free:

      * `logging.getLogger(name)` creates a logger record without importing the
        package that will later use it, and the level sticks for when it does.
      * `transformers` reads TRANSFORMERS_VERBOSITY and
        HF_HUB_DISABLE_PROGRESS_BARS from the environment during its OWN import,
        so setting them here configures a library that is not loaded yet.
      * structlog is configured only if something else has already imported it.

    `quieten_loaded()` does the rest, after a library is genuinely in memory.
    """
    global _applied
    if _applied and not force:
        return
    _applied = True
    threshold = level()

    for name in _STDLIB_LOGGERS:
        logging.getLogger(name).setLevel(threshold)

    # Read by transformers during its own import. `setdefault` so an operator who
    # set them deliberately keeps their value.
    os.environ.setdefault("TRANSFORMERS_VERBOSITY",
                          logging.getLevelName(threshold).lower())
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    _configure_structlog(threshold, force=force, import_it=False)


def quieten_loaded(force: bool = False) -> None:
    """The part that needs the libraries in memory. Safe to call repeatedly.

    Called from a rail's loader AFTER it has imported its dependency, so nothing
    is imported here that was not already being imported anyway. Splitting it
    this way is what keeps `quieten()` free of third-party imports.
    """
    threshold = level()
    transformers = sys.modules.get("transformers")
    if transformers is not None:
        try:
            transformers.logging.set_verbosity(threshold)
            transformers.logging.disable_progress_bar()
        except Exception:  # noqa: BLE001 - a changed API is not fatal
            pass
    _configure_structlog(threshold, force=force, import_it=True)


def _configure_structlog(threshold: int, *, force: bool, import_it: bool) -> None:
    """llm-guard logs through structlog, which prints EVERYTHING until someone
    configures it - and llm-guard never does; only `llm_guard_api` calls
    `configure_logger`.

    Only ever configures an UNCONFIGURED structlog. A host application that has
    set up its own pipeline keeps it: this module exists because of a library
    that reconfigures its host's logging as a side effect, and becoming that
    library would be a poor joke.
    """
    structlog = sys.modules.get("structlog")
    if structlog is None:
        if not import_it:
            return                      # never import it just to quieten it
        try:
            import structlog  # noqa: PLC0415
        except ImportError:
            return
    try:
        if force or not structlog.is_configured():
            structlog.configure(
                wrapper_class=structlog.make_filtering_bound_logger(threshold))
    except Exception:  # noqa: BLE001
        pass
