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

if __name__ == "__main__":
    suite = unittest.TestLoader().discover(
        start_dir=os.path.join(HERE, "tests"), top_level_dir=HERE, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
