"""Execution-flow unit tests for the agent_invoke Lambda handler (담당자 B, task 5.5).

These are EXAMPLE / UNIT tests (plain pytest - no Hypothesis, no ``property`` marker).
They exercise the control flow of ``backend/functions/agent_invoke/handler.py`` end-to-end
against the in-memory ``FakeSharedDB`` that 담당자 B's code now reaches through the
``shared_gateway`` adapter (installed by the ``install_shared`` fixture), with the Bedrock
``compose`` call replaced by a deterministic fake so no live model is invoked.

Post-checkpoint-2 reality
-------------------------
- **DB**: the ten high-level DB functions are monkeypatched onto ``FakeSharedDB`` via the
  ``shared_gateway`` adapter (``install_shared``). The real ``backend.shared`` package stays
  intact.
- **Auth**: 담당자 B's handler consumes 담당자 A's REAL ``auth.get_principal`` +
  ``Principal.require_role``, driven by claim-bearing API-Gateway events
  (``requestContext.authorizer.claims`` with ``custom:role`` / ``custom:office_id``). A
  non-OFFICE external caller yields a FORBIDDEN **proxy** error.
- **Responses**: the handler returns API-Gateway proxy dicts (``{statusCode, headers,
  body}``); the ``{success, data|error}`` envelope is JSON in ``body`` (parsed by
  :func:`_body`).

Concerns covered (one clearly-named test per concern; see tasks.md task 5.5): routing +
mode, external OFFICE gate vs. trusted-internal skip, per-path state guard, save split,
EMERGENCY terminal-transition ownership, and the freshest-snapshot validation.

Python 3.9: ``from __future__ import annotations`` keeps annotations lazy.
"""
from __future__ import annotations

import json
from collections import Counter

import pytest

from agent.schemas import (
    AgentInput,
    AgentOutput,
    Candidate,
    FixedMember,
    Priority,
    Recommendation,
    RequestSpec,
    TradeRequirement,
)
from backend.functions.agent_invoke import handler
from backend.functions.agent_invoke.persistence import SaveContext
from backend.functions.gap_event.emergency_payload import build_emergency_payload

OFFICE_ID = "OFFICE001"


def _body(resp):
    """Decode the ``{success, data|error}`` envelope from an API-Gateway proxy response."""
    return json.loads(resp["body"])


def _claims(role="OFFICE", office_id=OFFICE_ID, sub="user-1"):
    """Cognito-style custom claims for an API-Gateway authorizer context."""
    claims = {"sub": sub, "custom:role": role}
    if office_id:
        claims["custom:office_id"] = office_id
    return claims


# --------------------------------------------------------------------------- #
# Fake compose functions (no live Bedrock)                                     #
# --------------------------------------------------------------------------- #
def _valid_output_for(agent_input: AgentInput) -> AgentOutput:
    """Build a rule-compliant :class:`AgentOutput` derived from ``agent_input``.

    Produces ONE recommendation (rank 1) whose members exactly satisfy the request's
    required trade/headcount: every EMERGENCY ``fixed_members`` entry is kept, and the
    remaining per-trade shortage is filled from the candidate pool. ``total_cost`` is the
    sum of the retained fixed-member wages plus the picked candidates' wages, matching the
    freshest ``get_workers`` snapshot the validator uses (tests seed matching wages).
    """
    required: Counter = Counter()
    for tr in agent_input.request.required_workers:
        required[tr.trade] += tr.count

    fixed_ids = [f.worker_id for f in agent_input.fixed_members]
    remaining = Counter(required)
    for f in agent_input.fixed_members:
        if remaining.get(f.trade, 0) > 0:
            remaining[f.trade] -= 1

    by_trade: dict = {}
    for c in agent_input.candidates:
        by_trade.setdefault(c.trade, []).append(c)

    picked = []
    for trade, need in remaining.items():
        if need > 0:
            picked.extend(by_trade.get(trade, [])[:need])

    member_ids = list(fixed_ids) + [c.worker_id for c in picked]
    total_cost = sum(f.desired_daily_wage for f in agent_input.fixed_members) + sum(
        c.desired_daily_wage for c in picked
    )
    return AgentOutput(
        mode=agent_input.mode,
        request_id=agent_input.request.request_id,
        recommendations=[
            Recommendation(
                rank=1,
                member_ids=member_ids,
                total_cost=total_cost,
                reason="필요 직종 인원을 충족하는 팀 구성",
                considerations=["직종 인원 충족", "예산 내"],
            )
        ],
    )


