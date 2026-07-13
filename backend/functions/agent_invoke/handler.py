"""Lambda handler for the agent_invoke function (담당자 B, task 5.3).

This is the entry point that turns a compose/recompose trigger into a validated,
persisted crew proposal. It owns **routing**, **authorization** (external OFFICE gate
vs. IAM-enforced internal trust), the **state guard** (per-path branching), and the
first pass of the **compose_flow** orchestration (single execution; retry / fallback /
rollback are wired later in task 6.3).

Design references
-----------------
- ``design.md`` -> "Components and Interfaces" -> "4. Agent Invoke Lambda",
  "5. 상태 가드 & 동시성 제어", "7. 권한", and both sequence diagrams.
- ``requirements.md`` -> Req 6.1/6.2/6.3/6.5/6.6/6.7 (invoke + candidate assembly +
  state guard), 10.6/10.7/10.10 (EMERGENCY payload + terminal transition + not-found),
  11.1/11.2/11.3/11.4 (execution-trigger authorization).

Two entry paths, distinguished by EVENT SHAPE (not a trusted payload flag)
--------------------------------------------------------------------------
1. ``POST /office/requests/{requestId}/agent-compose``  -> NORMAL  (external/direct,
   via API Gateway proxy event).
2. gap_event Lambda's **trusted internal invoke** -> EMERGENCY, consuming a
   pre-assembled payload (a plain invoke dict, NOT an API Gateway event).

EMERGENCY is driven EXCLUSIVELY by the gap_event Lambda's EventBridge → trusted internal
invoke path; there is no external ``agent-recompose`` API route (the direct EMERGENCY
route was removed — decision 5). ``_is_internal_invoke`` routes by the event's *shape*: an
API Gateway proxy event carries ``requestContext`` / ``httpMethod`` / ``resource`` /
``pathParameters``, whereas gap_event's internal invoke is a plain dict carrying the
EMERGENCY payload plus an explicit ``internal_invoke`` marker and ``event_id``.

    IMPORTANT - the real trust boundary is IAM, not the payload marker. The
    ``internal_invoke`` key is only a *routing hint*: a payload flag is spoofable, so it
    can never be the security control. Access is enforced two ways: the API Gateway
    ``agent-compose`` route requires the OFFICE role (below), and the internal invoke is
    locked down by IAM so that ONLY gap_event's Lambda execution role may invoke
    agent_invoke directly. That IAM policy is 담당자 A's infrastructure scope; this handler
    documents and relies on it.

Internal-invoke payload contract (defined here; gap_event MUST match it)
------------------------------------------------------------------------
gap_event invokes agent_invoke synchronously with a JSON-serializable dict::

    {
        "internal_invoke": true,                 # routing marker (trust is IAM-enforced)
        "mode": "EMERGENCY",                     # always EMERGENCY on this path
        "event_id": "<GapEvent id>",             # the GapEvent gap_event already locked
        "agent_input": { ...AgentInput dict... },# pre-assembled EMERGENCY payload
        "office_id": "<office id>",              # optional linkage
        "current_crew_id": "<crew being recomposed>"  # optional linkage
    }

``agent_input`` is an :class:`~agent.schemas.AgentInput` serialized via ``model_dump()``
(gap_event builds it with ``build_emergency_payload``); this handler re-parses it with
:meth:`AgentInput.model_validate`. The ``mode`` / ``event_id`` / ``office_id`` /
``current_crew_id`` keys carry routing + linkage metadata.

Authorization - external OFFICE gate vs. trusted internal path (Req 11)
-----------------------------------------------------------------------
- The external/direct ``agent-compose`` route calls ``shared/auth.get_principal(event)``
  then ``Principal.require_role(OFFICE)``. A non-OFFICE subject trying to trigger the agent
  DIRECTLY raises ``responses.ApiError`` (FORBIDDEN), returned as a proxy error at the
  handler boundary (Req 11.1, 11.2, 11.4).
- The trusted internal invoke does NOT apply the OFFICE gate (Req 11.3): gap_event already
  authenticated the gap registrant (COMPANY *or* OFFICE), and the emergency recomposition
  is a continuation of that authenticated flow - so a COMPANY-registered gap flows through
  to recomposition without a FORBIDDEN. Trust on this path is IAM, not the role of the
  original registrant.

State guard - conditional writes, per-path branching (Req 6.6/6.7, design section 5)
------------------------------------------------------------------------------------
- NORMAL: ``transition_request_status(REQUESTED -> COMPOSING)``. A failed conditional
  write (already COMPOSING/PROPOSED, or a concurrent duplicate) -> ``STATE_CONFLICT``;
  duplicates are naturally rejected, never queued.
- EMERGENCY trusted internal invoke: gap_event has ALREADY acquired
  ``DETECTED -> RECOMPOSING`` before invoking, so the GapEvent is already ``RECOMPOSING``.
  This path does NOT acquire a lock and never raises ``STATE_CONFLICT`` (this is what
  prevents the internal invoke from dead-locking on gap_event's own lock).

EMERGENCY: NO Crew is created; gap_event owns the GapEvent (option-1 hand-off)
-----------------------------------------------------------------------------
Under the option-1 emergency hand-off, agent_invoke's EMERGENCY path composes + validates
1..3 recommendations and RETURNS them, but does NOT persist anything itself: it saves no
Crew, never touches the WorkRequest (it may be ``RUNNING``), and never transitions the
GapEvent. The gap_event Lambda records the retained ``fixed_member_ids`` + the
``recommendations`` onto the GapEvent item and owns the terminal transition
(``RECOMPOSING -> PROPOSED`` / ``FAILED``); 담당자 A's emergency approval API then reads
those and the OFFICE approves a ``replacement_member_ids`` set. Only the NORMAL path
persists a Crew (via ``save_normal_proposal``).

compose_flow (single attempt) + compose_flow_with_retry (orchestration, task 6.3)
---------------------------------------------------------------------------------
``compose_flow`` is ONE attempt: compose -> (on ``BedrockUnavailable``, substitute
``demo_fallback`` when the fallback flag is ON, Req 9.4) -> build the freshest-snapshot
validation context (검증 직전 최신 스냅샷) -> validate -> on pass, save via the mode-specific
persistence function -> (external EMERGENCY only) terminal ``RECOMPOSING -> PROPOSED``. On
validation failure it raises ``AGENT_OUTPUT_INVALID`` WITHOUT saving; a Bedrock
failure/timeout with fallback OFF maps to ``AGENT_RETRY_FAILED``.

``compose_flow_with_retry`` wraps that single attempt with the design's retry orchestration
(task 6.3) and is what the handler entry paths call:

- **Retry (Req 9.1)**: a validation failure is discarded, an error log is recorded, and the
  Agent is retried EXACTLY ONCE — at most two compose attempts total. A Bedrock failure with
  fallback OFF is NOT retried (a down Bedrock is not worth retrying).
- **Failure cleanup on exhaustion**: ``AGENT_RETRY_FAILED`` (Req 9.2) plus, per mode:
  NORMAL rolls the WorkRequest back ``COMPOSING -> REQUESTED`` (manual composition possible);
  EMERGENCY does NOTHING — gap_event owns ``RECOMPOSING -> FAILED`` + manual guidance
  (Req 10.9). EMERGENCY never touches the WorkRequest (it may be RUNNING) or the GapEvent.
  The only failure-path state change is the NORMAL non-PROPOSED rollback, so Property 9
  ("no save + no PROPOSED transition") still holds.

The single attempt is kept a separate, public function so the Property 9 and freshest-
snapshot tests can drive it directly and assert ``AGENT_OUTPUT_INVALID`` on a validation
failure; the retry/rollback lives in the wrapper, so extending 6.3 did not restructure it.

Observability logging (task 9.2, Req 12.1/12.2)
-----------------------------------------------
``compose_flow_with_retry`` emits EXACTLY ONE structured, PII-free ``AgentLogRecord`` per
execution — the "구조화 로그 기록" step of both sequence diagrams. The single attempt
(``compose_flow``) records the signals it can see into a shared :class:`_ExecutionTelemetry`
(fallback substitution, the produced recommendation count, its validation outcome + failed
check NAMES, and the final save + crew id); the wrapper owns ``retried`` (a second attempt
ran) and emits the record ONCE in a ``finally`` — so success (first try or after a retry),
double-validation-failure, fallback-served, and Bedrock-down-with-fallback-off executions
all produce one accurate line. Only counts / ids / flags are logged (never names / phones),
and the log emit is wrapped so it can never alter the flow's return value or raised error.
The record is emitted only where the Agent actually runs (inside the retry wrapper); the
pre-compose guard failures (FORBIDDEN / STATE_CONFLICT / GAP_EVENT_NOT_FOUND / CREW_INVALID)
short-circuit before any Agent execution and intentionally produce no execution record.

gap_event logs a SEPARATE record from its own perspective (see ``gap_event/handler.py``):
for a trusted internal invoke, agent_invoke logs the compose execution (keyed on the work
``request_id``) while gap_event logs the gap-handling execution (keyed on the ``event_id``,
``saved`` / ``recommendation_count`` sourced from agent_invoke's response). The two records
describe the same emergency from the two Lambdas' vantage points (both write structured logs
per the design) and are distinguishable by their id fields, not double-counted.

Bedrock fallback flag (Req 9.3)
-------------------------------
The demo-fallback flag is read from the ``AGENT_FALLBACK_ENABLED`` env var (default OFF) at
call time via :func:`fallback_enabled_default`. ``compose_flow`` / ``compose_flow_with_retry``
also accept an explicit ``fallback_enabled: Optional[bool]`` that overrides the env (``None``
uses the env value) so tests can force it ON/OFF without environment manipulation. When ON,
a ``BedrockUnavailable`` is served by the deterministic ``demo_fallback`` composer, which
flows through the identical validation + persistence path (the demo happy path, Property 13).

Which recommendation is saved
------------------------------
The Agent returns 1..3 ranked alternatives, and ALL are returned in the response for the
OFFICE to review. For NORMAL, ``save_normal_proposal`` persists the top-ranked
recommendation (smallest ``rank``) as the actionable ``Crew(PROPOSED)``. For EMERGENCY,
nothing is saved here — gap_event records all recommendations onto the GapEvent. Selection
among alternatives and approval are 담당자 A's scope.

shared helper consumption
-------------------------
``backend/shared/*`` is 담당자 A's and is consumed, never implemented (it is absent on
disk here). ``db`` / ``auth`` / ``response`` are imported LAZILY inside functions (matching
assembler/persistence) so they resolve at call time - the real Layer in deployment, or the
stubs installed under ``backend.shared.*`` in tests.

Python 3.9 note
---------------
``from __future__ import annotations`` keeps annotations lazy so the builtin-generic style
resolves on the local Python 3.9 runtime; ``Optional[...]`` is used for nullable types.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.crew_agent import BedrockUnavailable, compose
from agent.schemas import AgentInput, AgentOutput, Recommendation
from backend.functions.agent_invoke.assembler import (
    assemble_normal_input,
    build_validation_context,
)
from backend.functions.agent_invoke.fallback import demo_fallback
from backend.functions.agent_invoke.observability import (
    build_agent_log_record,
    log_agent_execution,
    new_execution_id,
)
from backend.functions.agent_invoke.persistence import (
    SaveContext,
    save_normal_proposal,
)
from backend.functions.agent_invoke.validator import validate_output

__all__ = [
    "handler",
    "compose_flow",
    "compose_flow_with_retry",
    "fallback_enabled_default",
    "INTERNAL_INVOKE_MARKER",
]

# Module logger — plain, propagating logger for the minimal error log Req 9.1 asks for on a
# validation-failure discard/retry, and for the defensive "log emit failed" line. Deliberately
# SEPARATE from observability.py's structured AgentLogRecord logger (LOGGER_NAME): task 9.2
# emits the full per-execution structured record via ``log_agent_execution`` (see
# :func:`_emit_execution_log` / :func:`compose_flow_with_retry`), while this logger only carries
# the lightweight per-attempt error line so a discarded/retried output stays traceable.
_logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Modes                                                                        #
# --------------------------------------------------------------------------- #
_MODE_NORMAL = "NORMAL"
_MODE_EMERGENCY = "EMERGENCY"

# --------------------------------------------------------------------------- #
# State constants — mirror backend.shared.state (RequestStatus / GapStatus).   #
# Declared locally (like persistence.py) so this module stays importable       #
# standalone; values are fixed by the shared-contract glossary in              #
# requirements.md and verified against tests/mocks/shared_stubs.py.            #
# --------------------------------------------------------------------------- #
_REQ_REQUESTED = "REQUESTED"  # RequestStatus.REQUESTED (expected state at NORMAL entry)
_REQ_COMPOSING = "COMPOSING"  # RequestStatus.COMPOSING (lock acquired at NORMAL entry)
_GAP_DETECTED = "DETECTED"  # GapStatus.DETECTED (expected at external agent-recompose)
_GAP_RECOMPOSING = "RECOMPOSING"  # GapStatus.RECOMPOSING (lock held during recomposition)
_GAP_PROPOSED = "PROPOSED"  # GapStatus.PROPOSED (terminal transition on save success)
_GAP_FAILED = "FAILED"  # GapStatus.FAILED (retry-exhausted terminal on the EXTERNAL route)

# Role required on the external API Gateway routes (Role.OFFICE).
_ROLE_OFFICE = "OFFICE"

# Path identifiers threaded through compose_flow for call-site symmetry.
_PATH_EXTERNAL = "external"  # API Gateway proxy event (NORMAL agent-compose)
_PATH_INTERNAL = "internal"  # gap_event's trusted internal invoke (EMERGENCY)

# --------------------------------------------------------------------------- #
# Error codes — fixed by the shared contract (PRD_A_BACKEND.md 1.6 / design.md #
# Error Handling). No new codes are invented.                                  #
# --------------------------------------------------------------------------- #
_ERR_STATE_CONFLICT = "STATE_CONFLICT"
_ERR_GAP_EVENT_NOT_FOUND = "GAP_EVENT_NOT_FOUND"
_ERR_CREW_INVALID = "CREW_INVALID"
_ERR_FORBIDDEN = "FORBIDDEN"
_ERR_AGENT_OUTPUT_INVALID = "AGENT_OUTPUT_INVALID"
_ERR_AGENT_RETRY_FAILED = "AGENT_RETRY_FAILED"

# Wall-clock bound (seconds) for a single Bedrock compose call (env-overridable).
_DEFAULT_TIMEOUT_S = float(os.environ.get("AGENT_INVOKE_TIMEOUT_S", "25"))

# --------------------------------------------------------------------------- #
# Bedrock fallback flag (Req 9.3) & retry budget (Req 9.1).                     #
# --------------------------------------------------------------------------- #
# The demo-fallback flag (Req 9.3) is read from this env var, defaulting OFF/false. It is
# read at CALL time (not import time) so deployment config and tests take effect without a
# re-import; callers may also override it per call via an explicit ``fallback_enabled`` arg
# (see :func:`fallback_enabled_default` and ``compose_flow``'s ``fallback_enabled`` param).
_ENV_FALLBACK_ENABLED = "AGENT_FALLBACK_ENABLED"
# Truthy spellings accepted for the env flag (case-insensitive); anything else is OFF.
_ENV_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

# "정확히 1회 재시도" (Req 9.1): at most TWO compose attempts total — the initial attempt
# plus exactly one retry on a validation failure. Bedrock-down + fallback OFF is NOT retried
# (an immediate AGENT_RETRY_FAILED per the design's Error Handling mapping).
_MAX_COMPOSE_ATTEMPTS = 2

# --------------------------------------------------------------------------- #
# Internal-invoke payload contract keys (see module docstring).                #
# gap_event task 8.5 MUST build its invoke payload with these keys.            #
# --------------------------------------------------------------------------- #
INTERNAL_INVOKE_MARKER = "internal_invoke"
_PAYLOAD_MODE = "mode"
_PAYLOAD_EVENT_ID = "event_id"
_PAYLOAD_AGENT_INPUT = "agent_input"
_PAYLOAD_OFFICE_ID = "office_id"
_PAYLOAD_CURRENT_CREW_ID = "current_crew_id"

# API Gateway proxy-event keys used only to distinguish an external event from an internal
# invoke dict (shape-based routing, per the design intent).
_APIGW_SHAPE_KEYS = ("requestContext", "httpMethod", "resource")


class _FlowError(Exception):
    """Internal control-flow signal carrying a shared error ``code`` + ``message``.

    Raised anywhere in routing / auth / state-guard / compose_flow to short-circuit to a
    ``response.error(code, message)`` at the single top-level handler boundary. Not part
    of the public surface — the handler always converts it to a shared response.
    """

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# Bedrock fallback flag resolution (Req 9.3)                                   #
# --------------------------------------------------------------------------- #
def fallback_enabled_default() -> bool:
    """Read the demo-fallback flag from the environment (Req 9.3), defaulting OFF.

    Returns ``True`` only when ``AGENT_FALLBACK_ENABLED`` is set to a truthy spelling
    (``1`` / ``true`` / ``yes`` / ``on``, case-insensitive); any other value (or unset) is
    ``False``. Read at call time so deployment config / tests take effect without a
    re-import. Public so tests and task 9.2 can consult the same source of truth.
    """
    raw = os.environ.get(_ENV_FALLBACK_ENABLED, "")
    return raw.strip().lower() in _ENV_TRUE_VALUES


def _resolve_fallback_enabled(fallback_enabled: Optional[bool]) -> bool:
    """Resolve the effective fallback flag: the explicit arg wins, else the env default.

    ``compose_flow`` / ``compose_flow_with_retry`` accept ``fallback_enabled: Optional[bool]``
    so a caller (notably a test) can force the flag ON/OFF without touching the environment.
    When it is ``None`` the environment value (:func:`fallback_enabled_default`) is used.
    """
    if fallback_enabled is not None:
        return fallback_enabled
    return fallback_enabled_default()


# --------------------------------------------------------------------------- #
# Event-shape routing                                                          #
# --------------------------------------------------------------------------- #
def _is_api_gateway_event(event: Any) -> bool:
    """True when the event looks like an API Gateway proxy event (external/direct)."""
    return isinstance(event, dict) and any(k in event for k in _APIGW_SHAPE_KEYS)


def _is_internal_invoke(event: Any) -> bool:
    """True when the event is gap_event's trusted internal invoke payload.

    Routing hint only: the ``internal_invoke`` marker distinguishes the plain invoke dict
    from an API Gateway proxy event. The actual trust boundary is IAM (only gap_event's
    execution role may invoke agent_invoke directly) — a payload flag is spoofable and is
    never treated as a security control.
    """
    return (
        isinstance(event, dict)
        and bool(event.get(INTERNAL_INVOKE_MARKER))
        and not _is_api_gateway_event(event)
    )


def _classify_api_event(event: Dict[str, Any]) -> str:
    """Classify an API Gateway proxy event; only NORMAL ``agent-compose`` is a valid route.

    EMERGENCY is driven exclusively by gap_event's trusted internal invoke (there is no
    external ``agent-recompose`` route), so any other/unrecognized API route raises.
    """
    resource = str(event.get("resource") or event.get("path") or "")
    path_params = event.get("pathParameters") or {}
    if "agent-compose" in resource or "requestId" in path_params:
        return _MODE_NORMAL
    raise ValueError(f"unrecognized agent_invoke route: resource={resource!r}")


def _path_param(event: Dict[str, Any], name: str) -> str:
    """Return a required path parameter (raises when absent/empty)."""
    value = (event.get("pathParameters") or {}).get(name)
    if not value:
        raise ValueError(f"missing path parameter: {name!r}")
    return value


# --------------------------------------------------------------------------- #
# Authorization                                                                #
# --------------------------------------------------------------------------- #
def _require_office(event: Any) -> "Principal":
    """Apply the external OFFICE-only gate and return the authenticated principal.

    Consumes 담당자 A's real ``shared/auth.get_principal(event)`` +
    ``Principal.require_role(OFFICE)``. Both raise ``responses.ApiError``
    (UNAUTHORIZED / FORBIDDEN) which propagates to the top-level handler and is converted to
    the matching proxy error response (Req 11.2, 11.4). This gate is applied ONLY on the
    external API Gateway routes; the trusted internal invoke deliberately skips it (Req 11.3).
    Callers read ``principal.office_id`` (an attribute) for the office linkage.
    """
    from backend.shared import auth  # lazy: real Layer in prod

    principal = auth.get_principal(event)
    principal.require_role(_ROLE_OFFICE)
    return principal


# --------------------------------------------------------------------------- #
# Per-execution observability telemetry (task 9.2)                             #
# --------------------------------------------------------------------------- #
@dataclass
class _ExecutionTelemetry:
    """Mutable per-execution signals populated by :func:`compose_flow` (a single attempt)
    and consumed by :func:`compose_flow_with_retry` to build EXACTLY ONE
    :class:`~backend.functions.agent_invoke.observability.AgentLogRecord` per execution.

    Why this exists (task 9.2)
    --------------------------
    The design (both sequence diagrams' "구조화 로그 기록" step, Req 12.1) asks for one
    structured log per Agent execution reflecting validation success/failure, retry,
    fallback, and the final save. A single attempt (:func:`compose_flow`) can only observe
    part of that — whether IT substituted the fallback, the output it produced, its own
    validation outcome, and its own save — while ``retried`` is only knowable by the wrapper
    that owns the attempt loop. So the single attempt records what it sees into this object
    and the wrapper stamps ``retried`` and emits the record ONCE for the whole execution.

    Threading contract
    ------------------
    Threaded into :func:`compose_flow` as an OPTIONAL keyword (default ``None``). The
    direct-drive callers of ``compose_flow`` (the Property 9 and freshest-snapshot tests)
    omit it, so they neither populate telemetry nor trigger a log line — the single-attempt
    contract they rely on is untouched. Only :func:`compose_flow_with_retry` passes one in,
    and it is the sole emitter of the structured record.

    Fields mirror the observable subset of ``AgentLogRecord``; ``retried`` is deliberately
    NOT here because the wrapper owns it. All values are counts / flags / ids only — never
    PII (Req 12.2).

    On a retry the SAME instance is reused across attempts, so each field is overwritten to
    reflect the LAST attempt — i.e. the execution's final outcome (validation_passed,
    failed checks, recommendation_count, saved, crew_id). ``fallback_used`` reflects whether
    the fallback was substituted on the final attempt.
    """

    fallback_used: bool = False
    recommendation_count: int = 0
    validation_passed: bool = False
    validation_failed_checks: List[str] = field(default_factory=list)
    saved: bool = False
    crew_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# compose_flow — validation + persistence (first pass; SEAM for task 6.3)      #
# --------------------------------------------------------------------------- #
def _collect_member_ids(output: AgentOutput) -> List[str]:
    """Union of every recommendation's ``member_ids`` (deduped downstream in the ctx)."""
    ids: List[str] = []
    for rec in output.recommendations:
        ids.extend(rec.member_ids)
    return ids


