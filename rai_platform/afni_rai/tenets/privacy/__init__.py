# -*- coding: utf-8 -*-
# Raw docstring: it quotes regexes containing \d, and a plain string makes
# those invalid escape sequences - a SyntaxWarning on every single run.
r"""
Privacy rails.

Privacy has the strongest Stage-1 story of the seven tenets: of the 17 tools that
contribute a Privacy check in `analysis/data/tenet_methodology_data.json`, six are
Stage 1 and every one of those six earns it on a *deterministic* mechanism -
regex plus a checksum. Eight are offline-only red-team or batch tools, and two
(OpenGuardrails, Guardrails AI) contribute a contract rather than a detector.

So the whole point of this module is that the useful part does not need torch,
spaCy or presidio. Everything in Stage 1 here is `re` plus checksum arithmetic
ported out of the vendored source, and it runs on 100% of traffic:

    PiiEntityRail            email / phone / IP, with redaction spans
    RegionIdRail             US SSN + ITIN, India Aadhaar (Verhoeff) + PAN,
                             UK NINO, Turkish IBAN (ISO 13616 mod-97)
    CreditCardRail           candidate scan + Luhn + IIN gate
    HealthcarePhiRail        ICD-10, MRN, NPI (80840 Luhn), DEA (Infosys checksum)
    ReversibleAnonymiserRail vault-backed pseudonymisation, reversible
    SystemPromptLeakageRail  extraction-probe patterns + n-gram containment

Two rails exist for depth and are honest about not being protection yet:

    PresidioPiiRail          Stage 2, needs `presidio-analyzer` - reports unjudged
    PiiLeakageJudgeRail      Stage 3, needs a paid judge model - reports unjudged

`RailResult.unjudged` on those is deliberate, and it has a consequence worth
stating plainly: the cascade fails closed on client-facing traffic, so a payload
that a Stage-1 rail escalated and Stage 2 could not judge is BLOCKED, not
allowed. That is the correct trade - "could not look" is not "found nothing" -
but it means installing presidio-analyzer changes the block rate, and nobody
should be surprised by that.

Three design decisions worth defending, because each is a deliberate divergence
from the vendored source:

1. **Checksums, not just patterns.** Every high-severity identifier here is
   validated: Luhn for cards and NPI, the Infosys DEA digit, Verhoeff for
   Aadhaar, ISO 13616 mod-97 for IBAN. Safe Zone's card pattern
   (`init.sql:28`) has no Luhn check at all and will redact any 13-16 digit run;
   that is a false-positive generator on a BPO transcript full of order numbers.

2. **Prefix and context gates on the PHI patterns.** hai-guardrails'
   `mrn-numeric` (`pii.guard.ts:57-62`) makes the `MRN` prefix *optional*, so it
   redacts every 7-10 digit integer in the payload, and its `icd10` pattern
   (`:50-55`) matches bare `[A-TV-Z]\d\d`, which redacts the `B12` in "vitamin
   B12". Both patterns are ported, both are gated. The tests pin the gates.

3. **Nothing here blocks on PII alone.** The OpenGuardrails taxonomy is explicit
   that PII "drives masking/minimisation, not refusal"
   (`specification/taxonomy.md:100-110`), so these rails emit `Action.REDACT`
   with `modifications` spans and leave the block decision to policy. The one
   exception is a confirmed system-prompt leak, which does block.

Source of every pattern and checksum is cited inline as `file:line` against
`references/`, and carried into each rail's `RailAttribution.evidence` so a
client reviewer can check the claim rather than take it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from ...cascade.rail import RailResult, Stage
from ...contract.explanation import RailAttribution
from ...contract.models import Action, Finding, Severity, Span, Tenet
from ...third_party_logging import quieten as _quieten
from ...third_party_logging import quieten_loaded as _quieten_loaded
from ...registry.capabilities import Coverage

# Silence presidio and spacy model-load chatter before any model is built. See
# afni_rai/third_party_logging.py - it is a privacy decision as much
# as a readability one.
_quieten()


TENET = Tenet.PRIVACY

# --------------------------------------------------------------------------- #
# Length-preserving fold                                                       #
# --------------------------------------------------------------------------- #
# Fullwidth digits and exotic dashes are the cheapest way to walk an SSN past a
# regex. Only *single character -> single character* substitutions are allowed
# here, so a match offset in the folded string is the same offset in the payload
# and `Span` stays truthful. Anything that changed the length (NFKC, invisible-
# character stripping the way LLM Guard's InvisibleText scanner does it) would
# silently corrupt every span this module emits.
_FOLD = {}
for _i in range(10):
    _FOLD[0xFF10 + _i] = ord("0") + _i          # FULLWIDTH DIGIT ZERO..NINE
for _cp in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFF0D):
    _FOLD[_cp] = ord("-")                       # hyphens, dashes, minus sign
for _cp in (0x00A0, 0x2007, 0x202F, 0x2060, 0xFEFF):
    _FOLD[_cp] = ord(" ")                       # non-breaking / figure spaces
_FOLD[0xFF0E] = ord(".")                        # FULLWIDTH FULL STOP
_FOLD[0xFF20] = ord("@")                        # FULLWIDTH COMMERCIAL AT
_FOLD[0xFF03] = ord("#")                        # FULLWIDTH NUMBER SIGN


def fold(text: str) -> str:
    """Offset-preserving normalisation. `len(fold(t)) == len(t)` always."""
    return text.translate(_FOLD)


def fingerprint(subject: str) -> str:
    """The `Finding.fp` whitelist key.

    A hash, never the value. An operator's false-positive exception has to key
    on *something* stable, and the one thing a privacy rail must never do is
    write the identifier it caught into a log line.
    """
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Checksums                                                                    #
# --------------------------------------------------------------------------- #
def digits_only(value: str) -> str:
    """Ported from agentic_security `pii_detector.py:104` `_digits_only`."""
    return re.sub(r"\D", "", value)


def luhn(value: str) -> bool:
    """Luhn (ISO/IEC 7812-1) mod-10 check.

    Ported from `references/agentic_security-main/agentic_security/
    refusal_classifier/pii_detector.py:108` `_passes_luhn`, including its
    `len(set(value)) == 1` guard - a run of identical digits passes Luhn about a
    tenth of the time and is essentially never a real card.

    The length window is a parameter here rather than hardcoded to 13..19,
    because the NPI check needs it over 14 digits.
    """
    if not value.isdigit() or len(set(value)) == 1:
        return False
    checksum = 0
    parity = len(value) % 2
    for index, char in enumerate(value):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def luhn_card(value: str) -> bool:
    """Luhn restricted to the card-number length window used upstream."""
    return 13 <= len(value) <= 19 and luhn(value)


# Verhoeff dihedral-group tables (D5). UIDAI mandates a Verhoeff check digit on
# every Aadhaar number, and the source-level analysis calls this out for AFNI
# specifically. NOTE, because it matters for provenance: the Infosys toolkit's
# recognizer at
# `references/Infosys-Responsible-AI-Toolkit-master/responsible-ai-privacy/
#  presidio_analyzer/.../predefined_recognizers/Aadhaar_Number.py:17`
# is pattern-only - it has NO checksum, and scores every 12-digit
# "[2-9]nnn nnnn nnnn" run at 0.5. The regex below is ported from there; the
# Verhoeff tables are the published D5 multiplication, permutation and inverse
# tables and are NOT from any vendored repo. Test vector: 236 -> check digit 3.
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def verhoeff(value: str) -> bool:
    """True when `value`'s trailing digit is a valid Verhoeff check digit."""
    if not value.isdigit() or not value:
        return False
    check = 0
    for index, char in enumerate(reversed(value)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[index % 8][int(char)]]
    return check == 0


