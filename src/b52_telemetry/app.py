from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from b52_telemetry.contract import TelemetryPayload
from b52_telemetry.source import (
    TelemetryFileSource,
    TelemetrySourceInvalid,
    TelemetrySourceUnavailable,
)


def create_app(telemetry_path: Path) -> FastAPI:
    source = TelemetryFileSource(telemetry_path)
    app = FastAPI()

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

    return app
