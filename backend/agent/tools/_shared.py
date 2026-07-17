"""Internal helpers for the read-only Agent tool modules (담당자 B).

This module is **not a tool** and is never placed in the tool registry. It holds
the cross-cutting concerns shared by the four read-only tools:

1. :func:`tool` - a guarded re-export of Strands' ``@tool`` decorator. When the
   SDK is installed the real decorator turns the wrapped function into an Agent
   tool (auto-generating its spec from the signature/docstring). When the SDK is
   absent in a lightweight test environment it degrades to an identity decorator so
   the plain read logic remains directly callable.
2. :func:`resolve_db` - a **lazy** resolver for 담당자 A's read-only ``db`` helper.
3. :class:`ToolAccessScope` - invocation-local authorization. Even if model input
   contains a malicious instruction, a tool can only read the request, office, crew,
   and workers that Lambda approved for that invocation.

Design references: ``design.md`` -> "3. Agent Tools" / "주 실행 경로: 사전
조립(pre-assembly) 우선"; ``requirements.md`` -> Requirement 5.

"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
import logging
from typing import Any, Callable, TypeVar

__all__ = [
    "STRANDS_AVAILABLE",
    "ToolAccessDenied",
    "ToolAccessScope",
    "current_tool_scope",
    "record_tool_call",
    "resolve_db",
    "tool",
    "tool_access_scope",
    "to_json_safe",
]

F = TypeVar("F", bound=Callable[..., Any])
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Strands ``@tool`` decorator guard                                            #
# --------------------------------------------------------------------------- #
# The tool modules always ``from ._shared import tool`` regardless of whether the
# SDK is present, so tool definitions read identically in both environments and
# task 2.3 can register them with a real Strands ``Agent(tools=[...])`` once the
# SDK lands. Registration (wrapping) is kept separate from the plain read logic:
# each tool module keeps a private ``_read_*`` core function (dependency-injectable
# and SDK-free) and exposes a thin ``@tool``-decorated wrapper on top of it.
try:  # canonical top-level re-export (documented: ``from strands import tool``)
    from strands import tool as _strands_tool  # type: ignore

    STRANDS_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means the SDK is unavailable
    try:  # fall back to the decorator's module path if the re-export moves
        from strands.tools.decorator import tool as _strands_tool  # type: ignore

        STRANDS_AVAILABLE = True
    except Exception:  # noqa: BLE001
        STRANDS_AVAILABLE = False

        def _strands_tool(func: Any = None, *args: Any, **kwargs: Any) -> Any:
            """No-op stand-in supporting both ``@tool`` and ``@tool(...)`` usage.

            Returns the undecorated function so the plain read logic stays directly
            callable/testable when the SDK is not installed.
            """
            if func is None:  # used as ``@tool(...)`` -> return the real decorator

                def _identity(inner: F) -> F:
                    return inner

                return _identity
            return func


# Public name the tool modules import. Aliased (not re-wrapped) so both bare
# ``@tool`` and parameterized ``@tool(...)`` usage pass straight through to the
# real SDK decorator when available.
tool = _strands_tool


# --------------------------------------------------------------------------- #
# Invocation-local authorization scope                                         #
# --------------------------------------------------------------------------- #
class ToolAccessDenied(PermissionError):
    """Raised when a model requests data outside Lambda's approved scope."""


@dataclass(frozen=True)
class ToolAccessScope:
    """Closed-world identifiers that read-only tools may access in one invocation."""

    request_id: str
    office_id: str
    crew_id: str | None
    ready_worker_ids: frozenset[str]
    history_worker_ids: frozenset[str]

    def require_request(self, request_id: str) -> None:
        if request_id != self.request_id:
            raise ToolAccessDenied("request_id is outside the authorized tool scope")

    def require_office(self, office_id: str) -> None:
        if office_id != self.office_id:
            raise ToolAccessDenied("office_id is outside the authorized tool scope")

    def require_crew(self, crew_id: str) -> None:
        if not self.crew_id or crew_id != self.crew_id:
            raise ToolAccessDenied("crew_id is outside the authorized tool scope")

    def require_workers(self, worker_ids: list[str]) -> None:
        if not set(worker_ids).issubset(self.history_worker_ids):
            raise ToolAccessDenied("worker_ids contain values outside the authorized tool scope")


_TOOL_ACCESS_SCOPE: ContextVar[ToolAccessScope | None] = ContextVar(
    "crewmate_tool_access_scope",
    default=None,
)


@contextmanager
def tool_access_scope(scope: ToolAccessScope):
    """Install ``scope`` for the current Agent invocation and always clear it."""
    token = _TOOL_ACCESS_SCOPE.set(scope)
    try:
        yield scope
    finally:
        _TOOL_ACCESS_SCOPE.reset(token)


def current_tool_scope() -> ToolAccessScope:
    """Return the active scope or deny calls made outside Agent orchestration."""
    scope = _TOOL_ACCESS_SCOPE.get()
    if scope is None:
        raise ToolAccessDenied("read-only Agent tool called without an authorized scope")
    return scope


def record_tool_call(tool_name: str, *, target_count: int = 1) -> None:
    """Emit metadata-only audit logging without worker IDs or tool payloads."""
    scope = current_tool_scope()
    logger.info(
        "crew_agent_tool_call request_id=%s tool=%s target_count=%d",
        scope.request_id,
        tool_name,
        target_count,
    )


def to_json_safe(value: Any) -> Any:
    """Convert DynamoDB ``Decimal`` values without changing the safe field set."""
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, list):
        return [to_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: to_json_safe(item) for key, item in value.items()}
    return value


# --------------------------------------------------------------------------- #
# Lazy resolver for 담당자 A's read-only ``db`` helper                          #
# --------------------------------------------------------------------------- #
def resolve_db(db: Any = None) -> Any:
    """Return the object exposing 담당자 A's read-only ``db`` helper functions.

    Parameters
    ----------
    db:
        Optional dependency-injected helper (an object/module exposing
        ``get_work_request``, ``query_ready_workers``, ``get_workers``,
        ``get_worker_collaborations``, ``get_crew``). Tests pass a
        ``FakeSharedDB`` here; the Agent-invoked tool wrappers pass nothing.

    When ``db`` is ``None`` the real ``shared.db`` module is imported
    **lazily** (at call time, not import time). In deployment this is 담당자 A's
    module packaged as a shared Lambda Layer; in tests it is the stub registered
    under ``shared.db`` by ``install_shared_stubs``. Deferring the import
    keeps every tool module importable even though ``backend/shared`` does not
    exist on disk in this repo.
    """
    if db is not None:
        return db
    # 계약 v2: 공용 엔터티별 테이블 read 헬퍼 (지연 임포트).
    from shared import db as shared_db

    return shared_db