def _fake_compose(agent_input, *, timeout_s=None, agent=None):
    """Stand-in for ``agent.crew_agent.compose`` returning a valid output (no Bedrock)."""
    return _valid_output_for(agent_input)


def _boom_compose(agent_input, *, timeout_s=None, agent=None):
    """Compose that must never be reached (asserts short-circuit before agent execution)."""
    raise AssertionError("compose must not be called on this path")


# --------------------------------------------------------------------------- #
# Event / payload builders                                                     #
# --------------------------------------------------------------------------- #
def _normal_event(request_id="REQ1", *, role="OFFICE", office_id=OFFICE_ID):
    """An API Gateway proxy event for ``POST .../requests/{requestId}/agent-compose``."""
    return {
        "resource": "/office/requests/{requestId}/agent-compose",
        "httpMethod": "POST",
        "requestContext": {
            "requestId": "apigw-normal",
            "authorizer": {"claims": _claims(role, office_id)},
        },
        "pathParameters": {"requestId": request_id},
    }


def _recompose_event(event_id="GE1", *, role="OFFICE", office_id=OFFICE_ID):
    """An API Gateway proxy event for ``POST .../gap-events/{eventId}/agent-recompose``."""
    return {
        "resource": "/office/gap-events/{eventId}/agent-recompose",
        "httpMethod": "POST",
        "requestContext": {
            "requestId": "apigw-emergency",
            "authorizer": {"claims": _claims(role, office_id)},
        },
        "pathParameters": {"eventId": event_id},
    }


def _internal_payload(agent_input, *, event_id="GE1", office_id=OFFICE_ID,
                      current_crew_id="CREW1"):
    """gap_event's trusted internal invoke payload (a plain dict + marker, no claims).

    Deliberately carries NO authorizer claims: the internal path is IAM-trusted and never
    calls ``get_principal`` (Req 11.3), so a claimless payload flowing through to success is
    itself proof the OFFICE gate was skipped.
    """
    return {
        handler.INTERNAL_INVOKE_MARKER: True,
        "mode": "EMERGENCY",
        "event_id": event_id,
        "agent_input": agent_input.model_dump(),
        "office_id": office_id,
        "current_crew_id": current_crew_id,
    }


def _emergency_agent_input(request_id="REQ_E"):
    """A ready-to-consume EMERGENCY ``AgentInput`` (fixed F1 + candidate N1, FORMWORK:2)."""
    request = RequestSpec(
        request_id=request_id,
        required_workers=[TradeRequirement(trade="FORMWORK", count=2)],
        budget=1_000_000,
        priority=Priority(cost="HIGH", skill="MEDIUM", teamwork="LOW"),
        site="현장 E",
        work_date="2025-01-02",
        start_time="07:00",
    )
    fixed = [FixedMember(worker_id="F1", trade="FORMWORK", desired_daily_wage=150_000)]
    candidates = [
        Candidate(worker_id="N1", trade="FORMWORK", skill_level=3,
                  desired_daily_wage=160_000, career_years=4)
    ]
    return build_emergency_payload(request, fixed, candidates, [])


# --------------------------------------------------------------------------- #
# Seeding helpers                                                              #
# --------------------------------------------------------------------------- #
def _seed_normal(db, *, request_id="REQ1", status="REQUESTED", office_id=OFFICE_ID):
    """Seed a REQUESTED WorkRequest + two READY FORMWORK candidates for the NORMAL flow."""
    db.add_work_request(
        request_id,
        status=status,
        office_id=office_id,
        required_workers=[{"trade": "FORMWORK", "count": 2}],
        budget=1_000_000,
        priority={"cost": "HIGH", "skill": "MEDIUM", "teamwork": "LOW"},
        site_name="현장 A",
        work_date="2025-01-01",
        start_time="08:00",
    )
    db.add_worker("W1", office_id=office_id, state="READY", trade="FORMWORK",
                  desired_daily_wage=150_000, skill_level=3, career_years=5)
    db.add_worker("W2", office_id=office_id, state="READY", trade="FORMWORK",
                  desired_daily_wage=160_000, skill_level=4, career_years=8)


