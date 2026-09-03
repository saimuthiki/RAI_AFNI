# -*- coding: utf-8 -*-
"""The build-plan grouping - the single source of truth for BOTH renderers.

`build_deck_buildplan.py` (PowerPoint) and `scripts/build_html.py` (the Guardrail
Atlas) both read this, so the deck and the HTML can never disagree about what the
plan is or how it is grouped. Deliberately free of any python-pptx import, so the
HTML path does not depend on a presentation library.

AFNI decided on 2026-09-03 to build the platform in one pass rather than across a
90-day, three-phase calendar. `data/RAI_Synthesis.json` -> `roadmap_phases` is
left ALONE: it records what the source-level analysis concluded, and the analysis
did conclude a phased plan. Rewriting research output to match a later delivery
decision would destroy the audit trail. This module reads those same 26 actions
and regroups them by the KIND OF WORK each one is.

The grouping is curated by (phase_index, action_index) rather than inferred from
the action text. Keyword matching over prose would silently reclassify an action
the moment somebody reworded it, and a plan that quietly moves an item into the
wrong group is worse than one that fails loudly - so a missing or extra index
raises instead.

Group order and wording match `knowledge/build-plan.md`.
"""

#: Colour is chosen by the RENDERER, not here - the deck and the HTML have
#: different palettes. This module carries only the key, the title and the blurb.
GROUP_ORDER = ["runtime", "testing", "measure", "batch", "govern", "settled"]

GROUP_META = {
    "runtime": ("The runtime gateway",
                "Everything that sits in a live request path. Ordered by cost, not by date."),
    "testing": ("Testing and CI",
                "Offline work. None of this is in a request path, and none of it can be."),
    "measure": ("Measurement",
                "The part nobody does. Without it every accuracy claim is a vendor's word."),
    "batch":   ("Fairness and explainability",
                "Scheduled batch jobs. One response is not a fairness measurement."),
    "govern":  ("Governance and accountability",
                "The half that is not code. One item here is the last real blocker."),
    "settled": ("Settled, superseded or conditional",
                "Kept visible rather than deleted, so a reader can see what changed and why."),
}

#: (phase_index, action_index) -> group key. Every one of the 26 actions from
#: `roadmap_phases` appears exactly once; `_flatten` asserts it.
GROUP_OF = {
    # ---- the runtime gateway -------------------------------------------------
    (0, 0): "runtime", (0, 1): "runtime", (0, 2): "runtime",
    (1, 0): "runtime", (1, 1): "runtime", (1, 2): "runtime", (1, 3): "runtime",
    # ---- testing and CI ------------------------------------------------------
    (0, 4): "testing", (0, 5): "testing",
    (1, 4): "testing", (1, 5): "testing",
    (2, 0): "testing", (2, 2): "testing",
    # ---- measurement ---------------------------------------------------------
    (2, 1): "measure", (2, 8): "measure",
    # ---- fairness and explainability (batch, never a request path) -----------
    (1, 6): "batch", (1, 7): "batch",
    # ---- governance ----------------------------------------------------------
    (0, 3): "govern", (1, 8): "govern", (2, 4): "govern", (2, 7): "govern",
    # ---- settled, superseded or conditional ---------------------------------
    (0, 6): "settled", (0, 7): "settled",
    (2, 3): "settled", (2, 5): "settled", (2, 6): "settled",
}


#: Notes attached to individual actions whose STATUS changed after the analysis.
#: Keyed the same way as GROUP_OF. These are corrections to the plan, and the
#: deck states them rather than quietly rendering a superseded action as live.
STATUS_NOTE = {
    (0, 6): "SETTLED 2026-09-02 - AFNI holds licences covering Apache-2.0, MIT and "
            "AGPL-3.0, and cleared external data transport. Deepchecks stays benched "
            "on a technical ground instead: it has no per-request API at all.",
    (0, 7): "PARTLY WITHDRAWN - the Guardrails AI PyPI compromise is real and stands. "
            "The 'hard-coded bearer token' in Agentic Security is NOT real: the string "
            "is a Bearer XXXXX placeholder in a config template. Claim withdrawn.",
    (2, 3): "SUPERSEDED 2026-09-03 - AFNI removed the tenant dimension. What is built "
            "instead is one global threshold store with an operator override layer and "
            "a read log that proves a configured threshold was consulted.",
}


#: Two actions refer to "Phase 1" INSIDE their own text, because the analysis
#: wrote them that way. `RAI_Synthesis.json` is the research record and is not
#: edited, so the substitution happens at DISPLAY time instead - otherwise a deck
#: whose heading says "no phases" would contain sentences that name one.
#:
#: These are the only two. A phrase that stops matching raises rather than
#: silently rendering the old wording, so this cannot rot into a no-op.
TEXT_FIXUPS = {
    (1, 3): [("seeding the signature store from the Phase 1 baseline findings",
              "seeding the signature store from the baseline red-team findings")],
    (1, 5): [("export every attack that succeeded in Phase 1",
              "export every attack that succeeded against the pilot application")],
}


def _apply_fixups(key, text):
    for old, new in TEXT_FIXUPS.get(key, ()):
        if old not in text:
            raise ValueError(
                f"action {key}: TEXT_FIXUPS expected {old!r} and did not find it. "
                f"RAI_Synthesis.json was reworded; update the fixup rather than "
                f"letting a phase reference render into an unphased plan.")
        text = text.replace(old, new)
    return text


def _flatten(roadmap_phases):
    """All 26 actions, tagged with their group. Raises if the mapping drifts."""
    seen, out = set(), []
    for pi, phase in enumerate(roadmap_phases):
        for ai, action in enumerate(phase["actions"]):
            key = (pi, ai)
            if key not in GROUP_OF:
                raise KeyError(
                    f"action {key} has no group in build_deck_buildplan.GROUP_OF. "
                    f"RAI_Synthesis.json grew an action; classify it rather than "
                    f"letting it vanish from the deck: {action[:90]!r}")
            seen.add(key)
            out.append({"key": key, "group": GROUP_OF[key],
                        "text": _apply_fixups(key, action),
                        "note": STATUS_NOTE.get(key)})
    extra = set(GROUP_OF) - seen
    if extra:
        raise KeyError(f"GROUP_OF classifies actions that no longer exist: {sorted(extra)}")
    return out




def groups():
    """[(key, title, blurb)] in display order."""
    return [(k, GROUP_META[k][0], GROUP_META[k][1]) for k in GROUP_ORDER]