def _select_recommendation(output: AgentOutput) -> Recommendation:
    """Pick the top-ranked recommendation (smallest ``rank``) to persist as the NORMAL Crew."""
    return min(output.recommendations, key=lambda rec: rec.rank)


def _persist_and_finalize(
    output: AgentOutput, save_ctx: SaveContext, *, path: str, event_id: Optional[str]
) -> Optional[str]:
    """Persist the result per mode and return the Crew id (``None`` for EMERGENCY).

    - NORMAL: ``save_normal_proposal`` saves the Crew AND transitions the WorkRequest
      ``COMPOSING -> PROPOSED`` (Req 8.1, 8.2). Returns the crew id.
    - EMERGENCY (option-1 hand-off): NOTHING is persisted here — no Crew, no WorkRequest
      change, no GapEvent transition. The validated recommendations are returned to the
      gap_event Lambda, which records them onto the GapEvent (``fixed_member_ids`` +
      ``recommendations``) and owns the terminal ``RECOMPOSING -> PROPOSED`` / ``FAILED``
      transition. Returns ``None``.

    ``path`` / ``event_id`` are retained on the signature for call-site symmetry but are no
    longer used to drive an EMERGENCY terminal transition (agent_invoke never transitions
    the GapEvent).
    """
    if save_ctx.mode == _MODE_NORMAL:
        recommendation = _select_recommendation(output)
        return save_normal_proposal(recommendation, save_ctx)
    # EMERGENCY: gap_event persists the recommendations + owns the terminal transition.
    return None