def _seed_emergency(db, *, event_id="GE1", crew_id="CREW1", request_id="REQ_E",
                    office_id=OFFICE_ID, gap_status="DETECTED"):
    """Seed a crew (F1 stays, F2 departs), a GapEvent, and workers for the EMERGENCY flow."""
    db.add_work_request(
        request_id,
        status="RUNNING",  # during emergency the original request may already be RUNNING
        office_id=office_id,
        required_workers=[{"trade": "FORMWORK", "count": 2}],
        budget=1_000_000,
        priority={"cost": "HIGH", "skill": "MEDIUM", "teamwork": "LOW"},
        site_name="현장 E",
        work_date="2025-01-02",
        start_time="07:00",
    )
    db.add_crew(
        crew_id,
        request_id=request_id,
        office_id=office_id,
        active_members=[
            {"worker_id": "F1", "trade": "FORMWORK", "desired_daily_wage": 150_000,
             "state": "RUNNING"},
            {"worker_id": "F2", "trade": "FORMWORK", "desired_daily_wage": 155_000,
             "state": "RUNNING"},
        ],
    )
    # Real GapEvent schema names the departed workers ``missing_worker_ids`` and the kind
    # ``gap_type``; seed both so the server-side external assembly reads them correctly.
    db.add_gap_event(event_id, status=gap_status, crew_id=crew_id,
                     missing_worker_ids=["F2"], gap_type="NO_SHOW", office_id=office_id)
    db.add_worker("F1", office_id=office_id, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=150_000, current_crew_id=crew_id,
                  skill_level=4, career_years=9)
    db.add_worker("F2", office_id=office_id, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=155_000, current_crew_id=crew_id,
                  skill_level=3, career_years=6)
    db.add_worker("N1", office_id=office_id, state="READY", trade="FORMWORK",
                  desired_daily_wage=160_000, current_crew_id=None,
                  skill_level=3, career_years=4)


def _seed_internal_workers(db, *, crew_id="CREW1", office_id=OFFICE_ID):
    """Seed just the workers the internal-invoke validation snapshot needs (F1 fixed, N1 new)."""
    db.add_worker("F1", office_id=office_id, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=150_000, current_crew_id=crew_id,
                  skill_level=4, career_years=9)
    db.add_worker("N1", office_id=office_id, state="READY", trade="FORMWORK",
                  desired_daily_wage=160_000, current_crew_id=None,
                  skill_level=3, career_years=4)


def _call_index(db, method):
    """Index of the first recorded call to ``method`` in ``db.calls`` (-1 if absent)."""
    for i, c in enumerate(db.calls):
        if c.get("method") == method:
            return i
    return -1


# =========================================================================== #
# 1. Routing & mode setting                                                    #
# =========================================================================== #
def test_normal_route_runs_in_normal_mode_and_succeeds(install_shared, monkeypatch):
    """agent-compose routes to NORMAL mode and produces a validated, saved proposal."""
    db = install_shared.db
    _seed_normal(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_normal_event("REQ1"))
    body = _body(resp)

    assert body["success"] is True
    assert body["data"]["mode"] == "NORMAL"
    assert body["data"]["request_id"] == "REQ1"
    assert body["data"]["crew_id"]  # a crew was persisted
    assert len(body["data"]["recommendations"]) == 1
    assert len(db.saved_crews) == 1


def test_emergency_external_route_runs_in_emergency_mode(install_shared, monkeypatch):
    """agent-recompose routes to EMERGENCY mode (server-side payload assembly)."""
    db = install_shared.db
    _seed_emergency(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_recompose_event("GE1"))
    body = _body(resp)

    assert body["success"] is True
    assert body["data"]["mode"] == "EMERGENCY"
    assert body["data"]["gap_event_id"] == "GE1"
    assert len(db.saved_crews) == 1


def test_internal_invoke_routes_to_emergency_mode(install_shared, monkeypatch):
    """A trusted internal invoke (plain dict + marker) routes to EMERGENCY mode."""
    db = install_shared.db
    _seed_internal_workers(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_internal_payload(_emergency_agent_input()))
    body = _body(resp)

    assert body["success"] is True
    assert body["data"]["mode"] == "EMERGENCY"
    assert len(db.saved_crews) == 1


