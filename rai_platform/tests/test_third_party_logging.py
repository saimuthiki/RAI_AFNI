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


def pathlib_write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)

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


class TestQuieteningImportsNothing(unittest.TestCase):
    """The constraint that makes this module safe, and the one it broke first.

    `quieten()` is called at TENET IMPORT time, so anything it imports becomes a
    dependency of importing that tenet. The first version reached for
    transformers' own verbosity register with a plain `import transformers` -
    which pulled transformers, torch and numpy into the Stage-1 path and broke
    the promise the whole platform rests on: 22 stdlib rails usable before anyone
    installs a model.

    Two existing per-tenet tests caught it. This covers all seven at once, in one
    subprocess, because the property is about the module boundary rather than any
    one tenet - and because the next thing added to `quieten()` will be tempted
    to import something too.
    """

    HEAVY = ("torch", "transformers", "llm_guard", "numpy", "scipy", "requests",
             "urllib3", "httpx", "structlog", "presidio_analyzer", "spacy",
             "huggingface_hub", "onnxruntime")

    def _imported_after(self, statement):
        """Run `statement` in a fresh interpreter; report which heavy modules it
        pulled in.

        Every heavy name is first made IMPORTABLE as a one-line stub on the
        subprocess's path. Without that, this test only works on a machine where
        the real libraries happen to be installed: an accidental
        `import transformers` on a bare box raises ImportError, gets swallowed by
        the surrounding try/except, and the test passes while the bug is present.

        Which is not hypothetical - it is exactly what happened when this test
        was first written. The regression it exists to catch was reported from a
        provisioned Windows machine and could not be reproduced here at all.
        Stubbing makes the check mean the same thing everywhere.
        """
        import subprocess
        import tempfile

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as stubs:
            for name in self.HEAVY:
                # Enough of a module to import successfully and to satisfy the
                # attribute access an accidental caller would attempt.
                pathlib_write(os.path.join(stubs, f"{name}.py"),
                              "class _Any:\n"
                              "    def __getattr__(self, n): return _Any()\n"
                              "    def __call__(self, *a, **k): return _Any()\n"
                              "def __getattr__(name): return _Any()\n"
                              "logging = _Any()\n")
            code = (
                f"import sys; sys.path.insert(0, {stubs!r}); "
                f"sys.path.insert(0, {root!r}); {statement}; "
                f"heavy = {self.HEAVY!r}; "
                "print(','.join(sorted(m for m in sys.modules "
                "if m.split('.')[0] in heavy)) or 'CLEAN')"
            )
            proc = subprocess.run([sys.executable, "-c", code],
                                  capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_quieten_on_its_own_imports_nothing_heavy(self):
        self.assertEqual(
            self._imported_after(
                "from afni_rai.third_party_logging import quieten; quieten()"),
            "CLEAN")

    def test_importing_every_tenet_imports_nothing_heavy(self):
        statement = "; ".join(
            f"import afni_rai.tenets.{pkg}" for pkg in
            ("privacy", "security", "fairness", "explainability",
             "content_safety", "hallucination", "accountability"))
        self.assertEqual(self._imported_after(statement), "CLEAN")

    def test_the_cli_loads_every_rail_without_a_heavy_import(self):
        # The real entry point, not just the packages: `load_tenets` is what the
        # CLI and the gateway both call.
        self.assertEqual(
            self._imported_after(
                "from afni_rai.cli import load_tenets; load_tenets()"),
            "CLEAN")

    def test_transformers_verbosity_is_set_by_environment_not_by_import(self):
        """The mechanism that replaced the import. transformers reads these
        during its OWN import, so they configure a library that is not loaded."""
        saved = {k: os.environ.pop(k, None) for k in
                 ("TRANSFORMERS_VERBOSITY", "HF_HUB_DISABLE_PROGRESS_BARS")}
        try:
            tpl.quieten(force=True)
            self.assertEqual(os.environ.get("TRANSFORMERS_VERBOSITY"), "error")
            self.assertEqual(os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS"), "1")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_a_deliberate_operator_setting_is_not_overwritten(self):
        os.environ["TRANSFORMERS_VERBOSITY"] = "debug"
        try:
            tpl.quieten(force=True)
            self.assertEqual(os.environ["TRANSFORMERS_VERBOSITY"], "debug",
                             "an explicit operator setting was overwritten")
        finally:
            os.environ.pop("TRANSFORMERS_VERBOSITY", None)


class TestNoTenetEmitsASyntaxWarning(unittest.TestCase):
    """`privacy/__init__.py` quoted regexes containing `\\d` in a plain
    docstring, so every single run opened with an invalid-escape SyntaxWarning.
    Harmless, and exactly the kind of standing noise that trains people to skim
    past warnings that matter."""

    def test_importing_every_tenet_is_warning_free(self):
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        statement = "; ".join(
            f"import afni_rai.tenets.{pkg}" for pkg in
            ("privacy", "security", "fairness", "explainability",
             "content_safety", "hallucination", "accountability"))
        code = f"import sys; sys.path.insert(0, {root!r}); {statement}; print('OK')"
        proc = subprocess.run(
            [sys.executable, "-W", "error::SyntaxWarning", "-c", code],
            capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0,
                         f"a tenet raised a SyntaxWarning:\n{proc.stderr}")


class TestNoTestAssertsAgainstThisProcessSysModules(unittest.TestCase):
    """A lint, earned by three separate occurrences of the same mistake.

    "Importing X must not pull in Y" is a real and valuable property. Asserting
    it as `assertNotIn("Y", sys.modules)` inside the test process is not a test
    of it: `sys.modules` there reflects the ENTIRE run, so the assertion passes
    or fails on module ORDER and on which optional packages the machine happens
    to have. Green on a bare box, red on a provisioned one - backwards, and
    invisible from the bare box where it gets written.

    That cost four round trips across three files (test_security, test_privacy,
    test_accountability) before it read as a pattern rather than three
    coincidences. The correct form is a subprocess with the banned modules
    stubbed importable; several tests in this file show it.

    Uses the AST rather than a regex, for two reasons found the hard way: a
    regex matched this file's own prose about the anti-pattern, and it missed
    `assertNotIn(banned, sys.modules, "message")` because the argument list did
    not end at the second argument. The AST sees calls, not text, so neither
    happens.
    """

    def _offenders(self):
        import ast

        tests_dir = os.path.dirname(os.path.abspath(__file__))
        found = []
        for name in sorted(os.listdir(tests_dir)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            path = os.path.join(tests_dir, name)
            source = open(path, encoding="utf-8").read()
            for node in ast.walk(ast.parse(source, filename=name)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr not in ("assertIn", "assertNotIn"):
                    continue
                if len(node.args) < 2:
                    continue
                if self._is_sys_modules(node.args[1]):
                    found.append(f"{name}:{node.lineno}")
        return found

    @staticmethod
    def _is_sys_modules(node):
        import ast

        return (isinstance(node, ast.Attribute) and node.attr == "modules"
                and isinstance(node.value, ast.Name) and node.value.id == "sys")

    def test_no_test_file_checks_sys_modules_in_process(self):
        offenders = self._offenders()
        self.assertEqual(
            offenders, [],
            "these assertions read THIS process's sys.modules, so they depend on "
            "test order and on what is installed. Run the import in a subprocess "
            "with the banned modules stubbed instead. Offenders: "
            + ", ".join(offenders))

    def test_the_lint_detects_the_shape_it_bans(self):
        """A lint that matches nothing is worse than none - it reads as a
        guarantee. So prove the detector fires on every real form, including the
        three-argument one a regex missed."""
        import ast

        for snippet in (
            'self.assertNotIn("opentelemetry", sys.modules)',
            "self.assertNotIn('presidio_analyzer', sys.modules)",
            'self.assertNotIn(banned, sys.modules, "a message")',
            'self.assertIn("torch", sys.modules)',
        ):
            with self.subTest(snippet=snippet):
                call = ast.parse(snippet).body[0].value
                self.assertIn(call.func.attr, ("assertIn", "assertNotIn"))
                self.assertTrue(self._is_sys_modules(call.args[1]),
                                "the detector missed a real case")

    def test_the_lint_ignores_the_correct_form(self):
        import ast

        for snippet in (
            'self.assertEqual(proc.stdout.strip(), "CLEAN")',
            'self.assertNotIn("torch", result.stdout)',
            'self.assertIn("torch", sorted(other.modules))',
        ):
            with self.subTest(snippet=snippet):
                call = ast.parse(snippet).body[0].value
                if call.func.attr not in ("assertIn", "assertNotIn"):
                    continue
                self.assertFalse(self._is_sys_modules(call.args[1]),
                                 "the detector fired on a correct check")


if __name__ == "__main__":
    unittest.main(verbosity=2)
