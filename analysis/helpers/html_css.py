# -*- coding: utf-8 -*-
CSS = r"""
:root {
  --bg: #F3F6FA;
  --surface: #FFFFFF;
  --surface-2: #EAF0F6;
  --ink: #131B24;
  --ink-muted: #55626F;
  --ink-faint: #7C8896;
  --line: #DCE3EA;
  --line-strong: #C3CDD8;
  --accent: #2B5C8A;
  --accent-strong: #163B5C;
  --accent-soft: #E4EDF6;
  --brass: #9A6B15;
  --brass-soft: #F3E8D2;
  --good: #2E7D5B;
  --good-soft: #E3F1EA;
  --warn: #9A6B15;
  --warn-soft: #F3E8D2;
  --risk: #A63D2E;
  --risk-soft: #F7E5E1;
  --code-bg: #101820;
  --code-ink: #D7E3EE;
  --shadow: 0 1px 2px rgba(19,27,36,0.04), 0 8px 24px -12px rgba(19,27,36,0.12);
  --radius: 10px;

  --t-privacy: #2E6FA3; --t-privacy-soft: #E3EDF6;
  --t-security: #A63D2E; --t-security-soft: #F7E5E1;
  --t-fairness: #6B4C93; --t-fairness-soft: #ECE6F3;
  --t-explain: #A3701F; --t-explain-soft: #F5EBDA;
  --t-content: #B0562F; --t-content-soft: #F8E8DF;
  --t-halluc: #237A72; --t-halluc-soft: #E1F1EE;
  --t-account: #3D5A73; --t-account-soft: #E6EDF2;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0F151C;
    --surface: #171F29;
    --surface-2: #1D2733;
    --ink: #E7EDF3;
    --ink-muted: #A9B5C1;
    --ink-faint: #7C8896;
    --line: #2A3541;
    --line-strong: #384453;
    --accent: #6FA8D8;
    --accent-strong: #9BC4E8;
    --accent-soft: #1C2E3E;
    --brass: #D6A94C;
    --brass-soft: #33291374;
    --good: #6FBF97;
    --good-soft: #16281f;
    --warn: #D6A94C;
    --warn-soft: #2e2513;
    --risk: #E08A78;
    --risk-soft: #2e1a15;
    --code-bg: #0A0F14;
    --code-ink: #CFE0EE;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);

    --t-privacy: #6FA8D8; --t-privacy-soft: #1b2a38;
    --t-security: #E08A78; --t-security-soft: #331d17;
    --t-fairness: #B9A0DA; --t-fairness-soft: #292036;
    --t-explain: #E0B45D; --t-explain-soft: #33280f;
    --t-content: #E19A6E; --t-content-soft: #33220f;
    --t-halluc: #6FCFC0; --t-halluc-soft: #12292a;
    --t-account: #8FB0CB; --t-account-soft: #1c2733;
  }
}

:root[data-theme="dark"] {
  --bg: #0F151C; --surface: #171F29; --surface-2: #1D2733;
  --ink: #E7EDF3; --ink-muted: #A9B5C1; --ink-faint: #7C8896;
  --line: #2A3541; --line-strong: #384453;
  --accent: #6FA8D8; --accent-strong: #9BC4E8; --accent-soft: #1C2E3E;
  --brass: #D6A94C; --brass-soft: #332913;
  --good: #6FBF97; --good-soft: #16281f;
  --warn: #D6A94C; --warn-soft: #2e2513;
  --risk: #E08A78; --risk-soft: #2e1a15;
  --code-bg: #0A0F14; --code-ink: #CFE0EE;
  --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);
  --t-privacy: #6FA8D8; --t-privacy-soft: #1b2a38;
  --t-security: #E08A78; --t-security-soft: #331d17;
  --t-fairness: #B9A0DA; --t-fairness-soft: #292036;
  --t-explain: #E0B45D; --t-explain-soft: #33280f;
  --t-content: #E19A6E; --t-content-soft: #33220f;
  --t-halluc: #6FCFC0; --t-halluc-soft: #12292a;
  --t-account: #8FB0CB; --t-account-soft: #1c2733;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Public Sans", -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 16px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, h4 { font-family: "Spectral", Georgia, "Times New Roman", serif; text-wrap: balance; margin: 0; color: var(--ink); }
h1 { font-weight: 600; }
h2 { font-weight: 600; }
p { margin: 0; }
a { color: var(--accent); }
.mono { font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace; }
.tabular { font-variant-numeric: tabular-nums; }

.wrap { max-width: 1200px; margin: 0 auto; padding: 0 28px; }
.section { padding: 76px 0; scroll-margin-top: 70px; }
.section + .section { border-top: 1px solid var(--line); }
.eyebrow {
  font-family: "IBM Plex Mono", monospace;
  font-size: 12.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
  font-weight: 500;
  margin: 0 0 10px;
}
.section-head { max-width: 760px; margin: 0 0 40px; }
.section-head h2 { font-size: clamp(26px, 3vw, 34px); line-height: 1.2; }
.section-head .dek { margin-top: 12px; color: var(--ink-muted); font-size: 16.5px; max-width: 65ch; }

/* ---------- top nav ---------- */
.topnav {
  position: sticky; top: 0; z-index: 40;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line);
}
.topnav .wrap { display: flex; align-items: center; gap: 28px; height: 58px; }
.brand { font-family: "Spectral", serif; font-weight: 600; font-size: 17px; white-space: nowrap; }
.brand .dot { color: var(--accent); }
.navlinks { display: flex; gap: 20px; overflow-x: auto; font-size: 13.5px; }
.navlinks a { color: var(--ink-muted); text-decoration: none; white-space: nowrap; padding: 4px 2px; border-bottom: 2px solid transparent; }
.navlinks a:hover { color: var(--ink); border-bottom-color: var(--accent); }

/* ---------- hero ---------- */
.hero { padding: 64px 0 52px; }
.hero-kicker { display:flex; align-items:center; gap: 10px; margin-bottom: 18px;}
.hero h1 { font-size: clamp(34px, 5vw, 54px); line-height: 1.08; max-width: 16ch; }
.hero .lede { margin-top: 20px; font-size: 18.5px; color: var(--ink-muted); max-width: 62ch; line-height: 1.5; }
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; margin-top: 40px; }
.stat { background: var(--surface); padding: 20px 22px; }
.stat .n { font-family: "Spectral", serif; font-size: 30px; font-weight: 600; color: var(--accent-strong); }
.stat .l { font-size: 12.5px; color: var(--ink-muted); margin-top: 4px; letter-spacing: 0.01em; }

/* ---------- tenet cards ---------- */
.tenet-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; }
.tenet-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px 18px 20px; box-shadow: var(--shadow); }
.tenet-card .idx { font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--tc); font-weight: 600; }
.tenet-card h3 { font-size: 16.5px; margin-top: 8px; line-height: 1.25; }
.tenet-card .blurb { margin-top: 8px; color: var(--ink-muted); font-size: 13.6px; line-height: 1.45; }
.tenet-card .count { margin-top: 12px; font-size: 12px; font-family:"IBM Plex Mono",monospace; color: var(--tc); }
.tenet-card { border-top: 3px solid var(--tc); }

/* ---------- filter bar ---------- */
.filterbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 26px; }
.filterbar input[type="search"] {
  flex: 1 1 240px; min-width: 200px; padding: 9px 13px; border-radius: 8px;
  border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink); font-size: 14px;
  font-family: inherit;
}
.filterbar input[type="search"]:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.chip {
  border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink-muted);
  font-size: 12.5px; padding: 6px 12px; border-radius: 999px; cursor: pointer;
  font-family: "IBM Plex Mono", monospace; transition: none;
}
.chip:hover { border-color: var(--accent); color: var(--ink); }
.chip.active { background: var(--accent); border-color: var(--accent); color: white; }
.chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* ---------- repo cards ---------- */
.repo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.repo-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.repo-card summary { list-style: none; cursor: pointer; padding: 18px 20px; }
.repo-card summary::-webkit-details-marker { display: none; }
.repo-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.repo-name { font-family: "Spectral", serif; font-weight: 600; font-size: 17px; }
.repo-chevron { font-size: 13px; color: var(--ink-faint); transition: transform 0.15s ease; margin-top: 3px; }
details[open] .repo-chevron { transform: rotate(90deg); }
.repo-summary-text { margin-top: 8px; font-size: 13.3px; color: var(--ink-muted); line-height: 1.45; }
.tagrow { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.tag { font-size: 10.8px; font-family: "IBM Plex Mono", monospace; padding: 3px 8px; border-radius: 999px; background: var(--tc-soft); color: var(--tc); font-weight: 600; }
.badge { font-size: 10.8px; font-family: "IBM Plex Mono", monospace; padding: 3px 9px; border-radius: 999px; font-weight: 600; }
.role-dev { background: var(--accent-soft); color: var(--accent-strong); }
.role-test { background: var(--risk-soft); color: var(--risk); }
.role-both { background: var(--brass-soft); color: var(--brass); }
.repo-body { padding: 0 20px 22px; border-top: 1px solid var(--line); }
.repo-body h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-faint); margin: 18px 0 8px; font-family: "IBM Plex Mono", monospace; font-weight: 600; }
.repo-body ul { margin: 0; padding-left: 18px; font-size: 13.4px; color: var(--ink); }
.repo-body li { margin-bottom: 6px; line-height: 1.42; }
.repo-body li.lim { color: var(--ink-muted); }
.factgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; margin-top: 14px; font-size: 12.8px; }
.factgrid .k { color: var(--ink-faint); font-family: "IBM Plex Mono", monospace; font-size: 10.6px; text-transform: uppercase; letter-spacing: 0.05em; }
.factgrid .v { color: var(--ink); margin-top: 2px; }
.fitnote { margin-top: 16px; background: var(--accent-soft); border-radius: 8px; padding: 12px 14px; font-size: 12.8px; color: var(--ink); line-height: 1.45; }
.fitnote b { color: var(--accent-strong); font-family: "IBM Plex Mono", monospace; font-size: 10.5px; letter-spacing: 0.05em; text-transform: uppercase; display: block; margin-bottom: 4px; }

/* ---------- diagram ---------- */
.diagram-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 28px; box-shadow: var(--shadow); }
.diagram-card svg { width: 100%; height: auto; display: block; }
.diagram-card svg text { fill: var(--ink); font-family: "Public Sans", sans-serif; }
.diagram-card svg .lbl { fill: var(--ink-muted); font-size: 11px; }
.diagram-card svg .node { fill: var(--surface-2); stroke: var(--line-strong); stroke-width: 1.2; }
.diagram-card svg .node-accent { fill: var(--accent-soft); stroke: var(--accent); stroke-width: 1.4; }
.diagram-card svg .node-offline { fill: var(--risk-soft); stroke: var(--risk); stroke-width: 1.2; }
.diagram-card svg line, .diagram-card svg path.arrow { stroke: var(--ink-faint); stroke-width: 1.4; fill: none; }
.diagram-card svg path.feedback { stroke: var(--accent); stroke-width: 1.6; stroke-dasharray: 5 4; fill: none; }
.diagram-card svg polygon.head { fill: var(--ink-faint); }
.diagram-card svg polygon.head-accent { fill: var(--accent); }
figcaption { margin-top: 16px; font-size: 13px; color: var(--ink-muted); max-width: 70ch; line-height: 1.5; }

/* ---------- checklist table ---------- */
.table-scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
table { width: 100%; border-collapse: collapse; font-size: 13.4px; }
thead th {
  text-align: left; padding: 11px 14px; font-family: "IBM Plex Mono", monospace; font-size: 10.8px;
  text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-faint); border-bottom: 1px solid var(--line);
  background: var(--surface-2); position: sticky; top: 0;
}
tbody td { padding: 10px 14px; border-bottom: 1px solid var(--line); vertical-align: top; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: var(--surface-2); }
.aspect-name { font-weight: 600; }
.aspect-note { color: var(--ink-muted); font-size: 12.6px; margin-top: 2px; }
.src-count { font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--ink-muted); }
.count-hint { font-size: 12.5px; color: var(--ink-faint); margin-bottom: 14px; }

/* ---------- recommendation cards ---------- */
.rec-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 24px 26px; margin-bottom: 18px; border-left: 4px solid var(--tc); }
.rec-head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.rec-head h3 { font-size: 19px; color: var(--tc); }
.rec-cols { display: grid; grid-template-columns: 1.1fr 1.4fr; gap: 22px; }
.rec-cols .lbl { font-family: "IBM Plex Mono", monospace; font-size: 10.8px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-faint); margin-bottom: 8px; }
.combo-badges { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 4px; }
.combo-badge { background: var(--good-soft); color: var(--good); font-family: "IBM Plex Mono", monospace; font-size: 11.5px; font-weight: 700; padding: 5px 11px; border-radius: 999px; }
.pill-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.pill { font-size: 11px; font-family: "IBM Plex Mono", monospace; padding: 3px 9px; border-radius: 999px; background: var(--tc-soft); color: var(--tc); }
.cloud-list { list-style: none; margin: 0; padding: 0; font-size: 12.6px; color: var(--ink-muted); }
.cloud-list li { padding: 4px 0 4px 14px; position: relative; line-height: 1.4; }
.cloud-list li::before { content: "—"; position: absolute; left: 0; color: var(--ink-faint); }
.rationale { font-size: 13.6px; line-height: 1.55; color: var(--ink); }
.prior-note { margin-top: 14px; background: var(--surface-2); border-radius: 8px; padding: 12px 14px; font-size: 12.6px; color: var(--ink-muted); line-height: 1.5; }
.prior-note b { color: var(--tc); font-family: "IBM Plex Mono", monospace; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 4px; }
@media (max-width: 760px) { .rec-cols { grid-template-columns: 1fr; } }

/* ---------- dev vs test ---------- */
.split-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
.split-col { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px 20px; box-shadow: var(--shadow); }
.split-col h4 { font-family:"IBM Plex Mono",monospace; font-size: 12px; letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 12px; }
.split-col ul { margin: 0; padding-left: 16px; font-size: 13.3px; }
.split-col li { margin-bottom: 6px; }
.split-col.dev { border-top: 3px solid var(--accent); }
.split-col.dev h4 { color: var(--accent); }
.split-col.test { border-top: 3px solid var(--risk); }
.split-col.test h4 { color: var(--risk); }
.split-col.both { border-top: 3px solid var(--brass); }
.split-col.both h4 { color: var(--brass); }
.connect-note { margin-top: 22px; background: var(--surface-2); border-radius: var(--radius); padding: 20px 24px; font-size: 14px; line-height: 1.6; color: var(--ink); }
.connect-note b { font-family:"IBM Plex Mono",monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--accent); display: block; margin-bottom: 8px; }
@media (max-width: 820px) { .split-grid { grid-template-columns: 1fr; } }

/* ---------- feasibility table ---------- */
.verdict { font-size: 11.3px; font-family:"IBM Plex Mono",monospace; font-weight: 700; padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
.v-adopt { background: var(--good-soft); color: var(--good); }
.v-combine { background: var(--accent-soft); color: var(--accent-strong); }
.v-bench { background: var(--warn-soft); color: var(--warn); }
.v-skip { background: var(--risk-soft); color: var(--risk); }

/* ---------- roadmap ---------- */
/* align-items: start so each card sizes to its own content. The old phase
   cards held 8/9/9 items and looked even by luck; these groups hold
   7/6/2/2/4/5, so stretching would leave a short card hanging over dead
   space. */
.build-plan { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px;
  align-items: start; }
.plan-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.plan-head { padding: 16px 20px; color: white; }
.plan-head .p { font-family: "IBM Plex Mono", monospace; font-size: 11px; opacity: 0.85; letter-spacing: 0.04em; text-transform: uppercase; }
.plan-head .t { font-family: "Spectral", serif; font-size: 18px; font-weight: 600; margin-top: 3px; }
/* Group colour is a grouping cue only. It carries NO ordering: these are six
   kinds of work, all in scope now, not six steps in a sequence. */
.plan-1 .plan-head { background: var(--accent-strong); }
.plan-2 .plan-head { background: var(--good); }
.plan-3 .plan-head { background: var(--brass); }
.plan-4 .plan-head { background: var(--brass); }
.plan-5 .plan-head { background: var(--accent-strong); }
.plan-6 .plan-head { background: var(--ink-muted); }
.plan-body { padding: 18px 20px; }
.plan-blurb { margin: 0 0 12px; font-size: 12.4px; font-style: italic; color: var(--ink-muted); line-height: 1.45; }
.plan-body ol { margin: 0; padding-left: 20px; font-size: 12.9px; line-height: 1.5; }
.plan-body li { margin-bottom: 11px; }
/* A status note is a CORRECTION to an action, so it sits under the action it
   corrects rather than replacing it. */
.plan-note { margin-top: 5px; padding: 6px 9px; border-left: 3px solid var(--brass);
  background: color-mix(in srgb, var(--brass) 8%, transparent);
  font-size: 11.8px; line-height: 1.45; color: var(--ink); }
@media (max-width: 900px) { .build-plan { grid-template-columns: 1fr; } }

/* ---------- closing ---------- */
.closing { background: var(--accent-strong); color: #EAF1F8; }
.closing .eyebrow { color: #B9D3EB; }
.closing h2 { color: white; }
.closing p.narrative { margin-top: 18px; font-size: 16.5px; line-height: 1.65; max-width: 74ch; color: #DCEAF6; }
.closing .steps { margin-top: 32px; display: grid; gap: 12px; max-width: 74ch; }
.closing .step { display: flex; gap: 12px; align-items: baseline; font-size: 14.5px; color: #EAF1F8; }
.closing .step .n { font-family: "IBM Plex Mono", monospace; color: #9BC4E8; font-weight: 700; }

footer { padding: 32px 0 60px; text-align: center; color: var(--ink-faint); font-size: 12.5px; }

.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
"""