def verhoeff_check_digit(body: str) -> str:
    """The digit that makes `body + digit` pass `verhoeff`. Test fixtures only."""
    check = 0
    for index, char in enumerate(reversed(body)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[(index + 1) % 8][int(char)]]
    return str(_VERHOEFF_INV[check])


def aadhaar(value: str) -> bool:
    """India Aadhaar: 12 digits, leading 2-9, Verhoeff-valid, not a digit run."""
    number = digits_only(value)
    if len(number) != 12 or number[0] in "01" or len(set(number)) == 1:
        return False
    return verhoeff(number)


def npi(value: str) -> bool:
    """US National Provider Identifier check digit.

    The rule is Luhn over the number prefixed with the 80840 issuer identifier
    (CMS NPI standard - stated here rather than cited, because no vendored repo
    implements NPI validation; hai-guardrails matches the shape only, at
    `references/hai-guardrails-main/hai-guardrails-main/src/guards/
     pii.guard.ts:71-76`). The Luhn arithmetic itself is the agentic_security
    port above. Test vector: 1234567893.
    """
    number = digits_only(value)
    return len(number) == 10 and luhn("80840" + number)


def dea(value: str) -> bool:
    """US DEA registration number check digit.

    Ported from the Infosys toolkit's Presidio recognizer at
    `references/Infosys-Responsible-AI-Toolkit-master/responsible-ai-privacy/
     presidio_analyzer/presidio_analyzer/Infosys_presidio_analyzer/
     presidio_analyzer/presidio_analyzer/predefined_recognizers/
     medical_license_recognizer.py:59-70` - the two registrant letters are
    dropped, then (d1+d3+d5) + 2*(d2+d4+d6) must end in the 7th digit.
    Test vector: AB1234563 valid, AB1234561 invalid.
    """
    number = digits_only(value)
    if len(number) != 7:
        return False
    digits = [int(c) for c in number]
    check = digits.pop()
    even = digits[-1::-2]      # positions 2, 4, 6
    odd = digits[-2::-2]       # positions 1, 3, 5
    return (2 * sum(even) + sum(odd) - check) % 10 == 0


_IBAN_LETTER = {chr(ord("A") + i): str(10 + i) for i in range(26)}


def iban(value: str) -> bool:
    """ISO 13616 mod-97 IBAN check.

    Safe Zone's `IBAN_TR` pattern (`references/safe-zone-main/safe-zone-main/
    init.sql:29`) is shape-only, so a transposed digit sails through it. The
    mod-97 rule is the ISO standard: rotate the first four characters to the
    end, map letters to numbers (A=10..Z=35), and the integer must be 1 mod 97.
    """
    compact = re.sub(r"[\s-]", "", value).upper()
    if not (15 <= len(compact) <= 34) or not compact[:2].isalpha():
        return False
    if not compact[2:4].isdigit() or not compact[4:].isalnum():
        return False
    rotated = compact[4:] + compact[:4]
    try:
        numeric = "".join(_IBAN_LETTER[c] if c.isalpha() else c for c in rotated)
    except KeyError:
        return False
    return int(numeric) % 97 == 1


_PAN_HOLDER_TYPES = set("ABCFGHLJPTKE")


def pan(value: str) -> bool:
    """India PAN structural check.

    The pattern is Infosys' (`PAN_Number.py:17`, `[A-Z]{5}[0-9]{4}[A-Z]{1}`),
    which on its own matches any 10-character token of that shape. The 4th
    character is the holder-type code, which is what actually distinguishes a
    PAN from an arbitrary alphanumeric id, so it is checked here.
    """
    return len(value) == 10 and value[3].upper() in _PAN_HOLDER_TYPES


# --------------------------------------------------------------------------- #
# Detector table                                                               #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Detector:
    """One regex plus, where the identifier has one, its checksum.

    `group` names the capture group carrying the identifier itself, so a pattern
    can require a `MRN:` prefix for precision without putting the prefix in the
    `subject` or the redaction span.
    """

    entity: str
    category: str
    pattern: re.Pattern[str]
    replacement: str
    severity: Severity
    validator: Callable[[str], bool] | None = None
    group: int = 0
    context: tuple[str, ...] = ()
    context_window: int = 48
    evidence: str = ""

    def scan(self, folded: str, original: str) -> list["Hit"]:
        hits: list[Hit] = []
        for match in self.pattern.finditer(folded):
            try:
                start, end = match.span(self.group)
            except IndexError:                       # pragma: no cover
                start, end = match.span(0)
            if start < 0:
                continue
            candidate = folded[start:end]
            if self.validator is not None and not self.validator(candidate):
                continue
            if self.context and not self._in_context(folded, match.start()):
                continue
            hits.append(Hit(
                detector=self,
                start=start,
                end=end,
                # Reported from the ORIGINAL payload, not the folded copy: the
                # operator's false-positive exception has to key on the bytes
                # that were actually sent.
                subject=original[start:end],
            ))
        return hits

    def _in_context(self, folded: str, at: int) -> bool:
        """Presidio-style context boost, used as a gate rather than a score.

        A bare `[A-TV-Z]\\d\\d` is an ICD-10 code and is also "vitamin B12".
        Requiring a context word nearby is the difference between a PHI rail and
        a redaction storm.
        """
        window = folded[max(0, at - self.context_window):at + self.context_window].lower()
        return any(word in window for word in self.context)


@dataclass(frozen=True)
class Hit:
    detector: Detector
    start: int
    end: int
    subject: str


def resolve_overlaps(hits: Sequence[Hit]) -> list[Hit]:
    """Keep the longest match per region, earliest wins on a tie.

    Without this a card candidate and a phone pattern can both claim the same
    digits and the payload gets two overlapping redaction spans, which is not a
    thing a caller can apply.
    """
    ordered = sorted(hits, key=lambda h: (h.start, -(h.end - h.start)))
    kept: list[Hit] = []
    for hit in ordered:
        if kept and hit.start < kept[-1].end:
            continue
        kept.append(hit)
    return kept


# --- PII entities ---------------------------------------------------------- #
# Email: identical in three of the vendored repos - hai-guardrails
# pii.guard.ts:17, agentic_security pii_detector.py:36, safe-zone init.sql:24.
EMAIL = Detector(
    entity="EMAIL_ADDRESS",
    category="privacy.pii.email",
    pattern=re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    replacement="[REDACTED-EMAIL]",
    severity=Severity.MEDIUM,
    evidence="hai-guardrails src/guards/pii.guard.ts:17; "
             "agentic_security refusal_classifier/pii_detector.py:36",
)

# Phone: agentic_security's is the tightest of the set. hai-guardrails uses
# `\b\d{3}[-.]?\d{3}[-.]?\d{4}\b` (pii.guard.ts:24), which is the same shape but
# without the `(?<!\w)`/`(?!\w)` guards, so it fires inside longer digit runs.
PHONE = Detector(
    entity="PHONE_NUMBER",
    category="privacy.pii.phone_number",
    pattern=re.compile(
        r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?"
        r"(?:\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})(?!\w)"
    ),
    replacement="[REDACTED-PHONE]",
    severity=Severity.MEDIUM,
    evidence="agentic_security refusal_classifier/pii_detector.py:47-48",
)

