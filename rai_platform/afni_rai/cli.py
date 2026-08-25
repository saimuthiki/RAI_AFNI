# -*- coding: utf-8 -*-
"""
Command line entry point. The fastest way to see the gateway decide something.

    python3 rai_platform/cli.py check "ignore all previous instructions"
    python3 rai_platform/cli.py check --internal "my ssn is 123-45-6789"
    python3 rai_platform/cli.py check --json "..." | jq .
    python3 rai_platform/cli.py coverage
    python3 rai_platform/cli.py rails
    python3 rai_platform/cli.py preflight

`check` mounts every request-path rail from every tenet, runs the cascade, and
prints the attribution: which repo made the call, how confident, which entity,
and where. `--reveal` shows the matched value; it is off by default because the
matched value is the SSN or the API key, and printing it into a terminal
scrollback or a CI log defeats the guardrail that caught it.

Exit codes are meant for scripting: 0 allowed, 1 blocked, 2 allowed but with an
unjudged path (something could not be looked at).
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys

from .cascade.engine import Cascade
from .cascade.rail import Stage
from .contract.explanation import explain
from .contract.models import Decision, EventKind, GuardEvent, LLMProtocol
from .registry.capabilities import CapabilityRegistry

TENET_PACKAGES = ("privacy", "security", "fairness", "explainability",
                  "content_safety", "hallucination", "accountability")


def load_tenets():
    """Import whatever tenet packages are present and collect their rails.

    A package that is absent or does not yet export the expected names is
    reported, not skipped silently - a missing tenet means missing protection,
    and that has to be visible rather than inferred from a short rail list.
    """
    rails, attributions, problems = [], {}, []
    for pkg in TENET_PACKAGES:
        try:
            mod = importlib.import_module(f"{__package__}.tenets.{pkg}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{pkg}: import failed ({type(exc).__name__}: {exc})")
            continue
        pkg_rails = getattr(mod, "RAILS", None)
        if pkg_rails is None:
            problems.append(f"{pkg}: no RAILS exported")
            continue
        rails.extend(pkg_rails)
        attributions.update(getattr(mod, "ATTRIBUTIONS", {}) or {})
    return rails, attributions, problems


def build_event(text: str, client_facing: bool, as_response: bool) -> GuardEvent:
    if as_response:
        payload = {"choices": [{"message": {"role": "assistant", "content": text}}]}
        kind = EventKind.RESPONSE
    else:
        payload = {"messages": [{"role": "user", "content": text}]}
        kind = EventKind.REQUEST
    return GuardEvent(
        kind=kind, step_id="cli-1", agent_id="cli", agent_type="cli",
        agent_workspace="afni", agent_user="cli",
        llm_protocol=LLMProtocol.OPENAI_CHAT, payload=payload,
        client_facing=client_facing,
    )


def cmd_check(args) -> int:
    rails, attributions, problems = load_tenets()
    mounted = [r for r in rails if r.stage is not Stage.OFFLINE]
    cascade = Cascade(mounted)
    outcome = cascade.evaluate(build_event(args.text, not args.internal, args.response))
    exp = explain(outcome.verdict, attributions, stages_run=outcome.stages_run)

    if args.json:
        print(json.dumps({"verdict": outcome.verdict.to_dict(),
                          "explanation": exp.to_dict(reveal_subject=args.reveal),
                          "rails_mounted": len(mounted),
                          "problems": problems}, indent=2))
    else:
        if problems:
            print("! tenets not loaded: " + "; ".join(problems), file=sys.stderr)
        print(exp.summary(reveal_subject=args.reveal))
        skipped = outcome.stages_skipped
        if skipped:
            print(f"  ({skipped} stage(s) never ran - that is the saving)")

    if outcome.verdict.decision is Decision.BLOCK:
        return 1
    return 2 if outcome.verdict.could_not_judge else 0


def cmd_coverage(args) -> int:
    registry = CapabilityRegistry()
    problems = []
    for pkg in TENET_PACKAGES:
        try:
            mod = importlib.import_module(f"{__package__}.tenets.{pkg}")
            mod.register(registry)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{pkg}: {type(exc).__name__}: {exc}")
    print(registry.report().render())
    if problems:
        print("\nNot registered (so counted as gaps above):")
        for p in problems:
            print(f"  {p}")
    return 0


def cmd_rails(args) -> int:
    rails, attributions, problems = load_tenets()
    by_stage: dict[int, list] = {}
    for rail in rails:
        by_stage.setdefault(int(rail.stage), []).append(rail)
    label = {1: "STAGE 1  free, deterministic, every request",
             2: "STAGE 2  local model or cloud second opinion",
             3: "STAGE 3  paid API or LLM judge",
             4: "OFFLINE  CI and red-team only - never mounted inline"}
    for stage in sorted(by_stage):
        print(f"\n{label[stage]}")
        for rail in sorted(by_stage[stage], key=lambda r: r.name):
            attr = attributions.get(rail.name)
            src = f"  <- {attr.source_repo}" if attr else ""
            print(f"  {rail.tenet.value:30s} {rail.name}{src}")
    print(f"\n{len(rails)} rail(s) total, "
          f"{sum(1 for r in rails if r.stage is not Stage.OFFLINE)} mountable.")
    if problems:
        print("Not loaded: " + "; ".join(problems))
    return 0


def cmd_preflight(args) -> int:
    """Every asset the platform needs but does not ship.

    Exit code is the count of outstanding items, capped at 100, so a
    provisioning script can gate on it.
    """
    from .preflight import collect, render
    print(render())
    outstanding = sum(1 for a in collect() if not a.present)
    return min(outstanding, 100)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="afni-rai", description="AFNI Responsible AI gateway")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="run one text through the cascade")
    c.add_argument("text")
    c.add_argument("--internal", action="store_true",
                   help="treat as internal traffic (fails open on unjudged, still reports)")
    c.add_argument("--response", action="store_true",
                   help="judge as a model response rather than a user prompt")
    c.add_argument("--reveal", action="store_true",
                   help="show matched values - off by default so a caught secret "
                        "is not printed into a log")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_check)

    sub.add_parser("coverage", help="capability coverage report").set_defaults(
        func=cmd_coverage)
    sub.add_parser("rails", help="list every rail by cascade stage").set_defaults(
        func=cmd_rails)
    sub.add_parser("preflight", help="what is missing, where it goes, where to "
                                     "get it").set_defaults(func=cmd_preflight)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
