# -*- coding: utf-8 -*-
"""Does the console's JavaScript actually PARSE?

WRITTEN AFTER SHIPPING A BLANK PAGE. On 2026-09-03 a scripted edit to an
`import { ... }` list produced `STAGES,, judgeChain` — a double comma. Every
Python test still passed, `preflight` was clean, the gateway served the file
with a 200 and the correct `no-cache` header, and the console rendered
**nothing at all**, because one `SyntaxError` in a module aborts the whole
graph.

That is a gap no Python test can see and no HTTP test can see: the server's job
is to hand over bytes, and it did. Only a JavaScript parser has an opinion. So
one runs here, over every file the console ships.

It is a PARSE check, not a lint and not a runtime check — it catches exactly the
class of failure that turns the console into a white screen, and it needs no
browser and no network. The browser-level checks stay a manual step; this is the
floor under them.

Skipped, not failed, when node is unavailable: a Python-only machine can still
run the suite, and a skip that says why is honest where a false pass is not.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import unittest

_WEB = pathlib.Path(os.path.abspath(__file__)).parents[1] / "web"

#: `node --experimental-vm-modules` and `SourceTextModule` parse an ES module
#: WITHOUT executing it or resolving its imports - so a file importing
#: `../api.js` is checked on its own, with no module resolution and no DOM.
_PARSER = r"""
const { SourceTextModule } = require('vm');
const fs = require('fs');
// The file list arrives in an ENVIRONMENT VARIABLE, not in argv. With
// `node -e SCRIPT -- arg`, process.argv has no script path, so the index of
// the first user argument depends on how node consumed `--` - and getting it
// wrong makes the harness crash rather than report, which is how a check
// silently stops checking. An env var has one unambiguous name.
const files = JSON.parse(process.env.AFNI_JS_FILES);
const failures = [];
for (const file of files) {
  try {
    new SourceTextModule(fs.readFileSync(file, 'utf8'), { identifier: file });
  } catch (err) {
    failures.push({ file, error: err.message });
  }
}
process.stdout.write(JSON.stringify(failures));
"""


def _node() -> str | None:
    return shutil.which("node")


def _modules() -> list[pathlib.Path]:
    return sorted(_WEB.rglob("*.js"))


class TheConsoleParses(unittest.TestCase):

    def test_there_are_modules_to_check(self):
        # A globbing bug that finds nothing would make every test below pass
        # for the wrong reason.
        modules = _modules()
        self.assertGreaterEqual(len(modules), 8)
        names = {m.name for m in modules}
        for required in ("app.js", "api.js", "ui.js"):
            self.assertIn(required, names)

    @unittest.skipUnless(_node(), "node is not installed")
    def test_every_module_parses(self):
        modules = _modules()
        result = subprocess.run(
            [_node(), "--experimental-vm-modules", "-e", _PARSER],
            capture_output=True, text=True, timeout=120,
            env={**os.environ,
                 "AFNI_JS_FILES": json.dumps([str(m) for m in modules])})
        self.assertEqual(result.returncode, 0,
                         f"the parser itself failed: {result.stderr[-800:]}")
        failures = json.loads(result.stdout or "[]")
        if failures:
            lines = "\n".join(
                f"  {pathlib.Path(f['file']).relative_to(_WEB)}: {f['error']}"
                for f in failures)
            self.fail(
                f"{len(failures)} console module(s) do not parse. One "
                f"SyntaxError blanks the entire console while every other "
                f"check stays green:\n{lines}")

    @unittest.skipUnless(_node(), "node is not installed")
    def test_a_deliberate_syntax_error_is_caught(self):
        # Proves the check bites. A parser harness that silently passes
        # everything is worse than no harness.
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as handle:
            handle.write("import { a,, b } from './x.js';\n")
            broken = handle.name
        try:
            result = subprocess.run(
                [_node(), "--experimental-vm-modules", "-e", _PARSER],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "AFNI_JS_FILES": json.dumps([broken])})
            failures = json.loads(result.stdout or "[]")
            self.assertEqual(len(failures), 1,
                             "the harness did not notice a double comma - "
                             "which is the exact error it was written for")
        finally:
            os.unlink(broken)

    def test_every_view_is_reachable_from_app_js(self):
        # A view file nobody imports is a screen nobody can open, and it will
        # not be syntax-checked by a browser either. Cheap to catch here.
        app = (_WEB / "app.js").read_text(encoding="utf-8")
        for view in sorted((_WEB / "views").glob("*.js")):
            with self.subTest(view=view.name):
                stem = view.stem
                imported_directly = f"./views/{view.name}" in app
                # Some views are sections of another view rather than routes -
                # beforeafter.js is mounted by corpus.js, governance.js by
                # tenets.js. Those are legitimate, so the check is "somebody
                # imports it", not "app.js does".
                imported_by_sibling = any(
                    view.name in other.read_text(encoding="utf-8")
                    for other in (_WEB / "views").glob("*.js")
                    if other != view)
                self.assertTrue(
                    imported_directly or imported_by_sibling,
                    f"views/{view.name} is imported by nothing - it is either "
                    f"dead code or a screen that cannot be opened")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
