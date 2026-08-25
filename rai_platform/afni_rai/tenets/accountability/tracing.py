# -*- coding: utf-8 -*-
"""
OpenTelemetry tracing that survives opentelemetry not being installed.

THE UPSTREAM PATTERN, AND THE ONE THING CHANGED

NeMo Guardrails has the span adapter this is modelled on -
`references/Guardrails-develop/nemoguardrails/tracing/adapters/opentelemetry.py`:

  :62-70   `try: from opentelemetry import trace ... except ImportError: raise
           ImportError("OpenTelemetry API is not installed...")`
  :75-83   uses only the OpenTelemetry **API**, never the SDK, and does not touch
           global state - the application configures the provider
  :103-112 warns when `trace.get_tracer_provider()` returns a
           `NoOpTracerProvider`, because traces would silently go nowhere
  :120-137 `transform()` walks `interaction_log.trace`, resolving each span's
           parent through `trace.set_span_in_context`

Two of those are exactly right and are kept: API-only, and warn loudly when there
is no real provider. Upstream's `raise ImportError` is not, for a gateway. In
NeMo the adapter is opt-in config, so raising is a correct configuration error.
Here, tracing is on the audit path - and losing the audit trail because an
observability dependency is missing is a worse outcome than exporting nothing.

So the import is guarded and lazy, and when it fails the recorder degrades to a
no-op *exporter* while still recording every span into the verdict store. The
trail survives the dependency; only the OTLP export is lost, and
`degraded_reason` says so in one sentence an operator can act on.

Nothing here imports opentelemetry at module import time, and nothing here makes
a network call - configuring an exporter is the application's job, which is
upstream's own stated best practice (:19-22).

Zero third-party dependencies required.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from .audit import TraceRow, VerdictStore

LOGGER = logging.getLogger("afni_rai.tracing")

SERVICE_NAME = "afni-rai-gateway"
# NeMo passes `schema_url="https://opentelemetry.io/schemas/1.26.0"` at
# opentelemetry.py:117. Same schema, so spans from both are comparable in one
# backend.
SCHEMA_URL = "https://opentelemetry.io/schemas/1.26.0"


class SpanRecorder:
    """Records spans locally, and exports them via OpenTelemetry when it is there.

    Usage is the same either way:

        with recorder.span("stage-1", stage=1, rails=6) as span:
            span["findings"] = 2

    On exit the span is appended to `spans` and, if a store was supplied, written
    to the `spans` table. `flush(event_id)` persists a batch after a verdict has
    been recorded so the spans carry the event id.
    """

    def __init__(self, service_name: str = SERVICE_NAME,
                 store: VerdictStore | None = None,
                 enable_otel: bool = True) -> None:
        self._service_name = service_name
        self._store = store
        self._enable_otel = enable_otel
        self._rows: list[TraceRow] = []
        self._stack: list[str] = []
        self._tracer: Any = None
        self._probed = False
        self._degraded_reason: str | None = None

    # ------------------------------------------------------------ the import --
    def _probe(self) -> None:
        """Guarded, lazy, once. Never at module import.

        Sets `_tracer` on success and `_degraded_reason` on any failure. Catches
        `Exception`, not just `ImportError`: a partially installed
        opentelemetry, or a provider that raises while being fetched, must
        degrade exactly like an absent one rather than taking down the request.
        """
        if self._probed:
            return
        self._probed = True
        if not self._enable_otel:
            self._degraded_reason = "OpenTelemetry export disabled by configuration"
            return
        try:
            from opentelemetry import trace  # noqa: PLC0415 - deliberately lazy
            from opentelemetry.trace import NoOpTracerProvider
        except Exception as exc:  # noqa: BLE001
            # NeMo raises here (opentelemetry.py:66-70). We do not: the local
            # trail is the part that matters, and it still works.
            self._degraded_reason = (
                f"opentelemetry-api not importable ({type(exc).__name__}); spans "
                "are still recorded to the audit store, but nothing is exported. "
                "Install opentelemetry-api and configure a TracerProvider to "
                "export.")
            return
        try:
            provider = trace.get_tracer_provider()
            if provider is None or isinstance(provider, NoOpTracerProvider):
                # NeMo's warning at opentelemetry.py:103-112. Worth repeating:
                # a NoOpTracerProvider means every span is silently discarded,
                # which looks identical to working tracing from the inside.
                self._degraded_reason = (
                    "no OpenTelemetry TracerProvider is configured, so spans "
                    "would not be exported; recording locally instead")
                LOGGER.warning("[TRACE] %s", self._degraded_reason)
                return
            self._tracer = trace.get_tracer(self._service_name,
                                            schema_url=SCHEMA_URL)
        except Exception as exc:  # noqa: BLE001
            self._degraded_reason = (
                f"OpenTelemetry present but unusable ({type(exc).__name__}: {exc}); "
                "recording locally instead")
            LOGGER.warning("[TRACE] %s", self._degraded_reason)

    @property
    def available(self) -> bool:
        """True only when spans are genuinely being exported. Never guessed from
        whether the import succeeded - an importable opentelemetry with a
        NoOpTracerProvider exports nothing, and reporting that as available is
        how an observability gap goes unnoticed."""
        self._probe()
        return self._tracer is not None

    @property
    def degraded_reason(self) -> str | None:
        self._probe()
        return self._degraded_reason

    # -------------------------------------------------------------- recording --
    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[dict[str, Any]]:
        """Record one span. Attributes can be added inside the block.

        The local row is written whether or not the export succeeds, and an
        exception inside the block still closes the span and records
        `error=True` - a span that vanishes because the work it measured failed
        is the least useful possible outcome.
        """
        self._probe()
        parent = self._stack[-1] if self._stack else None
        attrs: dict[str, Any] = dict(attributes)
        started = time.time()
        self._stack.append(name)
        otel_span = None
        cm = None
        if self._tracer is not None:
            try:
                cm = self._tracer.start_as_current_span(name)
                otel_span = cm.__enter__()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("[TRACE] span %r not exported: %s", name, exc)
                cm = None
        try:
            yield attrs
        except Exception:
            attrs["error"] = True
            raise
        finally:
            self._stack.pop()
            ended = time.time()
            row = TraceRow(name=name, started_at=started, ended_at=ended,
                           parent=parent, attributes=attrs)
            self._rows.append(row)
            if otel_span is not None:
                try:
                    for key, value in attrs.items():
                        otel_span.set_attribute(key, value)
                except Exception:  # noqa: BLE001 - export must never fail a request
                    pass
            if cm is not None:
                try:
                    cm.__exit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
            if self._store is not None:
                self._store.record_span(row)

    @property
    def spans(self) -> list[TraceRow]:
        return list(self._rows)

    def clear(self) -> None:
        self._rows.clear()
        self._stack.clear()

    def flush(self, event_id: str, store: VerdictStore | None = None) -> int:
        """Write the recorded spans against an event id and reset.

        Returns how many rows were written. Used when the spans were collected
        before the verdict existed, which is the normal order: the cascade runs,
        then the verdict is recorded, then the spans are attached to it.
        """
        target = store or self._store
        if target is None:
            self.clear()
            return 0
        written = 0
        for row in self._rows:
            target.record_span(TraceRow(
                name=row.name, started_at=row.started_at, ended_at=row.ended_at,
                parent=row.parent, event_id=event_id, attributes=row.attributes),
                event_id)
            written += 1
        self.clear()
        return written

    def render(self) -> str:
        head = ("OpenTelemetry export ACTIVE" if self.available
                else f"OpenTelemetry export DEGRADED: {self.degraded_reason}")
        lines = [head, f"  spans recorded locally: {len(self._rows)}"]
        for row in self._rows:
            ms = row.duration_ms
            lines.append(f"    {row.name:28s} {'-' if ms is None else f'{ms:8.2f}ms'}"
                         f"  parent={row.parent or '-'}")
        return "\n".join(lines)
