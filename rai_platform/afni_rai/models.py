# -*- coding: utf-8 -*-
"""
Where the Stage-2 model weights come from.

Every Stage-2 rail loads its model by HuggingFace repo id, with a pinned
revision. That is the right default: the id plus the revision is a
reproducible, auditable reference, and `local_files_only` keeps a rail from
pulling 400MB inside a live request.

It is also unusable on a network where `huggingface.co` is blocked, which is
common in a corporate environment and is the case in this project's own build
container. The fallback in that situation is to fetch the weights on a machine
that can reach the hub and carry them across - but the HuggingFace cache layout
(`models--org--name/snapshots/<sha>/` with blobs behind symlinks) is not
something anyone should hand-assemble, and a mistake in it looks exactly like a
missing model.

So this module adds one thing: a plain directory, in the repo, where a model can
be dropped as an ordinary folder of files.

    rai_platform/models/protectai__deberta-v3-base-prompt-injection-v2/
        config.json
        model.safetensors
        tokenizer.json
        ...

`AFNI_MODEL_DIR` overrides the location. A folder found here wins over the hub,
and `resolve()` reports which one it used so `/healthz` and the preflight check
can say so out loud - "loaded from a local folder" and "downloaded from the hub"
are different provenance claims and a governance tool should not blur them.

The revision pin does NOT disappear when a local folder is used: it cannot be
verified (a folder carries no commit sha), so `Resolved.revision` comes back
`None` and the caller must not pass `revision=` to `from_pretrained`, which
rejects it for a local path. `preflight` records the pinned sha alongside the
folder so the substitution stays visible rather than silent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Files transformers needs before it can build a tokenizer and a model. A folder
# missing `config.json` is not a model, it is a partial download - and treating
# it as one produces an exception mid-request rather than an honest `unjudged`.
REQUIRED_FILES = ("config.json",)

# At least one of these must be present, or there are no weights to load.
WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin", "model.onnx",
                "tf_model.h5", "model.safetensors.index.json",
                "pytorch_model.bin.index.json")


def model_dir() -> Path:
    """The directory local model folders are read from."""
    override = os.environ.get("AFNI_MODEL_DIR")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / "models"


def folder_name(repo_id: str) -> str:
    """`org/name` -> `org__name`.

    Double underscore rather than a single one because model names contain
    single underscores of their own, and `org_name` would be ambiguous about
    where the org ends.
    """
    return repo_id.replace("/", "__")


@dataclass(frozen=True)
class Resolved:
    """What a rail should hand to `from_pretrained`."""

    target: str          # a repo id, or an absolute local path
    local: bool          # True when `target` is a directory on this machine
    revision: str | None  # the pin, or None when loading from a folder
    note: str            # one line for /healthz and the preflight report

    @property
    def kwargs(self) -> dict:
        """`revision` and `local_files_only` as `from_pretrained` wants them.

        A local path takes neither: `revision` is rejected outright, and
        `local_files_only` is meaningless for a path that is already local.
        """
        if self.local:
            return {}
        return {"revision": self.revision, "local_files_only": True}


def resolve(repo_id: str, revision: str | None = None) -> Resolved:
    """Prefer a local folder for `repo_id`; fall back to the pinned hub id.

    Never raises and never touches the network. A rail calls this, tries to
    load, and reports `unjudged` if the load fails - the same honest degrade
    path as a missing library.
    """
    root = model_dir()
    for candidate in (root / folder_name(repo_id), root / repo_id.split("/")[-1]):
        if _is_model_folder(candidate):
            note = f"local folder {candidate.name}"
            if revision:
                # Said out loud rather than dropped. The pin is the provenance
                # claim, and a folder cannot evidence it - so the substitution
                # has to be visible wherever the source is reported.
                note += (f" (pinned revision {revision[:12]} not verifiable "
                         f"for a local folder)")
            return Resolved(target=str(candidate), local=True, revision=None,
                            note=note)
    return Resolved(
        target=repo_id, local=False, revision=revision,
        note=f"hub {repo_id}" + (f"@{revision[:12]}" if revision else ""))


def _is_model_folder(path: Path) -> bool:
    if not path.is_dir():
        return False
    if not all((path / name).is_file() for name in REQUIRED_FILES):
        return False
    return any((path / name).is_file() for name in WEIGHT_FILES)


def missing_files(path: Path) -> list[str]:
    """Why a folder was not accepted. For the preflight report, so a half-copied
    download says which file is short rather than just 'not found'."""
    out = []
    if not path.is_dir():
        return ["the directory itself"]
    out += [name for name in REQUIRED_FILES if not (path / name).is_file()]
    if not any((path / name).is_file() for name in WEIGHT_FILES):
        out.append("a weights file (one of: " + ", ".join(WEIGHT_FILES[:3]) + ")")
    return out
