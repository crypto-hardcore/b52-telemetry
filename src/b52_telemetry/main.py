from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI

from b52_telemetry.app import create_app
from b52_telemetry.authorization import SessionTelemetryAuthorizer
from b52_telemetry.session import SessionStore
from b52_telemetry.source_registry import B52InstanceId, TelemetrySourceRegistry

TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_SOURCES"
TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_ACCESS_KEY"


def telemetry_sources_from_environment() -> TelemetrySourceRegistry:
    configured_sources = os.environ.get(TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE)

    if configured_sources is None or not configured_sources.strip():
        raise RuntimeError(
            f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} must be configured"
        )

    try:
        decoded_sources = json.loads(configured_sources)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} must contain valid JSON"
        ) from exc

    if not isinstance(decoded_sources, dict) or not decoded_sources:
        raise RuntimeError(
            f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} must contain "
            "a non-empty JSON object"
        )

    sources: dict[B52InstanceId, Path] = {}

    for raw_instance_id, raw_path in decoded_sources.items():
        if not isinstance(raw_instance_id, str) or not raw_instance_id.strip():
            raise RuntimeError(
                f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} instance IDs "
                "must be non-empty strings"
            )

        if not isinstance(raw_path, str) or not raw_path.strip():
            raise RuntimeError(
                f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} telemetry paths "
                "must be non-empty strings"
            )

        sources[B52InstanceId(raw_instance_id)] = Path(raw_path)

    return TelemetrySourceRegistry(sources)


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
        telemetry_sources_from_environment(),
        telemetry_authorizer=SessionTelemetryAuthorizer(session_store),
        session_store=session_store,
        telemetry_access_key=telemetry_access_key_from_environment(),
    )


app = create_production_app()
