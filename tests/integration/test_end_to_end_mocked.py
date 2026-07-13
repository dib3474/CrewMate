"""Mocked end-to-end integration test — the capstone for 담당자 B (task 9.4).

This is the REQUIRED (별표 없음) integration test that automatically verifies the code
paths behind demo scenarios 2 and 3 (요청→AI 편성→저장, C 노쇼→A+B+E 추천→저장). Unlike the
per-module unit tests, it wires the REAL modules together and mocks ONLY the external
boundaries — so it proves the pieces actually compose into the three designed flows.

What is exercised REAL vs. what is mocked (design.md → "Testing Strategy" → 통합/모킹)
------------------------------------------------------------------------------------
REAL (wired together, not stubbed):
- ``agent_invoke`` handler → assembler → validator → persistence orchestration.
- ``gap_event`` handler → gap_logic (``compute_fixed_members`` / ``compute_missing``) →
  ``build_emergency_payload`` → the trusted internal invoke of ``agent_invoke``.
- The freshest-snapshot validation context (``build_validation_context``) built from the
  same in-memory DB the flow writes to.

Mocked / stubbed (the four external boundaries task 9.4 calls out):
- ``shared/db``   — the in-memory :class:`FakeSharedDB` installed under ``backend.shared.db``
  by the ``install_shared`` fixture (conftest.py). Both Lambdas import it lazily, so they
  share ONE instance and observe consistent state.
- ``shared/auth`` — the :class:`StubAuth` installed under ``backend.shared.auth``.
- ``Bedrock``     — the live ``compose`` call is monkeypatched to a deterministic fake that
  derives a rule-compliant :class:`AgentOutput` from the assembled input (no live model).
- ``Lambda invoke`` — the ``gap_event → agent_invoke`` synchronous invoke seam
  (``gap_event.handler.invoke_agent``) is monkeypatched to call ``agent_invoke``'s REAL
  handler directly with the internal payload. That is the whole point of the EMERGENCY
  internal test: it drives the true internal-invoke CONTRACT end-to-end (marker + payload
  shape + IAM-trusted skip-the-OFFICE-gate) against the SAME FakeSharedDB, rather than
  stubbing agent_invoke out.

The three end-to-end paths (task 9.4)
-------------------------------------
1. NORMAL (demo scenario 2): OFFICE ``agent-compose`` → assemble → compose → freshest
   snapshot → validate → Crew(PROPOSED, source=AGENT) saved + WorkRequest
   ``COMPOSING→PROPOSED``.                                        (Req 6.2, 6.5, 8.1, 8.2)
2. EMERGENCY, trusted internal invoke (demo scenario 3, C no-show → A+B+E): a COMPANY-
   registered gap → gap_event computes fixed_members/shortage and locks
   ``DETECTED→RECOMPOSING`` → synchronous internal invoke of agent_invoke → Crew(PROPOSED)
   saved WITHOUT a WorkRequest transition → **gap_event** owns the terminal
   ``RECOMPOSING→PROPOSED``.                                      (Req 10.6, 10.7)
3. EMERGENCY, external/direct ``agent-recompose``: OFFICE call → agent_invoke self-acquires
   ``DETECTED→RECOMPOSING`` → **server-side** payload assembly (reusing
   ``compute_fixed_members`` / ``compute_missing`` / ``build_emergency_payload``) → Crew
   (PROPOSED) saved WITHOUT a WorkRequest transition → **agent_invoke (compose_flow)** owns
   the terminal ``RECOMPOSING→PROPOSED``.                         (Req 6.2, 10.6, 10.7)

Both EMERGENCY paths stop at PROPOSED — APPROVED/FILLED, worker READY→RESERVED→RUNNING
assignment, and departed-worker INACTIVE handling are 담당자 A's emergency approval API and
are explicitly asserted to NOT occur here.

These are EXAMPLE / integration tests (plain pytest — no Hypothesis, no ``property`` marker).

Python 3.9: ``from __future__ import annotations`` keeps annotations lazy.
"""
from __future__ import annotations

