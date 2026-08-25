# -*- coding: utf-8 -*-
"""
Self-hardening attack corpus - the local, free half of the Rebuff loop.

WHAT REBUFF DOES

Rebuff is the only self-learning attack corpus in the 23 repos. When a canary
word planted in the prompt comes back in the completion, the attack is *confirmed*
and gets written back into the vector index that screens future prompts -
`references/rebuff-main/python-sdk/rebuff/sdk.py:205-221`:

    def log_leakage(self, user_input, completion, canary_word) -> None:
        if self.vector_store is None:
            self.initialize_pinecone()
        self.vector_store.add_texts(
            [user_input],
            metadatas=[{"completion": completion, "canary_word": canary_word}],
        )

That is the whole idea and it is a good one: an attack that worked once becomes a
detector for itself. The per-repo caveat records the catch - "Only the L1
heuristic layer is genuinely free and local... embeddings still call OpenAI
ada-002. The self-hardening corpus (log_leakage back into the same index) is the
part AFNI wants to reimplement."

WHAT THIS FILE IMPLEMENTS, AND WHAT IT DOES NOT

Implemented, Stage 1, zero dependencies:

  * the append interface - `AttackCorpus.confirm()`, the direct analogue of
    `log_leakage`, callable from the request path when a canary leaks or an
    operator confirms a finding;
  * exact-repeat detection by normalised sha256 fingerprint;
  * near-repeat detection by Jaccard similarity over the word set, which is
    exactly what JCB's copyright memorisation test does -
    `references/JCB-main/eval_utils.py:240-242` builds a MinHash by updating it
    once per word, and `:247`/`:264` compare with `score > threshold` at
    `threshold=0.6` ("0.6 works well for the current books and lyrics"). MinHash
    is an *approximation* of set Jaccard for large sets; on prompt-sized inputs
    the exact set Jaccard computed here is strictly more accurate and needs no
    dependency.

NOT implemented, and registered as the cloud half: embedding similarity. Rebuff's
recall comes from ada-002 embeddings in Pinecone, which catches a paraphrase that
shares no vocabulary. Token Jaccard does not. So this rail catches replays and
light mutations of a confirmed attack, not a reworded one, and the coverage
registration says so.

PRIVACY

The corpus stores no plaintext by default. `store_text=False` keeps only the
fingerprint and the set of *hashed* words - and Jaccard over hashed tokens equals
Jaccard over the raw tokens, so detection is unaffected. That matters because a
confirmed attack payload can contain whatever the attacker pasted into it,
including someone else's data. Rebuff stores the raw `user_input` and the raw
`completion`; this does not, unless a deployment opts in.

Zero third-party dependencies.
"""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from ...cascade.rail import RailResult, Stage
from ...cascade.rail import CheckContext
from ...contract.explanation import RailAttribution
from ...contract.models import Action, Finding, Severity, Tenet
from .thresholds import ThresholdMisconfigured, ThresholdStore

# The category a repeat is reported under when the stored entry does not name its
# own. `x.` is the vendor-extension namespace
# (`openguardrails/specification/taxonomy.md` conventions), which is where an
# AFNI-specific detector belongs.
DEFAULT_CATEGORY = "x.afni.attack_corpus.confirmed_repeat"

# The threshold key the rail resolves per tenant. Default 0.60 lives in
# `thresholds.GLOBAL_DEFAULTS`, cited to JCB.
SIMILARITY_KEY = "x.afni.attack_corpus.similarity"

# Below this many tokens a Jaccard score is not meaningful - two three-word
# prompts sharing two words score 0.67 and would fire on nothing. Exact
# fingerprint matching still covers short payloads.
MIN_TOKENS_FOR_SIMILARITY = 6

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def normalise(text: str) -> str:
    """NFKC, casefold, collapse whitespace.

    NFKC first so a homoglyph or full-width variant of a confirmed attack matches
    the entry it is a variant of - the same normalisation the unicode-smuggling
    rails rely on, and the cheapest possible defence against a trivially mutated
    replay.
    """
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.casefold().split())


def fingerprint(text: str, length: int = 32) -> str:
    """sha256 prefix of the normalised text. The corpus key, and the only
    representation of a payload the corpus is required to keep."""
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()[:length]


def tokens(text: str) -> frozenset[str]:
    """The word set JCB's MinHash is built over (`eval_utils.py:241-242` splits
    the chunk on whitespace and updates once per word). A *set*, not a list -
    MinHash's Jaccard is a set operation, so duplicates never counted upstream
    either."""
    return frozenset(_WORD_RE.findall(normalise(text)))


def token_hashes(text: str, length: int = 12) -> frozenset[str]:
    """Hashed word set. Jaccard is preserved exactly under a per-element hash, so
    this gives the same similarity score without retaining the words."""
    return frozenset(hashlib.sha256(t.encode("utf-8")).hexdigest()[:length]
                     for t in tokens(text))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """|A n B| / |A u B|. JCB's `mh_output.jaccard(mh_ref)` (eval_utils.py:261),
    computed exactly rather than estimated."""
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


