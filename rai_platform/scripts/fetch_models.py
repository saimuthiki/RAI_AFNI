# -*- coding: utf-8 -*-
"""
Download the five Stage-2 models into the local drop-in folder.

    python rai_platform/scripts/fetch_models.py
    python rai_platform/scripts/fetch_models.py --dest "D:\\Afni\\RAI_AFNI-main\\rai_platform\\models"
    python rai_platform/scripts/fetch_models.py --only security
    python rai_platform/scripts/fetch_models.py --dry-run

Run this on a machine that can reach huggingface.co. Works on Windows, macOS
and Linux; nothing here shells out, so there is no quoting to get wrong.

Why a script and not five `huggingface-cli` lines:

  * It reads the model ids and pinned revisions from the rails themselves, so it
    cannot ask for a different model than the platform loads.
  * It skips the ONNX, OpenVINO, CoreML, TensorFlow and Flax copies of the same
    weights. A HuggingFace repo often carries four formats of one model, and a
    plain `huggingface-cli download` takes all of them - several gigabytes of
    files this platform will never open.
  * It prefers `.safetensors` and only falls back to `pytorch_model.bin` when a
    repo has no safetensors at all, rather than taking both.
  * It PRINTS THE RESOLVED COMMIT SHA for each model. One of the five has no
    pinned revision in the code yet, and that sha is what pins it.
  * It verifies each folder against the same check the gateway uses, so a
    half-finished download is reported here rather than surfacing later as a
    rail that mysteriously will not load.
"""
from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Other frameworks' copies of the same weights, plus documentation. Excluded to
# keep the download to what transformers will actually open.
IGNORE = [
    "*.msgpack",        # Flax
    "*.h5",             # TensorFlow
    "*.tflite",
    "*.ot",             # Rust
    "*.onnx", "*.onnx_data", "onnx/*", "onnx_*/*",
    "openvino/*", "coreml/*",
    "*.md", "*.gitattributes", ".gitattributes",
]

# Pass 1: safetensors only. Pass 2 adds the pickle format, for a repo that has
# no safetensors at all.
SAFETENSORS_ONLY = IGNORE + ["*.bin"]


def targets():
    """(key, repo_id, revision, folder_name) for each model, read off the rails."""
    from afni_rai.models import folder_name
    from afni_rai.preflight import _hf_models

    out = []
    for rail, repo, revision, tenet, size, _why in _hf_models():
        if repo.startswith("<"):
            print(f"  ! could not read the model id for {rail}: {repo}")
            continue
        key = rail.split(".")[-1] if "." in rail else rail
        out.append((key, rail, repo, revision, folder_name(repo), tenet, size))
    return out


def download(repo_id, revision, dest: Path, ignore) -> str:
    """Fetch into `dest` as a plain folder. Returns the resolved commit sha."""
    from huggingface_hub import snapshot_download

    kwargs = dict(repo_id=repo_id, local_dir=str(dest), ignore_patterns=ignore)
    if revision:
        kwargs["revision"] = revision
    # Older huggingface_hub needs this to write real files instead of symlinks
    # into the shared cache; newer versions removed the argument. Passing it
    # blindly raises a TypeError on new versions, so ask first.
    params = inspect.signature(snapshot_download).parameters
    if "local_dir_use_symlinks" in params:
        kwargs["local_dir_use_symlinks"] = False
    path = snapshot_download(**kwargs)
    return resolved_sha(repo_id, revision) or "unknown"