# =========================================================================== #
# 2. Authorization - external OFFICE gate vs. trusted internal path            #
# =========================================================================== #
@pytest.mark.parametrize("role", ["COMPANY", "WORKER"])
def test_external_compose_rejects_non_office_with_forbidden(install_shared, monkeypatch, role):
    """External/direct agent-compose by a non-OFFICE subject is FORBIDDEN (no side effects)."""
    db = install_shared.db
    _seed_normal(db)
    monkeypatch.setattr(handler, "compose", _boom_compose)  # must not reach compose

    resp = handler.handler(_normal_event("REQ1", role=role))
    body = _body(resp)

    assert resp["statusCode"] == 403
    assert body["success"] is False
    assert body["error"]["code"] == "FORBIDDEN"
    # The OFFICE gate rejected the caller and nothing was written.
    assert db.saved_crews == []
    assert db.status_transitions == []
    assert db.gap_status_transitions == []


def test_external_recompose_rejects_company_with_forbidden(install_shared, monkeypatch):
    """External/direct agent-recompose by a COMPANY subject is FORBIDDEN (Req 11.4)."""
    db = install_shared.db
    _seed_emergency(db)
    monkeypatch.setattr(handler, "compose", _boom_compose)

    resp = handler.handler(_recompose_event("GE1", role="COMPANY"))
    body = _body(resp)

    assert body["success"] is False
    assert body["error"]["code"] == "FORBIDDEN"
    assert db.saved_crews == []
    assert db.gap_status_transitions == []  # rejected before the lock is acquired


def test_internal_invoke_from_company_registered_gap_is_not_forbidden(install_shared, monkeypatch):
    """A COMPANY-registered gap's internal invoke proceeds WITHOUT a FORBIDDEN (Req 11.3).

    The internal payload carries NO claims; if the internal path had applied the OFFICE gate
    (get_principal), a claimless event would raise UNAUTHORIZED. Flowing through to a saved
    proposal proves the gate is skipped entirely on the trusted internal path.
    """
    db = install_shared.db
    _seed_internal_workers(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_internal_payload(_emergency_agent_input()))
    body = _body(resp)

    assert body["success"] is True  # NOT forbidden / unauthorized
    assert len(db.saved_crews) == 1


# =========================================================================== #
# 3. State guard - per-path branching                                          #
# =========================================================================== #
def test_normal_conditional_write_failure_returns_state_conflict(install_shared, monkeypatch):
    """NORMAL: a failed REQUESTED->COMPOSING conditional write -> STATE_CONFLICT (no save)."""
    db = install_shared.db
    # Already COMPOSING => the REQUESTED->COMPOSING conditional transition fails.
    _seed_normal(db, status="COMPOSING")
    monkeypatch.setattr(handler, "compose", _boom_compose)

    resp = handler.handler(_normal_event("REQ1"))
    body = _body(resp)

    assert body["success"] is False
    assert body["error"]["code"] == "STATE_CONFLICT"
    # The single (failed) transition attempt was recorded; nothing was saved.
    assert len(db.status_transitions) == 1
    assert db.status_transitions[0]["ok"] is False
    assert db.saved_crews == []


def test_emergency_external_missing_gap_event_returns_not_found(install_shared, monkeypatch):
    """EMERGENCY external: an eventId with no GapEvent -> GAP_EVENT_NOT_FOUND (Req 10.10)."""
    db = install_shared.db  # no gap event seeded
    monkeypatch.setattr(handler, "compose", _boom_compose)

    resp = handler.handler(_recompose_event("MISSING"))
    body = _body(resp)

    assert body["success"] is False
    assert body["error"]["code"] == "GAP_EVENT_NOT_FOUND"
    # Not-found is reported BEFORE any lock attempt.
    assert db.gap_status_transitions == []
    assert db.saved_crews == []


@pytest.mark.parametrize("gap_status", ["RECOMPOSING", "PROPOSED", "FAILED"])
def test_emergency_external_non_detected_state_returns_conflict(install_shared, monkeypatch, gap_status):
    """EMERGENCY external: GapEvent not in DETECTED -> STATE_CONFLICT (no queueing)."""
    db = install_shared.db
    _seed_emergency(db, gap_status=gap_status)
    monkeypatch.setattr(handler, "compose", _boom_compose)

    resp = handler.handler(_recompose_event("GE1"))
    body = _body(resp)

    assert body["success"] is False
    assert body["error"]["code"] == "STATE_CONFLICT"
    # Exactly one (failed) DETECTED->RECOMPOSING attempt; nothing saved/re-transitioned.
    assert len(db.gap_status_transitions) == 1
    assert db.gap_status_transitions[0]["ok"] is False
    assert db.saved_crews == []


