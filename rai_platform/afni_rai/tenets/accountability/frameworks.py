# -*- coding: utf-8 -*-
"""
Compliance-framework mapping: AFNI `Finding.category` -> framework control ids.

This is what produces the client approval pack. A reviewer does not want a list
of regexes that fired; they want "OWASP LLM01 is covered, and here is the
evidence".

SOURCE

promptfoo has the richest mapping of the 23 repos - six frameworks, all in
`references/promptfoo-main/src/redteam/constants/frameworks.ts`:

    :8-18    FRAMEWORK_NAMES          the six display names
    :74-173  OWASP_LLM_TOP_10_MAPPING  owasp:llm:01 .. owasp:llm:10
    :396-485 NIST_AI_RMF_MAPPING       nist:ai:measure:1.1 .. 4.3   (21 controls)
    :499-658 MITRE_ATLAS_MAPPING       16 tactics
    :674-776 EU_AI_ACT_MAPPING         Art.5 prohibitions + Annex III high-risk
    :782-831 ISO_42001_MAPPING         7 AIMS risk areas
    :841-920 GDPR_MAPPING              8 articles

DeepTeam has five framework maps and PyRIT has none at all - its compliance
mapping is OWASP LLM01/LLM02 docstrings only, with no report generator (the
per-repo caveats note that the deck overstates this). So promptfoo is the pick,
and `docs/tenets.md:129-133` records that decision.

HOW THE PORT WORKS

promptfoo's maps run control -> promptfoo *plugin ids* (`pii:direct`,
`shell-injection`, `bias:race`, ...), because promptfoo is a red-team generator:
the mapping answers "which probes exercise this control". AFNI needs the inverse,
keyed on its own taxonomy: given a finding we actually produced, which controls
does it evidence?

So the port is three tables:

  1. `PLUGIN_TO_CATEGORY` - promptfoo plugin id -> AFNI category prefixes. This is
     the only judgement call in the file, and every row is a plugin id read out
     of frameworks.ts mapped to an OpenGuardrails taxonomy term
     (`references/openguardrails-main/.../specification/taxonomy.md`) or to the
     `x.afni.*` extension namespace where the taxonomy has no term (bias, for
     instance, has no OpenGuardrails category).
  2. `FRAMEWORKS` - the control -> plugin lists, transcribed from frameworks.ts.
  3. `CONTROL_STRATEGIES` + `STRATEGY_TO_CATEGORY` - the same for the `strategies`
     half of each mapping. Skipping it would lose real coverage: `jailbreak` is a
     promptfoo *strategy*, so without this table a `security.jailbreak` finding
     evidences no OWASP LLM control at all, even though frameworks.ts:81 lists
     jailbreak strategies under `owasp:llm:01`.

Inversion happens once at import, in pure Python, and produces
`category prefix -> [control ids]`. Matching is by prefix, so a finding at
`privacy.pii.us_ssn` matches a `privacy.pii` row - which means a new PII
subcategory added by the Privacy tenet maps correctly without touching this file.

COMPLETENESS, STATED HONESTLY

All six frameworks are transcribed from source that was read. Two carry a caveat
that is surfaced in `FRAMEWORKS[...].completeness` and in `render()`:

  * MITRE ATLAS - promptfoo's own comment at frameworks.ts:501 says "No promptfoo
    plugin directly validates model access level yet", and `mitre:atlas:ai-model-
    access` has an empty plugin list upstream. A control with no upstream plugins
    cannot be evidenced by any finding, so it is carried as a declared control
    with zero coverage rather than dropped.
  * EU AI Act - Art.5 and Annex III are transcribed, but the Act's other duties
    (Art.9 risk management, Art.12 logging, Art.13 transparency, Art.14 human
    oversight) have no promptfoo mapping at all, so this file cannot evidence
    them. They are AFNI process controls, not detector findings, and claiming
    otherwise would be the exact overstatement the analysis flagged in PyRIT.

`owasp:llm:03` (Supply Chain) is likewise empty upstream, for the same honest
reason: no runtime finding evidences a supply-chain control.

Zero third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

# --------------------------------------------------------------------------- #
# 1. promptfoo plugin id -> AFNI category prefixes
#
# Left side: plugin ids that appear in frameworks.ts. Right side: OpenGuardrails
# taxonomy terms, or `x.afni.*` where the taxonomy has no term.
# --------------------------------------------------------------------------- #
PLUGIN_TO_CATEGORY: dict[str, tuple[str, ...]] = {
    # ---- prompt injection / jailbreak (taxonomy.md:54-55) ----
    "ascii-smuggling": ("security.prompt_injection", "x.afni.invisible_text"),
    "special-token-injection": ("security.prompt_injection",),
    "indirect-prompt-injection": ("security.prompt_injection",),
    "system-prompt-override": ("security.jailbreak",),
    "hijacking": ("security.jailbreak", "safety.topic_violation"),
    "intent": ("security.jailbreak",),
    "policy": ("safety.topic_violation",),
    # ---- exfiltration / leakage (taxonomy.md:57-58, 100-120) ----
    "prompt-extraction": ("security.data_exfiltration", "x.afni.prompt_leak"),
    "data-exfil": ("security.data_exfiltration",),
    "rag-document-exfiltration": ("security.data_exfiltration",),
    "cross-session-leak": ("security.data_exfiltration", "privacy.pii"),
    "harmful:privacy": ("privacy.pii", "safety.pii"),
    "pii:direct": ("privacy.pii",),
    "pii:api-db": ("privacy.pii",),
    "pii:session": ("privacy.pii",),
    "pii:social": ("privacy.pii",),
    # ---- injection / insecure output handling (taxonomy.md:56, 59) ----
    "shell-injection": ("security.malicious_command",),
    "sql-injection": ("security.malicious_command",),
    "ssrf": ("security.ssrf",),
    "debug-access": ("security.privilege_escalation", "x.afni.debug_access"),
    # ---- agency / authorisation (taxonomy.md:60) ----
    "excessive-agency": ("x.afni.excessive_agency",),
    "rbac": ("security.privilege_escalation",),
    "bfla": ("security.privilege_escalation",),
    "bola": ("security.privilege_escalation",),
    "tool-discovery": ("x.afni.tool_discovery",),
    "mcp": ("security.tool_poisoning",),
    # ---- poisoning / persistence (taxonomy.md:63-64) ----
    "rag-poisoning": ("security.memory_poisoning",),
    "agentic:memory-poisoning": ("security.memory_poisoning",),
    # ---- safety content (taxonomy.md:16-26) ----
    "harmful": ("safety.illicit",),
    "harmful:hate": ("safety.toxicity",),
    "harmful:insults": ("safety.toxicity",),
    "harmful:harassment-bullying": ("safety.toxicity",),
    "harmful:violent-crime": ("safety.violence",),
    "harmful:radicalization": ("safety.violence",),
    "harmful:child-exploitation": ("safety.sexual",),
    "harmful:chemical-biological-weapons": ("safety.weapons",),
    "harmful:indiscriminate-weapons": ("safety.weapons",),
    "harmful:illegal-drugs": ("safety.illicit",),
    "harmful:unsafe-practices": ("safety.unsafe_advice",),
    "harmful:specialized-advice": ("safety.unsafe_advice",),
    "harmful:cybercrime": ("security.malicious_command", "safety.illicit"),
    "harmful:cybercrime:malicious-code": ("security.malicious_command",),
    "harmful:misinformation-disinformation": ("safety.hallucination",),
    # ---- reliability / grounding (taxonomy.md:25) ----
    "hallucination": ("safety.hallucination", "x.afni.grounding"),
    "unverifiable-claims": ("safety.hallucination",),
    "overreliance": ("x.afni.overreliance",),
    "imitation": ("safety.brand",),
    "competitors": ("safety.brand",),
    "model-identification": ("x.afni.model_disclosure",),
    "politics": ("safety.topic_violation",),
    "religion": ("safety.topic_violation",),
    "rag-source-attribution": ("x.afni.grounding",),
    # ---- fairness. OpenGuardrails has NO bias category, so this is the
    # extension namespace. Prefix matching means whatever the Fairness tenet
    # emits under `x.afni.bias.*` maps here without an edit.
    "bias:age": ("x.afni.bias.age",),
    "bias:gender": ("x.afni.bias.gender",),
    "bias:race": ("x.afni.bias.race",),
    "bias:disability": ("x.afni.bias.disability",),
    # ---- resource exhaustion (taxonomy.md:65) ----
    "divergent-repetition": ("security.resource_exhaustion",),
    "reasoning-dos": ("security.resource_exhaustion",),
}


# --------------------------------------------------------------------------- #
# 2. The six frameworks, transcribed from frameworks.ts.
# --------------------------------------------------------------------------- #
OWASP_LLM_TOP_10: dict[str, list[str]] = {
    # frameworks.ts:74-173. Titles from OWASP_LLM_TOP_10_NAMES (:20-31).
    "owasp:llm:01": ["ascii-smuggling", "indirect-prompt-injection",
                     "prompt-extraction", "harmful"],
    "owasp:llm:02": ["pii:api-db", "pii:direct", "pii:session", "pii:social",
                     "harmful:privacy", "cross-session-leak", "prompt-extraction"],
    "owasp:llm:03": [],  # Supply Chain - no upstream plugins, and no runtime
                         # finding could evidence it. Declared, not claimed.
    "owasp:llm:04": ["harmful:misinformation-disinformation", "harmful:hate",
                     "bias:age", "bias:disability", "bias:gender", "bias:race",
                     "harmful:radicalization", "harmful:specialized-advice"],
    "owasp:llm:05": ["shell-injection", "sql-injection", "ssrf", "debug-access"],
    "owasp:llm:06": ["excessive-agency", "rbac", "bfla", "bola", "shell-injection",
                     "sql-injection", "ssrf"],
    "owasp:llm:07": ["prompt-extraction", "rbac", "harmful:privacy", "pii:api-db",
                     "pii:direct", "pii:session", "pii:social"],
    "owasp:llm:08": ["cross-session-leak", "harmful:privacy", "pii:api-db",
                     "pii:direct", "pii:session", "pii:social"],
    "owasp:llm:09": ["hallucination", "overreliance",
                     "harmful:misinformation-disinformation",
                     "harmful:specialized-advice"],
    "owasp:llm:10": ["divergent-repetition", "reasoning-dos"],
}

OWASP_LLM_TITLES: dict[str, str] = {
    # frameworks.ts:20-31, in order.
    "owasp:llm:01": "Prompt Injection",
    "owasp:llm:02": "Sensitive Information Disclosure",
    "owasp:llm:03": "Supply Chain",
    "owasp:llm:04": "Data and Model Poisoning",
    "owasp:llm:05": "Improper Output Handling",
    "owasp:llm:06": "Excessive Agency",
    "owasp:llm:07": "System Prompt Leakage",
    "owasp:llm:08": "Vector and Embedding Weaknesses",
    "owasp:llm:09": "Misinformation",
    "owasp:llm:10": "Unbounded Consumption",
}

NIST_AI_RMF: dict[str, list[str]] = {
    # frameworks.ts:396-485. All 21 MEASURE controls, verbatim.
    "nist:ai:measure:1.1": ["excessive-agency",
                            "harmful:misinformation-disinformation"],
    "nist:ai:measure:1.2": ["excessive-agency",
                            "harmful:misinformation-disinformation"],
    "nist:ai:measure:2.1": ["harmful:privacy", "pii:api-db", "pii:direct",
                            "pii:session", "pii:social"],
    "nist:ai:measure:2.2": ["harmful:privacy", "pii:api-db", "pii:direct",
                            "pii:session", "pii:social"],
    "nist:ai:measure:2.3": ["excessive-agency"],
    "nist:ai:measure:2.4": ["excessive-agency",
                            "harmful:misinformation-disinformation"],
    "nist:ai:measure:2.5": ["excessive-agency"],
    "nist:ai:measure:2.6": ["harmful:chemical-biological-weapons",
                            "harmful:indiscriminate-weapons",
                            "harmful:unsafe-practices"],
    "nist:ai:measure:2.7": ["harmful:cybercrime", "shell-injection",
                            "sql-injection"],
    "nist:ai:measure:2.8": ["bfla", "bola", "rbac"],
    "nist:ai:measure:2.9": ["excessive-agency"],
    "nist:ai:measure:2.10": ["harmful:privacy", "pii:api-db", "pii:direct",
                             "pii:session", "pii:social"],
    "nist:ai:measure:2.11": ["harmful:harassment-bullying", "harmful:hate",
                             "harmful:insults"],
    "nist:ai:measure:2.12": [],  # empty upstream
    "nist:ai:measure:2.13": ["excessive-agency"],
    "nist:ai:measure:3.1": ["excessive-agency",
                            "harmful:misinformation-disinformation"],
    "nist:ai:measure:3.2": ["excessive-agency"],
    "nist:ai:measure:3.3": ["excessive-agency"],
    "nist:ai:measure:4.1": ["excessive-agency"],
    "nist:ai:measure:4.2": ["excessive-agency",
                            "harmful:misinformation-disinformation"],
    "nist:ai:measure:4.3": ["excessive-agency"],
}

_ATLAS_AI_ATTACK_STAGING = ["ascii-smuggling", "excessive-agency",
                            "harmful:cybercrime:malicious-code", "hallucination",
                            "indirect-prompt-injection", "rag-poisoning"]

MITRE_ATLAS: dict[str, list[str]] = {
    # frameworks.ts:487-663. The legacy alias `mitre:atlas:ml-attack-staging`
    # (:660-663) points at the same list and is kept for configs predating the
    # tactic rename.
    "mitre:atlas:ai-attack-staging": list(_ATLAS_AI_ATTACK_STAGING),
    "mitre:atlas:ml-attack-staging": list(_ATLAS_AI_ATTACK_STAGING),
    "mitre:atlas:ai-model-access": [],  # empty upstream; see frameworks.ts:501
    "mitre:atlas:collection": ["data-exfil", "harmful:privacy", "pii:api-db",
                               "pii:direct", "pii:session", "pii:social",
                               "prompt-extraction", "rag-document-exfiltration"],
    "mitre:atlas:command-and-control": ["excessive-agency", "harmful:cybercrime",
                                        "harmful:cybercrime:malicious-code", "mcp",
                                        "shell-injection", "ssrf"],
    "mitre:atlas:credential-access": ["data-exfil", "harmful:privacy", "pii:api-db",
                                      "pii:direct", "pii:session", "pii:social",
                                      "prompt-extraction",
                                      "rag-document-exfiltration",
                                      "tool-discovery"],
    "mitre:atlas:defense-evasion": ["ascii-smuggling", "hijacking", "imitation",
                                    "rag-source-attribution",
                                    "special-token-injection"],
    "mitre:atlas:discovery": ["debug-access", "model-identification",
                              "prompt-extraction", "system-prompt-override",
                              "tool-discovery"],
    "mitre:atlas:execution": ["excessive-agency", "hijacking",
                              "indirect-prompt-injection", "mcp",
                              "shell-injection", "sql-injection", "ssrf",
                              "system-prompt-override", "tool-discovery"],
    "mitre:atlas:exfiltration": ["ascii-smuggling", "cross-session-leak",
                                 "data-exfil", "harmful:privacy",
                                 "indirect-prompt-injection", "pii:api-db",
                                 "pii:direct", "pii:session", "pii:social",
                                 "prompt-extraction",
                                 "rag-document-exfiltration"],
    "mitre:atlas:impact": ["divergent-repetition", "excessive-agency", "harmful",
                           "hijacking", "imitation", "reasoning-dos"],
    "mitre:atlas:initial-access": ["debug-access", "harmful:cybercrime",
                                   "indirect-prompt-injection", "mcp",
                                   "shell-injection", "sql-injection", "ssrf"],
    "mitre:atlas:lateral-movement": ["bfla", "bola", "harmful:cybercrime", "rbac"],
    "mitre:atlas:persistence": ["agentic:memory-poisoning", "cross-session-leak",
                                "indirect-prompt-injection", "rag-poisoning",
                                "system-prompt-override"],
    "mitre:atlas:privilege-escalation": ["bfla", "bola", "debug-access",
                                         "excessive-agency", "mcp", "rbac",
                                         "shell-injection",
                                         "system-prompt-override"],
    "mitre:atlas:reconnaissance": ["competitors", "model-identification", "policy",
                                   "prompt-extraction", "rbac"],
    "mitre:atlas:resource-development": [
        "harmful:chemical-biological-weapons", "harmful:cybercrime",
        "harmful:cybercrime:malicious-code", "harmful:illegal-drugs",
        "harmful:indiscriminate-weapons"],
}

EU_AI_ACT: dict[str, list[str]] = {
    # frameworks.ts:674-776. Art.5 prohibitions, then Annex III high-risk uses.
    "eu:ai-act:art5:subliminal-manipulation": [
        "hijacking", "intent", "excessive-agency",
        "harmful:misinformation-disinformation"],
    "eu:ai-act:art5:exploitation-of-vulnerabilities": [
        "hijacking", "imitation", "harmful:misinformation-disinformation",
        "bias:age", "bias:disability"],
    "eu:ai-act:art5:social-scoring": [
        "harmful:misinformation-disinformation", "overreliance", "bias:age",
        "bias:gender", "bias:race", "bias:disability"],
    "eu:ai-act:art5:biometric-categorisation": ["pii:direct", "pii:session",
                                                "harmful:privacy"],
    "eu:ai-act:art5:remote-biometric-id-live": ["pii:session", "pii:direct",
                                                "harmful:privacy"],
    "eu:ai-act:art5:remote-biometric-id-post": ["pii:api-db", "pii:direct",
                                                "harmful:privacy"],
    "eu:ai-act:annex3:biometric-id": ["pii:direct", "pii:session",
                                      "harmful:privacy"],
    "eu:ai-act:annex3:critical-infrastructure": ["shell-injection",
                                                 "sql-injection", "ssrf",
                                                 "excessive-agency"],
    "eu:ai-act:annex3:education": ["harmful:misinformation-disinformation",
                                   "hallucination", "overreliance", "bias:race",
                                   "bias:gender", "bias:disability"],
    "eu:ai-act:annex3:employment": ["imitation", "pii:direct", "overreliance",
                                    "bias:gender", "bias:race", "bias:age",
                                    "bias:disability"],
    "eu:ai-act:annex3:essential-services": ["pii:direct", "pii:session",
                                            "excessive-agency", "bias:race",
                                            "bias:gender"],
    "eu:ai-act:annex3:law-enforcement": ["pii:direct", "pii:api-db",
                                         "harmful:privacy", "bias:race"],
    "eu:ai-act:annex3:migration-border": ["pii:direct", "harmful:hate",
                                          "harmful:privacy", "bias:race"],
    "eu:ai-act:annex3:justice-democracy": [
        "hallucination", "harmful:misinformation-disinformation", "pii:direct",
        "bias:race", "bias:gender"],
}

ISO_42001: dict[str, list[str]] = {
    # frameworks.ts:782-831. Seven AIMS risk areas.
    "iso:42001:accountability": ["excessive-agency", "overreliance", "hijacking"],
    "iso:42001:fairness": ["bias:age", "bias:disability", "bias:gender",
                           "bias:race", "harmful:hate"],
    "iso:42001:privacy": ["harmful:privacy", "pii:api-db", "pii:direct",
                          "pii:session", "pii:social"],
    "iso:42001:robustness": ["ascii-smuggling", "prompt-extraction"],
    "iso:42001:security": ["shell-injection", "sql-injection", "ssrf",
                           "debug-access"],
    "iso:42001:safety": ["harmful:chemical-biological-weapons",
                         "harmful:child-exploitation", "harmful:violent-crime",
                         "harmful:cybercrime",
                         "harmful:cybercrime:malicious-code"],
    "iso:42001:transparency": ["harmful:misinformation-disinformation",
                               "hallucination", "imitation",
                               "unverifiable-claims", "politics", "religion"],
}

GDPR: dict[str, list[str]] = {
    # frameworks.ts:841-920. Eight articles.
    "gdpr:art5": ["harmful:privacy", "pii:api-db", "pii:direct", "pii:session",
                  "pii:social", "hallucination",
                  "harmful:misinformation-disinformation"],
    "gdpr:art9": ["pii:direct", "pii:social", "harmful:privacy", "bias:age",
                  "bias:disability", "bias:gender", "bias:race"],
    "gdpr:art15": ["pii:api-db", "pii:session", "rbac", "bola", "bfla"],
    "gdpr:art17": ["pii:api-db", "pii:direct", "pii:session", "harmful:privacy",
                   "cross-session-leak"],
    "gdpr:art22": ["bias:age", "bias:disability", "bias:gender", "bias:race",
                   "harmful:hate", "overreliance", "hallucination"],
    "gdpr:art25": ["harmful:privacy", "pii:api-db", "pii:direct", "pii:session",
                   "pii:social", "prompt-extraction"],
    "gdpr:art32": ["shell-injection", "sql-injection", "ssrf", "debug-access",
                   "harmful:cybercrime", "rbac", "bfla", "bola"],
}


# --------------------------------------------------------------------------- #
# 3. Strategies.
#
# Each promptfoo control maps to `{plugins, strategies}` (frameworks.ts:6). The
# plugin lists above are the *what*; the strategy lists are the *how*, and
# ignoring them loses real mappings. `jailbreak` is a strategy, not a plugin - so
# without this table a `security.jailbreak` finding maps to nothing under OWASP
# LLM Top 10, even though frameworks.ts:81 lists jailbreak strategies under
# owasp:llm:01. Transcribed from the same six blocks.
# --------------------------------------------------------------------------- #
STRATEGY_TO_CATEGORY: dict[str, tuple[str, ...]] = {
    # taxonomy.md:55 - "Attempt to subvert the agent's own guardrails/policy."
    "jailbreak": ("security.jailbreak",),
    "jailbreak-templates": ("security.jailbreak",),
    "jailbreak:composite": ("security.jailbreak",),
    "jailbreak:tree": ("security.jailbreak",),
    "crescendo": ("security.jailbreak",),
    # Encoding obfuscation. OpenGuardrails names obfuscation only inside
    # security.malicious_command (taxonomy.md:56), which is narrower than what
    # these strategies do, so they get the extension namespace.
    "base64": ("x.afni.encoding_obfuscation",),
    "rot13": ("x.afni.encoding_obfuscation",),
    "leetspeak": ("x.afni.encoding_obfuscation",),
}

_JB3 = ("jailbreak", "jailbreak-templates", "jailbreak:composite")
_JB2 = ("jailbreak", "jailbreak-templates")

CONTROL_STRATEGIES: dict[str, tuple[str, ...]] = {
    # frameworks.ts:81,94,113,118,131,144,156,166 (owasp:llm:03 and :10 empty)
    "owasp:llm:01": _JB3, "owasp:llm:02": _JB3, "owasp:llm:04": _JB3,
    "owasp:llm:05": _JB2, "owasp:llm:06": _JB3, "owasp:llm:07": _JB3,
    "owasp:llm:08": _JB3, "owasp:llm:09": _JB3,
    # frameworks.ts:399,403,419,435,463 - the only five NIST controls with any
    "nist:ai:measure:1.1": _JB2, "nist:ai:measure:1.2": _JB2,
    "nist:ai:measure:2.4": _JB2, "nist:ai:measure:2.7": _JB2,
    "nist:ai:measure:3.1": _JB2,
    # frameworks.ts:496,528,552,576,603,615,629,642
    "mitre:atlas:ai-attack-staging": ("jailbreak", "jailbreak:tree"),
    "mitre:atlas:ml-attack-staging": ("jailbreak", "jailbreak:tree"),
    "mitre:atlas:command-and-control": ("crescendo",),
    "mitre:atlas:defense-evasion": ("base64", "jailbreak", "jailbreak-templates",
                                    "leetspeak", "rot13"),
    "mitre:atlas:execution": _JB2,
    "mitre:atlas:impact": ("crescendo",),
    "mitre:atlas:initial-access": ("base64", "jailbreak", "leetspeak",
                                   "jailbreak-templates", "rot13"),
    "mitre:atlas:persistence": ("jailbreak",),
    "mitre:atlas:privilege-escalation": ("jailbreak", "jailbreak:tree",
                                         "jailbreak-templates"),
    # frameworks.ts:678,689,723
    "eu:ai-act:art5:subliminal-manipulation": (
        "jailbreak", "jailbreak:tree", "jailbreak:composite",
        "jailbreak-templates"),
    "eu:ai-act:art5:exploitation-of-vulnerabilities": ("jailbreak",),
    "eu:ai-act:annex3:critical-infrastructure": _JB2,
    # frameworks.ts:801,806,817
    "iso:42001:robustness": ("jailbreak", "jailbreak:composite",
                            "jailbreak:tree"),
    "iso:42001:security": ("jailbreak", "jailbreak:composite", "base64", "rot13"),
    "iso:42001:safety": ("jailbreak", "jailbreak:composite", "jailbreak:tree"),
    # GDPR: every article's strategy list is empty upstream.
}


@dataclass(frozen=True)
class Framework:
    """One framework, its controls, and how complete this port of it is."""

    key: str
    name: str
    controls: Mapping[str, Sequence[str]]
    evidence: str
    completeness: str
    caveat: str = ""

    @property
    def control_ids(self) -> list[str]:
        return list(self.controls)

    def strategies_for(self, control: str) -> tuple[str, ...]:
        return CONTROL_STRATEGIES.get(control, ())

    @property
    def evidenceable(self) -> list[str]:
        """Controls that at least one plugin or strategy - and therefore at least
        one AFNI category - can evidence. The difference between this and
        `control_ids` is the honest gap."""
        return [c for c, plugins in self.controls.items()
                if plugins or CONTROL_STRATEGIES.get(c)]


FRAMEWORKS: dict[str, Framework] = {
    "owasp:llm": Framework(
        key="owasp:llm", name="OWASP LLM Top 10",  # FRAMEWORK_NAMES :13
        controls=OWASP_LLM_TOP_10,
        evidence="promptfoo src/redteam/constants/frameworks.ts:74-173",
        completeness="full",
        caveat="owasp:llm:03 (Supply Chain) has no upstream plugins and no "
               "runtime finding can evidence it."),
    "nist:ai:measure": Framework(
        key="nist:ai:measure", name="NIST AI RMF",  # FRAMEWORK_NAMES :11
        controls=NIST_AI_RMF,
        evidence="promptfoo src/redteam/constants/frameworks.ts:396-485",
        completeness="full",
        caveat="All 21 MEASURE controls transcribed. nist:ai:measure:2.12 is "
               "empty upstream. GOVERN/MAP/MANAGE functions are process "
               "controls with no promptfoo mapping and are out of scope here."),
    "mitre:atlas": Framework(
        key="mitre:atlas", name="MITRE ATLAS",  # FRAMEWORK_NAMES :10
        controls=MITRE_ATLAS,
        evidence="promptfoo src/redteam/constants/frameworks.ts:487-663",
        completeness="partial",
        caveat="mitre:atlas:ai-model-access is empty upstream - frameworks.ts:501 "
               "states no promptfoo plugin validates model access level yet. "
               "Carried as a declared control with zero coverage."),
    "eu:ai-act": Framework(
        key="eu:ai-act", name="EU AI Act",  # FRAMEWORK_NAMES :15
        controls=EU_AI_ACT,
        evidence="promptfoo src/redteam/constants/frameworks.ts:674-776",
        completeness="partial",
        caveat="Art.5 prohibitions and Annex III high-risk uses only. Art.9 "
               "risk management, Art.12 logging, Art.13 transparency and Art.14 "
               "human oversight have no promptfoo mapping and cannot be "
               "evidenced by a detector finding - they are AFNI process "
               "controls."),
    "iso:42001": Framework(
        key="iso:42001", name="ISO/IEC 42001",  # FRAMEWORK_NAMES :16
        controls=ISO_42001,
        evidence="promptfoo src/redteam/constants/frameworks.ts:782-831",
        completeness="full",
        caveat="Seven AIMS risk areas as promptfoo models them; these are risk "
               "domains, not the standard's numbered Annex A controls."),
    "gdpr": Framework(
        key="gdpr", name="GDPR",  # FRAMEWORK_NAMES :17
        controls=GDPR,
        evidence="promptfoo src/redteam/constants/frameworks.ts:841-920",
        completeness="full",
        caveat="Eight articles as promptfoo maps them."),
}


@dataclass(frozen=True)
class ControlRef:
    """One control a finding evidences, and the plugin id that justified the
    link - so a reviewer can walk the chain back to frameworks.ts."""

    framework: str
    framework_name: str
    control: str
    title: str
    via_plugin: str   # the promptfoo plugin OR strategy id that justified it

    def __str__(self) -> str:
        return f"{self.control} ({self.framework_name})"


def _invert() -> dict[str, list[ControlRef]]:
    """category prefix -> the controls it evidences. Built once at import.

    Walks both tables: a control is evidenced by its plugins and by its
    strategies, because upstream splits the two and a finding does not care which
    side of that split named it.
    """
    out: dict[str, list[ControlRef]] = {}
    for fw in FRAMEWORKS.values():
        for control in fw.controls:
            sources = ([(p, PLUGIN_TO_CATEGORY) for p in fw.controls[control]]
                       + [(s, STRATEGY_TO_CATEGORY)
                          for s in CONTROL_STRATEGIES.get(control, ())])
            for name, table in sources:
                for prefix in table.get(name, ()):
                    ref = ControlRef(
                        framework=fw.key, framework_name=fw.name, control=control,
                        title=OWASP_LLM_TITLES.get(control, ""), via_plugin=name)
                    bucket = out.setdefault(prefix, [])
                    if not any(r.framework == ref.framework
                               and r.control == ref.control for r in bucket):
                        bucket.append(ref)
    return out


CATEGORY_TO_CONTROLS: dict[str, list[ControlRef]] = _invert()


@dataclass
class ComplianceReport:
    """The client approval pack, one framework at a time."""

    by_framework: dict[str, dict[str, int]] = field(default_factory=dict)
    unmapped: dict[str, int] = field(default_factory=dict)
    total_findings: int = 0

    def coverage(self, framework: str) -> tuple[int, int]:
        """(controls evidenced, controls that *could* be evidenced). Deliberately
        not "controls declared" - a control no plugin maps to is not a hole in
        AFNI's coverage, and counting it as one would understate the report just
        as badly as ignoring it overstates it."""
        fw = FRAMEWORKS[framework]
        hit = len(self.by_framework.get(framework, {}))
        return hit, len(fw.evidenceable)

    def render(self) -> str:
        lines = ["AFNI Responsible AI - compliance framework mapping",
                 f"findings mapped: {self.total_findings}", ""]
        for key, fw in FRAMEWORKS.items():
            hit, possible = self.coverage(key)
            declared = len(fw.control_ids)
            lines.append(f"{fw.name}  [{fw.completeness}]")
            lines.append(f"  controls evidenced by findings : {hit} / {possible} "
                         f"mappable  ({declared} declared upstream)")
            lines.append(f"  source                         : {fw.evidence}")
            for control, count in sorted(self.by_framework.get(key, {}).items()):
                title = OWASP_LLM_TITLES.get(control, "")
                suffix = f"  {title}" if title else ""
                lines.append(f"    {control:48s} {count:4d} finding(s){suffix}")
            if fw.caveat:
                lines.append(f"  CAVEAT: {fw.caveat}")
            lines.append("")
        if self.unmapped:
            lines.append("Findings in categories no framework maps (not a failure - "
                         "AFNI detects more than the frameworks name):")
            lines += [f"  {cat:48s} {n:4d}" for cat, n in sorted(self.unmapped.items())]
        return "\n".join(lines)


class ComplianceMapper:
    """`Finding.category` -> framework control ids, by longest-prefix match."""

    def __init__(self, mapping: Mapping[str, Sequence[ControlRef]] | None = None
                 ) -> None:
        self._mapping = dict(mapping or CATEGORY_TO_CONTROLS)

    def controls_for(self, category: str) -> list[ControlRef]:
        """Every control this category evidences.

        Matching is prefix-based and *cumulative up the path*: a finding at
        `privacy.pii.us_ssn` picks up everything mapped at `privacy.pii` and at
        `privacy` if either exists. That way a new subcategory added by another
        tenet is mapped the day it ships, with no edit here.
        """
        refs: list[ControlRef] = []
        seen: set[tuple[str, str]] = set()
        for prefix, controls in self._mapping.items():
            if category == prefix or category.startswith(prefix + "."):
                for ref in controls:
                    key = (ref.framework, ref.control)
                    if key not in seen:
                        seen.add(key)
                        refs.append(ref)
        return sorted(refs, key=lambda r: (r.framework, r.control))

    def frameworks_for(self, category: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for ref in self.controls_for(category):
            out.setdefault(ref.framework, []).append(ref.control)
        return out

    def report(self, categories: Iterable[str] | Mapping[str, int]
               ) -> ComplianceReport:
        """Build the approval pack from either a list of finding categories or a
        `{category: count}` mapping (what `VerdictStore.category_counts()`
        returns, so the pack comes straight out of the audit trail)."""
        if isinstance(categories, Mapping):
            counts = dict(categories)
        else:
            counts = {}
            for category in categories:
                counts[category] = counts.get(category, 0) + 1

        report = ComplianceReport(total_findings=sum(counts.values()))
        for category, n in counts.items():
            refs = self.controls_for(category)
            if not refs:
                report.unmapped[category] = report.unmapped.get(category, 0) + n
                continue
            for ref in refs:
                bucket = report.by_framework.setdefault(ref.framework, {})
                bucket[ref.control] = bucket.get(ref.control, 0) + n
        return report
