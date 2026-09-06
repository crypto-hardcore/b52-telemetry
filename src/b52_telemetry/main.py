from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from b52_telemetry.app import create_app
from b52_telemetry.authorization import SessionTelemetryAuthorizer
from b52_telemetry.session import SessionStore

TELEMETRY_PATH_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_PATH"
TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_ACCESS_KEY"


def telemetry_path_from_environment() -> Path:
    configured_path = os.environ.get(TELEMETRY_PATH_ENVIRONMENT_VARIABLE)

    if configured_path is None or not configured_path.strip():
        raise RuntimeError(f"{TELEMETRY_PATH_ENVIRONMENT_VARIABLE} must be configured")

    return Path(configured_path)


def telemetry_access_key_from_environment() -> str:
    configured_access_key = os.environ.get(TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE)

    if configured_access_key is None or not configured_access_key.strip():
        raise RuntimeError(
            f"{TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE} must be configured"
        )

    return configured_access_key


def create_production_app() -> FastAPI:
    session_store = SessionStore()

    return create_app(
        telemetry_path_from_environment(),
        telemetry_authorizer=SessionTelemetryAuthorizer(session_store),
        session_store=session_store,
        telemetry_access_key=telemetry_access_key_from_environment(),
    )


app = create_production_app()