def compose_flow(
    agent_input: AgentInput,
    save_ctx: SaveContext,
    *,
    path: str,
    event_id: Optional[str] = None,
    compose_fn: Optional[Any] = None,
    fallback_enabled: Optional[bool] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    telemetry: Optional["_ExecutionTelemetry"] = None,
) -> Dict[str, Any]:
    """Run ONE compose attempt end-to-end and return a ``shared/response`` success dict.

    Steps (single execution): ``compose`` -> (on ``BedrockUnavailable``, substitute
    ``demo_fallback`` when the fallback flag is ON) -> build the freshest-snapshot
    :class:`ValidationContext` (검증 직전 최신 스냅샷) -> ``validate_output`` -> on pass,
    persist via the mode-specific save function and perform the path-owned terminal
    transition -> success response.

    Outcomes when the attempt does not succeed (both raised as :class:`_FlowError`):

    - **Validation failure** -> ``AGENT_OUTPUT_INVALID`` with NO save and NO state change
      (upholds Property 9). This is the single-attempt contract the direct-drive tests
      (Property 9 / freshest-snapshot) rely on; the ONE retry + rollback / FAILED transition
      live in :func:`compose_flow_with_retry`, which wraps this function (see below).
    - **Bedrock failure/timeout + fallback OFF** -> ``AGENT_RETRY_FAILED`` (design Error
      Handling mapping: a down Bedrock with fallback disabled is not worth retrying).
    - **Bedrock failure/timeout + fallback ON** -> the deterministic ``demo_fallback`` output
      is composed and flows through the SAME validation + persistence path (Req 9.4). Given
      sufficient candidates it validates and saves (Property 13, the demo happy path).

    Parameters
    ----------
    compose_fn:
        Overrides the module-level :func:`compose` (tests inject a fake so no live Bedrock
        call is made); production omits it.
    fallback_enabled:
        Explicit override of the demo-fallback flag (Req 9.3). ``None`` (the default) uses
        the environment value via :func:`_resolve_fallback_enabled`; a test may force it
        ``True`` / ``False`` without touching the environment. Only consulted on a
        ``BedrockUnavailable``.
    path:
        ``_PATH_EXTERNAL`` / ``_PATH_INTERNAL`` — governs the EMERGENCY terminal-transition
        owner. ``event_id`` is required for the external EMERGENCY terminal transition.
    telemetry:
        Optional :class:`_ExecutionTelemetry` (task 9.2). When provided, this single attempt
        records the signals it observes — ``fallback_used``, ``recommendation_count``,
        ``validation_passed`` + ``validation_failed_checks``, and ``saved`` + ``crew_id`` —
        into it. It is NOT emitted here: :func:`compose_flow_with_retry` owns the ``retried``
        flag and emits exactly ONE structured log per execution. ``None`` (the default) means
        no telemetry is recorded and no log line is produced by this attempt, keeping the
        direct-drive single-attempt callers (Property 9 / freshest-snapshot tests) unchanged.

    Retry / rollback split (task 6.3)
    ---------------------------------
    This function stays a SINGLE attempt on purpose so it remains directly testable (the
    Property 9 and freshest-snapshot tests drive it and assert ``AGENT_OUTPUT_INVALID`` on a
    validation failure). The design's retry orchestration — "정확히 1회 재시도" then the NORMAL
    ``COMPOSING -> REQUESTED`` rollback or the EMERGENCY-external ``RECOMPOSING -> FAILED``
    transition and the final ``AGENT_RETRY_FAILED`` — is implemented in
    :func:`compose_flow_with_retry`, which the handler entry paths call. That wrapper catches
    this function's ``AGENT_OUTPUT_INVALID`` to decide whether to retry, so extending 6.3 did
    not restructure this working single attempt.
    """
    from backend.shared import responses  # lazy: real Layer in prod

    active_compose = compose_fn if compose_fn is not None else compose
    use_fallback = _resolve_fallback_enabled(fallback_enabled)

    # ---- Agent execution ---------------------------------------------------------- #
    # SEAM (task 6.3): on BedrockUnavailable, substitute demo_fallback WHEN the fallback flag
    # is ON (Req 9.4) and continue down the identical validation path; when it is OFF, map the
    # Bedrock failure to AGENT_RETRY_FAILED (design Error Handling: "Bedrock 실패/타임아웃 +
    # 폴백 OFF -> AGENT_RETRY_FAILED"). demo_fallback is deterministic and makes no LLM call.
    try:
        output = active_compose(agent_input, timeout_s=timeout_s)
    except BedrockUnavailable as exc:
        if not use_fallback:
            # Bedrock down + fallback OFF: no output is produced, so telemetry keeps its
            # defaults (recommendation_count=0, validation_passed=False, saved=False) — a
            # clear "execution failed to produce anything" record when the wrapper emits it.
            raise _FlowError(
                _ERR_AGENT_RETRY_FAILED,
                f"agent unavailable and fallback disabled: {exc}",
            ) from exc
        output = demo_fallback(agent_input)
        if telemetry is not None:
            telemetry.fallback_used = True  # the demo composer produced this output (Req 9.4)

    if telemetry is not None:
        # Count whatever the agent (or fallback) produced, even if it later fails validation.
        telemetry.recommendation_count = len(output.recommendations)

    # ---- Validation against the freshest snapshot (검증 직전 최신 스냅샷) ------------- #
    # The fallback output (if used) is NOT trusted any more than a live one: it goes through
    # the same freshest-snapshot context + validate_output, so an insufficient-candidate
    # fallback would still be rejected here (the safe, degraded outcome).
    ctx = build_validation_context(
        _collect_member_ids(output),
        mode=agent_input.mode,
        candidates=agent_input.candidates,
        fixed_members=agent_input.fixed_members,
        required_workers=agent_input.request.required_workers,
        current_crew_id=save_ctx.current_crew_id,
    )
    result = validate_output(output, ctx)
    if telemetry is not None:
        # Final validation outcome for this attempt; failed_checks() is [] on success and
        # the failing check NAMES (never worker data) on failure — safe for the log (Req 12.2).
        telemetry.validation_passed = result.valid
        telemetry.validation_failed_checks = result.failed_checks()
    if not result.valid:
        # Single-attempt contract (upholds Property 9): NO save, NO state change — just
        # AGENT_OUTPUT_INVALID. compose_flow_with_retry catches this to run the one retry and,
        # if that also fails, the NORMAL COMPOSING -> REQUESTED rollback (EMERGENCY does no
        # cleanup here — gap_event owns RECOMPOSING -> FAILED).
        raise _FlowError(
            _ERR_AGENT_OUTPUT_INVALID,
            "agent output failed validation: " + ", ".join(result.failed_checks()),
        )

    # ---- Persist (NORMAL only) ---------------------------------------------------- #
    # NORMAL saves a Crew(PROPOSED) + transitions the WorkRequest; EMERGENCY persists nothing
    # here (crew_id stays None) — gap_event records the recommendations onto the GapEvent.
    crew_id = _persist_and_finalize(output, save_ctx, path=path, event_id=event_id)
    if telemetry is not None:
        # The attempt produced a validated, finalized result. ``saved`` is True on both modes
        # (the compose succeeded); ``crew_id`` is the NORMAL Crew id, or None for EMERGENCY
        # (no Crew is created — the recommendations are the deliverable).
        telemetry.saved = True
        telemetry.crew_id = crew_id

    data: Dict[str, Any] = {
        "mode": output.mode,
        "request_id": output.request_id,
        "recommendations": [rec.model_dump() for rec in output.recommendations],
    }
    if crew_id is not None:
        data["crew_id"] = crew_id  # NORMAL only; EMERGENCY returns no Crew id
    if save_ctx.gap_event_id is not None:
        data["gap_event_id"] = save_ctx.gap_event_id
    return responses.success(data)