import json
from collections import Counter

from agent.schemas import AgentInput, AgentOutput, Recommendation
from backend.functions.agent_invoke import handler as agent_invoke_handler
from backend.functions.gap_event import handler as gap_handler

OFFICE_ID = "OFFICE001"


# --------------------------------------------------------------------------- #
# Fake Bedrock compose (deterministic; no live model)                          #
# --------------------------------------------------------------------------- #
def _valid_output_for(agent_input: AgentInput) -> AgentOutput:
    """Build a rule-compliant :class:`AgentOutput` derived from ``agent_input``.

    Produces ONE recommendation (rank 1) that exactly satisfies the request's required
    trade/headcount: every EMERGENCY ``fixed_members`` entry is kept and the remaining
    per-trade shortage is filled from the candidate pool. ``total_cost`` is the sum of the
    retained fixed-member wages plus the picked candidates' wages. Because the tests seed the
    DB workers with the SAME wages/trades as this pool, the freshest ``get_workers`` snapshot
    the validator uses matches this ``total_cost`` and the output validates (Property 1-8).

    Deriving the output from the ACTUAL (possibly server-assembled) ``agent_input`` lets the
    same fake serve the NORMAL, EMERGENCY-internal, and EMERGENCY-external flows unchanged —
    which is exactly what makes this a genuine end-to-end wiring rather than a canned reply.
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
    """Stand-in for ``agent.crew_agent.compose`` — returns a valid output (no Bedrock)."""
    return _valid_output_for(agent_input)


# --------------------------------------------------------------------------- #
# API Gateway event / registration builders                                   #
# --------------------------------------------------------------------------- #
def _normal_event(request_id):
    """An API Gateway proxy event for ``POST .../requests/{requestId}/agent-compose``."""
    return {
        "resource": "/office/requests/{requestId}/agent-compose",
        "httpMethod": "POST",
        "requestContext": {"requestId": "apigw-normal"},
        "pathParameters": {"requestId": request_id},
    }


def _recompose_event(event_id):
    """An API Gateway proxy event for ``POST .../gap-events/{eventId}/agent-recompose``."""
    return {
        "resource": "/office/gap-events/{eventId}/agent-recompose",
        "httpMethod": "POST",
        "requestContext": {"requestId": "apigw-emergency"},
        "pathParameters": {"eventId": event_id},
    }


def _gap_registration_event(crew_id, gap_type="NO_SHOW", departed_ids=("C",)):
    """An API Gateway proxy event for ``POST .../crews/{crewId}/gap-events`` (registration).

    ``crewId`` arrives as a path parameter; ``type`` / ``departed_ids`` in the JSON body (a
    string, as API Gateway delivers it).
    """
    return {
        "resource": "/company/crews/{crewId}/gap-events",
        "httpMethod": "POST",
        "requestContext": {"requestId": "apigw-gap"},
        "pathParameters": {"crewId": crew_id},
        "body": json.dumps({"type": gap_type, "departed_ids": list(departed_ids)}),
    }


# --------------------------------------------------------------------------- #
# Seeding helpers                                                              #
# --------------------------------------------------------------------------- #
def _seed_running_crew_ABC(db, *, crew_id, request_id, office_id=OFFICE_ID):
    """Seed a RUNNING crew (A, B, C all RUNNING FORMWORK) + a READY replacement E.

    The linked WorkRequest is already RUNNING (as it would be during a mid-job emergency),
    requires FORMWORK:3, and each crew member's wage matches its worker record so the
    freshest ``get_workers`` snapshot the validator uses agrees with the assembled payload.
    """
    db.add_work_request(
        request_id,
        status="RUNNING",  # during an emergency the original request may already be RUNNING
        office_id=office_id,
        required_workers=[{"trade": "FORMWORK", "count": 3}],
        budget=2_000_000,
        priority={"cost": "MEDIUM", "skill": "HIGH", "teamwork": "HIGH"},
        site="현장 E",
        work_date="2025-01-02",
        start_time="07:00",
    )
    db.add_crew(
        crew_id,
        request_id=request_id,
        office_id=office_id,
        active_members=[
            {"worker_id": "A", "trade": "FORMWORK", "desired_daily_wage": 150_000,
             "state": "RUNNING"},
            {"worker_id": "B", "trade": "FORMWORK", "desired_daily_wage": 155_000,
             "state": "RUNNING"},
            {"worker_id": "C", "trade": "FORMWORK", "desired_daily_wage": 160_000,
             "state": "RUNNING"},
        ],
    )
    # A, B stay RUNNING in the crew being recomposed (fixed members).
    db.add_worker("A", office_id=office_id, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=150_000, current_crew_id=crew_id,
                  skill_level=4, career_years=9)
    db.add_worker("B", office_id=office_id, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=155_000, current_crew_id=crew_id,
                  skill_level=4, career_years=7)
    # C is the departed (no-show / left-site) worker.
    db.add_worker("C", office_id=office_id, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=160_000, current_crew_id=crew_id,
                  skill_level=3, career_years=5)
    # E is the READY replacement the agent draws on to fill the shortage.
    db.add_worker("E", office_id=office_id, state="READY", trade="FORMWORK",
                  desired_daily_wage=158_000, current_crew_id=None,
                  skill_level=4, career_years=6)


def _call_index(db, method):
    """Index of the first recorded call to ``method`` in ``db.calls`` (-1 if absent)."""
    for i, c in enumerate(db.calls):
        if c.get("method") == method:
            return i
    return -1


# =========================================================================== #
# Path 1 — NORMAL happy path (demo scenario 2: 요청 → AI 편성 → 저장)            #
# =========================================================================== #
def test_normal_end_to_end_request_to_saved_proposal(install_shared, monkeypatch):
    """NORMAL agent-compose end-to-end: request → candidate assembly → compose → freshest
    snapshot → validate → Crew(PROPOSED) saved + WorkRequest COMPOSING→PROPOSED.

    Demo scenario 2. Only the four external boundaries are mocked (shared/db + shared/auth
    via install_shared, Bedrock via the compose monkeypatch); the assemble→validate→persist
    chain is the real code.
    """
    db = install_shared.db
    # OFFICE is the StubAuth default — the external agent-compose route requires it.
    assert install_shared.auth.role == "OFFICE"

    db.add_work_request(
        "REQ-N1",
        status="REQUESTED",
        office_id=OFFICE_ID,
        required_workers=[{"trade": "FORMWORK", "count": 2}],
        budget=1_000_000,
        priority={"cost": "HIGH", "skill": "MEDIUM", "teamwork": "LOW"},
        site="현장 A",
        work_date="2025-01-01",
        start_time="08:00",
    )
    db.add_worker("W1", office_id=OFFICE_ID, state="READY", trade="FORMWORK",
                  desired_daily_wage=150_000, skill_level=3, career_years=5)
    db.add_worker("W2", office_id=OFFICE_ID, state="READY", trade="FORMWORK",
                  desired_daily_wage=160_000, skill_level=4, career_years=8)
    # Out-of-scope workers must never surface: a RUNNING worker and a different-office one.
    db.add_worker("W3", office_id=OFFICE_ID, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=140_000)
    db.add_worker("OTHER", office_id="OFFICE999", state="READY", trade="FORMWORK",
                  desired_daily_wage=140_000)

    # Bedrock mocked: compose returns a compliant output derived from the assembled input.
    monkeypatch.setattr(agent_invoke_handler, "compose", _fake_compose)

    resp = agent_invoke_handler.handler(_normal_event("REQ-N1"))

    # --- success response with recommendations (Req 6.2) ---
    assert resp["success"] is True
    assert resp["data"]["mode"] == "NORMAL"
    assert resp["data"]["request_id"] == "REQ-N1"
    assert resp["data"]["crew_id"]
    assert len(resp["data"]["recommendations"]) == 1

    # --- Crew(status=PROPOSED, source=AGENT) saved with the recommended members (Req 8.1) ---
    assert len(db.saved_crews) == 1
    crew = db.saved_crews[0]
    assert crew["status"] == "PROPOSED"
    assert crew["source"] == "AGENT"
    assert set(crew["member_ids"]) == {"W1", "W2"}  # only office-scoped READY candidates
    assert "OTHER" not in crew["member_ids"] and "W3" not in crew["member_ids"]

    # --- WorkRequest REQUESTED→COMPOSING then COMPOSING→PROPOSED (Req 8.2) ---
    kinds = [(t["expected"], t["target"], t["ok"]) for t in db.status_transitions]
    assert kinds == [
        ("REQUESTED", "COMPOSING", True),
        ("COMPOSING", "PROPOSED", True),
    ]
    assert db.work_requests["REQ-N1"]["status"] == "PROPOSED"

    # --- freshest snapshot: get_workers read for the recommended members BEFORE save (Req 6.5) ---
    get_workers_calls = db.method_calls("get_workers")
    assert len(get_workers_calls) == 1
    assert set(get_workers_calls[0]["worker_ids"]) == {"W1", "W2"}
    assert 0 <= _call_index(db, "get_workers") < _call_index(db, "save_crew")

    # --- four boundaries mocked/stubbed: shared/auth OFFICE gate consulted once; shared/db is
    #     the in-memory fake (crew + transitions above); Bedrock replaced (our fake ran); no
    #     Lambda invoke on the single-Lambda NORMAL route. ---
    assert len(install_shared.auth.calls) == 1
    assert install_shared.auth.calls[0]["roles"] == ["OFFICE"]


# =========================================================================== #
# Path 2 — EMERGENCY trusted internal invoke (demo scenario 3: C 노쇼 → A+B+E)  #
# =========================================================================== #
def test_emergency_internal_invoke_end_to_end_no_show_recompose(install_shared, monkeypatch):
    """gap_event → trusted internal invoke → agent_invoke, end-to-end (demo scenario 3).

    A COMPANY-registered NO_SHOW gap on a RUNNING crew (C departs) drives
    ``DETECTED→RECOMPOSING→PROPOSED``: gap_event computes fixed_members (A, B) and the
    shortage, locks the GapEvent, and synchronously invokes agent_invoke's REAL handler
    (the monkeypatched Lambda-invoke seam) against the SAME FakeSharedDB. agent_invoke saves
    Crew(PROPOSED) WITHOUT touching the WorkRequest, and **gap_event** owns the terminal
    ``RECOMPOSING→PROPOSED`` (agent_invoke does not transition the GapEvent on this path).
    """
    db = install_shared.db
    # A COMPANY-registered gap must still flow through the trusted internal invoke (Req 11.3):
    # the internal path is IAM-trusted and does NOT re-apply agent_invoke's OFFICE gate.
    install_shared.auth.role = "COMPANY"
    _seed_running_crew_ABC(db, crew_id="CREW-E1", request_id="REQ-E1")

    # Bedrock mocked on agent_invoke.
    monkeypatch.setattr(agent_invoke_handler, "compose", _fake_compose)

    # Wire the gap_event → agent_invoke internal invoke: replace the boto3/Lambda seam with a
    # DIRECT call to agent_invoke's REAL handler, capturing the payload so we can assert the
    # trusted-internal contract. This is what exercises the real internal-invoke path E2E.
    invoked_payloads = []

    def _internal_invoke(payload):
        invoked_payloads.append(payload)
        return agent_invoke_handler.handler(payload)

    monkeypatch.setattr(gap_handler, "invoke_agent", _internal_invoke)

    resp = gap_handler.handler(_gap_registration_event("CREW-E1", "NO_SHOW", ["C"]))

    # --- gap_event success response: EMERGENCY, ended at PROPOSED ---
    assert resp["success"] is True
    assert resp["data"]["mode"] == "EMERGENCY"
    assert resp["data"]["gap_status"] == "PROPOSED"

    # --- GapEvent saved DETECTED first, in the office-query-path form (Req 10.1) ---
    assert db.method_calls("save_gap_event")
    saved_gap = db.saved_gap_events[0]
    assert saved_gap["office_id"] == OFFICE_ID  # office query-path key
    assert saved_gap["type"] == "NO_SHOW"
    assert saved_gap["crew_id"] == "CREW-E1"
    event_id = saved_gap["event_id"]

    # --- the Lambda-invoke seam actually fired, with the trusted-internal contract ---
    assert len(invoked_payloads) == 1
    payload = invoked_payloads[0]
    assert payload["internal_invoke"] is True
    assert payload["mode"] == "EMERGENCY"
    assert payload["event_id"] == event_id
    assert payload["current_crew_id"] == "CREW-E1"
    # fixed_members = active(A,B,C) − departed(C) = {A, B}, carried in the EMERGENCY payload.
    fixed_ids = sorted(f["worker_id"] for f in payload["agent_input"]["fixed_members"])
    assert fixed_ids == ["A", "B"]

    # --- agent_invoke saved Crew(PROPOSED, source=AGENT) WITHOUT a WorkRequest transition ---
    assert len(db.saved_crews) == 1
    crew = db.saved_crews[0]
    assert crew["status"] == "PROPOSED"
    assert crew["source"] == "AGENT"
    assert crew["gap_event_id"] == event_id
    # A+B+E recommended: fixed members preserved, departed C excluded, replacement E filled.
    assert set(crew["member_ids"]) == {"A", "B", "E"}
    assert "C" not in crew["member_ids"]
    # EMERGENCY must NOT touch the WorkRequest state machine (it is RUNNING).
    assert db.status_transitions == []
    assert db.work_requests["REQ-E1"]["status"] == "RUNNING"

    # --- terminal-transition ownership: gap_event owns RECOMPOSING→PROPOSED (Req 10.7) ---
    gap_transitions = [(t["expected"], t["target"], t["ok"]) for t in db.gap_status_transitions]
    assert gap_transitions == [
        ("DETECTED", "RECOMPOSING", True),   # gap_event acquired the lock
        ("RECOMPOSING", "PROPOSED", True),   # gap_event owns the terminal transition
    ]
    assert db.gap_events[event_id]["status"] == "PROPOSED"
    # PROPOSED-only scope: never APPROVED/FILLED (담당자 A's approval API).
    _targets = {t["target"] for t in db.gap_status_transitions}
    _expecteds = {t["expected"] for t in db.gap_status_transitions}
    assert "APPROVED" not in _targets and "FILLED" not in _targets
    assert "APPROVED" not in _expecteds and "FILLED" not in _expecteds

    # --- freshest snapshot fed the validator (get_workers for the recommended members) ---
    get_workers_calls = db.method_calls("get_workers")
    assert len(get_workers_calls) == 1
    assert set(get_workers_calls[0]["worker_ids"]) == {"A", "B", "E"}

    # --- no worker-state change anywhere (assignment/approval is 담당자 A's) ---
    assert db.workers["A"]["state"] == "RUNNING"
    assert db.workers["B"]["state"] == "RUNNING"
    assert db.workers["C"]["state"] == "RUNNING"  # departed worker not mutated here
    assert db.workers["E"]["state"] == "READY"    # replacement not reserved/assigned

    # --- four boundaries mocked/stubbed: shared/auth consulted ONLY by gap_event (COMPANY|OFFICE),
    #     and the internal agent_invoke path skipped the OFFICE gate entirely (Req 11.3); the
    #     Lambda-invoke seam was our stub; Bedrock replaced; shared/db is the shared fake. ---
    assert len(install_shared.auth.calls) == 1
    assert install_shared.auth.calls[0]["roles"] == ["COMPANY", "OFFICE"]


# =========================================================================== #
# Path 3 — EMERGENCY external/direct agent-recompose                           #
# =========================================================================== #
def test_emergency_external_recompose_end_to_end(install_shared, monkeypatch):
    """External OFFICE agent-recompose end-to-end: agent_invoke self-locks, assembles the
    EMERGENCY payload SERVER-SIDE, saves Crew(PROPOSED) without a WorkRequest transition, and
    (compose_flow) owns the terminal ``RECOMPOSING→PROPOSED``.

    Server-side assembly reuses task 8.1's ``compute_fixed_members`` / ``compute_missing`` and
    task 8.4's ``build_emergency_payload`` — verified by the saved crew reflecting the retained
    fixed members (A, B) plus the filled shortage (E), with the departed worker (C) excluded,
    even though the client body carries no payload (it is not trusted).
    """
    db = install_shared.db
    install_shared.auth.role = "OFFICE"  # external route requires OFFICE
    _seed_running_crew_ABC(db, crew_id="CREW-X1", request_id="REQ-X1")
    # A GapEvent already DETECTED (as gap_event would have saved it) links to the crew.
    db.add_gap_event("GE-X1", status="DETECTED", crew_id="CREW-X1",
                     departed_ids=["C"], type="LEFT_SITE", office_id=OFFICE_ID)

    monkeypatch.setattr(agent_invoke_handler, "compose", _fake_compose)

    resp = agent_invoke_handler.handler(_recompose_event("GE-X1"))

    # --- success response: EMERGENCY, links the GapEvent ---
    assert resp["success"] is True
    assert resp["data"]["mode"] == "EMERGENCY"
    assert resp["data"]["gap_event_id"] == "GE-X1"

    # --- server-side assembly happened: crew looked up + READY candidates queried ---
    assert db.method_calls("get_crew")[0]["crew_id"] == "CREW-X1"
    assert db.method_calls("query_ready_workers")  # server-side candidate pool assembly

    # --- Crew(PROPOSED, source=AGENT) reflects fixed members + filled shortage, C excluded ---
    assert len(db.saved_crews) == 1
    crew = db.saved_crews[0]
    assert crew["status"] == "PROPOSED"
    assert crew["source"] == "AGENT"
    assert crew["gap_event_id"] == "GE-X1"
    assert set(crew["member_ids"]) == {"A", "B", "E"}
    assert "C" not in crew["member_ids"]
    # EMERGENCY never transitions the WorkRequest (it is RUNNING).
    assert db.status_transitions == []
    assert db.work_requests["REQ-X1"]["status"] == "RUNNING"

    # --- terminal-transition ownership: agent_invoke (compose_flow) owns it on the EXTERNAL
    #     route because it self-acquired the lock (Req 10.7 mirror). ---
    gap_transitions = [(t["expected"], t["target"], t["ok"]) for t in db.gap_status_transitions]
    assert gap_transitions == [
        ("DETECTED", "RECOMPOSING", True),   # agent_invoke self-acquired the lock
        ("RECOMPOSING", "PROPOSED", True),   # agent_invoke owns the terminal transition
    ]
    assert db.gap_events["GE-X1"]["status"] == "PROPOSED"
    # PROPOSED-only scope: never APPROVED/FILLED.
    _targets = {t["target"] for t in db.gap_status_transitions}
    _expecteds = {t["expected"] for t in db.gap_status_transitions}
    assert "APPROVED" not in _targets and "FILLED" not in _targets
    assert "APPROVED" not in _expecteds and "FILLED" not in _expecteds

    # --- freshest snapshot fed the validator (get_workers for the recommended members) ---
    get_workers_calls = db.method_calls("get_workers")
    assert len(get_workers_calls) == 1
    assert set(get_workers_calls[0]["worker_ids"]) == {"A", "B", "E"}

    # --- no worker-state change (assignment/approval is 담당자 A's) ---
    assert db.workers["A"]["state"] == "RUNNING"
    assert db.workers["C"]["state"] == "RUNNING"
    assert db.workers["E"]["state"] == "READY"

    # --- four boundaries mocked/stubbed: shared/auth OFFICE gate consulted; shared/db is the
    #     in-memory fake; Bedrock replaced; no Lambda invoke on the single-Lambda external route. ---
    assert install_shared.auth.calls[0]["roles"] == ["OFFICE"]
