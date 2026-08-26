#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run every platform test suite. No arguments, no dependencies beyond stdlib
(the schema-conformance suite skips itself, loudly, if jsonschema is absent).

    python3 rai_platform/run_tests.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def _banner() -> None:
    """Say which build this is, before the output.

    Four rounds of a real bug report turned out to be an unpulled tree - every
    symptom matched a defect already fixed, and nothing in the output said which
    revision produced it. The test COUNT is the tell (747 vs 768), and it lands
    at the bottom under whatever the libraries have logged, so it gets missed.
    Put the provenance at the top instead.
    """
    try:
        from afni_rai.build_info import banner
        print(banner())
    except Exception:  # noqa: BLE001 - a banner must never block a test run
        pass


if __name__ == "__main__":
    _banner()
    suite = unittest.TestLoader().discover(
        start_dir=os.path.join(HERE, "tests"), top_level_dir=HERE, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"\n{result.testsRun} test(s) run.  "
          f"{'PASS' if result.wasSuccessful() else 'FAIL'}")
    _banner()
    sys.exit(0 if result.wasSuccessful() else 1)
