from __future__ import annotations

import json
from asyncio import sleep as async_sleep
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from starlette.responses import StreamingResponse

from b52_telemetry.contract import TelemetryPayload
from b52_telemetry.public_projection import (
    PublicTelemetryPayload,
    project_public_telemetry,
)
from b52_telemetry.source import (
    TelemetryFileSource,
    TelemetrySourceInvalid,
    TelemetrySourceUnavailable,
)

TELEMETRY_STREAM_INTERVAL_SECONDS = 1.0


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


def create_app(telemetry_path: Path) -> FastAPI:
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

    @app.get(
        "/api/telemetry/latest",
        response_model=None,
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