# --------------------------------------------------------------------------- #
# compose_flow_with_retry — retry (Req 9.1) + failure cleanup (Req 9.2, 10.9)   #
# --------------------------------------------------------------------------- #
def _apply_failure_cleanup(
    save_ctx: SaveContext, *, path: str, event_id: Optional[str]
) -> None:
    """Perform the per-mode failure cleanup when the retry budget is exhausted.

    This is the ONLY state change on the failure path, and it is deliberately NOT a PROPOSED
    transition (so it never conflicts with Property 9's "no save + no PROPOSED"):

    - **NORMAL** -> rollback ``transition_request_status(COMPOSING -> REQUESTED)`` so manual
      composition becomes possible again (Req 9.2). This is the ``COMPOSING -> REQUESTED``
      rollback that task 6.4 asserts happens exactly once.
    - **EMERGENCY** -> do NOTHING. EMERGENCY runs only on the trusted internal invoke path;
      gap_event owns the terminal ``RECOMPOSING -> FAILED`` transition + manual guidance
      (Req 10.9) and never lets agent_invoke touch the GapEvent or the WorkRequest (it may be
      RUNNING). gap_event sees the AGENT_RETRY_FAILED response and performs its own FAILED
      transition.

    ``path`` / ``event_id`` are unused for EMERGENCY now (retained on the signature for
    call-site symmetry).
    """
    from backend.functions.agent_invoke import shared_gateway as db  # high-level adapter

    if save_ctx.mode == _MODE_NORMAL:
        # NORMAL rollback so the office can compose manually (Req 9.2).
        db.transition_request_status(save_ctx.request_id, _REQ_COMPOSING, _REQ_REQUESTED)
    # EMERGENCY: intentionally no transition — gap_event owns RECOMPOSING -> FAILED (Req 10.9).


