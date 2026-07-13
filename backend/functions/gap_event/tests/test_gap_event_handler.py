"""Execution-flow unit tests for the gap_event Lambda handler (담당자 B, task 8.6).

These are EXAMPLE / UNIT tests (plain pytest - no Hypothesis, no ``property`` marker).
They exercise the control flow of ``backend/functions/gap_event/handler.py`` (task 8.5)
end-to-end against the in-memory shared stubs installed under ``backend.shared.*`` via the
``install_shared`` fixture (conftest.py). The one seam to agent_invoke -
``handler.invoke_agent`` - is monkeypatched so NO real Lambda / boto3 call happens and the
gap_event orchestration is isolated from the agent_invoke internals.

Scope of what is verified (tasks.md task 8.6; Req 10.1/10.7/10.8/10.9/10.11/11.3)
--------------------------------------------------------------------------------
1. Happy path (긴급 시나리오) - a COMPANY-registered gap on a running crew (one member
   departs) drives a full ``DETECTED -> RECOMPOSING -> PROPOSED`` recomposition: the gap is
   saved DETECTED first with the office-query-path fields, the affected crew is looked up,
   the retained team (active - departed) is preserved as ``fixed_members`` in the EMERGENCY
   payload, agent_invoke is invoked once with the trusted-internal contract, and the
   GapEvent ends at PROPOSED.                                        (Req 10.1, 10.7, 11.3)
2. Registrant role - BOTH COMPANY and OFFICE may register a gap (test 1 uses COMPANY,
   ``test_office_registrant_...`` uses OFFICE); a WORKER is FORBIDDEN with no save and no
   invoke.                                                           (Req 11.3)
3. ``CREW_INVALID`` - a missing affected crew fails with CREW_INVALID, but the gap is still
   saved DETECTED first (retrievable), and no recomposition is invoked or locked. (Req 10.11)
4. ``STATE_CONFLICT`` - a failed ``DETECTED -> RECOMPOSING`` lock short-circuits before the
   invoke.                                                           (Req 6.6 / 6.7 semantics)
5. Recomposition failure - when agent_invoke returns ``success=False`` the handler moves the
   GapEvent ``RECOMPOSING -> FAILED``, returns an error carrying manual-composition guidance,
   never reaches PROPOSED, and changes no worker state.              (Req 10.9, 10.8)
6. B's PROPOSED-only scope - the handler NEVER transitions the GapEvent to APPROVED or
   FILLED (those belong to 담당자 A's emergency approval API).       (task 8.6 scope note)

Note on the FakeSharedDB save/transition aliasing (from the 8.5 implementer)
----------------------------------------------------------------------------
``FakeSharedDB.save_gap_event`` stores the SAME dict object in both ``saved_gap_events`` and
``gap_events``, so a later terminal transition mutates the saved snapshot's ``status`` in
place. Therefore, to assert the DETECTED-at-save office-query-path form, these tests assert
on the NON-mutated fields (``office_id`` / ``type`` / ``crew_id``) of
``db.saved_gap_events[0]`` and prove the DETECTED status via the FIRST
``gap_status_transitions`` entry (``expected="DETECTED"``, ``ok=True``) - the conditional
lock only succeeds when the stored status was DETECTED - rather than reading the (mutated)
``saved_gap_events[0]["status"]``.

Python 3.9: ``from __future__ import annotations`` keeps annotations lazy.
"""
from __future__ import annotations

import json

import pytest

from backend.functions.gap_event import handler as gap_handler

OFFICE_ID = "OFFICE001"


# --------------------------------------------------------------------------- #
# Fake agent_invoke seam (no live Lambda / boto3)                              #
# --------------------------------------------------------------------------- #
def _success_response(crew_id="CREW#AGENT-1"):
    """A well-formed agent_invoke success response (a saved EMERGENCY proposal)."""
    return {
        "success": True,
        "data": {
            "crew_id": crew_id,
            "recommendations": [
                {
                    "rank": 1,
                    "member_ids": ["F1", "N1"],
                    "total_cost": 310_000,
                    "reason": "결원 직종 인원을 충족하는 팀 재구성",
                    "considerations": ["잔여 팀원 유지", "예산 내"],
                }
            ],
        },
    }


def _make_capturing_invoke(sink, response):
    """A fake ``invoke_agent`` that records each payload into ``sink`` and returns ``response``."""

    def _fake(payload):
        sink.append(payload)
        return response

    return _fake


def _explode_invoke(payload):
    """A fake ``invoke_agent`` that must never be reached (asserts a pre-invoke short-circuit)."""
    raise AssertionError("invoke_agent must not be called on this path")


