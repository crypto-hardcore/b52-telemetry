from __future__ import annotations

import json
from asyncio import sleep as async_sleep
from collections.abc import AsyncIterator
from pathlib import Path
from secrets import compare_digest

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from b52_telemetry.authorization import (
    TELEMETRY_SESSION_COOKIE_NAME,
    TelemetryAuthorizer,
    deny_telemetry_access,
)
from b52_telemetry.contract import TelemetryPayload
from b52_telemetry.public_projection import (
    PublicTelemetryPayload,
    project_public_telemetry,
)
from b52_telemetry.session import SessionStore
from b52_telemetry.source import (
    TelemetryFileSource,
    TelemetrySourceInvalid,
    TelemetrySourceUnavailable,
)

TELEMETRY_STREAM_INTERVAL_SECONDS = 1.0


class SessionRequest(BaseModel):
    access_key: str


def _encode_sse_payload(payload: TelemetryPayload) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"data:{serialized}\n\n"


async def _stream_telemetry(
    source: TelemetryFileSource,
    initial_payload: TelemetryPayload,
) -> AsyncIterator[str]:
    payload = initial_payload

    while True:
        yield _encode_sse_payload(payload)
        await async_sleep(TELEMETRY_STREAM_INTERVAL_SECONDS)

        try:
            payload = source.read()
        except (TelemetrySourceUnavailable, TelemetrySourceInvalid):
            return


def create_app(
    telemetry_path: Path,
    telemetry_authorizer: TelemetryAuthorizer = deny_telemetry_access,
    session_store: SessionStore | None = None,
    telemetry_access_key: str | None = None,
) -> FastAPI:
    source = TelemetryFileSource(telemetry_path)
    app = FastAPI()

    @app.get(
        "/api/public/snapshot",
        response_model=None,
    )
    def public_snapshot() -> PublicTelemetryPayload:
        try:
            telemetry = source.read()
        except TelemetrySourceUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="telemetry source unavailable",
            ) from exc
        except TelemetrySourceInvalid as exc:
            raise HTTPException(
                status_code=503,
                detail="telemetry source invalid",
            ) from exc

        return project_public_telemetry(telemetry)

    @app.post("/api/session")
    def create_session(
        session_request: SessionRequest,
        response: Response,
    ) -> dict[str, bool]:
        if session_store is None or telemetry_access_key is None:
            raise HTTPException(
                status_code=503,
                detail="session authentication unavailable",
            )

        if not compare_digest(
            session_request.access_key,
            telemetry_access_key,
        ):
            raise HTTPException(
                status_code=401,
                detail="invalid access credential",
            )

        session_id = session_store.create()
        response.set_cookie(
            key=TELEMETRY_SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/",
        )

        return {"authenticated": True}

    @app.get("/api/session")
    def session_status(request: Request) -> dict[str, bool]:
        if session_store is None:
            return {"authenticated": False}

        session_id = request.cookies.get(TELEMETRY_SESSION_COOKIE_NAME)

        return {
            "authenticated": (
                session_id is not None and session_store.contains(session_id)
            )
        }

    @app.delete("/api/session")
    def delete_session(
        request: Request,
        response: Response,
    ) -> dict[str, bool]:
        if session_store is not None:
            session_id = request.cookies.get(TELEMETRY_SESSION_COOKIE_NAME)

            if session_id is not None:
                session_store.revoke(session_id)

        response.delete_cookie(
            key=TELEMETRY_SESSION_COOKIE_NAME,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )

        return {"authenticated": False}

    @app.get(
        "/api/telemetry/latest",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def latest_telemetry() -> TelemetryPayload:
        try:
            return source.read()
        except TelemetrySourceUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="telemetry source unavailable",
            ) from exc
        except TelemetrySourceInvalid as exc:
            raise HTTPException(
                status_code=503,
                detail="telemetry source invalid",
            ) from exc

    @app.get(
        "/api/telemetry/stream",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def stream_telemetry() -> StreamingResponse:
        try:
            initial_payload = source.read()
        except TelemetrySourceUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="telemetry source unavailable",
            ) from exc
        except TelemetrySourceInvalid as exc:
            raise HTTPException(
                status_code=503,
                detail="telemetry source invalid",
            ) from exc

        return StreamingResponse(
            _stream_telemetry(source, initial_payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
            },
        )

    return app
