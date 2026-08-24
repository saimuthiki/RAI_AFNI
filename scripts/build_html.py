# -*- coding: utf-8 -*-
"""Generates the Guardrail Atlas HTML artifact from the repo + synthesis data."""
import json
import os
import sys
import html as _html

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "helpers"))

from repo_slide_content import REPO_SLIDES

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_ROOT, "data")

with open(os.path.join(_DATA_DIR, "RAI_Synthesis.json"), encoding="utf-8") as f:
    SYN = json.load(f)

OUT_PATH = os.path.join(_ROOT, "guardrail_atlas.html")

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

TENET_ORDER = [
    "Privacy", "Security", "Fairness & Bias", "Explainability & Transparency",
    "Profanity / Content Safety", "Hallucination / Reliability", "Accountability",
]
TENET_SLUG = {t: t.lower().replace(" & ", "-").replace(" / ", "-").replace(" ", "-") for t in TENET_ORDER}
TENET_BLURBS = {
    "Privacy": "Personal data - names, SSNs, medical records - never leaks into an answer.",
    "Security": "Defends against jailbreaks, prompt injection, and other adversarial attacks.",
    "Fairness & Bias": "AI decisions treat every group of people fairly, with no hidden discrimination.",
    "Explainability & Transparency": "Every decision can be explained, in plain language, to a person.",
    "Profanity / Content Safety": "Toxic, hateful, or otherwise unsafe language is blocked in and out.",
    "Hallucination / Reliability": "Made-up facts are caught; answers stay grounded in real information.",
    "Accountability": "Clear ownership, audit trails, and logging for every AI decision made.",
}


def esc(s):
    return _html.escape(str(s), quote=True)


def short(folder):
    return SHORT_NAME.get(folder, folder)


ROLE_LABEL = {
    "Guardrail Development": "Development",
    "Vulnerability / Red-Team Testing": "Red-Team Testing",
    "Both": "Development + Testing",
}
ROLE_CLASS = {
    "Guardrail Development": "role-dev",
    "Vulnerability / Red-Team Testing": "role-test",
    "Both": "role-both",
}

print(f"Loaded {len(REPO_SLIDES)} repo entries, {len(SYN['master_aspect_list'])} checklist items,"
      f" {len(SYN['tenet_matrix'])} tenet recs, {len(SYN['feasibility_matrix'])} feasibility rows.")

# ============================================================ HERO / STATS
def gen_stats():
    n_checks = len(SYN["master_aspect_list"])
    n_repos = len(REPO_SLIDES)
    n_tenets = len(TENET_ORDER)
    n_rec = sum(len(t["recommended_combination"]) for t in SYN["tenet_matrix"])
    stats = [
        (n_repos, "open-source tools reviewed, code-level"),
        (n_checks, "concrete checks catalogued"),
        (n_tenets, "responsible-AI tenets covered"),
        (3, "phase rollout plan, 90 days"),
    ]
    cells = "".join(
        f'<div class="stat"><div class="n tabular">{n}</div><div class="l">{esc(l)}</div></div>'
        for n, l in stats
    )
    return f'<div class="stat-row">{cells}</div>'


# ============================================================ TENET CARDS
def gen_tenet_cards():
    counts = {}
    for item in SYN["master_aspect_list"]:
        counts[item["tenet"]] = counts.get(item["tenet"], 0) + 1
    cards = []
    for i, t in enumerate(TENET_ORDER, start=1):
        slug = TENET_SLUG[t]
        cards.append(f'''
        <div class="tenet-card" style="--tc: var(--t-{slug})">
          <div class="idx">{i:02d}</div>
          <h3>{esc(t)}</h3>
          <p class="blurb">{esc(TENET_BLURBS[t])}</p>
          <div class="count">{counts.get(t,0)} checks catalogued →</div>
        </div>''')
    return "".join(cards)