def _retry_failed_message(save_ctx: SaveContext, path: str) -> str:
    """Build the AGENT_RETRY_FAILED message, including manual-composition guidance per mode."""
    if save_ctx.mode == _MODE_NORMAL:
        # Rolled back to REQUESTED; the front-end falls back to manual composition.
        return (
            "Agent가 재시도 후에도 유효한 편성을 생성하지 못했습니다. "
            "요청을 수동 편성 가능 상태로 되돌렸습니다."
        )
    # EMERGENCY (trusted internal invoke): gap_event will mark the GapEvent FAILED and attach
    # its own manual-composition guidance.
    return "Agent가 재시도 후에도 유효한 재편성을 생성하지 못했습니다."


def _emit_execution_log(
    agent_input: AgentInput,
    save_ctx: SaveContext,
    telemetry: _ExecutionTelemetry,
    *,
    execution_id: str,
    retried: bool,
) -> None:
    """Build and emit EXACTLY ONE structured :class:`AgentLogRecord` for a whole execution.

    This is the "구조화 로그 기록" step at the end of both sequence diagrams (Req 12.1). It is
    sourced ONLY from counts / ids / flags the flow already holds — the resolved
    ``agent_mode`` and ``request_id`` from ``save_ctx``, ``len(agent_input.candidates)``, and
    the per-execution ``telemetry`` (recommendation count, validation outcome + failed check
    NAMES, fallback/save flags, crew id) — plus the wrapper-owned ``retried`` flag. It passes
    NO worker names / phones, and ``AgentLogRecord`` (``extra="forbid"``) would reject any
    stray key, so the PII-exclusion guarantee holds by construction (Req 12.2).

    Logging is a pure side-effect and must never alter the flow's outcome, so any unexpected
    error while building / emitting the record is caught and swallowed after a diagnostic
    line — the caller's return value or propagated ``_FlowError`` is preserved untouched.
    """
    try:
        record = build_agent_log_record(
            agent_execution_id=execution_id,
            agent_mode=save_ctx.mode,
            request_id=save_ctx.request_id,
            input_candidate_count=len(agent_input.candidates),
            recommendation_count=telemetry.recommendation_count,
            validation_passed=telemetry.validation_passed,
            validation_failed_checks=telemetry.validation_failed_checks,
            retried=retried,
            fallback_used=telemetry.fallback_used,
            saved=telemetry.saved,
            crew_id=telemetry.crew_id,
        )
        log_agent_execution(record)
    except Exception:  # noqa: BLE001 - logging must never break the compose flow
        _logger.exception("failed to emit structured agent execution log")