@dataclass(frozen=True)
class AttackEntry:
    """One confirmed attack. Rebuff's `add_texts([user_input], metadatas=[...])`
    (sdk.py:218-221), minus the plaintext."""

    fp: str
    token_hashes: frozenset[str]
    category: str = DEFAULT_CATEGORY
    source: str = "runtime-confirmed"
    severity: Severity = Severity.HIGH
    added_at: float = field(default_factory=time.time)
    # Rebuff's metadata equivalent: which canary leaked, which event confirmed it.
    canary: str | None = None
    event_id: str | None = None
    note: str = ""
    # Only populated when the corpus is explicitly configured to keep plaintext.
    text: str | None = None

    @property
    def size(self) -> int:
        return len(self.token_hashes)


@dataclass(frozen=True)
class CorpusHit:
    entry: AttackEntry
    score: float
    exact: bool
    threshold: float
    threshold_source: str


class AttackCorpus:
    """Append-only store of confirmed attacks, with exact and near matching.

    In-memory by default. `snapshot()` / `load()` move it to and from a plain
    list of dicts so a deployment can persist it beside the audit DB without this
    module choosing a storage engine.
    """

    def __init__(self, store_text: bool = False) -> None:
        self._store_text = store_text
        self._by_fp: dict[str, AttackEntry] = {}

    def __len__(self) -> int:
        return len(self._by_fp)

    def __iter__(self) -> Iterator[AttackEntry]:
        return iter(self._by_fp.values())

    @property
    def stores_plaintext(self) -> bool:
        return self._store_text

    def confirm(self, text: str, *, category: str = DEFAULT_CATEGORY,
                source: str = "runtime-confirmed",
                severity: Severity = Severity.HIGH,
                canary: str | None = None, event_id: str | None = None,
                note: str = "") -> AttackEntry:
        """Rebuff's `log_leakage` (sdk.py:205-221): write a confirmed attack back
        into the corpus that screens future traffic.

        Idempotent on the normalised fingerprint - the same attack arriving twice
        does not grow the corpus, which matters because a replayed attack is
        precisely the case this exists to catch.
        """
        # Validate the category through the contract rather than trusting the
        # caller: a corpus entry's category ends up on a Finding, and a malformed
        # one would raise at detection time instead of at insertion time.
        Finding(category=category)
        fp = fingerprint(text)
        existing = self._by_fp.get(fp)
        if existing is not None:
            return existing
        entry = AttackEntry(
            fp=fp, token_hashes=token_hashes(text), category=category,
            source=source, severity=severity, canary=canary, event_id=event_id,
            note=note, text=text if self._store_text else None)
        self._by_fp[fp] = entry
        return entry

    def extend(self, texts: Iterable[str], **kwargs) -> list[AttackEntry]:
        """Bulk load - a garak or promptfoo run's confirmed hits, seeded into the
        corpus from CI. Same schema as a runtime confirmation, which is the
        "same record shape everywhere" rule applied to the corpus."""
        return [self.confirm(t, **kwargs) for t in texts]

    def contains(self, text: str) -> bool:
        return fingerprint(text) in self._by_fp

    def best_match(self, text: str, threshold: float) -> CorpusHit | None:
        """Exact fingerprint first, then the highest Jaccard above `threshold`.

        Exact first because it is O(1) and because an exact replay deserves the
        deterministic 1.0 score rather than a similarity number.
        """
        fp = fingerprint(text)
        exact = self._by_fp.get(fp)
        if exact is not None:
            return CorpusHit(entry=exact, score=1.0, exact=True,
                             threshold=threshold, threshold_source="exact-match")
        hashes = token_hashes(text)
        if len(hashes) < MIN_TOKENS_FOR_SIMILARITY:
            return None
        best: CorpusHit | None = None
        for entry in self._by_fp.values():
            if entry.size < MIN_TOKENS_FOR_SIMILARITY:
                continue
            score = jaccard(hashes, entry.token_hashes)
            # JCB eval_utils.py:264 uses strict `>`, so a score exactly at the
            # threshold does not fire. Kept, so a threshold ported from JCB
            # keeps its meaning.
            if score > threshold and (best is None or score > best.score):
                best = CorpusHit(entry=entry, score=score, exact=False,
                                 threshold=threshold, threshold_source="jaccard")
        return best

    def snapshot(self) -> list[dict[str, object]]:
        return [{"fp": e.fp, "token_hashes": sorted(e.token_hashes),
                 "category": e.category, "source": e.source,
                 "severity": e.severity.value, "added_at": e.added_at,
                 "canary": e.canary, "event_id": e.event_id, "note": e.note,
                 "text": e.text}
                for e in self._by_fp.values()]

    def load(self, rows: Iterable[dict]) -> int:
        added = 0
        for row in rows:
            fp = str(row["fp"])
            if fp in self._by_fp:
                continue
            self._by_fp[fp] = AttackEntry(
                fp=fp,
                token_hashes=frozenset(row.get("token_hashes") or ()),
                category=str(row.get("category") or DEFAULT_CATEGORY),
                source=str(row.get("source") or "imported"),
                severity=Severity(row.get("severity") or Severity.HIGH.value),
                added_at=float(row.get("added_at") or time.time()),
                canary=row.get("canary"), event_id=row.get("event_id"),
                note=str(row.get("note") or ""),
                text=row.get("text") if self._store_text else None)
            added += 1
        return added