# IP: pattern from hai-guardrails pii.guard.ts:44. It has no octet range check,
# so `10.4.256.1` and the `1.2.3.4` inside a five-part version string both match.
# Octet validation and the `(?<![\d.])`/`(?!\.?\d)` guards are added here.
IP_ADDRESS = Detector(
    entity="IP_ADDRESS",
    category="privacy.pii.ip_address",
    pattern=re.compile(r"(?<![\d.])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\.?\d)"),
    replacement="[REDACTED-IP-ADDRESS]",
    severity=Severity.MEDIUM,
    validator=lambda v: all(0 <= int(o) <= 255 for o in v.split(".")),
    evidence="hai-guardrails src/guards/pii.guard.ts:44 (octet check added here)",
)

# --- region-specific identifiers ------------------------------------------- #
# SSN: agentic_security's invalid-prefix exclusions (no 000/666/9xx area, no 00
# group, no 0000 serial) over Infosys' wider `[- .]` separator class. Both a
# separator and the exclusions are load-bearing: hai-guardrails' SSN pattern
# (pii.guard.ts:31) makes the separator optional, which means every bare 9-digit
# number in the payload is an SSN to it.
US_SSN = Detector(
    entity="US_SSN",
    category="privacy.pii.national_id.us",
    pattern=re.compile(r"\b(?!000|666|9\d{2})\d{3}[- .](?!00)\d{2}[- .](?!0000)\d{4}\b"),
    replacement="[REDACTED-US-SSN]",
    severity=Severity.HIGH,
    evidence="agentic_security refusal_classifier/pii_detector.py:41 (exclusions); "
             "Infosys us_ssn_recognizer.py:23 (separator class)",
)

US_ITIN = Detector(
    entity="US_ITIN",
    category="privacy.pii.tax_id.us",
    pattern=re.compile(r"\b9\d{2}[- ](?:5\d|6[0-5]|7\d|8[0-8]|9(?:[0-2]|[4-9]))[- ]\d{4}\b"),
    replacement="[REDACTED-US-ITIN]",
    severity=Severity.HIGH,
    evidence="Infosys predefined_recognizers/us_itin_recognizer.py:27 "
             "('Itin (medium)', score 0.5)",
)

IN_AADHAAR = Detector(
    entity="IN_AADHAAR",
    category="privacy.pii.national_id.in",
    pattern=re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b"),
    replacement="[REDACTED-IN-AADHAAR]",
    severity=Severity.HIGH,
    validator=aadhaar,
    evidence="Infosys predefined_recognizers/Aadhaar_Number.py:17 (pattern); "
             "Verhoeff D5 check digit added - upstream has none",
)

IN_PAN = Detector(
    entity="IN_PAN",
    category="privacy.pii.tax_id.in",
    pattern=re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    replacement="[REDACTED-IN-PAN]",
    severity=Severity.HIGH,
    validator=pan,
    evidence="Infosys predefined_recognizers/PAN_Number.py:17 (pattern); "
             "holder-type character check added",
)

UK_NINO = Detector(
    entity="UK_NINO",
    category="privacy.pii.national_id.gb",
    pattern=re.compile(r"\b[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\d{6}[A-D]\b"),
    replacement="[REDACTED-UK-NINO]",
    severity=Severity.HIGH,
    evidence="safe-zone init.sql:35 ('UK_NINO')",
)

IBAN_CODE = Detector(
    entity="IBAN_CODE",
    category="privacy.pii.bank_account",
    pattern=re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]{4}){2,7}(?:[ -]?[A-Z0-9]{1,3})?\b"),
    replacement="[REDACTED-IBAN]",
    severity=Severity.HIGH,
    validator=iban,
    evidence="safe-zone init.sql:29 ('IBAN_TR', shape only); "
             "generalised to any country code and gated on ISO 13616 mod-97",
)

# --- payment cards --------------------------------------------------------- #
# Candidate window and the digit-run rejection come from agentic_security. The
# IIN gate is the idea behind LLM Guard's CREDIT_CARD_RE
# (anonymize_helpers/regex_patterns.py:37), which only accepts Visa, Amex and
# Diners prefixes for exactly this reason; the family list here is wider.
_CARD_IIN = (
    ("visa", re.compile(r"^4\d{12}(?:\d{3})?(?:\d{3})?$")),
    ("mastercard", re.compile(r"^(?:5[1-5]\d{14}|2(?:22[1-9]|2[3-9]\d|[3-6]\d\d|7[01]\d|720)\d{12})$")),
    ("amex", re.compile(r"^3[47]\d{13}$")),
    ("discover", re.compile(r"^(?:6011\d{12}|65\d{14}|64[4-9]\d{13}|622(?:12[6-9]|1[3-9]\d|[2-8]\d\d|9[01]\d|92[0-5])\d{10})$")),
    ("diners", re.compile(r"^3(?:0[0-5]\d{11}|[68]\d{12})$")),
    ("jcb", re.compile(r"^35(?:2[89]|[3-8]\d)\d{12}$")),
    ("unionpay", re.compile(r"^62\d{14,17}$")),
    ("maestro", re.compile(r"^(?:5018|5020|5038|5893|6304|6759|676[1-3])\d{8,15}$")),
)


def card_brand(number: str) -> str | None:
    for brand, pattern in _CARD_IIN:
        if pattern.match(number):
            return brand
    return None


def credit_card(value: str) -> bool:
    number = digits_only(value)
    return luhn_card(number) and card_brand(number) is not None


CREDIT_CARD = Detector(
    entity="CREDIT_CARD",
    category="privacy.pii.bank_card",
    # agentic_security's candidate is `(?<!\d)(?:\d[ -]?){13,19}(?!\d)`, which
    # puts the optional separator INSIDE the repeat, so on "4111 1111 1111 1111
    # done" the match runs one character past the last digit and the redaction
    # span eats the following space. Anchored on a digit at both ends here; the
    # accepted digit count is unchanged.
    pattern=re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)"),
    replacement="[REDACTED-CREDIT-CARD]",
    severity=Severity.HIGH,
    validator=credit_card,
    evidence="agentic_security refusal_classifier/pii_detector.py:67 "
             "CREDIT_CARD_CANDIDATE, :108 _passes_luhn; "
             "llm-guard anonymize_helpers/regex_patterns.py:37 (IIN gate); "
             "candidate anchored on a digit at both ends here",
)

# --- healthcare PHI -------------------------------------------------------- #
# All four patterns are hai-guardrails' - the only dedicated PHI regex set in
# the 23 reviewed repos (capability_matrix_data.json calls it exactly that).
#
# ICD-10 is gated on context or a decimal subcode. Upstream's bare pattern
# redacts "vitamin B12", "form W22" and "Room T10"; the gate is what makes it
# usable on real BPO text.
_ICD10_CONTEXT = ("icd", "diagnos", "dx", "coded", "code ", "codes",
                  "discharge", "chart", "encounter", "billing", "claim")
ICD10 = Detector(
    entity="ICD10_CODE",
    category="x.afni.phi.icd10",
    pattern=re.compile(r"\b[A-TV-Z][0-9]{2}(?:\.[0-9A-TV-Z]{1,4})\b"),
    replacement="[REDACTED-ICD10]",
    severity=Severity.HIGH,
    evidence="hai-guardrails src/guards/pii.guard.ts:50-55 "
             "(decimal subcode required here)",
)
ICD10_CONTEXTUAL = Detector(
    entity="ICD10_CODE",
    category="x.afni.phi.icd10",
    pattern=re.compile(r"\b[A-TV-Z][0-9]{2}\b"),
    replacement="[REDACTED-ICD10]",
    severity=Severity.HIGH,
    context=_ICD10_CONTEXT,
    evidence="hai-guardrails src/guards/pii.guard.ts:50-55 "
             "(context gate added; upstream matches 'vitamin B12')",
)

