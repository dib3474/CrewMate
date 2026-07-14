"""assignment Lambda (계약 v2) — 승인/긴급 승인 (트랜잭션 1).

Route:
  POST /office/crews/{crewId}/approve        작업조 승인 → 조원 전원 READY→NOTIFIED (트랜잭션 1)
  POST /office/emergency/{eventId}/approve   긴급 승인 → 대체자만 READY→NOTIFIED

트랜잭션 1 (승인): 조원 전원 Workers READY→NOTIFIED(조건 state=READY, current_offer 없음)
+ current_offer 기록 + Assignments 생성(PENDING) + Crew→NOTIFIED + Request→APPROVED.
한 명이라도 실패 시 전체 롤백(STATE_CONFLICT). 이후 수락은 worker_api 가 담당한다.
"""

from __future__ import annotations

import logging
from typing import Any

from botocore.exceptions import ClientError

from shared import db, txn
from shared.auth import Principal
from shared.crew import (
    assemble_crew_members,
    validate_budget,
    validate_candidates_state,
    validate_excluded_trades,
    validate_members_unique,
    validate_required_coverage,
)
from shared.responses import ApiError, ErrorCode, success
from shared.routing import Router
from shared.schemas import (
    build_assignment,
    build_notification,
    build_offer,
    crew_view,
    gap_view,
    now_iso,
    parse_body,
)
from shared.state import (
    Acceptance,
    AssignmentStatus,
    CrewStatus,
    GapStatus,
    RequestStatus,
    Role,
    WorkerState,
)

logger = logging.getLogger()
router = Router()


def _load_workers(worker_ids) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for wid in worker_ids:
        if wid not in out:
            w = db.get_worker(wid)
            if w:
                out[wid] = w
    return out


def _notify(user_id, ntype, title, message):
    if not user_id:
        return
    try:
        db.put_notification(build_notification(user_id=user_id, type=ntype, title=title, message=message))
    except ClientError:
        logger.exception("notify_failed user=%s", user_id)


def _run(entries, label):
    try:
        txn.run(entries)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("TransactionCanceledException", "ConditionalCheckFailedException"):
            raise ApiError(ErrorCode.STATE_CONFLICT, f"{label} 도중 상태가 변경되어 처리를 완료할 수 없습니다.")
        raise


# ---------------------------------------------------------------------------
# 승인 (트랜잭션 1)
# ---------------------------------------------------------------------------
@router.route("POST", "/office/crews/{crewId}/approve")
def approve_crew(event, principal: Principal, params):
    principal.require_role(Role.OFFICE)
    crew_id = params["crewId"]
    crew = db.get_crew(crew_id)
    if not crew:
        raise ApiError(ErrorCode.CREW_INVALID, "작업조를 찾을 수 없습니다.")
    principal.require_office(crew["office_id"])
    if crew["status"] not in (CrewStatus.DRAFT, CrewStatus.PROPOSED):
        raise ApiError(ErrorCode.CREW_INVALID, "이미 승인되었거나 승인할 수 없는 작업조입니다.")

    request = db.get_request(crew["request_id"])
    if not request:
        raise ApiError(ErrorCode.REQUEST_NOT_FOUND, "연결된 요청을 찾을 수 없습니다.")
    if request["status"] in (RequestStatus.APPROVED, RequestStatus.DISPATCHED,
                             RequestStatus.RUNNING, RequestStatus.COMPLETED):
        raise ApiError(ErrorCode.REQUEST_ALREADY_ASSIGNED, "이미 배정이 진행된 요청입니다.")

    # AI 추천안(rank) 선택 시 해당 조합으로 교체
    body = parse_body(event)
    members = _select_members(crew, body.get("rank"))
    validate_members_unique([m["worker_id"] for m in members])

    workers_by_id = _load_workers(m["worker_id"] for m in members)
    try:
        validate_candidates_state(members, workers_by_id, office_id=crew["office_id"])
    except ApiError as exc:
        # 승인 시점 비-READY(동시 승인 등)는 STATE_CONFLICT 로 통일 (계약)
        if exc.code == ErrorCode.WORKER_NOT_READY:
            raise ApiError(ErrorCode.STATE_CONFLICT, "일부 근로자가 이미 다른 작업에 배정되었습니다.")
        raise
    validate_excluded_trades(members, workers_by_id)
    validate_required_coverage(members, request.get("required_workers", []))
    validate_budget(members, request.get("budget", 0))

    now = now_iso()
    entries = []
    for m in members:
        offer = build_offer(crew_id, request, m)
        entries.append(txn.worker_entry(
            m["worker_id"], now=now, to_state=WorkerState.NOTIFIED,
            from_states=[WorkerState.READY], current_offer=offer,
            current_crew_id=crew_id, require_no_offer=True,
        ))
        entries.append(txn.assignment_put_entry(build_assignment(
            crew_id=crew_id, worker_id=m["worker_id"],
            assigned_trade=m["assigned_trade"], offered_wage=m["offered_wage"],
            acceptance=Acceptance.PENDING, status=AssignmentStatus.RESERVED,
            is_replacement=bool(m.get("is_replacement")), notified_at=now,
        )))
    entries.append(txn.crew_status_entry(
        crew_id, to_status=CrewStatus.NOTIFIED,
        from_statuses=[CrewStatus.DRAFT, CrewStatus.PROPOSED], now=now,
    ))
    entries.append(txn.request_status_entry(
        crew["request_id"], to_status=RequestStatus.APPROVED,
        from_statuses=[RequestStatus.REQUESTED, RequestStatus.COMPOSING, RequestStatus.PROPOSED],
        now=now,
    ))
    _run(entries, "승인")

    # proposed_members / member_ids 동기화
    db.update_crew(
        crew_id,
        UpdateExpression="SET proposed_members = :pm, member_ids = :ids, updated_at = :t",
        ExpressionAttributeValues={
            ":pm": _to_decimal(members),
            ":ids": [m["worker_id"] for m in members],
            ":t": now,
        },
    )
    for m in members:
        w = workers_by_id.get(m["worker_id"], {})
        _notify(w.get("user_id"), "OFFER", "배정 제안",
                f"{request.get('site_name')}에 배정 제안이 도착했습니다. 확인 후 수락해주세요.")

    crew = db.get_crew(crew_id)
    return success(crew_view(crew, assemble_crew_members(crew)))