def test_emergency_external_duplicate_recompose_returns_conflict(install_shared, monkeypatch):
    """EMERGENCY external: a duplicate recompose on the same GapEvent -> STATE_CONFLICT."""
    db = install_shared.db
    _seed_emergency(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    first = handler.handler(_recompose_event("GE1"))
    second = handler.handler(_recompose_event("GE1"))

    assert _body(first)["success"] is True  # first acquires the lock and completes
    assert _body(second)["success"] is False
    assert _body(second)["error"]["code"] == "STATE_CONFLICT"  # not queued - rejected
    assert len(db.saved_crews) == 1  # the duplicate saved nothing


def test_internal_invoke_accepts_recomposing_without_conflict(install_shared, monkeypatch):
    """Trusted internal invoke ACCEPTS an already-RECOMPOSING GapEvent and never conflicts."""
    db = install_shared.db
    _seed_internal_workers(db)
    db.add_gap_event("GE1", status="RECOMPOSING", crew_id="CREW1")
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_internal_payload(_emergency_agent_input()))

    assert _body(resp)["success"] is True
    assert len(db.saved_crews) == 1
    # No GapEvent transition performed by the internal path, and its status is unchanged.
    assert db.gap_status_transitions == []
    assert db.gap_events["GE1"]["status"] == "RECOMPOSING"


# =========================================================================== #
# 4. Save split - NORMAL transitions WorkRequest, EMERGENCY does not           #
# =========================================================================== #
def test_normal_save_transitions_work_request_to_proposed(install_shared, monkeypatch):
    """NORMAL takes the save_normal_proposal path: Crew(PROPOSED) + WorkRequest ->PROPOSED."""
    db = install_shared.db
    _seed_normal(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_normal_event("REQ1"))

    assert _body(resp)["success"] is True
    # Crew stored as a PROPOSED, AGENT-sourced proposal.
    assert len(db.saved_crews) == 1
    assert db.saved_crews[0]["status"] == "PROPOSED"
    assert db.saved_crews[0]["source"] == "AGENT"
    # Two WorkRequest transitions: the entry lock and the terminal COMPOSING->PROPOSED.
    kinds = [(t["expected"], t["target"], t["ok"]) for t in db.status_transitions]
    assert ("REQUESTED", "COMPOSING", True) in kinds
    assert ("COMPOSING", "PROPOSED", True) in kinds
    assert db.work_requests["REQ1"]["status"] == "PROPOSED"


def test_emergency_external_save_does_not_transition_work_request(install_shared, monkeypatch):
    """EMERGENCY takes save_emergency_proposal: Crew saved, WorkRequest NEVER transitioned."""
    db = install_shared.db
    _seed_emergency(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_recompose_event("GE1"))
    body = _body(resp)

    assert body["success"] is True
    assert len(db.saved_crews) == 1
    assert db.saved_crews[0]["status"] == "PROPOSED"
    assert db.saved_crews[0]["source"] == "AGENT"
    # Crew↔GapEvent linkage is surfaced in the RESPONSE (the canonical Crew schema has no
    # gap field), not persisted on the Crew item.
    assert body["data"]["gap_event_id"] == "GE1"
    # EMERGENCY must not touch the WorkRequest state machine (it may be RUNNING).
    assert db.status_transitions == []
    assert db.work_requests["REQ_E"]["status"] == "RUNNING"


def test_internal_invoke_save_does_not_transition_work_request(install_shared, monkeypatch):
    """Internal EMERGENCY invoke also saves via save_emergency_proposal (no WorkRequest change)."""
    db = install_shared.db
    _seed_internal_workers(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_internal_payload(_emergency_agent_input()))

    assert _body(resp)["success"] is True
    assert len(db.saved_crews) == 1
    assert db.status_transitions == []  # no WorkRequest transition on the internal path


# =========================================================================== #
# 5. EMERGENCY terminal-transition ownership (per path)                        #
# =========================================================================== #
def test_emergency_external_owns_recomposing_to_proposed_transition(install_shared, monkeypatch):
    """External agent-recompose: compose_flow performs RECOMPOSING->PROPOSED on save (Req 10.7)."""
    db = install_shared.db
    _seed_emergency(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_recompose_event("GE1"))

    assert _body(resp)["success"] is True
    transitions = [(t["expected"], t["target"], t["ok"]) for t in db.gap_status_transitions]
    assert transitions == [
        ("DETECTED", "RECOMPOSING", True),   # entry lock (self-acquired)
        ("RECOMPOSING", "PROPOSED", True),   # terminal transition owned by agent_invoke
    ]
    assert db.gap_events["GE1"]["status"] == "PROPOSED"


