# -*- coding: utf-8 -*-
"""
The verdict store: every decision, live or offline, in one schema.

The deck's request-flow slide ends every branch - including delivery - at a
single box (`knowledge/request-flow.md` §"The flow", the AUDIT STORE box):

    AUDIT STORE - every verdict, one schema
    findings . severity . score . redaction spans . OpenTelemetry trace

and two design notes make it load-bearing: "Delivered responses are logged too,
not just blocks. The audit trail is the evidence pack for a client reviewer; a
log of only refusals proves nothing", and "Same record shape everywhere. A
red-team finding, a CI failure and a live production block are all one schema, so
they can be trended on one dashboard."

WHAT WAS PORTED, AND FROM WHERE

  Guardrails AI  `guardrails/call_tracing/sqlite_trace_handler.py:63-73` -
                 a local SQLite trace DB (`CREATE TABLE IF NOT EXISTS
                 guard_logs`) opened with `isolation_level=None` and
                 `PRAGMA journal_mode = wal` so readers and writers coexist.
                 Ported: stdlib `sqlite3`, WAL, same reader/writer split. NOT
                 ported: upstream stores `prevalidate_text` and
                 `postvalidate_text` - the entire payload, before and after - and
                 `PRAGMA synchronous = OFF`, which its own comment calls "the
                 highway to the danger zone". AFNI stores neither the payload nor
                 any matched value, and leaves synchronous at its default.

  Safe Zone      `internal/metrics/store.go:18-42` - a 50-event in-memory ring
                 buffer for the dashboard, whose comment is the best statement of
                 the rule in the whole reviewed set: the struct deliberately
                 omits the detected PII value and the raw request body, because
                 the record keeps "what happened", not "what it contained".
                 `internal/guardrails/siem.go:16-39` - a SecurityEvent POSTed to
                 `SIEM_WEBHOOK_URL`, silently disabled when unset, 2s timeout.
                 Ported: the ring buffer, the `[AUDIT]` log line, and the
                 SecurityEvent field shape (`internal/models/security_event.go:5-14`).
                 NOT ported: the outbound HTTP call. A sink is a caller-supplied
                 callable here, so this module makes no network call, ever, and
                 an unreachable SIEM can never add latency to a request.

THE ONE HARD RULE

`Finding.subject` is the matched value - an actual SSN, an actual API key. It is
never written to this database. The `findings` table has no `subject` column at
all, so the guarantee is structural rather than a filter someone can forget: only
`fp`, the sha256 fingerprint the engine minted, is persisted. A guardrail whose
audit log contains the SSN it caught has defeated itself, and this is the
component where that mistake would be permanent.

Zero third-party dependencies.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from ...contract.explanation import Explanation, RailAttribution
from ...contract.models import Finding, GuardEvent, Span, Verdict

LOGGER = logging.getLogger("afni_rai.audit")

# Safe Zone internal/metrics/store.go:42 - `const maxEvents = 50`.
RING_BUFFER_SIZE = 50

# The one field that must never reach storage. Named so the guard is greppable
# and so the test that proves the guarantee has something to assert against.
FORBIDDEN_FINDING_FIELDS = ("subject",)


# Origin is a documented string vocabulary rather than an Enum, because the same
# record shape has to accept a value written by a CI job that does not import this
# package. "Same record shape everywhere" (request-flow.md §'Also true') only holds if an
# offline tool can produce a valid row without a dependency on the gateway.
ORIGIN_LIVE = "live"          # the request path
ORIGIN_OFFLINE = "offline"    # garak / promptfoo / PyRIT in CI
ORIGIN_REPLAY = "replay"      # a stored event re-run against new rails

_SCHEMA = """
CREATE TABLE IF NOT EXISTS verdicts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      TEXT    NOT NULL,
    origin        TEXT    NOT NULL,
    provider      TEXT    NOT NULL,
    decision      TEXT    NOT NULL,
    enforced      TEXT,
    fail_mode     TEXT,
    agent_id      TEXT,
    agent_type    TEXT,
    kind          TEXT,
    could_not_judge TEXT,
    latency_ms    INTEGER,
    stages_run    INTEGER,
    recorded_at   REAL    NOT NULL
);
-- NOTE: deliberately no `subject` column. See FORBIDDEN_FINDING_FIELDS and the
-- module docstring. The absence is the guarantee.
CREATE TABLE IF NOT EXISTS findings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    verdict_id   INTEGER NOT NULL REFERENCES verdicts(id),
    category     TEXT    NOT NULL,
    severity     TEXT,
    action       TEXT,
    path         TEXT,
    start_offset INTEGER,
    end_offset   INTEGER,
    score        REAL,
    detector     TEXT,
    fp           TEXT,
    whitelisted  INTEGER
);
CREATE TABLE IF NOT EXISTS attributions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id      INTEGER NOT NULL REFERENCES findings(id),
    rail            TEXT    NOT NULL,
    source_repo     TEXT,
    display_name    TEXT,
    mechanism       TEXT,
    stage           INTEGER,
    confidence_kind TEXT,
    evidence        TEXT,
    capability      TEXT
);
CREATE TABLE IF NOT EXISTS modifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    verdict_id   INTEGER NOT NULL REFERENCES verdicts(id),
    path         TEXT    NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset   INTEGER NOT NULL,
    replacement  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS spans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    verdict_id INTEGER REFERENCES verdicts(id),
    event_id   TEXT,
    name       TEXT NOT NULL,
    parent     TEXT,
    started_at REAL NOT NULL,
    ended_at   REAL,
    attributes TEXT
);
CREATE INDEX IF NOT EXISTS idx_verdicts_event ON verdicts(event_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_time ON verdicts(recorded_at);
CREATE INDEX IF NOT EXISTS idx_findings_verdict ON findings(verdict_id);
CREATE INDEX IF NOT EXISTS idx_findings_category ON findings(category);
"""


@dataclass(frozen=True)
class SecurityEvent:
    """Safe Zone `internal/models/security_event.go:5-14`, field for field.

    This is the SIEM wire shape, kept separate from the SQLite row so a SIEM
    integration is a field mapping rather than a schema migration. `pattern` is
    the *rule name* that fired, never the text it matched.
    """

    type: str                 # BLOCK, MASK, ALLOW
    category: str             # AFNI Finding.category
    pattern: str              # detector / rail name
    confidence_score: float
    threshold: float
    action: str
    request_id: str
    timestamp: int

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "category": self.category,
                "pattern": self.pattern, "confidence_score": self.confidence_score,
                "threshold": self.threshold, "action": self.action,
                "request_id": self.request_id, "timestamp": self.timestamp}


@dataclass(frozen=True)
class RingEvent:
    """Safe Zone `internal/metrics/store.go:27-32`. What happened, not what it
    contained - so no payload, no subject, no matched value."""

    timestamp: float
    request_id: str
    blocked: bool
    reason: str
    findings: int = 0
    unjudged: int = 0


@dataclass
class Summary:
    """Safe Zone `internal/metrics/store.go:35-40`, plus the two counters this
    framework exists for: how often a decision was made without a full judgement,
    and how often the fail-closed rule actually fired."""

    total: int = 0
    allowed: int = 0
    blocked: int = 0
    with_findings: int = 0
    could_not_judge: int = 0
    fail_closed_blocks: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"total_requests": self.total, "allowed": self.allowed,
                "blocked": self.blocked, "with_findings": self.with_findings,
                "could_not_judge": self.could_not_judge,
                "fail_closed_blocks": self.fail_closed_blocks}


def fingerprint(value: str, length: int = 16) -> str:
    """The only representation of a matched value this module will store.

    Same construction the rails use for `Finding.fp` - a sha256 prefix - so a
    false-positive exception keyed on a fingerprint at detection time still
    matches the audit row.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


class VerdictStore:
    """Append-only SQLite record of every verdict, live or offline.

    `path=":memory:"` (the default) keeps it entirely in-process, which is what
    tests and a CI run want. A file path gives the durable evidence pack. The
    connection is opened lazily on first use, so importing this module touches no
    filesystem and opens no socket.
    """

    def __init__(self, path: str = ":memory:", *,
                 sink: Callable[[SecurityEvent], None] | None = None,
                 log_audit_lines: bool = True,
                 ring_size: int = RING_BUFFER_SIZE) -> None:
        self._path = path
        self._sink = sink
        self._log_audit_lines = log_audit_lines
        self._db: sqlite3.Connection | None = None
        self._ring: deque[RingEvent] = deque(maxlen=ring_size)
        self._summary = Summary()

    # ------------------------------------------------------------ connection --
    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            # Guardrails AI sqlite_trace_handler.py:57-63: isolation_level=None
            # for autocommit, WAL so a dashboard can read while the gateway
            # writes, check_same_thread=False because the gateway is threaded.
            # Upstream also sets `PRAGMA synchronous = OFF`; we do not - its own
            # comment concedes that trades away durability, and this table is the
            # evidence pack.
            db = sqlite3.connect(self._path, isolation_level=None,
                                 check_same_thread=False)
            try:
                db.execute("PRAGMA journal_mode = wal")
            except sqlite3.DatabaseError:
                # An in-memory database cannot use WAL. Not an error worth
                # failing a request over.
                pass
            db.executescript(_SCHEMA)
            self._db = db
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    # ---------------------------------------------------------------- record --
    def record(self, verdict: Verdict, *,
               event: GuardEvent | None = None,
               explanation: Explanation | None = None,
               attributions: dict[str, RailAttribution] | None = None,
               origin: str = ORIGIN_LIVE,
               enforced: str | None = None,
               fail_mode: str | None = None,
               stages_run: int | None = None,
               spans: Sequence["TraceRow"] = ()) -> int:
        """Persist one verdict and everything that explains it. Returns the row id.

        `enforced` and `fail_mode` come from `policy.PolicyOutcome`, so a record
        shows both what the cascade concluded and what the configured fail_mode
        enforced. A record that showed only the second would hide every policy
        override.
        """
        attributions = dict(attributions or {})
        if explanation is not None:
            for fe in explanation.findings:
                if fe.attribution is not None:
                    attributions.setdefault(fe.attribution.rail, fe.attribution)

        db = self.db
        now = time.time()
        cur = db.execute(
            "INSERT INTO verdicts (event_id, origin, provider, decision, enforced,"
            " fail_mode, agent_id, agent_type, kind,"
            " could_not_judge, latency_ms, stages_run, recorded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (verdict.event_id, origin, verdict.provider, verdict.decision.value,
             enforced, fail_mode,
             getattr(event, "agent_id", None), getattr(event, "agent_type", None),
             event.kind.value if event is not None else None,
             json.dumps(list(verdict.unjudged)) if verdict.unjudged else None,
             verdict.latency_ms,
             stages_run if stages_run is not None
             else (explanation.stages_run if explanation else None),
             now))
        verdict_id = int(cur.lastrowid)

        for finding in verdict.findings:
            self._insert_finding(db, verdict_id, finding, attributions)
        for span in verdict.modifications:
            self._insert_modification(db, verdict_id, span)
        for row in spans:
            self._insert_span(db, verdict_id, verdict.event_id, row)

        self._update_counters(verdict, event, enforced)
        self._emit(verdict, event, enforced, fail_mode)
        return verdict_id

    def _insert_finding(self, db: sqlite3.Connection, verdict_id: int,
                        finding: Finding, attributions: dict[str, RailAttribution]
                        ) -> int:
        # The column list is explicit and closed. `subject` is not in it, and
        # there is no column it could go into - see the schema comment.
        cur = db.execute(
            "INSERT INTO findings (verdict_id, category, severity, action, path,"
            " start_offset, end_offset, score, detector, fp, whitelisted)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (verdict_id, finding.category,
             finding.severity.value if finding.severity else None,
             finding.action.value if finding.action else None,
             finding.path, finding.start, finding.end, finding.score,
             finding.detector,
             # If a rail set `subject` but forgot `fp`, mint the fingerprint here
             # rather than storing nothing - the exception key must survive, the
             # value must not.
             finding.fp or (fingerprint(finding.subject) if finding.subject else None),
             None if finding.whitelisted is None else int(finding.whitelisted)))
        finding_id = int(cur.lastrowid)
        attr = attributions.get(finding.detector or "")
        if attr is not None:
            db.execute(
                "INSERT INTO attributions (finding_id, rail, source_repo,"
                " display_name, mechanism, stage, confidence_kind, evidence,"
                " capability) VALUES (?,?,?,?,?,?,?,?,?)",
                (finding_id, attr.rail, attr.source_repo, attr.display_name,
                 attr.mechanism, attr.stage, attr.confidence_kind, attr.evidence,
                 attr.capability))
        return finding_id

    @staticmethod
    def _insert_modification(db: sqlite3.Connection, verdict_id: int,
                             span: Span) -> None:
        # `replacement` is the placeholder that went in ("<US_SSN>"), never the
        # text that came out. Redaction spans are in the deck's audit-store list
        # precisely so a reviewer can see that masking happened.
        db.execute("INSERT INTO modifications (verdict_id, path, start_offset,"
                   " end_offset, replacement) VALUES (?,?,?,?,?)",
                   (verdict_id, span.path, span.start, span.end, span.replacement))

    @staticmethod
    def _insert_span(db: sqlite3.Connection, verdict_id: int | None,
                     event_id: str | None, row: "TraceRow") -> None:
        db.execute("INSERT INTO spans (verdict_id, event_id, name, parent,"
                   " started_at, ended_at, attributes) VALUES (?,?,?,?,?,?,?)",
                   (verdict_id, event_id, row.name, row.parent, row.started_at,
                    row.ended_at,
                    json.dumps(row.attributes, default=str) if row.attributes
                    else None))

    def record_span(self, row: "TraceRow", event_id: str | None = None) -> None:
        """Write one span with no verdict attached. This is what keeps the trace
        alive when opentelemetry is not installed - see `tracing.py`."""
        self._insert_span(self.db, None, event_id or row.event_id, row)

    # -------------------------------------------------------------- counters --
    def _update_counters(self, verdict: Verdict, event: GuardEvent | None,
                         enforced: str | None) -> None:
        decision = enforced or verdict.decision.value
        self._summary.total += 1
        if decision == "block":
            self._summary.blocked += 1
        else:
            self._summary.allowed += 1
        if verdict.findings:
            self._summary.with_findings += 1
        if verdict.unjudged:
            self._summary.could_not_judge += 1
            blocking = any(f.action and f.action.value == "block"
                           for f in verdict.findings)
            if decision == "block" and not blocking:
                # Blocked *only* because something could not be judged. This is
                # the counter that proves fail-closed is doing work rather than
                # being a setting nobody exercises.
                self._summary.fail_closed_blocks += 1
        reason = ("UNJUDGED" if verdict.unjudged
                  else (verdict.findings[0].category if verdict.findings else "CLEAN"))
        self._ring.append(RingEvent(
            timestamp=time.time(), request_id=verdict.event_id,
            blocked=decision == "block", reason=reason,
            findings=len(verdict.findings), unjudged=len(verdict.unjudged)))

    def _emit(self, verdict: Verdict, event: GuardEvent | None,
              enforced: str | None, fail_mode: str | None) -> None:
        decision = enforced or verdict.decision.value
        if self._log_audit_lines:
            # Safe Zone's `[AUDIT]` line. Categories and counts only.
            LOGGER.info(
                "[AUDIT] event=%s decision=%s fail_mode=%s findings=%s "
                "categories=%s unjudged=%s",
                verdict.event_id, decision,
                fail_mode, len(verdict.findings),
                ",".join(sorted({f.category for f in verdict.findings})) or "-",
                ",".join(verdict.unjudged) or "-")
        if self._sink is None:
            return  # siem.go:18-20 - unset endpoint means disabled, not an error.
        top = verdict.findings[0] if verdict.findings else None
        try:
            self._sink(SecurityEvent(
                type=decision.upper(),
                category=top.category if top else "none",
                pattern=(top.detector if top and top.detector else "gateway"),
                confidence_score=(top.score if top and top.score is not None else 0.0),
                threshold=0.0,
                action=(top.action.value if top and top.action else decision),
                request_id=verdict.event_id,
                timestamp=int(time.time())))
        except Exception as exc:  # noqa: BLE001
            # siem.go:34-37 logs and returns. A SIEM outage must never fail a
            # request, but it must never be silent either.
            LOGGER.warning("[AUDIT] sink delivery failed: %s: %s",
                           type(exc).__name__, exc)

    # ----------------------------------------------------------------- reads --
    @property
    def summary(self) -> Summary:
        return self._summary

    @property
    def recent(self) -> list[RingEvent]:
        """The dashboard's last-N view. Newest last, as in store.go:69."""
        return list(self._ring)

    def history(self, event_id: str) -> list[dict[str, Any]]:
        """Guardrails AI's `Guard.history` equivalent: every verdict recorded for
        one event id, each with its findings and their attributions, oldest
        first. This is the per-call tree a reviewer asks for when a single
        request is disputed."""
        db = self.db
        out: list[dict[str, Any]] = []
        for row in db.execute(
                "SELECT id, origin, decision, enforced, fail_mode, could_not_judge,"
                " latency_ms, stages_run, recorded_at FROM verdicts"
                " WHERE event_id = ? ORDER BY id", (event_id,)).fetchall():
            vid = row[0]
            findings = []
            for f in db.execute(
                    "SELECT id, category, severity, action, path, start_offset,"
                    " end_offset, score, detector, fp FROM findings"
                    " WHERE verdict_id = ? ORDER BY id", (vid,)).fetchall():
                attr = db.execute(
                    "SELECT rail, source_repo, display_name, mechanism, stage,"
                    " confidence_kind, evidence, capability FROM attributions"
                    " WHERE finding_id = ?", (f[0],)).fetchone()
                findings.append({
                    "category": f[1], "severity": f[2], "action": f[3],
                    "path": f[4], "start": f[5], "end": f[6], "score": f[7],
                    "detector": f[8], "fp": f[9],
                    "attribution": None if attr is None else {
                        "rail": attr[0], "source_repo": attr[1],
                        "display_name": attr[2], "mechanism": attr[3],
                        "stage": attr[4], "confidence_kind": attr[5],
                        "evidence": attr[6], "capability": attr[7]},
                })
            out.append({
                "verdict_id": vid, "origin": row[1], "decision": row[2],
                "enforced": row[3], "fail_mode": row[4],
                "could_not_judge": json.loads(row[5]) if row[5] else [],
                "latency_ms": row[6], "stages_run": row[7], "recorded_at": row[8],
                "findings": findings,
            })
        return out

    def count(self, table: str = "verdicts") -> int:
        if table not in ("verdicts", "findings", "attributions", "modifications",
                         "spans"):
            raise KeyError(f"unknown audit table {table!r}")
        return int(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def category_counts(self, origin: str | None = None) -> dict[str, int]:
        """Finding counts by category - the input the compliance mapper turns
        into a framework report."""
        sql = ("SELECT f.category, COUNT(*) FROM findings f"
               " JOIN verdicts v ON v.id = f.verdict_id")
        args: tuple[Any, ...] = ()
        if origin is not None:
            sql += " WHERE v.origin = ?"
            args = (origin,)
        sql += " GROUP BY f.category ORDER BY 2 DESC"
        return {row[0]: int(row[1]) for row in self.db.execute(sql, args).fetchall()}

    def all_values(self) -> list[str]:
        """Every text value in every table, as strings.

        Exists for one reason: the test that proves no subject value ever reaches
        the database can scan the whole store instead of trusting a column list.
        """
        out: list[str] = []
        for (table,) in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            cur = self.db.execute(f"SELECT * FROM {table}")
            for row in cur.fetchall():
                out.extend(str(v) for v in row if v is not None)
        return out

    def render(self) -> str:
        s = self._summary
        lines = ["AFNI audit store", f"  path      : {self._path}",
                 f"  verdicts  : {self.count('verdicts')}",
                 f"  findings  : {self.count('findings')}"
                 f"  (attributed {self.count('attributions')})",
                 f"  spans     : {self.count('spans')}",
                 f"  requests  : {s.total} = {s.allowed} allowed / {s.blocked} blocked",
                 f"  could not judge : {s.could_not_judge}"
                 f"  (fail-closed blocks {s.fail_closed_blocks})"]
        if s.could_not_judge:
            lines.append("  ^ a request counted here was decided without a full "
                         "judgement; that is the number to drive to zero")
        return "\n".join(lines)


@dataclass
class TraceRow:
    """One span, in the shape the audit store persists.

    Defined here rather than in `tracing.py` so the store has no dependency on
    the tracer: spans survive whether or not opentelemetry is installed.
    """

    name: str
    started_at: float
    ended_at: float | None = None
    parent: str | None = None
    event_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at) * 1000.0


def scan_for_leak(store: VerdictStore, secrets: Iterable[str]) -> list[str]:
    """Return any secret that can be found anywhere in the store.

    A helper, not a test - a gateway can run it against its own audit DB as a
    self-check before handing the evidence pack to a client reviewer.
    """
    values = store.all_values()
    blob = "\n".join(values)
    return [s for s in secrets if s and s in blob]
