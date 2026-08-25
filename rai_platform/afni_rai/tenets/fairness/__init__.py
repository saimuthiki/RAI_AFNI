# -*- coding: utf-8 -*-
"""
Fairness & Bias - the tenet that is structurally almost entirely offline.

Read this before looking for a per-request fairness check, because there isn't
one and there should not be one.

The methodology analysis counted 13 tools contributing to this tenet and put
**11 of them Offline** (`knowledge/methodology.md`, "Fairness & Bias": Stage 2 1
- Stage 3 1 - Offline 11). That is not a shortfall in the tooling; it is what
fairness *is*. Every group-fairness metric in the reviewed corpus needs two
things that do not exist at request time:

  a labelled ground truth      Fairlearn's `demographic_parity_difference` takes
                               `y_true` alongside `y_pred`
                               (references/fairlearn-main/fairlearn/metrics/_fairness_metrics.py:12)
  a declared protected group    `sensitive_features=` is a required keyword-only
                               argument of the same function, and AIF360 makes it
                               a constructor argument of the dataset itself
                               (`protected_attribute_names=['race', 'sex']`,
                               references/AIF360-main/aif360/datasets/adult_dataset.py:22)

Bias is a property of a *population* of decisions, not an event in one request.
A single request carries one outcome and no counterfactual, so there is nothing
to disaggregate. `knowledge/tenets.md` states the consequence directly: this
tenet "runs as: scheduled batch job. **Never** a live per-response check".

So this package deliberately does three things and refuses a fourth:

  1. Two runtime rails that are honestly *not* fairness measurements:
     - `ProtectedAttributeReferenceRail` (Stage 1, stdlib) flags that a decision
       may be conditioning on a protected class. It does not measure bias.
     - `LocalBiasClassifierRail` (Stage 2) adapts LLM Guard's bias scanner, and
       reports `unjudged` until transformers and the weights are present.
  2. A batch-job scaffold (`BatchDataset`, `BatchReport`, `FairnessBatchJob`,
     `BatchJobSpec`) plus `OFFLINE_JOB_SPECS` - a registry so the seven OFFLINE-
     registered capabilities point at a named entry point in a named library
     with a preflight check, rather than at a comment. `GroupFairnessMetricsJob`
     is a working stdlib port of Fairlearn's two headline disparity differences,
     so the scaffold is verifiable in CI with nothing installed.
  3. Registers all nine matrix capabilities at their true status - seven OFFLINE,
     one CLOUD, one DEPENDENCY-or-IMPLEMENTED, and nothing claimed that is not
     there.

  4. It does NOT invent a per-request fairness metric. There is no rail here
     called `FairnessRail` that returns a number, because any such number would
     be fabricated. An honest gap beats a manufactured capability.

One consequence worth stating out loud: after `register()` runs, Fairness has
**zero IMPLEMENTED capabilities** on a stock box. That is the correct reading of
the coverage report, not a bug in it. The one rail that genuinely runs today -
the protected-attribute detector - maps to no row in
`analysis/data/capability_matrix_data.json`, so it is deliberately registered
against nothing (`capability=None`); attributing it to "Bias detection
(generative)" would inflate the coverage number with a check that does something
else entirely.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from ...cascade.rail import RailResult, Stage
from ...contract.explanation import RailAttribution
from ...contract.models import Action, Finding, Severity, Tenet
from ...registry.capabilities import Coverage

# --------------------------------------------------------------------- shared --

TENET = Tenet.FAIRNESS


def _fp(subject: str) -> str:
    """Whitelist fingerprint for a finding's subject.

    A truncated sha256 of the subject, never the subject itself - this is what an
    operator's false-positive exception keys on, and it is the only reason
    `subject` may be carried at all (upstream forbids per-span echoes of matched
    text anywhere else on a finding).
    """
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]


def _installed(root_package: str) -> bool:
    """Is a top-level package importable, without importing it?

    Deliberately `find_spec` on the ROOT package only. Probing
    `fairlearn.postprocessing` would execute `fairlearn/__init__.py`, and a
    readiness check must not have side effects - see the no-network-at-import
    rule this whole platform is built on.
    """
    try:
        return importlib.util.find_spec(root_package) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


# ============================================================================
# Stage 1 - protected-attribute reference detector
# ============================================================================
#
# WHAT THIS IS NOT
# ----------------
# This is not a fairness metric, a bias score, or a disparity measurement. It
# cannot be: see the module docstring. It is a deterministic *governance signal*
# with one job - surface that a piece of traffic appears to condition an outcome
# on a protected class, so a human or a scheduled Fairlearn job can go and look.
#
# It has no ground truth, no comparison group, and no notion of whether the
# conditioning is lawful (a senior discount and a denied mortgage look identical
# to it). Therefore its action is ALWAYS `flag` and NEVER `block`, and it emits
# no `score` - there is nothing to be confident about, only a pattern that
# matched.
#
# WHERE THE VOCABULARY COMES FROM
# -------------------------------
# The axes are not invented. They are the union of the protected-attribute axes
# the vendored corpus actually enumerates:
#
#   references/deepeval-main/deepeval/benchmarks/bbq/task.py:5-15
#       BBQTask - Age, Disability_status, Gender_identity, Nationality,
#       Physical_appearance, Race_ethnicity, Race_x_SES, Race_x_gender,
#       Religion, SES, Sexual_orientation.  Eleven axes, the widest enumeration
#       in the corpus, and the reason this rail has eleven axes.
#   references/promptfoo-main/src/redteam/constants/plugins.ts:233
#       BIAS_PLUGINS = ['bias:age', 'bias:disability', 'bias:gender', 'bias:race']
#   references/Infosys-Responsible-AI-Toolkit-master/.../fairness/service/service_monitoring.py:57-62
#       bias_types - race/gender/age/disability with concrete group terms
#       ("white, black, asian, hispanic, other"; "male, female, other";
#       "infants ... seniors"; "physical/sensory/intellectual/psychiatric/
#       learning disabilities, chronic health conditions").
#   references/AIF360-main/aif360/datasets/adult_dataset.py:22, bank_dataset.py:15,
#   compas_dataset.py:31, german_dataset.py:30, law_school_gpa_dataset.py:10
#       protected_attribute_names = race, sex, age, gender.
#
# Two axes - `pregnancy` and `veteran_status` - have NO source in the vendored
# corpus. They are here on statutory grounds (US Pregnancy Discrimination Act;
# USERRA) because a BPO gateway will see both, and they are marked as such in
# `_Axis.evidence` so nobody later mistakes them for a ported finding.
#
# The "is a decision being made" half comes from promptfoo's BiasGrader rubric,
# which is explicit that the failure mode is differential *treatment*:
# "Providing different advice or recommendations based on demographic factors",
# "Making assumptions about suitability for roles based on protected
# characteristics", "Unnecessarily emphasizing protected characteristics when
# they're not relevant"
# (references/promptfoo-main/src/redteam/plugins/bias.ts:31-45).
#
# The decision *domains* are the domains the corpus's own fairness benchmarks
# are drawn from, which is why lending, employment, admissions, healthcare,
# housing and criminal-risk vocabulary is present and nothing else is:
# AIF360 adult (income/employment), german + bank (credit), compas
# (criminal risk), law_school_gpa (admissions), meps (healthcare); Fairlearn
# _fetch_adult, _fetch_bank_marketing, _fetch_credit_card,
# _fetch_diabetes_hospital, _fetch_acs_income.
#
# FALSE-POSITIVE DISCIPLINE
# -------------------------
# A protected-attribute term alone fires nothing. Three guards, all cheap:
#
#   (1) co-occurrence - an attribute term AND a decision term must appear in the
#       SAME sentence. "Our D&I training covers race and gender" has no decision
#       term and is silent, which is promptfoo's own instruction: "Discussing
#       diversity and inclusion initiatives is typically appropriate"
#       (bias.ts:66-69).
#   (2) person-anchoring - terms that are only demographic in context ("black",
#       "white", "old", "foreign", "fat") must appear within four words of a
#       person noun. "Approve the white paper" is silent; "approve the white
#       applicant" is not.
#   (3) severity tiering - MEDIUM only when an explicit conditioning connective
#       ("because", "based on", "on the grounds of") joins them; otherwise LOW.
#       Mere adjacency is weaker evidence than stated causation, and the finding
#       says so.

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
# Sentence-ish chunks. Cheap on purpose: this rail runs on 100% of traffic.
_CHUNK_RE = re.compile(r"[^.!?;:\n\r]+")
# How many words may sit between an ambiguous term and its person anchor.
_ANCHOR_WINDOW = 4
# Cap per payload path. A 200-word paragraph about hiring demographics should
# produce a handful of findings, not two hundred.
_MAX_FINDINGS = 8


def _phrase_alternation(phrases: Sequence[str]) -> "re.Pattern[str]":
    """Word-boundaried alternation over literal phrases, whitespace-tolerant.

    Longest-first so "african american" wins over a bare "african", and internal
    spaces/hyphens both match either, so "non-white" and "non white" behave the
    same.
    """
    parts = []
    for phrase in sorted(set(phrases), key=len, reverse=True):
        escaped = re.escape(phrase)
        # Both separators become the same flexible class, via a sentinel. Doing
        # it as two chained str.replace calls does NOT work: the replacement
        # text itself contains an escaped hyphen, so the second pass rewrites
        # the first pass's output and silently produces `zip[\s[\s\-]+]+code`,
        # which matches nothing. That bug made every multi-word phrase in every
        # axis dead - including the whole connective list.
        escaped = (escaped.replace("\\-", "\x00")
                          .replace("\\ ", "\x00")
                          .replace("\x00", r"[\s\-]+"))
        parts.append(escaped)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


@dataclass(frozen=True)
class _Axis:
    """One protected-attribute axis and the provenance of its term list."""

    name: str
    evidence: str
    # Terms that are demographic on their own.
    unambiguous: tuple[str, ...]
    # Single tokens that are demographic ONLY next to a person noun.
    qualified: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "_unambiguous_re",
                           _phrase_alternation(self.unambiguous) if self.unambiguous else None)
        object.__setattr__(self, "_qualified", frozenset(t.lower() for t in self.qualified))


_BBQ = ("references/deepeval-main/deepeval/benchmarks/bbq/task.py:5-15 (BBQTask)")
_INFOSYS = ("references/Infosys-Responsible-AI-Toolkit-master/responsible-ai-fairness/"
            "responsible-ai-fairness/src/fairness/service/service_monitoring.py:57-62")
_PROMPTFOO = "references/promptfoo-main/src/redteam/constants/plugins.ts:233"
_AIF360_ADULT = "references/AIF360-main/aif360/datasets/adult_dataset.py:22"

AXES: tuple[_Axis, ...] = (
    _Axis(
        name="race_ethnicity",
        evidence=f"BBQ Race_ethnicity/Race_x_SES/Race_x_gender - {_BBQ}; "
                 f"Infosys bias_types race groups - {_INFOSYS}; "
                 f"promptfoo bias:race - {_PROMPTFOO}; "
                 f"AIF360 protected_attribute_names=['race','sex'] - {_AIF360_ADULT}",
        unambiguous=(
            "race", "races", "racial", "racially", "ethnicity", "ethnicities",
            "ethnic", "caucasian", "hispanic", "latino", "latina", "latinx",
            "indigenous", "aboriginal", "african american", "native american",
            "asian american", "people of color", "person of color",
            "persons of color", "nonwhite", "non-white", "racial minority",
            "racial minorities",
        ),
        qualified=("black", "white", "asian", "arab", "african"),
    ),
    _Axis(
        name="gender",
        evidence=f"BBQ Gender_identity/Race_x_gender - {_BBQ}; "
                 f"Infosys bias_types gender groups - {_INFOSYS}; "
                 f"promptfoo bias:gender - {_PROMPTFOO}; "
                 f"AIF360 protected_attribute_names 'sex' - {_AIF360_ADULT}; "
                 "PyRIT gendered_professions.yaml - references/PyRIT-main/pyrit/"
                 "datasets/lexicons/fairness/gendered_professions.yaml",
        unambiguous=(
            "gender", "genders", "gendered", "sex", "male", "males", "female",
            "females", "man", "men", "woman", "women", "transgender",
            "trans woman", "trans man", "nonbinary", "non-binary", "cisgender",
            "mother", "mothers", "father", "fathers", "maternity", "paternity",
            "husband", "wife", "housewife",
        ),
    ),
    _Axis(
        name="age",
        evidence=f"BBQ Age - {_BBQ}; Infosys bias_types age groups "
                 f"(infants..seniors) - {_INFOSYS}; promptfoo bias:age - {_PROMPTFOO}; "
                 "AIF360 BankDataset protected_attribute_names=['age'] - "
                 "references/AIF360-main/aif360/datasets/bank_dataset.py:15",
        unambiguous=(
            "age", "ages", "aged", "age group", "age bracket", "elderly",
            "senior", "seniors", "senior citizen", "senior citizens",
            "geriatric", "retiree", "retirees", "teenager", "teenagers",
            "teen", "teens", "juvenile", "adolescent", "adolescents",
            "toddler", "toddlers", "infant", "infants", "preschooler",
            "preschoolers", "child", "children", "millennial", "millennials",
            "baby boomer", "boomer", "boomers", "gen z", "middle aged",
            "middle-aged", "date of birth", "year of birth",
        ),
        qualified=("old", "older", "young", "younger", "aging", "ageing"),
    ),
    _Axis(
        name="disability",
        evidence=f"BBQ Disability_status - {_BBQ}; Infosys bias_types disability "
                 f"groups (physical/sensory/intellectual/psychiatric/learning "
                 f"disabilities, chronic health conditions) - {_INFOSYS}; "
                 f"promptfoo bias:disability - {_PROMPTFOO}",
        unambiguous=(
            "disability", "disabilities", "disabled", "handicap", "handicapped",
            "impairment", "impairments", "hearing impaired",
            "visually impaired", "deaf", "wheelchair", "paraplegic",
            "quadriplegic", "amputee", "autism", "autistic",
            "learning disability", "dyslexia", "dyslexic", "chronic illness",
            "chronic condition", "mental illness", "psychiatric",
            "reasonable accommodation", "assistive technology",
        ),
        qualified=("blind",),
    ),
    _Axis(
        name="religion",
        evidence=f"BBQ Religion - {_BBQ}",
        unambiguous=(
            "religion", "religions", "religious", "muslim", "muslims", "islam",
            "islamic", "christian", "christians", "christianity", "catholic",
            "protestant", "jewish", "judaism", "hindu", "hindus", "buddhist",
            "buddhists", "sikh", "sikhs", "atheist", "atheists", "mormon",
            "hijab", "yarmulke", "turban", "religious observance", "sabbath",
            "ramadan", "kosher", "halal",
        ),
    ),
    _Axis(
        name="national_origin",
        evidence=f"BBQ Nationality - {_BBQ}",
        unambiguous=(
            "nationality", "national origin", "citizenship",
            "citizenship status", "noncitizen", "non-citizen", "immigrant",
            "immigrants", "immigration", "undocumented", "green card",
            "visa status", "work permit", "foreign national", "foreign-born",
            "country of origin", "expatriate", "refugee", "refugees", "asylum",
            "non-native speaker", "english as a second language",
        ),
        qualified=("accent", "foreign"),
    ),
    _Axis(
        name="sexual_orientation",
        evidence=f"BBQ Sexual_orientation - {_BBQ}",
        unambiguous=(
            "sexual orientation", "gay", "lesbian", "bisexual", "homosexual",
            "heterosexual", "queer", "lgbt", "lgbtq", "same-sex",
            "civil partnership",
        ),
    ),
    _Axis(
        name="socioeconomic",
        evidence=f"BBQ SES/Race_x_SES - {_BBQ}",
        unambiguous=(
            "socioeconomic", "socio-economic", "social class", "working class",
            "lower class", "upper class", "low-income", "low income",
            "welfare recipient", "food stamps", "medicaid",
            "public assistance", "housing project", "zip code", "postcode",
            "postal code", "indigent", "impoverished", "poverty",
        ),
        qualified=("poor", "wealthy", "affluent"),
    ),
    _Axis(
        name="physical_appearance",
        evidence=f"BBQ Physical_appearance - {_BBQ}",
        unambiguous=(
            "physical appearance", "obese", "obesity", "overweight",
            "underweight", "body mass index", "bmi", "tattoo", "tattoos",
            "piercing", "piercings", "facial hair", "dreadlocks",
            "natural hair", "hair texture",
        ),
        qualified=("fat", "ugly", "unattractive"),
    ),
    _Axis(
        name="pregnancy",
        evidence="NO source in the vendored corpus. Statutory: US Pregnancy "
                 "Discrimination Act 1978 / FMLA. Included because a BPO "
                 "contact-centre gateway will see it; flagged here so it is "
                 "never mistaken for a ported finding.",
        unambiguous=(
            "pregnant", "pregnancy", "maternity leave", "parental leave",
            "postpartum", "breastfeeding", "fertility treatment", "ivf",
        ),
    ),
    _Axis(
        name="veteran_status",
        evidence="NO source in the vendored corpus. Statutory: USERRA / VEVRAA. "
                 "Included on the same grounds as `pregnancy` and flagged the "
                 "same way.",
        unambiguous=(
            "veteran", "veterans", "military service", "service member",
            "servicemember", "active duty", "national guard",
            "honorably discharged", "dishonorably discharged", "gi bill",
            "va benefits",
        ),
    ),
)

# A decision, recommendation or eligibility determination is being made. Domains
# are those of the corpus's own fairness benchmarks - see the header comment.
_DECISION_TERMS = (
    # generic determination
    "approve", "approved", "approves", "approval", "approvals", "approving",
    "deny", "denied", "denies", "denial", "denials", "decline", "declined",
    "reject", "rejected", "rejects", "rejection", "eligible", "ineligible",
    "eligibility", "qualify", "qualifies", "qualified", "disqualify",
    "disqualified", "grant", "granted", "select", "selected", "selection",
    "recommend", "recommends", "recommended", "recommendation",
    "recommendations",
    # employment (AIF360 adult, Fairlearn _fetch_adult/_fetch_acs_income)
    "hire", "hired", "hires", "hiring", "shortlist", "shortlisted", "promote",
    "promoted", "promotion", "terminate", "terminated", "termination",
    "dismiss", "dismissed", "dismissal", "lay off", "laid off", "layoff",
    "layoffs", "interview", "interviews", "job offer", "offer letter",
    "salary", "salaries", "compensation", "pay raise", "bonus", "wage",
    "wages", "background check",
    # credit and lending (AIF360 german + bank, Fairlearn _fetch_credit_card)
    "loan", "loans", "mortgage", "mortgages", "credit", "credit limit",
    "credit score", "creditworthy", "creditworthiness", "underwrite",
    "underwriting", "underwritten", "interest rate", "line of credit",
    "collateral", "foreclose", "foreclosure", "credit check",
    # insurance and healthcare (AIF360 meps, Fairlearn _fetch_diabetes_hospital)
    "premium", "premiums", "deductible", "copay", "risk class", "risk tier",
    "risk score", "risk rating", "actuarial", "prior authorization",
    "coverage decision", "claim denial",
    # admissions (AIF360 law_school_gpa)
    "admission", "admissions", "admit", "admitted", "enroll", "enrolled",
    "enrollment", "scholarship", "financial aid", "waitlist", "waitlisted",
    # housing
    "lease", "leased", "tenancy", "evict", "evicted", "eviction",
    "rental application", "security deposit",
    # criminal risk (AIF360 compas)
    "sentencing", "parole", "bail", "recidivism", "pretrial release",
    # routing / triage
    "triage", "prioritize", "prioritise", "prioritized", "priority", "rank",
    "ranked", "ranking", "screen out", "screened out", "filter out", "tier",
    "tiered",
)
_DECISION_RE = _phrase_alternation(_DECISION_TERMS)

# Explicit causation. Its presence is the difference between LOW and MEDIUM:
# "denied the loan because she is pregnant" states the conditioning; "pregnancy"
# and "loan" merely co-occurring does not.
_CONNECTIVE_TERMS = (
    "because", "because of", "due to", "based on", "on the basis of",
    "on account of", "on grounds of", "on the grounds of", "owing to",
    "as a result of", "given that", "in light of", "solely because",
    "purely because", "on the strength of",
)
_CONNECTIVE_RE = _phrase_alternation(_CONNECTIVE_TERMS)

# Anchors that turn an ambiguous token into a demographic reference.
_PERSON_NOUNS = frozenset("""
applicant applicants candidate candidates customer customers client clients
consumer consumers employee employees employer employers worker workers staff
personnel hire hires recruit recruits borrower borrowers tenant tenants renter
renters landlord patient patients student students pupil pupils person persons
people individual individuals man men woman women guy guys folks family
families household households community communities resident residents driver
drivers caller callers user users member members claimant claimants defendant
defendants inmate inmates neighborhood neighborhoods neighbourhood group groups
population populations demographic demographics cohort cohorts
""".split())


@dataclass(frozen=True)
class _Hit:
    axis: str
    term: str
    start: int
    end: int
    anchored: bool


class ProtectedAttributeReferenceRail:
    """Stage 1: flag traffic that appears to condition an outcome on a protected
    class. **This is not a fairness metric.**

    It reports one thing and nothing more: a protected-attribute term and a
    decision term occur in the same sentence. It does not know whether the
    decision was unfair, whether the conditioning is lawful, or whether any
    disparity exists - all three of those need a labelled population and a
    comparison group, which a single request does not have (module docstring).
    A scheduled Fairlearn/AIF360 job answers those; this answers "somebody
    should look here".

    Because of that, two properties are structural rather than configurable:

      * every finding is `Action.FLAG`. It never blocks, and `RailResult.block`
        is never set. Blocking a request for mentioning a protected class would
        be both a fabricated fairness claim and a discrimination hazard of its
        own.
      * no `score` is emitted. There is no probability here, only a pattern
        that matched, and `confidence_kind="deterministic"` says exactly that.

    `escalate_on_hit` defaults to **False**, which is the load-bearing default.
    Escalating every protected-attribute mention to the Stage 2 classifier would
    (a) spend a local model on traffic that is usually benign and (b) on any box
    without transformers installed turn this rail's `flag` into a hard BLOCK via
    the engine's fail-closed rule - converting a governance signal into an
    outage, and over-claiming in exactly the way this tenet must not. An
    operator who has the weights installed and wants the second opinion can turn
    it on deliberately.
    """

    name = "afni.fairness.protected_attribute"
    tenet = TENET
    stage = Stage.STAGE_1
    CATEGORY = "x.afni.fairness.protected_attribute_reference"

    def __init__(self, escalate_on_hit: bool = False,
                 max_findings: int = _MAX_FINDINGS) -> None:
        self._escalate = escalate_on_hit
        self._max = max_findings

    # -- matching ----------------------------------------------------------
    @staticmethod
    def _anchored_hits(axis: _Axis, chunk: str) -> list[tuple[str, int, int]]:
        """Ambiguous single tokens, kept only within `_ANCHOR_WINDOW` words of a
        person noun. This is guard (2): "approve the white paper" stays silent."""
        qualified: frozenset[str] = getattr(axis, "_qualified")
        if not qualified:
            return []
        tokens = [(m.group(0).lower(), m.start(), m.end())
                  for m in _WORD_RE.finditer(chunk)]
        anchors = [i for i, (tok, _, _) in enumerate(tokens) if tok in _PERSON_NOUNS]
        if not anchors:
            return []
        out: list[tuple[str, int, int]] = []
        for i, (tok, start, end) in enumerate(tokens):
            if tok in qualified and any(abs(i - a) <= _ANCHOR_WINDOW for a in anchors):
                out.append((tok, start, end))
        return out

    def _scan_chunk(self, chunk: str, offset: int) -> list[_Hit]:
        hits: list[_Hit] = []
        anchored: list[_Hit] = []
        for axis in AXES:
            pattern = getattr(axis, "_unambiguous_re")
            if pattern is not None:
                for m in pattern.finditer(chunk):
                    hits.append(_Hit(axis.name, m.group(0), offset + m.start(),
                                     offset + m.end(), anchored=False))
            for tok, start, end in self._anchored_hits(axis, chunk):
                anchored.append(_Hit(axis.name, tok, offset + start,
                                     offset + end, anchored=True))
        # An ambiguous token sitting inside a phrase already matched outright is
        # the same reference, not a second one: "African American" must not also
        # report a bare "african". Reporting both would double-count one mention
        # against the per-path cap and read as two problems in the explanation.
        spans = [(h.start, h.end) for h in hits]
        hits.extend(h for h in anchored
                    if not any(h.start < e and s < h.end for s, e in spans))
        return hits

    # -- Rail protocol -----------------------------------------------------
    def check(self, path: str, text: str) -> RailResult:
        if not text or not text.strip():
            return RailResult.clean()

        findings: list[Finding] = []
        seen: set[tuple[str, str]] = set()

        for chunk_match in _CHUNK_RE.finditer(text):
            chunk = chunk_match.group(0)
            # Guard (1): no decision term in this sentence, no finding. A
            # sentence that merely mentions a protected class is not a signal.
            if not _DECISION_RE.search(chunk):
                continue
            hits = self._scan_chunk(chunk, chunk_match.start())
            if not hits:
                continue
            # Guard (3): stated causation is stronger evidence than adjacency.
            conditioned = _CONNECTIVE_RE.search(chunk) is not None
            for hit in hits:
                key = (hit.axis, hit.term.lower())
                if key in seen:
                    continue
                seen.add(key)
                subject = hit.term
                findings.append(Finding(
                    category=self.CATEGORY,
                    severity=Severity.MEDIUM if conditioned else Severity.LOW,
                    # Structural. Never BLOCK, never REDACT - redacting the word
                    # "pregnancy" out of a customer's own sentence would be a
                    # different kind of harm.
                    action=Action.FLAG,
                    path=path,
                    start=hit.start,
                    end=hit.end,
                    detector=self.name,
                    subject=subject,
                    fp=_fp(subject),
                ))
                if len(findings) >= self._max:
                    break
            if len(findings) >= self._max:
                break

        if not findings:
            return RailResult.clean()
        return RailResult(judged=True, findings=findings,
                          block=False, escalate=self._escalate)

    def axes_for(self, text: str) -> list[str]:
        """Which axes this rail would report on `text`. A helper for tuning and
        for the batch side, not part of the Rail protocol."""
        out: list[str] = []
        result = self.check("payload", text)
        for f in result.findings:
            for axis in AXES:
                pattern = getattr(axis, "_unambiguous_re")
                qualified: frozenset[str] = getattr(axis, "_qualified")
                term = (f.subject or "").lower()
                if (pattern is not None and pattern.fullmatch(f.subject or "")) \
                        or term in qualified:
                    if axis.name not in out:
                        out.append(axis.name)
                    break
        return out


# ============================================================================
# Stage 2 - LLM Guard's local bias classifier
# ============================================================================

class LocalBiasClassifierRail:
    THRESHOLD_KEY = "x.afni.bias.classifier"
    """Stage 2: the one local model in this tenet.

    A faithful adapter of LLM Guard's `Bias` output scanner
    (references/llm-guard-main/llm-guard-main/llm_guard/output_scanners/bias.py),
    which is a text-classification pipeline over `valurank/distilroberta-bias`
    pinned at revision `c1e4a27...` (bias.py:13-23) with a default threshold of
    0.7 (bias.py:46). The label-inversion arithmetic is ported exactly:

        score = round(result["score"] if result["label"] == "BIASED"
                      else 1 - result["score"], 2)          # bias.py:87-90

    Two deliberate divergences from upstream, both documented rather than silent:

      * upstream returns `is_valid=False` on a hit, i.e. it invalidates the
        model output. Here the finding is `Action.FLAG`. One classifier score on
        one response is not a fairness measurement, and blocking on it would be
        the over-claim this tenet exists to avoid. Enforcement is a policy
        decision made above the rail, on aggregate.
      * `Finding.score` carries the raw model probability, not upstream's
        `calculate_risk_score` (util.py:134-144), which returns -1..1 and would
        violate the contract's `0.0 <= score <= 1.0`.

    Degradation is honest and total: with transformers/torch absent, or the
    weights unavailable, `check()` returns `unjudged` with the real reason. It
    never guesses, and the engine's fail-closed rule then blocks client-facing
    traffic - which is correct behaviour, not a bug.

    Nothing is loaded at import time and no network call happens until the first
    `check()` on a box where the library exists.
    """

    name = "llm_guard.bias"
    tenet = TENET
    stage = Stage.STAGE_2
    CATEGORY = "x.afni.fairness.biased_language"
    MODEL_PATH = "valurank/distilroberta-bias"
    MODEL_REVISION = "c1e4a2773522c3acc929a7b2c9af2b7e4137b96d"
    BIASED_LABEL = "BIASED"
    source: str | None = None

    def __init__(self, threshold: float = 0.7,
                 pipeline_factory: Callable[[], Any] | None = None) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError(f"threshold must be in (0, 1), got {threshold}")
        self._threshold = threshold
        self._factory = pipeline_factory
        self._pipeline: Any = None
        self._load_error: str | None = None
        self._tried = False

    # -- lazy, guarded dependency -----------------------------------------
    @staticmethod
    def dependency_available() -> bool:
        """Cheap, side-effect-free readiness probe used by `register()`."""
        return _installed("transformers") and _installed("torch")

    def _default_factory(self) -> Any:
        # Imported INSIDE the function on purpose. Importing transformers at
        # module scope would make this whole tenet unimportable on a stock box,
        # and would pull a multi-hundred-megabyte dependency into the Stage 1
        # path that must stay stdlib-only.
        from transformers import pipeline  # noqa: PLC0415

        from ...models import resolve  # noqa: PLC0415

        resolved = resolve(self.MODEL_PATH, self.MODEL_REVISION)
        self.source = resolved.note
        return pipeline(
            task="text-classification",
            model=resolved.target,
            truncation=True,
            max_length=512,
            **resolved.kwargs,
        )

    def _ensure_pipeline(self) -> Any:
        if self._pipeline is not None or self._tried:
            return self._pipeline
        self._tried = True
        factory = self._factory or self._default_factory
        try:
            self._pipeline = factory()
        except Exception as exc:  # noqa: BLE001 - any load failure is unjudged
            self._load_error = f"{type(exc).__name__}: {exc}"
            self._pipeline = None
        return self._pipeline

    # -- Rail protocol -----------------------------------------------------
    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Per-tenant threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self._threshold)
                     if ctx is not None else self._threshold)
        # Mirrors bias.py:81-82 - an empty payload is judged, and clean.
        if not text or not text.strip():
            return RailResult.clean()

        pipe = self._ensure_pipeline()
        if pipe is None:
            detail = self._load_error or (
                f"transformers/torch not installed; {self.MODEL_PATH} unavailable")
            return RailResult.unjudged(
                f"{self.name}: {detail} - could not look, which is not 'found nothing'")

        try:
            raw = pipe(text)
        except Exception as exc:  # noqa: BLE001
            return RailResult.unjudged(
                f"{self.name}: inference failed - {type(exc).__name__}: {exc}")

        results = raw if isinstance(raw, list) else [raw]
        highest = 0.0
        for result in results:
            try:
                label = str(result["label"])
                prob = float(result["score"])
            except (KeyError, TypeError, ValueError) as exc:
                return RailResult.unjudged(
                    f"{self.name}: unusable classifier output - {type(exc).__name__}: {exc}")
            # Ported verbatim from bias.py:87-90.
            score = round(prob if label == self.BIASED_LABEL else 1 - prob, 2)
            highest = max(highest, score)

        if highest <= threshold:
            return RailResult.clean()

        return RailResult(judged=True, findings=[Finding(
            category=self.CATEGORY,
            severity=Severity.MEDIUM,
            action=Action.FLAG,
            path=path,
            score=min(max(highest, 0.0), 1.0),
            detector=self.name,
        )])


# ============================================================================
# Stage 3 - hai-guardrails' generative bias judge
# ============================================================================

class GenerativeBiasJudgeRail:
    THRESHOLD_KEY = "x.afni.bias.judge"
    """Stage 3: an adapter for hai-guardrails' `biasDetectionGuard`.

    Upstream is a paid-API LLM judge - `llmGuard` with
    `validationType: ValidationType.Score`, a default threshold of 0.7 and a zod
    schema of `{score, reason, categories, affectedGroups, impact}`
    (references/hai-guardrails-main/hai-guardrails-main/src/guards/
    bias-detection.guard.ts:74-103). Its role definition is the rubric this rail
    is faithful to: "Identify any statements that contain stereotypes,
    prejudices, or unfair generalizations about people based on their group
    membership" (bias-detection.guard.ts:83-86).

    This class takes the judge as a **callable**, so the paid dependency lives
    outside the platform and one adapter serves any provider. With no judge
    configured it returns `unjudged` - it does not guess, and it does not fake a
    score.

    It is deliberately NOT in `RAILS`. Mounting a rail that is unjudged by
    default would, via fail-closed, block every escalated client-facing request
    on a box with no judge wired up. It lives in `CLOUD_RAILS` and the
    capability is registered `Coverage.CLOUD`, which is the honest status.
    """

    name = "hai_guardrails.bias_detection"
    tenet = TENET
    stage = Stage.STAGE_3
    CATEGORY = "x.afni.fairness.stereotype"
    _IMPACT_SEVERITY = {"low": Severity.LOW, "medium": Severity.MEDIUM,
                        "high": Severity.HIGH}

    def __init__(self, judge: Callable[[str], dict[str, Any]] | None = None,
                 threshold: float = 0.7) -> None:
        # Default 0.7 is upstream's: bias-detection.guard.ts:75.
        if not 0.0 < threshold < 1.0:
            raise ValueError(f"threshold must be in (0, 1), got {threshold}")
        self._judge = judge
        self._threshold = threshold

    def check(self, path: str, text: str,
              ctx: CheckContext | None = None) -> RailResult:
        # Per-tenant threshold, falling back to the ported default when no
        # store is wired. THRESHOLD_KEY is resolved once per call, not per
        # finding, so the read log carries one entry per check.
        threshold = (ctx.threshold(self.THRESHOLD_KEY, self._threshold)
                     if ctx is not None else self._threshold)
        if self._judge is None:
            return RailResult.unjudged(
                f"{self.name}: no LLM judge configured (hai-guardrails "
                "biasDetectionGuard requires a paid API) - could not look")
        if not text or not text.strip():
            return RailResult.clean()

        try:
            verdict = self._judge(text)
        except Exception as exc:  # noqa: BLE001
            return RailResult.unjudged(
                f"{self.name}: judge call failed - {type(exc).__name__}: {exc}")

        try:
            score = float(verdict["score"])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            # A judge that answers off-schema has not judged. Coercing a
            # malformed reply into a pass is the failure mode this platform
            # refuses.
            return RailResult.unjudged(
                f"{self.name}: judge reply off-schema - {type(exc).__name__}: {exc}")
        if not 0.0 <= score <= 1.0:
            return RailResult.unjudged(
                f"{self.name}: judge score {score} outside [0, 1]")

        if score < threshold:
            return RailResult.clean()

        impact = str(verdict.get("impact") or "").lower()
        severity = self._IMPACT_SEVERITY.get(impact, Severity.MEDIUM)
        return RailResult(judged=True, findings=[Finding(
            category=self.CATEGORY,
            severity=severity,
            action=Action.FLAG,
            path=path,
            score=score,
            detector=self.name,
        )])


# ============================================================================
# The offline half: batch-job scaffold and runner registry
# ============================================================================

@dataclass(frozen=True)
class PreflightResult:
    """Whether a declared batch job could run on this box, and why not."""

    available: bool
    detail: str


@dataclass(frozen=True)
class BatchJobSpec:
    """A scheduled fairness job, declared rather than described.

    This is what turns `Coverage.OFFLINE` from an assertion into something
    checkable. Each spec names the capability it serves, the library and the
    exact entry point inside it, the inputs the job cannot run without, and the
    `file:line` in the vendored source the claim came from. `preflight()` then
    answers "could this run today" without importing anything heavier than a
    module spec.
    """

    capability: str
    tool: str
    entry_point: str
    requires: tuple[str, ...]
    cadence: str
    evidence: str
    note: str = ""

    @property
    def root_package(self) -> str:
        return self.entry_point.split(".", 1)[0]

    def preflight(self) -> PreflightResult:
        if _installed(self.root_package):
            return PreflightResult(
                True,
                f"{self.root_package} is importable; entry point "
                f"{self.entry_point} not resolved (would require importing the "
                "package, which a readiness check must not do)")
        return PreflightResult(
            False, f"{self.root_package} is not installed - {self.entry_point} "
                   f"cannot run; install {self.tool} in the batch environment")


@dataclass
class BatchDataset:
    """The inputs every fairness metric in the corpus requires, and a single
    place that refuses to proceed without them.

    The field names are Fairlearn's on purpose - `y_true`, `y_pred`,
    `sensitive_features` (references/fairlearn-main/fairlearn/metrics/
    _fairness_metrics.py:13-18) - so a scheduled job hands the same object to
    this scaffold or to MetricFrame with no translation. `sensitive_features`
    maps a protected-attribute name to that column's per-row group label, which
    is AIF360's `protected_attribute_names` shape flattened
    (references/AIF360-main/aif360/datasets/adult_dataset.py:22).

    Plain tuples, no numpy: the point of the scaffold is that CI can exercise it
    with nothing installed.
    """

    y_true: tuple[Any, ...]
    y_pred: tuple[Any, ...]
    sensitive_features: dict[str, tuple[Any, ...]]
    positive_label: Any = 1

    def __post_init__(self) -> None:
        self.y_true = tuple(self.y_true)
        self.y_pred = tuple(self.y_pred)
        self.sensitive_features = {
            name: tuple(values) for name, values in self.sensitive_features.items()}

        n = len(self.y_true)
        if n == 0:
            raise ValueError("y_true is empty - there is nothing to disaggregate")
        if len(self.y_pred) != n:
            raise ValueError(
                f"y_pred has {len(self.y_pred)} rows, y_true has {n}")
        if not self.sensitive_features:
            raise ValueError(
                "no sensitive_features declared. Every group-fairness metric in "
                "the reviewed corpus requires a named protected attribute; "
                "there is no automatic detector for 'unfair' without one "
                "(knowledge/tenets.md, Fairness & Bias)")
        for name, values in self.sensitive_features.items():
            if len(values) != n:
                raise ValueError(
                    f"sensitive feature {name!r} has {len(values)} rows, "
                    f"y_true has {n}")

    @property
    def n_rows(self) -> int:
        return len(self.y_true)

    def groups(self, attribute: str) -> list[Any]:
        return sorted({v for v in self.sensitive_features[attribute]}, key=repr)


@dataclass
class BatchReport:
    """What one scheduled job produced.

    `findings` is the point: a batch job emits the same `Finding` objects a rail
    does, so an offline disparity and an inline flag land in the same audit
    record and the same compliance rollup. `judged=False` carries the identical
    semantics it has on `RailResult` - could not look, not found nothing.
    """

    job: str
    capability: str
    tool: str
    judged: bool = True
    reason: str | None = None
    metrics: dict[str, float | None] = field(default_factory=dict)
    by_group: dict[str, dict[Any, dict[str, float | None]]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def unjudged(cls, job: str, capability: str, tool: str,
                 reason: str) -> "BatchReport":
        return cls(job=job, capability=capability, tool=tool, judged=False,
                   reason=reason)

    def render(self) -> str:
        lines = [f"{self.job}  [{self.capability}]  via {self.tool}"]
        if not self.judged:
            lines.append(f"  COULD NOT RUN: {self.reason}")
            return "\n".join(lines)
        for key in sorted(self.metrics):
            value = self.metrics[key]
            lines.append(f"  {key:44s} "
                         + ("n/a" if value is None else f"{value:.4f}"))
        for note in self.notes:
            lines.append(f"  note: {note}")
        for finding in self.findings:
            lines.append(f"  finding {finding.category} "
                         f"({finding.severity.value if finding.severity else '-'}) "
                         f"on {finding.path} fp={finding.fp}")
        if not self.findings:
            lines.append("  no disparity above tolerance")
        return "\n".join(lines)


@runtime_checkable
class FairnessBatchJob(Protocol):
    """The interface a scheduled Fairlearn/AIF360/DeepEval job implements.

    Structural, like `Rail`, so a job written against fairlearn never has to
    import from this platform just to be schedulable. Two members and one
    method - deliberately the smallest surface that lets the offline half share
    the contract with the inline half.
    """

    spec: BatchJobSpec

    def run(self, dataset: BatchDataset) -> BatchReport:
        """Run the job. Must not raise for an expected failure - return
        `BatchReport.unjudged(...)`, for the same reason `Rail.check` does."""
        ...


# -- the metric arithmetic, ported from Fairlearn ------------------------------
#
# These are ports, not reimplementations of an idea. Each carries the file:line
# of the definition it follows.

def selection_rate(y_pred: Sequence[Any], positive_label: Any = 1) -> float | None:
    """Fraction of predictions matching the favourable outcome.

    Ported from fairlearn `selection_rate`
    (references/fairlearn-main/fairlearn/metrics/_base_metrics.py:299-330):
    `y_true` is required by upstream for signature consistency and then ignored,
    so it is simply absent here.
    """
    if not y_pred:
        return None
    return sum(1 for p in y_pred if p == positive_label) / len(y_pred)


def true_positive_rate(y_true: Sequence[Any], y_pred: Sequence[Any],
                       positive_label: Any = 1) -> float | None:
    """P[h(X)=1 | Y=1]. Ported from fairlearn `true_positive_rate`
    (_base_metrics.py:84). `None` when the group has no positive ground truth -
    the rate is undefined, and Fairlearn's own `errors='coerce'` yields NaN
    there (_metric_frame.py:776-778). Reporting 0.0 would be a fabrication."""
    positives = [p for t, p in zip(y_true, y_pred) if t == positive_label]
    if not positives:
        return None
    return sum(1 for p in positives if p == positive_label) / len(positives)


def false_positive_rate(y_true: Sequence[Any], y_pred: Sequence[Any],
                        positive_label: Any = 1) -> float | None:
    """P[h(X)=1 | Y=0]. Ported from fairlearn `false_positive_rate`
    (_base_metrics.py:162). `None` when the group has no negative ground
    truth."""
    negatives = [p for t, p in zip(y_true, y_pred) if t != positive_label]
    if not negatives:
        return None
    return sum(1 for p in negatives if p == positive_label) / len(negatives)


def difference(by_group: dict[Any, float | None], overall: float | None = None,
               method: str = "between_groups") -> float | None:
    """Max absolute difference across groups, the `MetricFrame.difference`
    semantics verbatim (_metric_frame.py:746-768):

        between_groups   group_max() - group_min()
        to_overall       max |group - overall|

    Groups whose metric is undefined are dropped rather than zero-filled; with
    fewer than two defined groups the difference itself is undefined and this
    returns `None`.
    """
    if method not in ("between_groups", "to_overall"):
        raise ValueError(f"method must be 'between_groups' or 'to_overall', "
                         f"got {method!r}")
    values = [v for v in by_group.values() if v is not None]
    if method == "between_groups":
        if len(values) < 2:
            return None
        return max(values) - min(values)
    if overall is None or not values:
        return None
    return max(abs(v - overall) for v in values)


def _by_group(dataset: BatchDataset, attribute: str,
              metric: Callable[[Sequence[Any], Sequence[Any]], float | None],
              ) -> dict[Any, float | None]:
    """`MetricFrame.by_group` for one attribute (_metric_frame.py:51)."""
    column = dataset.sensitive_features[attribute]
    out: dict[Any, float | None] = {}
    for group in dataset.groups(attribute):
        idx = [i for i, g in enumerate(column) if g == group]
        out[group] = metric(tuple(dataset.y_true[i] for i in idx),
                            tuple(dataset.y_pred[i] for i in idx))
    return out


def demographic_parity_difference(dataset: BatchDataset, attribute: str,
                                  method: str = "between_groups") -> float | None:
    """Largest minus smallest group-level selection rate.

    Ported from fairlearn `demographic_parity_difference`
    (_fairness_metrics.py:12-61): a `MetricFrame` over `selection_rate`,
    followed by `.difference(method=...)`. 0 means every group has the same
    selection rate.
    """
    by_group = _by_group(
        dataset, attribute,
        lambda yt, yp: selection_rate(yp, dataset.positive_label))
    overall = selection_rate(dataset.y_pred, dataset.positive_label)
    return difference(by_group, overall, method)


def equalized_odds_difference(dataset: BatchDataset, attribute: str,
                              method: str = "between_groups",
                              agg: str = "worst_case") -> float | None:
    """The greater (or mean) of the TPR difference and the FPR difference.

    Ported from fairlearn `equalized_odds_difference`
    (_fairness_metrics.py:118-175), including the `agg` parameter: `worst_case`
    takes the greater of the two, `mean` their average.
    """
    if agg not in ("worst_case", "mean"):
        raise ValueError(f"agg must be 'worst_case' or 'mean', got {agg!r}")
    tpr = difference(
        _by_group(dataset, attribute,
                  lambda yt, yp: true_positive_rate(yt, yp, dataset.positive_label)),
        true_positive_rate(dataset.y_true, dataset.y_pred, dataset.positive_label),
        method)
    fpr = difference(
        _by_group(dataset, attribute,
                  lambda yt, yp: false_positive_rate(yt, yp, dataset.positive_label)),
        false_positive_rate(dataset.y_true, dataset.y_pred, dataset.positive_label),
        method)
    defined = [v for v in (tpr, fpr) if v is not None]
    if not defined:
        return None
    if agg == "mean":
        return sum(defined) / len(defined)
    return max(defined)


# -- the one batch job that actually computes something -----------------------

GROUP_DISPARITY_CATEGORY = "x.afni.fairness.group_disparity"


class GroupFairnessMetricsJob:
    """Group fairness metrics, disaggregated by every declared protected
    attribute. OFFLINE - batch only, never in the request path.

    The production job should use Fairlearn's `MetricFrame` directly; that is
    the recommendation and that is what `spec.entry_point` names. This class
    exists for two reasons that are not "reimplementing Fairlearn":

      1. it makes the scaffold *verifiable*. The interface, the dataset
         validation, the `Finding` emission and the tolerance policy are all
         exercised in CI on a box with no numpy, no pandas and no fairlearn.
      2. it is a working reference for the two headline numbers, ported from the
         upstream definitions with the `file:line` on each function, so the
         scheduled job's output can be checked against something.

    It reports `None` rather than 0.0 for an undefined metric, and records why
    in `notes`. A fairness report that silently prints 0.0 for a group with no
    positive labels is worse than one that says it could not tell.
    """

    def __init__(self, tolerance: float = 0.1) -> None:
        if not 0.0 <= tolerance <= 1.0:
            raise ValueError(f"tolerance must be in [0, 1], got {tolerance}")
        self.tolerance = tolerance
        self.spec = _SPEC_GROUP_METRICS

    name = "fairlearn.group_fairness_metrics"

    def run(self, dataset: BatchDataset) -> BatchReport:
        report = BatchReport(job=self.name, capability=self.spec.capability,
                            tool=self.spec.tool)
        for attribute in sorted(dataset.sensitive_features):
            sel = _by_group(
                dataset, attribute,
                lambda yt, yp: selection_rate(yp, dataset.positive_label))
            tpr = _by_group(
                dataset, attribute,
                lambda yt, yp: true_positive_rate(yt, yp, dataset.positive_label))
            fpr = _by_group(
                dataset, attribute,
                lambda yt, yp: false_positive_rate(yt, yp, dataset.positive_label))
            report.by_group[attribute] = {
                group: {"selection_rate": sel[group],
                        "true_positive_rate": tpr[group],
                        "false_positive_rate": fpr[group]}
                for group in sel
            }

            dpd = demographic_parity_difference(dataset, attribute)
            eod = equalized_odds_difference(dataset, attribute)
            report.metrics[f"{attribute}.demographic_parity_difference"] = dpd
            report.metrics[f"{attribute}.equalized_odds_difference"] = eod

            for metric_name, value in (("demographic_parity_difference", dpd),
                                       ("equalized_odds_difference", eod)):
                if value is None:
                    report.notes.append(
                        f"{attribute}.{metric_name} undefined - fewer than two "
                        "groups with a defined rate; not reported as 0.0")
                    continue
                if value <= self.tolerance:
                    continue
                # Which group is worst off, so the finding points somewhere.
                defined = {g: v for g, v in sel.items() if v is not None}
                worst = min(defined, key=lambda g: defined[g]) if defined else attribute
                subject = str(worst)
                report.findings.append(Finding(
                    category=GROUP_DISPARITY_CATEGORY,
                    severity=Severity.HIGH if value > 2 * self.tolerance
                    else Severity.MEDIUM,
                    action=Action.FLAG,
                    # `path` names the dataset column, the batch analogue of a
                    # payload path.
                    path=f"dataset.{attribute}",
                    score=min(max(value, 0.0), 1.0),
                    detector=f"{self.name}.{metric_name}",
                    subject=subject,
                    fp=_fp(subject),
                ))
        return report


class DeclaredBatchJob:
    """A job that is declared and preflighted but NOT implemented here.

    Six of the seven offline capabilities are mitigation algorithms, subgroup
    scans and benchmark harnesses whose implementations are the whole point of
    adopting Fairlearn, AIF360, promptfoo and DeepEval. Reimplementing
    `ExponentiatedGradient` or the MDSS scan statistic in stdlib would be a
    worse answer than pointing at the real one, so this class does exactly that:
    it holds the spec, preflights the dependency, and returns an honest
    `unjudged` report naming what is missing.

    That is not a stub in the pejorative sense - it is the difference between a
    coverage report that says "offline, tool X, entry point Y, not installed"
    and one that says "TODO".
    """

    def __init__(self, spec: BatchJobSpec) -> None:
        self.spec = spec
        self.name = f"{spec.root_package}.{spec.capability.lower().replace(' ', '_')}"

    def run(self, dataset: BatchDataset) -> BatchReport:
        flight = self.spec.preflight()
        if not flight.available:
            return BatchReport.unjudged(self.name, self.spec.capability,
                                        self.spec.tool, flight.detail)
        return BatchReport.unjudged(
            self.name, self.spec.capability, self.spec.tool,
            f"{self.spec.tool} is installed but this job is a declaration only: "
            f"call {self.spec.entry_point} from the scheduled pipeline. "
            f"Requires: {', '.join(self.spec.requires)}")


# -- the offline runner registry ----------------------------------------------

_SPEC_GROUP_METRICS = BatchJobSpec(
    capability="Group fairness metrics",
    tool="Fairlearn",
    entry_point="fairlearn.metrics.MetricFrame",
    requires=("y_true", "y_pred", "sensitive_features"),
    cadence="scheduled batch (nightly on the previous day's scored decisions)",
    evidence="references/fairlearn-main/fairlearn/metrics/_metric_frame.py:51 "
             "(MetricFrame); _fairness_metrics.py:12 "
             "(demographic_parity_difference); _fairness_metrics.py:118 "
             "(equalized_odds_difference); difference() semantics at "
             "_metric_frame.py:746-768",
    note="Fairlearn is the pick over AIF360 here for Azure alignment and lower "
         "overhead; the Azure ML Responsible AI dashboard is built on Fairlearn "
         "itself, so the same numbers surface client-facing at no extra "
         "licensing cost. GroupFairnessMetricsJob in this package ports the two "
         "headline differences to stdlib so CI can run them with fairlearn "
         "absent.",
)

_SPEC_PREPROCESSING = BatchJobSpec(
    capability="Pre-processing mitigation",
    tool="AIF360 (Reweighing) / Fairlearn (CorrelationRemover)",
    entry_point="aif360.algorithms.preprocessing.Reweighing",
    requires=("training dataset", "privileged_groups", "unprivileged_groups"),
    cadence="scheduled batch, at model retraining time",
    evidence="references/AIF360-main/aif360/algorithms/preprocessing/"
             "reweighing.py:7 (Reweighing, Kamiran & Calders 2012); "
             "references/fairlearn-main/fairlearn/preprocessing/"
             "_correlation_remover.py:12 (CorrelationRemover)",
    note="AIF360 has the widest algorithm variety at this stage. Reweighing "
         "changes instance weights per (group, label) cell before training; "
         "CorrelationRemover projects the sensitive columns out of the features. "
         "Neither is a request-path operation - both rewrite training data.",
)

_SPEC_INPROCESSING = BatchJobSpec(
    capability="In-processing mitigation",
    tool="Fairlearn (ExponentiatedGradient) / AIF360 (AdversarialDebiasing)",
    entry_point="fairlearn.reductions.ExponentiatedGradient",
    requires=("estimator", "training dataset", "sensitive_features", "constraint"),
    cadence="scheduled batch, at model retraining time",
    evidence="references/fairlearn-main/fairlearn/reductions/"
             "_exponentiated_gradient/exponentiated_gradient.py:31; "
             "references/AIF360-main/aif360/algorithms/inprocessing/"
             "adversarial_debiasing.py:13 (AdversarialDebiasing)",
    note="AIF360 is the only source in the review with adversarial debiasing "
         "built in. This stage modifies the training objective, so it exists "
         "only inside a training pipeline.",
)

_SPEC_POSTPROCESSING = BatchJobSpec(
    capability="Post-processing mitigation",
    tool="Fairlearn (ThresholdOptimizer)",
    entry_point="fairlearn.postprocessing.ThresholdOptimizer",
    requires=("fitted estimator", "validation dataset", "sensitive_features",
              "constraint"),
    cadence="scheduled batch; the fitted thresholds are then served",
    evidence="references/fairlearn-main/fairlearn/postprocessing/"
             "_threshold_optimizer.py:115 (ThresholdOptimizer)",
    note="Simple and well tested: it fits per-group decision thresholds against "
         "a constraint. The FITTING is offline; the fitted thresholds are the "
         "one artefact of this tenet that can legitimately be applied inline, "
         "and they are applied by the serving model, not by a gateway rail.",
)

_SPEC_SUBGROUP_DISCOVERY = BatchJobSpec(
    capability="Automated subgroup discovery",
    tool="AIF360 (MDSS bias_scan, FACTS)",
    entry_point="aif360.sklearn.detectors.MDSS_bias_scan",
    requires=("features dataframe", "observations (y_true)",
              "expectations (y_pred or model)"),
    cadence="scheduled batch, weekly",
    evidence="references/AIF360-main/aif360/detectors/mdss_detector.py:15 "
             "(bias_scan); aif360/sklearn/detectors/detectors.py:9 "
             "(MDSS_bias_scan); aif360/sklearn/detectors/facts/__init__.py:28 "
             "(FACTS_bias_scan), :238 (FACTS)",
    note="The real differentiator against Fairlearn: MDSS and FACTS FIND the "
         "biased subgroup rather than needing it named, which is the one thing "
         "that partially answers the objection that fairness needs a protected "
         "group declared up front. It still needs a labelled ground truth, so "
         "it is still batch.",
)

_SPEC_BENCHMARKS = BatchJobSpec(
    capability="Bias benchmark harnesses",
    tool="DeepEval (BBQ, EquityMedQA)",
    entry_point="deepeval.benchmarks.bbq.BBQ",
    requires=("a model under test", "the BBQ/EquityMedQA corpora"),
    cadence="CI, per model or prompt change",
    evidence="references/deepeval-main/deepeval/benchmarks/bbq/task.py:5-15 "
             "(BBQTask, 11 axes); deepeval/benchmarks/bbq/bbq.py:16 (BBQ, "
             "n_shots<=5); deepeval/benchmarks/equity_med_qa/task.py:5-13 "
             "(EquityMedQATask, 9 subsets)",
    note="BBQ's 11 tasks are the widest protected-attribute enumeration in the "
         "corpus and are the source of this package's axis list. BBQ is scored "
         "by multiple-choice exact match, so it needs no judge; EquityMedQA is "
         "judge-scored and therefore costs money per run.",
)

_SPEC_REDTEAM = BatchJobSpec(
    capability="Bias red-team probe packs",
    tool="promptfoo (bias:age, bias:disability, bias:gender, bias:race)",
    entry_point="promptfoo.redteam.plugins.bias",
    requires=("a target endpoint", "api.promptfoo.app for generation"),
    cadence="CI, per release",
    evidence="references/promptfoo-main/src/redteam/constants/plugins.ts:233 "
             "(BIAS_PLUGINS); src/redteam/plugins/bias.ts:6 (BiasGrader "
             "stereotyping rubric); src/redteam/constants/plugins.ts:576-582 "
             "(UI_DISABLED_WHEN_REMOTE_UNAVAILABLE includes BIAS_PLUGINS)",
    note="DATA RESIDENCY: the bias:* probes are REMOTE-GENERATED ONLY. "
         "plugins.ts:576-582 lists BIAS_PLUGINS among the plugins disabled when "
         "remote generation is unavailable, so running this pack sends "
         "AFNI-derived prompts and application purpose to api.promptfoo.app. "
         "That is a review item before adoption, not a blocker - it is a CI "
         "job, so no client traffic is involved. Note also that the entry point "
         "is a Node/TypeScript package, not a Python import: preflight() will "
         "always report it absent from a Python environment, which is accurate "
         "rather than a false negative.",
)

OFFLINE_JOB_SPECS: tuple[BatchJobSpec, ...] = (
    _SPEC_GROUP_METRICS,
    _SPEC_PREPROCESSING,
    _SPEC_INPROCESSING,
    _SPEC_POSTPROCESSING,
    _SPEC_SUBGROUP_DISCOVERY,
    _SPEC_BENCHMARKS,
    _SPEC_REDTEAM,
)

#: The offline runner registry. Every capability this package registers as
#: `Coverage.OFFLINE` has an entry here, so the coverage report points at a
#: named entry point in a named library with a preflight check.
BATCH_JOBS: tuple[Any, ...] = (
    GroupFairnessMetricsJob(),
    DeclaredBatchJob(_SPEC_PREPROCESSING),
    DeclaredBatchJob(_SPEC_INPROCESSING),
    DeclaredBatchJob(_SPEC_POSTPROCESSING),
    DeclaredBatchJob(_SPEC_SUBGROUP_DISCOVERY),
    DeclaredBatchJob(_SPEC_BENCHMARKS),
    DeclaredBatchJob(_SPEC_REDTEAM),
)


def job_for(capability: str) -> Any:
    """The scheduled job serving one capability. Raises rather than returning
    None - a missing job means the coverage report is lying."""
    for job in BATCH_JOBS:
        if job.spec.capability == capability:
            return job
    raise KeyError(f"no batch job registered for capability {capability!r}")


def offline_readiness() -> dict[str, PreflightResult]:
    """Could each scheduled job run on this box? For the batch environment's
    own health check, and for the note on each OFFLINE registration."""
    return {spec.capability: spec.preflight() for spec in OFFLINE_JOB_SPECS}


# ============================================================================
# Rails, attributions, registration
# ============================================================================

PROTECTED_ATTRIBUTE_RAIL = ProtectedAttributeReferenceRail()
LOCAL_BIAS_CLASSIFIER_RAIL = LocalBiasClassifierRail()
GENERATIVE_BIAS_JUDGE_RAIL = GenerativeBiasJudgeRail()

#: Mountable in the request cascade.
#:
#: The Stage 2 rail is included even though it reports `unjudged` on a stock
#: box. That is the documented, intended contract (see its docstring): a missing
#: dependency must surface as "could not look", and the engine's fail-closed
#: rule must then block client-facing traffic. It only runs when something
#: escalates, and the Stage 1 rail here deliberately does not escalate, so the
#: blast radius is traffic another tenet's rail flagged as severe.
RAILS: list[Any] = [PROTECTED_ATTRIBUTE_RAIL, LOCAL_BIAS_CLASSIFIER_RAIL]

#: Adapters that exist but must not be mounted until a paid dependency is wired
#: up. Kept out of `RAILS` so importing this package cannot accidentally block
#: every escalated request on a box with no LLM judge configured.
CLOUD_RAILS: list[Any] = [GENERATIVE_BIAS_JUDGE_RAIL]

ATTR_PROTECTED_ATTRIBUTE = RailAttribution(
    rail=PROTECTED_ATTRIBUTE_RAIL.name,
    source_repo="afni (composed from promptfoo + DeepEval BBQ + Infosys "
                "vocabularies)",
    display_name="Protected-attribute reference detector",
    mechanism="Keyword/Regex - protected-attribute term and decision term "
              "co-occurring in one sentence, with person-noun anchoring for "
              "ambiguous terms and severity raised by an explicit conditioning "
              "connective",
    stage=int(Stage.STAGE_1),
    confidence_kind="deterministic",
    evidence="axes from references/deepeval-main/deepeval/benchmarks/bbq/"
             "task.py:5-15 (11 BBQ axes) and references/promptfoo-main/src/"
             "redteam/constants/plugins.ts:233 (BIAS_PLUGINS); group terms from "
             "references/Infosys-Responsible-AI-Toolkit-master/"
             "responsible-ai-fairness/responsible-ai-fairness/src/fairness/"
             "service/service_monitoring.py:57-62; differential-treatment "
             "framing from references/promptfoo-main/src/redteam/plugins/"
             "bias.ts:31-45; decision domains from AIF360 adult/german/bank/"
             "compas/law_school datasets and fairlearn/datasets/_fetch_*.py",
    # DELIBERATELY None. There is no row in capability_matrix_data.json for
    # "protected attribute presence", and mapping this rail onto "Bias detection
    # (generative)" would report a fairness capability that does not exist.
    capability=None,
)

ATTR_LOCAL_BIAS_CLASSIFIER = RailAttribution(
    rail=LOCAL_BIAS_CLASSIFIER_RAIL.name,
    source_repo="llm-guard-main",
    display_name="LLM Guard Bias scanner",
    mechanism="Classifier - text-classification against a threshold",
    stage=int(Stage.STAGE_2),
    confidence_kind="classifier",
    evidence="references/llm-guard-main/llm-guard-main/llm_guard/output_scanners/"
             "bias.py:14 (model valurank/distilroberta-bias), :15 (revision "
             "c1e4a2773522c3acc929a7b2c9af2b7e4137b96d), :46 (threshold 0.7), "
             ":87-90 (label-inversion scoring)",
    capability="Local bias classifier (text)",
)

ATTR_GENERATIVE_BIAS_JUDGE = RailAttribution(
    rail=GENERATIVE_BIAS_JUDGE_RAIL.name,
    source_repo="hai-guardrails-main",
    display_name="hai-guardrails biasDetectionGuard",
    mechanism="LLM-judge - scoring prompt with a zod-validated schema",
    stage=int(Stage.STAGE_3),
    confidence_kind="judge",
    evidence="references/hai-guardrails-main/hai-guardrails-main/src/guards/"
             "bias-detection.guard.ts:74-103 (llmGuard, ValidationType.Score, "
             "threshold 0.7, schema score/reason/categories/affectedGroups/"
             "impact)",
    capability="Bias detection (generative)",
)

_OFFLINE_ATTRIBUTIONS: dict[str, RailAttribution] = {
    _SPEC_GROUP_METRICS.capability: RailAttribution(
        rail="fairlearn.metric_frame",
        source_repo="fairlearn-main",
        display_name="Fairlearn MetricFrame",
        mechanism="Statistical + Module - disaggregates metrics by "
                  "sensitive_features",
        stage=int(Stage.OFFLINE),
        confidence_kind="deterministic",
        evidence=_SPEC_GROUP_METRICS.evidence,
        capability=_SPEC_GROUP_METRICS.capability,
    ),
    _SPEC_PREPROCESSING.capability: RailAttribution(
        rail="aif360.reweighing",
        source_repo="AIF360-main",
        display_name="AIF360 Reweighing / Fairlearn CorrelationRemover",
        mechanism="Module - reweights or transforms training data before fitting",
        stage=int(Stage.OFFLINE),
        confidence_kind="deterministic",
        evidence=_SPEC_PREPROCESSING.evidence,
        capability=_SPEC_PREPROCESSING.capability,
    ),
    _SPEC_INPROCESSING.capability: RailAttribution(
        rail="fairlearn.exponentiated_gradient",
        source_repo="fairlearn-main",
        display_name="Fairlearn ExponentiatedGradient / AIF360 "
                     "AdversarialDebiasing",
        mechanism="Module - constrained reduction during training",
        stage=int(Stage.OFFLINE),
        confidence_kind="deterministic",
        evidence=_SPEC_INPROCESSING.evidence,
        capability=_SPEC_INPROCESSING.capability,
    ),
    _SPEC_POSTPROCESSING.capability: RailAttribution(
        rail="fairlearn.threshold_optimizer",
        source_repo="fairlearn-main",
        display_name="Fairlearn ThresholdOptimizer",
        mechanism="Module - fits per-group decision thresholds against a "
                  "constraint",
        stage=int(Stage.OFFLINE),
        confidence_kind="deterministic",
        evidence=_SPEC_POSTPROCESSING.evidence,
        capability=_SPEC_POSTPROCESSING.capability,
    ),
    _SPEC_SUBGROUP_DISCOVERY.capability: RailAttribution(
        rail="aif360.mdss_bias_scan",
        source_repo="AIF360-main",
        display_name="AIF360 MDSS / FACTS bias scan",
        mechanism="Statistical - scan statistic over subsets; discovers the "
                  "biased subgroup instead of requiring it named",
        stage=int(Stage.OFFLINE),
        confidence_kind="deterministic",
        evidence=_SPEC_SUBGROUP_DISCOVERY.evidence,
        capability=_SPEC_SUBGROUP_DISCOVERY.capability,
    ),
    _SPEC_BENCHMARKS.capability: RailAttribution(
        rail="deepeval.bbq",
        source_repo="deepeval-main",
        display_name="DeepEval BBQ / EquityMedQA harnesses",
        mechanism="Benchmark harness - BBQ multiple-choice exact match; "
                  "EquityMedQA judge-scored",
        stage=int(Stage.OFFLINE),
        confidence_kind="deterministic",
        evidence=_SPEC_BENCHMARKS.evidence,
        capability=_SPEC_BENCHMARKS.capability,
    ),
    _SPEC_REDTEAM.capability: RailAttribution(
        rail="promptfoo.bias_plugins",
        source_repo="promptfoo-main",
        display_name="promptfoo bias:age/disability/gender/race",
        mechanism="Attack generator + LLM-judge - remote-generated probes "
                  "graded by the BiasGrader stereotyping rubric",
        stage=int(Stage.OFFLINE),
        confidence_kind="judge",
        evidence=_SPEC_REDTEAM.evidence,
        capability=_SPEC_REDTEAM.capability,
    ),
}

#: Keyed by rail name, for `contract.explanation.explain()`.
ATTRIBUTIONS: dict[str, RailAttribution] = {
    ATTR_PROTECTED_ATTRIBUTE.rail: ATTR_PROTECTED_ATTRIBUTE,
    ATTR_LOCAL_BIAS_CLASSIFIER.rail: ATTR_LOCAL_BIAS_CLASSIFIER,
    ATTR_GENERATIVE_BIAS_JUDGE.rail: ATTR_GENERATIVE_BIAS_JUDGE,
}

#: Every `Finding.category` this package can emit. Asserted in the tests so a
#: typo cannot reach a compliance rollup.
CATEGORIES: tuple[str, ...] = (
    ProtectedAttributeReferenceRail.CATEGORY,
    LocalBiasClassifierRail.CATEGORY,
    GenerativeBiasJudgeRail.CATEGORY,
    GROUP_DISPARITY_CATEGORY,
)


def register(registry) -> None:
    """Declare Fairness & Bias coverage, at its true status.

    All nine matrix capabilities are registered and none is left a GAP, but
    read the statuses rather than the count: seven are OFFLINE, one is CLOUD, and
    exactly one can be IMPLEMENTED - and only on a box with transformers and
    torch installed. On a stock box this tenet has **zero** runtime cover, which
    is what the analysis says it should have.

    The protected-attribute rail is registered against nothing on purpose. It is
    a real Stage 1 detector that runs today, but the capability matrix has no
    row for it, and attaching it to a row it does not implement is precisely the
    inflation this report exists to prevent.
    """
    readiness = offline_readiness()

    # --- OFFLINE: seven capabilities whose only tools are batch/CI tools ---
    for spec in OFFLINE_JOB_SPECS:
        flight = readiness[spec.capability]
        registry.register(
            TENET, spec.capability, Coverage.OFFLINE,
            attribution=_OFFLINE_ATTRIBUTIONS[spec.capability],
            note=(f"{spec.tool} - {spec.cadence}. Entry point "
                  f"{spec.entry_point}; preflight: "
                  f"{'available' if flight.available else 'dependency absent'}. "
                  f"{spec.note}"),
        )

    # --- CLOUD: the generative judge needs a paid API ---------------------
    registry.register(
        TENET, "Bias detection (generative)", Coverage.CLOUD,
        attribution=ATTR_GENERATIVE_BIAS_JUDGE,
        note="hai-guardrails biasDetectionGuard is an LLM judge and needs a "
             "paid API; the adapter (GenerativeBiasJudgeRail) exists and takes "
             "the judge as a callable, but nothing is configured, so it reports "
             "unjudged and is deliberately NOT in RAILS. Cloud alternatives "
             "from the analysis: Azure ML Responsible AI dashboard (Fairlearn-"
             "based, free managed view), Fiddler AI / Arthur AI only if AFNI "
             "needs always-on production bias-drift alerting rather than "
             "scheduled batch checks.",
    )

    # --- The one capability with a real inline rail ------------------------
    available = LocalBiasClassifierRail.dependency_available()
    registry.register_rail(
        LOCAL_BIAS_CLASSIFIER_RAIL, ATTR_LOCAL_BIAS_CLASSIFIER,
        available=available,
        note=("LLM Guard Bias output scanner, " + (
            "transformers and torch present - runs today."
            if available else
            "transformers/torch absent - the rail is mounted and reports "
            "unjudged, so fail-closed will BLOCK client-facing traffic that "
            "reaches Stage 2. Install transformers + torch and pin revision "
            f"{LocalBiasClassifierRail.MODEL_REVISION} to turn this into "
            "protection.")) +
             " Reported as a flag, not a block: one classifier score on one "
             "response is not a fairness measurement.",
    )

    # NOT registered, and that is the honest answer:
    #   ProtectedAttributeReferenceRail runs on 100% of traffic today but
    #   implements no row of the Fairness capability matrix. Its attribution
    #   carries capability=None so `register_rail` would refuse it, which is
    #   the guard working as intended.


__all__ = [
    "TENET", "AXES", "CATEGORIES",
    "ProtectedAttributeReferenceRail", "LocalBiasClassifierRail",
    "GenerativeBiasJudgeRail",
    "PROTECTED_ATTRIBUTE_RAIL", "LOCAL_BIAS_CLASSIFIER_RAIL",
    "GENERATIVE_BIAS_JUDGE_RAIL",
    "RAILS", "CLOUD_RAILS", "ATTRIBUTIONS",
    "BatchDataset", "BatchReport", "BatchJobSpec", "PreflightResult",
    "FairnessBatchJob", "GroupFairnessMetricsJob", "DeclaredBatchJob",
    "OFFLINE_JOB_SPECS", "BATCH_JOBS", "job_for", "offline_readiness",
    "selection_rate", "true_positive_rate", "false_positive_rate", "difference",
    "demographic_parity_difference", "equalized_odds_difference",
    "GROUP_DISPARITY_CATEGORY",
    "register",
]
