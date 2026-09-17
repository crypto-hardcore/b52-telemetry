from __future__ import annotations

import json
from asyncio import sleep as async_sleep
from collections.abc import AsyncIterator
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
from b52_telemetry.fleet_projection import FleetSnapshot, project_fleet
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
from b52_telemetry.source_registry import (
    B52InstanceId,
    TelemetrySourceRegistry,
    UnknownTelemetrySource,
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


def _resolve_source(
    registry: TelemetrySourceRegistry,
    instance_id: str,
) -> TelemetryFileSource:
    try:
        identity = B52InstanceId(instance_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail="B-52 telemetry source not found",
        ) from exc

    try:
        return registry.resolve(identity)
    except UnknownTelemetrySource as exc:
        raise HTTPException(
            status_code=404,
            detail="B-52 telemetry source not found",
        ) from exc


def _read_source(source: TelemetryFileSource) -> TelemetryPayload:
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


def create_app(
    telemetry_sources: TelemetrySourceRegistry,
    telemetry_authorizer: TelemetryAuthorizer = deny_telemetry_access,
    session_store: SessionStore | None = None,
    telemetry_access_key: str | None = None,
) -> FastAPI:
    app = FastAPI()

    @app.get(
        "/api/public/instances/{instance_id}/snapshot",
        response_model=None,
    )
    def public_snapshot(instance_id: str) -> PublicTelemetryPayload:
        source = _resolve_source(telemetry_sources, instance_id)
        telemetry = _read_source(source)
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
        "/api/telemetry/instances",
        dependencies=[Depends(telemetry_authorizer)],
    )
    def telemetry_instances() -> dict[str, list[str]]:
        return {
            "instances": [
                instance_id.value for instance_id in telemetry_sources.instance_ids()
            ]
        }

    @app.get(
        "/api/telemetry/fleet",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def fleet_telemetry() -> FleetSnapshot:
        return project_fleet(telemetry_sources)

    @app.get(
        "/api/telemetry/instances/{instance_id}/latest",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def latest_telemetry(instance_id: str) -> TelemetryPayload:
        source = _resolve_source(telemetry_sources, instance_id)
        return _read_source(source)

    @app.get(
        "/api/telemetry/instances/{instance_id}/stream",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def stream_telemetry(instance_id: str) -> StreamingResponse:
        source = _resolve_source(telemetry_sources, instance_id)
        initial_payload = _read_source(source)

        return StreamingResponse(
            _stream_telemetry(source, initial_payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
            },
        )

    return app