def compose_flow_with_retry(
    agent_input: AgentInput,
    save_ctx: SaveContext,
    *,
    path: str,
    event_id: Optional[str] = None,
    compose_fn: Optional[Any] = None,
    fallback_enabled: Optional[bool] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    """Wrap :func:`compose_flow` with the ONE retry and the failure cleanup (task 6.3).

    This is the design's ``compose_flow`` orchestration: it runs the single attempt
    (:func:`compose_flow`) up to twice and, when the budget is exhausted, applies the
    path/mode failure cleanup and raises ``AGENT_RETRY_FAILED``. The handler entry paths call
    THIS function; the single attempt is factored out so it stays directly testable.

    Retry policy (Req 9.1 / 9.2, design "compose_flow의 실행 규칙")
    -------------------------------------------------------------
    - A **validation failure** (``AGENT_OUTPUT_INVALID``) discards the output, records an
      error log, and triggers exactly ONE retry — at most ``_MAX_COMPOSE_ATTEMPTS`` (2)
      compose attempts total. A second validation failure exhausts the budget.
    - A **Bedrock failure with fallback OFF** (``AGENT_RETRY_FAILED`` out of the single
      attempt) is NOT retried — retrying a down Bedrock is pointless per the design's Error
      Handling mapping — and goes straight to cleanup. (With fallback ON, the single attempt
      already substituted ``demo_fallback`` and typically succeeds; it never surfaces as a
      Bedrock ``AGENT_RETRY_FAILED`` here.)

    On exhaustion (either the retry-soaked validation failure or a non-retryable Bedrock
    failure) it calls :func:`_apply_failure_cleanup` (NORMAL rollback / EMERGENCY-external
    ``RECOMPOSING -> FAILED`` / EMERGENCY-internal no-op) and raises ``AGENT_RETRY_FAILED``
    with per-path manual-composition guidance. It never saves on the failure path, and its
    only state change is the non-PROPOSED cleanup transition — so Property 9 still holds.

    ``fallback_enabled`` is resolved ONCE here (arg overrides env) and threaded into every
    attempt so both attempts share one flag decision.
    """
    resolved_fallback = _resolve_fallback_enabled(fallback_enabled)

    # One telemetry object + one execution id for the WHOLE execution (task 9.2). The single
    # attempt(s) below populate telemetry; the finally emits exactly ONE structured record.
    telemetry = _ExecutionTelemetry()
    execution_id = new_execution_id()
    attempts_made = 0
    try:
        for attempt in range(1, _MAX_COMPOSE_ATTEMPTS + 1):
            attempts_made = attempt
            try:
                return compose_flow(
                    agent_input,
                    save_ctx,
                    path=path,
                    event_id=event_id,
                    compose_fn=compose_fn,
                    fallback_enabled=resolved_fallback,
                    timeout_s=timeout_s,
                    telemetry=telemetry,
                )
            except _FlowError as exc:
                # A validation failure is the only retryable outcome (Req 9.1). A Bedrock
                # failure with fallback OFF (AGENT_RETRY_FAILED) is terminal — do not retry a
                # down Bedrock.
                retryable = exc.code == _ERR_AGENT_OUTPUT_INVALID
                # Minimal error log on the discard/retry (Req 9.1) — kept as a single
                # lightweight line. The full structured AgentLogRecord for the whole execution
                # is emitted once in the finally below (task 9.2).
                _logger.error(
                    "agent compose attempt %d/%d failed (%s); discarding output: %s",
                    attempt,
                    _MAX_COMPOSE_ATTEMPTS,
                    exc.code,
                    exc.message,
                )
                if retryable and attempt < _MAX_COMPOSE_ATTEMPTS:
                    continue  # exactly one retry on a validation failure
                break  # retry exhausted, or a non-retryable Bedrock failure

        # Budget exhausted -> path/mode failure cleanup + AGENT_RETRY_FAILED (Req 9.2, 10.9).
        _apply_failure_cleanup(save_ctx, path=path, event_id=event_id)
        raise _FlowError(_ERR_AGENT_RETRY_FAILED, _retry_failed_message(save_ctx, path))
    finally:
        # Emit EXACTLY ONE structured record per execution, on every exit (success return,
        # AGENT_RETRY_FAILED raise, or any unexpected error). ``retried`` is true iff a second
        # attempt ran (attempts_made > 1). Placed in finally so it runs once and cannot be
        # skipped, and _emit_execution_log never raises, so the return/raise is preserved.
        _emit_execution_log(
            agent_input,
            save_ctx,
            telemetry,
            execution_id=execution_id,
            retried=attempts_made > 1,
        )


# --------------------------------------------------------------------------- #
# Per-path entry handlers                                                      #
# --------------------------------------------------------------------------- #
def _handle_normal(event: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """NORMAL (external ``agent-compose``): OFFICE gate -> lock -> assemble -> compose_flow."""
    from backend.functions.agent_invoke import shared_gateway as db  # high-level adapter

    principal = _require_office(event)  # FORBIDDEN if not OFFICE (Req 11.1, 11.2)

    # State guard: acquire the REQUESTED -> COMPOSING lock (Req 6.6/6.7). A failed
    # conditional write (wrong state / concurrent duplicate / missing request) -> conflict.
    if not db.transition_request_status(request_id, _REQ_REQUESTED, _REQ_COMPOSING):
        raise _FlowError(
            _ERR_STATE_CONFLICT,
            f"work request {request_id!r} not in {_REQ_REQUESTED} (already composing?)",
        )

    office_id = principal.office_id
    if not office_id:
        record = db.get_work_request(request_id)
        office_id = (record or {}).get("office_id")

    agent_input = assemble_normal_input(request_id, office_id)
    save_ctx = SaveContext(
        mode=_MODE_NORMAL, request_id=request_id, office_id=office_id
    )
    # Retry-orchestrated (task 6.3): on retry-exhausted validation failure, the wrapper rolls
    # the WorkRequest back COMPOSING -> REQUESTED so manual composition is possible (Req 9.2).
    return compose_flow_with_retry(agent_input, save_ctx, path=_PATH_EXTERNAL)


def _handle_internal(event: Dict[str, Any]) -> Dict[str, Any]:
    """EMERGENCY trusted internal invoke: consume gap_event's payload; no OFFICE re-gate.

    No OFFICE gate (Req 11.3 — trust is IAM-enforced) and no state guard: gap_event has
    already acquired ``DETECTED -> RECOMPOSING`` before invoking, so the GapEvent is
    already ``RECOMPOSING`` and this path ACCEPTS that as the expected state (no re-lock,
    no STATE_CONFLICT). The GapEvent terminal transition is gap_event's (task 8.5); this
    path passes ``_PATH_INTERNAL`` so compose_flow does NOT transition the GapEvent.
    """
    raw_input = event.get(_PAYLOAD_AGENT_INPUT)
    if raw_input is None:
        raise ValueError("internal invoke payload missing 'agent_input'")
    agent_input = (
        raw_input
        if isinstance(raw_input, AgentInput)
        else AgentInput.model_validate(raw_input)
    )
    event_id = event.get(_PAYLOAD_EVENT_ID)

    save_ctx = SaveContext(
        mode=_MODE_EMERGENCY,
        request_id=agent_input.request.request_id,
        office_id=event.get(_PAYLOAD_OFFICE_ID),
        current_crew_id=event.get(_PAYLOAD_CURRENT_CREW_ID),
        gap_event_id=event_id,
    )
    # Internal route: gap_event owns BOTH terminal transitions (PROPOSED on success, FAILED on
    # retry-exhausted failure per task 8.5). This path never transitions the GapEvent — on
    # failure the wrapper returns AGENT_RETRY_FAILED and gap_event performs its own FAILED
    # transition + guidance.
    return compose_flow_with_retry(
        agent_input, save_ctx, path=_PATH_INTERNAL, event_id=event_id
    )


# --------------------------------------------------------------------------- #
# Lambda entry point                                                           #
# --------------------------------------------------------------------------- #
def handler(event: Any, context: Any = None) -> Dict[str, Any]:
    """agent_invoke Lambda entry point: route by event shape, then dispatch.

    Routing (see module docstring): a trusted internal invoke (plain dict + marker) ->
    EMERGENCY internal path (gap_event's EventBridge-driven recomposition); otherwise an API
    Gateway proxy event -> NORMAL (``agent-compose``). There is no external EMERGENCY route.
    Every mapped failure is raised internally as a ``_FlowError`` (the internal flow codes)
    or, from the auth gate, as 담당자 A's ``responses.ApiError`` (UNAUTHORIZED / FORBIDDEN);
    both are converted here to a single proxy error response. Success paths return
    ``responses.success(...)``.
    """
    from backend.shared import responses  # lazy: real Layer in prod
    from backend.shared.responses import ApiError

    try:
        if _is_internal_invoke(event):
            return _handle_internal(event)
        # The only external API route is NORMAL agent-compose (_classify_api_event raises on
        # any unrecognized route).
        _classify_api_event(event)
        return _handle_normal(event, _path_param(event, "requestId"))
    except _FlowError as exc:
        return responses.error(exc.code, exc.message)
    except ApiError as exc:
        # Auth gate (get_principal / require_role) raises this — return its proxy response.
        return exc.to_response()
