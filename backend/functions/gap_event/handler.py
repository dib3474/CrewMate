"""Lambda handler for the gap_event function (담당자 B, task 8.5).

This is the entry point a gap registration (a worker going NO_SHOW / LEFT_SITE /
UNAVAILABLE mid-job) flows through. It captures the gap, computes the retained team and
the shortage, and drives an EMERGENCY re-composition by invoking the agent_invoke Lambda
through a **trusted internal invoke**, then owns the GapEvent's terminal transition
(``RECOMPOSING → PROPOSED`` / ``FAILED``) on that internal path.

Design references
-----------------
- ``design.md`` → "Components and Interfaces" → "6. Gap Event Lambda", the EMERGENCY
  sequence diagram, "5. 상태 가드 & 동시성 제어", and "7. 권한".
- ``requirements.md`` → Req 10.1/10.2/10.6/10.7/10.8/10.9/10.11 (gap capture + emergency
  recomposition), 11.3 (both COMPANY and OFFICE may register a gap).
- ``tasks.md`` → task 8.5 and the Notes on trusted internal-invoke / IAM, the EMERGENCY
  state-guard branching, and terminal-transition ownership.

End-to-end flow (order matters — mirrors the design's EMERGENCY sequence)
-------------------------------------------------------------------------
1. **Authenticate** the registrant with ``shared/auth.require_role(event, [COMPANY,
   OFFICE])`` — BOTH roles may register a gap (Req 11.3). A forbidden role maps to
   ``FORBIDDEN``.
2. **Save the GapEvent as DETECTED FIRST** (``save_gap_event``), before looking anything
   else up, so the event is retrievable through the office polling query path within the
   ~5s polling cycle **even if the recomposition later fails** (Req 10.1). The saved item
   carries the office-query-path fields: ``office_id`` + ``status=DETECTED`` (plus
   ``type`` / ``crew_id`` / ``departed_ids``). See "Office query path" below.
3. **Look up the affected Crew** (``get_crew``); a missing/invalid crew → ``CREW_INVALID``
   (Req 10.2, 10.11). The DETECTED event stays saved (retrievable), matching the design.
4. **Compute** the retained team and the shortage with the pure ``gap_logic`` functions:
   ``compute_fixed_members(active, departed)`` (Req 10.3/10.4) and
   ``compute_missing(required, fixed)`` (Req 10.5). No worker state is ever modified.
5. **Assemble the EMERGENCY payload** by reusing the same shared logic the external
   ``agent-recompose`` route uses (so both paths are byte-for-byte consistent): the
   ``assembler.assemble_normal_input`` gives the FULL :class:`RequestSpec`, the
   office-scoped READY candidate pool, and the collaboration pairs; the candidate pool is
   narrowed to the trades with a positive shortage; then ``build_emergency_payload``
   (task 8.4) builds the ``mode=EMERGENCY`` :class:`AgentInput` (Req 10.6).
6. **Acquire the lock BEFORE invoking** — ``transition_gap_event_status(DETECTED →
   RECOMPOSING)`` (Req 10.6). A failed conditional transition (duplicate / wrong state) →
   ``STATE_CONFLICT``. Locking first is what lets the internal agent_invoke path accept an
   already-``RECOMPOSING`` GapEvent as its expected state instead of dead-locking on the
   lock it would otherwise try to acquire itself.
7. **Trusted internal invoke** of agent_invoke (synchronous) with the EMERGENCY payload.
8. **Own the terminal transition** on this internal path: on save success gap_event moves
   ``RECOMPOSING → PROPOSED`` (Req 10.7); on retry-exhausted failure gap_event moves
   ``RECOMPOSING → FAILED`` and returns manual-composition guidance (Req 10.9). The
   remaining team members keep their RUNNING state throughout — this handler never
   changes any worker state (Req 10.8).

Trusted internal invoke — the contract and the IAM trust boundary
-----------------------------------------------------------------
gap_event invokes agent_invoke SYNCHRONOUSLY. In deployment this is an AWS Lambda invoke
(``boto3 lambda.invoke``, ``RequestResponse``); locally / in tests it is a direct call to
agent_invoke's handler with the same payload. That call is isolated behind the module-level
:func:`invoke_agent` seam so production uses boto3 while tests monkeypatch it (to call
agent_invoke directly, or to stub a response) — no live AWS needed to exercise the flow.

The payload gap_event produces MUST match the contract agent_invoke defines
(``agent_invoke/handler.py``: ``INTERNAL_INVOKE_MARKER`` + ``_handle_internal``). It is a
plain, JSON-serializable dict::

    {
        "internal_invoke": true,                  # routing marker (trust is IAM-enforced)
        "mode": "EMERGENCY",                       # always EMERGENCY on this path
        "event_id": "<GapEvent id>",               # the GapEvent gap_event already locked
        "agent_input": { ...AgentInput.model_dump()... },  # the EMERGENCY payload
        "office_id": "<office id>",                # optional Crew linkage
        "current_crew_id": "<crew being recomposed>"       # optional Crew linkage
    }

The keys mirror ``agent_invoke``'s ``INTERNAL_INVOKE_MARKER`` / ``_PAYLOAD_*`` constants;
they are declared locally here (rather than importing ``agent_invoke.handler``, which would
pull in the Agent/Bedrock stack at import time) with this docstring as the alignment
contract. agent_invoke re-parses ``agent_input`` with ``AgentInput.model_validate``.

Crucially, the ``internal_invoke`` marker is ONLY a routing hint — a payload flag is
spoofable and can never be the security control. The real trust boundary is **IAM**: only
gap_event's Lambda execution role is granted permission to invoke agent_invoke directly, so
agent_invoke can trust the internal path without re-applying its OFFICE-only external gate.
That IAM policy is 담당자 A's infrastructure scope; this handler documents and relies on it.

Registrant role vs. the internal path (Req 11.3)
------------------------------------------------
gap_event authenticates the registrant as COMPANY **or** OFFICE and then invokes
agent_invoke. It does NOT require the registrant to be OFFICE: agent_invoke's OFFICE-only
gate applies to its *external* API Gateway routes, not to this trusted internal invoke, so a
COMPANY-registered gap flows through to recomposition without a FORBIDDEN. (agent_invoke's
``_handle_internal`` deliberately skips the OFFICE gate for exactly this reason.)

Terminal-transition ownership — internal path only
--------------------------------------------------
On THIS gap_event-driven internal invoke path, gap_event owns the GapEvent terminal
transition and agent_invoke does not touch the GapEvent (its internal path passes
``_PATH_INTERNAL`` so ``compose_flow`` skips the transition). The symmetric external/direct
``agent-recompose`` path is the opposite — there agent_invoke acquires the lock and owns the
terminal transition, and gap_event is not involved at all. This handler only implements the
internal path.

Observability logging (task 9.2, Req 12.1/12.2)
-----------------------------------------------
Both Lambdas write a structured CloudWatch log (design component diagram). After the
internal invoke, gap_event emits its OWN PII-free ``AgentLogRecord`` (:func:`_log_gap_execution`)
capturing the emergency from ITS vantage point: ``agent_mode=EMERGENCY``, ``request_id`` =
the GapEvent ``event_id`` (gap_event's correlation key), the assembled candidate count, and
``recommendation_count`` / ``saved`` / ``validation_passed`` sourced from agent_invoke's
response. agent_invoke separately logs the compose execution it ran (keyed on the work
``request_id``), so the two records describe the same emergency from the two Lambdas'
vantage points and are distinguishable by their id fields — not double-counted. gap_event
does not observe agent_invoke's internal retry / fallback, so those flags stay false in
gap_event's record. The record is emitted exactly once, only after the Agent actually ran
(the pre-invoke FORBIDDEN / CREW_INVALID / STATE_CONFLICT guards short-circuit with no
execution record), and a logging failure can never alter the flow (it is swallowed).

Office query path (Req 10.1)
----------------------------
The DETECTED item is saved with ``office_id`` and ``status`` so 담당자 A's office polling
query (a status-scoped, office-keyed GSI) can return it within the polling cycle.
``office_id`` is derived from the authenticated identity (the OFFICE linkage 담당자 A's auth
attaches to the claim), which is available *before* the crew lookup; the crew's ``office_id``
is used as a fallback for the downstream candidate assembly. The DynamoDB table / GSI itself
is 담당자 A's scope — this handler only *includes the fields* and consumes ``save_gap_event``.

Responsibility boundary (B's GapEvent scope is PROPOSED-only)
-------------------------------------------------------------
This scope transitions the GapEvent only as far as ``PROPOSED`` (or ``FAILED``). The
``APPROVED`` / ``FILLED`` transitions, the replacement workers' ``READY → RESERVED →
RUNNING`` assignment, and marking the departed worker ``INACTIVE`` are 담당자 A's emergency
approval API (``/office/emergency/{eventId}/approve``) and are NOT implemented here.

shared helper consumption
-------------------------
``backend/shared/*`` is 담당자 A's and is consumed, never implemented (absent on disk here).
``db`` / ``auth`` / ``response`` are imported LAZILY inside functions so they resolve at call
time — the real Layer in deployment, or the stubs installed under ``backend.shared.*`` in
tests. This handler performs no worker-state change, approval, or assignment (Req 10.8).

Python 3.9 note
---------------
``from __future__ import annotations`` keeps annotations lazy so the builtin-generic style
resolves on the local Python 3.9 runtime; ``Optional[...]`` / ``Literal[...]`` are used for
nullable / enumerated fields (no PEP 604 unions in the Pydantic model).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from agent.schemas import AgentInput
from backend.functions.agent_invoke.assembler import assemble_normal_input
from backend.functions.agent_invoke.observability import (
    build_agent_log_record,
    log_agent_execution,
    new_execution_id,
)
from backend.functions.gap_event.emergency_payload import build_emergency_payload
from backend.functions.gap_event.gap_logic import (
    Member,
    compute_fixed_members,
    compute_missing,
)

# Module logger — plain, propagating logger used only for the defensive "structured log emit
# failed" line (below). The full per-execution structured record is emitted via
# ``log_agent_execution`` on observability.py's dedicated logger, exactly as agent_invoke does.
_logger = logging.getLogger(__name__)

__all__ = [
    "handler",
    "invoke_agent",
    "GapEventInput",
]

# --------------------------------------------------------------------------- #
# Modes                                                                        #
# --------------------------------------------------------------------------- #
_MODE_EMERGENCY = "EMERGENCY"

# --------------------------------------------------------------------------- #
# State constants — mirror backend.shared.state (GapStatus). Declared locally  #
# (like agent_invoke/handler.py and persistence.py) so this module stays       #
# importable standalone; values are fixed by the shared-contract glossary in   #
# requirements.md and verified against tests/mocks/shared_stubs.py.            #
# --------------------------------------------------------------------------- #
_GAP_DETECTED = "DETECTED"  # GapStatus.DETECTED (saved first; office-query-path visible)
_GAP_RECOMPOSING = "RECOMPOSING"  # GapStatus.RECOMPOSING (lock acquired before invoke)
_GAP_PROPOSED = "PROPOSED"  # GapStatus.PROPOSED (terminal transition on save success)
_GAP_FAILED = "FAILED"  # GapStatus.FAILED (terminal transition on retry-exhausted failure)

# Roles allowed to register a gap event (Req 11.3): COMPANY and OFFICE both.
_ROLE_COMPANY = "COMPANY"
_ROLE_OFFICE = "OFFICE"

# Coercion defaults for 담당자 A's Crew-member records (mirror agent_invoke/handler.py's
# non-safety-critical fallbacks). Fixed-member wages here are only Agent hints; the
# validator recomputes total_cost from the freshest get_workers snapshot.
_RUNNING = "RUNNING"
_DEFAULT_TRADE = "GENERAL"
_DEFAULT_WAGE = 1  # smallest positive wage (schema constrains > 0); malformed record only

# --------------------------------------------------------------------------- #
# Error codes — fixed by the shared contract (PRD_A_BACKEND.md 1.6 / design.md  #
# Error Handling). No new codes are invented.                                  #
# --------------------------------------------------------------------------- #
_ERR_STATE_CONFLICT = "STATE_CONFLICT"
_ERR_CREW_INVALID = "CREW_INVALID"
_ERR_FORBIDDEN = "FORBIDDEN"
_ERR_AGENT_RETRY_FAILED = "AGENT_RETRY_FAILED"

# --------------------------------------------------------------------------- #
# Internal-invoke payload contract keys — MUST match agent_invoke/handler.py    #
# (INTERNAL_INVOKE_MARKER + _PAYLOAD_* constants). See the module docstring.    #
# --------------------------------------------------------------------------- #
_PAYLOAD_INTERNAL_MARKER = "internal_invoke"
_PAYLOAD_MODE = "mode"
_PAYLOAD_EVENT_ID = "event_id"
_PAYLOAD_AGENT_INPUT = "agent_input"
_PAYLOAD_OFFICE_ID = "office_id"
_PAYLOAD_CURRENT_CREW_ID = "current_crew_id"

# Target agent_invoke function for the production boto3 invoke (env-overridable).
_AGENT_INVOKE_FUNCTION_ENV = "AGENT_INVOKE_FUNCTION_NAME"
_DEFAULT_AGENT_INVOKE_FUNCTION = "agent_invoke"

# Manual-composition guidance appended when an emergency recomposition fails (Req 10.9).
_MANUAL_GUIDANCE = "자동 긴급 재편성에 실패했습니다. 수동으로 작업조를 편성해 주세요."


class _FlowError(Exception):
    """Internal control-flow signal carrying a shared error ``code`` + ``message``.

    Raised in auth / gap-lookup / state-guard to short-circuit to a single
    ``response.error(code, message)`` at the top-level handler boundary. Not public — the
    handler always converts it to a shared response.
    """

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# Gap registration input (design.md → "Data Models" → "GapEvent 처리 모델")      #
# --------------------------------------------------------------------------- #
class GapEventInput(BaseModel):
    """The gap registration payload: which crew lost whom, and why.

    ``crew_id`` identifies the affected Crew, ``type`` is the gap kind, and
    ``departed_ids`` lists the workers who went missing (empty-tolerant so a
    slightly lean body still parses; a real gap normally names at least one).
    """

    crew_id: str
    type: Literal["NO_SHOW", "LEFT_SITE", "UNAVAILABLE"]
    departed_ids: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Coercion helpers (담당자 A record shapes → strict schemas)                     #
# --------------------------------------------------------------------------- #
def _as_int(value: Any, default: int) -> int:
    """Coerce a possibly-``Decimal`` / ``None`` numeric to ``int`` (``None`` → default)."""
    if value is None:
        return default
    return int(value)


def _to_member(raw: Dict[str, Any]) -> Optional[Member]:
    """Coerce a Crew-member record to a :class:`Member`, or ``None`` when unusable.

    ``worker_id`` is required (a member without an id can be neither retained nor
    excluded); such entries are skipped. Other fields fall back to documented defaults.
    The wage is only an Agent hint — the validator recomputes ``total_cost`` from the
    freshest ``get_workers`` snapshot — so a defaulted wage cannot make an invalid output
    pass. ``state`` is carried for context only; the gap logic never mutates it.
    """
    worker_id = raw.get("worker_id")
    if not worker_id:
        return None
    return Member(
        worker_id=worker_id,
        trade=(raw.get("trade") or _DEFAULT_TRADE),
        desired_daily_wage=_as_int(raw.get("desired_daily_wage"), _DEFAULT_WAGE),
        state=(raw.get("state") or _RUNNING),
    )


def _extract_active_members(crew: Dict[str, Any]) -> List[Member]:
    """Extract active crew members (``active_members`` preferred, then ``members``)."""
    raw_members = crew.get("active_members")
    if raw_members is None:
        raw_members = crew.get("members") or []
    members = [_to_member(m) for m in raw_members]
    return [m for m in members if m is not None]


# --------------------------------------------------------------------------- #
# Gap registration input parsing                                               #
# --------------------------------------------------------------------------- #
def _parse_gap_input(event: Any) -> GapEventInput:
    """Parse a :class:`GapEventInput` from the API Gateway proxy event.

    The registration route is ``POST /{company|office}/crews/{crewId}/gap-events``, so the
    affected ``crewId`` arrives as a path parameter and ``type`` / ``departed_ids`` in the
    JSON body. A path ``crewId`` takes precedence over any ``crew_id`` in the body. For
    ergonomic direct invocation (tests / tooling) an event WITHOUT a ``body`` is treated as
    the input record itself. Strict field/`type` validation is enforced by the model.
    """
    if isinstance(event, dict) and "body" in event:
        body = event.get("body")
        if isinstance(body, str):
            data = json.loads(body) if body else {}
        elif isinstance(body, dict):
            data = dict(body)
        else:
            data = {}
    elif isinstance(event, dict):
        data = dict(event)
    else:
        data = {}

    path_params = (event.get("pathParameters") or {}) if isinstance(event, dict) else {}
    crew_id = path_params.get("crewId") or data.get("crew_id")

    return GapEventInput(
        crew_id=crew_id,
        type=data.get("type"),
        departed_ids=data.get("departed_ids") or [],
    )


# --------------------------------------------------------------------------- #
# Authorization                                                                #
# --------------------------------------------------------------------------- #
def _require_registrant(event: Any) -> Dict[str, Any]:
    """Authenticate the gap registrant: COMPANY or OFFICE (Req 11.3).

    Consumes ``shared/auth.require_role(event, [COMPANY, OFFICE])``. A role outside that set
    raises the auth helper's ForbiddenError, translated to ``_FlowError(FORBIDDEN)`` so the
    handler returns a FORBIDDEN response. Any non-forbidden exception propagates unchanged.
    Returns the caller identity dict (used to derive ``office_id`` for the office query path).
    """
    from backend.shared import auth  # lazy: real Layer in prod, installed stub in tests

    forbidden_type = getattr(auth, "ForbiddenError", None)
    try:
        identity = auth.require_role(event, [_ROLE_COMPANY, _ROLE_OFFICE])
    except Exception as exc:  # noqa: BLE001 - re-raise non-forbidden as-is (below)
        if forbidden_type is not None and isinstance(exc, forbidden_type):
            raise _FlowError(_ERR_FORBIDDEN, getattr(exc, "message", str(exc))) from exc
        raise
    return identity if isinstance(identity, dict) else {}


# --------------------------------------------------------------------------- #
# Trusted internal invoke seam (boto3 in prod; monkeypatched in tests)          #
# --------------------------------------------------------------------------- #
def invoke_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronously invoke agent_invoke with the trusted internal EMERGENCY payload.

    This is the single, injectable SEAM between gap_event and agent_invoke:

    - **Production**: an AWS Lambda ``RequestResponse`` invoke via boto3. The IAM trust
      boundary (only gap_event's execution role may invoke agent_invoke directly) is what
      lets agent_invoke trust this path; the ``internal_invoke`` marker is merely a routing
      hint. The target function name is read from the ``AGENT_INVOKE_FUNCTION_NAME`` env var.
    - **Tests**: monkeypatched to call ``agent_invoke.handler`` directly with ``payload`` (or
      to return a stubbed response), so the flow is exercised without live AWS.

    Returns the parsed agent_invoke response dict (``{"success": bool, ...}``). ``boto3`` is
    imported lazily so importing this module never requires it in the local dev/test env.
    """
    import boto3  # lazy: deploy-time dependency only; tests monkeypatch this function

    client = boto3.client("lambda")
    function_name = os.environ.get(
        _AGENT_INVOKE_FUNCTION_ENV, _DEFAULT_AGENT_INVOKE_FUNCTION
    )
    result = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = result.get("Payload")
    body = raw.read() if raw is not None else b""
    return json.loads(body) if body else {}


