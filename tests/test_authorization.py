from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from b52_telemetry.authorization import (
    TELEMETRY_SESSION_COOKIE_NAME,
    SessionTelemetryAuthorizer,
)
from b52_telemetry.session import SessionStore


def make_request(cookie_value: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []

    if cookie_value is not None:
        headers.append(
            (
                b"cookie",
                f"{TELEMETRY_SESSION_COOKIE_NAME}={cookie_value}".encode(),
            )
        )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/telemetry/latest",
        "headers": headers,
    }

    return Request(scope)


def test_authorizer_accepts_active_session() -> None:
    store = SessionStore()
    session_id = store.create()
    authorizer = SessionTelemetryAuthorizer(store)

    authorizer(make_request(session_id))


@pytest.mark.parametrize("session_id", [None, "", "unknown-session"])
def test_authorizer_rejects_missing_or_invalid_session(
    session_id: str | None,
) -> None:
    store = SessionStore()
    authorizer = SessionTelemetryAuthorizer(store)

    with pytest.raises(HTTPException) as exc_info:
        authorizer(make_request(session_id))

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "telemetry authentication required"


def test_authorizer_rejects_revoked_session() -> None:
    store = SessionStore()
    session_id = store.create()
    store.revoke(session_id)
    authorizer = SessionTelemetryAuthorizer(store)

    with pytest.raises(HTTPException) as exc_info:
        authorizer(make_request(session_id))

    assert exc_info.value.status_code == 401
