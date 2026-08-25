#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin launcher so the CLI runs without installing the package.

    python3 rai_platform/cli.py check "some text"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from afni_rai.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
