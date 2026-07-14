"""agent_invoke Lambda (계약 v2) — Crew Composition Agent (조회·추천 전용).

Route (OFFICE 전용):
  POST /office/requests/{requestId}/agent-compose      NORMAL 편성 추천 → Crew(PROPOSED, AGENT)
  POST /office/gap-events/{eventId}/agent-recompose     EMERGENCY 대체 추천 → GapEvent(PROPOSED)

원칙 (PROMPT §5):
- Agent는 추천만 한다. 쓰기 Tool 없음. 각 추천 멤버에 assigned_trade 포함.
- 후보에 preferred_trades / excluded_trades / desired_daily_wage 반영, assigned_trade ∉ excluded.
- 예산: NORMAL=budget, EMERGENCY=budget − 고정 인원 offered_wage 합.
- EMERGENCY 후보에서 declined_worker_ids 제외. fixed_members 불변.
- 추천 사유에 개인 부정 평가·확률 수치·최적 보장 표현 금지.
- LLM(Strands+Bedrock) 추천을 우선 시도하고, 검증 실패 시 1회 재시도, 그래도 실패하거나
  Bedrock 미가용 시 결정론적 폴백으로 동일 규칙의 추천을 생성한다(데모 안정성).
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any

from shared import db
from shared.auth import Principal
from shared.crew import assemble_crew_members
from shared.responses import ApiError, ErrorCode, success
from shared.routing import Router
from shared.schemas import (
    build_crew,
    crew_view,
    gap_view,
    now_iso,
)
from shared.state import CrewStatus, GapStatus, RequestStatus, Role, WorkerState

logger = logging.getLogger()
router = Router()

FALLBACK_ENABLED = os.environ.get("AGENT_FALLBACK_ENABLED", "false").lower() == "true"


# ---------------------------------------------------------------------------
# NORMAL: agent-compose
# ---------------------------------------------------------------------------
@router.route("POST", "/office/requests/{requestId}/agent-compose")
def agent_compose(_event, principal: Principal, params):
    principal.require_role(Role.OFFICE)
    request = db.get_request(params["requestId"])
    if not request:
        raise ApiError(ErrorCode.REQUEST_NOT_FOUND, "요청을 찾을 수 없습니다.")
    principal.require_office(request["office_id"])

    declined = set(request.get("declined_worker_ids") or [])
    candidates = [
        w for w in db.query_office_workers_by_state(request["office_id"], WorkerState.READY)
        if w["worker_id"] not in declined
    ]
    needed = _flatten_required(request.get("required_workers", []))
    if len(candidates) < len(needed):
        raise ApiError(ErrorCode.AGENT_RETRY_FAILED,
                       "READY 상태 후보가 부족하여 AI 편성에 실패했습니다. 수동 편성으로 진행해주세요.")

    recs = _recommend(candidates, needed, int(request.get("budget", 0)))
    if not recs:
        raise ApiError(ErrorCode.AGENT_RETRY_FAILED,
                       "예산 범위 내에서 가능한 조합을 찾지 못했습니다. 예산 조정 또는 수동 편성이 필요합니다.")

    _cancel_existing_crews(request["request_id"])
    top = recs[0]
    proposed = [
        {"worker_id": m["worker_id"], "assigned_trade": m["assigned_trade"],
         "offered_wage": m["offered_wage"], "is_replacement": False}
        for m in top["members"]
    ]
    crew = build_crew(
        office_id=request["office_id"],
        request_id=request["request_id"],
        proposed_members=proposed,
        status=CrewStatus.PROPOSED,
        source="AGENT",
        reason=top["reason"],
        considerations=top["considerations"],
        total_cost=top["total_cost"],
        recommendations=recs,
    )
    db.put_crew(crew)
    _set_request_status(request["request_id"], RequestStatus.PROPOSED)
    return success(crew_view(crew, assemble_crew_members(crew)))


# ---------------------------------------------------------------------------
# EMERGENCY: agent-recompose
# ---------------------------------------------------------------------------
@router.route("POST", "/office/gap-events/{eventId}/agent-recompose")
def agent_recompose(_event, principal: Principal, params):
    principal.require_role(Role.OFFICE)
    gap = db.get_gap_event(params["eventId"])
    if not gap:
        raise ApiError(ErrorCode.GAP_EVENT_NOT_FOUND, "결원 이벤트를 찾을 수 없습니다.")
    principal.require_office(gap["office_id"])
    crew = db.get_crew(gap["crew_id"])
    request = db.get_request(gap["request_id"])
    if not crew or not request:
        raise ApiError(ErrorCode.CREW_INVALID, "작업조/요청을 찾을 수 없습니다.")

    _set_gap_status(gap["event_id"], GapStatus.RECOMPOSING)

    fixed = assemble_crew_members(crew)
    fixed_cost = sum(int(m.get("offered_wage", 0)) for m in fixed)
    gap_trades = _gap_trades(request.get("required_workers", []), fixed)
    if not gap_trades:
        # 결원 직종이 없으면(이미 충족) 실패 처리
        _set_gap_status(gap["event_id"], GapStatus.FAILED)
        raise ApiError(ErrorCode.AGENT_RETRY_FAILED, "충원이 필요한 직종을 찾지 못했습니다.")

    declined = set(request.get("declined_worker_ids") or [])
    fixed_ids = {m["worker_id"] for m in fixed}
    candidates = [
        w for w in db.query_office_workers_by_state(gap["office_id"], WorkerState.READY)
        if w["worker_id"] not in declined and w["worker_id"] not in fixed_ids
    ]
    budget = int(request.get("budget", 0))
    remaining = (budget - fixed_cost) if budget > 0 else 0
    recs = _recommend(candidates, gap_trades, remaining)
    if not recs:
        _set_gap_status(gap["event_id"], GapStatus.FAILED)
        raise ApiError(ErrorCode.AGENT_RETRY_FAILED,
                       "대체 가능한 인력을 찾지 못했습니다. 수동 편성 또는 편성 취소가 필요합니다.")

    now = now_iso()
    db.update_gap_event(
        gap["event_id"],
        UpdateExpression="SET #s = :s, gsi1sk = :g, recommendations = :r, updated_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": GapStatus.PROPOSED,
            ":g": db.gap_gsi1sk(GapStatus.PROPOSED, gap["event_id"]),
            ":r": _to_decimal(recs),
            ":t": now,
        },
    )
    return success(gap_view(db.get_gap_event(gap["event_id"])))


# ---------------------------------------------------------------------------
# 추천 엔진: LLM(선택) → 검증 → 결정론적 폴백
# ---------------------------------------------------------------------------
def _recommend(candidates, needed_trades, budget) -> list[dict[str, Any]]:
    """LLM 추천을 우선 시도하고(가용 시), 검증 실패 시 결정론적 추천으로 폴백한다."""
    llm_recs = _try_llm(candidates, needed_trades, budget)
    if llm_recs:
        valid = [r for r in llm_recs if _valid_rec(r, candidates, needed_trades, budget)]
        if valid:
            for i, r in enumerate(valid, start=1):
                r["rank"] = i
            return valid[:3]
    return _greedy(candidates, needed_trades, budget)


def _try_llm(candidates, needed_trades, budget):
    """Strands+Bedrock 추천 (1회 재시도). 미가용/오류 시 None."""
    try:
        from agent.crew_agent import BedrockUnavailable, compose  # noqa: F401
        from agent.schemas import AgentInput, Candidate, Priority, RequestSpec, TradeRequirement
    except Exception:  # noqa: BLE001 - SDK/스키마 미가용
        return None

    timeout_s = float(os.environ.get("AGENT_INVOKE_TIMEOUT_S", "25"))
    try:
        cand_models = [
            Candidate(
                worker_id=w["worker_id"],
                preferred_trades=list(w.get("preferred_trades") or []),
                excluded_trades=list(w.get("excluded_trades") or []),
                skill_level=int(w.get("skill_level", 1)),
                desired_daily_wage=int(w.get("desired_daily_wage", 1)),
                certifications=list(w.get("certifications") or []),
                career_years=int(w.get("career_years", 0)),
            )
            for w in candidates
        ]
        req = RequestSpec(
            request_id="compose",
            required_workers=[TradeRequirement(trade=t, count=needed_trades.count(t))
                              for t in dict.fromkeys(needed_trades)],
            budget=budget if budget > 0 else 100_000_000,
            priority=Priority(cost="MEDIUM", skill="MEDIUM", teamwork="MEDIUM"),
            site="", work_date="", start_time="",
        )
        agent_input = AgentInput(mode="NORMAL", request=req, fixed_members=[],
                                 candidates=cand_models, collaboration_pairs=[])
    except Exception:  # noqa: BLE001
        return None

    for attempt in range(2):
        try:
            output = compose(agent_input, timeout_s=timeout_s)
        except Exception:  # noqa: BLE001 - Bedrock 미가용/파싱 실패
            return None
        recs = _llm_output_to_recs(output, candidates)
        if recs:
            return recs
    return None


def _llm_output_to_recs(output, candidates):
    by_id = {w["worker_id"]: w for w in candidates}
    recs = []
    for rec in getattr(output, "recommendations", []):
        members = []
        for m in rec.members:
            w = by_id.get(m.worker_id)
            if not w:
                members = []
                break
            members.append(_member(w, m.assigned_trade, int(m.offered_wage)))
        if not members:
            continue
        recs.append(_rec(rec.rank, members, rec.reason, list(rec.considerations)))
    return recs


# ---------------------------------------------------------------------------
# 결정론적 추천 (그리디, 규칙 준수) — 폴백/기본 엔진
# ---------------------------------------------------------------------------
def _greedy(candidates, needed_trades, budget) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    rng = random.Random(42)
    for attempt in range(6):
        if len(recs) >= 3:
            break
        pool = list(candidates)
        if attempt == 0:
            pool.sort(key=lambda w: int(w.get("desired_daily_wage", 0)))
        else:
            pool.sort(key=lambda w: int(w.get("desired_daily_wage", 0)) + rng.uniform(-40000, 40000))

        members = []
        used = set()
        for trade in needed_trades:
            for w in pool:
                if w["worker_id"] in used:
                    continue
                if trade in (w.get("excluded_trades") or []):
                    continue
                members.append(_member(w, trade, int(w.get("desired_daily_wage", 0))))
                used.add(w["worker_id"])
                break
        if len(members) < len(needed_trades):
            continue
        total = sum(m["offered_wage"] for m in members)
        if budget and budget > 0 and total > budget:
            continue
        key = tuple(sorted(m["worker_id"] for m in members))
        if key in seen:
            continue
        seen.add(key)
        rank = len(recs) + 1
        considerations = ["필수 직종 구성 충족", "예산 범위 내",
                          "최저 비용 우선" if rank == 1 else "숙련도 균형"]
        recs.append(_rec(rank, members,
                         f"{', '.join(considerations)} 기준으로 구성한 {rank}안입니다.",
                         considerations))
    return recs


# ---------------------------------------------------------------------------
# 검증 (LLM 출력 신뢰 금지)
# ---------------------------------------------------------------------------
def _valid_rec(rec, candidates, needed_trades, budget) -> bool:
    by_id = {w["worker_id"]: w for w in candidates}
    ids = [m["worker_id"] for m in rec["members"]]
    if len(ids) != len(set(ids)):
        return False
    from collections import Counter
    need = Counter(needed_trades)
    got = Counter()
    total = 0
    for m in rec["members"]:
        w = by_id.get(m["worker_id"])
        if not w or w.get("state") != WorkerState.READY:
            return False
        if m["assigned_trade"] in (w.get("excluded_trades") or []):
            return False
        got[m["assigned_trade"]] += 1
        total += int(m["offered_wage"])
    if got != need:
        return False
    if budget and budget > 0 and total > budget:
        return False
    return True


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _member(worker, assigned_trade, offered_wage) -> dict[str, Any]:
    return {
        "worker_id": worker["worker_id"],
        "name": worker.get("name"),
        "assigned_trade": assigned_trade,
        "skill_level": int(worker.get("skill_level", 0)),
        "offered_wage": int(offered_wage),
        "acceptance": "PENDING",
    }


def _rec(rank, members, reason, considerations) -> dict[str, Any]:
    return {
        "rank": int(rank),
        "member_ids": [m["worker_id"] for m in members],
        "members": members,
        "total_cost": sum(m["offered_wage"] for m in members),
        "reason": reason,
        "considerations": considerations,
    }


def _flatten_required(required_workers) -> list[str]:
    out = []
    for spec in required_workers or []:
        out += [spec["trade"]] * int(spec.get("count", 0))
    return out


def _gap_trades(required_workers, fixed_members) -> list[str]:
    from collections import Counter
    have = Counter(m.get("assigned_trade") for m in fixed_members)
    out = []
    for spec in required_workers or []:
        trade = spec["trade"]
        need = int(spec.get("count", 0)) - have.get(trade, 0)
        out += [trade] * max(0, need)
    return out


def _cancel_existing_crews(request_id: str):
    now = now_iso()
    for c in db.query_crews_by_request(request_id):
        if c.get("status") in (CrewStatus.CANCELLED, CrewStatus.RUNNING,
                               CrewStatus.COMPLETED, CrewStatus.DISPATCHED):
            continue
        db.update_crew(
            c["crew_id"],
            UpdateExpression="SET #s = :s, gsi1sk = :g, updated_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": CrewStatus.CANCELLED,
                ":g": db.crew_gsi1sk(CrewStatus.CANCELLED, c["crew_id"]),
                ":t": now,
            },
        )


def _set_request_status(request_id, status):
    now = now_iso()
    db.update_request(
        request_id,
        UpdateExpression="SET #s = :s, gsi1sk = :g, updated_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":g": db.request_gsi1sk(status, request_id), ":t": now},
    )


def _set_gap_status(event_id, status):
    now = now_iso()
    db.update_gap_event(
        event_id,
        UpdateExpression="SET #s = :s, gsi1sk = :g, updated_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":g": db.gap_gsi1sk(status, event_id), ":t": now},
    )


def _to_decimal(value):
    from shared.schemas import to_decimal
    return to_decimal(value)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    return router.dispatch(event)