# MRN: hai-guardrails' alphanumeric variant (:64-69) requires the prefix. Its
# numeric variant (:57-62) makes the prefix optional and therefore matches every
# 7-10 digit integer; that variant is deliberately NOT ported. The prefix stays
# outside the capture group so it is not redacted or fingerprinted.
MRN = Detector(
    entity="MEDICAL_RECORD_NUMBER",
    category="privacy.pii.health_id.mrn",
    pattern=re.compile(
        r"\b(?:MRN|MR|MEDICAL\s*RECORD)(?:\s*(?:NO|NUM|NUMBER|#))?[-:\s#]*([A-Z0-9]{6,12})\b",
        re.IGNORECASE),
    replacement="[REDACTED-MRN]",
    severity=Severity.HIGH,
    group=1,
    evidence="hai-guardrails src/guards/pii.guard.ts:64-69 (prefix required; "
             "the optional-prefix mrn-numeric variant at :57-62 is not ported)",
)

NPI = Detector(
    entity="US_NPI",
    category="privacy.pii.health_id.npi",
    pattern=re.compile(r"\bNPI[-:\s#]*(\d{10})\b", re.IGNORECASE),
    replacement="[REDACTED-NPI]",
    severity=Severity.HIGH,
    validator=npi,
    group=1,
    evidence="hai-guardrails src/guards/pii.guard.ts:71-76 (pattern); "
             "80840-prefixed Luhn check digit added",
)

DEA = Detector(
    entity="US_DEA",
    category="privacy.pii.health_id.dea",
    pattern=re.compile(r"\bDEA[-:\s#]*([A-Z]{2}\d{7})\b", re.IGNORECASE),
    replacement="[REDACTED-DEA]",
    severity=Severity.HIGH,
    validator=dea,
    group=1,
    evidence="hai-guardrails src/guards/pii.guard.ts:78-83 (pattern); "
             "Infosys medical_license_recognizer.py:59-70 (check digit)",
)

PII_DETECTORS = (EMAIL, PHONE, IP_ADDRESS)
REGION_DETECTORS = (US_SSN, US_ITIN, IN_AADHAAR, IN_PAN, UK_NINO, IBAN_CODE)
CARD_DETECTORS = (CREDIT_CARD,)
PHI_DETECTORS = (ICD10, ICD10_CONTEXTUAL, MRN, NPI, DEA)
ALL_DETECTORS = PII_DETECTORS + REGION_DETECTORS + CARD_DETECTORS + PHI_DETECTORS


# --------------------------------------------------------------------------- #
# Stage 1 - the deterministic rails                                            #
# --------------------------------------------------------------------------- #
class _DetectorRail:
    """Shared body for the four pattern-and-checksum rails.

    One `check()` implementation, four detector sets. Nothing here blocks: per
    the OpenGuardrails taxonomy, PII drives masking rather than refusal, so the
    rail emits `Action.REDACT` plus a `Span` and lets policy decide.
    """

    stage = Stage.STAGE_1
    tenet = TENET

    def __init__(self, name: str, detectors: Sequence[Detector]) -> None:
        self.name = name
        self.detectors = tuple(detectors)

    def hits(self, text: str) -> list[Hit]:
        folded = fold(text)
        found: list[Hit] = []
        for detector in self.detectors:
            found.extend(detector.scan(folded, text))
        return resolve_overlaps(found)

    def check(self, path: str, text: str) -> RailResult:
        if not text:
            return RailResult.clean()
        hits = self.hits(text)
        if not hits:
            return RailResult.clean()
        findings = [
            Finding(
                category=hit.detector.category,
                severity=hit.detector.severity,
                action=Action.REDACT,
                path=path,
                start=hit.start,
                end=hit.end,
                detector=self.name,
                subject=hit.subject,
                fp=fingerprint(hit.subject),
            )
            for hit in hits
        ]
        spans = [
            Span(path=path, start=hit.start, end=hit.end,
                 replacement=hit.detector.replacement)
            for hit in hits
        ]
        return RailResult(findings=findings, modifications=spans)


class PiiEntityRail(_DetectorRail):
    """Email, phone and IP address, with redaction spans."""

    def __init__(self) -> None:
        super().__init__("privacy.pii_entities", PII_DETECTORS)


class RegionIdRail(_DetectorRail):
    """Region-specific national and tax identifiers, checksum-validated where
    the identifier carries one: Verhoeff for Aadhaar, mod-97 for IBAN."""

    def __init__(self) -> None:
        super().__init__("privacy.region_ids", REGION_DETECTORS)


class CreditCardRail(_DetectorRail):
    """Payment cards: candidate scan, Luhn, then an IIN family gate."""

    def __init__(self) -> None:
        super().__init__("privacy.credit_card", CARD_DETECTORS)


class HealthcarePhiRail(_DetectorRail):
    """Healthcare PHI: ICD-10, MRN, NPI, DEA - the hai-guardrails set, gated."""

    def __init__(self) -> None:
        super().__init__("privacy.healthcare_phi", PHI_DETECTORS)


# --------------------------------------------------------------------------- #
# Stage 1 - reversible anonymisation                                           #
# --------------------------------------------------------------------------- #
class Vault:
    """Placeholder-to-value store for reversible redaction.

    Ported from `references/llm-guard-main/llm-guard-main/llm_guard/vault.py`,
    which is the ONLY reversible redaction mechanism in any of the 23 reviewed
    repos - everything else is one-way masking. Same API surface (`append`,
    `extend`, `remove`, `get`, `placeholder_exists`) plus `resolve` and `clear`,
    and it stays pure stdlib, exactly as upstream is.

    Deliberately NOT thread-shared: one vault per conversation. A process-wide
    vault would let one tenant's placeholder resolve to another tenant's value,
    which is a data-leak primitive rather than a privacy control.
    """

    def __init__(self, tuples: list[tuple[str, str]] | None = None) -> None:
        self._tuples: list[tuple[str, str]] = list(tuples or [])

    def append(self, new_tuple: tuple[str, str]) -> None:
        self._tuples.append(new_tuple)

    def extend(self, new_tuples: Iterable[tuple[str, str]]) -> None:
        self._tuples.extend(new_tuples)

    def remove(self, tuple_to_remove: tuple[str, str]) -> None:
        self._tuples.remove(tuple_to_remove)

    def get(self) -> list[tuple[str, str]]:
        return list(self._tuples)

    def placeholder_exists(self, placeholder: str) -> bool:
        return any(p == placeholder for p, _ in self._tuples)

    def resolve(self, placeholder: str) -> str | None:
        for holder, value in self._tuples:
            if holder == placeholder:
                return value
        return None

    def placeholder_for(self, entity: str, value: str) -> str | None:
        """The placeholder already minted for this value, if any."""
        prefix = f"[REDACTED_{entity}_"
        for holder, stored in self._tuples:
            if stored == value and holder.startswith(prefix):
                return holder
        return None

    def next_index(self, entity: str) -> int:
        prefix = f"[REDACTED_{entity}_"
        used = 0
        for holder, _ in self._tuples:
            if holder.startswith(prefix):
                try:
                    used = max(used, int(holder[len(prefix):-1]))
                except ValueError:                       # pragma: no cover
                    continue
        return used + 1

    def clear(self) -> None:
        self._tuples.clear()

    def __len__(self) -> int:
        return len(self._tuples)


