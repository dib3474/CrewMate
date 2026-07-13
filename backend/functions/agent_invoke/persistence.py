"""Persistence for validated Agent recommendations (담당자 B, task 5.2).

This module stores a validated :class:`~agent.schemas.Recommendation` as a
``Crew(status=PROPOSED, source=AGENT)`` via 담당자 A's ``backend/shared/db`` helper.
It deliberately keeps the **NORMAL** and **EMERGENCY** save flows on separate,
explicit code paths so that only the NORMAL path ever transitions the associated
WorkRequest.

Why the flows are split (design.md → "저장 흐름 분리", tasks.md Overview)
----------------------------------------------------------------------
- **NORMAL** : save the Crew, THEN transition the WorkRequest ``COMPOSING → PROPOSED``
  (Req 8.1, 8.2). The invoke handler already acquired the lock at entry
  (``REQUESTED → COMPOSING``), so this terminal transition closes the compose flow.
- **EMERGENCY** : save the Crew ONLY (Req 8.1). It must NOT touch the WorkRequest
  state machine — during an emergency re-composition the original WorkRequest may
  already be ``RUNNING``, and rewinding/altering it would corrupt a live assignment.
  It must NOT transition the GapEvent either: the GapEvent terminal transition
  (``RECOMPOSING → PROPOSED`` / ``FAILED``) is owned by the *path owner's*
  orchestration (the trusted-internal gap_event Lambda, or the external
  ``agent-recompose`` compose_flow), never by this save function.

Safety invariant (underpins Property 9, tested in task 5.4)
-----------------------------------------------------------
Neither function performs any worker state change, approval, or assignment — those
are delegated to 담당자 A's approval API. The only side effects here are
``save_crew`` (both flows) and, for NORMAL only, ``transition_request_status``.

shared helper consumption (design.md → "소비하는 shared 계약")
------------------------------------------------------------
``backend/shared/*`` is 담당자 A's and is **consumed, never implemented**. It does
not exist on disk in this scope (see ``tests/test_scaffolding.py``); tests install
in-memory stubs under ``backend.shared.*`` via ``install_shared_stubs(monkeypatch)``.
The ``db`` module is therefore imported **lazily inside each function** so it resolves
at call time (the real Layer module in deployment, the installed stub during tests)
regardless of import order.

Python 3.9 note
---------------
``from __future__ import annotations`` keeps annotations lazy so the design's
builtin-generic / ``Literal`` annotation style resolves cleanly on Python 3.9.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from agent.schemas import Recommendation

__all__ = [
    "SaveContext",
    "save_normal_proposal",
    "save_emergency_proposal",
    "save_proposal",
]

# --------------------------------------------------------------------------- #
# Contract constants — mirror backend.shared.state values                      #
# (CrewStatus.PROPOSED / Source.AGENT / RequestStatus.COMPOSING|PROPOSED).      #
# Declared locally so this module stays importable standalone (the real        #
# state module is 담당자 A's and absent on disk here). Values are fixed by the  #
# shared contract glossary in requirements.md and verified against             #
# tests/mocks/shared_stubs.py.                                                  #
# --------------------------------------------------------------------------- #
MODE_NORMAL = "NORMAL"
MODE_EMERGENCY = "EMERGENCY"

_CREW_PROPOSED = "PROPOSED"  # CrewStatus.PROPOSED
_SOURCE_AGENT = "AGENT"  # Source.AGENT
_REQ_COMPOSING = "COMPOSING"  # RequestStatus.COMPOSING (expected state at save time)
_REQ_PROPOSED = "PROPOSED"  # RequestStatus.PROPOSED (target after NORMAL save)


@dataclass(frozen=True)
class SaveContext:
    """Minimal, immutable context needed to build and persist a proposed Crew.

    Built by the invoke handler (task 5.3) after validation passes and passed to the
    matching save function. Kept intentionally small: only what a Crew item needs plus
    the EMERGENCY linkage fields.

    Attributes
    ----------
    mode:
        ``"NORMAL"`` or ``"EMERGENCY"`` — selects the save flow. Only NORMAL transitions
        the WorkRequest.
    request_id:
        The associated WorkRequest id (stored on the Crew; used as the transition key in
        the NORMAL flow).
    office_id:
        Owning office (linkage; enables office-scoped queries). Optional.
    work_date:
        Work date for the composed crew (linkage). Optional.
    current_crew_id:
        EMERGENCY only — the Crew being re-composed/superseded. Optional.
    gap_event_id:
        EMERGENCY only — the originating GapEvent. Optional.
    source:
        Provenance marker; always ``AGENT`` in this scope.
    crew_id:
        Explicit Crew id. When ``None`` the db helper assigns one and returns it.
    """

    mode: Literal["NORMAL", "EMERGENCY"]
    request_id: str
    office_id: Optional[str] = None
    work_date: Optional[str] = None
    current_crew_id: Optional[str] = None
    gap_event_id: Optional[str] = None
    source: str = _SOURCE_AGENT
    crew_id: Optional[str] = None


def _build_crew_item(recommendation: Recommendation, ctx: SaveContext) -> Dict[str, Any]:
    """Assemble the ``Crew(status=PROPOSED, source=AGENT)`` item for ``save_crew``.

    Faithfully persists the recommendation (members, cost, rank, rationale) plus the
    request/office/work_date linkage. EMERGENCY linkage fields (``gap_event_id``,
    ``current_crew_id``) are included only when provided. ``crew_id`` is omitted when
    unset so the db helper can assign one. The exact Crew table schema is 담당자 A's;
    these field names follow the shared-contract concepts in design.md.
    """
    item: Dict[str, Any] = {
        "status": _CREW_PROPOSED,
        "source": ctx.source,
        "request_id": ctx.request_id,
        "rank": recommendation.rank,
        "member_ids": list(recommendation.member_ids),
        "total_cost": recommendation.total_cost,
        "reason": recommendation.reason,
        "considerations": list(recommendation.considerations),
    }
    if ctx.crew_id is not None:
        item["crew_id"] = ctx.crew_id
    if ctx.office_id is not None:
        item["office_id"] = ctx.office_id
    if ctx.work_date is not None:
        item["work_date"] = ctx.work_date
    # EMERGENCY linkage — present only when the caller supplied it.
    if ctx.gap_event_id is not None:
        item["gap_event_id"] = ctx.gap_event_id
    if ctx.current_crew_id is not None:
        item["current_crew_id"] = ctx.current_crew_id
    return item


def save_normal_proposal(recommendation: Recommendation, ctx: SaveContext) -> str:
    """NORMAL: save the Crew, THEN transition the WorkRequest ``COMPOSING → PROPOSED``.

    Order matters (Req 8.1 then 8.2): the Crew is persisted first, then the WorkRequest
    is advanced. The expected state is ``COMPOSING`` because the handler moved the
    request ``REQUESTED → COMPOSING`` at entry and holds that lock throughout the
    compose flow, so this terminal transition is expected to succeed.

    Returns the ``crew_id`` (assigned by the db helper when ``ctx.crew_id`` is unset).
    Performs no worker state change, approval, or assignment (delegated to 담당자 A).
    """
    from backend.shared import db  # lazy: real Layer in prod, installed stub in tests

    crew_item = _build_crew_item(recommendation, ctx)
    crew_id = db.save_crew(crew_item)
    db.transition_request_status(ctx.request_id, _REQ_COMPOSING, _REQ_PROPOSED)
    return crew_id


def save_emergency_proposal(recommendation: Recommendation, ctx: SaveContext) -> str:
    """EMERGENCY: save the Crew ONLY. Never transition WorkRequest or GapEvent.

    During emergency re-composition the original WorkRequest may already be ``RUNNING``;
    this path must not rewind or alter the WorkRequest state machine. The GapEvent
    terminal transition (``RECOMPOSING → PROPOSED`` / ``FAILED``) is owned by the path
    owner's orchestration (trusted-internal gap_event Lambda per Req 10.7, or the
    external ``agent-recompose`` compose_flow), not by this save function.

    Returns the ``crew_id`` (assigned by the db helper when ``ctx.crew_id`` is unset).
    Performs no worker state change, approval, or assignment (delegated to 담당자 A).
    """
    from backend.shared import db  # lazy: real Layer in prod, installed stub in tests

    crew_item = _build_crew_item(recommendation, ctx)
    crew_id = db.save_crew(crew_item)
    # Intentionally no WorkRequest transition and no GapEvent transition here.
    return crew_id


def save_proposal(recommendation: Recommendation, ctx: SaveContext) -> str:
    """Dispatch to the mode-specific save flow (design.md ``save_proposal``).

    A single, explicit branch point so that ONLY NORMAL can ever transition the
    WorkRequest. An unknown mode raises rather than silently falling through to a
    state-mutating path (defensive: a malformed mode must never trigger a transition).
    """
    if ctx.mode == MODE_NORMAL:
        return save_normal_proposal(recommendation, ctx)
    if ctx.mode == MODE_EMERGENCY:
        return save_emergency_proposal(recommendation, ctx)
    raise ValueError(f"unknown SaveContext.mode: {ctx.mode!r}")
