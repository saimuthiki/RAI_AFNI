# -*- coding: utf-8 -*-
"""Detailed request-flow flowchart + Infosys-vs-NeMo comparison slides."""
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

from build_pptx import (
    blank_slide, add_rect, add_rounded, add_text, add_bullets, add_header,
    badge, flow_box, flow_arrow, add_line, add_arrowhead,
    NAVY, TEAL, BG_LIGHT, CARD_BG, WHITE, TEXT_DARK, TEXT_MUTED,
    TEXT_SOFT_ON_NAVY, AMBER, GREEN, RED_SOFT, LINE_GREY,
    FONT_HEAD, FONT_BODY,
)


# ===================================================== DETAILED FLOWCHART
def add_request_flow_slide(prs, finish_slide_fn):
    slide = blank_slide(prs)
    add_header(slide, "How It Actually Works", "Step by Step: One Request, Start to Finish", accent=TEAL)

    # ---- Row 1: main pipeline ----
    y1, h1 = 1.6, 0.7
    cy1 = y1 + h1 / 2
    request = flow_box(slide, 0.35, y1, 1.05, h1, "Request")
    input_rails = flow_box(slide, 1.58, y1, 1.75, h1, "Input Rails", "PII · secrets · injection · unicode")
    d1_x, d1_w, d1_h = 3.51, 1.2, 0.95
    d1_y = cy1 - d1_h / 2
    diamond1 = flow_box(slide, d1_x, d1_y, d1_w, d1_h, "Block, escalate,\nor clear?", size=9.5,
                        fill=BG_LIGHT, shape=MSO_SHAPE.DIAMOND)
    model = flow_box(slide, 4.89, y1, 1.15, h1, "Model Call")
    output_rails = flow_box(slide, 6.22, y1, 1.9, h1, "Output Rails", "toxicity · groundedness · PII · schema")
    d2_x, d2_w, d2_h = 8.30, 1.2, 0.95
    d2_y = cy1 - d2_h / 2
    diamond2 = flow_box(slide, d2_x, d2_y, d2_w, d2_h, "All clear?", size=10,
                        fill=BG_LIGHT, shape=MSO_SHAPE.DIAMOND)
    deliver = flow_box(slide, 9.68, y1, 1.5, h1, "Deliver Response", "to user / app",
                       fill=NAVY, text_color=WHITE)

    flow_arrow(slide, 1.40, cy1, 1.56, cy1)
    flow_arrow(slide, 3.33, cy1, 3.49, cy1)
    flow_arrow(slide, 4.71, cy1, 4.87, cy1, label="clear", color=TEAL)
    flow_arrow(slide, 6.04, cy1, 6.20, cy1)
    flow_arrow(slide, 8.12, cy1, 8.28, cy1)
    flow_arrow(slide, 9.50, cy1, 9.66, cy1, label="safe", color=GREEN)

    # ---- Row 2: input-side branches ----
    y2, h2 = 2.62, 0.58
    block1 = flow_box(slide, 2.35, y2, 1.65, h2, "BLOCK & Refuse", size=9.5, fill=RED_SOFT, text_color=WHITE)
    cloud = flow_box(slide, 4.30, y2, 1.75, h2, "Cloud 2nd Opinion", "Azure / vendor", size=9.5)
    flow_arrow(slide, d1_x + 0.15, d1_y + d1_h, block1.left / 914400 + 0.35, y2, label="block", color=RED_SOFT)
    flow_arrow(slide, d1_x + d1_w - 0.15, d1_y + d1_h, cloud.left / 914400 + 0.6, y2, label="borderline", color=AMBER)
    flow_arrow(slide, cloud.left / 914400 + 1.5, y2, model.left / 914400 + 0.7, y1 + h1, color=TEAL)

    # ---- Row 3: mitigation chips (fed by diamond 2 "not safe") ----
    bus_y = 3.42
    chip_y, chip_h = 3.62, 0.62
    chips = [
        (5.70, 1.55, "Toxic\n→ Block / Refuse", RED_SOFT),
        (7.45, 1.85, "PII Leak\n→ Mask & Continue", AMBER),
        (9.50, 1.95, "Not Grounded\n→ Flag / Regenerate", AMBER),
        (11.65, 1.2, "Bad Tool Call\n→ Block", RED_SOFT),
    ]
    chip_shapes = []
    for cx, cw, label, fill in chips:
        shp = flow_box(slide, cx, chip_y, cw, chip_h, label, size=9, fill=fill, text_color=WHITE, bold=False)
        chip_shapes.append((cx + cw / 2, shp))

    d2_bottom_x = d2_x + d2_w / 2
    add_line(slide, d2_bottom_x, d2_y + d2_h, d2_bottom_x, bus_y, color=AMBER)
    add_line(slide, chip_shapes[0][0], bus_y, chip_shapes[-1][0], bus_y, color=AMBER)
    add_text(slide, d2_bottom_x - 0.55, bus_y - 0.32, 1.3, 0.2, "not safe", size=8.5, color=AMBER,
              align=PP_ALIGN.CENTER, font=FONT_BODY)
    for cx_mid, shp in chip_shapes:
        flow_arrow(slide, cx_mid, bus_y, cx_mid, chip_y, color=AMBER, width=1.2)

    # ---- Row 4: audit store ----
    audit_y = 4.42
    audit = flow_box(slide, 2.9, audit_y, 9.6, 0.55, "AUDIT STORE — every verdict, one schema",
                     "findings · severity · score · redaction spans · OpenTelemetry trace",
                     fill=NAVY, text_color=WHITE, size=11, sub_size=8.5)
    for cx, cw, label, fill in [(2.35, 1.65, "", RED_SOFT)] + chips:
        cx_mid = cx + cw / 2
        add_line(slide, cx_mid, chip_y + chip_h, cx_mid, audit_y, color=TEXT_MUTED, width=1)
        add_arrowhead(slide, cx_mid, audit_y, "down", color=TEXT_MUTED, size=0.07)

    add_text(slide, 9.68, y1 + h1 + 0.06, 1.5, 0.3, "(delivered responses\nare logged too)", size=7.8,
              color=TEXT_MUTED, italic=True, align=PP_ALIGN.CENTER, font=FONT_BODY, line_spacing=0.95)

    # ---- Row 5: offline red-team loop ----
    off_y = 5.35
    offline = flow_box(slide, 2.9, off_y, 9.6, 0.55, "OFFLINE, CONTINUOUS: Red-Team & Eval CI",
                       "PyRIT · garak · promptfoo · DeepTeam - runs on every rail, prompt, or model change",
                       fill=RED_SOFT, text_color=WHITE, size=11, sub_size=8.5)
    audit_cx = 2.9 + 9.6 / 2
    flow_arrow(slide, audit_cx, off_y, audit_cx, audit_y + 0.55, label="every finding", color=RED_SOFT)
    flow_arrow(slide, 4.5, off_y, 2.4, y2 + h2, dashed=True, color=TEAL, label="hardens rails")

    add_text(slide, 0.35, 6.15, 12.4, 0.75,
              "Solid arrows = live request path (every millisecond counts). Dashed arrow = offline feedback: "
              "confirmed red-team failures raise thresholds and add new rails before the next release. "
              "Two rules never bend: the gateway fails closed on client-facing traffic, and a check that could "
              "not run is reported as unjudged, never silently passed.",
              size=10.3, color=TEXT_MUTED, font=FONT_BODY, line_spacing=1.15)

    finish_slide_fn(slide, "Request Flow")