class ReversibleAnonymiserRail:
    """Pseudonymise every detected identifier to a stable placeholder, keeping
    the real value in a vault so the model's reply can be re-hydrated.

    This is the rail that makes redaction usable rather than merely safe. A
    one-way mask breaks any downstream task that has to *refer* to the customer
    ("call Mr Smith back on his mobile"); LLM Guard solves it with
    `Anonymize` -> `Vault` -> `Deanonymize`, and this is that loop in stdlib.

    Placeholder format and the reuse rule are upstream's:
      - `[REDACTED_{ENTITY}_{n}]` - `input_scanners/anonymize.py:232-233`
      - the same value inside one conversation gets the same placeholder -
        `input_scanners/anonymize.py:273-286`
      - `deanonymise` is exact-string replacement - `output_scanners/
        deanonymize.py:29-41` (`MatchingStrategy._match_exact`). Upstream's
        fuzzy strategy needs the `fuzzysearch` package and is not ported.
    """

    stage = Stage.STAGE_1
    tenet = TENET
    name = "privacy.reversible_anonymiser"

    def __init__(self, vault: Vault | None = None,
                 detectors: Sequence[Detector] = ALL_DETECTORS) -> None:
        self.vault = vault if vault is not None else Vault()
        self.detectors = tuple(detectors)

    def _placeholder(self, entity: str, value: str) -> str:
        existing = self.vault.placeholder_for(entity, value)
        if existing is not None:
            return existing
        holder = f"[REDACTED_{entity}_{self.vault.next_index(entity)}]"
        self.vault.append((holder, value))
        return holder

    def check(self, path: str, text: str) -> RailResult:
        if not text:
            return RailResult.clean()
        folded = fold(text)
        raw: list[Hit] = []
        for detector in self.detectors:
            raw.extend(detector.scan(folded, text))
        hits = resolve_overlaps(raw)
        if not hits:
            return RailResult.clean()

        findings: list[Finding] = []
        spans: list[Span] = []
        for hit in hits:
            holder = self._placeholder(hit.detector.entity, hit.subject)
            findings.append(Finding(
                category=hit.detector.category,
                severity=hit.detector.severity,
                action=Action.REDACT,
                path=path,
                start=hit.start,
                end=hit.end,
                detector=self.name,
                subject=hit.subject,
                fp=fingerprint(hit.subject),
            ))
            spans.append(Span(path=path, start=hit.start, end=hit.end,
                              replacement=holder))
        return RailResult(findings=findings, modifications=spans)

    def anonymise(self, text: str) -> str:
        """Apply this rail's own spans, left to right. Convenience for callers
        that want the redacted string rather than the span list."""
        result = self.check("payload", text)
        out, cursor = [], 0
        for span in sorted(result.modifications, key=lambda s: s.start):
            out.append(text[cursor:span.start])
            out.append(span.replacement)
            cursor = span.end
        out.append(text[cursor:])
        return "".join(out)

    def deanonymise(self, text: str) -> str:
        """Exact-match restore, per `deanonymize.py:29-41`."""
        for holder, value in self.vault.get():
            text = text.replace(holder, value)
        return text


# --------------------------------------------------------------------------- #
# Stage 1 - system-prompt leakage                                              #
# --------------------------------------------------------------------------- #
# Request side: the extraction-probe patterns from hai-guardrails' leakageGuard.
# Its `pattern` mode is pure regex and therefore Stage 1; its `language-model`
# mode is the Stage 3 half of the same guard and is not ported here.
_LEAK_PROBE_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bwhat (is|are) (your|the) (system|initial|original|base)? ?"
    r"(prompt|instructions|context|rules|message|configuration)\b",
    r"\brepeat (your|the) (instructions|prompt|context|rules|message)\b",
    r"\bshow (me )?(your|the) (prompt|instructions|context|rules|message)\b",
    r"\bprint (your|the) (prompt|instructions|context|rules|message)\b",
    r"\breveal (your|the) (prompt|instructions|context|rules|message)\b",
    r"\bwho programmed you\b",
    r"\bwhat did your developer tell you\b",
    r"\bwhat are you allowed to do\b",
    r"\bwhat are your (restrictions|capabilities|training data)\b",
))

_WHITESPACE = re.compile(r"\s")


def ngram_containment(target: str, context: str, n: int = 4) -> float:
    """Proportion of `target`'s character n-grams present in `context`.

    Ported verbatim in behaviour from `references/garak-main/garak/resources/
    matching.py:5-27` (`ngram_contained_match`), the function garak's
    `detectors/sysprompt_extraction.py:95` uses to decide whether a system
    prompt has been extracted. Asymmetric on purpose: it measures how much of
    the system prompt shows up in the reply and ignores everything else the
    reply contains.

    garak itself is an OFFLINE tool and is registered as such below - what is
    ported here is this one pure-Python function, not the probe harness.
    """
    if not target or not context or len(target) < n:
        return 0.0
    target, context = target.lower(), context.lower()
    grams = {target[i:i + n] for i in range(len(target) - (n - 1))}
    return sum(1 for gram in grams if gram in context) / len(grams)


def _mildly_sanitise(text: str) -> str:
    """`sysprompt_extraction.py:47-48`."""
    return _WHITESPACE.sub(" ", text).strip()


