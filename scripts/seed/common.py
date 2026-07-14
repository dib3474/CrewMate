"""시드 스크립트 공용 유틸 (계약 v2, 엔터티별 테이블).

- backend/ 를 import 경로에 추가
- 사무소/건설사/직종/지역 상수
- 테이블별 리셋(스캔 후 삭제) 및 배치 쓰기

seed = 42 고정으로 재현 가능한 합성 데이터를 만든다. 주민등록번호는 생성하지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from shared import db  # noqa: E402

SEED = 42

OFFICES = ["OFFICE001", "OFFICE002"]
COMPANIES = ["COMPANY001", "COMPANY002"]

TRADES = ["FORMWORK", "REBAR", "MASONRY", "MATERIAL_CARRY", "GENERAL"]
REGIONS = [
    "부산 해운대구",
    "부산 사상구",
    "부산 부산진구",
    "부산 동래구",
    "부산 강서구",
]
CERTIFICATIONS = ["비계기능사", "거푸집기능사", "철근기능사", "건설안전기사", "안전교육이수"]

# 테이블 key(=PK[,SK]) 속성명
_TABLE_KEYS: dict[str, tuple] = {
    "workers": ("worker_id",),
    "offices": ("office_id",),
    "companies": ("company_id",),
    "requests": ("request_id",),
    "crews": ("crew_id",),
    "assignments": ("crew_id", "worker_id"),
    "gap_events": ("event_id",),
    "notifications": ("user_id", "sk"),
}

_TABLE_ACCESSOR = {
    "workers": db.workers_table,
    "offices": db.offices_table,
    "companies": db.companies_table,
    "requests": db.requests_table,
    "crews": db.crews_table,
    "assignments": db.assignments_table,
    "gap_events": db.gap_events_table,
    "notifications": db.notifications_table,
}


def reset_table(table_key: str) -> int:
    table = _TABLE_ACCESSOR[table_key]()
    keys = _TABLE_KEYS[table_key]
    proj = ", ".join(f"#{k}" for k in keys)
    names = {f"#{k}": k for k in keys}
    deleted = 0
    scan_kwargs: dict[str, Any] = {"ProjectionExpression": proj, "ExpressionAttributeNames": names}
    while True:
        resp = table.scan(**scan_kwargs)
        items = resp.get("Items", [])
        with table.batch_writer() as batch:
            for it in items:
                batch.delete_item(Key={k: it[k] for k in keys})
                deleted += 1
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return deleted


def reset_all() -> int:
    total = 0
    for key in _TABLE_KEYS:
        total += reset_table(key)
    return total


def write_items(table_key: str, items: Iterable[dict[str, Any]]) -> int:
    items = list(items)
    db.batch_put(table_key, items)
    return len(items)