def test_internal_invoke_does_not_transition_gap_event(install_shared, monkeypatch):
    """Trusted internal invoke: agent_invoke does NOT transition the GapEvent (gap_event owns it)."""
    db = install_shared.db
    _seed_internal_workers(db)
    db.add_gap_event("GE1", status="RECOMPOSING", crew_id="CREW1")
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_internal_payload(_emergency_agent_input()))

    assert _body(resp)["success"] is True
    assert len(db.saved_crews) == 1
    # The terminal RECOMPOSING->PROPOSED transition is gap_event's responsibility, not ours.
    assert db.gap_status_transitions == []
    assert db.gap_events["GE1"]["status"] == "RECOMPOSING"


# =========================================================================== #
# 6. Freshest snapshot (검증 직전 최신 스냅샷)                                    #
# =========================================================================== #
def test_normal_reads_fresh_snapshot_before_validation_and_save(install_shared, monkeypatch):
    """get_workers is read for the recommended members and BEFORE the crew is saved."""
    db = install_shared.db
    _seed_normal(db)
    monkeypatch.setattr(handler, "compose", _fake_compose)

    resp = handler.handler(_normal_event("REQ1"))

    assert _body(resp)["success"] is True
    get_workers_calls = db.method_calls("get_workers")
    assert len(get_workers_calls) == 1
    assert get_workers_calls[0]["worker_ids"] == ["W1", "W2"]  # the recommended members
    # The fresh read happened before the crew was persisted (validation sits between them).
    assert 0 <= _call_index(db, "get_workers") < _call_index(db, "save_crew")


def test_compose_flow_validates_against_freshest_snapshot_over_stale_pool(install_shared):
    """The injected fresh snapshot (get_workers) - not the stale agent-input pool - drives validity."""
    db = install_shared.db
    db.add_worker("N1", office_id=OFFICE_ID, state="READY", trade="FORMWORK",
                  desired_daily_wage=175_000, current_crew_id=None,
                  skill_level=3, career_years=4)

    # Stale agent-input pool: wage 100_000 (differs from the fresh DB value).
    stale_candidate = Candidate(worker_id="N1", trade="FORMWORK", skill_level=3,
                                desired_daily_wage=100_000, career_years=4)
    agent_input = AgentInput(
        mode="NORMAL",
        request=RequestSpec(
            request_id="REQF",
            required_workers=[TradeRequirement(trade="FORMWORK", count=1)],
            budget=1_000_000,
            priority=Priority(cost="MEDIUM", skill="MEDIUM", teamwork="MEDIUM"),
            site="현장 F", work_date="2025-04-01", start_time="08:00",
        ),
        candidates=[stale_candidate],
    )
    save_ctx = SaveContext(mode="NORMAL", request_id="REQF", office_id=OFFICE_ID)

    # (a) total_cost matching the FRESH wage (175_000) validates and saves.
    def _fresh_valued(ai, *, timeout_s=None, agent=None):
        return AgentOutput(
            mode="NORMAL", request_id="REQF",
            recommendations=[Recommendation(rank=1, member_ids=["N1"], total_cost=175_000,
                                            reason="fresh", considerations=["ok"])],
        )

    resp = handler.compose_flow(agent_input, save_ctx, path=handler._PATH_EXTERNAL,
                                compose_fn=_fresh_valued)
    assert _body(resp)["success"] is True
    assert len(db.saved_crews) == 1
    # The fresh read was for the recommended member only.
    assert db.method_calls("get_workers")[0]["worker_ids"] == ["N1"]

    # (b) total_cost matching the STALE pool wage (100_000) fails validation - nothing saved.
    def _stale_valued(ai, *, timeout_s=None, agent=None):
        return AgentOutput(
            mode="NORMAL", request_id="REQF",
            recommendations=[Recommendation(rank=1, member_ids=["N1"], total_cost=100_000,
                                            reason="stale", considerations=["no"])],
        )

    with pytest.raises(handler._FlowError) as excinfo:
        handler.compose_flow(agent_input, save_ctx, path=handler._PATH_EXTERNAL,
                             compose_fn=_stale_valued)
    assert excinfo.value.code == "AGENT_OUTPUT_INVALID"
    assert len(db.saved_crews) == 1  # unchanged - the invalid output was NOT saved