# ============================================================ REPO CARDS
def gen_repo_cards():
    cards = []
    for r in REPO_SLIDES:
        tags = "".join(
            f'<span class="tag" style="--tc: var(--t-{TENET_SLUG[t]}); --tc-soft: var(--t-{TENET_SLUG[t]}-soft)">{esc(t)}</span>'
            for t in r["tenets"]
        )
        role_class = ROLE_CLASS[r["role"]]
        role_label = ROLE_LABEL[r["role"]]
        features = "".join(f"<li>{esc(f)}</li>" for f in r["features"])
        limitations = "".join(f'<li class="lim">{esc(l)}</li>' for l in r["limitations"])
        tenet_data_attr = " ".join(TENET_SLUG[t] for t in r["tenets"])
        role_data_attr = role_class
        cards.append(f'''
        <details class="repo-card" data-tenets="{esc(tenet_data_attr)}" data-role="{esc(role_data_attr)}" data-name="{esc(r['display_name'].lower())}">
          <summary>
            <div class="repo-head">
              <div class="repo-name">{esc(r['display_name'])}</div>
              <div class="repo-chevron">›</div>
            </div>
            <p class="repo-summary-text">{esc(r['summary'])}</p>
            <div class="tagrow">
              {tags}
              <span class="badge {role_class}">{esc(role_label)}</span>
            </div>
          </summary>
          <div class="repo-body">
            <h4>Key features</h4>
            <ul>{features}</ul>
            <h4>Limitations to watch</h4>
            <ul>{limitations}</ul>
            <div class="factgrid">
              <div><div class="k">Layer type</div><div class="v">{esc(r['layer'])}</div></div>
              <div><div class="k">Cost model</div><div class="v">{esc(r['cost'])}</div></div>
              <div><div class="k">Integration effort</div><div class="v">{esc(r['effort'])}</div></div>
              <div><div class="k">License</div><div class="v">{esc(r['license'])}</div></div>
            </div>
            <div class="fitnote"><b>AFNI fit</b>{esc(r['fit'])}</div>
          </div>
        </details>''')
    return "".join(cards)


# ============================================================ CHECKLIST TABLE
def gen_checklist_rows():
    rows = []
    for item in SYN["master_aspect_list"]:
        slug = TENET_SLUG.get(item["tenet"], "account")
        n_src = len(item.get("source_repos", []))
        src_names = ", ".join(short(r) for r in item.get("source_repos", []))
        rows.append(f'''
        <tr data-tenet="{esc(slug)}" data-search="{esc((item['aspect'] + ' ' + src_names).lower())}">
          <td><span class="tag" style="--tc: var(--t-{slug}); --tc-soft: var(--t-{slug}-soft)">{esc(item['tenet'])}</span></td>
          <td>
            <div class="aspect-name">{esc(item['aspect'])}</div>
            <div class="aspect-note">{esc(item.get('notes',''))}</div>
          </td>
          <td class="src-count tabular">{n_src}</td>
          <td class="aspect-note">{esc(src_names)}</td>
        </tr>''')
    return "".join(rows)


def gen_tenet_filter_chips(extra_all_label="All tenets"):
    chips = [f'<button class="chip active" data-filter="all">{esc(extra_all_label)}</button>']
    for t in TENET_ORDER:
        slug = TENET_SLUG[t]
        chips.append(f'<button class="chip" data-filter="{esc(slug)}">{esc(t)}</button>')
    return "".join(chips)


# ============================================================ TENET RECOMMENDATIONS
def gen_recommendation_cards():
    cards = []
    for entry in SYN["tenet_matrix"]:
        tenet = entry["tenet"]
        slug = TENET_SLUG[tenet]
        combo_badges = "".join(f'<span class="combo-badge">{esc(short(r))}</span>' for r in entry["recommended_combination"])
        os_pills = "".join(f'<span class="pill" style="--tc: var(--t-{slug}); --tc-soft: var(--t-{slug}-soft)">{esc(short(r))}</span>' for r in entry["open_source_repos"])
        cloud_items = "".join(f"<li>{esc(c)}</li>" for c in entry["cloud_paid_options"])
        prior = entry.get("afni_prior_experience_note", "")
        prior_html = f'<div class="prior-note"><b>Sai\'s prior experience</b>{esc(prior)}</div>' if prior else ""
        cards.append(f'''
        <article class="rec-card" id="rec-{esc(slug)}" style="--tc: var(--t-{slug})">
          <div class="rec-head">
            <h3>{esc(tenet)}</h3>
            <div class="combo-badges">{combo_badges}</div>
          </div>
          <div class="rec-cols">
            <div>
              <div class="lbl">Open-source options (of the 23 reviewed)</div>
              <div class="pill-row">{os_pills}</div>
              <div class="lbl" style="margin-top:14px">Cloud / paid options</div>
              <ul class="cloud-list">{cloud_items}</ul>
            </div>
            <div>
              <div class="lbl">Why this combination</div>
              <p class="rationale">{esc(entry['combination_rationale'])}</p>
              {prior_html}
            </div>
          </div>
        </article>''')
    return "".join(cards)


