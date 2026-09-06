from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from fastapi import HTTPException, Request

from b52_telemetry.session import SessionStore

TELEMETRY_SESSION_COOKIE_NAME = "b52_telemetry_session"

TelemetryAuthorizer: TypeAlias = Callable[[Request], None]


def deny_telemetry_access(_: Request) -> None:
    raise HTTPException(
        status_code=403,
        detail="telemetry access denied",
    )


class SessionTelemetryAuthorizer:
    def __init__(self, session_store: SessionStore) -> None:
        self._session_store = session_store

    def __call__(self, request: Request) -> None:
        session_id = request.cookies.get(TELEMETRY_SESSION_COOKIE_NAME)

        if session_id is None or not self._session_store.contains(session_id):
            raise HTTPException(
                status_code=401,
                detail="telemetry authentication required",
            )
