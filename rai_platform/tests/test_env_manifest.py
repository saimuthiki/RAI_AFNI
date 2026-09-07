# -*- coding: utf-8 -*-
"""Is every environment variable the code reads actually DOCUMENTED?

WRITTEN AFTER A CONFIGURATION FILE WAS FILLED IN AND STILL DID NOT WORK. AFNI's
local endpoint requires a key. The judge chain reads `LOCAL_API_KEYS` /
`LOCAL_API_KEY` for exactly that - and `.env.example`, the file whose entire job
is to be the list of things to fill in, did not mention either. So the only way
to discover the variable was to read `providers.py`, and the symptom until you
did was a 401 that looked like a platform fault.

`AZURE_CONTENT_SAFETY_ENDPOINT` and `AZURE_CONTENT_SAFETY_KEY` were the same
story, on the rail whose console line reads `security.prompt_shields:
configured() is False` - a rail reported as unconfigured with no documented way
to configure it.

This is the same failure as `requirements.txt` omitting `jsonschema` while
preflight said `11/11 present`: a manifest that is maintained by hand drifts from
the code silently, and the drift is only visible to whoever is holding the
manifest. So the manifest is checked against the code instead.

HOW THE READS ARE FOUND. By AST, not grep. `grep` for the name pattern finds
`AFNI_DEFAULT` (a `FailMode` constant) and `LOCAL_BIAS_CLASSIFIER_RAIL` (a rail
instance) and would have to be silenced with an ignore list that then needs its
own maintenance. Two shapes are matched instead, which is how this platform
actually reads configuration:

    os.environ.get("NAME") / env.get("NAME") / os.environ["NAME"]
    ENV_SOMETHING = "NAME"        (module or class constant, used indirectly)

A variable may be documented COMMENTED OUT (`# NAME=`). That is deliberate: a
rarely-used knob should not add an active line to everybody's configuration, but
it still has to be findable by searching the file for its name.
"""
from __future__ import annotations

import ast
import pathlib
import re
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "rai_platform"
_EXAMPLE = _ROOT / ".env.example"

#: The variables this platform owns or consumes. Anything else a dependency
#: reads on its own (`PATH`, `HOME`, `HTTPS_PROXY`) is not this file's business.
_PREFIXES = ("AFNI_", "OPENAI_", "GOOGLE_", "LOCAL_", "AZURE_", "HF_",
             "TRANSFORMERS_")

#: Read by a THIRD-PARTY library during its own import, and set here with
#: `setdefault` so an operator's value wins. Not this platform's variables, and
#: documenting them as configuration would imply this code reads them.
_UPSTREAM = {"TRANSFORMERS_VERBOSITY", "HF_HUB_DISABLE_PROGRESS_BARS"}