# ============================================================ DEV VS TEST
def gen_dev_test_section():
    split = SYN["dev_vs_testing_split"]
    def col(cls, label, repos):
        items = "".join(f"<li>{esc(short(r))}</li>" for r in repos)
        return f'<div class="split-col {cls}"><h4>{esc(label)} ({len(repos)})</h4><ul>{items}</ul></div>'
    cols = (
        col("dev", "Development", split["guardrail_development_repos"])
        + col("test", "Testing", split["vulnerability_testing_repos"])
        + col("both", "Both", split["both_repos"])
    )
    return f'''
    <div class="split-grid">{cols}</div>
    <div class="connect-note"><b>How they connect</b>{esc(split["how_they_connect"])}</div>
    '''


# ============================================================ FEASIBILITY
def verdict_class(v):
    vl = v.lower()
    if "adopt" in vl:
        return "v-adopt"
    if "combine" in vl:
        return "v-combine"
    if "bench" in vl:
        return "v-bench"
    return "v-skip"


def gen_feasibility_table():
    rows = []
    for e in SYN["feasibility_matrix"]:
        vclass = verdict_class(e["verdict"])
        rows.append(f'''
        <tr>
          <td>{esc(short(e['repo_folder']))}</td>
          <td>{esc(e['integration_effort'])}</td>
          <td>{esc(e['cost_model'].replace(' (free core + optional paid add-ons)', ''))}</td>
          <td>{esc(e['reliability_confidence'])}<div class="aspect-note">{esc(e['reliability_reason'])}</div></td>
          <td>{esc(e['maintenance_burden'])}</td>
          <td><span class="verdict {vclass}">{esc(e['verdict'])}</span><div class="aspect-note">{esc(e['verdict_reason'])}</div></td>
        </tr>''')
    return "".join(rows)


# ============================================================ ROADMAP
def gen_roadmap():
    cards = []
    for i, phase in enumerate(SYN["roadmap_phases"], start=1):
        actions = "".join(f"<li>{esc(a)}</li>" for a in phase["actions"])
        title = phase["phase"].split("(")[0].strip()
        window = phase["phase"].split("(")[1].rstrip(")") if "(" in phase["phase"] else ""
        cards.append(f'''
        <div class="phase-card phase-{i}">
          <div class="phase-head"><div class="p">{esc(window)}</div><div class="t">{esc(title)}</div></div>
          <div class="phase-body"><ol>{actions}</ol></div>
        </div>''')
    return "".join(cards)


# ============================================================ CLOSING
def gen_closing_steps():
    steps = [
        "Walk through this atlas with Kiran and agree the AFNI Responsible AI standard.",
        "Kick off Phase 1: the gateway, the OpenGuardrails contract, and the LLM Guard fork.",
        "Get legal sign-off on the two flagged licensing/vendor-risk items (Deepchecks AGPL, promptfoo remote plugins).",
        "Yamini to schedule the follow-up session and send Kiran the acceptable-use document.",
        "Sai to complete the Azure AI-103 certification.",
    ]
    return "".join(
        f'<div class="step"><span class="n">{i:02d}</span><span>{esc(s)}</span></div>'
        for i, s in enumerate(steps, start=1)
    )


# ================================================================= BUILD
from html_css import CSS
from html_js import JS
from html_diagram import ARCHITECTURE_SVG, MITIGATION_SVG