def _build_internal_payload(
    agent_input: AgentInput,
    event_id: str,
    office_id: Optional[str],
    crew_id: Optional[str],
) -> Dict[str, Any]:
    """Build the trusted internal-invoke payload matching agent_invoke's contract.

    Serializes the EMERGENCY :class:`AgentInput` with ``model_dump()`` (agent_invoke
    re-parses it with ``AgentInput.model_validate``) and attaches the routing marker, the
    mode, the locked ``event_id``, and the optional Crew-linkage fields. See the module
    docstring for the full contract.
    """
    payload: Dict[str, Any] = {
        _PAYLOAD_INTERNAL_MARKER: True,
        _PAYLOAD_MODE: _MODE_EMERGENCY,
        _PAYLOAD_EVENT_ID: event_id,
        _PAYLOAD_AGENT_INPUT: agent_input.model_dump(),
    }
    if office_id is not None:
        payload[_PAYLOAD_OFFICE_ID] = office_id
    if crew_id is not None:
        payload[_PAYLOAD_CURRENT_CREW_ID] = crew_id
    return payload


# --------------------------------------------------------------------------- #
# Observability — gap_event's own structured execution log (task 9.2)           #
# --------------------------------------------------------------------------- #
def _log_gap_execution(
    agent_input: AgentInput,
    *,
    event_id: str,
    success: bool,
    recommendations: List[Dict[str, Any]],
    crew_id: Optional[str],
) -> None:
    """Emit gap_event's OWN structured, PII-free execution record (Req 12.1, 12.2).

    The design has BOTH Lambdas write a structured log to CloudWatch. On the trusted
    internal-invoke path, agent_invoke already logged the compose execution it ran; this
    record captures the same emergency from gap_event's vantage point, so the two are
    complementary rather than double-counted:

    - ``agent_mode`` = EMERGENCY — this Lambda only ever drives emergency recomposition.
    - ``request_id`` carries the GapEvent ``event_id`` — gap_event's own correlation key —
      which is what distinguishes this record from agent_invoke's (keyed on the work
      ``request_id``). Both are PII-free string ids.
    - ``input_candidate_count`` = the candidate pool gap_event assembled into the payload.
    - ``recommendation_count`` / ``saved`` / ``crew_id`` / ``validation_passed`` come from
      agent_invoke's response: ``success`` means agent_invoke validated the output and saved
      a Crew(PROPOSED), so from gap_event's vantage ``validation_passed`` ≈ ``saved`` ≈
      ``success``. gap_event does NOT observe agent_invoke's internal retry / fallback, so
      ``retried`` / ``fallback_used`` stay false here — those belong to agent_invoke's own
      record, avoiding a misleading double-count.

    Only counts / ids / flags are logged (never worker names / phones); ``AgentLogRecord``'s
    ``extra="forbid"`` would reject a stray key regardless (Req 12.2). Logging is a pure
    side-effect: any failure building / emitting the record is swallowed after a diagnostic
    line so it can never alter the gap-handling flow's outcome.
    """
    try:
        record = build_agent_log_record(
            agent_execution_id=new_execution_id(),
            agent_mode=_MODE_EMERGENCY,
            request_id=event_id,
            input_candidate_count=len(agent_input.candidates),
            recommendation_count=len(recommendations),
            validation_passed=success,
            saved=success,
            crew_id=crew_id,
        )
        log_agent_execution(record)
    except Exception:  # noqa: BLE001 - logging must never break the gap-handling flow
        _logger.exception("failed to emit gap_event structured execution log")


