# -*- coding: utf-8 -*-
"""
Profanity / Content Safety rails.

The tenet principle from `knowledge/tenets.md` is "don't overpay for commodity
checks - profanity filtering is free in five or more of the reviewed tools". So
the honest Stage-1 win here is a *good* banned-word filter plus the canonical
harm taxonomy, and the money goes on the harder problems. Everything in this
module that runs today is pure stdlib; everything that needs a model imports it
lazily and says `unjudged` when it is absent.

Three things make this filter better than the wordlists it is built from:

1. **Whole-token matching, ported from `better_profanity`.** The upstream
   scanner walks the text character by character and only ever compares a
   *complete* token against the wordset
   (`better_profanity/better_profanity.py:168-214`, vendored in the Infosys
   toolkit at
   `responsible-ai-safety/responsible-ai-toxicity/lib/better_profanity-2.0.0-py3-none-any.whl`).
   That is what stops the Scunthorpe problem, and it is why "assessment",
   "classic", "Cockburn" and "Scunthorpe" cannot match. Substring matching on a
   profanity list is the single most common way this check is got wrong.

2. **Severity and category are data, not opinion.** garak ships the only graded
   list in the whole review -
   `garak-main/garak/data/ofcom-potentially-offensive.txt`, 150 rows of
   `category<TAB>term<TAB>strength(0-4)` across six categories. Strength drives
   the tier (block vs flag) and category drives the OpenGuardrails id. A slur
   and a mild expletive are genuinely not the same finding, and here they are
   not treated as one.

3. **A named ambiguity tier that deliberately does not fire.** The vendored
   lists contain terms with a common benign register - `div` (an HTML element),
   `prod` (a production environment), `nonce` (a cryptographic nonce), `git`
   (the version control system), `ginger`, `tart`, `slope`, `spade`, `mental`,
   `special`. Flagging those in a corporate gateway is a false-positive storm,
   and a profanity filter with a bad false-positive rate is worse than none. So
   they are held in `_AMBIGUOUS`, produce **no finding at all**, and instead ask
   the cascade to escalate to the Stage-2 context-aware classifier. That is the
   whole cascade argument applied to a wordlist.

The raw source lists are *not* used as-is, on purpose. Infosys' 917-row
`wordlist.csv` alone contains `len`, `pot`, `god`, `kill`, `fat`, `pawn`, `xx`,
`hemp`, `niggle` and `omg`; a gateway that blocked those would be unusable, and
`len` would fire on every line of Python that reaches it. The tier tables below
are built from the *intersection* of Infosys' list with garak's LDNOOBW list -
159 terms confirmed by two independent sources - plus garak's graded OFCOM
table, minus the curated ambiguity set. Fewer terms, defensible provenance,
far fewer false positives.

Sources ported (all under `references/`):

  Infosys-Responsible-AI-Toolkit-master
    responsible-ai-safety/responsible-ai-toxicity/data/wordlist.csv        917 rows
    responsible-ai-safety/responsible-ai-toxicity/src/profanity/util/profanity_wordlist.txt  916 rows
    responsible-ai-safety/responsible-ai-toxicity/src/profanity/service/service.py:80,288
    responsible-ai-safety/responsible-ai-toxicity/lib/better_profanity-2.0.0-py3-none-any.whl
  garak-main
    garak/data/ofcom-potentially-offensive.txt                             150 graded rows
    garak/data/ldnoobw-en.txt                                              403 rows
  llm-guard-main
    llm_guard/input_scanners/ban_substrings.py:38-49                       MatchType STR/WORD
    llm_guard/input_scanners/toxicity.py:13-36                             unitary/unbiased-toxic-roberta
    llm_guard/input_scanners/ban_topics.py:80-90,104                       roberta-base-zeroshot-v2.0-c
  openguardrails-main
    specification/taxonomy.md:10-26                                        the 11 safety.* ids
  hai-guardrails-main
    src/guards/profanity.guard.ts:21-27, src/guards/adult-content.guard.ts:21-27
  Guardrails-develop (NeMo)
    docs/configure-rails/guardrail-catalog/content-safety.mdx:11,25,31,67,180
    docs/configure-rails/guardrail-catalog/topic-control.mdx:25
  promptfoo-main
    src/redteam/constants/plugins.ts:55-79                                 26 harmful:* ids
    src/redteam/constants/plugins.ts:327-431                               dataset plugins
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Sequence

from ...cascade.rail import RailResult, RailSpec, Stage
from ...contract.explanation import RailAttribution
from ...contract.models import Action, Finding, Severity, Tenet

TENET = Tenet.CONTENT_SAFETY

# ============================================================== taxonomy ====
# The canonical multi-category harm taxonomy. A faithful port of the `safety.*`
# table at references/openguardrails-main/openguardrails-main/specification/
# taxonomy.md:10-26, plus the refinement subcategories the same file's
# "Reference moderation mapping" section defines at lines ~175-190.
#
# This is the mapper every other rail in the platform should emit through, which
# is why it lives here as pure data rather than inside one rail: a detector's
# native label set is a vendor artefact, and the whole reason AFNI adopted the
# OpenGuardrails contract was so that policy is written once against neutral
# ids. `safety.sexual.minors` is marked always-block by the spec itself.

SAFETY_CATEGORIES: dict[str, str] = {
    "safety.toxicity": "Harassment, hate, demeaning content.",
    "safety.toxicity.hate": "Identity-directed slur or hate speech.",
    "safety.toxicity.profanity": "Profane or obscene language.",
    "safety.toxicity.harassment": "Targeted insult or harassment.",
    "safety.self_harm": "Self-harm / suicide promotion or instructions.",
    "safety.sexual": "Sexual content.",
    "safety.sexual.minors": "CSAM - the spec marks this always block.",
    "safety.violence": "Violent threats or instructions.",
    "safety.violence.threat": "An explicit threat of violence.",
    "safety.weapons": "Illicit weapons / CBRN uplift.",
    "safety.illicit": "Other illicit-activity facilitation.",
    "safety.illicit.commercial": "Illicit commercial activity.",
    "safety.illicit.ip": "Intellectual-property infringement.",
    "safety.illicit.sexual_crime": "Sexual crime facilitation.",
    "safety.pii": "Personal data uttered in generated content.",
    "safety.brand": "Brand-safety / off-policy persona.",
    "safety.topic_violation": "Out-of-scope topic for a constrained agent.",
    "safety.hallucination": "Unsupported factual claim.",
    "safety.unsafe_advice": "Harmful confident guidance in a high-stakes domain.",
}

# The 11 top-level ids the spec's table declares, in spec order. Kept separate
# from the refinements so a test can assert we did not quietly drop one.
SAFETY_ROOTS: tuple[str, ...] = (
    "safety.toxicity", "safety.self_harm", "safety.sexual", "safety.violence",
    "safety.weapons", "safety.illicit", "safety.pii", "safety.brand",
    "safety.topic_violation", "safety.hallucination", "safety.unsafe_advice",
)

# Vendor label -> neutral id. Every key is a label string that actually appears
# in the vendored source; nothing here is invented.
VENDOR_LABEL_MAP: dict[str, str] = {
    # unitary/unbiased-toxic-roberta head labels, llm-guard
    # llm_guard/input_scanners/toxicity.py:28-36
    "toxicity": "safety.toxicity",
    "severe_toxicity": "safety.toxicity",
    "obscene": "safety.toxicity.profanity",
    "threat": "safety.violence.threat",
    "insult": "safety.toxicity.harassment",
    "identity_attack": "safety.toxicity.hate",
    "sexual_explicit": "safety.sexual",
    # garak ofcom-potentially-offensive.txt column 1
    "general": "safety.toxicity.profanity",
    "sexual": "safety.sexual",
    "raceethnic": "safety.toxicity.hate",
    "sexgender": "safety.toxicity.hate",
    "discriminatory": "safety.toxicity.hate",
    "mentalhealth": "safety.toxicity.hate",
    # promptfoo redteam plugin ids, src/redteam/constants/plugins.ts:55-79
    "harmful:hate": "safety.toxicity.hate",
    "harmful:harassment-bullying": "safety.toxicity.harassment",
    "harmful:insults": "safety.toxicity.harassment",
    "harmful:profanity": "safety.toxicity.profanity",
    "harmful:graphic-content": "safety.violence",
    "harmful:violent-crime": "safety.violence",
    "harmful:self-harm": "safety.self_harm",
    "harmful:sexual-content": "safety.sexual",
    "harmful:child-exploitation": "safety.sexual.minors",
    "harmful:sex-crime": "safety.illicit.sexual_crime",
    "harmful:chemical-biological-weapons": "safety.weapons",
    "harmful:indiscriminate-weapons": "safety.weapons",
    "harmful:weapons:ied": "safety.weapons",
    "harmful:illegal-activities": "safety.illicit",
    "harmful:illegal-drugs": "safety.illicit",
    "harmful:illegal-drugs:meth": "safety.illicit",
    "harmful:non-violent-crime": "safety.illicit",
    "harmful:cybercrime": "safety.illicit",
    "harmful:cybercrime:malicious-code": "safety.illicit",
    "harmful:radicalization": "safety.illicit",
    "harmful:copyright-violations": "safety.illicit.ip",
    "harmful:intellectual-property": "safety.illicit.ip",
    "harmful:privacy": "safety.pii",
    "harmful:misinformation-disinformation": "safety.hallucination",
    "harmful:specialized-advice": "safety.unsafe_advice",
    "harmful:unsafe-practices": "safety.unsafe_advice",
    # Infosys nsfw_model output classes, responsible-ai-safety/
    # responsible-ai-toxicity/src/profanity/util/nsfw_model/nsfw_detector/predict.py
    "porn": "safety.sexual",
    "hentai": "safety.sexual",
    "sexy": "safety.sexual",
    # llm-guard BanTopics has no label set of its own - the topics are supplied
    # by the caller, so a hit is a topic violation by construction.
    "banned_topic": "safety.topic_violation",
}


def map_category(vendor_label: str, default: str = "safety.toxicity") -> str:
    """Neutral OpenGuardrails id for one vendor label.

    Unknown labels fall back to `default` rather than being invented into a new
    id, because the taxonomy is a shared vocabulary: a detector that mints its
    own bucket makes the compliance rollup unanswerable. Callers that genuinely
    need a new class put it under `x.afni.*` themselves.
    """
    return VENDOR_LABEL_MAP.get(vendor_label.strip().lower(), default)


def rollup(category: str) -> str:
    """The spec's hierarchical rollup rule (taxonomy.md, "Conventions"): a
    consumer meeting an unknown id falls back to its longest known prefix."""
    parts = category.split(".")
    while len(parts) > 1:
        candidate = ".".join(parts)
        if candidate in SAFETY_CATEGORIES:
            return candidate
        parts.pop()
    return category


# ========================================================== lexicon data ====
# garak/data/ofcom-potentially-offensive.txt, ported verbatim: (category, term,
# strength). Strength 0-4 is OFCOM's own audience-research grading; it is the
# only severity signal in any wordlist in the whole 23-repo review.
_OFCOM: tuple[tuple[str, str, int], ...] = (
    ("general", "arse", 1),
    ("general", "arsehole", 2),
    ("general", "balls", 2),
    ("general", "bastard", 3),
    ("general", "beaver", 3),
    ("general", "beef curtains", 3),
    ("general", "bellend", 3),
    ("general", "bint", 2),
    ("general", "bitch", 2),
    ("general", "bloodclaat", 3),
    ("general", "bloody", 1),
    ("general", "bollocks", 2),
    ("general", "bugger", 1),
    ("general", "bullshit", 2),
    ("general", "clunge", 3),
    ("general", "cock", 3),
    ("general", "cow", 1),
    ("general", "crap", 1),
    ("general", "cunt", 4),
    ("general", "damn", 1),
    ("general", "dick", 3),
    ("general", "dickhead", 3),
    ("general", "fanny", 3),
    ("general", "feck", 2),
    ("general", "effing", 2),
    ("general", "flaps", 3),
    ("general", "fuck", 4),
    ("general", "gash", 3),
    ("general", "ginger", 1),
    ("general", "git", 1),
    ("general", "god", 1),
    ("general", "goddam", 1),
    ("general", "jesus christ", 1),
    ("general", "knob", 3),
    ("general", "minge", 3),
    ("general", "minger", 1),
    ("general", "motherfucker", 4),
    ("general", "munter", 2),
    ("general", "pissed", 2),
    ("general", "pissed off", 2),
    ("general", "prick", 3),
    ("general", "punani", 3),
    ("general", "pussy", 3),
    ("general", "shit", 2),
    ("general", "snatch", 3),
    ("general", "sod-off", 1),
    ("general", "son of a bitch", 2),
    ("general", "tits", 2),
    ("general", "twat", 3),
    ("sexual", "bonk", 1),
    ("sexual", "bukkake", 3),
    ("sexual", "cocksucker", 3),
    ("sexual", "dildo", 3),
    ("sexual", "ho", 3),
    ("sexual", "jizz", 3),
    ("sexual", "nonce", 3),
    ("sexual", "prickteaser", 3),
    ("sexual", "rapey", 3),
    ("sexual", "shag", 2),
    ("sexual", "skank", 3),
    ("sexual", "slag", 3),
    ("sexual", "slapper", 2),
    ("sexual", "slut", 3),
    ("sexual", "tart", 2),
    ("sexual", "wanker", 3),
    ("sexual", "whore", 3),
    ("discriminatory", "coffin dodger", 1),
    ("discriminatory", "fop", 2),
    ("discriminatory", "fucking old person", 2),
    ("discriminatory", "old bag", 1),
    ("discriminatory", "fenian", 3),
    ("discriminatory", "kafir", 2),
    ("discriminatory", "kufaar", 3),
    ("discriminatory", "kike", 3),
    ("discriminatory", "papist", 3),
    ("discriminatory", "prod", 3),
    ("discriminatory", "taig", 3),
    ("discriminatory", "yid", 3),
    ("sexgender", "batty boy", 4),
    ("sexgender", "bender", 3),
    ("sexgender", "bum boy", 3),
    ("sexgender", "bumclat", 3),
    ("sexgender", "bummer", 2),
    ("sexgender", "chi-chi man", 4),
    ("sexgender", "chick with a dick", 4),
    ("sexgender", "dyke", 3),
    ("sexgender", "faggot", 4),
    ("sexgender", "fairy", 2),
    ("sexgender", "fudge-packer", 4),
    ("sexgender", "gay", 0),
    ("sexgender", "gender bender", 4),
    ("sexgender", "he-she", 3),
    ("sexgender", "homo", 3),
    ("sexgender", "lezza", 3),
    ("sexgender", "lesbo", 3),
    ("sexgender", "muff diver", 3),
    ("sexgender", "nancy", 3),
    ("sexgender", "pansy", 2),
    ("sexgender", "poof", 3),
    ("sexgender", "queer", 3),
    ("sexgender", "rugmuncher", 3),
    ("sexgender", "carpetmuncher", 3),
    ("sexgender", "shirt lifter", 4),
    ("sexgender", "tranny", 3),
    ("mentalhealth", "cretin", 1),
    ("mentalhealth", "cripple", 3),
    ("mentalhealth", "div", 1),
    ("mentalhealth", "loony", 1),
    ("mentalhealth", "mental", 1),
    ("mentalhealth", "midget", 2),
    ("mentalhealth", "mong", 4),
    ("mentalhealth", "nutter", 1),
    ("mentalhealth", "psycho", 1),
    ("mentalhealth", "retard", 4),
    ("mentalhealth", "schizo", 2),
    ("mentalhealth", "spastic", 4),
    ("mentalhealth", "spakka", 4),
    ("mentalhealth", "spaz", 4),
    ("mentalhealth", "special", 2),
    ("mentalhealth", "vegetable", 2),
    ("mentalhealth", "window licker", 4),
    ("raceethnic", "chinky", 4),
    ("raceethnic", "choc ice", 3),
    ("raceethnic", "coloured", 2),
    ("raceethnic", "coon", 4),
    ("raceethnic", "darky", 4),
    ("raceethnic", "dago", 3),
    ("raceethnic", "gippo", 2),
    ("raceethnic", "golliwog", 4),
    ("raceethnic", "gook", 3),
    ("raceethnic", "jock", 1),
    ("raceethnic", "honky", 3),
    ("raceethnic", "hun", 1),
    ("raceethnic", "jap", 3),
    ("raceethnic", "kraut", 2),
    ("raceethnic", "nazi", 1),
    ("raceethnic", "negro", 3),
    ("raceethnic", "nigger", 4),
    ("raceethnic", "nig-nog", 4),
    ("raceethnic", "paki", 4),
    ("raceethnic", "pikey", 2),
    ("raceethnic", "polack", 3),
    ("raceethnic", "raghead", 3),
    ("raceethnic", "sambo", 4),
    ("raceethnic", "slope", 3),
    ("raceethnic", "spade", 3),
    ("raceethnic", "spic", 3),
    ("raceethnic", "taff", 2),
    ("raceethnic", "wog", 4),
    ("raceethnic", "wop", 3),
)

_IDENTITY_CATEGORIES = frozenset(
    {"raceethnic", "sexgender", "discriminatory", "mentalhealth"})

# --------------------------------------------------------------------------
# The terms confirmed by BOTH Infosys' wordlist.csv and garak's ldnoobw-en.txt
# (159 of them), hand-partitioned into the three content classes the taxonomy
# distinguishes plus the ambiguity tier. Neither source ships a category or a
# severity, so the partition is ours - and it is written out term by term
# precisely so a reviewer can argue with an individual call instead of having to
# trust an opaque heuristic.
_SLUR_CONFIRMED: tuple[str, ...] = (
    "coon", "faggot", "fudgepacker", "kike", "negro", "nigga", "nigger",
    "paki", "spic", "wetback", "shemale", "carpet muncher",
)

_EXPLICIT_CONFIRMED: tuple[str, ...] = (
    "2 girls 1 cup", "auto erotic", "autoerotic", "bdsm", "beastiality",
    "bestiality", "blow job", "blowjob", "blue waffle", "bondage", "boner",
    "booty call", "brown showers", "bukkake", "busty", "butthole", "clit",
    "cock", "cocks", "cum", "cumming", "cumshot", "cunnilingus", "deep throat",
    "deepthroat", "dick", "dildo", "dog style", "doggie style", "doggiestyle",
    "doggy style", "doggystyle", "ejaculation", "felch", "fellatio", "feltch",
    "femdom", "fingering", "fisting", "footjob", "futanari", "g-spot",
    "gang bang", "gangbang", "goatse", "gokkun", "golden shower", "hand job",
    "handjob", "hentai", "homoerotic", "humping", "jack off", "jerk off",
    "jizz", "kinbaku", "kinky", "masturbate", "masturbating", "masturbation",
    "milf", "nympho", "orgasm", "orgy", "panties", "panty", "pedo",
    "pedophile", "pissing", "poon", "poontang", "porn", "porno", "pornography",
    "pussy", "queaf", "queef", "quim", "rimjob", "rimming", "sadism",
    "schlong", "shibari", "shota", "slut", "smut", "spooge", "strip club",
    "threesome", "throating", "titties", "titty", "tits", "tubgirl", "twat",
    "voyeur", "vulva", "wank", "whore", "xxx", "yaoi",
)

_PROFANITY_CONFIRMED: tuple[str, ...] = (
    "arsehole", "ass", "asshole", "assmunch", "bastard", "bimbos", "bitch",
    "bitches", "bullshit", "cunt", "fuck", "fuckin", "fucking", "motherfucker",
    "shit", "shitty", "tosser",
)

# --------------------------------------------------------------------------
# Misspelling and obfuscation families harvested from Infosys' wordlist.csv for
# the highest-value stems only. Deliberately *not* generated by prefix match:
# `niggle` and `niglet` sit next to `nigga` in that file, and `fag`/`fagged`
# are ordinary British English for a cigarette and for being tired. Those are
# excluded here and appear in `_AMBIGUOUS` instead.
_VARIANTS: dict[str, tuple[str, ...]] = {
    "fuck": (
        "fcuk", "fcuker", "fcuking", "fuck-ass", "fuck-bitch", "fuck-tard",
        "fucka", "fuckass", "fucked", "fucker", "fuckers", "fuckface",
        "fuckhead", "fuckheads", "fuckhole", "fuckings", "fuckme", "fuckmeat",
        "fucknugget", "fucknut", "fuckoff", "fuckpuppet", "fucks", "fucktard",
        "fucktoy", "fuckup", "fuckwad", "fuckwhit", "fuckwit", "fuk", "fuker",
        "fukker", "fukkin", "fukking", "fuks", "fux", "fux0r", "fvck", "fxck",
        "phuck", "phuk", "phuked", "phuking", "phukked", "phukking", "phuks",
        "phuq", "mofo", "m0fo", "mof0", "m0f0",
    ),
    "shit": (
        "sh!+", "sh!t", "sh1t", "shi+", "shitdick", "shite", "shiteater",
        "shited", "shitey", "shitface", "shitfuck", "shitfucker", "shitfull",
        "shithead", "shithole", "shithouse", "shiting", "shitings", "shits",
        "shitt", "shitted", "shitter", "shitters", "shitting", "shittings",
    ),
    "cunt": ("cnut", "cuntlicker", "cuntlicking", "cunts"),
    "nigger": ("n1gga", "n1gger", "nigg3r", "nigg4h", "niggah", "niggas",
               "niggaz", "niggers"),
    "faggot": ("fagg", "faggit", "faggitt", "faggot", "faggots", "faggs",
               "fagot", "fagots", "faigt"),
    "arse": ("4r5e", "arrse", "arses", "arsehole", "arseholes"),
    "ass": ("ass-fucker", "assbang", "assbanged", "assfuck", "assfucker",
            "assfukka", "assholes", "asswhole"),
    "twat": ("tw4t", "twathead", "twats", "twatty"),
    "whore": ("hoar", "hoer", "hoore", "whoar", "whores"),
    "penis": (),   # left empty on purpose - see _AMBIGUOUS
}

# --------------------------------------------------------------------------
# The ambiguity tier. Every entry appears in one of the three vendored lists and
# is deliberately NOT reported: each has a routine benign register in the kind of
# text an enterprise gateway actually sees. A hit here produces no finding and
# asks the cascade to escalate, so a context-aware Stage-2 classifier decides.
#
# This table is the single most important thing in this module. Without it the
# filter fires on an HTML `div`, a `prod` deploy, a cryptographic `nonce`, a
# `git` command, an anatomy term in a clinical note, and "slope" in any piece of
# maths - and a check nobody can leave switched on is not a control.
_AMBIGUOUS: dict[str, str] = {
    # software / engineering vocabulary
    "div": "HTML element and CSS selector",
    "prod": "production environment",
    "nonce": "cryptographic nonce",
    "git": "the version-control system",
    "knob": "a physical control; 'knob' in hardware docs",
    "flaps": "aircraft control surface",
    "retard": "'retard' the ignition timing; the Airbus RETARD callout",
    "slope": "gradient of a line",
    "spade": "a tool and a card suit",
    "special": "'special report', 'special case'",
    "mental": "'mental model'",
    "vegetable": "food",
    "cripple": "'cripple the network'",
    "balls": "ball bearings, 'on the ball'",
    "snatch": "'snatch victory'; the weightlifting lift",
    "spunk": "courage, in US English",
    # names, places, animals, plants
    "beaver": "the animal",
    "cow": "the animal",
    "ginger": "the spice",
    "tart": "a pastry",
    "tit": "the bird, and 'tit for tat'",
    "nancy": "a given name",
    "taff": "a given name and a river",
    "jock": "a given name; jockstrap",
    "hun": "Attila the Hun; a term of endearment",
    "fairy": "folklore",
    "pansy": "the flower",
    "shag": "shag carpet, shag tobacco, the cormorant",
    "bonk": "to collide; the cycling term",
    "bender": "a pipe bender",
    "bummer": "a mild interjection",
    "hooker": "the rugby position, and a surname",
    "dyke": "an embankment, and the surname Van Dyke",
    "fag": "British English for a cigarette",
    "fags": "British English for cigarettes",
    "fagged": "British English for exhausted",
    "fagging": "British English for tiring work",
    "niggle": "a minor persistent doubt - unrelated etymology",
    "niglet": "excluded with 'niggle': too close to a benign token to risk",
    "ho": "'ho ho ho'; the abbreviation for a scale gauge",
    "homo": "'Homo sapiens'",
    "gay": "OFCOM grades this 0; neutral and reclaimed usage",
    "queer": "reclaimed, and standard in academic usage",
    "nazi": "legitimate historical and educational reference",
    "coloured": "British spelling of colored; 'coloured pencils'",
    "god": "religious reference",
    "jesus christ": "religious reference",
    "fop": "an archaic word for a dandy",
    # clinical and legal registers - a healthcare or compliance payload is full
    # of these, and a gateway that flags them cannot be left switched on
    "anal": "clinical anatomy",
    "anus": "clinical anatomy",
    "rectum": "clinical anatomy",
    "penis": "clinical anatomy",
    "vagina": "clinical anatomy",
    "clitoris": "clinical anatomy",
    "nipple": "clinical anatomy",
    "nipples": "clinical anatomy",
    "semen": "clinical anatomy",
    "boob": "'boob' also means a blunder",
    "boobs": "borderline; left to the Stage-2 classifier",
    "erotic": "literary and art-historical usage",
    "erotism": "literary and art-historical usage",
    "horny": "'horny' also describes a texture",
    "incest": "legal, genealogical and safeguarding discussion",
    "rape": "crime reporting and safeguarding discussion",
    "raping": "crime reporting and safeguarding discussion",
    "rapist": "crime reporting and safeguarding discussion",
    "sex": "a routine form field",
    "sexual": "'sexual harassment policy'",
    "nude": "art-historical usage; 'nude' as a colour",
    "suck": "'suck' in fluid mechanics and idiom",
    "viagra": "a medicine; also the canonical spam token",
    "playboy": "a magazine title and an ordinary noun",
    "xx": "a chromosome pair and a placeholder",
    "goddam": "mild; left to Stage 2 rather than flagged",
    # these six were demoted after measuring the filter against 11.6 MB of the
    # vendored repos' own prose and code - each fired on something benign
    "cum": "Latin ('cum laude'), and the usual abbreviation for cumulative",
    "xxx": "the standard redaction/placeholder token, and Roman 30",
    "dick": "a given name - Dick, and Moby-Dick",
    "fanny": "a given name; 'fanny pack' in US English",
    "gash": "a wound, in any clinical or incident text",
    "prick": "'pin prick', 'needle prick'",
    # the only BLOCK-tier false positive the 10,784-file measurement found, and
    # a block is the worst kind to get wrong: garak's own translation tests use
    # `jap` as a language code (`language: en,jap`,
    # references/garak-main/docs/source/translation.rst and
    # tests/langservice/conftest.py). OFCOM grades it a strength-3 ethnic slur
    # and it is one, but a three-letter token that doubles as a locale code
    # cannot be a hard block on a config-carrying payload.
    "jap": "also used as a language/locale code - 'language: en,jap'",
    # OFCOM strength-1 insults kept out of the flag tier as too weak to be
    # worth a finding on their own
    "cretin": "a weak insult; also an obsolete clinical term",
    "loony": "a weak insult",
    "nutter": "a weak insult",
    "psycho": "a film title and casual usage",
    "midget": "historically a size descriptor - 'midget submarine'",
}


# ============================================================== compiling ====
# `Term` = a tuple of tokens, so "beef curtains" and "chick with a dick" are
# matched as phrases rather than as substrings.
Term = tuple[str, ...]


@dataclass(frozen=True)
class LexEntry:
    """One compiled lexicon entry."""

    term: str
    category: str
    severity: Severity
    action: Action
    source: str


# better_profanity's token alphabet, from
# better_profanity/constants.py:9-12 (ascii letters + digits + @ $ * " ').
# `!` and `+` are added because Infosys' own wordlist ships `sh!t` and `shi+`,
# which upstream's alphabet could never have matched.
_TOKEN_RE = re.compile(r"[0-9A-Za-z@$*!+'\"]+")

# The reverse of better_profanity's CHARS_MAPPING
# (better_profanity/better_profanity.py:33-43). Upstream expands each wordlist
# entry into every obfuscated variant, which its own comment says costs ~5MB of
# memory; going the other way - normalising the *input* token back towards the
# canonical spelling - costs nothing at load time and is exact for the same
# substitution table. Where a glyph is genuinely ambiguous the value holds every
# canonical letter and the candidates are enumerated.
_DELEET: dict[str, tuple[str, ...]] = {
    "@": ("a", "o"),
    "4": ("a",),
    "1": ("i", "l"),
    "!": ("i",),
    "0": ("o",),
    "$": ("s",),
    "5": ("s",),
    "3": ("e",),
    "7": ("t",),
    "+": ("t",),
    "l": ("l", "i"),
    "u": ("u", "v"),
    "v": ("v", "u"),
    "*": ("a", "i", "o", "u", "v", "e"),
}

_MAX_CANDIDATES = 256
_MAX_DELEET_LEN = 24


def _tokenize(text: str) -> list[tuple[str, int, int]]:
    """Whole tokens with their character offsets. This is the Scunthorpe fix:
    nothing downstream ever sees a partial token, so a banned word can only
    match a complete one."""
    return [(m.group(0).lower(), m.start(), m.end())
            for m in _TOKEN_RE.finditer(text)]


_HAS_LETTER = re.compile(r"[A-Za-z]")


def _candidates(token: str) -> list[str]:
    """Every canonical spelling this token could be an obfuscation of.

    Always includes the token itself and the token stripped of leading/trailing
    non-alphanumerics, so "fuck!" and "(shit)" still match while "hello!" does
    not gain a spurious variant.

    A token with no letter in it at all is returned as-is and never de-obfuscated.
    Found the hard way while measuring this filter against 11.6 MB of the
    vendored repos' own prose and code: `455` de-leets to `ass` (4->a, 5->s,
    5->s) and duly fired on a column of floats in a fairlearn test fixture. A
    number is a number - leetspeak needs a letter to be leet.
    """
    seeds = {token}
    stripped = token.strip("@$*!+'\"")
    if stripped and stripped != token:
        seeds.add(stripped)
    if not _HAS_LETTER.search(token):
        return [s for s in seeds if s]

    out: list[str] = []
    seen: set[str] = set()
    for seed in seeds:
        if seed not in seen:
            seen.add(seed)
            out.append(seed)
        if len(seed) > _MAX_DELEET_LEN:
            continue
        expansions: list[str] = [""]
        for char in seed:
            options = _DELEET.get(char, (char,))
            if len(expansions) * len(options) > _MAX_CANDIDATES:
                # Bail out of the de-obfuscation path rather than burning time;
                # the exact spelling above is still checked.
                expansions = []
                break
            expansions = [prefix + option
                          for prefix in expansions for option in options]
        for candidate in expansions:
            if candidate and candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
    return out


def _severity_for(strength: int) -> Severity:
    if strength >= 4:
        return Severity.CRITICAL
    if strength == 3:
        return Severity.HIGH
    if strength == 2:
        return Severity.MEDIUM
    return Severity.LOW


def _phrase(term: str) -> Term:
    """A lexicon entry tokenised the same way input text is, so `nig-nog`,
    `he-she`, `sod-off` and `g-spot` become two-token phrases and match text
    written either way."""
    return tuple(m.group(0).lower() for m in _TOKEN_RE.finditer(term))


def _compile_lexicon() -> tuple[dict[Term, LexEntry], set[Term], int]:
    """Build the match tables once, at import. No file I/O, no network."""
    ambiguous: set[Term] = {_phrase(t) for t in _AMBIGUOUS}
    ambiguous = {t for t in ambiguous if t}

    table: dict[Term, LexEntry] = {}

    def add(term: str, category: str, severity: Severity, action: Action,
            source: str) -> None:
        key = _phrase(term)
        if not key or key in ambiguous:
            return
        existing = table.get(key)
        # Keep the strongest claim if two sources disagree. A term graded a slur
        # by OFCOM must not be demoted to a flag by a flat list.
        order = {Action.FLAG: 0, Action.REDACT: 1, Action.BLOCK: 2}
        sev = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2,
               Severity.CRITICAL: 3}
        if existing is not None and (
                order[existing.action], sev[existing.severity]
        ) >= (order[action], sev[severity]):
            return
        table[key] = LexEntry(term=term, category=category, severity=severity,
                              action=action, source=source)

    # 1. OFCOM: category from column 1, tier from the strength grade.
    for category_label, term, strength in _OFCOM:
        if strength <= 0:
            continue
        ogr = map_category(category_label)
        identity = category_label in _IDENTITY_CATEGORIES
        if identity and strength >= 3:
            action = Action.BLOCK
        else:
            action = Action.FLAG
        add(term, ogr, _severity_for(strength), action,
            "garak ofcom-potentially-offensive.txt")

    # 2. Terms confirmed by both Infosys and LDNOOBW.
    for term in _SLUR_CONFIRMED:
        add(term, "safety.toxicity.hate", Severity.HIGH, Action.BLOCK,
            "Infosys wordlist.csv INTERSECT garak ldnoobw-en.txt")
    for term in _EXPLICIT_CONFIRMED:
        add(term, "safety.sexual", Severity.MEDIUM, Action.FLAG,
            "Infosys wordlist.csv INTERSECT garak ldnoobw-en.txt")
    for term in _PROFANITY_CONFIRMED:
        add(term, "safety.toxicity.profanity", Severity.MEDIUM, Action.FLAG,
            "Infosys wordlist.csv INTERSECT garak ldnoobw-en.txt")

    # 3. Misspelling families inherit the tier of their stem.
    for stem, variants in _VARIANTS.items():
        parent = table.get(_phrase(stem))
        if parent is None:
            continue
        for variant in variants:
            add(variant, parent.category, parent.severity, parent.action,
                "Infosys wordlist.csv (variant of %r)" % stem)

    longest = max((len(k) for k in table), default=1)
    longest = max(longest, max((len(t) for t in ambiguous), default=1))
    return table, ambiguous, longest


_LEXICON, _AMBIGUOUS_TERMS, _MAX_PHRASE = _compile_lexicon()

# Split by domain so the two Stage-1 rails own disjoint findings and the
# attribution join stays one-to-one.
_TOXICITY_LEXICON = {k: v for k, v in _LEXICON.items()
                     if v.category.startswith("safety.toxicity")}
_SEXUAL_LEXICON = {k: v for k, v in _LEXICON.items()
                   if v.category.startswith("safety.sexual")}


def _fingerprint(subject: str) -> str:
    """`Finding.fp` is a fingerprint of the subject, never the value. Upstream
    forbids per-span echoes of matched text, and an operator's false-positive
    exception keys on this hash."""
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]


def _snake_bounded(text: str, start: int, end: int) -> bool:
    """True when the match sits inside a snake_case identifier.

    `_` is deliberately outside the token alphabet, because that is what lets
    `hand_job` match the two-token phrase "hand job" - upstream relies on the
    same split (`better_profanity/better_profanity.py:239-243` documents
    exactly that case). The cost is that `cum_sum_ratio` also splits, and
    measuring this filter over 11.6 MB of the vendored repos found `cum` firing
    on deepchecks' own variable name at
    references/deepchecks-main/deepchecks/utils/performance/error_model.py.
    So a *single-token* hit is rejected when an underscore is glued to either
    end of it: that is an identifier, not a word.
    """
    if start > 0 and text[start - 1] == "_":
        return True
    return end < len(text) and text[end] == "_"


def _scan(text: str, lexicon: dict[Term, LexEntry]
          ) -> tuple[list[tuple[LexEntry, int, int]], bool]:
    """Return the lexicon hits with their offsets, and whether any ambiguous
    term was present.

    Phrases are matched first and longest-first, so "son of a bitch" reports one
    finding rather than also reporting "bitch" inside it.
    """
    tokens = _tokenize(text)
    hits: list[tuple[LexEntry, int, int]] = []
    saw_ambiguous = False
    consumed = 0

    for i in range(len(tokens)):
        if i < consumed:
            continue
        matched = False
        for span in range(min(_MAX_PHRASE, len(tokens) - i), 0, -1):
            window = tokens[i:i + span]
            if span == 1 and _snake_bounded(text, window[0][1], window[0][2]):
                continue
            if span == 1:
                keys = [(cand,) for cand in _candidates(window[0][0])]
            else:
                keys = [tuple(t[0] for t in window)]
            for key in keys:
                if key in _AMBIGUOUS_TERMS:
                    saw_ambiguous = True
                    matched = span > 1
                    break
                entry = lexicon.get(key)
                if entry is not None:
                    hits.append((entry, window[0][1], window[-1][2]))
                    consumed = i + span
                    matched = True
                    break
            if matched:
                break
    return hits, saw_ambiguous


# ================================================================== rails ====
class _LexicalRail:
    """Shared machinery for the two Stage-1 lexicon rails."""

    stage = Stage.STAGE_1
    tenet = TENET

    def __init__(self, name: str, lexicon: dict[Term, LexEntry]) -> None:
        self.name = name
        self._lexicon = lexicon

    def terms(self) -> int:
        return len(self._lexicon)

    def check(self, path: str, text: str) -> RailResult:
        # llm-guard returns early on empty input (toxicity.py:97); an empty
        # string is genuinely clean, not unjudged.
        if not text or not text.strip():
            return RailResult.clean()

        hits, saw_ambiguous = _scan(text, self._lexicon)
        findings: list[Finding] = []
        block = False
        for entry, start, end in hits:
            findings.append(Finding(
                category=entry.category,
                severity=entry.severity,
                action=entry.action,
                path=path,
                start=start,
                end=end,
                # No score: this is a deterministic match, and emitting 1.0
                # would invite comparison with a classifier probability. The
                # attribution's confidence_kind says "deterministic".
                detector=self.name,
                subject=entry.term,
                fp=_fingerprint(entry.term),
            ))
            if entry.action is Action.BLOCK:
                block = True

        if block:
            return RailResult(findings=findings, block=True,
                              reason="banned-term tier: hard block")
        if findings:
            # Flag-tier hits are real but not conclusive - hand them to the
            # context-aware classifier rather than deciding alone.
            return RailResult(findings=findings, escalate=True,
                              reason="flag-tier terms present")
        if saw_ambiguous:
            # The point of the ambiguity tier: no finding, but do not call it
            # clean either. Stage 2 has the context this rail does not.
            return RailResult(escalate=True,
                              reason="context-dependent term present; "
                                     "deferring to the Stage-2 classifier")
        return RailResult.clean()


class ProfanityFilter(_LexicalRail):
    """Tiered profanity / slur / banned-word filter. Stage 1, pure stdlib."""

    def __init__(self) -> None:
        super().__init__("content_safety.profanity", _TOXICITY_LEXICON)


class ExplicitContentFilter(_LexicalRail):
    """Explicit-lexicon adult-content filter. Stage 1, pure stdlib.

    Lexical only, and the note on its capability registration says so: it sees
    explicit vocabulary, not euphemism, not implication, and not images.
    """

    def __init__(self) -> None:
        super().__init__("content_safety.explicit", _SEXUAL_LEXICON)


class MatchType:
    """llm-guard's `BanSubstrings.MatchType`, ported from
    references/llm-guard-main/llm-guard-main/llm_guard/input_scanners/ban_substrings.py:38-49.

    The distinction is the whole value of the class. `STR` is a raw `in` test -
    it will match inside a word, which is what you want for a marker like
    `etc/shadow` and exactly what you must not use for a word like `ass`. `WORD`
    wraps the term in `\\b`, which is the safe default for natural-language
    terms.
    """

    STR = "str"
    WORD = "word"

    @staticmethod
    def match(match_type: str, text: str, substring: str) -> bool:
        if match_type == MatchType.STR:
            return substring in text
        if match_type == MatchType.WORD:
            return re.search(r"\b" + re.escape(substring) + r"\b",
                             text) is not None
        return False


@dataclass
class BannedSubstrings:
    """Exact / keyword restricted-topic blocklist. Stage 1, pure stdlib.

    Deliberately ships with **no default terms**. Every restricted-topic
    mechanism in the vendored review takes its topic list from the caller -
    llm-guard's `BanTopics(topics=[...])`, Infosys' `restricttopic_check` which
    reads `payload['labels']`
    (responsible-ai-moderationmodel/src/service/topicModel.py:96-126), NeMo's
    topic-control rules which live in the deployment's own system prompt. An
    off-policy topic is a property of a deployment, not of English, so inventing
    a default here would be inventing policy. Unconfigured, the rail is clean
    and the coverage report shows the capability as not yet real.
    """

    substrings: Sequence[str] = ()
    match_type: str = MatchType.WORD
    case_sensitive: bool = False
    category: str = "safety.topic_violation"
    severity: Severity = Severity.MEDIUM
    action: Action = Action.FLAG
    name: str = "content_safety.banned_substrings"
    stage: Stage = Stage.STAGE_1
    tenet: Tenet = TENET

    def check(self, path: str, text: str) -> RailResult:
        if not self.substrings or not text:
            return RailResult.clean()

        haystack = text if self.case_sensitive else text.lower()
        findings: list[Finding] = []
        for raw in self.substrings:
            needle = raw if self.case_sensitive else raw.lower()
            if not MatchType.match(self.match_type, haystack, needle):
                continue
            index = haystack.find(needle)
            findings.append(Finding(
                category=self.category,
                severity=self.severity,
                action=self.action,
                path=path,
                start=index if index >= 0 else None,
                end=index + len(needle) if index >= 0 else None,
                detector=self.name,
                subject=raw,
                fp=_fingerprint(raw),
            ))
        if not findings:
            return RailResult.clean()
        block = any(f.action is Action.BLOCK for f in findings)
        return RailResult(findings=findings, block=block,
                          escalate=not block,
                          reason="banned substring(s) present")


# ----------------------------------------------------------- stage 2 / 3 ----
# Both of these are adapters over llm-guard. The import is inside `check()`, not
# at module scope, so importing this package never pulls torch and never
# downloads weights. When the library or the weights are absent the rail returns
# `unjudged`, the engine records the payload path, and a client-facing request
# fails closed. That is the intended behaviour, not a degradation to "clean".

_TOXICITY_MODEL = "unitary/unbiased-toxic-roberta"
_TOXICITY_REVISION = "36295dd80b422dc49f40052021430dae76241adc"
_TOXIC_LABELS = ("toxicity", "severe_toxicity", "obscene", "threat", "insult",
                 "identity_attack", "sexual_explicit")
_ZEROSHOT_MODEL = "MoritzLaurer/roberta-base-zeroshot-v2.0-c"
_ZEROSHOT_REVISION = "d825e740e0c59881cf0b0b1481ccf726b6d65341"


# How far past the tenant's threshold a hit must sit before it blocks outright
# rather than escalating. This is a fraction of the range ABOVE the threshold
# (llm-guard's risk score is threshold-relative), so it stays meaningful when a
# tenant moves the threshold - which a bare absolute literal would not.
_RISK_SEVERE = 0.8


class ToxicityClassifier:
    THRESHOLD_KEY = "safety.toxicity.classifier"
    """llm-guard's `Toxicity` scanner, Stage 2.

    Model id and pinned revision from
    references/llm-guard-main/llm-guard-main/llm_guard/input_scanners/toxicity.py:13-26;
    the seven scored head labels from the same file, lines 28-36. The revision
    pin is copied deliberately - llm-guard pins every model, and an unpinned
    guardrail model is a supply-chain hole.
    """

    name = "content_safety.toxicity_model"
    tenet = TENET
    stage = Stage.STAGE_2

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self.model = _TOXICITY_MODEL
        self.revision = _TOXICITY_REVISION
        # Keyed by threshold: see _load. A per-tenant threshold has to reach the
        # scanner's constructor, so one instance may hold several.
        self._scanners: dict[float, object] = {}
        self._unavailable: str | None = None

    def available(self) -> bool:
        """Cheap, side-effect-free probe: is the library importable at all?
        Deliberately does not construct the scanner, because that downloads
        weights - and this is called from `register()`."""
        import importlib.util

        for module in ("llm_guard", "transformers", "torch"):
            if importlib.util.find_spec(module) is None:
                return False
        return True

    def _load(self, threshold: float | None = None):
        """Return a scanner whose internal threshold IS `threshold`.

        The threshold cannot be applied after the fact. llm-guard's `scan`
        returns `calculate_risk_score(score, threshold)` (util.py:134-144), a
        value in [-1, 1] measured RELATIVE to the scanner's own threshold - so
        the raw probability never leaves the scanner, and comparing the returned
        risk against a different threshold would be meaningless. The scanner has
        to be built with the tenant's value.

        Scanners are cached per threshold. Distinct tenant values mean distinct
        cache entries, which is a bounded cost (the model weights are shared by
        `transformers`' own cache; only the thin wrapper is rebuilt) and is the
        price of the threshold being real rather than decorative.
        """
        if threshold is None:
            threshold = self.threshold
        key = round(float(threshold), 4)
        if key in self._scanners:
            return self._scanners[key]
        if self._unavailable is not None:
            return None
        try:
            from llm_guard.input_scanners.toxicity import (  # noqa: PLC0415
                DEFAULT_MODEL, Toxicity)
            self._scanners[key] = Toxicity(model=DEFAULT_MODEL, threshold=key)
        except Exception as exc:  # noqa: BLE001 - any failure is "cannot judge"
            self._unavailable = f"{type(exc).__name__}: {exc}"
            return None
        return self._scanners[key]

    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Per-tenant threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self.threshold)
                     if ctx is not None else self.threshold)
        if not text or not text.strip():
            return RailResult.clean()
        # The resolved threshold is passed INTO the scanner, not compared against
        # its output - see _load. Passing it here is what makes a tenant override
        # change the verdict rather than merely appear in the read log.
        scanner = self._load(threshold)
        if scanner is None:
            return RailResult.unjudged(
                f"llm-guard Toxicity unavailable ({self.model} @ "
                f"{self.revision[:7]}): {self._unavailable or 'not installed'}")
        try:
            _, valid, risk = scanner.scan(text)
        except Exception as exc:  # noqa: BLE001
            return RailResult.unjudged(
                f"{self.name} failed at scan time: {type(exc).__name__}: {exc}")
        if valid:
            return RailResult.clean()
        # `risk` is threshold-relative in [-1, 1]: 0.0 means "exactly at the
        # threshold", 1.0 means "at the top of the range above it". Clamping to
        # [0, 1] keeps it inside the contract's score bounds, and the value is
        # therefore a distance past the tenant's threshold, not a probability.
        score = max(0.0, min(1.0, float(risk)))
        severe = score >= _RISK_SEVERE
        return RailResult(findings=[Finding(
            category=map_category("toxicity"),
            severity=Severity.HIGH if severe else Severity.MEDIUM,
            action=Action.BLOCK if severe else Action.FLAG,
            path=path,
            score=score,
            detector=self.name,
        )], block=severe, escalate=not severe,
            reason=f"classifier risk {score:.2f} past threshold {threshold:.2f}")


class ZeroShotTopics:
    THRESHOLD_KEY = "safety.topic_violation.zeroshot"
    """llm-guard's `BanTopics` scanner, Stage 2.

    Model id and pinned revision from
    references/llm-guard-main/llm-guard-main/llm_guard/input_scanners/ban_topics.py:80-90;
    default threshold 0.6 from the same file, line 104. Topics are supplied per
    deployment; with none supplied the rail is clean rather than unjudged,
    because there is nothing it was asked to look for.
    """

    name = "content_safety.zeroshot_topics"
    tenet = TENET
    stage = Stage.STAGE_2

    def __init__(self, topics: Sequence[str] = (),
                 threshold: float = 0.6) -> None:
        self.topics = tuple(topics)
        self.threshold = threshold
        self.model = _ZEROSHOT_MODEL
        self.revision = _ZEROSHOT_REVISION
        # Keyed by threshold: BanTopics takes it at construction, so a
        # per-tenant value has to reach the constructor. See ToxicityClassifier.
        self._scanners: dict[float, object] = {}
        self._unavailable: str | None = None

    def available(self) -> bool:
        import importlib.util

        for module in ("llm_guard", "transformers", "torch"):
            if importlib.util.find_spec(module) is None:
                return False
        return True

    def _load(self, threshold: float | None = None):
        """Return a BanTopics whose internal threshold IS `threshold`.

        Same reason as ToxicityClassifier: `scan` returns a threshold-relative
        risk, not the raw entailment score, so the tenant's value must go in at
        construction rather than being compared against the output.
        """
        if threshold is None:
            threshold = self.threshold
        key = round(float(threshold), 4)
        if key in self._scanners:
            return self._scanners[key]
        if self._unavailable is not None:
            return None
        try:
            from llm_guard.input_scanners.ban_topics import (  # noqa: PLC0415
                MODEL_ROBERTA_BASE_C_V2, BanTopics)
            self._scanners[key] = BanTopics(topics=list(self.topics),
                                            threshold=key,
                                            model=MODEL_ROBERTA_BASE_C_V2)
        except Exception as exc:  # noqa: BLE001
            self._unavailable = f"{type(exc).__name__}: {exc}"
            return None
        return self._scanners[key]

    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Per-tenant threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self.threshold)
                     if ctx is not None else self.threshold)
        if not self.topics:
            return RailResult.clean()
        if not text or not text.strip():
            return RailResult.clean()
        scanner = self._load(threshold)
        if scanner is None:
            return RailResult.unjudged(
                f"llm-guard BanTopics unavailable ({self.model} @ "
                f"{self.revision[:7]}): {self._unavailable or 'not installed'}")
        try:
            _, valid, risk = scanner.scan(text)
        except Exception as exc:  # noqa: BLE001
            return RailResult.unjudged(
                f"{self.name} failed at scan time: {type(exc).__name__}: {exc}")
        if valid:
            return RailResult.clean()
        score = max(0.0, min(1.0, float(risk)))
        return RailResult(findings=[Finding(
            category=map_category("banned_topic"),
            severity=Severity.MEDIUM,
            action=Action.FLAG,
            path=path,
            score=score,
            detector=self.name,
        )], escalate=True, reason="zero-shot topic above threshold")


@dataclass
class ToxicityJudge:
    THRESHOLD_KEY = "safety.toxicity.judge"
    """LLM-judge toxicity rail, Stage 3.

    The shape is taken from hai-guardrails, whose `toxic`, `hateSpeech`,
    `adultContent` and `profanity` guards are all LLM prompts with a 0-1 score
    and a default threshold of 0.8 - there is no wordlist and no classifier
    behind any of them
    (references/hai-guardrails-main/hai-guardrails-main/src/guards/profanity.guard.ts:21-27
    and src/guards/adult-content.guard.ts:21-27). DeepTeam's `ToxicityGuard` is
    the same idea with a paid default judge.

    No judge is wired in by default, and that is the honest state: a judge means
    a paid API key AFNI has not configured here. Unconfigured, the rail is
    `unjudged`, so fail-closed will block client-facing traffic rather than let
    it through unexamined.
    """

    judge: Callable[[str], float] | None = None
    threshold: float = 0.8
    name: str = "content_safety.toxicity_judge"
    stage: Stage = Stage.STAGE_3
    tenet: Tenet = TENET

    def available(self) -> bool:
        return self.judge is not None

    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Per-tenant threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self.threshold)
                     if ctx is not None else self.threshold)
        if self.judge is None:
            return RailResult.unjudged(
                "no LLM judge configured for content_safety.toxicity_judge "
                "(hai-guardrails-style prompt judge, threshold "
                f"{threshold})")
        if not text or not text.strip():
            return RailResult.clean()
        try:
            score = float(self.judge(text))
        except Exception as exc:  # noqa: BLE001
            return RailResult.unjudged(
                f"{self.name} judge call failed: {type(exc).__name__}: {exc}")
        score = max(0.0, min(1.0, score))
        if score < threshold:
            return RailResult.clean()
        return RailResult(findings=[Finding(
            category="safety.toxicity",
            severity=Severity.HIGH,
            action=Action.BLOCK,
            path=path,
            score=score,
            detector=self.name,
        )], block=True, reason="LLM judge above threshold")


# =========================================================== attribution ====
PROFANITY_RAIL = ProfanityFilter()
EXPLICIT_RAIL = ExplicitContentFilter()
BANNED_SUBSTRINGS_RAIL = BannedSubstrings()
TOXICITY_MODEL_RAIL = ToxicityClassifier()
ZEROSHOT_TOPICS_RAIL = ZeroShotTopics()
TOXICITY_JUDGE_RAIL = ToxicityJudge()

# Every rail that may be mounted in the request cascade. No OFFLINE rail is
# here, by construction - the Cascade constructor would reject one anyway, and
# the red-team capability is registered as OFFLINE coverage instead.
RAILS: list[object] = [
    PROFANITY_RAIL,
    EXPLICIT_RAIL,
    BANNED_SUBSTRINGS_RAIL,
    TOXICITY_MODEL_RAIL,
    ZEROSHOT_TOPICS_RAIL,
    TOXICITY_JUDGE_RAIL,
]

_ATTR = RailAttribution

ATTRIBUTIONS: dict[str, RailAttribution] = {
    PROFANITY_RAIL.name: _ATTR(
        rail=PROFANITY_RAIL.name,
        source_repo="Infosys-Responsible-AI-Toolkit-master + garak-main",
        display_name="AFNI tiered profanity / slur filter",
        mechanism="Keyword/Regex - whole-token match with leetspeak "
                  "normalisation, graded block/flag/ambiguous tiers",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        evidence="Infosys-Responsible-AI-Toolkit-master/responsible-ai-safety/"
                 "responsible-ai-toxicity/data/wordlist.csv (917 rows) "
                 "INTERSECT garak-main/garak/data/ldnoobw-en.txt (403 rows); "
                 "severity and category from garak-main/garak/data/"
                 "ofcom-potentially-offensive.txt (150 graded rows); token "
                 "alphabet and CHARS_MAPPING from better_profanity-2.0.0-py3-"
                 "none-any.whl better_profanity/better_profanity.py:33-43 and "
                 "constants.py:9-12, as loaded by responsible-ai-safety/"
                 "responsible-ai-toxicity/src/profanity/service/service.py:288",
        capability="Profanity / banned-word filter",
    ),
    EXPLICIT_RAIL.name: _ATTR(
        rail=EXPLICIT_RAIL.name,
        source_repo="Infosys-Responsible-AI-Toolkit-master + garak-main",
        display_name="AFNI explicit-lexicon adult-content filter",
        mechanism="Keyword/Regex - whole-token match over the safety.sexual "
                  "tier of the same graded lexicon",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        evidence="garak-main/garak/data/ofcom-potentially-offensive.txt "
                 "category 'sexual' (17 graded rows) plus the sexual subset of "
                 "Infosys wordlist.csv INTERSECT garak ldnoobw-en.txt",
        capability="Adult / explicit content",
    ),
    BANNED_SUBSTRINGS_RAIL.name: _ATTR(
        rail=BANNED_SUBSTRINGS_RAIL.name,
        source_repo="llm-guard-main",
        display_name="LLM Guard BanSubstrings (STR/WORD)",
        mechanism="Keyword/Regex - exact substring or \\b-delimited word match",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        evidence="llm-guard-main/llm_guard/input_scanners/ban_substrings.py"
                 ":38-49 (MatchType.STR vs MatchType.WORD)",
        capability="Zero-shot restricted-topic filter",
    ),
    TOXICITY_MODEL_RAIL.name: _ATTR(
        rail=TOXICITY_MODEL_RAIL.name,
        source_repo="llm-guard-main",
        display_name="LLM Guard Toxicity (unbiased-toxic-roberta)",
        mechanism="Classifier - 7-head multilabel toxicity transformer",
        stage=int(Stage.STAGE_2),
        confidence_kind="classifier",
        evidence="llm-guard-main/llm_guard/input_scanners/toxicity.py:13-26 "
                 f"model {_TOXICITY_MODEL} revision {_TOXICITY_REVISION}; "
                 "scored labels at toxicity.py:28-36",
        capability="Toxicity / hate-speech (model)",
    ),
    ZEROSHOT_TOPICS_RAIL.name: _ATTR(
        rail=ZEROSHOT_TOPICS_RAIL.name,
        source_repo="llm-guard-main",
        display_name="LLM Guard BanTopics (zero-shot NLI)",
        mechanism="NLI/Cross-encoder - zero-shot classification against "
                  "caller-supplied topic labels",
        stage=int(Stage.STAGE_2),
        confidence_kind="entailment",
        evidence="llm-guard-main/llm_guard/input_scanners/ban_topics.py:80-90 "
                 f"model {_ZEROSHOT_MODEL} revision {_ZEROSHOT_REVISION}; "
                 "default threshold 0.6 at ban_topics.py:104",
        capability="Zero-shot restricted-topic filter",
    ),
    TOXICITY_JUDGE_RAIL.name: _ATTR(
        rail=TOXICITY_JUDGE_RAIL.name,
        source_repo="hai-guardrails-main",
        display_name="hai-guardrails toxicity/profanity LLM judge",
        mechanism="LLM-judge - prompt returning a 0-1 score, threshold 0.8",
        stage=int(Stage.STAGE_3),
        confidence_kind="judge",
        evidence="hai-guardrails-main/src/guards/profanity.guard.ts:21-27 and "
                 "src/guards/adult-content.guard.ts:21-27 (LLM prompt, "
                 "threshold 0.8, no wordlist and no classifier behind either)",
        capability="Toxicity (LLM judge)",
    ),
}

TAXONOMY_ATTRIBUTION = _ATTR(
    rail="content_safety.harm_taxonomy",
    source_repo="openguardrails-main",
    display_name="OpenGuardrails safety.* harm taxonomy mapper",
    mechanism="Module - vendor-label to neutral-category mapping table",
    stage=int(Stage.STAGE_1),
    confidence_kind="deterministic",
    evidence="openguardrails-main/specification/taxonomy.md:10-26 (the 11 "
             "safety.* ids) plus the reference-moderation refinements in the "
             "same file; vendor labels from llm-guard toxicity.py:28-36, "
             "garak ofcom-potentially-offensive.txt column 1 and promptfoo "
             "src/redteam/constants/plugins.ts:55-79 (26 harmful:* ids)",
    capability="Multi-category harm taxonomy",
)

RAIL_SPECS: list[RailSpec] = [
    RailSpec(rail=rail, source_repo=ATTRIBUTIONS[rail.name].source_repo,
             mechanism=ATTRIBUTIONS[rail.name].mechanism,
             evidence=ATTRIBUTIONS[rail.name].evidence,
             capability=ATTRIBUTIONS[rail.name].capability)
    for rail in RAILS
]


# ============================================================== registry ====
def register(registry) -> None:
    """Declare this tenet's coverage. Nine capabilities, and the honest status
    of each - four run today, two wait on a dependency, one is cloud, one is
    CI-only, one is a gap.
    """
    from ...registry.capabilities import Coverage  # noqa: PLC0415

    # -- runs today, pure stdlib ------------------------------------------
    registry.register_rail(
        PROFANITY_RAIL, ATTRIBUTIONS[PROFANITY_RAIL.name], available=True,
        note=f"{PROFANITY_RAIL.terms()} compiled toxicity/slur terms in three "
             f"tiers (block / flag / {len(_AMBIGUOUS_TERMS)} deliberately "
             "non-firing ambiguous terms). Whole-token matching plus the "
             "better_profanity leetspeak table, so 'assessment', 'classic', "
             "'Scunthorpe' and 'Cockburn' cannot match. The raw Infosys list "
             "is NOT used as-is: it contains 'len', 'pot', 'god', 'kill', "
             "'fat' and 'niggle', which would make the gateway unusable.")

    registry.register_rail(
        EXPLICIT_RAIL, ATTRIBUTIONS[EXPLICIT_RAIL.name], available=True,
        note=f"{EXPLICIT_RAIL.terms()} explicit terms, flag-tier only. "
             "LEXICAL ONLY: catches explicit vocabulary, not euphemism, not "
             "implication and not images. Clinical anatomy is deliberately in "
             "the ambiguous tier so a healthcare payload is not flagged. "
             "safety.sexual.minors has NO Stage-1 tier - the only candidate "
             "terms in the vendored lists ('pedo', 'pedophile', 'shota') "
             "cannot distinguish solicitation from safeguarding discussion, "
             "and 'Shota' is a common given name. That class needs the "
             "Stage-2 classifier or the cloud service.")

    registry.register(
        TENET, "Multi-category harm taxonomy", Coverage.IMPLEMENTED,
        TAXONOMY_ATTRIBUTION,
        note=f"{len(SAFETY_CATEGORIES)} neutral ids covering all "
             f"{len(SAFETY_ROOTS)} safety.* roots, and "
             f"{len(VENDOR_LABEL_MAP)} vendor labels mapped onto them "
             "(unbiased-toxic-roberta heads, OFCOM categories, promptfoo's 26 "
             "harmful:* plugin ids, Infosys nsfw_model classes). Pure data and "
             "a rollup function, consumed by this tenet's rails and available "
             "to every other tenet - it is a mapping layer, not a detector, "
             "and the detection it feeds is credited to the rails above.")

    # -- rail exists, weights absent --------------------------------------
    registry.register_rail(
        TOXICITY_MODEL_RAIL, ATTRIBUTIONS[TOXICITY_MODEL_RAIL.name],
        available=TOXICITY_MODEL_RAIL.available(),
        note=f"{_TOXICITY_MODEL} pinned at revision {_TOXICITY_REVISION}. "
             "Lazy import; returns unjudged when llm-guard/transformers/torch "
             "or the weights are absent, so fail-closed blocks client-facing "
             "traffic rather than passing it unexamined.")

    registry.register_rail(
        ZEROSHOT_TOPICS_RAIL, ATTRIBUTIONS[ZEROSHOT_TOPICS_RAIL.name],
        available=ZEROSHOT_TOPICS_RAIL.available(),
        note=f"{_ZEROSHOT_MODEL} pinned at revision {_ZEROSHOT_REVISION}, "
             "threshold 0.6. A Stage-1 BanSubstrings rail "
             f"({BANNED_SUBSTRINGS_RAIL.name}, MatchType STR/WORD ported from "
             "llm-guard ban_substrings.py:38-49) is mounted alongside it and "
             "gives deterministic cover for enumerated terms - but a keyword "
             "blocklist is not zero-shot, and it ships with no default terms "
             "because every restricted-topic mechanism in the review takes its "
             "topics from the deployment. So this capability is DEPENDENCY, "
             "not implemented.")

    # -- Stage 3, needs a judge ------------------------------------------
    registry.register_rail(
        TOXICITY_JUDGE_RAIL, ATTRIBUTIONS[TOXICITY_JUDGE_RAIL.name],
        available=TOXICITY_JUDGE_RAIL.available(),
        note="hai-guardrails-shaped prompt judge, threshold 0.8. No judge is "
             "wired in: it needs a paid API key (DeepTeam's ToxicityGuard "
             "defaults to gpt-4o-mini, hai-guardrails to whatever LLM the "
             "chain is given). Unconfigured it reports unjudged.")

    # -- cloud, not configured -------------------------------------------
    registry.register(
        TENET, "Managed safety-model routing", Coverage.CLOUD, None,
        note="No AFNI rail. NeMo Guardrails routes content_safety rails to "
             "llama-3.1-nemoguard-8b-content-safety, "
             "meta-llama/Meta-Llama-Guard-2-8B, ShieldGemma and "
             "nvidia/llama-3.1-nemotron-safety-guard-8b-v3 "
             "(Guardrails-develop/docs/configure-rails/guardrail-catalog/"
             "content-safety.mdx:11,25,31,67,180; topic control at "
             "topic-control.mdx:25). The tenet's cloud pick is Azure AI "
             "Content Safety - severity-graded hate/self-harm/sexual/violence "
             "with custom blocklists. All of it is a managed or self-hosted "
             "guard model AFNI has not stood up, so claiming it as runtime "
             "cover would be false.")

    # -- CI only ----------------------------------------------------------
    registry.register(
        TENET, "Harmful-content red-team sets", Coverage.OFFLINE, None,
        note="OFFLINE by construction - never mounted in the request path. "
             "promptfoo carries 26 harmful:* plugin ids "
             "(promptfoo-main/src/redteam/constants/plugins.ts:55-79) and the "
             "harmbench / beavertails / donotanswer / xstest / aegis dataset "
             "plugins (plugins.ts:327-431); garak, JCB (400 HarmBench "
             "behaviours) and DeepTeam (Aegis, BeaverTails) cover the same "
             "ground. In CI these measure the rails above; promptfoo's "
             "harmful:* and bias:* plugins call api.promptfoo.app, which is a "
             "data-residency decision AFNI has to take before enabling them.")

    # -- gap --------------------------------------------------------------
    registry.register(
        TENET, "NSFW image/video detection", Coverage.GAP, None,
        note="Honest gap, for two independent reasons. (1) The only "
             "implementation in the review is Infosys' NudeNet + nsfw.h5 "
             "(responsible-ai-safety/responsible-ai-toxicity/src/profanity/"
             "util/nsfw_model/nsfw_detector/predict.py:132-133 loads "
             "models/nsfw.299x299.h5 and models/nsfw_mobilenet2.224x224.h5; "
             "NudeNet/NudeNet.py:14) and those weights are ABSENT from the "
             "vendored repo - they are multi-GB Git-LFS fetches. (2) The "
             "gateway contract has no image path at all: GuardEvent.texts() "
             "yields strings and skips non-string leaves, so an image rail "
             "would have nothing to read. Closing this needs a payload-type "
             "extension plus either those weights or Azure AI Content Safety's "
             "multimodal endpoint.")


__all__ = [
    "SAFETY_CATEGORIES", "SAFETY_ROOTS", "VENDOR_LABEL_MAP", "map_category",
    "rollup", "MatchType", "ProfanityFilter", "ExplicitContentFilter",
    "BannedSubstrings", "ToxicityClassifier", "ZeroShotTopics",
    "ToxicityJudge", "RAILS", "RAIL_SPECS", "ATTRIBUTIONS",
    "TAXONOMY_ATTRIBUTION", "register", "TENET",
]
