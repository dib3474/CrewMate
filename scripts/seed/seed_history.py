"""seed_history.py (계약 v2).

완료된 작업조와 그에 속한 Assignments(status=COMPLETED)를 생성한다.
작업 이력·협업 이력은 별도 테이블 없이 Assignments GSI1 에서 유도되므로,
이 스크립트가 그 원천 데이터를 만든다. seed_workers 이후 실행한다.

사용법:
  python scripts/seed/seed_history.py
"""

from __future__ import annotations

import argparse
import random
from typing import Any

from faker import Faker

from common import OFFICES, SEED, write_items

from shared.db import query_office_all_workers  # noqa: E402
from shared.schemas import build_assignment, build_crew, build_request  # noqa: E402
from shared.state import AssignmentStatus, CrewStatus, RequestStatus  # noqa: E402

_fake = Faker("ko_KR")


def _init_seed() -> None:
    random.seed(SEED)
    Faker.seed(SEED)


def generate_history(num_crews_per_office: int = 6):
    crews, assignments, requests = [], [], []
    for office_id in OFFICES:
        worker_ids = [w["worker_id"] for w in query_office_all_workers(office_id)]
        if len(worker_ids) < 3:
            continue
        for n in range(num_crews_per_office):
            size = random.randint(3, min(5, len(worker_ids)))
            members = random.sample(worker_ids, k=size)
            date = _fake.date_between("-90d", "-1d").isoformat()
            req = build_request(
                company_id="COMPANY001",
                office_id=office_id,
                site_name=f"{_fake.city()} 과거현장 {n + 1}",
                work_date=date,
                start_time="07:00",
                location_text=_fake.address().replace("\n", " "),
                required_workers=[{"trade": "GENERAL", "count": size}],
                budget=size * 160000,
                status=RequestStatus.COMPLETED,
            )
            requests.append(req)
            crew = build_crew(
                office_id=office_id,
                request_id=req["request_id"],
                proposed_members=[
                    {"worker_id": m, "assigned_trade": "GENERAL", "offered_wage": 160000}
                    for m in members
                ],
                status=CrewStatus.COMPLETED,
                source="MANUAL",
            )
            crews.append(crew)
            for m in members:
                assignments.append(build_assignment(
                    crew_id=crew["crew_id"], worker_id=m,
                    assigned_trade="GENERAL", offered_wage=160000,
                    acceptance="ACCEPTED", status=AssignmentStatus.COMPLETED,
                    created_at=date + "T07:00:00+00:00",
                ))
    return crews, assignments, requests


def main() -> None:
    parser = argparse.ArgumentParser(description="완료 작업조/배치 이력 시드")
    parser.add_argument("--crews-per-office", type=int, default=6)
    args = parser.parse_args()

    _init_seed()
    crews, assignments, requests = generate_history(args.crews_per_office)
    write_items("requests", requests)
    n_c = write_items("crews", crews)
    n_a = write_items("assignments", assignments)
    print(f"[seed] 완료 작업조 {n_c}건, 배치 이력 {n_a}건 생성 완료 (seed={SEED})")


if __name__ == "__main__":
    main()