class _Reads(ast.NodeVisitor):
    """Every string literal used as an environment variable name."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def _keep(self, value: object) -> None:
        if isinstance(value, str) and value.startswith(_PREFIXES):
            self.names.add(value)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("get", "setdefault"):
            base = ast.unparse(func.value)
            if "environ" in base or base == "env" or base.endswith(".env"):
                if node.args and isinstance(node.args[0], ast.Constant):
                    self._keep(node.args[0].value)
        # A HELPER THAT IS HANDED THE ENVIRONMENT. `_keys(env, "OPENAI_API_KEYS",
        # "OPENAI_API_KEY")` reads two variables and never touches `.get` in this
        # function, so a rule that only matched `.get` missed the platform's most
        # important credential - which is precisely the drift being tested for.
        # The rule generalises: a call that receives the environment AND a string
        # literal is reading that name out of it.
        if any(ast.unparse(arg) in ("env", "os.environ", "dict(os.environ)")
               for arg in node.args):
            for arg in node.args:
                if isinstance(arg, ast.Constant):
                    self._keep(arg.value)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: N802
        base = ast.unparse(node.value)
        if "environ" in base and isinstance(node.slice, ast.Constant):
            self._keep(node.slice.value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        # `ENV_KEY = "AZURE_CONTENT_SAFETY_KEY"` - the name reaches os.environ
        # through the constant, so the literal is the only place to catch it.
        if isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and (
                        target.id.startswith("ENV_") or target.id.endswith("_ENV")):
                    self._keep(node.value.value)
        self.generic_visit(node)


def _sources() -> list[pathlib.Path]:
    return [p for p in sorted(_PACKAGE.rglob("*.py"))
            if "tests" not in p.parts and "references" not in p.parts]


def _read_by_code() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in _sources():
        visitor = _Reads()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        for name in visitor.names:
            out.setdefault(name, []).append(
                str(path.relative_to(_ROOT)))
    return out


def _documented() -> set[str]:
    """Names declared in `.env.example`, active or commented out."""
    text = _EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", text, re.M))


class TheExampleFileIsComplete(unittest.TestCase):

    def test_the_audit_finds_something(self):
        # A visitor bug that matched nothing would make the test below pass for
        # the wrong reason - the same trap `test_dependency_manifest` guards.
        found = _read_by_code()
        self.assertGreater(len(found), 20, found)
        for expected in ("AFNI_TARGET_BASE_URL", "OPENAI_API_KEYS",
                         "LOCAL_API_KEYS", "AZURE_CONTENT_SAFETY_KEY"):
            self.assertIn(expected, found)

    def test_it_does_not_pick_up_python_constants(self):
        """`AFNI_DEFAULT` is a FailMode and `LOCAL_BIAS_CLASSIFIER_RAIL` is a
        rail instance. A grep-based audit reported both as configuration."""
        found = _read_by_code()
        self.assertNotIn("AFNI_DEFAULT", found)
        self.assertNotIn("LOCAL_BIAS_CLASSIFIER_RAIL", found)

    def test_every_variable_the_code_reads_is_in_the_example(self):
        found = _read_by_code()
        documented = _documented()
        missing = {name: files for name, files in found.items()
                   if name not in documented and name not in _UPSTREAM}
        if missing:
            lines = "\n".join(f"  {name:34s} read in {files[0]}"
                              for name, files in sorted(missing.items()))
            self.fail(
                f"{len(missing)} environment variable(s) are read by the code "
                f"and absent from .env.example - so the only way to find them "
                f"is to read the source:\n{lines}")

    def test_the_upstream_exemptions_are_still_upstream(self):
        """The exemption list must not become a place to hide this platform's
        own variables. Anything on it has to be set with `setdefault`, not read
        as configuration."""
        blob = "\n".join(p.read_text(encoding="utf-8") for p in _sources())
        for name in _UPSTREAM:
            with self.subTest(name=name):
                self.assertIn(f'setdefault("{name}"', blob)

    def test_no_documented_variable_carries_a_real_credential(self):
        """`.env.example` IS COMMITTED. A key here is a key in every clone.

        Length is the check, because shape is not: a real OpenAI key is ~164
        characters and a real AI Studio key is 39, while every legitimate value
        in this file is a URL, a number, a path or a boolean.
        """
        text = _EXAMPLE.read_text(encoding="utf-8")
        for line in text.splitlines():
            match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
            if not match:
                continue
            name, value = match.group(1), match.group(2).strip()
            with self.subTest(name=name):
                if "KEY" in name or "TOKEN" in name or "SECRET" in name:
                    self.assertEqual(
                        value, "",
                        f"{name} has a value in a COMMITTED file - if it is a "
                        f"real credential, rotate it now and clean history "
                        f"second")
                self.assertFalse(
                    value.startswith(("sk-", "AIza", "AQ.", "ya29.")),
                    f"{name} looks like a live credential")


class TheExampleFileParsesTheWayTheLoaderReadsIt(unittest.TestCase):
    """`serve.load_dotenv` is twenty lines of stdlib, and its rules are not
    python-dotenv's. Anything in the example file that those rules would
    misread is a trap for whoever copies it to `.env`."""

    def test_no_value_carries_a_trailing_comment(self):
        # The loader takes everything after `=` as the value. `AFNI_PORT=8000
        # # the port` would set the port to "8000  # the port" and fail to parse
        # as an int, so comments live on their own line.
        for line in _EXAMPLE.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
            if match and match.group(2).strip():
                with self.subTest(name=match.group(1)):
                    self.assertNotIn(" #", match.group(2))

    def test_every_active_line_is_a_name_equals_value(self):
        for number, line in enumerate(
                _EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            with self.subTest(line=number):
                self.assertRegex(stripped, r"^[A-Z][A-Z0-9_]*=")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
