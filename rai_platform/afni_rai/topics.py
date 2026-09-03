# -*- coding: utf-8 -*-
"""
The topic policy: what an AFNI application will not discuss.

WHY THIS FILE EXISTS AT ALL

`TopicScopeRail` has been built and unit-tested since the first cut of this
platform, and it has been deliberately UNMOUNTED, because a topic list is a
business decision and not something that can be downloaded. Every reviewed tool
says the same thing in its own way - NeMo puts it in `config.yml`, DeepTeam takes
`TopicalGuard(allowed_topics=[...])` - and none of them ships a list.

So this file is the two halves of that decision, kept apart on purpose:

  ALWAYS      hard-coded here, cannot be switched off from the console. These are
              the topics where no AFNI application, in any line of business, has
              a legitimate reason to help. Changing one is a code change and a
              code review, which is the point.

  OPTIONAL    the catalogue an operator picks from in the console. Ships with
              NOTHING selected, because "what is off-topic" differs per
              application: a benefits helpdesk must discuss medical leave, and a
              billing bot must not.

WHAT THIS RAIL IS AND IS NOT

It is a Stage-1 word and phrase matcher. It is fast, free, deterministic, and it
runs on every message in both directions. It is NOT an understanding of intent -
that is Stage 2 and Stage 3. Two consequences worth stating before anyone reads
a tick-box as a guarantee:

  * A pattern can be evaded by paraphrase. "How do I make a bomb" is caught;
    an oblique request for the same thing is not. This is a floor, not a ceiling.
  * A pattern can fire on innocent text. Every phrase here was chosen to need
    at least two words precisely because single words are false-positive
    machines - `bomb` alone fires on "I bombed the interview".

ACTION, PER TOPIC

`always=True` topics BLOCK. They are phrased tightly enough that a match is not
plausibly innocent, and they are the cases where waiting for a second opinion is
the wrong trade.

Everything an operator ticks FLAGS by default and escalates - the message still
goes through, and the finding is recorded. An operator can promote a topic to
blocking in the console, and the console states the trade-off next to the
control, because a blocking keyword list is the easiest way to build a guardrail
that refuses ordinary work.

Zero third-party dependencies.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV_POLICY_PATH = "AFNI_TOPIC_POLICY"
DEFAULT_POLICY_FILENAME = "afni_topic_policy.json"


@dataclass(frozen=True)
class Topic:
    """One topic an application may refuse to discuss.

    `patterns` are matched by `TopicScopeRail`: a single word against the word
    set, anything containing a space as a phrase. Prefer phrases - see the
    module docstring on why bare words are false-positive machines.
    """

    id: str
    label: str
    group: str
    why: str                      # one line, in the operator's language
    patterns: tuple[str, ...]
    always: bool = False          # hard-coded ban; not switchable from the UI

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "group": self.group,
                "why": self.why, "always": self.always,
                "patterns": list(self.patterns)}


# --------------------------------------------------------------------------- #
# ALWAYS BANNED - hard-coded, six topics                                      #
#                                                                             #
# The test for inclusion here is deliberately strict: is there ANY AFNI line of #
# business where helping with this is legitimate? If the answer is "maybe",     #
# it belongs in the optional catalogue instead.                                #
# --------------------------------------------------------------------------- #
ALWAYS: tuple[Topic, ...] = (
    Topic("weapons_manufacture", "Making weapons or explosives", "Never",
          "No AFNI process needs instructions for building a weapon.",
          ("make a bomb", "build a bomb", "making a bomb", "build an explosive",
           "make an explosive", "pipe bomb", "improvised explosive",
           "how to make gunpowder", "3d printed gun", "untraceable firearm"),
          always=True),
    Topic("drug_synthesis", "Manufacturing illegal drugs", "Never",
          "Synthesis instructions, as distinct from a customer mentioning drugs.",
          ("how to make meth", "synthesise methamphetamine",
           "synthesize methamphetamine", "cook methamphetamine", "make fentanyl",
           "manufacture cocaine", "drug synthesis", "make illegal drugs",
           "recipe for creating illegal drugs"),
          always=True),
    Topic("malware", "Writing malware or ransomware", "Never",
          "Working malicious code, not a customer asking whether they have a virus.",
          ("write ransomware", "write a keylogger", "write malware",
           "create a virus that", "build a botnet", "credential stealer",
           "how to write a rootkit", "sql injection payload"),
          always=True),
    Topic("csae", "Child sexual abuse material", "Never",
          "Non-negotiable, in every jurisdiction and every line of business.",
          ("child sexual", "child porn", "csam", "sexualise a child",
           "sexualize a child", "underage sexual", "minor sexual content"),
          always=True),
    Topic("self_harm_method", "Methods of suicide or self-harm", "Never",
          "Methods only. A customer in distress must be routed to a human, not refused.",
          ("how to kill myself", "ways to kill myself", "how to commit suicide",
           "painless way to die", "lethal dose of", "how to hang myself"),
          always=True),
    Topic("trafficking", "Human trafficking and forced labour", "Never",
          "Includes advice on moving people or evading labour law by coercion.",
          ("human trafficking", "traffic people", "smuggle people",
           "forced labour scheme", "forced labor scheme", "sell a person"),
          always=True),
)


# --------------------------------------------------------------------------- #
# OPTIONAL CATALOGUE - twenty-four topics, none selected by default           #
#                                                                             #
# Grouped the way an operator thinks about them, not the way the code does.   #
# The `why` line is what appears under the tick-box, so it is written for      #
# somebody deciding, not for somebody debugging.                              #
# --------------------------------------------------------------------------- #
OPTIONAL: tuple[Topic, ...] = (
    # ---- Advice the business is not licensed to give ----------------------
    Topic("legal_advice", "Legal advice", "Regulated advice",
          "Interpreting a contract or advising on a dispute. Common, and a real liability.",
          ("legal advice", "should i sue", "can i sue", "is this legally binding",
           "am i liable", "take legal action", "breach of contract")),
    Topic("medical_advice", "Medical advice", "Regulated advice",
          "Diagnosing or recommending treatment. Leave on unless this IS a health service.",
          ("medical advice", "should i take", "diagnose my", "what medication",
           "is it safe to take", "recommended dosage", "my symptoms are")),
    Topic("financial_advice", "Investment and financial advice", "Regulated advice",
          "Recommending an investment. Regulated in most markets.",
          ("investment advice", "should i invest", "financial advice",
           "which stock", "will the market", "guaranteed return")),
    Topic("tax_advice", "Tax advice", "Regulated advice",
          "Filing, deductions or liability. Wrong answers here cost the customer money.",
          ("tax advice", "how much tax", "claim on my taxes", "tax deduction",
           "avoid paying tax", "tax loophole")),
    Topic("immigration_advice", "Immigration advice", "Regulated advice",
          "Visa and status questions. Regulated advice in most markets.",
          ("immigration advice", "visa application", "my visa status",
           "apply for asylum", "work permit")),
    Topic("insurance_advice", "Insurance claim advice", "Regulated advice",
          "Whether a claim will pay out, or how to word one.",
          ("will my claim", "insurance claim advice", "how to word my claim",
           "is this covered by my policy")),

    # ---- Commitments the AI must not make on AFNI's behalf ----------------
    Topic("refund_promise", "Promising refunds or credits", "Commitments",
          "An AI promising money creates an expectation somebody has to honour.",
          ("i will refund", "we will refund you", "guarantee a refund",
           "full refund guaranteed", "i can waive")),
    Topic("pricing_negotiation", "Negotiating price or discounts", "Commitments",
          "Discounting is a human decision with a margin attached.",
          ("special discount", "beat that price", "lowest price i can",
           "negotiate the price", "give you a discount")),
    Topic("contract_commitment", "Committing to contract terms", "Commitments",
          "Agreeing to terms, dates or SLAs on the record.",
          ("i commit to", "we guarantee delivery", "contractually agree",
           "i promise that we will", "sign on behalf of")),
    Topic("employment_terms", "Employment terms and HR matters", "Commitments",
          "Salary, notice, disciplinary matters. For an internal bot, consider leaving off.",
          ("my salary", "notice period", "disciplinary action", "am i being fired",
           "grievance procedure", "redundancy package")),

    # ---- Content that damages the brand -----------------------------------
    Topic("competitors", "Discussing competitors", "Brand",
          "Comparing AFNI or a client to a named competitor.",
          ("compared to your competitor", "better than your competitor",
           "why should i not switch", "competitor pricing")),
    Topic("politics", "Politics and elections", "Brand",
          "No upside, real downside. Usually left on.",
          ("who should i vote", "which political party", "the election result",
           "political opinion", "your political view")),
    Topic("religion", "Religion", "Brand",
          "Same reasoning as politics.",
          ("religious belief", "which religion", "is god real",
           "your religious view")),
    Topic("adult_content", "Adult and sexual content", "Brand",
          "Between consenting adults, but not in a customer-service transcript.",
          ("sexually explicit", "adult content", "erotic story", "nsfw content")),
    Topic("dating_romantic", "Romantic or personal advances", "Brand",
          "Customers do this to chatbots. It should be deflected, not engaged.",
          ("are you single", "do you love me", "be my girlfriend",
           "be my boyfriend", "i love you bot")),
    Topic("gambling", "Gambling and betting", "Brand",
          "Odds, tips or placing bets.",
          ("betting odds", "place a bet", "gambling tips", "which horse should i",
           "casino strategy")),
    Topic("crypto", "Cryptocurrency", "Brand",
          "Prices, wallets and transfers. Often paired with a scam.",
          ("crypto wallet", "send bitcoin", "buy cryptocurrency",
           "crypto investment", "seed phrase")),
    Topic("alcohol_tobacco", "Alcohol, tobacco and vaping", "Brand",
          "Age-restricted goods, which some clients require kept out entirely.",
          ("buy cigarettes", "where to buy alcohol", "vape juice",
           "underage drinking")),

    # ---- Safety and abuse --------------------------------------------------
    Topic("hate_speech", "Slurs and hate speech", "Safety",
          "Content attacking a protected characteristic.",
          ("racial slur", "hate speech", "all muslims are", "all jews are",
           "people of that race are")),
    Topic("violence_threat", "Threats of violence", "Safety",
          "A threat against a person, including AFNI staff.",
          ("i will kill you", "i will hurt you", "going to find you",
           "threaten your family", "shoot up the")),
    Topic("weapons_sales", "Buying or selling weapons", "Safety",
          "Distinct from manufacture, which is always banned.",
          ("buy a gun", "sell my firearm", "where to get a gun",
           "buy ammunition", "unregistered weapon")),

    # ---- Internal information ----------------------------------------------
    Topic("internal_systems", "Internal systems and infrastructure",
          "Internal information",
          "Server names, database schemas, internal tooling. Reconnaissance.",
          ("internal database", "your server name", "production credentials",
           "internal api endpoint", "which database do you use")),
    Topic("other_customers", "Other customers' information",
          "Internal information",
          "Any request for data belonging to somebody else. Often a real attack.",
          ("another customer", "other customers data", "list all customers",
           "someone else's account", "previous caller")),
    Topic("credentials_request", "Asking for passwords or credentials",
          "Internal information",
          "A legitimate service never asks. Catching it catches phishing scripts.",
          ("tell me your password", "give me the api key", "what is the admin password",
           "share your credentials", "send me the token")),
)


CATALOGUE: tuple[Topic, ...] = ALWAYS + OPTIONAL
BY_ID: dict[str, Topic] = {t.id: t for t in CATALOGUE}


def groups() -> list[str]:
    """Group names in catalogue order, deduplicated."""
    seen: dict[str, None] = {}
    for t in CATALOGUE:
        seen.setdefault(t.group, None)
    return list(seen)


# --------------------------------------------------------------------------- #
# The policy file                                                             #
#                                                                             #
# A JSON file on the server, NOT a request field. Which topics an application  #
# refuses is a deployment decision, and a caller who could set it per request  #
# could route around it - the same reasoning that keeps AFNI_REVEAL_SUBJECT    #
# server-side.                                                                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Policy:
    """What the operator has chosen. `always` topics are not represented here -
    they are not switchable, so storing them would imply they were."""

    enabled: frozenset[str] = frozenset()
    blocking: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": sorted(self.enabled), "blocking": sorted(self.blocking)}


def policy_path() -> Path:
    """Where the policy lives. `AFNI_TOPIC_POLICY` overrides."""
    override = os.environ.get(ENV_POLICY_PATH, "").strip()
    return Path(override) if override else Path(DEFAULT_POLICY_FILENAME)


def load_policy(path: Path | None = None) -> Policy:
    """Read the policy. A missing or unreadable file is an EMPTY policy.

    Empty rather than an exception, and that is a deliberate asymmetry worth
    stating: a corrupt policy file must not stop the gateway booting, because the
    six ALWAYS topics do not come from the file and would be lost with it. An
    unreadable file therefore degrades to "nothing optional is enabled", which is
    the shipped default, and `/v1/topics` reports the read error so it is visible
    rather than silent.
    """
    p = policy_path() if path is None else path
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Policy()
    if not isinstance(raw, dict):
        return Policy()
    known = {t.id for t in OPTIONAL}
    enabled = {t for t in raw.get("enabled", []) if t in known}
    # Blocking only means anything for a topic that is also enabled.
    blocking = {t for t in raw.get("blocking", []) if t in enabled}
    return Policy(frozenset(enabled), frozenset(blocking))


def save_policy(policy: Policy, path: Path | None = None) -> None:
    p = policy_path() if path is None else path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(policy.to_dict(), indent=2) + "\n", encoding="utf-8")


def patterns_for(policy: Policy) -> tuple[list[str], list[str]]:
    """(flagging patterns, blocking patterns) for a `TopicScopeRail`.

    The six ALWAYS topics are always in the blocking list. They are added here
    rather than in the file so that deleting the policy file cannot disable them.
    """
    blocking: list[str] = []
    flagging: list[str] = []
    for t in ALWAYS:
        blocking.extend(t.patterns)
    for t in OPTIONAL:
        if t.id not in policy.enabled:
            continue
        (blocking if t.id in policy.blocking else flagging).extend(t.patterns)
    return flagging, blocking


def summary(policy: Policy | None = None) -> dict[str, Any]:
    """The whole catalogue plus what is selected - what `GET /v1/topics` returns."""
    pol = load_policy() if policy is None else policy
    flagging, blocking = patterns_for(pol)
    return {
        "policy_path": str(policy_path()),
        "policy_exists": policy_path().exists(),
        "groups": groups(),
        "always": [t.to_dict() for t in ALWAYS],
        "optional": [dict(t.to_dict(),
                          enabled=t.id in pol.enabled,
                          blocking=t.id in pol.blocking) for t in OPTIONAL],
        "counts": {
            "always": len(ALWAYS),
            "optional_available": len(OPTIONAL),
            "optional_enabled": len(pol.enabled),
            "promoted_to_blocking": len(pol.blocking),
            "flagging_patterns": len(flagging),
            "blocking_patterns": len(blocking),
        },
    }
