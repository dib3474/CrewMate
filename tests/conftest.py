"""pytest 공용 픽스처 (계약 v2): moto 기반 8개 엔터티 테이블 + API 이벤트 빌더."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

REGION = "ap-northeast-2"

_TABLE_ENV = {
    "WORKERS_TABLE": "CrewMate-Workers-test",
    "OFFICES_TABLE": "CrewMate-Offices-test",
    "COMPANIES_TABLE": "CrewMate-Companies-test",
    "REQUESTS_TABLE": "CrewMate-Requests-test",
    "CREWS_TABLE": "CrewMate-Crews-test",
    "ASSIGNMENTS_TABLE": "CrewMate-Assignments-test",
    "GAP_EVENTS_TABLE": "CrewMate-GapEvents-test",
    "NOTIFICATIONS_TABLE": "CrewMate-Notifications-test",
}


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    for k, v in _TABLE_ENV.items():
        monkeypatch.setenv(k, v)


def _gsi(name, pk, sk):
    return {
        "IndexName": name,
        "KeySchema": [
            {"AttributeName": pk, "KeyType": "HASH"},
            {"AttributeName": sk, "KeyType": "RANGE"},
        ],
        "Projection": {"ProjectionType": "ALL"},
    }


def _create_all(client):
    def attrs(*names):
        return [{"AttributeName": n, "AttributeType": "S"} for n in names]

    def ks(pk, sk=None):
        k = [{"AttributeName": pk, "KeyType": "HASH"}]
        if sk:
            k.append({"AttributeName": sk, "KeyType": "RANGE"})
        return k

    specs = [
        ("CrewMate-Workers-test", attrs("worker_id", "office_id", "gsi1sk"),
         ks("worker_id"), [_gsi("GSI1", "office_id", "gsi1sk")]),
        ("CrewMate-Offices-test", attrs("office_id"), ks("office_id"), None),
        ("CrewMate-Companies-test", attrs("company_id"), ks("company_id"), None),
        ("CrewMate-Requests-test", attrs("request_id", "office_id", "gsi1sk", "company_id"),
         ks("request_id"), [_gsi("GSI1", "office_id", "gsi1sk"), _gsi("GSI2", "company_id", "request_id")]),
        ("CrewMate-Crews-test", attrs("crew_id", "office_id", "gsi1sk"),
         ks("crew_id"), [_gsi("GSI1", "office_id", "gsi1sk")]),
        ("CrewMate-Assignments-test", attrs("crew_id", "worker_id", "created_at"),
         ks("crew_id", "worker_id"), [_gsi("GSI1", "worker_id", "created_at")]),
        ("CrewMate-GapEvents-test", attrs("event_id", "office_id", "gsi1sk"),
         ks("event_id"), [_gsi("GSI1", "office_id", "gsi1sk")]),
        ("CrewMate-Notifications-test", attrs("user_id", "sk"), ks("user_id", "sk"), None),
    ]
    for name, ad, kschema, gsis in specs:
        kwargs = dict(TableName=name, BillingMode="PAY_PER_REQUEST",
                      AttributeDefinitions=ad, KeySchema=kschema)
        if gsis:
            kwargs["GlobalSecondaryIndexes"] = gsis
        client.create_table(**kwargs)


@pytest.fixture
def tables(_aws_env):
    """moto 목킹된 8개 엔터티 테이블. shared.db 캐시를 리셋한다."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name=REGION)
        _create_all(client)

        import shared.db as db
        db._resource = None
        db._client = None
        db._tables = {}
        yield db


def make_event(method, path, *, role=None, sub="user-1", body=None,
               office_id=None, company_id=None, path_params=None):
    claims = {"sub": sub}
    if role:
        claims["custom:role"] = role
    if office_id:
        claims["custom:office_id"] = office_id
    if company_id:
        claims["custom:company_id"] = company_id
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path_params,
        "requestContext": {"authorizer": {"claims": claims}},
    }


def body_of(response):
    return json.loads(response["body"])
