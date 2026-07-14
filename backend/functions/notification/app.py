"""notification Lambda (계약 v2).

Route:
  GET  /notifications        내 알림 목록 (최신순)
  POST /notifications/read   읽음 일괄 처리 (body: ids)
"""

from __future__ import annotations

from typing import Any

from shared import db
from shared.auth import Principal
from shared.responses import success
from shared.routing import Router
from shared.schemas import notification_view, parse_body

router = Router()

_MAX_LIMIT = 100
_DEFAULT_LIMIT = 50


@router.route("GET", "/notifications")
def list_notifications(event, principal: Principal, _params):
    qp = event.get("queryStringParameters") or {}
    limit = _DEFAULT_LIMIT
    if qp.get("limit"):
        try:
            limit = max(1, min(_MAX_LIMIT, int(qp["limit"])))
        except (ValueError, TypeError):
            limit = _DEFAULT_LIMIT
    items = db.query_notifications(principal.user_id, limit=limit)
    return success([notification_view(n) for n in items])


@router.route("POST", "/notifications/read")
def mark_read(event, principal: Principal, _params):
    body = parse_body(event)
    ids = body.get("ids") or []
    updated = 0
    for n in db.query_notifications(principal.user_id, limit=_MAX_LIMIT):
        if n.get("id") in ids and not n.get("read", False):
            db.update_notification_read(principal.user_id, n["sk"])
            updated += 1
    return success({"updated": updated})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    return router.dispatch(event)
