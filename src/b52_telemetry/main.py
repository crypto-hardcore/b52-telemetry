from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from secrets import compare_digest

from fastapi import FastAPI

from b52_telemetry.app import create_app
from b52_telemetry.authorization import SessionTelemetryAuthorizer
from b52_telemetry.session import SessionStore
from b52_telemetry.source_registry import (
    B52InstanceId,
    ProducerAuthorization,
    TelemetrySourceRegistration,
    TelemetrySourceRegistry,
)

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

    registrations: dict[B52InstanceId, TelemetrySourceRegistration] = {}

    for raw_instance_id, raw_registration in decoded_sources.items():
        if not isinstance(raw_instance_id, str) or not raw_instance_id.strip():
            raise RuntimeError(
                f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} instance IDs "
                "must be non-empty strings"
            )

        if not isinstance(raw_registration, dict) or set(raw_registration) != {
            "path",
            "producer",
        }:
            raise RuntimeError(
                f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} registrations "
                "must contain exactly path and producer"
            )
        raw_path = raw_registration["path"]
        raw_producer = raw_registration["producer"]
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise RuntimeError(
                f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} telemetry paths "
                "must be non-empty strings"
            )
        if not isinstance(raw_producer, dict) or set(raw_producer) != {
            "enabled",
            "authorization_generation",
            "credential_sha256",
        }:
            raise RuntimeError(
                f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} producer records "
                "are invalid"
            )
        try:
            registration = TelemetrySourceRegistration(
                path=Path(raw_path),
                producer=ProducerAuthorization(
                    enabled=raw_producer["enabled"],
                    authorization_generation=raw_producer["authorization_generation"],
                    credential_sha256=raw_producer["credential_sha256"],
                ),
            )
            registrations[B52InstanceId(raw_instance_id)] = registration
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"{TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE} contains an invalid "
                "registration"
            ) from exc

    return TelemetrySourceRegistry(registrations)


def telemetry_access_key_from_environment() -> str:
    configured_access_key = os.environ.get(TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE)

    if configured_access_key is None or not configured_access_key.strip():
        raise RuntimeError(
            f"{TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE} must be configured"
        )

    return configured_access_key


def create_production_app() -> FastAPI:
    session_store = SessionStore()
    telemetry_sources = telemetry_sources_from_environment()
    telemetry_access_key = telemetry_access_key_from_environment()
    browser_digest = sha256(telemetry_access_key.encode("utf-8")).hexdigest()
    if any(
        compare_digest(browser_digest, producer_digest)
        for producer_digest in telemetry_sources.producer_credential_digests()
    ):
        raise RuntimeError(
            "browser access key must not equal a producer bearer credential"
        )

    return create_app(
        telemetry_sources,
        telemetry_authorizer=SessionTelemetryAuthorizer(session_store),
        session_store=session_store,
        telemetry_access_key=telemetry_access_key,
    )


app = create_production_app()