class SystemPromptLeakageRail:
    THRESHOLD_KEY = "privacy.system_prompt_leakage"
    """Two deterministic halves of one problem.

    **Request side** (always on): the 9 extraction-probe patterns from
    `references/hai-guardrails-main/hai-guardrails-main/src/guards/
    leakage.guard.ts:31-41`. A probe is a flag, not a block - "what are you
    allowed to do" is a reasonable question as often as it is an attack - so it
    flags and asks for escalation.

    **Response side** (needs configuration): character n-gram containment of the
    configured system prompt in the payload, per garak's
    `detectors/sysprompt_extraction.py:70-104`, with its verbatim-excerpt
    shortcut. A confirmed leak DOES block: the secret is already in the buffer
    and the only useful action left is to stop it leaving.

    `output_paths` exists to prevent the obvious self-inflicted false positive:
    on a request event the system prompt is legitimately *in* the payload as the
    system message, and n-gram-matching it against itself would flag every
    single request. So the containment check runs only on payload paths that
    look like model output. Note what is deliberately NOT in the default tuple:
    `message`, because `payload.messages[0].content` - the request-side system
    message - contains it as a substring, and including it reintroduced exactly
    the false positive this parameter exists to stop. The OpenAI response shape
    is still covered by `choices`. If a deployment's paths are named
    differently it passes its own tuple; the rail never guesses.

    `confidence_kind` is `deterministic` for both halves - no model is involved
    either way. The score on a containment hit is a measured overlap fraction
    rather than a probability, which is noted in the attribution evidence so a
    reader does not compare it against a classifier's 0.87.
    """

    stage = Stage.STAGE_1
    tenet = TENET
    name = "privacy.system_prompt_leakage"

    def __init__(self, system_prompt: str | None = None, *,
                 threshold: float = 0.6, n: int = 4,
                 min_prompt_len: int = 20, excerpt_score: float = 0.95,
                 output_paths: tuple[str, ...] = (
                     "output", "completion", "choices", "response",
                     "bot_message", "assistant")) -> None:
        self.system_prompt = system_prompt
        self.threshold = threshold
        self.n = n
        self.min_prompt_len = min_prompt_len
        self.excerpt_score = excerpt_score
        self.output_paths = output_paths

    def _looks_like_output(self, path: str) -> bool:
        lowered = path.lower()
        return any(hint in lowered for hint in self.output_paths)

    def _containment(self, text: str) -> float:
        target = _mildly_sanitise(self.system_prompt or "")
        context = _mildly_sanitise(text)
        if not target or not context:
            return 0.0
        # garak's verbatim-excerpt shortcut: a reply truncated by a token limit
        # is still a full extraction.
        if len(context) > self.min_prompt_len and (target in context or context in target):
            return self.excerpt_score
        return ngram_containment(target, context, self.n)

    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Per-tenant threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self.threshold)
                     if ctx is not None else self.threshold)
        if not text:
            return RailResult.clean()
        findings: list[Finding] = []
        block = False

        folded = fold(text)
        probe = next((p for p in _LEAK_PROBE_PATTERNS if p.search(folded)), None)
        if probe is not None:
            match = probe.search(folded)
            findings.append(Finding(
                category="x.afni.privacy.system_prompt_probe",
                severity=Severity.MEDIUM,
                action=Action.FLAG,
                path=path,
                start=match.start(),
                end=match.end(),
                detector=self.name,
                subject=text[match.start():match.end()],
                fp=fingerprint(text[match.start():match.end()]),
            ))

        if self.system_prompt and self._looks_like_output(path):
            score = self._containment(text)
            if score >= threshold:
                findings.append(Finding(
                    category="x.afni.privacy.system_prompt_leak",
                    severity=Severity.CRITICAL,
                    action=Action.BLOCK,
                    path=path,
                    score=round(min(score, 1.0), 4),
                    detector=self.name,
                    # Deliberately no subject: the subject here would be the
                    # system prompt itself.
                ))
                block = True

        if not findings:
            return RailResult.clean()
        return RailResult(
            findings=findings,
            block=block,
            # A probe alone is worth a second opinion; a confirmed leak is not -
            # it already blocked, and escalating would only spend money.
            escalate=not block,
        )


# --------------------------------------------------------------------------- #
# Stage 2 - Presidio depth layer                                               #
# --------------------------------------------------------------------------- #
_PRESIDIO_ENTITIES = (
    "CREDIT_CARD", "CRYPTO", "EMAIL_ADDRESS", "IBAN_CODE", "IP_ADDRESS",
    "PERSON", "PHONE_NUMBER", "US_SSN", "US_BANK_NUMBER", "LOCATION",
)

# `specification/taxonomy.md:155-163` publishes the presidio -> taxonomy mapping.
# Using theirs rather than inventing one is the whole reason for adopting the
# OpenGuardrails contract.
PRESIDIO_TO_CATEGORY = {
    "US_SSN": "privacy.pii.national_id.us",
    "US_ITIN": "privacy.pii.tax_id.us",
    "IN_AADHAAR": "privacy.pii.national_id.in",
    "PL_PESEL": "privacy.pii.national_id.pl",
    "KR_RRN": "privacy.pii.national_id.kr",
    "UK_NHS": "privacy.pii.health_id.uk",
    "IT_FISCAL_CODE": "privacy.pii.tax_id.it",
    "CREDIT_CARD": "privacy.pii.bank_card",
    "IBAN_CODE": "privacy.pii.bank_account",
    "US_BANK_NUMBER": "privacy.pii.bank_account",
    "PHONE_NUMBER": "privacy.pii.phone_number",
    "PERSON": "privacy.pii.person_name",
    "LOCATION": "privacy.pii.address",
    "EMAIL_ADDRESS": "privacy.pii.email",
    "IP_ADDRESS": "privacy.pii.ip_address",
    "CRYPTO": "privacy.pii.credential",
    "DATE_TIME": "privacy.pii.date_time",
    "URL": "privacy.pii.url",
}


class PresidioPiiRail:
    THRESHOLD_KEY = "privacy.pii.ner_score"
    """The NER depth layer: the entities regex structurally cannot find.

    A checksum finds an SSN. Nothing in Stage 1 finds "the claimant, Margaret
    Okafor, at 14 Ashgrove Terrace" - that needs a model, and it is exactly what
    LLM Guard's `Anonymize` scanner delegates to presidio-analyzer 2.2.358
    (`input_scanners/anonymize.py:28-40`, entity list at `:27-41`) and what NeMo
    Guardrails' sensitive-data rails do
    (`library/sensitive_data_detection/actions.py:81`).

    `presidio-analyzer` is NOT installed in this environment, so this rail
    reports `unjudged` on every call. That is the honest answer and not a pass:
    the cascade will fail closed on client-facing traffic that reached Stage 2.
    The import is behind `find_spec` and the engine is built on first use, so
    importing this module downloads nothing and touches no network.
    """

    stage = Stage.STAGE_2
    tenet = TENET
    name = "privacy.presidio_ner"

    def __init__(self, entities: Sequence[str] = _PRESIDIO_ENTITIES,
                 score_threshold: float = 0.5, language: str = "en") -> None:
        self.entities = tuple(entities)
        self.score_threshold = score_threshold
        self.language = language
        self._analyzer = None
        self._unavailable: str | None = None

    @staticmethod
    def dependency_available() -> bool:
        """True when `presidio-analyzer` is importable. No import performed."""
        return importlib.util.find_spec("presidio_analyzer") is not None

    def preload(self) -> bool:
        """Build the Presidio engine and load the spaCy pipeline now. Measured
        at ~3.5 s cold, which is 3.5 s the first request should not pay."""
        return self._engine() is not None

    def _engine(self):
        if self._analyzer is not None or self._unavailable is not None:
            return self._analyzer
        if not self.dependency_available():
            self._unavailable = (
                "presidio-analyzer not installed (LLM Guard pins "
                "presidio-analyzer==2.2.358); install it plus the spaCy "
                "en_core_web_lg model to enable the Privacy stage-2 NER layer"
            )
            return None
        try:
            from presidio_analyzer import AnalyzerEngine  # noqa: PLC0415

            _quieten_loaded()
            self._analyzer = AnalyzerEngine(
                default_score_threshold=self.score_threshold)
        except Exception as exc:                          # noqa: BLE001
            self._unavailable = f"presidio-analyzer failed to initialise: {exc}"
            return None
        return self._analyzer

    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Per-tenant threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self.score_threshold)
                     if ctx is not None else self.score_threshold)
        engine = self._engine()
        if engine is None:
            return RailResult.unjudged(self._unavailable or "presidio unavailable")
        try:
            # Presidio takes the threshold PER CALL, so unlike the llm-guard
            # scanners no rebuild is needed - the engine's
            # `default_score_threshold` is only a fallback for calls that omit it.
            results = engine.analyze(text=text, language=self.language,
                                     entities=list(self.entities),
                                     score_threshold=threshold)
        except TypeError:
            # An older analyzer without the per-call argument. Fall back to the
            # engine default and rely on the filter below, rather than silently
            # ignoring the tenant's threshold.
            try:
                results = engine.analyze(text=text, language=self.language,
                                         entities=list(self.entities))
            except Exception as exc:                      # noqa: BLE001
                return RailResult.unjudged(f"presidio analyze failed: {exc}")
        except Exception as exc:                          # noqa: BLE001
            return RailResult.unjudged(f"presidio analyze failed: {exc}")

        findings: list[Finding] = []
        spans: list[Span] = []
        for res in results:
            # Belt and braces. Passing score_threshold above should already have
            # dropped these, but a tenant tightening the threshold must drop
            # entities even if the engine ignored the argument - otherwise the
            # threshold is decorative, which is the whole failure mode being
            # fixed here.
            if float(getattr(res, "score", 0.0)) < threshold:
                continue
            entity = getattr(res, "entity_type", "") or ""
            category = PRESIDIO_TO_CATEGORY.get(entity, "privacy.pii")
            subject = text[res.start:res.end]
            findings.append(Finding(
                category=category,
                severity=Severity.HIGH if entity in (
                    "US_SSN", "CREDIT_CARD", "IBAN_CODE", "US_BANK_NUMBER",
                ) else Severity.MEDIUM,
                action=Action.REDACT,
                path=path,
                start=res.start,
                end=res.end,
                score=round(float(getattr(res, "score", 0.0)), 4),
                detector=self.name,
                subject=subject,
                fp=fingerprint(subject),
            ))
            spans.append(Span(path=path, start=res.start, end=res.end,
                              replacement=f"[REDACTED-{entity or 'PII'}]"))
        if not findings:
            return RailResult.clean()
        return RailResult(findings=findings, modifications=spans)


