# -*- coding: utf-8 -*-
"""
One merged slide per tenet, replacing the two overlapping sets that both carried
an "AFNI RECOMMENDATION" heading:

  * the tenet "cheat sheets" (build_deck_tenetcards.TENET_CARDS) - open-source
    lead / cloud lead / recommendation / principle, all as prose
  * the tenet recommendation slides (build_deck_synthesis.add_tenet_recommendation_slide)
    - option pills, cloud bullets, badge combination, long rationale

Why they looked contradictory
-----------------------------
They were answering two different questions under the same label. The
recommendation slides answered "which of the 23 reviewed repos should AFNI
adopt", so their badges are repo names. The cheat sheets answered "what does the
runtime stack look like", which mixes repos with the *engines* inside them and
the *cloud services* beside them. For Privacy that produced "Presidio + Azure
PII" on one slide and "LLM Guard + NeMo Guardrails + garak" on another - the same
stack described at two different layers, but a client cannot tell that.

The fix is not to pick one. It is to state the recommendation in the three
layers it actually has, each explicitly labelled, so nothing reads as a
contradiction:

    ADOPT              which of the 23 reviewed repos AFNI takes on
    ENGINE UNDER IT    the library or model those repos actually run
    CLOUD SECOND OPINION  the managed service layered beside them
    WHERE IT RUNS      the cascade stage, from the methodology analysis

Where the two sets genuinely disagreed rather than merely differing in altitude,
`conflict` records the call and the evidence for it. Prose is reused from
TENET_CARDS and the rationale from RAI_Synthesis.json, so there is no third copy
of any text to keep in sync.
"""
import json
import os

from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

from build_pptx import (
    blank_slide, add_rect, add_rounded, add_text, add_header, badge, pill,
    NAVY, TEAL, CARD_BG, WHITE, TEXT_DARK, TEXT_MUTED, TEXT_SOFT_ON_NAVY,
    AMBER, GREEN, RED_SOFT, LINE_GREY, TENET_COLORS, FONT_HEAD, FONT_BODY,
)
from build_deck_tenetcards import TENET_CARDS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_ROOT, "data", "RAI_Synthesis.json"), encoding="utf-8") as f:
    _SYN = json.load(f)
TENET_MATRIX = {t["tenet"]: t for t in _SYN["tenet_matrix"]}

SHORT = {
    "llm-guard-main": "LLM Guard", "Guardrails-develop": "NeMo Guardrails",
    "guardrails-main": "Guardrails AI", "garak-main": "garak", "PyRIT-main": "PyRIT",
    "fairlearn-main": "Fairlearn", "AIF360-main": "AIF360", "promptfoo-main": "Promptfoo",
    "shap-master": "SHAP", "deepeval-main": "DeepEval", "deepteam-main": "DeepTeam",
    "openguardrails-main": "OpenGuardrails", "giskard-oss-main": "Giskard",
    "hai-guardrails-main": "hai-guardrails", "safe-zone-main": "Safe Zone (TSZ)",
    "Infosys-Responsible-AI-Toolkit-master": "Infosys RAI Toolkit",
    "agentic_security-main": "Agentic Security", "deepchecks-main": "Deepchecks",
    "evals-main": "OpenAI Evals", "FuzzyAI-main": "FuzzyAI", "JCB-main": "JCB",
    "LLMFuzzer-main": "LLMFuzzer", "rebuff-main": "Rebuff",
}


# Light amber tint for the reconciliation note - flags "this is where the two
# earlier slides disagreed" without shouting.
RGB_NOTE = RGBColor(0xFD, 0xF6, 0xE7)


def short(folder):
    return SHORT.get(folder, folder)


