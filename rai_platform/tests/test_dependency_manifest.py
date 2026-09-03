# -*- coding: utf-8 -*-
"""Does the dependency manifest actually list what the code imports?

WRITTEN BECAUSE IT DID NOT. On 2026-09-03 `requirements.txt` omitted
`jsonschema`, which `hallucination.structured-output-schema` needs. AFNI
installed from the file into a clean venv and got **six test failures** whose
messages named the rail rather than the package. `preflight` then reported
"PYTHON PACKAGES (11/11 present)" — **a package list that does not include a
required package is worse than no list, because it actively reassures.**

So the manifest is no longer maintained by hand and hoped over. This file walks
every `import` in `afni_rai/` with the AST — lazy imports inside functions
included, which is where four of them live — and asserts each one is either:

  * pinned in `requirements.txt`, or
  * listed in `requirements.txt` as a commented-out OPTIONAL tier, or
  * declared here as TRANSITIVE, with the package that brings it in.

A new third-party import with none of those fails this test, which is the only
way this stays true.
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys
import unittest

_HERE = pathlib.Path(os.path.abspath(__file__)).parent
_PLATFORM = _HERE.parent
_REPO = _PLATFORM.parent
sys.path.insert(0, str(_PLATFORM))

#: import name -> distribution name, where they differ.
DIST_NAME = {
    "cv2": "opencv-python-headless",
    "llm_guard": "llm-guard",
    "presidio_analyzer": "presidio-analyzer",
    "huggingface_hub": "huggingface-hub",
    "opentelemetry": "opentelemetry-api",
}

#: Imports that arrive WITH something already pinned, so pinning them again
#: would be a second version constraint on the same wheel. Each one names its
#: parent, because "it comes in anyway" is a claim that needs a subject.
TRANSITIVE = {
    "pydantic": "fastapi",
    "structlog": "llm-guard",
}

#: Our own top-level modules and the ones the stdlib owns.
LOCAL = {"afni_rai", "corpus", "scripts", "tests", "serve", "build_info"}


def _third_party_imports() -> dict[str, set[str]]:
    """Every non-stdlib, non-local module imported under afni_rai/ (+ serve.py).

    AST rather than grep, because four of these are lazy imports inside a
    function body and a line-based search for `^import` misses them - which is
    exactly how one went unnoticed.
    """
    stdlib = set(sys.stdlib_module_names)
    found: dict[str, set[str]] = {}
    files = sorted((_PLATFORM / "afni_rai").rglob("*.py"))
    files.append(_PLATFORM / "serve.py")
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:          # relative - our own code
                    continue
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if not top or top in stdlib or top in LOCAL:
                    continue
                found.setdefault(top, set()).add(
                    str(path.relative_to(_PLATFORM)))
    return found


def _requirements() -> tuple[set[str], set[str]]:
    """(pinned, optional) distribution names from requirements.txt.

    The optional tier is read from COMMENTED-OUT requirement lines, which is
    how the file expresses "you may want this". Parsing them rather than
    keeping a second list here means the file stays the single source of truth.
    """
    from packaging.requirements import Requirement

    text = (_REPO / "requirements.txt").read_text(encoding="utf-8")
    pinned: set[str] = set()
    optional: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        commented = line.startswith("#")
        candidate = line.lstrip("#").strip() if commented else line
        # A prose comment is not a requirement line. Only try to parse
        # something that looks like `name>=1,<2` or a bare name.
        if not candidate or " " in candidate.split(";")[0].strip():
            continue
        try:
            name = Requirement(candidate).name.lower()
        except Exception:  # noqa: BLE001 - it was prose after all
            continue
        (optional if commented else pinned).add(name)
    return pinned, optional


class TheManifestCoversTheCode(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.imports = _third_party_imports()
        cls.pinned, cls.optional = _requirements()

    def test_requirements_txt_parses_into_something(self):
        self.assertGreaterEqual(len(self.pinned), 10)
        self.assertIn("numpy", self.pinned)

    def test_every_third_party_import_is_accounted_for(self):
        for module, files in sorted(self.imports.items()):
            dist = DIST_NAME.get(module, module).lower()
            with self.subTest(module=module):
                accounted = (dist in self.pinned
                             or dist in self.optional
                             or module in TRANSITIVE)
                self.assertTrue(accounted, (
                    f"{module!r} is imported by {sorted(files)} but is neither "
                    f"pinned in requirements.txt, listed there as an optional "
                    f"tier, nor declared TRANSITIVE in this test. A manifest "
                    f"that omits a required package actively reassures - see "
                    f"this module's docstring."))

    def test_jsonschema_specifically_is_pinned(self):
        # The one that got away. Named explicitly so the regression has a
        # test with its own failure message rather than being one subTest
        # among sixteen.
        self.assertIn("jsonschema", self.imports,
                      "if this rail stopped needing jsonschema, delete this "
                      "test rather than the pin")
        self.assertIn("jsonschema", self.pinned)

    def test_a_transitive_claim_names_its_parent(self):
        for module, parent in TRANSITIVE.items():
            with self.subTest(module=module):
                self.assertIn(parent.lower(), self.pinned,
                              f"{module} is claimed to arrive with {parent}, "
                              f"but {parent} is not pinned - so the claim is "
                              f"that it arrives with nothing")

    def test_the_dist_name_map_has_no_stale_entries(self):
        # A rename left behind is a rename that will mislead the next reader.
        for module in DIST_NAME:
            with self.subTest(module=module):
                self.assertIn(module, self.imports,
                              f"{module} is mapped to a distribution name but "
                              f"nothing imports it any more")


class PreflightReportsTheRequiredOnes(unittest.TestCase):
    """A required package missing from preflight is the failure that started this.

    preflight is the command the setup guide tells you to run to find out what
    is missing. It said 11/11 while six tests failed on a missing package.
    """

    @classmethod
    def setUpClass(cls):
        from afni_rai import preflight
        cls.assets = preflight.collect()
        cls.reported = {a.name for a in cls.assets
                        if a.kind in ("package", "optional")}

    def test_jsonschema_is_reported(self):
        self.assertIn("jsonschema", self.reported)

    def test_every_import_the_platform_makes_is_reported_somewhere(self):
        imports = _third_party_imports()
        # `numpy` and `huggingface_hub` arrive with other pinned packages and
        # are not separately actionable, so they are allowed to be absent from
        # the report; everything else must be findable from one command.
        exempt = {"numpy", "huggingface_hub", "pydantic", "structlog"}
        for module in sorted(imports):
            if module in exempt:
                continue
            with self.subTest(module=module):
                self.assertIn(module, self.reported, (
                    f"{module!r} is imported by the platform but preflight "
                    f"never mentions it, so 'why is this rail unjudged' is not "
                    f"answerable from the one command that is supposed to "
                    f"answer it"))

    def test_the_optional_section_does_not_inflate_the_outstanding_count(self):
        # A deliberate omission is not an outstanding item. If optional
        # packages counted, `preflight`'s exit code would never reach 0 on a
        # perfectly good install.
        for asset in self.assets:
            if asset.kind == "optional":
                with self.subTest(name=asset.name):
                    self.assertTrue(asset.present)
                    # ...but the detail line must still say which it is.
                    self.assertIn("installed", asset.detail)

    def test_preflight_renders_without_raising(self):
        from afni_rai import preflight
        text = preflight.render()
        self.assertIn("PYTHON PACKAGES", text)
        self.assertIn("OPTIONAL PACKAGES", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
