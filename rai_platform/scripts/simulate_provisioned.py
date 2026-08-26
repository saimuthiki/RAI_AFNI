# -*- coding: utf-8 -*-
"""
Run the suite as if the Stage-2 models and libraries were installed.

    python rai_platform/scripts/simulate_provisioned.py

Why this exists. The platform has two legitimate configurations - bare (Stage 1
only, stdlib) and provisioned (Stage 2 live) - and a test can pass in one and
fail in the other. Nine did: they asserted the BARE state as gospel, so
installing the models, which is the documented next step, turned the suite red on
a correctly-provisioned machine while it stayed green on a bare one. The wrong way
round, and invisible from a bare box.

This stubs `transformers`, `torch`, `llm_guard` and the model folders so the
availability branches take the provisioned path, then runs everything. It is NOT
a substitute for running on a real machine - the stubs answer plausibly, they do
not classify anything - but any test that fails here fails there for the same
reason, and it catches the whole class in under a second instead of two minutes
plus a 3.8 GB download.

The stub shapes deliberately mirror the real call sites (`model(**pair)["logits"][0]`
then `torch.softmax(...).tolist()`), because a stub that is merely close produces
failures that look like product bugs and are not.

Run BOTH before pushing a change to any Stage-2 rail or coverage registration:

    python rai_platform/run_tests.py                        # bare
    python rai_platform/scripts/simulate_provisioned.py     # provisioned
"""
import importlib.machinery
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Make the drop-in folders real, so `_weights_reachable` answers the way it does
# on a provisioned machine. Without this the availability probes say False while
# the stubbed libraries say True - a state that cannot occur for real, and which
# made two tests look broken when they were not.
import os
import tempfile
_models = tempfile.mkdtemp()
os.environ["AFNI_MODEL_DIR"] = _models
for name in ("protectai__deberta-v3-base-prompt-injection-v2",
             "unitary__unbiased-toxic-roberta",
             "MoritzLaurer__deberta-v3-base-zeroshot-v2.0",
             "valurank__distilroberta-bias",
             "MoritzLaurer__roberta-base-zeroshot-v2.0-c"):
    d = Path(_models) / name
    d.mkdir()
    (d / "config.json").write_text("{}")
    (d / "model.safetensors").write_bytes(b"\x00")
print(f"fake model folders at {_models}\n")


def fake(name, **attrs):
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class FakePipeline:
    """A text-classification pipeline that answers plausibly and never blocks."""
    def __call__(self, text, **kw):
        return [{"label": "SAFE", "score": 0.02}]


def fake_pipeline(*a, **kw):
    return FakePipeline()


class FakeTensor:
    def softmax(self, *a, **kw):
        return self
    def tolist(self):
        return [0.9, 0.1]
    def __getitem__(self, i):
        return self


fake("torch", no_grad=lambda: __import__("contextlib").nullcontext(),
     tensor=lambda *a, **k: FakeTensor(),
     softmax=lambda t, dim: FakeTensor())
class FakeTokenizer:
    def __call__(self, *a, **kw):
        return {"input_ids": FakeTensor()}


class FakeModel:
    """Matches what the rail actually does: model(**pair)["logits"][0], then
    torch.softmax(...).tolist()."""
    def eval(self):
        return self
    def __call__(self, **kw):
        return {"logits": FakeTensor()}


fake("transformers", pipeline=fake_pipeline,
     AutoTokenizer=types.SimpleNamespace(
         from_pretrained=lambda *a, **k: FakeTokenizer()),
     AutoModelForSequenceClassification=types.SimpleNamespace(
         from_pretrained=lambda *a, **k: FakeModel()))


class FakeScanner:
    def __init__(self, *a, **kw):
        pass
    def scan(self, prompt, *a, **kw):
        # llm-guard's contract: (sanitised, is_valid, risk_score)
        return prompt, True, 0.0


lg = fake("llm_guard")
fake("llm_guard.input_scanners")
model_cls = types.SimpleNamespace
tox = fake("llm_guard.input_scanners.toxicity",
           Toxicity=FakeScanner,
           DEFAULT_MODEL=types.SimpleNamespace(path="x", revision=None))
fake("llm_guard.input_scanners.ban_topics",
     BanTopics=FakeScanner,
     MODEL_ROBERTA_BASE_C_V2=types.SimpleNamespace(path="x", revision=None))
fake("presidio_analyzer", AnalyzerEngine=lambda *a, **k: types.SimpleNamespace(
    analyze=lambda *a, **k: []))

modules = ["tests.test_accountability", "tests.test_content_safety",
           "tests.test_contract_conformance", "tests.test_explainability",
           "tests.test_fairness", "tests.test_hallucination",
           "tests.test_models", "tests.test_privacy", "tests.test_security",
           "tests.test_threshold_wiring", "tests.test_foundation"]
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for m in modules:
    try:
        suite.addTests(loader.loadTestsFromName(m))
    except Exception as exc:
        print(f"!! could not load {m}: {exc}")
result = unittest.TextTestRunner(verbosity=0).run(suite)
print("\n=== FAILURES WITH THE MODELS PRESENT ===")
for case, _ in result.failures + result.errors:
    print(" ", case.id())
print(f"\n{len(result.failures)} failures, {len(result.errors)} errors, "
      f"{result.testsRun} run")