def _select_members(crew, rank):
    """rank 선택 시 추천안 조합, 아니면 proposed_members."""
    if rank and crew.get("recommendations"):
        for rec in crew["recommendations"]:
            if int(rec.get("rank", -1)) == int(rank):
                return [
                    {
                        "worker_id": mem["worker_id"],
                        "assigned_trade": mem["assigned_trade"],
                        "offered_wage": int(mem["offered_wage"]),
                        "is_replacement": bool(mem.get("is_replacement", False)),
                    }
                    for mem in rec.get("members", [])
                ]
    return [
        {
            "worker_id": m["worker_id"],
            "assigned_trade": m["assigned_trade"],
            "offered_wage": int(m["offered_wage"]),
            "is_replacement": bool(m.get("is_replacement", False)),
        }
        for m in crew.get("proposed_members", [])
    ]


def _to_decimal(value):
    from shared.schemas import to_decimal
    return to_decimal(value)


# ---------------------------------------------------------------------------
# 긴급 승인 — 대체자만 NOTIFIED
# ---------------------------------------------------------------------------
@router.route("POST", "/office/emergency/{eventId}/approve")
def approve_emergency(event, principal: Principal, params):
    principal.require_role(Role.OFFICE)
    event_id = params["eventId"]
    gap = db.get_gap_event(event_id)
    if not gap:
        raise ApiError(ErrorCode.GAP_EVENT_NOT_FOUND, "결원 이벤트를 찾을 수 없습니다.")
    principal.require_office(gap["office_id"])
    if gap["status"] == GapStatus.FILLED:
        raise ApiError(ErrorCode.STATE_CONFLICT, "이미 충원이 완료된 결원 이벤트입니다.")

    crew = db.get_crew(gap["crew_id"])
    request = db.get_request(gap["request_id"])
    if not crew or not request:
        raise ApiError(ErrorCode.CREW_INVALID, "작업조/요청을 찾을 수 없습니다.")

    body = parse_body(event)
    from shared.crew import normalize_member_inputs
    workers_by_id = _load_workers(m["worker_id"] for m in body.get("members", []))
    replacements = normalize_member_inputs(body.get("members", []), workers_by_id)
    for m in replacements:
        m["is_replacement"] = True
    validate_members_unique([m["worker_id"] for m in replacements])
    validate_candidates_state(replacements, workers_by_id, office_id=gap["office_id"])
    validate_excluded_trades(replacements, workers_by_id)

    # 잔여 예산 = budget − 고정 인원 offered_wage 합
    fixed = assemble_crew_members(crew)
    fixed_cost = sum(int(m.get("offered_wage", 0)) for m in fixed)
    validate_budget(replacements, request.get("budget", 0), fixed_cost=fixed_cost)

    now = now_iso()
    entries = []
    for m in replacements:
        offer = build_offer(gap["crew_id"], request, m, is_emergency=True)
        entries.append(txn.worker_entry(
            m["worker_id"], now=now, to_state=WorkerState.NOTIFIED,
            from_states=[WorkerState.READY], current_offer=offer,
            current_crew_id=gap["crew_id"], require_no_offer=True,
        ))
        entries.append(txn.assignment_put_entry(build_assignment(
            crew_id=gap["crew_id"], worker_id=m["worker_id"],
            assigned_trade=m["assigned_trade"], offered_wage=m["offered_wage"],
            acceptance=Acceptance.PENDING, status=AssignmentStatus.RESERVED,
            is_replacement=True, notified_at=now,
        )))
    entries.append(txn.gap_status_entry(
        event_id, to_status=GapStatus.APPROVED,
        from_statuses=[GapStatus.DETECTED, GapStatus.RECOMPOSING, GapStatus.PROPOSED],
        now=now,
    ))
    _run(entries, "긴급 승인")

    new_ids = [m["worker_id"] for m in fixed] + [m["worker_id"] for m in replacements]
    db.update_crew(gap["crew_id"], UpdateExpression="SET member_ids = :m, updated_at = :t",
                   ExpressionAttributeValues={":m": new_ids, ":t": now})
    for m in replacements:
        w = workers_by_id.get(m["worker_id"], {})
        _notify(w.get("user_id"), "EMERGENCY_OFFER", "긴급 배정 제안",
                f"{request.get('site_name')} 긴급 대체 인력 제안이 도착했습니다.")

    return success(gap_view(db.get_gap_event(event_id)))


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    return router.dispatch(event)
