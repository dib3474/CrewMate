"""``get_ready_workers`` — 읽기 전용 Agent Tool (계약 v2).

사무소의 READY 후보 근로자를 반환한다. 선택적으로 required_trades 로 좁힌다
(preferred_trades 교집합 또는 excluded_trades 미포함 기준).
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

from ._shared import current_tool_scope, record_tool_call, resolve_db, to_json_safe, tool

_SAFE_WORKER_FIELDS = (
    "worker_id",
    "preferred_trades",
    "excluded_trades",
    "desired_daily_wage",
    "certifications",
    "career_years",
)


def _read_ready_workers(
    office_id: str,
    required_trades: Optional[Sequence[str]] = None,
    *,
    allowed_worker_ids: Optional[Sequence[str]] = None,
    db: Any = None,
) -> Any:
    d = resolve_db(db)
    workers = d.query_office_workers_by_state(office_id, "READY")
    if allowed_worker_ids is not None:
        allowed_ids = set(allowed_worker_ids)
        workers = [w for w in workers if w.get("worker_id") in allowed_ids]
    if required_trades:
        allowed = set(required_trades)
        workers = [
            w for w in workers
            if (set(w.get("preferred_trades") or []) & allowed)
            or not (set(w.get("excluded_trades") or []) & allowed)
        ]
    return to_json_safe([
        {field: worker[field] for field in _SAFE_WORKER_FIELDS if field in worker}
        for worker in workers
    ])


@tool
def get_ready_workers(office_id: str, required_trades: Optional[List[str]] = None) -> Any:
    """현재 호출에 허용된 READY 후보의 편성용 상세정보를 반환한다.

    Lambda가 AgentInput의 candidate_worker_ids로 승인한 후보만 반환한다. 이름,
    전화번호와 운영상 부정 지표는 반환하지 않는다. 읽기 전용이며 상태를 변경하지 않는다.

    Args:
        office_id: AgentInput에 포함된 허용 사무소 ID.
        required_trades: 요청이 필요로 하는 직종 목록으로 후보를 좁힌다(선택).

    Returns:
        허용 후보 중 READY 상태이며 안전 필드만 포함한 근로자 목록.
    """
    scope = current_tool_scope()
    scope.require_office(office_id)
    record_tool_call("get_ready_workers")
    return _read_ready_workers(
        office_id,
        required_trades,
        allowed_worker_ids=scope.ready_worker_ids,
    )