def resolved_sha(repo_id, revision) -> str | None:
    """The commit sha actually downloaded. This is what pins an unpinned model."""
    try:
        from huggingface_hub import HfApi
        return HfApi().model_info(repo_id, revision=revision).sha
    except Exception:  # noqa: BLE001 - informational only, never fatal
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Download the Stage-2 models into the drop-in folder.")
    parser.add_argument("--dest", default=None,
                        help="where to write (default: rai_platform/models, or "
                             "AFNI_MODEL_DIR if set)")
    parser.add_argument("--only", action="append", default=None,
                        help="substring of a rail or model name; repeatable")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and exit, download nothing")
    parser.add_argument("--all-formats", action="store_true",
                        help="do not skip the ONNX/TF/Flax copies (rarely wanted)")
    args = parser.parse_args(argv)

    from afni_rai.models import missing_files, model_dir

    dest_root = Path(args.dest).expanduser() if args.dest else model_dir()
    plan = targets()
    if args.only:
        wanted = [w.lower() for w in args.only]
        plan = [row for row in plan
                if any(w in row[1].lower() or w in row[2].lower() for w in wanted)]
        if not plan:
            print(f"nothing matched {args.only}")
            return 2

    print(f"Destination: {dest_root}")
    print(f"Models: {len(plan)}\n")
    for _key, rail, repo, revision, folder, tenet, size in plan:
        pin = revision[:12] if revision else "NOT PINNED"
        print(f"  {repo}")
        print(f"    -> {dest_root / folder}")
        print(f"       {tenet} · {rail} · {size} · revision {pin}")
    print()

    if args.dry_run:
        print("--dry-run: nothing downloaded.")
        return 0

    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        print("huggingface_hub is not installed. Run:\n"
              "    pip install huggingface_hub\n")
        return 2

    dest_root.mkdir(parents=True, exist_ok=True)
    shas: dict[str, str] = {}
    failures: list[tuple[str, str]] = []

    for _key, rail, repo, revision, folder, _tenet, _size in plan:
        dest = dest_root / folder
        print(f"=== {repo}")
        if not missing_files(dest):
            print(f"    already complete at {dest} - skipping")
            shas[repo] = resolved_sha(repo, revision) or "unknown"
            continue
        ignore = IGNORE if args.all_formats else SAFETENSORS_ONLY
        try:
            sha = download(repo, revision, dest, ignore)
        except Exception as exc:  # noqa: BLE001
            print(f"    FAILED: {exc.__class__.__name__}: {exc}")
            failures.append((repo, f"{exc.__class__.__name__}: {exc}"))
            continue

        short = missing_files(dest)
        if short and not args.all_formats:
            # No safetensors in this repo. Take the pickle format instead.
            print(f"    no safetensors found ({', '.join(short)}) - "
                  f"retrying with pytorch_model.bin")
            try:
                sha = download(repo, revision, dest, IGNORE)
            except Exception as exc:  # noqa: BLE001
                print(f"    FAILED on retry: {exc.__class__.__name__}: {exc}")
                failures.append((repo, str(exc)))
                continue
            short = missing_files(dest)

        if short:
            print(f"    INCOMPLETE - still missing: {', '.join(short)}")
            failures.append((repo, "incomplete: " + ", ".join(short)))
        else:
            size_mb = sum(f.stat().st_size for f in dest.rglob("*")
                          if f.is_file()) / 1_048_576
            print(f"    OK  {dest}  ({size_mb:.0f} MB)")
            print(f"    commit sha: {sha}")
            shas[repo] = sha
        print()

    # ---- what to do next ---------------------------------------------------
    print("=" * 70)
    if failures:
        print(f"{len(failures)} model(s) did not complete:\n")
        for repo, why in failures:
            print(f"  {repo}\n    {why}")
        print()

    unpinned = [(rail, repo) for _k, rail, repo, revision, *_ in plan
                if not revision]
    if unpinned:
        print("These models have NO pinned revision in the code. Send the sha")
        print("below so the pin can be recorded - an unpinned SECURITY model")
        print("means upstream can replace the weights and this gateway adopts")
        print("them on the next cold start, silently.\n")
        for rail, repo in unpinned:
            print(f"  {rail}")
            print(f"    {repo}")
            print(f"    sha: {shas.get(repo, 'download did not complete')}\n")

    print("Verify with:")
    print("    python rai_platform/cli.py preflight")
    print("    python rai_platform/cli.py coverage")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
