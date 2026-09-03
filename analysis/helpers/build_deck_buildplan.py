# -*- coding: utf-8 -*-
"""The build plan, unphased.

Replaces the four "Adoption Plan - A 90-Day Phased Roadmap" slides. AFNI decided
on 2026-09-03 to build the platform in one pass rather than across three 30-day
windows, so the calendar is gone from the deck as it is from the platform.

WHAT IS AND IS NOT CHANGED HERE

`data/RAI_Synthesis.json` -> `roadmap_phases` is left ALONE. It is the record of
what the source-level analysis concluded, and the analysis did conclude a phased
plan. Rewriting research output to match a later delivery decision would destroy
the audit trail. Instead this module reads those same 26 actions and regroups
them by the KIND OF WORK each one is, which is the arrangement that survives the
removal of dates.

The grouping is curated by (phase_index, action_index) rather than inferred from
the action text. Keyword matching over prose would silently reclassify an action
the moment somebody reworded it, and a build plan that quietly moves an item into
the wrong group is worse than one that fails loudly - so a missing or extra index
raises instead.

The grouping itself lives in `helpers/build_plan_data.py`, which the Atlas HTML
also reads, so the deck, the HTML and `knowledge/build-plan.md` cannot disagree
about what the plan is. This module only decides how it LOOKS on a slide.
"""
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

from build_pptx import (
    blank_slide, add_rect, add_rounded, add_text, add_bullets, add_header,
    TEAL, WHITE, TEXT_DARK, TEXT_MUTED, AMBER, GREEN, LINE_GREY,
    FONT_HEAD, FONT_BODY,
)

from build_plan_data import GROUP_META, GROUP_ORDER, _flatten

#: Colour is a RENDERER choice, so it lives here rather than in the shared data
#: module - the Atlas HTML uses a different palette for the same groups.
GROUP_COLOR = {
    "runtime": TEAL, "testing": GREEN, "measure": AMBER,
    "batch": AMBER, "govern": TEAL, "settled": TEXT_MUTED,
}

GROUPS = [(k, GROUP_META[k][0], GROUP_COLOR[k], GROUP_META[k][1])
          for k in GROUP_ORDER]


def add_build_plan_overview_slide(prs, roadmap_phases, finish_slide_fn):
    actions = _flatten(roadmap_phases)
    counts = {k: sum(1 for a in actions if a["group"] == k) for k, *_ in GROUPS}

    slide = blank_slide(prs)
    add_header(slide, "Build Plan", "One Pass, No Phases - Overview", accent=TEAL)

    add_text(slide, 0.55, 1.45, 12.1, 0.5,
             "AFNI builds the whole platform as one body of work. There is no 30 / 60 / 90-day "
             "rollout: every item below is in scope now, and the only ordering that matters is "
             "the runtime cost cascade, which is a per-request decision rather than a date.",
             size=12.5, color=TEXT_DARK, font=FONT_BODY, line_spacing=1.25)

    # Two rows of three cards.
    col_w, gap = 3.85, 0.2
    for i, (key, title, color, blurb) in enumerate(GROUPS):
        col, row = i % 3, i // 3
        x = 0.55 + col * (col_w + gap)
        y = 2.35 + row * 1.55
        add_rounded(slide, x, y, col_w, 0.5, color, radius=0.12)
        add_text(slide, x, y, col_w, 0.5, title, size=12, color=WHITE, bold=True,
                 align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, font=FONT_HEAD)
        add_text(slide, x, y + 0.58, col_w, 0.3,
                 f"{counts[key]} item{'s' if counts[key] != 1 else ''}",
                 size=10.5, color=color, bold=True, font=FONT_HEAD)
        add_text(slide, x, y + 0.88, col_w, 0.6, blurb,
                 size=10, color=TEXT_MUTED, italic=True, font=FONT_BODY, line_spacing=1.15)

    add_rect(slide, 0.55, 5.6, 12.1, 0.02, LINE_GREY)
    add_text(slide, 0.55, 5.78, 12.1, 1.2,
             "Same 26 actions the analysis produced, regrouped by the kind of work each one is. "
             "The source record in RAI_Synthesis.json is left as the analysis wrote it - what "
             "changed is the delivery decision, not the findings. Three actions have since been "
             "settled, superseded or partly withdrawn; they are shown with the reason rather "
             "than removed.",
             size=11.5, color=TEXT_MUTED, font=FONT_BODY, line_spacing=1.25)
    finish_slide_fn(slide, "Build Plan Overview")


def add_build_plan_group_slides(prs, roadmap_phases, finish_slide_fn):
    """One slide per group, two columns, with status notes called out."""
    actions = _flatten(roadmap_phases)
    for key, title, color, blurb in GROUPS:
        items = [a for a in actions if a["group"] == key]
        if not items:
            continue
        slide = blank_slide(prs)
        add_header(slide, "Build Plan", title, accent=color)
        add_text(slide, 0.55, 1.42, 12.1, 0.32, blurb,
                 size=11.5, color=TEXT_MUTED, italic=True, font=FONT_BODY)

        # A status note is a correction, so it is rendered as the action text
        # followed by the note - never instead of it.
        rendered = []
        for a in items:
            rendered.append(a["text"] if not a["note"]
                            else f"{a['text']}\n    -> {a['note']}")

        mid = -(-len(rendered) // 2)
        col1, col2 = rendered[:mid], rendered[mid:]
        add_bullets(slide, 0.55, 1.9, 5.85, 5.1, col1, size=10.5,
                    bullet_color=color, space_after=12, line_spacing=1.1)
        if col2:
            add_bullets(slide, 6.55, 1.9, 6.1, 5.1, col2, size=10.5,
                        bullet_color=color, space_after=12, line_spacing=1.1)
        finish_slide_fn(slide, f"Build Plan - {title}")


def add_all_build_plan_slides(prs, roadmap_phases, finish_slide_fn):
    add_build_plan_overview_slide(prs, roadmap_phases, finish_slide_fn)
    add_build_plan_group_slides(prs, roadmap_phases, finish_slide_fn)
