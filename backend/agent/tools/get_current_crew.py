"""``get_current_crew`` - read-only Agent tool (Requirement 5.5).

Returns the current crew record for a ``crew_id`` - its current members, active
members, gaps, and required conditions - used mainly during EMERGENCY
re-composition to know which members remain and what must be back-filled. Backed
solely by 담당자 A's read-only ``db.get_crew`` helper - no write/transition helper
is called.

Structure mirrors the other tools: a plain, dependency-injectable core
(:func:`_read_current_crew`) plus a thin ``@tool`` wrapper (:func:`get_current_crew`).
"""
from __future__ import annotations

from typing import Any

from ._shared import current_tool_scope, record_tool_call, resolve_db, to_json_safe, tool

_SAFE_CREW_FIELDS = (
    "crew_id",
    "request_id",
    "status",
    "member_ids",
    "proposed_members",
    "total_cost",
)


def _read_current_crew(crew_id: str, *, db: Any = None) -> Any:
    """Core read logic: return the current crew for ``crew_id``.

    Read-only. Calls only ``db.get_crew`` (Requirement 5.5). ``db`` may be
    dependency-injected for tests; otherwise 담당자 A's ``shared.db`` is
    resolved lazily.
    """
    item = resolve_db(db).get_crew(crew_id)
    if not item:
        return None
    return to_json_safe({field: item[field] for field in _SAFE_CREW_FIELDS if field in item})


@tool
def get_current_crew(crew_id: str) -> Any:
    """현재 호출에 허용된 작업조의 안전한 최신 상태를 반환한다.

    EMERGENCY에서 작업조 ID, 상태, 현재 멤버와 배정 직종을 확인할 때 사용한다.
    실제 결원 직종과 잔여 예산은 AgentInput의 Lambda 계산값을 따른다. 읽기 전용이며
    상태를 변경하지 않는다.

    Args:
        crew_id: AgentInput에 포함된 허용 작업조 ID.

    Returns:
        작업조 ID, 요청 ID, 상태, 멤버, 배정 직종과 비용의 안전 필드.
    """
    current_tool_scope().require_crew(crew_id)
    record_tool_call("get_current_crew")
    return _read_current_crew(crew_id)