# --------------------------------------------------------------------------- #
# Stage 3 - LLM-judge PII leakage                                              #
# --------------------------------------------------------------------------- #
class PiiLeakageJudgeRail:
    THRESHOLD_KEY = "privacy.pii.leakage_judge"
    """Did the model *disclose* personal data it should not have?

    This is a different question from "does this string contain an SSN", and it
    is the only Privacy question in the set that regex cannot reach: a reply that
    confirms which of two customers holds an account leaks personal data without
    containing a single matchable entity. DeepTeam's `PIIMetric`
    (`references/deepteam-main/deepteam/metrics/pii/pii.py:27`, prompt at
    `metrics/pii/template.py`) scores exactly that with an LLM judge, and its
    `PrivacyGuard` screens live traffic with gpt-4.1.

    It is Stage 3 because it costs money per call and needs a paid model, so it
    is not wired to a provider here. `judge` is injected: any callable taking
    the payload text and returning a float in [0, 1], where 1.0 means "leaked".
    With no judge configured the rail reports `unjudged`, which is the truth -
    registered below as CLOUD cover, not as protection.
    """

    stage = Stage.STAGE_3
    tenet = TENET
    name = "privacy.pii_leakage_judge"

    def __init__(self, judge: Callable[[str], float] | None = None,
                 threshold: float = 0.5) -> None:
        self.judge = judge
        self.threshold = threshold

    @staticmethod
    def dependency_available() -> bool:
        return importlib.util.find_spec("deepteam") is not None

    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Per-tenant threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self.threshold)
                     if ctx is not None else self.threshold)
        if self.judge is None:
            return RailResult.unjudged(
                "no PII-leakage judge configured; DeepTeam PIIMetric "
                "(metrics/pii/pii.py:27) requires a paid judge model"
                + ("" if self.dependency_available() else " and deepteam is not installed")
            )
        if not text:
            return RailResult.clean()
        try:
            score = float(self.judge(text))
        except Exception as exc:                          # noqa: BLE001
            return RailResult.unjudged(f"PII-leakage judge failed: {exc}")
        if not 0.0 <= score <= 1.0:
            return RailResult.unjudged(
                f"PII-leakage judge returned {score!r}, outside [0, 1]")
        if score < threshold:
            return RailResult.clean()
        return RailResult(findings=[Finding(
            category="privacy.pii",
            severity=Severity.HIGH,
            action=Action.FLAG,
            path=path,
            score=round(score, 4),
            detector=self.name,
        )])


# --------------------------------------------------------------------------- #
# Attribution and registration                                                 #
# --------------------------------------------------------------------------- #
PII_ENTITY_RAIL = PiiEntityRail()
REGION_ID_RAIL = RegionIdRail()
CREDIT_CARD_RAIL = CreditCardRail()
HEALTHCARE_PHI_RAIL = HealthcarePhiRail()
ANONYMISER_RAIL = ReversibleAnonymiserRail()
SYSTEM_PROMPT_RAIL = SystemPromptLeakageRail()
PRESIDIO_RAIL = PresidioPiiRail()
JUDGE_RAIL = PiiLeakageJudgeRail()

CAP_PII = "PII entity detection & redaction"
CAP_REGION = "Region-specific ID recognizers"
CAP_CARD = "Credit card detection (Luhn-checked)"
CAP_PHI = "Healthcare PHI entities"
CAP_JUDGE = "PII leakage detection (LLM judge)"
CAP_SYSPROMPT = "System-prompt leakage detection"
CAP_REDTEAM = "PII leakage red-team probing"
CAP_VAULT = "Reversible anonymisation (vault)"
CAP_MULTIFORMAT = "Multi-format PII scanning"

ATTRIBUTIONS: dict[str, RailAttribution] = {
    PII_ENTITY_RAIL.name: RailAttribution(
        rail=PII_ENTITY_RAIL.name,
        source_repo="hai-guardrails-main + agentic_security-main",
        display_name="AFNI PII entity regex set",
        mechanism="Keyword/Regex",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        capability=CAP_PII,
        evidence="hai-guardrails src/guards/pii.guard.ts:14-47; "
                 "agentic_security refusal_classifier/pii_detector.py:33-67; "
                 "llm-guard anonymize_helpers/regex_patterns.py:54",
    ),
    REGION_ID_RAIL.name: RailAttribution(
        rail=REGION_ID_RAIL.name,
        source_repo="Infosys-Responsible-AI-Toolkit-master + safe-zone-main",
        display_name="AFNI region ID recognizers",
        mechanism="Keyword/Regex + checksum",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        capability=CAP_REGION,
        evidence="Infosys predefined_recognizers/{us_ssn,us_itin,PAN_Number,"
                 "Aadhaar_Number}.py; safe-zone init.sql:29,34,35; "
                 "Verhoeff (Aadhaar) and ISO 13616 mod-97 (IBAN) added here",
    ),
    CREDIT_CARD_RAIL.name: RailAttribution(
        rail=CREDIT_CARD_RAIL.name,
        source_repo="agentic_security-main",
        display_name="AFNI Luhn card check",
        mechanism="Keyword/Regex + checksum",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        capability=CAP_CARD,
        evidence="agentic_security refusal_classifier/pii_detector.py:67 "
                 "CREDIT_CARD_CANDIDATE, :108 _passes_luhn; "
                 "llm-guard anonymize_helpers/regex_patterns.py:37 (IIN gate)",
    ),
    HEALTHCARE_PHI_RAIL.name: RailAttribution(
        rail=HEALTHCARE_PHI_RAIL.name,
        source_repo="hai-guardrails-main",
        display_name="AFNI PHI regex set",
        mechanism="Keyword/Regex + checksum",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        capability=CAP_PHI,
        evidence="hai-guardrails src/guards/pii.guard.ts:48-83 "
                 "(ICD-10, MRN, NPI, DEA); Infosys "
                 "medical_license_recognizer.py:59-70 (DEA check digit); "
                 "NPI 80840-prefixed Luhn added",
    ),
    ANONYMISER_RAIL.name: RailAttribution(
        rail=ANONYMISER_RAIL.name,
        source_repo="llm-guard-main",
        display_name="AFNI reversible anonymiser (Vault)",
        mechanism="Module + Keyword/Regex",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        capability=CAP_VAULT,
        evidence="llm-guard llm_guard/vault.py (whole file); "
                 "input_scanners/anonymize.py:232-233 placeholder format, "
                 ":273-286 placeholder reuse; "
                 "output_scanners/deanonymize.py:29-41 exact-match restore",
    ),
    SYSTEM_PROMPT_RAIL.name: RailAttribution(
        rail=SYSTEM_PROMPT_RAIL.name,
        source_repo="hai-guardrails-main + garak-main",
        display_name="AFNI system-prompt leakage check",
        mechanism="Keyword/Regex + n-gram containment",
        stage=int(Stage.STAGE_1),
        confidence_kind="deterministic",
        capability=CAP_SYSPROMPT,
        evidence="hai-guardrails src/guards/leakage.guard.ts:31-41 "
                 "(pattern mode; the language-model mode is not ported); "
                 "garak resources/matching.py:5-27 and "
                 "detectors/sysprompt_extraction.py:70-104 - the score is a "
                 "character n-gram containment fraction, not a model probability",
    ),
    PRESIDIO_RAIL.name: RailAttribution(
        rail=PRESIDIO_RAIL.name,
        source_repo="llm-guard-main",
        display_name="Presidio analyzer (via LLM Guard)",
        mechanism="Module + Classifier",
        stage=int(Stage.STAGE_2),
        confidence_kind="classifier",
        capability=CAP_PII,
        evidence="llm-guard input_scanners/anonymize.py:27-41 entity list, "
                 ":28-40 presidio-analyzer==2.2.358; NeMo Guardrails "
                 "library/sensitive_data_detection/actions.py:81; "
                 "presidio name mapping from openguardrails "
                 "specification/taxonomy.md:155-163",
    ),
    JUDGE_RAIL.name: RailAttribution(
        rail=JUDGE_RAIL.name,
        source_repo="deepteam-main",
        display_name="DeepTeam PIIMetric (LLM judge)",
        mechanism="LLM-judge",
        stage=int(Stage.STAGE_3),
        confidence_kind="judge",
        capability=CAP_JUDGE,
        evidence="deepteam metrics/pii/pii.py:27 PIIMetric, "
                 "metrics/pii/template.py judge prompt; "
                 "guardrails/guards/privacy_guard/template.py (gpt-4.1)",
    ),
}

