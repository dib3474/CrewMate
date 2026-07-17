"""작업 시작 전 요청 종료를 원자적으로 처리한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import db, txn
from .schemas import now_iso
from .state import (
    Acceptance,
    AssignmentStatus,
    CrewStatus,
    GapStatus,
    RequestStatus,
    WorkerState,
)


class CancellationConflict(ValueError):
    """작업이 시작됐거나 이미 종료되어 취소할 수 없는 상태."""


@dataclass
class CancellationResult:
    restored_workers: list[dict[str, Any]]
    cancelled_crew_ids: list[str]


_TERMINAL_ASSIGNMENTS = {
    AssignmentStatus.DECLINED,
    AssignmentStatus.CANCELLED,
    AssignmentStatus.NO_SHOW,
    AssignmentStatus.LEFT_SITE,
    AssignmentStatus.COMPLETED,
}
_ACTIVE_GAPS = {
    GapStatus.DETECTED,
    GapStatus.RECOMPOSING,
    GapStatus.PROPOSED,
    GapStatus.APPROVED,
}


def cancel_request_before_start(
    request: dict[str, Any],
    *,
    final_status: str,
    reason_field: str,
    reason: str,
) -> CancellationResult:
    """연결된 편성과 배정을 정리하고 요청을 REJECTED/CANCELLED로 종료한다."""
    if final_status not in (RequestStatus.REJECTED, RequestStatus.CANCELLED):
        raise ValueError("unsupported request cancellation status")
    if request.get("status") in (
        RequestStatus.RUNNING,
        RequestStatus.COMPLETED,
        RequestStatus.CANCELLED,
        RequestStatus.REJECTED,
    ):
        raise CancellationConflict("이미 작업이 시작·완료되었거나 종료된 요청입니다.")

    crews = [
        crew for crew in db.query_crews_by_request(request["request_id"])
        if crew.get("status") != CrewStatus.CANCELLED
    ]
    if any(crew.get("status") in (CrewStatus.RUNNING, CrewStatus.COMPLETED) for crew in crews):
        raise CancellationConflict("작업이 시작되었거나 완료된 편성은 취소할 수 없습니다.")

    now = now_iso()
    entries: list[dict[str, Any]] = []
    restored: dict[str, dict[str, Any]] = {}
    cancelled_crew_ids: list[str] = []

    for crew in crews:
        crew_id = crew["crew_id"]
        for assignment in db.query_crew_assignments(crew_id):
            if assignment.get("acceptance") == Acceptance.DECLINED:
                continue
            if assignment.get("status") in _TERMINAL_ASSIGNMENTS:
                continue
            worker = db.get_worker(assignment["worker_id"])
            if (
                worker
                and worker.get("state") in (WorkerState.NOTIFIED, WorkerState.RESERVED)
                and worker.get("current_crew_id") == crew_id
            ):
                was_reserved = worker["state"] == WorkerState.RESERVED
                entries.append(txn.worker_entry(
                    worker["worker_id"],
                    now=now,
                    to_state=WorkerState.READY,
                    from_states=[worker["state"]],
                    current_offer=None,
                    current_crew_id=None,
                    dec_dispatched=was_reserved,
                ))
                restored[worker["worker_id"]] = worker
            entries.append(txn.assignment_update_entry(
                crew_id,
                assignment["worker_id"],
                now=now,
                acceptance=Acceptance.DECLINED,
                status=AssignmentStatus.CANCELLED,
            ))

        entries.append(txn.crew_status_entry(
            crew_id,
            to_status=CrewStatus.CANCELLED,
            from_statuses=[crew["status"]],
            now=now,
        ))
        cancelled_crew_ids.append(crew_id)
        for gap in db.query_gap_events_by_crew(crew_id):
            if gap.get("status") in _ACTIVE_GAPS:
                entries.append(txn.gap_status_entry(
                    gap["event_id"],
                    to_status=GapStatus.FAILED,
                    from_statuses=[gap["status"]],
                    now=now,
                ))

    entries.append(txn.request_status_entry(
        request["request_id"],
        to_status=final_status,
        from_statuses=[request["status"]],
        now=now,
        extra_set={reason_field: reason},
    ))
    txn.run(entries)
    return CancellationResult(list(restored.values()), cancelled_crew_ids)
