"""``get_ready_workers`` — 읽기 전용 Agent Tool (계약 v2).

사무소의 READY 후보 근로자를 반환한다. 선택적으로 required_trades 로 좁힌다
(preferred_trades 교집합 또는 excluded_trades 미포함 기준).
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

from ._shared import resolve_db, tool


def _read_ready_workers(
    office_id: str,
    required_trades: Optional[Sequence[str]] = None,
    *,
    db: Any = None,
) -> Any:
    d = resolve_db(db)
    workers = d.query_office_workers_by_state(office_id, "READY")
    if required_trades:
        allowed = set(required_trades)
        workers = [
            w for w in workers
            if (set(w.get("preferred_trades") or []) & allowed)
            or not (set(w.get("excluded_trades") or []) & allowed)
        ]
    return workers


@tool
def get_ready_workers(office_id: str, required_trades: Optional[List[str]] = None) -> Any:
    """사무소의 READY 후보 근로자를 반환한다 (읽기 전용, 상태 변경 없음).

    Args:
        office_id: 후보를 조회할 사무소.
        required_trades: 요청이 필요로 하는 직종 목록으로 후보를 좁힌다(선택).

    Returns:
        해당 사무소의 READY 근로자 목록.
    """
    return _read_ready_workers(office_id, required_trades)
