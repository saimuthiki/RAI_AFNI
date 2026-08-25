# -*- coding: utf-8 -*-
"""Synthesis-driven slides: master checklist, tenet recommendations, dev vs
testing split, feasibility matrix, unified architecture, roadmap, closing."""
import textwrap
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

from build_pptx import (
    blank_slide, add_rect, add_rounded, add_text, add_bullets,
    add_header, pill, badge, add_table,
    NAVY, TEAL, BG_LIGHT, CARD_BG, WHITE, TEXT_DARK, TEXT_MUTED,
    TEXT_SOFT_ON_NAVY, AMBER, GREEN, RED_SOFT, LINE_GREY, TENET_COLORS,
    TENET_ORDER, ROLE_COLORS, FONT_HEAD, FONT_BODY, SLIDE_W_IN, SLIDE_H_IN,
)

SHORT_NAME = {
    "agentic_security-main": "Agentic Security", "AIF360-main": "AIF360",
    "deepchecks-main": "Deepchecks", "deepeval-main": "DeepEval",
    "deepteam-main": "DeepTeam", "evals-main": "OpenAI Evals",
    "fairlearn-main": "Fairlearn", "FuzzyAI-main": "FuzzyAI",
    "garak-main": "garak", "giskard-oss-main": "Giskard",
    "Guardrails-develop": "NeMo Guardrails", "guardrails-main": "Guardrails AI",
    "hai-guardrails-main": "hai-guardrails", "Infosys-Responsible-AI-Toolkit-master": "Infosys RAI Toolkit",
    "JCB-main": "JCB", "LLMFuzzer-main": "LLMFuzzer", "llm-guard-main": "LLM Guard",
    "openguardrails-main": "OpenGuardrails (OGR)", "promptfoo-main": "Promptfoo",
    "PyRIT-main": "PyRIT", "rebuff-main": "Rebuff", "safe-zone-main": "Safe Zone (TSZ)",
    "shap-master": "SHAP",
}


def short(folder):
    return SHORT_NAME.get(folder, folder)


def wrap_note(text, width=95):
    return "\n".join(textwrap.wrap(text, width=width))


# ---------------------------------------------------- CHECKLIST SLIDES ----
def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rsplit(" ", 1)[0] + "…"


