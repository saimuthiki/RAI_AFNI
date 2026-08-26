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
from dataclasses import dataclass, field

from .models import folder_name, missing_files, model_dir


@dataclass
class Asset:
    kind: str                 # model | package | credential | decision
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
        "escalates by design, so without this a textbook injection is allowed "
        "on internal traffic.")
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

    # ---- the one item that is not a download -------------------------------
    assets.append(Asset(
        kind="decision", name="allowed / banned topic list",
        needed_by="TopicScopeRail, content_safety.zeroshot_topics",
        tenet="Explainability & Transparency", where_from="AFNI - not a download",
        destination="passed to the rail at construction, per application",
        present=False,
        detail="empty, so TopicScopeRail is built and tested but NOT MOUNTED",
        notes=["This is the 'Ban-topics / on-topic scope' gap. Every reviewed "
               "tool treats on-topic as deployment policy (NeMo config.yml, "
               "DeepTeam TopicalGuard(allowed_topics=[...])), so no download "
               "closes it - it needs the list of topics each AFNI application "
               "is allowed to discuss."]))
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

    for kind, title in (("model", "MODELS"), ("package", "PYTHON PACKAGES"),
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
    lines.append("Nothing here stops the gateway running. Stage 1 - 22 rails "
                 "across all seven tenets - is")
    lines.append("pure standard library and needs none of it. Every item above "
                 "is a rail that reports")
    lines.append("`unjudged` until it arrives, which fails closed on "
                 "client-facing traffic.")
    return "\n".join(lines)
