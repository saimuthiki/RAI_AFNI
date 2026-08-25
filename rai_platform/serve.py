#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Launcher for the AFNI Responsible AI gateway.

    python3 rai_platform/serve.py
    python3 rai_platform/serve.py --host 0.0.0.0 --port 9000 --log-level debug
    python3 rai_platform/serve.py --reload            # local development only

Deliberately thin. Everything that decides anything lives in
`afni_rai/gateway/app.py`; this file exists to put `rai_platform` on `sys.path`,
configure logging once, and hand uvicorn an app. If a change to how the gateway
behaves needs an edit here, it is in the wrong place.

Logging is configured with a plain stdlib format and nothing else: this platform
must never print a matched value, and `logging` is the only writer - there is no
`print` anywhere in the gateway. `AFNI_REVEAL_SUBJECT` is the single switch that
allows a matched value into an explanation, it is off unless a server operator
sets it, and no request can turn it on.

Configuration, all server-side:

    AFNI_REVEAL_SUBJECT   off (default) | 1 - echo matched values in explanations
    AFNI_AUDIT_DB         :memory: (default) | a path for the durable evidence pack
    AFNI_JUDGE_PROVIDER   none (default) | openai | gemini | local
    AFNI_JUDGE_TIMEOUT    seconds, default 10.0
    AFNI_HOST/AFNI_PORT   defaults 127.0.0.1 / 8000 - loopback, not 0.0.0.0,
                          because this endpoint sees every prompt in the estate
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    # `afni_rai.registry.phases.status()` imports `afni_rai.tenets.*` by absolute
    # name, so the package has to be importable as a top-level name whichever
    # directory the process was started from.
    sys.path.insert(0, HERE)

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"


def build_app():
    """The uvicorn app factory. Imported late so `--help` needs no FastAPI."""
    from afni_rai.gateway.app import create_app

    return create_app()


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="afni-rai-serve", description="Serve the AFNI Responsible AI gateway")
    parser.add_argument("--host", default=os.environ.get("AFNI_HOST", "127.0.0.1"),
                        help="default 127.0.0.1 - binding 0.0.0.0 exposes every "
                             "prompt this gateway sees, so it must be deliberate")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("AFNI_PORT", "8000")))
    parser.add_argument("--log-level", default=os.environ.get("AFNI_LOG_LEVEL", "info"),
                        choices=("critical", "error", "warning", "info", "debug"))
    parser.add_argument("--reload", action="store_true",
                        help="uvicorn autoreload - development only")
    parser.add_argument("--workers", type=int, default=1,
                        help="each worker holds its own audit store; a file-backed "
                             "AFNI_AUDIT_DB is shared, :memory: is not")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        format=LOG_FORMAT)
    log = logging.getLogger("afni_rai.serve")

    try:
        import uvicorn
    except ImportError:
        log.error("uvicorn is not installed: pip install uvicorn fastapi")
        return 1

    log.info("AFNI Responsible AI gateway on http://%s:%d  (docs at /docs)",
             args.host, args.port)
    if args.workers > 1 and (os.environ.get("AFNI_AUDIT_DB") or ":memory:") == ":memory:":
        log.warning("--workers %d with an in-memory audit store: each worker keeps "
                    "its own records and none of them survive a restart. Set "
                    "AFNI_AUDIT_DB to a path for the evidence pack.", args.workers)

    # `--reload` and `--workers` both need an import string rather than an app
    # object, so the factory is always passed by name.
    uvicorn.run("serve:build_app", factory=True, host=args.host, port=args.port,
                log_level=args.log_level, reload=args.reload,
                workers=args.workers if args.workers > 1 else None,
                app_dir=HERE)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