# The reconciled recommendation, one entry per tenet. `adopt` is the single
# authoritative repo pick; engine/cloud/cascade say what sits under and beside
# it so the earlier two-slide split cannot re-emerge as ambiguity.
RECONCILED = {
    "Privacy": {
        "adopt": ["llm-guard-main", "Guardrails-develop", "garak-main"],
        "engine": "Microsoft Presidio - 18 country packs including India Aadhaar (Verhoeff checksum), PAN, "
                  "GSTIN, US SSN/ITIN - plus an ai4privacy DeBERTa NER. LLM Guard wraps both and adds a Vault, "
                  "the only reversible redaction in the whole set.",
        "cloud": "Azure AI Language PII, in Conversation-PII mode for contact-centre transcripts - a direct "
                 "match for AFNI's BPO workload. ~$0.38 per 1,000 records (verify the current rate).",
        "cascade": "Stage 1 LLM Guard + NeMo deterministic pass on every request  ·  Stage 2 Azure PII on "
                   "Azure-native traffic  ·  Offline garak ProPILE leakage probes",
        "conflict": "Presidio is the engine inside LLM Guard and NeMo, not a separate thing to adopt. That is "
                    "the whole reason the earlier two slides read differently.",
    },
    "Security": {
        "adopt": ["llm-guard-main", "Guardrails-develop", "PyRIT-main"],
        "engine": "LLM Guard's protectai/deberta-v3-base-prompt-injection-v2 and bc-detect-secrets (95 pattern "
                  "plugins); NeMo's YARA sqli/code/template/xss rules and its NemoGuard-JailbreakDetect ONNX "
                  "classifier.",
        "cloud": "Azure AI Content Safety Prompt Shields - the most mature named capability for direct and "
                 "indirect (document-borne) injection. Never the only filter.",
        "cascade": "Stage 1 secrets, invisible-text, YARA rules  ·  Stage 2 DeBERTa injection classifier  "
                   "·  Stage 3 Prompt Shields on high-risk traffic  ·  Offline PyRIT and garak",
        "conflict": "Both earlier slides agreed here. Note from the source read: NeMo's jailbreak rail defaults "
                    "to fail-OPEN and must be explicitly flipped.",
    },
    "Fairness & Bias": {
        "adopt": ["fairlearn-main", "AIF360-main", "promptfoo-main"],
        "engine": "Fairlearn MetricFrame plus ThresholdOptimizer/ExponentiatedGradient; AIF360's MDSS and FACTS "
                  "scanners, which discover which subgroup is biased instead of requiring AFNI to name it first.",
        "cloud": "Azure ML Responsible AI dashboard - built on Fairlearn itself, so a managed client-facing view "
                 "at no extra licence. Fiddler or Arthur only if always-on drift alerting is needed.",
        "cascade": "Batch only. 11 of the 13 tools reviewed for this tenet cannot run inline at all - bias is a "
                   "pattern, not an event, so this is never a live per-response check.",
        "conflict": "Both earlier slides agreed. Every metric here needs a labelled ground truth and a declared "
                    "protected attribute, which is what makes it structurally offline.",
    },
    "Explainability & Transparency": {
        "adopt": ["shap-master", "deepeval-main"],
        "engine": "SHAP's auto-dispatching Explainer - exact for tree and linear models, approximate "
                  "(Kernel/Deep) elsewhere; DeepEval's G-Eval and DAG rubrics, versioned and CI-runnable "
                  "instead of an ad-hoc judge prompt.",
        "cloud": "Azure ML RAI dashboard surfaces SHAP client-facing at no extra licence cost; IBM AIX360 and "
                 "InterpretML add counterfactual and rule-based families.",
        "cascade": "Async explain endpoint, never synchronous - SHAP's Kernel cost scales samples × features. "
                   "DeepEval rubrics run in CI.",
        "conflict": "Both earlier slides agreed. Three different questions need three different tools: SHAP "
                    "explains the model, the Verdict schema explains the guardrail, a rubric explains a policy call.",
    },
    "Profanity / Content Safety": {
        "adopt": ["llm-guard-main", "Guardrails-develop", "promptfoo-main"],
        "engine": "LLM Guard's unitary/unbiased-toxic-roberta and valurank/distilroberta-bias, plus zero-shot "
                  "BanTopics that needs no retraining for a new restricted topic; NeMo routes borderline cases "
                  "to Llama Guard 3 or ShieldGemma.",
        "cloud": "Azure AI Content Safety - managed, multi-modal, severity-graded, with custom blocklists and "
                 "the audit evidence a client reviewer will ask to see.",
        "cascade": "Stage 1 BanSubstrings blocklist  ·  Stage 2 local toxicity classifier  ·  Stage 3 "
                   "Azure or a guard model on borderline input  ·  Offline promptfoo HarmBench / BeaverTails / XSTest",
        "conflict": "The cheat sheet named only LLM Guard + Azure; the recommendation slide named LLM Guard + "
                    "NeMo + Promptfoo. The union is correct - NeMo does the routing, Promptfoo does the CI corpus.",
    },
    "Hallucination / Reliability": {
        "adopt": ["llm-guard-main", "deepeval-main"],
        "engine": "LLM Guard's cross-encoder NLI FactualConsistency scanner - the only groundedness check in the "
                  "review cheap enough to run on every single response, with no judge-LLM call; DeepEval's "
                  "faithfulness and contextual precision/recall for the offline tier.",
        "cloud": "Azure AI Content Safety groundedness detection for regulated RAG; Patronus Lynx and Cleanlab "
                 "are both available as ready-made NeMo rails.",
        "cascade": "Stage 2 LLM Guard NLI on every RAG response  ·  Offline DeepEval, plus Giskard for its "
                   "sycophancy check (unique in the set)",
        "conflict": "The cheat sheet added Giskard to the runtime picture. Giskard v3 is LLM-judge based and "
                    "needs a paid API, so it belongs in CI only - keep it, but never inline.",
    },
    "Accountability": {
        "adopt": ["openguardrails-main", "PyRIT-main", "promptfoo-main"],
        "engine": "The OpenGuardrails GuardEvent/Verdict schema as AFNI's record shape - pin it, the protocol is "
                  "v0.8 and pre-1.0. PyRIT's memory store and its scorer_evaluation tooling with Krippendorff's "
                  "alpha give a measured detector accuracy rather than a vendor claim.",
        "cloud": "Azure Monitor and Application Insights for the production audit trail and OpenTelemetry "
                 "tracing. Monitaur or Fiddler only for a dedicated managed governance record store.",
        "cascade": "Stage 1 emit the verdict schema on every decision, live or offline  ·  Offline Promptfoo "
                   "generates the compliance pack from CI artefacts",
        "conflict": "REAL DISAGREEMENT, now settled: the cheat sheet named DeepTeam, the recommendation slide "
                    "named Promptfoo. Promptfoo wins - it maps 6 frameworks (OWASP LLM, NIST AI RMF, MITRE "
                    "ATLAS, EU AI Act, ISO 42001, GDPR) against DeepTeam's 5, and PyRIT ships no report "
                    "generator at all. DeepTeam stays as a secondary source of agentic findings.",
    },
}


