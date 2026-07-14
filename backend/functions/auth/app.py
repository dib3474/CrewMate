"""auth Lambda (계약 v2).

프론트가 Cognito SDK를 직접 쓰지 않는 A안: 백엔드가 가입/로그인을 래핑한다.

Route (모두 공개 — Cognito Authorizer 없음):
  POST /auth/signup   Cognito 가입 + 역할 그룹 + custom claim. OFFICE/COMPANY 레코드 자동 생성.
  POST /auth/login    Cognito 인증 래핑 → IdToken + 역할 반환.
  GET  /offices       사무소 목록 (가입/요청 화면 선택 리스트).
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from shared import db
from shared.responses import ApiError, ErrorCode, success
from shared.routing import Router
from shared.schemas import (
    build_company,
    build_office,
    new_id,
    office_public_view,
    parse_body,
    require_fields,
)
from shared.state import Role

logger = logging.getLogger()
router = Router()

USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
USER_POOL_CLIENT_ID = os.environ.get("USER_POOL_CLIENT_ID", "")

_cognito = None


def _idp():
    global _cognito
    if _cognito is None:
        _cognito = boto3.client("cognito-idp")
    return _cognito


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """검증 없이 JWT payload를 디코드한다 (방금 Cognito가 발급한 토큰)."""
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:  # noqa: BLE001
        return {}


def _auth_user(*, user_id: str, role: str, name: str, token: str, region: str | None) -> dict[str, Any]:
    user = {"userId": user_id, "role": role, "name": name, "token": token}
    if region:
        user["region"] = region
    return {"user": user}


# ---------------------------------------------------------------------------
# 가입
# ---------------------------------------------------------------------------
@router.route("POST", "/auth/signup", public=True)
def signup(event: dict[str, Any], _principal, _params):
    body = parse_body(event)
    require_fields(body, ["username", "password", "role", "name"])
    username = body["username"]
    password = body["password"]
    role = body["role"]
    name = body["name"]
    region = body.get("region") or ""

    if role not in Role.ALL:
        raise ApiError(ErrorCode.INVALID_INPUT, f"알 수 없는 역할입니다: {role}")

    attributes = [
        {"Name": "name", "Value": name},
        {"Name": "custom:role", "Value": role},
        {"Name": "custom:region", "Value": region},
    ]

    # 역할별 식별자 사전 생성 (custom claim에 주입)
    office_id = new_id("OFFICE_") if role == Role.OFFICE else ""
    company_id = new_id("COMPANY_") if role == Role.COMPANY else ""
    if office_id:
        attributes.append({"Name": "custom:office_id", "Value": office_id})
    if company_id:
        attributes.append({"Name": "custom:company_id", "Value": company_id})

    try:
        resp = _idp().admin_create_user(
            UserPoolId=USER_POOL_ID,
            Username=username,
            MessageAction="SUPPRESS",
            UserAttributes=attributes,
        )
        _idp().admin_set_user_password(
            UserPoolId=USER_POOL_ID,
            Username=username,
            Password=password,
            Permanent=True,
        )
        _idp().admin_add_user_to_group(
            UserPoolId=USER_POOL_ID, Username=username, GroupName=role
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "UsernameExistsException":
            raise ApiError(ErrorCode.USERNAME_TAKEN, "이미 사용 중인 아이디입니다.")
        if code in ("InvalidPasswordException", "InvalidParameterException"):
            raise ApiError(ErrorCode.INVALID_INPUT, "입력값이 유효하지 않습니다.")
        logger.exception("signup_failed")
        raise ApiError(ErrorCode.INTERNAL_ERROR, "가입 처리 중 오류가 발생했습니다.")

    sub = _extract_sub(resp)

    # 역할별 마스터 레코드 자동 생성 (owner_user_id = cognito sub)
    if role == Role.OFFICE:
        db.put_office(build_office(
            office_id=office_id, name=name, region=region or "지역 미설정",
            owner_name=name, owner_user_id=sub,
        ))
    elif role == Role.COMPANY:
        db.put_company(build_company(
            company_id=company_id, name=name, region=region, owner_user_id=sub,
        ))

    token = _login_token(username, password)
    return success(
        _auth_user(user_id=sub or username, role=role, name=name, token=token, region=region)
    )


def _extract_sub(create_resp: dict[str, Any]) -> str:
    for attr in (create_resp.get("User") or {}).get("Attributes", []):
        if attr.get("Name") == "sub":
            return attr.get("Value", "")
    return ""


def _login_token(username: str, password: str) -> str:
    try:
        resp = _idp().admin_initiate_auth(
            UserPoolId=USER_POOL_ID,
            ClientId=USER_POOL_CLIENT_ID,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
        return resp.get("AuthenticationResult", {}).get("IdToken", "")
    except ClientError:
        return ""


# ---------------------------------------------------------------------------
# 로그인
# ---------------------------------------------------------------------------
@router.route("POST", "/auth/login", public=True)
def login(event: dict[str, Any], _principal, _params):
    body = parse_body(event)
    require_fields(body, ["username", "password"])
    username = body["username"]
    password = body["password"]

    try:
        resp = _idp().admin_initiate_auth(
            UserPoolId=USER_POOL_ID,
            ClientId=USER_POOL_CLIENT_ID,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("NotAuthorizedException", "UserNotFoundException"):
            raise ApiError(ErrorCode.UNAUTHORIZED, "아이디 또는 비밀번호가 일치하지 않습니다.")
        logger.exception("login_failed")
        raise ApiError(ErrorCode.INTERNAL_ERROR, "로그인 처리 중 오류가 발생했습니다.")

    id_token = resp.get("AuthenticationResult", {}).get("IdToken", "")
    claims = _decode_jwt_claims(id_token)
    return success(
        _auth_user(
            user_id=claims.get("sub", ""),
            role=claims.get("custom:role", ""),
            name=claims.get("name", username),
            token=id_token,
            region=claims.get("custom:region") or None,
        )
    )


# ---------------------------------------------------------------------------
# 사무소 목록
# ---------------------------------------------------------------------------
@router.route("GET", "/offices", public=True)
def list_offices(_event: dict[str, Any], _principal, _params):
    offices = db.list_offices()
    result = []
    for office in offices:
        count = db.count_office_workers(office["office_id"])
        result.append(office_public_view(office, worker_count=count, active=True))
    result.sort(key=lambda o: o.get("office_id", ""))
    return success(result)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    return router.dispatch(event)
