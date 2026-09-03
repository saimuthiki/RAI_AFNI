# -*- coding: utf-8 -*-
"""
What is missing, where it goes, and where to get it.

    python3 rai_platform/cli.py preflight

One table. Every asset the platform needs but does not ship: the four
HuggingFace models behind the Stage-2 rails, the spaCy model behind Presidio,
the Python packages, the cloud credentials, and the one item that is a business
decision rather than a download.

The point is that it is generated from the code, not written by hand. Each model
id and pinned revision below is read off the rail that loads it, so this cannot
drift from what the platform actually asks for - a manifest maintained
separately is wrong the first time someone bumps a pin.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field

from .models import folder_name, missing_files, model_dir


@dataclass
class Asset:
    kind: str                 # model | package | credential | decision | abi
    name: str
    needed_by: str            # rail or capability
    tenet: str
    where_from: str
    destination: str
    present: bool
    detail: str = ""
    approx_size: str = ""
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# HuggingFace models, read off the rails themselves                            #
# --------------------------------------------------------------------------- #
def _hf_models() -> list[tuple[str, str, str | None, str, str, str]]:
    """(rail, repo_id, revision, tenet, size, why) for every HF-backed rail.

    Imported lazily and defensively: a tenet that will not import must not stop
    the preflight report, since a broken import is exactly when you most want to
    see what is missing.
    """
    out = []

    def add(module, cls_name, rail_name, tenet, size, why,
            id_attr="MODEL_ID", rev_attr="MODEL_REVISION"):
        try:
            import importlib
            mod = importlib.import_module(f".tenets.{module}", __package__)
            cls = getattr(mod, cls_name)
            repo = getattr(cls, id_attr)
            rev = getattr(cls, rev_attr, None)
            out.append((rail_name, repo, rev, tenet, size, why))
        except Exception as exc:  # noqa: BLE001
            out.append((rail_name, f"<could not read: {exc}>", None, tenet,
                        size, why))

    add("security", "DebertaInjectionRail", "security.injection.deberta_v3_v2",
        "Security", "~740 MB",
        "The only thing that BLOCKS a prompt injection. Stage 1 flags and "
        "escalates by design, so without this the block you get is the "
        "fail-closed one - a coverage gap, not a detection.")
    add("fairness", "LocalBiasClassifierRail", "llm_guard.bias", "Fairness & Bias",
        "~330 MB",
        "The only runtime bias signal beyond a regex. Fairness is 0/9 "
        "implemented without it.",
        id_attr="MODEL_PATH")
    add("hallucination", "NliGroundednessRail", "groundedness-nli",
        "Hallucination / Reliability", "~740 MB",
        "Entailment of an answer against its retrieved source - the only "
        "grounding check that is not a string comparison.")

    # The two content-safety rails go through llm-guard, so their ids are
    # module-level constants rather than class attributes.
    try:
        from .tenets import content_safety as cs
        out.append(("content_safety.toxicity_model", cs._TOXICITY_MODEL,
                    cs._TOXICITY_REVISION, "Profanity / Content Safety",
                    "~500 MB",
                    "7-head multilabel toxicity. Stage 1 catches slurs from a "
                    "lexicon; this catches toxicity with no banned word in it."))
        out.append(("content_safety.zeroshot_topics", cs._ZEROSHOT_MODEL,
                    cs._ZEROSHOT_REVISION, "Profanity / Content Safety",
                    "~500 MB",
                    "Zero-shot topic scoping. Needs a topic list too - see the "
                    "'decision' row."))
    except Exception as exc:  # noqa: BLE001
        out.append(("content_safety.*", f"<could not read: {exc}>", None,
                    "Profanity / Content Safety", "", ""))
    return out


def _abi_checks() -> list[Asset]:
    """Does the installed C-extension stack actually AGREE with itself?

    This section exists because a version list is not an answer. On 2026-09-03
    a machine had transformers installed, all five model folders downloaded, and
    every package present - and every Stage-2 rail was dead, because numpy had
    been upgraded to 2.5.2 while pandas was still compiled against numpy 1.x:

        transformers -> sklearn -> pandas -> ValueError: numpy.dtype size
        changed ... Expected 96 from C header, got 88 from PyObject

    `find_spec` said everything was fine. Only an ACTUAL IMPORT finds this, so
    that is what this does: it imports the two chains the rails depend on and
    reports what happened, with the fix. Four hours were spent on this once; the
    point of the section is that nobody spends them twice.

    Cost: a real import of transformers on a provisioned box, a few seconds,
    paid only when the package is present. `preflight` is a diagnostic command
    that a person runs deliberately - it is the one place that cost is correct.
    """
    import importlib.util

    out: list[Asset] = []

    def version_of(module: str) -> str | None:
        try:
            import importlib.metadata as md
            return md.version(module)
        except Exception:  # noqa: BLE001
            return None

    # ---- the numpy / opencv pairing, which is the one that fights ----------
    numpy_v = version_of("numpy")
    cv_v = (version_of("opencv-python-headless") or version_of("opencv-python"))
    if numpy_v or cv_v:
        major = int(numpy_v.split(".")[0]) if numpy_v else None
        # 4.12.0.88 is where opencv's own metadata switched to numpy>=2. Read
        # off each release's requires_dist, not guessed.
        cv_needs_numpy_2 = False
        if cv_v:
            try:
                parts = [int(x) for x in cv_v.split(".")[:2]]
                cv_needs_numpy_2 = (parts[0] > 4) or (parts[0] == 4 and parts[1] >= 12)
            except ValueError:
                cv_needs_numpy_2 = False
        agree = not (numpy_v and cv_v) or (cv_needs_numpy_2 == (major == 2))
        out.append(Asset(
            kind="abi", name="numpy / opencv pairing",
            needed_by="POST /v1/media/*", tenet="Profanity / Content Safety",
            where_from="requirements.txt pins the working pair",
            destination="site-packages",
            present=agree,
            detail=(f"numpy {numpy_v or 'absent'}, opencv {cv_v or 'absent'} - "
                    + ("compatible" if agree else "INCOMPATIBLE")),
            notes=([] if agree else [
                "opencv 4.12.0.88 and later REQUIRE numpy>=2; 4.11.0.86 and "
                "earlier require numpy>=1.26. Pick a matching pair.",
                'Fix: pip install "numpy>=1.26,<2" '
                '"opencv-python-headless>=4.10,<4.12"'])))

    # ---- the import chain the Stage-2 rails actually walk -----------------
    # `find_spec` RAISES ValueError when a module is already in sys.modules
    # with `__spec__` set to None - which is what a partially-initialised or
    # stubbed module looks like. A diagnostic command must never be the thing
    # that crashes, so the probe is guarded. Found by the test that fakes a
    # broken transformers: preflight died with "transformers.__spec__ is None"
    # instead of reporting the very problem it exists to report.
    try:
        transformers_present = importlib.util.find_spec("transformers") is not None
    except (ImportError, ValueError):
        # Present enough to be in sys.modules and broken enough to have no
        # spec. Either way there is something to import-check.
        transformers_present = "transformers" in sys.modules

    if transformers_present:
        broken = None
        try:
            from transformers import pipeline  # noqa: F401, PLC0415
        except Exception as exc:  # noqa: BLE001 - that is the finding
            broken = f"{exc.__class__.__name__}: {exc}"
        notes = []
        if broken and "numpy.dtype size changed" in broken:
            notes = [
                "This is a numpy ABI mismatch, not a missing package. A "
                "package compiled against numpy 1.x is running against numpy "
                "2.x (numpy 2.0 shrank PyArray_Descr from 96 to 88 bytes).",
                'Fix: pip install "numpy>=1.26,<2" - then re-run this command.',
                "While it lasts, all four Stage-2 model rails report `unjudged` "
                "and fail closed. That is correct behaviour, not a bug - they "
                "genuinely cannot look."]
        elif broken:
            notes = ["transformers is installed but will not import. The "
                     "Stage-2 model rails will report `unjudged` and fail "
                     "closed until it does."]
        out.append(Asset(
            kind="abi", name="transformers imports",
            needed_by="all four Stage-2 model rails", tenet="all",
            where_from="already installed - this is a usability check",
            destination="site-packages",
            present=broken is None,
            detail="imports cleanly" if broken is None else broken.split("\n")[0],
            notes=notes))

    return out


def collect() -> list[Asset]:
    assets: list[Asset] = []
    root = model_dir()

    for rail, repo, rev, tenet, size, why in _hf_models():
        folder = root / folder_name(repo)
        present = not missing_files(folder)
        detail = ("found" if present
                  else "missing: " + ", ".join(missing_files(folder)))
        notes = []
        if rev:
            notes.append(f"pinned revision {rev}")
        else:
            notes.append("NO PINNED REVISION - record the sha you download")
        assets.append(Asset(
            kind="model", name=repo, needed_by=rail, tenet=tenet,
            where_from=f"https://huggingface.co/{repo}"
                       + (f"/tree/{rev}" if rev else ""),
            destination=str(folder), present=present, detail=detail,
            approx_size=size, notes=notes + [why]))

    # ---- Python packages ---------------------------------------------------
    packages = [
        ("transformers", "all four HF-backed Stage-2 rails", "all", "~12 MB",
         "PyPI - reachable"),
        ("torch", "all four HF-backed Stage-2 rails", "all", "~900 MB (CPU)",
         "PyPI - reachable. Use the CPU wheel index unless you have a GPU."),
        ("llm_guard", "content_safety.toxicity_model, .zeroshot_topics",
         "Profanity / Content Safety", "~1 MB",
         "PyPI as `llm-guard` - reachable"),
        ("presidio_analyzer", "privacy.presidio_ner", "Privacy", "~1 MB",
         "PyPI - reachable"),
        ("spacy", "privacy.presidio_ner", "Privacy", "~30 MB",
         "PyPI - reachable"),
        ("fastapi", "the gateway", "all", "~5 MB", "PyPI - reachable"),
        ("uvicorn", "the gateway", "all", "~1 MB", "PyPI - reachable"),
        ("httpx", "the Stage-3 judge chain", "all", "~1 MB", "PyPI - reachable"),
        # Media moderation. `nudenet` is the unusual one in this list: the 12 MB
        # 320n.onnx model ships INSIDE the wheel, so `pip install nudenet` is
        # both the library and the model download and nothing is fetched at
        # runtime. That is the only reason media moderation works air-gapped
        # while the Infosys Keras alternative does not.
        ("nudenet", "POST /v1/media/image, /v1/media/video",
         "Profanity / Content Safety", "~11 MB wheel (model included)",
         "PyPI - reachable. Ships nudenet/320n.onnx inside the wheel."),
        ("onnxruntime", "POST /v1/media/* (runs 320n.onnx)",
         "Profanity / Content Safety", "~60 MB", "PyPI - reachable"),
        ("cv2", "POST /v1/media/* (decode, blur, video frames)",
         "Profanity / Content Safety", "~40 MB",
         "PyPI as `opencv-python-headless` - reachable. Headless, not the "
         "full `opencv-python`: a gateway has no display and the GUI build "
         "pulls in X11."),
    ]
    for module, needed_by, tenet, size, where in packages:
        present = importlib.util.find_spec(module) is not None
        assets.append(Asset(
            kind="package", name=module, needed_by=needed_by, tenet=tenet,
            where_from=where, destination="site-packages (pip install)",
            present=present, detail="installed" if present else "not installed",
            approx_size=size))

    # ---- spaCy pipeline ----------------------------------------------------
    spacy_present = False
    spacy_detail = "spacy itself is not installed"
    if importlib.util.find_spec("spacy") is not None:
        spacy_present = importlib.util.find_spec("en_core_web_lg") is not None
        spacy_detail = ("installed" if spacy_present
                        else "spacy is present but en_core_web_lg is not")
    assets.append(Asset(
        kind="model", name="en_core_web_lg", needed_by="privacy.presidio_ner",
        tenet="Privacy", approx_size="~590 MB",
        where_from="github.com/explosion/spacy-models/releases - reachable, "
                   "NOT huggingface.co",
        destination="site-packages (pip install), not the models/ folder",
        present=spacy_present, detail=spacy_detail,
        notes=["Install with `python -m spacy download en_core_web_lg`, never a "
               "pinned wheel URL: the model version must match the installed "
               "spaCy, and a 3.7 model against spaCy 3.8 installs cleanly then "
               "fails to load."]))

    # ---- cloud credentials -------------------------------------------------
    creds = [
        ("OPENAI_API_KEYS", "Stage-3 judge chain", "all",
         "Comma-separated, tried in order."),
        ("GOOGLE_API_KEYS", "Stage-3 judge chain", "all",
         "Comma-separated, tried in order."),
        ("LOCAL_BASE_URL", "Stage-3 judge chain (preferred)", "all",
         "An OpenAI-compatible local endpoint. The ONLY judge option that keeps "
         "flagged content on your own network."),
        ("AZURE_CONTENT_SAFETY_KEY", "security.prompt_shields", "Security",
         "Azure AI Content Safety. Optional - Stage 1 and 2 cover injection "
         "without it."),
    ]
    for var, needed_by, tenet, note in creds:
        assets.append(Asset(
            kind="credential", name=var, needed_by=needed_by, tenet=tenet,
            where_from="your own vendor account",
            destination=".env (gitignored) - never a committed file",
            present=bool(os.environ.get(var, "").strip()),
            detail="set" if os.environ.get(var, "").strip() else "empty",
            notes=[note]))

    # ---- the topic list ----------------------------------------------------
    # This WAS the "one item that is not a download": an outstanding decision,
    # reported as making TopicScopeRail unmounted. It no longer is, and leaving
    # the old text here would have preflight telling an operator the rail was
    # off while it was blocking their traffic. Six topics are compiled in and
    # the rest are an operator choice, so what preflight reports now is which
    # optional ones this deployment has selected - never "missing".
    from . import topics as _topics                             # noqa: PLC0415
    _pol = _topics.load_policy()
    _flagging, _blocking = _topics.patterns_for(_pol)
    assets.append(Asset(
        kind="decision", name="allowed / banned topic list",
        needed_by="TopicScopeRail (mounted by load_tenets)",
        tenet="Explainability & Transparency",
        where_from="AFNI - not a download. Set it in the console's Topics "
                   "screen, or PUT /v1/topics.",
        destination=str(_topics.policy_path()),
        # Present because the rail is armed either way: the six ALWAYS topics
        # are compiled into topics.py and cannot be switched off, so there is
        # no state in which this is an outstanding blocker.
        present=True,
        detail=(f"{len(_topics.ALWAYS)} always-on topics compiled in; "
                f"{len(_pol.enabled)} of {len(_topics.OPTIONAL)} optional "
                f"topics enabled ({len(_pol.blocking)} promoted to blocking); "
                f"{len(_blocking)} blocking and {len(_flagging)} flagging "
                f"patterns armed"),
        notes=["The six always-on topics need no configuration and cannot be "
               "disabled from the UI or the policy file - only by a code "
               "change to topics.py.",
               "The optional 24 ship OFF, because on-topic scope genuinely "
               "differs per application: a benefits helpdesk must discuss "
               "medical leave and a billing bot must not.",
               "An enabled topic FLAGS by default. Promoting one to BLOCK is a "
               "separate per-topic control, because a keyword hit is evidence "
               "rather than a verdict."]))
    # ABI checks last: they do real imports, so everything else
    # is already reported by the time one of them is slow.
    assets.extend(_abi_checks())
    return assets


def render() -> str:
    assets = collect()
    lines: list[str] = []
    lines.append("AFNI Responsible AI - preflight")
    try:
        from .build_info import banner
        lines.append(banner())
    except Exception:  # noqa: BLE001
        pass
    lines.append("")
    lines.append(f"Local model folder: {model_dir()}")
    lines.append(f"  (override with AFNI_MODEL_DIR)")
    lines.append("")

    for kind, title in (("abi", "ENVIRONMENT - DOES THE STACK AGREE WITH ITSELF"),
                        ("model", "MODELS"), ("package", "PYTHON PACKAGES"),
                        ("credential", "CREDENTIALS"),
                        ("decision", "NOT A DOWNLOAD")):
        rows = [a for a in assets if a.kind == kind]
        if not rows:
            continue
        have = sum(1 for a in rows if a.present)
        lines.append(f"{title}  ({have}/{len(rows)} present)")
        lines.append("-" * 74)
        for a in rows:
            mark = "OK  " if a.present else "MISS"
            lines.append(f"  [{mark}] {a.name}")
            lines.append(f"         needed by : {a.needed_by}  ({a.tenet})")
            lines.append(f"         status    : {a.detail}")
            if not a.present:
                lines.append(f"         get from  : {a.where_from}")
                lines.append(f"         put in    : {a.destination}")
                if a.approx_size:
                    lines.append(f"         size      : {a.approx_size}")
            for note in a.notes:
                lines.append(f"         note      : {note}")
            lines.append("")
        lines.append("")

    missing = [a for a in assets if not a.present]
    lines.append(f"{len(missing)} item(s) outstanding, "
                 f"{len(assets) - len(missing)} present.")
    lines.append("")
    # The Stage-1 count is COUNTED, not written down. It was hardcoded at 22 and
    # went stale the moment the topic rail was mounted; a number in prose that
    # nothing checks is a number that will be wrong.
    stage_1 = _stage_1_count()
    lines.append(f"Nothing here stops the gateway running. Stage 1 - {stage_1} "
                 "rails across all seven tenets - is")
    lines.append("pure standard library and needs none of it. Every item above "
                 "is a rail that reports")
    lines.append("`unjudged` until it arrives, and unjudged fails closed - "
                 "unconditionally, for every")
    lines.append("caller, with no request field and no switch that relaxes it.")
    lines.append("")
    lines.append("Media moderation is the exception to 'nothing stops it "
                 "running': images and video are")
    lines.append("judged only if `nudenet` is installed, and every image comes "
                 "back unjudged - so blocked -")
    lines.append("until it is. `GET /v1/media` reports which.")
    return "\n".join(lines)


def _stage_1_count() -> int:
    """How many rails run for free on every request.

    Imported lazily and defensively: `preflight` must still render on an install
    where a tenet cannot import, because reporting what is missing is the whole
    point of this command. A failure here returns 0 rather than raising, and 0
    reads as obviously wrong rather than as a plausible lie.
    """
    try:
        from .cli import load_tenets                            # noqa: PLC0415
        from .cascade.rail import Stage                         # noqa: PLC0415
        rails, _attrs, _problems = load_tenets()
        return sum(1 for r in rails if r.stage is Stage.STAGE_1)
    except Exception:  # noqa: BLE001
        return 0