# --------------------------------------------------------------------------- #
# Event / seeding builders                                                     #
# --------------------------------------------------------------------------- #
def _gap_event(crew_id="CREW1", gap_type="NO_SHOW", departed_ids=("F2",)):
    """An API Gateway proxy event for ``POST .../crews/{crewId}/gap-events``.

    ``crewId`` arrives as a path parameter; ``type`` / ``departed_ids`` in the JSON body
    (a string, as API Gateway delivers it).
    """
    return {
        "resource": "/office/crews/{crewId}/gap-events",
        "httpMethod": "POST",
        "requestContext": {"requestId": "apigw-gap"},
        "pathParameters": {"crewId": crew_id},
        "body": json.dumps({"type": gap_type, "departed_ids": list(departed_ids)}),
    }


def _seed_gap(db, *, crew_id="CREW1", request_id="REQ_E", office_id=OFFICE_ID):
    """Seed a RUNNING work request, an affected crew (F1 stays, F2 departs), and workers.

    ``F1`` / ``F2`` are RUNNING crew members; ``N1`` is a READY FORMWORK candidate the
    assembler will offer to fill the shortage left by ``F2``'s departure. The work request
    carries the FULL requirement (FORMWORK:2) so ``build_emergency_payload`` sees remaining
    + shortage = full.
    """
    db.add_work_request(
        request_id,
        status="RUNNING",  # during an emergency the original request may already be RUNNING
        office_id=office_id,
        required_workers=[{"trade": "FORMWORK", "count": 2}],
        budget=1_000_000,
        priority={"cost": "HIGH", "skill": "MEDIUM", "teamwork": "LOW"},
        site="현장 E",
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
    db.add_worker("F1", office_id=office_id, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=150_000, current_crew_id=crew_id,
                  skill_level=4, career_years=9)
    db.add_worker("F2", office_id=office_id, state="RUNNING", trade="FORMWORK",
                  desired_daily_wage=155_000, current_crew_id=crew_id,
                  skill_level=3, career_years=6)
    db.add_worker("N1", office_id=office_id, state="READY", trade="FORMWORK",
                  desired_daily_wage=160_000, current_crew_id=None,
                  skill_level=3, career_years=4)


def _transitions(db):
    """The recorded GapEvent transitions as ``(expected, target, ok)`` tuples, in order."""
    return [(t["expected"], t["target"], t["ok"]) for t in db.gap_status_transitions]


# =========================================================================== #
# 1. Happy path (긴급 시나리오) - COMPANY registrant                            #
# =========================================================================== #
def test_emergency_happy_path_company_registrant_recomposes_to_proposed(
    install_shared, monkeypatch
):
    """A COMPANY-registered gap drives DETECTED -> RECOMPOSING -> PROPOSED end-to-end.

    Verifies the full 긴급 시나리오: the gap is saved DETECTED first in the office-query-path
    form, the affected crew is looked up, the retained team (active - departed) is preserved
    as ``fixed_members`` in the EMERGENCY payload handed to a single trusted internal invoke,
    and the GapEvent ends at PROPOSED with a success response.
    """
    db = install_shared.db
    install_shared.auth.role = "COMPANY"  # COMPANY may register a gap (Req 11.3)
    _seed_gap(db)

    invoked = []
    monkeypatch.setattr(
        gap_handler, "invoke_agent", _make_capturing_invoke(invoked, _success_response())
    )

    resp = gap_handler.handler(_gap_event(crew_id="CREW1", departed_ids=["F2"]))

    # --- Response: success, PROPOSED, EMERGENCY, agent data surfaced ---
    assert resp["success"] is True
    assert resp["data"]["gap_status"] == "PROPOSED"
    assert resp["data"]["mode"] == "EMERGENCY"
    assert resp["data"]["crew_id"] == "CREW#AGENT-1"
    assert resp["data"]["recommendations"] == _success_response()["data"]["recommendations"]

    # --- save_gap_event happened, in the office-query-path form (Req 10.1) ---
    assert db.method_calls("save_gap_event")  # the gap was saved
    saved = db.saved_gap_events[0]
    # Assert the NON-mutated fields (status is mutated in place by later transitions).
    assert saved["office_id"] == OFFICE_ID     # office query-path key
    assert saved["type"] == "NO_SHOW"
    assert saved["crew_id"] == "CREW1"
    # The DETECTED-at-save status is proven by the FIRST transition's expected state:
    # a conditional DETECTED->RECOMPOSING only succeeds when the stored status was DETECTED.
    assert db.gap_status_transitions[0]["expected"] == "DETECTED"
    assert db.gap_status_transitions[0]["ok"] is True

    # --- Affected crew was looked up (Req 10.2) ---
    assert db.method_calls("get_crew")
    assert db.method_calls("get_crew")[0]["crew_id"] == "CREW1"

    # --- Terminal transition sequence is EXACTLY DETECTED->RECOMPOSING->PROPOSED (Req 10.7) ---
    assert _transitions(db) == [
        ("DETECTED", "RECOMPOSING", True),
        ("RECOMPOSING", "PROPOSED", True),
    ]
    assert db.gap_events[saved["event_id"]]["status"] == "PROPOSED"

    # --- agent_invoke called exactly once with the trusted-internal contract ---
    assert len(invoked) == 1
    payload = invoked[0]
    assert payload["internal_invoke"] is True
    assert payload["mode"] == "EMERGENCY"
    assert payload["event_id"] == saved["event_id"]  # the GapEvent gap_event locked
    assert payload["current_crew_id"] == "CREW1"
    assert "agent_input" in payload

    # --- fixed_members preserved conceptually: active(F1,F2) minus departed(F2) == {F1} ---
    agent_input = payload["agent_input"]
    assert agent_input["mode"] == "EMERGENCY"
    fixed_ids = [f["worker_id"] for f in agent_input["fixed_members"]]
    assert fixed_ids == ["F1"]


# =========================================================================== #
# 2. Registrant role - OFFICE allowed, WORKER forbidden (Req 11.3)             #
# =========================================================================== #
def test_office_registrant_is_allowed(install_shared, monkeypatch):
    """OFFICE may also register a gap -> the same happy path succeeds (Req 11.3)."""
    db = install_shared.db
    install_shared.auth.role = "OFFICE"
    _seed_gap(db)

    invoked = []
    monkeypatch.setattr(
        gap_handler, "invoke_agent", _make_capturing_invoke(invoked, _success_response())
    )

    resp = gap_handler.handler(_gap_event(crew_id="CREW1", departed_ids=["F2"]))

    assert resp["success"] is True
    assert resp["data"]["gap_status"] == "PROPOSED"
    assert len(invoked) == 1
    assert _transitions(db) == [
        ("DETECTED", "RECOMPOSING", True),
        ("RECOMPOSING", "PROPOSED", True),
    ]


def test_worker_registrant_is_forbidden_with_no_side_effects(install_shared, monkeypatch):
    """A WORKER cannot register a gap -> FORBIDDEN, and nothing is saved or invoked."""
    db = install_shared.db
    install_shared.auth.role = "WORKER"
    _seed_gap(db)
    monkeypatch.setattr(gap_handler, "invoke_agent", _explode_invoke)

    resp = gap_handler.handler(_gap_event(crew_id="CREW1", departed_ids=["F2"]))

    assert resp["success"] is False
    assert resp["error"]["code"] == "FORBIDDEN"
    # Rejected before any write / lookup / invoke.
    assert db.saved_gap_events == []
    assert db.method_calls("save_gap_event") == []
    assert db.gap_status_transitions == []


# =========================================================================== #
# 3. CREW_INVALID - missing affected crew (Req 10.11)                          #
# =========================================================================== #
def test_missing_crew_returns_crew_invalid_but_saves_detected_gap(
    install_shared, monkeypatch
):
    """A missing affected crew -> CREW_INVALID, yet the gap is saved DETECTED (retrievable).

    The gap must be captured before the crew lookup so the OFFICE polling path can surface
    it even when the crew is invalid; recomposition is neither locked nor invoked.
    """
    db = install_shared.db  # NOTE: no crew seeded -> get_crew returns None
    monkeypatch.setattr(gap_handler, "invoke_agent", _explode_invoke)

    resp = gap_handler.handler(_gap_event(crew_id="MISSING", departed_ids=["F2"]))

    assert resp["success"] is False
    assert resp["error"]["code"] == "CREW_INVALID"

    # The DETECTED gap was saved first and is retrievable in the office-query-path form.
    assert db.method_calls("save_gap_event")
    saved = db.saved_gap_events[0]
    assert saved["office_id"] == OFFICE_ID
    assert saved["crew_id"] == "MISSING"
    # No transition mutated it on this path, so the stored status is still DETECTED.
    assert saved["status"] == "DETECTED"

    # No lock (no RECOMPOSING transition) and no recomposition was invoked.
    assert db.gap_status_transitions == []


# =========================================================================== #
# 4. STATE_CONFLICT - the DETECTED->RECOMPOSING lock fails                      #
# =========================================================================== #
def test_lock_failure_returns_state_conflict_without_invoking(install_shared, monkeypatch):
    """A failed DETECTED->RECOMPOSING lock short-circuits to STATE_CONFLICT before the invoke."""
    from backend.shared import db as shared_db_mod  # the installed stub module (patched here)

    db = install_shared.db
    _seed_gap(db)

    # Force the conditional lock to fail (as if the GapEvent were already recomposing).
    # Patch the MODULE function the handler calls (its reference is bound at install time),
    # recording the attempt so we can prove it was the DETECTED->RECOMPOSING lock.
    attempts = []

    def _failing_transition(event_id, expected, target):
        attempts.append((event_id, expected, target))
        return False

    monkeypatch.setattr(shared_db_mod, "transition_gap_event_status", _failing_transition)
    monkeypatch.setattr(gap_handler, "invoke_agent", _explode_invoke)

    resp = gap_handler.handler(_gap_event(crew_id="CREW1", departed_ids=["F2"]))

    assert resp["success"] is False
    assert resp["error"]["code"] == "STATE_CONFLICT"
    # Exactly one transition attempt - the DETECTED->RECOMPOSING lock - and nothing after it.
    event_id = db.saved_gap_events[0]["event_id"]
    assert attempts == [(event_id, "DETECTED", "RECOMPOSING")]
    # The gap was still captured (DETECTED) before the lock attempt; nothing was recomposed.
    assert db.method_calls("save_gap_event")
    assert db.saved_crews == []


# =========================================================================== #
# 5. Recomposition failure -> FAILED + manual guidance (Req 10.9, 10.8)        #
# =========================================================================== #
def test_recomposition_failure_transitions_to_failed_with_manual_guidance(
    install_shared, monkeypatch
):
    """agent_invoke failure -> GapEvent RECOMPOSING->FAILED, error with manual guidance, no PROPOSED.

    Also asserts no worker-state change (the gap_event handler never writes worker state or
    saves a crew - that is 담당자 A's / agent_invoke's job) and the WorkRequest is untouched.
    """
    db = install_shared.db
    _seed_gap(db)
    failure = {
        "success": False,
        "error": {"code": "AGENT_RETRY_FAILED", "message": "재시도 후에도 검증 실패"},
    }
    invoked = []
    monkeypatch.setattr(
        gap_handler, "invoke_agent", _make_capturing_invoke(invoked, failure)
    )

    resp = gap_handler.handler(_gap_event(crew_id="CREW1", departed_ids=["F2"]))

    # --- Error response carrying manual-composition guidance (Req 10.9) ---
    assert resp["success"] is False
    assert resp["error"]["code"] == "AGENT_RETRY_FAILED"
    assert gap_handler._MANUAL_GUIDANCE in resp["error"]["message"]

    # --- agent_invoke was reached exactly once ---
    assert len(invoked) == 1

    # --- GapEvent moved RECOMPOSING->FAILED and NEVER reached PROPOSED (Req 10.9) ---
    assert _transitions(db) == [
        ("DETECTED", "RECOMPOSING", True),
        ("RECOMPOSING", "FAILED", True),
    ]
    assert db.gap_events[db.saved_gap_events[0]["event_id"]]["status"] == "FAILED"
    assert all(t["target"] != "PROPOSED" for t in db.gap_status_transitions)

    # --- No worker-state change and no WorkRequest transition (Req 10.8) ---
    assert db.saved_crews == []            # gap_event never saves a crew
    assert db.status_transitions == []     # WorkRequest state machine untouched
    assert db.workers["F1"]["state"] == "RUNNING"   # remaining team stays RUNNING
    assert db.workers["F2"]["state"] == "RUNNING"   # departed worker not mutated here
    assert db.workers["N1"]["state"] == "READY"     # candidate not reserved/assigned


# =========================================================================== #
# 6. Scope - B stops at PROPOSED/FAILED, never APPROVED/FILLED                  #
# =========================================================================== #
def test_handler_never_transitions_to_approved_or_filled(install_shared, monkeypatch):
    """The handler owns only DETECTED->RECOMPOSING->PROPOSED (or FAILED); never APPROVED/FILLED.

    APPROVED / FILLED transitions belong to 담당자 A's emergency approval API and must not
    appear anywhere in this handler's GapEvent transitions on a successful run.
    """
    db = install_shared.db
    _seed_gap(db)
    monkeypatch.setattr(
        gap_handler, "invoke_agent", _make_capturing_invoke([], _success_response())
    )

    resp = gap_handler.handler(_gap_event(crew_id="CREW1", departed_ids=["F2"]))

    assert resp["success"] is True
    targets = {t["target"] for t in db.gap_status_transitions}
    expecteds = {t["expected"] for t in db.gap_status_transitions}
    assert "APPROVED" not in targets and "APPROVED" not in expecteds
    assert "FILLED" not in targets and "FILLED" not in expecteds
    # Only the two in-scope terminal states appear.
    assert targets == {"RECOMPOSING", "PROPOSED"}
