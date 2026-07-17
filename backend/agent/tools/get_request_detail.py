"""``get_request_detail`` - read-only Agent tool (Requirement 5.2).

Returns the detail conditions of a work request. Backed solely by 담당자 A's
read-only ``db.get_work_request`` helper - no write/transition helper is called.

Structure (see ``_shared`` for the rationale):
- :func:`_read_request_detail` is the plain, dependency-injectable core read
  logic. It stays directly callable/testable without the Strands SDK.
- :func:`get_request_detail` is the thin ``@tool``-decorated wrapper the Agent
  sees; its signature is kept clean (only ``request_id``) so the generated tool
  spec never exposes internal plumbing.
"""
from __future__ import annotations

from typing import Any

from ._shared import current_tool_scope, record_tool_call, resolve_db, to_json_safe, tool

_SAFE_REQUEST_FIELDS = (
    "request_id",
    "office_id",
    "site_name",
    "work_date",
    "start_time",
    "required_workers",
    "budget",
    "priority",
    "status",
)


def _read_request_detail(request_id: str, *, db: Any = None) -> Any:
    """Core read logic: return the work request detail for ``request_id``.

    Read-only. Calls only ``db.get_request`` (계약 v2). ``db`` may be
    dependency-injected for tests; otherwise 공용 ``shared.db`` 를 지연 해석한다.
    """
    item = resolve_db(db).get_request(request_id)
    if not item:
        return None
    return to_json_safe({field: item[field] for field in _SAFE_REQUEST_FIELDS if field in item})


@tool
def get_request_detail(request_id: str) -> Any:
    """현재 호출에 허용된 작업 요청의 안전한 최신 조건을 반환한다.

    입력 조건이 누락되었거나 충돌하는지 확인할 때 사용한다. 필요 직종·인원,
    예산, 우선순위, 현장과 작업 시간만 반환하며 자유서술 메모나 개인정보는
    반환하지 않는다. 읽기 전용이며 상태를 변경하지 않는다.

    Args:
        request_id: AgentInput에 포함된 허용 요청 ID.

    Returns:
        허용된 요청의 안전 필드만 포함한 최신 조건.
    """
    current_tool_scope().require_request(request_id)
    record_tool_call("get_request_detail")
    return _read_request_detail(request_id)