def add_checklist_slide(prs, tenet, items, page_no_fn, finish_slide_fn):
    slide = blank_slide(prs)
    color = TENET_COLORS[tenet]
    add_header(slide, "Master Checklist", tenet, accent=color)
    add_text(slide, 0.6, 1.42, 11.8, 0.32,
              f"{len(items)} concrete checks found across the 23 tools for this tenet - the "
              "number in brackets is how many tools provide it.",
              size=11.5, color=TEXT_MUTED, font=FONT_BODY)

    n = len(items)
    cols = 3 if n > 14 else 2
    col_w = 11.9 / cols
    rows_per_col = -(-n // cols)
    y0 = 1.95
    max_h = 4.95
    row_h = min(0.36, max_h / max(rows_per_col, 1))
    text_w_in = col_w - 0.35
    avg_char_w = (9.3 / 72) * 0.52
    line_h = (9.3 / 72) * 1.05
    max_lines = max(1, int(row_h / line_h))
    chars_per_line = max(10, int(text_w_in / avg_char_w))
    max_chars = chars_per_line * max_lines - 6  # leave room for " (n)"
    for i, item in enumerate(items):
        col = i // rows_per_col
        row = i % rows_per_col
        x = 0.55 + col * col_w
        y = y0 + row * row_h
        n_src = len(item.get("source_repos", []))
        aspect_text = _truncate(item["aspect"], max_chars)
        add_rect(slide, x, y + row_h * 0.32, 0.09, 0.09, color)
        add_text(slide, x + 0.18, y, col_w - 0.35, row_h, f"{aspect_text}  ({n_src})",
                  size=9.3, color=TEXT_DARK, font=FONT_BODY, line_spacing=0.95, wrap=True)
    finish_slide_fn(slide, f"Checklist - {tenet}")


def add_all_checklists(prs, master_aspect_list, finish_slide_fn):
    by_tenet = {t: [] for t in TENET_ORDER}
    for item in master_aspect_list:
        t = item.get("tenet")
        if t in by_tenet:
            by_tenet[t].append(item)
        else:
            by_tenet.setdefault(t, []).append(item)
    for tenet in TENET_ORDER:
        items = by_tenet.get(tenet, [])
        if items:
            add_checklist_slide(prs, tenet, items, None, finish_slide_fn)


# ------------------------------------------------ TENET RECOMMENDATION ----
def add_tenet_recommendation_slide(prs, entry, finish_slide_fn):
    tenet = entry["tenet"]
    color = TENET_COLORS[tenet]
    slide = blank_slide(prs)
    add_header(slide, "Tenet Recommendation", tenet, accent=color)

    full_x, full_w = 0.55, 12.1
    left_x, left_w = 0.55, 5.85
    right_x, right_w = 6.55, 6.1

    # Row A: open-source pills (left) + cloud/paid bullets (right)
    row_a_y = 1.45
    add_text(slide, left_x, row_a_y, left_w, 0.22, "OPEN-SOURCE OPTIONS (of the 23 reviewed)", size=9.5,
              color=TEAL, bold=True, font=FONT_HEAD)
    os_repos = entry["open_source_repos"]
    shown = os_repos[:10]
    extra = len(os_repos) - len(shown)
    x, y, row_h = left_x, row_a_y + 0.26, 0.28
    max_x = left_x + left_w
    max_rows = 2
    row_idx = 0
    for repo in shown:
        label = short(repo)
        w = 0.14 + 0.062 * len(label) + 0.12
        if x + w > max_x:
            x = left_x
            row_idx += 1
            y += row_h
            if row_idx >= max_rows:
                break
        pill(slide, x, y, label, color, w=w, size=8.2)
        x += w + 0.07
    if extra > 0:
        add_text(slide, left_x, y + row_h + 0.02, left_w, 0.2, f"+ {extra} more", size=8.5,
                  color=TEXT_MUTED, italic=True, font=FONT_BODY)

    add_text(slide, right_x, row_a_y, right_w, 0.22, "CLOUD / PAID OPTIONS", size=9.5, color=NAVY,
              bold=True, font=FONT_HEAD)
    cloud_items = [_truncate(c, 92) for c in entry["cloud_paid_options"][:5]]
    add_bullets(slide, right_x, row_a_y + 0.26, right_w, 0.95, cloud_items, size=8.8, bullet_color=NAVY,
                space_after=2, line_spacing=0.98)

    # Row B: recommended combination badges
    row_b_y = row_a_y + 1.22
    add_text(slide, full_x, row_b_y, 3.0, 0.24, "AFNI RECOMMENDATION:", size=10, color=GREEN, bold=True,
              font=FONT_HEAD)
    xb = full_x + 2.35
    for repo in entry["recommended_combination"]:
        label = short(repo)
        w = 0.18 + 0.082 * len(label) + 0.14
        badge(slide, xb, row_b_y - 0.03, label, GREEN, w=w, h=0.32, size=10)
        xb += w + 0.1

    # Row C: rationale, full width
    row_c_y = row_b_y + 0.44
    add_text(slide, full_x, row_c_y, full_w, 0.2, "WHY THIS COMBINATION", size=9.5, color=TEXT_MUTED,
              bold=True, font=FONT_HEAD)
    rationale_h = 2.95
    add_text(slide, full_x, row_c_y + 0.24, full_w, rationale_h, entry["combination_rationale"],
              size=10.3, color=TEXT_DARK, font=FONT_BODY, line_spacing=1.08)

    # Row D: prior experience, full width
    prior = entry.get("afni_prior_experience_note", "")
    if prior:
        row_d_y = row_c_y + 0.24 + rationale_h + 0.08
        row_d_h = max(0.5, 7.08 - row_d_y)
        add_rounded(slide, full_x, row_d_y, full_w, row_d_h, NAVY, radius=0.04)
        add_text(slide, full_x + 0.15, row_d_y + 0.06, 2.6, row_d_h - 0.1, "SAI'S PRIOR EXPERIENCE",
                  size=8.7, color=TEAL, bold=True, font=FONT_HEAD, line_spacing=1.0)
        add_text(slide, full_x + 2.85, row_d_y + 0.06, full_w - 3.0, row_d_h - 0.1,
                  _truncate(prior, 430), size=8.9, color=WHITE, font=FONT_BODY, line_spacing=1.05)

    notes = slide.notes_slide
    notes.notes_text_frame.text = (
        f"Full cloud/paid options:\n" + "\n".join(f"- {c}" for c in entry["cloud_paid_options"])
        + f"\n\nFull prior-experience note:\n{prior}"
    )

    finish_slide_fn(slide, f"Recommendation - {tenet}")


# ------------------------------------------------------- DEV VS TESTING ----
def add_dev_vs_testing_slide(prs, split, finish_slide_fn):
    slide = blank_slide(prs)
    add_header(slide, "Two Halves, One Loop", "Guardrail Development vs. Vulnerability Testing - By Tool", accent=RED_SOFT)

    col_w = 3.75
    xs = [0.55, 4.5, 8.45]
    titles = [
        ("DEVELOPMENT", split["guardrail_development_repos"], TEAL),
        ("TESTING", split["vulnerability_testing_repos"], RED_SOFT),
        ("BOTH", split["both_repos"], NAVY),
    ]
    for x, (label, repos, color) in zip(xs, titles):
        add_rounded(slide, x, 1.48, col_w, 0.36, color, radius=0.2)
        add_text(slide, x, 1.48, col_w, 0.36, f"{label}  ({len(repos)})", size=11, color=WHITE, bold=True,
                  align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, font=FONT_HEAD)
        add_bullets(slide, x, 1.96, col_w, 2.15, [short(r) for r in repos], size=9.8, bullet_color=color,
                    space_after=4, line_spacing=0.95)

    add_rect(slide, 0.55, 4.24, 12.1, 0.02, LINE_GREY)
    add_text(slide, 0.55, 4.38, 12.1, 0.22, "HOW THEY CONNECT", size=10.5, color=NAVY, bold=True, font=FONT_HEAD)
    add_text(slide, 0.55, 4.63, 12.1, 2.45, split["how_they_connect"], size=9.3, color=TEXT_DARK,
              font=FONT_BODY, line_spacing=1.08)
    finish_slide_fn(slide, "Development vs Testing")


# --------------------------------------------------------- FEASIBILITY ----
VERDICT_COLORS = {
    "Adopt now": GREEN, "Combine": TEAL, "Bench for later": AMBER, "Skip": RED_SOFT,
}


def verdict_color(v):
    for k, c in VERDICT_COLORS.items():
        if v.lower().startswith(k.lower()) or k.lower() in v.lower():
            return c
    return TEXT_MUTED


def add_feasibility_slides(prs, feasibility_matrix, finish_slide_fn):
    chunks = [feasibility_matrix[:12], feasibility_matrix[12:]]
    for ci, chunk in enumerate(chunks, start=1):
        slide = blank_slide(prs)
        add_header(slide, "Feasibility Check", f"Can We Integrate It? ({ci} of {len(chunks)})", accent=NAVY)
        headers = ["Tool", "Effort", "Cost", "Reliability", "Maintenance", "Verdict"]
        rows = []
        for e in chunk:
            rows.append([
                short(e["repo_folder"]), e["integration_effort"], e["cost_model"].replace(" (free core + optional paid add-ons)", ""),
                e["reliability_confidence"], e["maintenance_burden"], e["verdict"],
            ])
        add_table(slide, 0.55, 1.55, 12.2, 5.4, headers, rows,
                  col_widths=[2.0, 1.0, 2.0, 1.1, 1.1, 1.8], font_size=10, header_h=0.38, row_h=0.42)
        finish_slide_fn(slide, "Feasibility Check")


# -------------------------------------------------------- ARCHITECTURE ----
def add_architecture_narrative_slide(prs, ua, finish_slide_fn):
    slide = blank_slide(prs)
    add_header(slide, "The Unified Design", "One Gateway, One Contract, Two Loops", accent=TEAL)
    add_text(slide, 0.55, 1.5, 12.2, 4.3, ua["narrative"], size=12.3, color=TEXT_DARK, font=FONT_BODY,
              line_spacing=1.22)
    add_rect(slide, 0.55, 6.0, 12.2, 0.02, LINE_GREY)
    add_text(slide, 0.55, 6.15, 12.2, 0.25, "WHY INFOSYS TOOLKIT AS THE STARTING SHAPE", size=10.5,
              color=NAVY, bold=True, font=FONT_HEAD)
    add_text(slide, 0.55, 6.42, 12.2, 0.65,
              "The Infosys toolkit's one-dispatcher, per-tenant threshold pattern is the right shape to copy - "
              "but NeMo Guardrails is the recommended engine to actually build it on (see next slide).",
              size=10.5, color=TEXT_MUTED, font=FONT_BODY, line_spacing=1.1)
    finish_slide_fn(slide, "Unified Architecture")


def add_architecture_orchestration_slide(prs, ua, finish_slide_fn):
    slide = blank_slide(prs)
    add_header(slide, "The Unified Design", "Why NeMo Guardrails as the Backbone", accent=TEAL)
    add_text(slide, 0.55, 1.5, 12.2, 5.4, ua["orchestration_note"], size=11.6, color=TEXT_DARK,
              font=FONT_BODY, line_spacing=1.2)
    finish_slide_fn(slide, "Orchestration Design")


def add_architecture_stack_slides(prs, ua, finish_slide_fn):
    stacks = ua["per_tenet_stack"]
    chunks = [stacks[i:i + 2] for i in range(0, len(stacks), 2)]
    for ci, chunk in enumerate(chunks, start=1):
        slide = blank_slide(prs)
        add_header(slide, "The Unified Design", f"Per-Tenet Stack ({ci} of {len(chunks)})", accent=TEAL)
        y = 1.5
        h = 2.65
        for s in chunk:
            color = TENET_COLORS.get(s["tenet"], TEAL)
            add_rect(slide, 0.55, y, 0.09, h, color)
            add_text(slide, 0.78, y, 4.5, 0.3, s["tenet"], size=14, color=NAVY, bold=True, font=FONT_HEAD)
            add_text(slide, 0.78, y + 0.36, 11.9, 0.5, s["one_line"], size=10.8, color=TEXT_MUTED,
                      italic=True, font=FONT_BODY, line_spacing=1.05)
            stack_text = "   →   ".join(s["stack"])
            add_text(slide, 0.78, y + 0.9, 11.9, h - 0.98, stack_text, size=10.3, color=TEXT_DARK,
                      font=FONT_BODY, line_spacing=1.22, wrap=True)
            y += h + 0.15
        finish_slide_fn(slide, "Per-Tenet Stack")


# --------------------------------------------------------------ROADMAP ----
def add_roadmap_overview_slide(prs, roadmap_phases, finish_slide_fn):
    slide = blank_slide(prs)
    add_header(slide, "Adoption Plan", "A 90-Day Phased Roadmap - Overview", accent=TEAL)
    col_w = 3.85
    xs = [0.55, 4.55, 8.55]
    colors = [TEAL, AMBER, GREEN]
    for x, phase, color in zip(xs, roadmap_phases, colors):
        add_rounded(slide, x, 1.55, col_w, 0.55, color, radius=0.15)
        add_text(slide, x, 1.55, col_w, 0.55, phase["phase"], size=13, color=WHITE, bold=True,
                  align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, font=FONT_HEAD)
        headline = _truncate(phase["actions"][0], 140)
        add_text(slide, x, 2.3, col_w, 1.0, headline, size=10.8, color=TEXT_DARK, italic=True,
                  font=FONT_BODY, line_spacing=1.15)
        add_text(slide, x, 3.4, col_w, 0.35, f"{len(phase['actions'])} concrete actions →", size=10.5,
                  color=color, bold=True, font=FONT_HEAD)
    add_rect(slide, 0.55, 4.1, 12.1, 0.02, LINE_GREY)
    add_text(slide, 0.55, 4.3, 12.1, 2.6,
              "Each phase is detailed on its own slide next. The plan front-loads free, deterministic "
              "checks and the shared gateway contract, adds model-based and cloud checks once the basics "
              "are calibrated on real traffic, and only takes on the heaviest red-team and drift-monitoring "
              "work once the runtime layer is stable - so cost and complexity ramp up only as trust in the "
              "earlier layers is proven.",
              size=12.5, color=TEXT_MUTED, font=FONT_BODY, line_spacing=1.25)
    finish_slide_fn(slide, "Roadmap Overview")


def add_roadmap_phase_slides(prs, roadmap_phases, finish_slide_fn):
    colors = [TEAL, AMBER, GREEN]
    for phase, color in zip(roadmap_phases, colors):
        slide = blank_slide(prs)
        add_header(slide, "Adoption Plan", phase["phase"], accent=color)
        actions = phase["actions"]
        mid = -(-len(actions) // 2)
        col1, col2 = actions[:mid], actions[mid:]
        add_bullets(slide, 0.55, 1.55, 5.85, 5.5, col1, size=11.5, bullet_color=color, space_after=14,
                    line_spacing=1.12)
        add_bullets(slide, 6.55, 1.55, 6.1, 5.5, col2, size=11.5, bullet_color=color, space_after=14,
                    line_spacing=1.12)
        finish_slide_fn(slide, phase["phase"])


# --------------------------------------------------------------CLOSING ----
def add_recommendation_slide(prs, narrative, finish_slide_fn):
    slide = blank_slide(prs, NAVY)
    add_rect(slide, 0, 0, SLIDE_W_IN, SLIDE_H_IN, NAVY)
    add_rect(slide, 0.9, 1.1, 0.6, 0.05, TEAL)
    add_text(slide, 0.9, 0.55, 11, 0.4, "THE BOTTOM LINE", size=14, color=TEAL, bold=True, font=FONT_HEAD)
    add_text(slide, 0.85, 1.3, 11.6, 0.8, "How AFNI Should Think About Cost, Accuracy, and Reliability",
              size=24, color=WHITE, bold=True, font=FONT_HEAD, line_spacing=1.1)
    add_text(slide, 0.9, 2.4, 11.5, 4.4, narrative, size=13.5, color=TEXT_SOFT_ON_NAVY, font=FONT_BODY,
              line_spacing=1.3)
    finish_slide_fn(slide, "Recommendation")


def add_next_steps_slide(prs, finish_slide_fn):
    slide = blank_slide(prs)
    add_header(slide, "Wrap-Up", "Next Steps")
    items = [
        "Walk through this deck with Kiran and agree the AFNI Responsible AI standard.",
        "Kick off Phase 1 of the roadmap: the gateway, the OpenGuardrails contract, and the LLM Guard fork.",
        "Get legal sign-off on the two flagged licensing/vendor-risk items (Deepchecks AGPL, promptfoo remote plugins).",
        "Yamini to schedule the follow-up session and send Kiran the acceptable-use document.",
        "Sai to complete the Azure AI-103 certification.",
    ]
    add_bullets(slide, 0.6, 1.7, 11.8, 4.5, items, size=15, space_after=18, line_spacing=1.2)
    finish_slide_fn(slide, "Next Steps")


# ---------------------------------------------------------------- MAIN ----
def add_synthesis_slides(prs, synthesis, slide_divider_fn, finish_slide_fn, next_page_fn):
    slide_divider_fn(prs, "Section", "The Master Checklist",
                      "Every concrete check found across all 23 tools, grouped by tenet - "
                      "the full inventory behind the recommendations that follow.")
    add_all_checklists(prs, synthesis["master_aspect_list"], finish_slide_fn)

    slide_divider_fn(prs, "Section", "Tenet-by-Tenet Recommendations",
                      "For each of the 7 tenets: the open-source options, the cloud options, "
                      "and AFNI's recommended combination - picked on merit, not forced into a fixed pattern.")

    from build_deck_tenetcards import add_all_tenet_cards
    add_all_tenet_cards(prs, finish_slide_fn)

    for entry in synthesis["tenet_matrix"]:
        add_tenet_recommendation_slide(prs, entry, finish_slide_fn)

    slide_divider_fn(prs, "Section", "Detailed Capability Matrix",
                      "Every specific control found across the frameworks reviewed - aspects on the rows, "
                      "tools on the columns - with a cost/efficiency best pick for every capability more "
                      "than one tool offers, one matrix per tenet.")
    from build_deck_matrix import add_all_capability_matrices
    add_all_capability_matrices(prs, finish_slide_fn)

    slide_divider_fn(prs, "Section", "How Each Tool Actually Works",
                      "Per tenet: every contributing repository, the mechanism behind its check - module, "
                      "keyword, classifier, NLI, LLM judge or cloud API - its cost and latency class, and "
                      "where it belongs in AFNI's free-first cascade.")
    from build_deck_methodology import add_all_methodology_slides
    add_all_methodology_slides(prs, finish_slide_fn)

    slide_divider_fn(prs, "Section", "Feasibility & Unified Architecture",
                      "Which tools to adopt, how they fit together, and the phased plan to get there.")
    add_dev_vs_testing_slide(prs, synthesis["dev_vs_testing_split"], finish_slide_fn)
    add_feasibility_slides(prs, synthesis["feasibility_matrix"], finish_slide_fn)
    add_architecture_narrative_slide(prs, synthesis["unified_architecture"], finish_slide_fn)

    from build_deck_flow import (
        add_request_flow_slide, add_infosys_vs_nemo_diagram_slide, add_infosys_vs_nemo_bullets_slide,
    )
    add_request_flow_slide(prs, finish_slide_fn)

    add_architecture_orchestration_slide(prs, synthesis["unified_architecture"], finish_slide_fn)
    add_infosys_vs_nemo_diagram_slide(prs, finish_slide_fn)
    add_infosys_vs_nemo_bullets_slide(prs, finish_slide_fn)
    add_architecture_stack_slides(prs, synthesis["unified_architecture"], finish_slide_fn)
    add_roadmap_overview_slide(prs, synthesis["roadmap_phases"], finish_slide_fn)
    add_roadmap_phase_slides(prs, synthesis["roadmap_phases"], finish_slide_fn)
    add_recommendation_slide(prs, synthesis["key_tradeoff_narrative"], finish_slide_fn)
    add_next_steps_slide(prs, finish_slide_fn)