def gen_infosys_vs_nemo():
    drawbacks = [
        "Deploying it as designed means standing up about 20 independently-versioned FastAPI microservices plus an Angular front end, each with its own model weights",
        "Red-team modules are marked retired for release 2.2.1; the front end still ships orphaned red-team screens pointing at nothing",
        "No accuracy numbers exist anywhere for its in-house fine-tuned models",
        "The core dispatcher wraps each check in a broad try/except that logs and returns None - one timeout silently drops a check instead of failing loudly",
        "Every one of the ~20 services must be configured with every other service's URL",
    ]
    wins = [
        "One pip-installable Python package, not a service mesh to operate",
        "Already a plugin architecture: every rail is a self-contained module (an actions file, a config schema, a manifest) - AFNI's own detectors plug in as first-class rails",
        "Ships ready adapters for about 20 managed safety vendors plus Azure services, so AFNI stays Azure-first without being locked in",
        "NVIDIA-maintained with a 383-file test suite, and it publishes honest numbers about its own weak spots",
    ]
    carry = ["Per-tenant threshold service", "One consolidated verdict", "Fail-loud, fails-closed policy"]
    dcol = "".join(f"<li>{esc(d)}</li>" for d in drawbacks)
    wcol = "".join(f"<li>{esc(w)}</li>" for w in wins)
    ccol = "".join(f"<li>{esc(c)}</li>" for c in carry)
    return f'''
    <div class="split-grid" style="grid-template-columns: 1fr 1fr;">
      <div class="split-col test"><h4>Infosys Toolkit - right shape, wrong build</h4><ul>{dcol}</ul></div>
      <div class="split-col dev"><h4>NeMo Guardrails - recommended backbone</h4><ul>{wcol}</ul></div>
    </div>
    <div class="connect-note"><b>Carry over from Infosys, build explicitly on NeMo</b><ul style="margin:0;padding-left:18px">{ccol}</ul></div>
    '''

