# -*- coding: utf-8 -*-
"""
Tests for the local model-folder resolver.

The point of `afni_rai/models.py` is that a network without huggingface.co can
still run the Stage-2 tier, by dropping model folders into `rai_platform/models/`.
So the things worth pinning are: a folder is found, a half-copied folder is NOT
treated as a model, and the kwargs handed to `from_pretrained` are legal for
whichever source won - `revision=` is rejected outright for a local path, so
getting that wrong turns a working drop-in into a load failure that reads like a
missing model.

Run: python3 rai_platform/run_tests.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from afni_rai import models  # noqa: E402

REPO = "protectai/deberta-v3-base-prompt-injection-v2"
SHA = "c1e4a2773522c3acc929a7b2c9af2b7e4137b96d"


class _WithModelDir(unittest.TestCase):
    """Every test runs against a temporary AFNI_MODEL_DIR, so nothing here
    depends on what happens to be sitting in the repo's own models/ folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._saved = os.environ.get("AFNI_MODEL_DIR")
        os.environ["AFNI_MODEL_DIR"] = str(self.root)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("AFNI_MODEL_DIR", None)
        else:
            os.environ["AFNI_MODEL_DIR"] = self._saved
        self._tmp.cleanup()

    def make_model(self, name, config=True, weights="model.safetensors"):
        folder = self.root / name
        folder.mkdir(parents=True)
        if config:
            (folder / "config.json").write_text("{}", encoding="utf-8")
        if weights:
            (folder / weights).write_bytes(b"\x00" * 16)
        return folder


class TestResolution(_WithModelDir):

    def test_falls_back_to_the_pinned_hub_id_when_no_folder_exists(self):
        resolved = models.resolve(REPO, SHA)
        self.assertFalse(resolved.local)
        self.assertEqual(resolved.target, REPO)
        self.assertEqual(resolved.revision, SHA)
        self.assertEqual(resolved.kwargs,
                         {"revision": SHA, "local_files_only": True})

    def test_a_dropped_in_folder_wins(self):
        folder = self.make_model("protectai__deberta-v3-base-prompt-injection-v2")
        resolved = models.resolve(REPO, SHA)
        self.assertTrue(resolved.local)
        self.assertEqual(resolved.target, str(folder))

    def test_the_bare_model_name_is_accepted_too(self):
        """A human copying a download is as likely to name the folder after the
        model as after `org__model`. Both work."""
        folder = self.make_model("deberta-v3-base-prompt-injection-v2")
        self.assertEqual(models.resolve(REPO, SHA).target, str(folder))

    def test_the_org_prefixed_form_is_preferred_when_both_exist(self):
        qualified = self.make_model("protectai__deberta-v3-base-prompt-injection-v2")
        self.make_model("deberta-v3-base-prompt-injection-v2")
        self.assertEqual(models.resolve(REPO, SHA).target, str(qualified))


class TestTheKwargsAreLegalForTheSourceThatWon(_WithModelDir):
    """`from_pretrained` REJECTS `revision=` for a local path. Passing it anyway
    would turn a correct drop-in into a load failure indistinguishable from a
    missing model - so this is the assertion that makes the feature work."""

    def test_a_local_folder_gets_neither_revision_nor_local_files_only(self):
        self.make_model("protectai__deberta-v3-base-prompt-injection-v2")
        resolved = models.resolve(REPO, SHA)
        self.assertEqual(resolved.kwargs, {})
        self.assertIsNone(resolved.revision)

    def test_an_unpinned_repo_resolves_without_raising(self):
        """The security rail carried no pinned revision, so `revision` is None
        on the single most important model here. An earlier version of the
        resolver indexed it unconditionally and raised TypeError on exactly
        this path."""
        for local in (False, True):
            if local:
                self.make_model("protectai__deberta-v3-base-prompt-injection-v2")
            with self.subTest(local=local):
                resolved = models.resolve(REPO, None)
                self.assertEqual(resolved.local, local)
                self.assertIsNone(resolved.revision)
                self.assertTrue(resolved.note)

    def test_a_dropped_folder_says_the_pin_could_not_be_verified(self):
        # The pin is a provenance claim and a folder cannot evidence it. Silently
        # dropping it would let a report imply the pinned weights were used.
        self.make_model("protectai__deberta-v3-base-prompt-injection-v2")
        note = models.resolve(REPO, SHA).note
        self.assertIn("local folder", note)
        self.assertIn("not verifiable", note)
        self.assertIn(SHA[:12], note)