# Every rail that may be mounted in the request cascade. Ordered by stage.
# OFFLINE rails are absent by construction - `Cascade.__init__` raises on them,
# and 8 of Privacy's 17 contributing tools are offline-only.
STAGE_1_RAILS = [
    PII_ENTITY_RAIL,
    REGION_ID_RAIL,
    CREDIT_CARD_RAIL,
    HEALTHCARE_PHI_RAIL,
    ANONYMISER_RAIL,
    SYSTEM_PROMPT_RAIL,
]
RAILS = STAGE_1_RAILS + [PRESIDIO_RAIL, JUDGE_RAIL]


def register(registry) -> None:
    """Declare Privacy's coverage. Six of nine run today; three do not, and are
    recorded as what they actually are rather than rounded up."""
    registry.register_rail(PII_ENTITY_RAIL, ATTRIBUTIONS[PII_ENTITY_RAIL.name],
                           available=True,
                           note="stdlib regex set runs on 100% of traffic. The "
                                "stage-2 NER depth layer (privacy.presidio_ner) "
                                "is mounted but reports unjudged until "
                                "presidio-analyzer and en_core_web_lg are "
                                "installed, so PERSON/LOCATION entities are not "
                                "covered today")
    registry.register_rail(REGION_ID_RAIL, ATTRIBUTIONS[REGION_ID_RAIL.name],
                           available=True,
                           note="US SSN/ITIN, India Aadhaar (Verhoeff) and PAN, "
                                "UK NINO, IBAN (mod-97). Other Presidio region "
                                "packs (AU, IT, ES, SG, KR, PL) are not ported")
    registry.register_rail(CREDIT_CARD_RAIL, ATTRIBUTIONS[CREDIT_CARD_RAIL.name],
                           available=True,
                           note="Luhn plus an IIN family gate; both are needed - "
                                "Luhn alone accepts ~1 in 10 random digit runs")
    registry.register_rail(HEALTHCARE_PHI_RAIL, ATTRIBUTIONS[HEALTHCARE_PHI_RAIL.name],
                           available=True,
                           note="ICD-10 (context- or subcode-gated), MRN "
                                "(prefix required), NPI and DEA (checksummed). "
                                "Free-text clinical PHI - conditions, treatment "
                                "narrative - needs the stage-2 NER layer")
    registry.register_rail(ANONYMISER_RAIL, ATTRIBUTIONS[ANONYMISER_RAIL.name],
                           available=True,
                           note="pure-stdlib port of LLM Guard's Vault, the only "
                                "reversible redaction in the 23 reviewed repos. "
                                "Exact-match deanonymise only; upstream's fuzzy "
                                "strategy needs the fuzzysearch package")
    registry.register_rail(SYSTEM_PROMPT_RAIL, ATTRIBUTIONS[SYSTEM_PROMPT_RAIL.name],
                           available=True,
                           note="probe patterns always on; the n-gram containment "
                                "half needs a configured system_prompt and runs "
                                "only on output paths")

    # Stage 3, paid. A rail exists and degrades honestly, but an unconfigured
    # judge is not protection, so this is CLOUD rather than IMPLEMENTED.
    registry.register(
        TENET, CAP_JUDGE, Coverage.CLOUD,
        attribution=ATTRIBUTIONS[JUDGE_RAIL.name],
        note="privacy.pii_leakage_judge is written and mounted but reports "
             "unjudged: DeepTeam's PIIMetric needs a paid judge model "
             "(gpt-4.1 in its PrivacyGuard), and none is configured. Inject a "
             "judge callable to activate. Azure AI Language PII - Conversation "
             "PII mode - is the cloud pick in tenets.md for the same slot",
    )

    # garak's ProPILE probes are an attack generator: they need to drive the
    # model repeatedly with candidate PII and compare replies. That is a CI job,
    # not a request-path check, and `Cascade` refuses to mount an OFFLINE rail.
    registry.register(
        TENET, CAP_REDTEAM, Coverage.OFFLINE,
        note="garak ProPILE twin/triplet/quad probes "
             "(garak/probes/propile.py, data/propile/prompt_templates.tsv) "
             "with detectors/propile.py:17 PIILeak exact + Jaro-Winkler "
             "matching. Belongs in CI against a deployed model; the "
             "nltk jaro_winkler_similarity import also makes it a dependency. "
             "Promptfoo's pii:* plugins and PyRIT's "
             "SystemPromptExtractionScorer sit in the same tier",
    )

    # Honest GAP. Not attempted, and faking it would be worse than the zero.
    registry.register(
        TENET, CAP_MULTIFORMAT, Coverage.GAP,
        note="no rail. Infosys is the only reviewed toolkit with real breadth "
             "here (DicomImageRedactorEngine plus PDF/Office/OCR paths, "
             "responsible-ai-privacy/src/privacy/service/__init__.py:103-132), "
             "and every path needs a third-party parser - pydicom, pymupdf, "
             "python-docx, an OCR engine - none of which is installed. It is "
             "also not text-payload work: it needs a file-extraction stage "
             "ahead of the cascade, which this gateway does not have yet",
    )
