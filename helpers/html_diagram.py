# -*- coding: utf-8 -*-
ARCHITECTURE_SVG = r"""
<svg viewBox="0 0 1120 460" role="img" aria-label="A request enters the gateway, passes cheap deterministic input rails, escalates to a cloud check only if borderline, reaches the model, passes output rails that recheck each streamed chunk, then returns a response. In parallel, offline red-teaming builds a regression corpus that hardens the rails and every verdict from both paths lands in one audit store." xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <polygon class="head" points="0,0 10,5 0,10 3,5"></polygon>
    </marker>
    <marker id="arrow-accent" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <polygon class="head-accent" points="0,0 10,5 0,10 3,5"></polygon>
    </marker>
  </defs>

  <rect x="155" y="15" width="790" height="275" rx="10" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.2" stroke-dasharray="4 5"></rect>
  <text x="170" y="34" class="lbl mono-lbl" style="font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:0.04em;">GATEWAY — FAILS CLOSED ON CLIENT-FACING TRAFFIC</text>

  <!-- Row 1: runtime path -->
  <rect class="node" x="20" y="60" width="110" height="56" rx="10"></rect>
  <text x="75" y="93" text-anchor="middle" font-size="12.5">Request</text>

  <rect class="node-accent" x="170" y="54" width="170" height="68" rx="8"></rect>
  <text x="255" y="82" text-anchor="middle" font-size="13" font-weight="600">Input Rails</text>
  <text x="255" y="100" text-anchor="middle" class="lbl">PII · secrets · injection</text>

  <polygon class="node" points="375,88 430,48 485,88 430,128"></polygon>
  <text x="430" y="92" text-anchor="middle" font-size="11">borderline?</text>

  <rect class="node" x="365" y="210" width="190" height="56" rx="8"></rect>
  <text x="460" y="234" text-anchor="middle" font-size="12">Cloud Check</text>
  <text x="460" y="250" text-anchor="middle" class="lbl">Azure / vendor, 2nd opinion</text>

  <rect class="node-accent" x="565" y="54" width="130" height="68" rx="8"></rect>
  <text x="630" y="92" text-anchor="middle" font-size="13" font-weight="600">Model Call</text>

  <rect class="node-accent" x="735" y="54" width="190" height="68" rx="8"></rect>
  <text x="830" y="82" text-anchor="middle" font-size="13" font-weight="600">Output Rails</text>
  <text x="830" y="100" text-anchor="middle" class="lbl">toxicity · groundedness · PII</text>

  <rect class="node" x="985" y="60" width="110" height="56" rx="10"></rect>
  <text x="1040" y="93" text-anchor="middle" font-size="12.5">Response</text>

  <!-- Row 2: offline path -->
  <rect class="node-offline" x="170" y="345" width="230" height="64" rx="8"></rect>
  <text x="285" y="372" text-anchor="middle" font-size="12.5" font-weight="600">Offline Red-Team &amp; Eval</text>
  <text x="285" y="390" text-anchor="middle" class="lbl">PyRIT · garak · promptfoo</text>

  <rect class="node" x="460" y="345" width="190" height="64" rx="8"></rect>
  <text x="555" y="372" text-anchor="middle" font-size="12.5" font-weight="600">Regression Corpus</text>
  <text x="555" y="390" text-anchor="middle" class="lbl">versioned in git</text>

  <rect class="node" x="730" y="345" width="190" height="64" rx="8"></rect>
  <text x="825" y="372" text-anchor="middle" font-size="12.5" font-weight="600">Audit Store</text>
  <text x="825" y="390" text-anchor="middle" class="lbl">verdicts + OTel traces</text>

  <!-- Arrows: runtime -->
  <line x1="130" y1="88" x2="167" y2="88" marker-end="url(#arrow)"></line>
  <line x1="342" y1="88" x2="372" y2="88" marker-end="url(#arrow)"></line>
  <line x1="486" y1="88" x2="562" y2="88" marker-end="url(#arrow)"></line>
  <text x="524" y="78" text-anchor="middle" class="lbl">clear</text>
  <path class="arrow" d="M430,128 L430,207" marker-end="url(#arrow)"></path>
  <text x="466" y="182" text-anchor="middle" class="lbl">borderline</text>
  <path class="arrow" d="M556,235 C 615,232 630,180 628,125" marker-end="url(#arrow)"></path>
  <line x1="697" y1="88" x2="732" y2="88" marker-end="url(#arrow)"></line>
  <line x1="927" y1="88" x2="982" y2="88" marker-end="url(#arrow)"></line>
  <text x="954" y="78" text-anchor="middle" class="lbl">if safe</text>
  <path class="arrow" d="M790,53 C 800,25 860,25 870,53" marker-end="url(#arrow)"></path>
  <text x="830" y="24" text-anchor="middle" class="lbl">re-checked every streamed chunk</text>

  <!-- Arrows: down to audit -->
  <path class="arrow" d="M865,123 C 850,220 838,290 826,343" marker-end="url(#arrow)"></path>
  <text x="905" y="230" text-anchor="middle" class="lbl">every verdict</text>

  <!-- Arrows: offline -->
  <line x1="402" y1="377" x2="457" y2="377" marker-end="url(#arrow)"></line>
  <text x="430" y="367" text-anchor="middle" class="lbl">confirmed failures</text>
  <line x1="652" y1="377" x2="727" y2="377" marker-end="url(#arrow)"></line>
  <text x="690" y="367" text-anchor="middle" class="lbl">every finding</text>

  <!-- Feedback loop -->
  <path class="feedback" d="M540,343 C 420,270 320,240 262,126" marker-end="url(#arrow-accent)"></path>
  <text x="330" y="255" text-anchor="middle" class="lbl" fill="var(--accent)" style="fill:var(--accent)">hardens rails before next release</text>
</svg>
"""