# ============================================== INFOSYS VS NEMO DIAGRAM
def add_infosys_vs_nemo_diagram_slide(prs, finish_slide_fn):
    slide = blank_slide(prs)
    add_header(slide, "Current Shape vs. Recommended Backbone", "Infosys Toolkit vs. NeMo Guardrails", accent=NAVY)

    lx, lw = 0.4, 5.85
    rx, rw = 6.55, 5.85

    add_rounded(slide, lx, 1.5, lw, 0.46, RED_SOFT, radius=0.18)
    add_text(slide, lx, 1.5, lw, 0.46, "INFOSYS TOOLKIT — right shape, wrong build", size=12, color=WHITE,
              bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, font=FONT_HEAD)
    add_rounded(slide, rx, 1.5, rw, 0.46, TEAL, radius=0.18)
    add_text(slide, rx, 1.5, rw, 0.46, "NEMO GUARDRAILS — recommended backbone", size=12, color=WHITE,
              bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, font=FONT_HEAD)

    # mini diagrams
    my = 2.15
    l1 = flow_box(slide, lx, my, 1.75, 0.62, "1 Dispatcher", size=9.5)
    l2 = flow_box(slide, lx + 2.0, my, 1.85, 0.62, "~15 Checks", "fanned out, own thresholds", size=9)
    l3 = flow_box(slide, lx + 4.0, my, 1.85, 0.62, "1 Pass/Fail", "+ per-check evidence", size=9)
    flow_arrow(slide, lx + 1.75, my + 0.31, lx + 1.98, my + 0.31, width=1.2)
    flow_arrow(slide, lx + 3.85, my + 0.31, lx + 4.0 - 0.02, my + 0.31, width=1.2)

    r1 = flow_box(slide, rx, my, 1.75, 0.62, "pip install", "1 package, not a mesh", size=9)
    r2 = flow_box(slide, rx + 2.0, my, 1.85, 0.62, "Plugin Rails", "actions + config + manifest", size=9)
    r3 = flow_box(slide, rx + 4.0, my, 1.85, 0.62, "~20 Adapters", "vendors + Azure", size=9)
    flow_arrow(slide, rx + 1.75, my + 0.31, rx + 1.98, my + 0.31, color=TEAL, width=1.2)
    flow_arrow(slide, rx + 3.85, my + 0.31, rx + 4.0 - 0.02, my + 0.31, color=TEAL, width=1.2)

    add_text(slide, lx, 3.0, lw, 0.25, "DRAWBACKS FOUND IN THE CODE", size=10.5, color=RED_SOFT, bold=True,
              font=FONT_HEAD)
    add_bullets(slide, lx, 3.3, lw, 3.1, [
        "Deploying it as designed means standing up about 20 independently-versioned FastAPI microservices plus an Angular front end, each with its own model weights",
        "Red-team modules are marked retired for release 2.2.1; the front end still ships orphaned red-teaming screens pointing at nothing",
        "No accuracy numbers exist anywhere for its in-house fine-tuned models",
        "The core dispatcher wraps each check in a broad try/except that logs and returns None - one timeout silently drops a check instead of failing loudly",
        "Every one of the ~20 services must be configured with every other service's URL",
    ], size=10.3, bullet_color=RED_SOFT, space_after=9, line_spacing=1.08)

    add_text(slide, rx, 3.0, rw, 0.25, "WHY IT WINS AS THE BACKBONE", size=10.5, color=TEAL, bold=True,
              font=FONT_HEAD)
    add_bullets(slide, rx, 3.3, rw, 3.1, [
        "One pip-installable Python package, not a service mesh to operate",
        "Already a plugin architecture: every rail is a self-contained module (an actions file, a config schema, a manifest) - AFNI's own detectors plug in as first-class rails",
        "Ships ready adapters for about 20 managed safety vendors plus Azure services, so AFNI stays Azure-first without being locked in",
        "NVIDIA-maintained with a 383-file test suite, and it publishes honest numbers about its own weak spots instead of hiding them",
    ], size=10.3, bullet_color=TEAL, space_after=9, line_spacing=1.08)

    add_rounded(slide, 0.4, 6.55, 12.0, 0.55, NAVY, radius=0.1)
    add_text(slide, 0.55, 6.55, 3.1, 0.55, "CARRY OVER FROM INFOSYS:", size=10, color=TEAL, bold=True,
              anchor=MSO_ANCHOR.MIDDLE, font=FONT_HEAD)
    for i, label in enumerate(["Per-tenant threshold service", "One consolidated verdict", "Fail-loud, fails-closed policy"]):
        badge(slide, 3.75 + i * 2.95, 6.68, label, TEAL, w=2.75, h=0.3, size=9.5)

    finish_slide_fn(slide, "Infosys vs NeMo")


