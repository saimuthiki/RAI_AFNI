# -*- coding: utf-8 -*-
"""
Tests for the vendored-library log suppression.

Worth its own file because the failure mode was invisible from a bare machine.
With the Stage-2 models installed, llm-guard logged the full per-label score
vector for every text it scanned, at DEBUG, through an unconfigured structlog -
174 lines of output in which the test summary did not appear.

Two properties are pinned: the vendored loggers are quiet by default, and a host
application's own structlog configuration is left alone. The second matters
because this module exists precisely because of a library that reconfigures its
host's logging as a side effect.

Run: python3 rai_platform/run_tests.py
"""
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai import third_party_logging as tpl  # noqa: E402


class _WithEnv(unittest.TestCase):

    def setUp(self):
        self._saved = os.environ.get(tpl.ENV_VAR)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(tpl.ENV_VAR, None)
        else:
            os.environ[tpl.ENV_VAR] = self._saved


class TestTheDefaultIsQuiet(_WithEnv):

    def test_the_default_level_is_error(self):
        os.environ.pop(tpl.ENV_VAR, None)
        self.assertEqual(tpl.level(), logging.ERROR)

    def test_every_vendored_logger_is_raised_to_the_threshold(self):
        os.environ.pop(tpl.ENV_VAR, None)
        tpl.quieten(force=True)
        for name in tpl._STDLIB_LOGGERS:
            with self.subTest(logger=name):
                self.assertGreaterEqual(logging.getLogger(name).level,
                                        logging.ERROR)

    def test_importing_a_tenet_applies_it(self):
        """The flood starts when a model is CONSTRUCTED, which happens inside the
        first request. Configuring it there would be one request too late, so the
        tenet packages call it at import."""
        import importlib

        for pkg in ("content_safety", "fairness", "hallucination", "security",
                    "privacy"):
            with self.subTest(tenet=pkg):
                importlib.import_module(f"afni_rai.tenets.{pkg}")
        self.assertGreaterEqual(logging.getLogger("llm_guard").level,
                                logging.ERROR)


class TestTheOverride(_WithEnv):

    def test_debug_restores_the_original_behaviour(self):
        os.environ[tpl.ENV_VAR] = "DEBUG"
        self.assertEqual(tpl.level(), logging.DEBUG)

    def test_lowercase_is_accepted(self):
        os.environ[tpl.ENV_VAR] = "warning"
        self.assertEqual(tpl.level(), logging.WARNING)

    def test_an_unparseable_value_falls_back_rather_than_raising(self):
        # A bad log setting must not stop a guardrail from booting.
        for bad in ("nonsense", "", "   ", "12", "TRACE"):
            with self.subTest(value=bad):
                os.environ[tpl.ENV_VAR] = bad
                self.assertEqual(tpl.level(), logging.ERROR)

    def test_the_override_reaches_the_loggers(self):
        os.environ[tpl.ENV_VAR] = "DEBUG"
        tpl.quieten(force=True)
        self.assertEqual(logging.getLogger("llm_guard").level, logging.DEBUG)
        # Put it back so the rest of the suite is not noisy.
        os.environ.pop(tpl.ENV_VAR, None)
        tpl.quieten(force=True)


class TestItDoesNotTrampleTheHost(_WithEnv):

    def test_it_never_touches_the_root_logger(self):
        root = logging.getLogger()
        before_level, before_handlers = root.level, list(root.handlers)
        tpl.quieten(force=True)
        self.assertEqual(root.level, before_level,
                         "the root logger's level was changed")
        self.assertEqual(root.handlers, before_handlers,
                         "a handler was added to or removed from the root logger")

    def test_an_existing_structlog_configuration_is_left_alone(self):
        """A host that has configured structlog keeps its configuration. Only an
        UNCONFIGURED structlog - the state that produces the flood - is touched."""
        try:
            import structlog
        except ImportError:
            self.skipTest("structlog is not installed")

        sentinel = object()
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(
            logging.CRITICAL))
        self.assertTrue(structlog.is_configured())
        configured_before = structlog.get_config()
        # force=False must respect it.
        tpl._applied = False
        tpl.quieten()
        self.assertEqual(structlog.get_config()["wrapper_class"],
                         configured_before["wrapper_class"],
                         "a host structlog configuration was overwritten")
        structlog.reset_defaults()

    def test_quieten_is_idempotent(self):
        tpl._applied = False
        tpl.quieten()
        tpl.quieten()
        tpl.quieten()
        self.assertTrue(tpl._applied)

    def test_it_never_raises_when_a_library_is_absent(self):
        # transformers and structlog are both optional. A missing one must not
        # turn log configuration into a boot failure.
        tpl.quieten(force=True)   # no assertion needed: raising is the failure


if __name__ == "__main__":
    unittest.main(verbosity=2)