def _card(tenet):
    for c in TENET_CARDS:
        if c["tenet"] == tenet:
            return c
    raise KeyError(tenet)


def add_tenet_merged_slide(prs, tenet, idx, total, finish_slide_fn):
    card = _card(tenet)
    entry = TENET_MATRIX[tenet]
    rec = RECONCILED[tenet]
    color = TENET_COLORS.get(tenet, TEAL)

    slide = blank_slide(prs)
    add_header(slide, f"Tenet {idx} of {total}", card["title"], accent=color)

    full_x, full_w = 0.55, 12.2

    # ---------------------------------------------- Row A: the two option sides
    y = 1.40
    row_a_h = 1.44
    lx, lw = full_x, 5.92
    rx, rw = full_x + 6.28, 5.92

    for x, w, label, name, text, accent in (
        (lx, lw, "OPEN-SOURCE", card["open_source_name"], card["open_source_text"], TEAL),
        (rx, rw, "CLOUD & PAID", card["cloud_name"], card["cloud_text"], NAVY),
    ):
        add_rect(slide, x, y, 0.07, row_a_h, accent)
        badge(slide, x + 0.18, y + 0.01, label, accent, w=1.62, h=0.24, size=8.5)
        add_text(slide, x + 0.18, y + 0.28, w - 0.24, 0.24, name, size=10.5, color=NAVY, bold=True,
                 font=FONT_HEAD)
        add_text(slide, x + 0.18, y + 0.53, w - 0.24, row_a_h - 0.56, text, size=8.2, color=TEXT_DARK,
                 font=FONT_BODY, line_spacing=1.08)

    # ------------------------------- Row B: every open-source option of the 23
    y += row_a_h + 0.10
    add_text(slide, full_x, y, 4.2, 0.20, f"ALL OPTIONS FOUND (of the 23 reviewed)", size=8,
             color=TEXT_MUTED, bold=True, font=FONT_HEAD)
    px, py = full_x, y + 0.22
    max_x = full_x + full_w
    for repo in entry["open_source_repos"]:
        label = short(repo)
        w = 0.12 + 0.055 * len(label) + 0.10
        if px + w > max_x:
            px = full_x
            py += 0.25
        pill(slide, px, py, label, color, w=w, size=7.5)
        px += w + 0.06
    y = py + 0.34

    # -------------------------------------- Row C: the reconciled recommendation
    rec_h = 1.66
    add_rounded(slide, full_x, y, full_w, rec_h, CARD_BG, radius=0.05, line=True)
    add_rect(slide, full_x, y, 0.07, rec_h, GREEN)
    badge(slide, full_x + 0.18, y + 0.03, "AFNI RECOMMENDATION", GREEN, w=2.5, h=0.25, size=8.7)

    bx = full_x + 2.82
    add_text(slide, bx, y + 0.05, 1.0, 0.2, "ADOPT", size=7.5, color=TEXT_MUTED, bold=True, font=FONT_HEAD)
    bx += 0.72
    for repo in rec["adopt"]:
        label = short(repo)
        w = 0.16 + 0.072 * len(label) + 0.12
        badge(slide, bx, y + 0.01, label, GREEN, w=w, h=0.27, size=9)
        bx += w + 0.09

    ty = y + 0.33
    for lbl, txt, col in (("ENGINE UNDER IT", rec["engine"], TEXT_DARK),
                          ("CLOUD SECOND OPINION", rec["cloud"], TEXT_DARK)):
        add_text(slide, full_x + 0.20, ty, 1.62, 0.18, lbl, size=7, color=TEAL, bold=True, font=FONT_HEAD)
        add_text(slide, full_x + 1.90, ty - 0.01, full_w - 2.12, 0.42, txt, size=7.8, color=col,
                 font=FONT_BODY, line_spacing=1.05)
        ty += 0.45
    add_text(slide, full_x + 0.20, ty, 1.62, 0.18, "WHERE IT RUNS", size=7, color=TEAL, bold=True,
             font=FONT_HEAD)
    add_text(slide, full_x + 1.90, ty - 0.01, full_w - 2.12, 0.30, rec["cascade"], size=7.8,
             color=NAVY, bold=True, font=FONT_BODY, line_spacing=1.05)
    y += rec_h + 0.09

    # -------------------------------------------- Row D: the reconciliation note
    note_h = 0.52
    add_rounded(slide, full_x, y, full_w, note_h, RGB_NOTE, radius=0.04)
    add_text(slide, full_x + 0.18, y + 0.03, 1.9, 0.2, "RECONCILED", size=7, color=AMBER, bold=True,
             font=FONT_HEAD)
    add_text(slide, full_x + 1.90, y + 0.02, full_w - 2.12, note_h - 0.05, rec["conflict"], size=7.6,
             color=TEXT_DARK, font=FONT_BODY, line_spacing=1.05)
    y += note_h + 0.09

    # ------------------------------------------------- Row E: principle footer
    band_h = min(0.46, 7.06 - y)
    if band_h > 0.2:
        add_rounded(slide, full_x, y, full_w, band_h, NAVY, radius=0.10)
        add_text(slide, full_x + 0.25, y, full_w - 0.5, band_h, card["principle"], size=9,
                 color=WHITE, bold=True, italic=True, anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.CENTER,
                 font=FONT_BODY, line_spacing=1.05)

    # Everything that no longer fits on the slide goes to the notes pane rather
    # than being dropped: the long rationale, the full cloud list, and Sai's
    # prior-experience note that the old recommendation slide carried on-slide.
    notes = slide.notes_slide
    notes.notes_text_frame.text = (
        f"WHY THIS COMBINATION\n{entry['combination_rationale']}\n\n"
        f"FULL CLOUD / PAID OPTIONS\n"
        + "\n".join(f"- {c}" for c in entry["cloud_paid_options"])
        + f"\n\nSAI'S PRIOR EXPERIENCE\n{entry.get('afni_prior_experience_note', '(none recorded)')}"
        + f"\n\nRECONCILIATION\n{rec['conflict']}"
    )

    finish_slide_fn(slide, f"Tenet - {tenet}")


def add_all_tenet_merged_slides(prs, finish_slide_fn):
    total = len(RECONCILED)
    for i, tenet in enumerate(RECONCILED.keys(), start=1):
        add_tenet_merged_slide(prs, tenet, i, total, finish_slide_fn)