MITIGATION_SVG = r"""
<svg viewBox="0 0 1080 260" role="img" aria-label="When the output rails do not come back clear, the action depends on the category: toxic or unsafe content is blocked and refused, a PII leak is masked and the response continues, an ungrounded claim is flagged or the answer is regenerated, and a disallowed tool call is blocked before it executes." xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrow2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <polygon class="head" points="0,0 10,5 0,10 3,5"></polygon>
    </marker>
  </defs>
  <polygon class="node" points="60,50 150,15 240,50 150,85"></polygon>
  <text x="150" y="54" text-anchor="middle" font-size="11">all clear?</text>
  <line x1="150" y1="85" x2="150" y2="150" marker-end="url(#arrow2)"></line>
  <text x="188" y="105" text-anchor="middle" class="lbl">not safe</text>
  <path d="M150,150 L 210,150 M150,150 L 415,150 M150,150 L 635,150 M150,150 L 860,150" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.2" fill="none"></path>

  <rect class="node" x="130" y="180" width="160" height="60" rx="8" fill="var(--risk-soft)" stroke="var(--risk)"></rect>
  <text x="210" y="204" text-anchor="middle" font-size="11.5" font-weight="600" fill="var(--risk)">Toxic / unsafe</text>
  <text x="210" y="222" text-anchor="middle" font-size="11" fill="var(--risk)">→ Block &amp; refuse</text>

  <rect class="node" x="330" y="180" width="170" height="60" rx="8" fill="var(--warn-soft)" stroke="var(--warn)"></rect>
  <text x="415" y="204" text-anchor="middle" font-size="11.5" font-weight="600" fill="var(--warn)">PII leak</text>
  <text x="415" y="222" text-anchor="middle" font-size="11" fill="var(--warn)">→ Mask &amp; continue</text>

  <rect class="node" x="540" y="180" width="190" height="60" rx="8" fill="var(--warn-soft)" stroke="var(--warn)"></rect>
  <text x="635" y="204" text-anchor="middle" font-size="11.5" font-weight="600" fill="var(--warn)">Not grounded</text>
  <text x="635" y="222" text-anchor="middle" font-size="11" fill="var(--warn)">→ Flag or regenerate</text>

  <rect class="node" x="770" y="180" width="180" height="60" rx="8" fill="var(--risk-soft)" stroke="var(--risk)"></rect>
  <text x="860" y="204" text-anchor="middle" font-size="11.5" font-weight="600" fill="var(--risk)">Disallowed tool call</text>
  <text x="860" y="222" text-anchor="middle" font-size="11" fill="var(--risk)">→ Block before execution</text>

  <line x1="210" y1="150" x2="210" y2="177" marker-end="url(#arrow2)"></line>
  <line x1="415" y1="150" x2="415" y2="177" marker-end="url(#arrow2)"></line>
  <line x1="635" y1="150" x2="635" y2="177" marker-end="url(#arrow2)"></line>
  <line x1="860" y1="150" x2="860" y2="177" marker-end="url(#arrow2)"></line>

  <line x1="240" y1="50" x2="1000" y2="50" marker-end="url(#arrow2)"></line>
  <text x="1015" y="54" font-size="11">safe → deliver</text>
</svg>
"""
