from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from b52_telemetry.app import create_app

TELEMETRY_PATH_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_PATH"


def telemetry_path_from_environment() -> Path:
    configured_path = os.environ.get(TELEMETRY_PATH_ENVIRONMENT_VARIABLE)

    if configured_path is None or not configured_path.strip():
        raise RuntimeError(f"{TELEMETRY_PATH_ENVIRONMENT_VARIABLE} must be configured")

    return Path(configured_path)


def create_production_app() -> FastAPI:
    return create_app(telemetry_path_from_environment())


app = create_production_app()