PAGE = f"""<title>Guardrail Atlas</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Spectral:wght@500;600;700&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>

<nav class="topnav">
  <div class="wrap">
    <div class="brand">Guardrail<span class="dot">·</span>Atlas</div>
    <div class="navlinks">
      <a href="#tenets">Tenets</a>
      <a href="#architecture">Architecture</a>
      <a href="#repos">23 Tools</a>
      <a href="#checklist">Checklist</a>
      <a href="#recommendations">Recommendations</a>
      <a href="#feasibility">Feasibility</a>
      <a href="#roadmap">Roadmap</a>
    </div>
  </div>
</nav>

<header class="hero">
  <div class="wrap">
    <div class="hero-kicker"><span class="eyebrow" style="margin:0">AFNI · Responsible AI Governance</span></div>
    <h1>A field guide to building AI you can defend in front of a client.</h1>
    <p class="lede">Twenty-three open-source tools, read down to the actual source code — not the README —
      then sorted into seven tenets and one buildable, phased plan for AFNI's own Responsible AI toolkit.</p>
    {gen_stats()}
  </div>
</header>

<section class="section" id="tenets">
  <div class="wrap">
    <div class="section-head">
      <p class="eyebrow">The foundation</p>
      <h2>Seven tenets, one shared vocabulary</h2>
      <p class="dek">Every framework — NIST, the EU AI Act, Microsoft's own RAI standard — names things a little
        differently. These are the seven AFNI is working from.</p>
    </div>
    <div class="tenet-grid">{gen_tenet_cards()}</div>
  </div>
</section>

<section class="section" id="architecture">
  <div class="wrap">
    <div class="section-head">
      <p class="eyebrow">The unified design</p>
      <h2>One gateway, one contract, two loops</h2>
      <p class="dek">Cheap, deterministic checks run on every request. A paid model or cloud service is called
        only when a request looks borderline. Offline, a red-team loop keeps hardening the same rails.</p>
    </div>
    <figure class="diagram-card">
      {ARCHITECTURE_SVG}
      <figcaption>{esc(' '.join(SYN["unified_architecture"]["narrative"].split('. ')[:2]) + '.')} The two rules
        that don't bend: the gateway fails closed for client-facing traffic, and any check that couldn't run
        is reported as <em>unjudged</em>, never silently passed.</figcaption>
    </figure>

    <figure class="diagram-card" style="margin-top:20px">
      {MITIGATION_SVG}
      <figcaption>Zooming into the "not safe" branch above: the action taken depends on the category. A toxic
        or unsafe response and a disallowed tool call are hard-blocked. A PII leak is masked and the response
        still reaches the user. An ungrounded claim is flagged or the answer is regenerated - never silently
        let through unmarked.</figcaption>
    </figure>

    <div class="section-head" style="margin-top:56px">
      <p class="eyebrow">Current shape vs. recommended backbone</p>
      <h2>Infosys Toolkit vs. NeMo Guardrails</h2>
      <p class="dek">The Infosys toolkit has the right shape - one dispatcher fanning out to ~15 checks with a
        single verdict - but adopting it as built means running an entire microservice mesh. NeMo Guardrails
        gets the same shape from one Python package.</p>
    </div>
    {gen_infosys_vs_nemo()}
  </div>
</section>

<section class="section" id="repos">
  <div class="wrap">
    <div class="section-head">
      <p class="eyebrow">Repository deep-dives</p>
      <h2>23 tools, read down to the source code</h2>
      <p class="dek">Each card is one repository — what it actually does internally, its real features and
        limits, cost, effort to integrate, and how it fits into AFNI's toolkit. Filter by tenet or search by name.</p>
    </div>
    <div id="repo-filter-root">
      <div class="filterbar">
        <input type="search" placeholder="Search tools by name…" aria-label="Search tools by name">
      </div>
      <div class="filterbar" style="margin-top:-14px">{gen_tenet_filter_chips()}</div>
      <p class="count-hint"></p>
      <div class="repo-grid">{gen_repo_cards()}</div>
    </div>
  </div>
</section>

<section class="section" id="checklist">
  <div class="wrap">
    <div class="section-head">
      <p class="eyebrow">The master checklist</p>
      <h2>Every concrete check we found, tagged to a tenet</h2>
      <p class="dek">{len(SYN['master_aspect_list'])} distinct checks, detectors, and metrics across all 23 tools —
        deduplicated, tagged, and counted by how many tools provide each one.</p>
    </div>
    <div id="checklist-filter-root">
      <div class="filterbar">
        <input type="search" placeholder="Search checks by name or tool…" aria-label="Search checks">
      </div>
      <div class="filterbar" style="margin-top:-14px">{gen_tenet_filter_chips()}</div>
      <p class="count-hint"></p>
      <div class="table-scroll">
        <table>
          <thead><tr><th>Tenet</th><th>Check</th><th>Tools</th><th>Which tools provide it</th></tr></thead>
          <tbody id="checklist-body">{gen_checklist_rows()}</tbody>
        </table>
      </div>
    </div>
  </div>
</section>

<section class="section" id="recommendations">
  <div class="wrap">
    <div class="section-head">
      <p class="eyebrow">Tenet-by-tenet recommendations</p>
      <h2>Picked on merit, not forced into a fixed pattern</h2>
      <p class="dek">For each tenet: what's open-source, what's cloud/paid, and AFNI's recommended combination —
        one tool, two, or three, whichever combination genuinely wins on cost, accuracy, and reliability.</p>
    </div>
    {gen_recommendation_cards()}
  </div>
</section>

<section class="section" id="dev-vs-test">
  <div class="wrap">
    <div class="section-head">
      <p class="eyebrow">Two halves, one loop</p>
      <h2>Guardrail development vs. vulnerability testing</h2>
      <p class="dek">Some tools build the defense. Others attack it. Both are first-class parts of the toolkit.</p>
    </div>
    {gen_dev_test_section()}
  </div>
</section>

<section class="section" id="feasibility">
  <div class="wrap">
    <div class="section-head">
      <p class="eyebrow">Feasibility check</p>
      <h2>Can we actually integrate it?</h2>
      <p class="dek">Effort, cost, reliability, and maintenance burden for all 23 tools, with a clear verdict on each.</p>
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr><th>Tool</th><th>Effort</th><th>Cost</th><th>Reliability</th><th>Maintenance</th><th>Verdict</th></tr></thead>
        <tbody>{gen_feasibility_table()}</tbody>
      </table>
    </div>
  </div>
</section>

<section class="section" id="roadmap">
  <div class="wrap">
    <div class="section-head">
      <p class="eyebrow">Adoption plan</p>
      <h2>A 90-day phased roadmap</h2>
      <p class="dek">Free and deterministic first. Model-based and cloud checks once thresholds are calibrated.
        The heaviest red-teaming once the runtime layer is stable.</p>
    </div>
    <div class="roadmap">{gen_roadmap()}</div>
  </div>
</section>

<section class="section closing" id="bottom-line">
  <div class="wrap">
    <p class="eyebrow">The bottom line</p>
    <h2>How AFNI should think about cost, accuracy, and reliability</h2>
    <p class="narrative">{esc(SYN["key_tradeoff_narrative"])}</p>
    <div class="steps">{gen_closing_steps()}</div>
  </div>
</section>

<footer>
  Prepared by Sai Muthiki for Kiran Devkar &amp; AFNI AI Governance · Companion to the AFNI Responsible AI Framework deck
</footer>

<script>{JS}</script>
"""

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(PAGE)

print(f"Wrote {OUT_PATH} ({len(PAGE):,} chars)")