# ============================================== 4-QUADRANT BULLET DETAIL
def add_infosys_vs_nemo_bullets_slide(prs, finish_slide_fn):
    slide = blank_slide(prs)
    add_header(slide, "In Detail", "What To Keep, What To Drop, What To Build", accent=NAVY)

    quads = [
        (0.4, 1.5, "WHAT INFOSYS HAS TODAY", NAVY, [
            "One async dispatcher (moderationlayer) fans a single input out to roughly 15 independently-thresholded checks",
            "Returns one pass/fail summary with per-check evidence, in both coupled and decoupled modes",
            "Thresholds are configured per account and per portfolio through a separate admin service",
            "Locally-hosted fine-tuned models for toxicity, jailbreak, restricted topics, and gibberish - no per-call cloud cost",
        ]),
        (6.75, 1.5, "DRAWBACKS FOUND", RED_SOFT, [
            "Full adoption means ~20 FastAPI microservices plus an Angular front end, each with its own requirements file and several GB of model weights",
            "Red-team (PAIR/TAP) modules are retired for 2.2.1; the frontend still ships orphaned red-team screens with no backend behind them",
            "No published accuracy figures for any in-house fine-tuned model",
            "Broad try/except blocks log and return None on failure - a single bad threshold or timeout silently drops a check",
        ]),
        (0.4, 4.15, "WHAT NEMO GUARDRAILS BRINGS", TEAL, [
            "A single pip-installable Python package - no service mesh, no per-service URL wiring",
            "A genuine plugin architecture: each rail is a self-contained module (actions file, config schema, manifest)",
            "Roughly 20 ready adapters to managed safety vendors, plus native Azure service adapters",
            "NVIDIA maintains it, backed by a 383-file test suite, and publishes its own weakness numbers honestly",
        ]),
        (6.75, 4.15, "WHAT AFNI MUST BUILD ITSELF", AMBER, [
            "A per-tenant and per-project threshold configuration service, modelled on Infosys's admin pattern",
            "One consolidated verdict summary per request - not a raw list of individual rail outputs",
            "A loud-failure policy: any check that could not complete is reported as unjudged, and for client-facing traffic the gateway fails closed",
            "The OpenGuardrails Verdict/GuardEvent schema as the fixed contract between the gateway and every app",
        ]),
    ]
    for x, y, title, color, items in quads:
        add_rect(slide, x, y, 5.85, 0.05, color)
        add_text(slide, x, y + 0.12, 5.85, 0.28, title, size=12, color=color, bold=True, font=FONT_HEAD)
        add_bullets(slide, x, y + 0.48, 5.85, 2.15, items, size=10.2, bullet_color=color, space_after=7,
                    line_spacing=1.05)

    finish_slide_fn(slide, "Infosys vs NeMo - Detail")