ATTRIBUTION = RailAttribution(
    rail="attack-corpus-repeat",
    source_repo="rebuff-main",
    display_name="Rebuff self-hardening corpus (local half)",
    mechanism="Keyword/Regex - normalised sha256 fingerprint plus exact Jaccard "
              "over the hashed word set",
    stage=int(Stage.STAGE_1),
    confidence_kind="deterministic",
    evidence="rebuff-main/python-sdk/rebuff/sdk.py:205-221 (log_leakage writes the "
             "confirmed attack back into the index); similarity mechanism and the "
             "0.6 threshold from JCB-main/eval_utils.py:240-242,247,264",
    capability="Self-hardening attack corpus",
)


class AttackCorpusRail:
    """Stage 1. Blocks a replay or light mutation of an attack already confirmed.

    Per-tenant threshold, resolved on every check through `ThresholdStore` - and
    that is deliberate rather than incidental. Safe Zone stores per-pattern
    thresholds and never reads them (`internal/guardrails/thresholds.go:8-24`
    uses env globals instead); this rail's threshold comes from the store on the
    detection path, and `test_accountability.py` asserts against the store's read
    log to prove it.

    A misconfigured threshold produces `unjudged`, not a default. Substituting a
    sane-looking fallback for a broken config is how a tuned threshold becomes a
    lie; fail-closed then blocks the client-facing request and somebody fixes the
    config.
    """

    tenet = Tenet.ACCOUNTABILITY
    stage = Stage.STAGE_1

    def __init__(self, corpus: AttackCorpus | None = None,
                 thresholds: ThresholdStore | None = None,
                 tenant: str | None = None,
                 name: str = "attack-corpus-repeat") -> None:
        self.name = name
        self.corpus = corpus if corpus is not None else AttackCorpus()
        self.thresholds = thresholds if thresholds is not None else ThresholdStore()
        self.tenant = tenant

    def for_tenant(self, tenant: str | None) -> "AttackCorpusRail":
        """A rail pre-bound to one account, sharing the corpus and the store.

        Retained for a single-tenant deployment and for tests. It is no longer
        how the gateway does it: `check` now takes the tenant from the request
        context, because a rail whose tenant is fixed at construction applies one
        account's threshold to every account's traffic once it is mounted in a
        shared cascade. `ctx.tenant` wins over this when a context is passed.
        """
        return AttackCorpusRail(self.corpus, self.thresholds, tenant, self.name)

    def check(self, path: str, text: str,
              ctx: "CheckContext | None" = None) -> RailResult:
        if not text or not self.corpus:
            # Nothing confirmed yet is a genuine clean, not an inability to look:
            # an empty corpus means no attack has ever been confirmed.
            return RailResult.clean()

        # The request's tenant, not the one this instance happened to be built
        # with. A mounted rail serves every account.
        tenant = ctx.tenant if ctx is not None else self.tenant
        try:
            read = self.thresholds.resolve(tenant, SIMILARITY_KEY)
        except ThresholdMisconfigured as exc:
            return RailResult.unjudged(f"{self.name}: {exc}")
        if ctx is not None:
            ctx.reads.append((SIMILARITY_KEY, read.value, "resolved"))

        hit = self.corpus.best_match(text, read.value)
        if hit is None:
            return RailResult.clean()

        finding = Finding(
            category=hit.entry.category,
            severity=hit.entry.severity,
            action=Action.BLOCK,
            path=path,
            score=1.0 if hit.exact else round(hit.score, 4),
            detector=self.name,
            # The fingerprint of the *incoming* text, which for an exact hit
            # equals the corpus entry's. Never the text itself.
            fp=fingerprint(text, 16),
        )
        reason = (f"{'exact' if hit.exact else 'near'} repeat of a confirmed attack "
                  f"(score {finding.score}, threshold {read.value} via {read.source})")
        # `block=True` ends the cascade. A confirmed attack replay is the one case
        # where there is nothing left to decide, so paying for stage 2 or 3 on it
        # would be spending money to re-derive a known answer.
        return RailResult(judged=True, findings=[finding], block=True, reason=reason)


RAIL = AttackCorpusRail