# --------------------------------------------------------------------------- #
# Core orchestration                                                           #
# --------------------------------------------------------------------------- #
def _process_gap_event(event: Any) -> Dict[str, Any]:
    """Run the full gap-capture → EMERGENCY recomposition flow (see module docstring).

    Raises ``_FlowError`` for the pre-invoke guard failures (FORBIDDEN / CREW_INVALID /
    STATE_CONFLICT), which the top-level handler converts to a shared error response.
    Returns a shared success response on ``RECOMPOSING → PROPOSED``, or a shared error
    response (after ``RECOMPOSING → FAILED``) with manual-composition guidance on failure.
    """
    from backend.shared import db, response  # lazy: real Layer / installed stub

    # 1. Authenticate the registrant — COMPANY or OFFICE (Req 11.3).
    identity = _require_registrant(event)

    # 2. Parse the gap registration input (crew_id, type, departed_ids).
    gap_input = _parse_gap_input(event)

    # 3. office_id for the office query path — from the authenticated identity, which is
    #    available BEFORE the crew lookup (the crew's office_id is a downstream fallback).
    office_id = identity.get("office_id")

    # 4. Save the GapEvent as DETECTED FIRST (Req 10.1) so it is retrievable through the
    #    office polling query path within the polling cycle, even if recomposition fails.
    #    The item carries the office-query-path fields: office_id + status(=DETECTED).
    gap_item: Dict[str, Any] = {
        "status": _GAP_DETECTED,
        "type": gap_input.type,
        "crew_id": gap_input.crew_id,
        "departed_ids": list(gap_input.departed_ids),
    }
    if office_id is not None:
        gap_item["office_id"] = office_id
    event_id = db.save_gap_event(gap_item)

    # 5. Look up the affected Crew (Req 10.2). Missing/invalid → CREW_INVALID (Req 10.11);
    #    the DETECTED event stays saved and retrievable (matches the design sequence).
    crew = db.get_crew(gap_input.crew_id)
    if crew is None:
        raise _FlowError(
            _ERR_CREW_INVALID, f"affected crew not found: {gap_input.crew_id!r}"
        )
    request_id = crew.get("request_id")
    if not request_id:
        raise _FlowError(
            _ERR_CREW_INVALID, f"crew {gap_input.crew_id!r} has no linked request_id"
        )

    # 6. Compute the retained team (active − departed) and the shortage — pure, no worker
    #    state change (Req 10.3/10.4/10.5).
    active_members = _extract_active_members(crew)
    fixed_members = compute_fixed_members(active_members, gap_input.departed_ids)

    # 7. Assemble the FULL request + office-scoped READY candidates + collaboration pairs,
    #    reusing the same assembler the external agent-recompose route uses (no divergence).
    assembly_office_id = office_id or crew.get("office_id")
    try:
        normal_like = assemble_normal_input(request_id, assembly_office_id)
    except ValueError as exc:  # linked work request missing/unreadable
        raise _FlowError(
            _ERR_CREW_INVALID,
            f"work request for crew {gap_input.crew_id!r} unavailable: {exc}",
        ) from exc
    request = normal_like.request

    # 8. Narrow candidates to trades with a positive shortage (fully covered trades need
    #    no new hires); build the mode=EMERGENCY payload (Req 10.6). The request carries the
    #    FULL required_workers (fixed + shortage), as build_emergency_payload requires.
    missing = compute_missing(request.required_workers, fixed_members)
    missing_trades = {tr.trade for tr in missing}
    candidates = [c for c in normal_like.candidates if c.trade in missing_trades]
    agent_input = build_emergency_payload(
        request, fixed_members, candidates, normal_like.collaboration_pairs
    )

    # 9. Acquire the lock BEFORE invoking: DETECTED → RECOMPOSING (Req 10.6). A failed
    #    conditional transition (duplicate / not DETECTED) → STATE_CONFLICT. Pre-locking is
    #    what lets agent_invoke's internal path accept the already-RECOMPOSING GapEvent.
    if not db.transition_gap_event_status(event_id, _GAP_DETECTED, _GAP_RECOMPOSING):
        raise _FlowError(
            _ERR_STATE_CONFLICT,
            f"gap event {event_id!r} not in {_GAP_DETECTED} (already recomposing?)",
        )

    # 10. Trusted internal invoke of agent_invoke (synchronous) with the EMERGENCY payload.
    payload = _build_internal_payload(
        agent_input, event_id, assembly_office_id, gap_input.crew_id
    )
    agent_resp = invoke_agent(payload)

    # 10b. Emit gap_event's OWN structured execution record (task 9.2) — ONCE per gap
    #      handling, from gap_event's vantage point (agent_invoke logged the compose
    #      execution separately). Derived from the invoke response; never touches the DB, so
    #      it does not affect the transition order asserted by the tests.
    success = isinstance(agent_resp, dict) and agent_resp.get("success") is True
    agent_data = (agent_resp.get("data") or {}) if isinstance(agent_resp, dict) else {}
    _log_gap_execution(
        agent_input,
        event_id=event_id,
        success=success,
        recommendations=agent_data.get("recommendations", []) if success else [],
        crew_id=agent_data.get("crew_id") if success else None,
    )

    # 11. Own the terminal transition on this internal path (agent_invoke does not touch
    #     the GapEvent here). Remaining team members keep RUNNING — no worker-state change.
    if success:
        db.transition_gap_event_status(event_id, _GAP_RECOMPOSING, _GAP_PROPOSED)
        return response.ok(
            {
                "event_id": event_id,
                "gap_status": _GAP_PROPOSED,
                "mode": _MODE_EMERGENCY,
                "crew_id": agent_data.get("crew_id"),
                "recommendations": agent_data.get("recommendations", []),
            }
        )

    # Recomposition failed (retry exhausted): FAILED + manual-composition guidance (Req 10.9).
    db.transition_gap_event_status(event_id, _GAP_RECOMPOSING, _GAP_FAILED)
    err = agent_resp.get("error") if isinstance(agent_resp, dict) else None
    err = err or {}
    code = err.get("code") or _ERR_AGENT_RETRY_FAILED
    detail = err.get("message") or "emergency recomposition failed"
    return response.error(code, f"{detail} | {_MANUAL_GUIDANCE}")


# --------------------------------------------------------------------------- #
# Lambda entry point                                                           #
# --------------------------------------------------------------------------- #
def handler(event: Any, context: Any = None) -> Dict[str, Any]:
    """gap_event Lambda entry point: capture the gap, then drive EMERGENCY recomposition.

    Delegates to :func:`_process_gap_event`; every mapped guard failure is raised internally
    as a ``_FlowError`` and converted here to a single ``response.error(code, message)``.
    Success and recomposition-failure paths return their shared responses directly (the
    failure path also performs the ``RECOMPOSING → FAILED`` transition before returning).
    """
    from backend.shared import response  # lazy: real Layer in prod, installed stub in tests

    try:
        return _process_gap_event(event)
    except _FlowError as exc:
        return response.error(exc.code, exc.message)