class TestAPartialDownloadIsNotAModel(_WithModelDir):
    """A half-copied folder must fail the same way a missing one does - as an
    honest `unjudged`, not as an exception thrown from inside a live request."""

    def test_a_folder_with_no_config_is_rejected(self):
        self.make_model("protectai__deberta-v3-base-prompt-injection-v2",
                        config=False)
        self.assertFalse(models.resolve(REPO, SHA).local)

    def test_a_folder_with_no_weights_is_rejected(self):
        self.make_model("protectai__deberta-v3-base-prompt-injection-v2",
                        weights=None)
        self.assertFalse(models.resolve(REPO, SHA).local)

    def test_an_empty_directory_is_rejected(self):
        (self.root / "protectai__deberta-v3-base-prompt-injection-v2").mkdir()
        self.assertFalse(models.resolve(REPO, SHA).local)

    def test_every_accepted_weight_format_is_accepted(self):
        for weights in ("model.safetensors", "pytorch_model.bin", "model.onnx"):
            with self.subTest(weights=weights):
                with tempfile.TemporaryDirectory() as tmp:
                    os.environ["AFNI_MODEL_DIR"] = tmp
                    folder = Path(tmp) / "protectai__deberta-v3-base-prompt-injection-v2"
                    folder.mkdir()
                    (folder / "config.json").write_text("{}", encoding="utf-8")
                    (folder / weights).write_bytes(b"\x00")
                    self.assertTrue(models.resolve(REPO, SHA).local, weights)

    def test_missing_files_names_the_file_that_is_short(self):
        # "not found" sends someone hunting; "config.json is missing" does not.
        folder = self.make_model("x", config=False)
        self.assertIn("config.json", models.missing_files(folder))
        self.assertEqual(models.missing_files(self.root / "absent"),
                         ["the directory itself"])


class TestNoNetworkAndNoRaising(_WithModelDir):

    def test_resolve_never_raises_on_a_hostile_directory(self):
        # A file where a directory is expected, a dangling symlink - resolve is
        # called inside a rail's load path, so raising here would convert an
        # honest `unjudged` into a 500.
        (self.root / "protectai__deberta-v3-base-prompt-injection-v2").write_text(
            "not a directory", encoding="utf-8")
        self.assertFalse(models.resolve(REPO, SHA).local)

    def test_model_dir_honours_the_override_and_has_a_default(self):
        self.assertEqual(models.model_dir(), self.root)
        os.environ.pop("AFNI_MODEL_DIR")
        self.assertEqual(models.model_dir().name, "models")

    def test_folder_name_uses_a_double_underscore(self):
        # Single would be ambiguous: model names contain underscores of their own.
        self.assertEqual(models.folder_name("a/b_c"), "a__b_c")


class TestPreflightReport(unittest.TestCase):

    def test_it_reads_the_ids_off_the_rails_rather_than_a_hand_list(self):
        """A manifest maintained separately is wrong the first time a pin moves.
        So every id in the report must come from the rail that loads it."""
        from afni_rai.preflight import collect

        assets = collect()
        models_listed = {a.name for a in assets if a.kind == "model"}
        for expected in ("protectai/deberta-v3-base-prompt-injection-v2",
                         "valurank/distilroberta-bias",
                         "MoritzLaurer/deberta-v3-base-zeroshot-v2.0",
                         "unitary/unbiased-toxic-roberta",
                         "MoritzLaurer/roberta-base-zeroshot-v2.0-c",
                         "en_core_web_lg"):
            self.assertIn(expected, models_listed)
        # No id may come back as a read failure - that would mean a rail was
        # renamed and this report silently stopped naming its model.
        for name in models_listed:
            self.assertNotIn("could not read", name)

    def test_every_asset_says_where_it_comes_from_and_where_it_goes(self):
        from afni_rai.preflight import collect

        for asset in collect():
            with self.subTest(asset=asset.name):
                self.assertTrue(asset.where_from, f"{asset.name}: no source")
                self.assertTrue(asset.destination, f"{asset.name}: no destination")
                self.assertTrue(asset.needed_by, f"{asset.name}: no consumer")

    def test_the_report_renders(self):
        from afni_rai.preflight import render

        text = render()
        self.assertIn("MODELS", text)
        self.assertIn("PYTHON PACKAGES", text)
        self.assertIn("CREDENTIALS", text)
        self.assertIn("NOT A DOWNLOAD", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
