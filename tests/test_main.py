from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI

from b52_telemetry.source_registry import B52InstanceId
from tests.transport_support import PRODUCER_DIGEST, PRODUCER_TOKEN, write_accepted

TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_SOURCES"
TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_ACCESS_KEY"
MODULE_NAME = "b52_telemetry.main"


def configured_registration(
    path: Path,
    *,
    credential_digest: str = PRODUCER_DIGEST,
) -> dict[str, object]:
    return {
        "path": str(path),
        "producer": {
            "enabled": True,
            "authorization_generation": 1,
            "credential_sha256": credential_digest,
        },
    }


def import_main() -> ModuleType:
    sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


def test_production_app_uses_configured_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_path = tmp_path / "B52-001" / "telemetry.latest.json"
    second_path = tmp_path / "B52-002" / "telemetry.latest.json"

    first_payload = {
        "schema_version": 10,
        "instance": "first-process",
        "environment": "testnet",
        "position_sizing_leverage": 3,
        "generated_at": "2026-09-16T10:00:00+00:00",
        "phase": "AWAITING_OPERATOR",
        "system": {},
        "market": None,
        "mission": None,
    }
    second_payload = {
        "schema_version": 10,
        "instance": "second-process",
        "environment": "testnet",
        "position_sizing_leverage": 3,
        "generated_at": "2026-09-16T10:00:01+00:00",
        "phase": "AWAITING_OPERATOR",
        "system": {},
        "market": None,
        "mission": None,
    }

    write_accepted(first_path, first_payload, identity="B52-001")
    write_accepted(second_path, second_payload, identity="B52-002")

    monkeypatch.setenv(
        TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE,
        json.dumps(
            {
                "B52-001": configured_registration(first_path),
                "B52-002": configured_registration(
                    second_path,
                    credential_digest="1" * 64,
                ),
            }
        ),
    )
    monkeypatch.setenv(
        TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE,
        "production-access-key",
    )

    main = import_main()
    registry = main.telemetry_sources_from_environment()

    assert isinstance(main.app, FastAPI)
    assert registry.instance_ids() == (
        B52InstanceId("B52-001"),
        B52InstanceId("B52-002"),
    )
    assert registry.resolve(B52InstanceId("B52-001")).read() == first_payload
    assert registry.resolve(B52InstanceId("B52-002")).read() == second_payload
    assert main.telemetry_access_key_from_environment() == "production-access-key"


@pytest.mark.parametrize("configured_sources", [None, "", "   "])
def test_production_app_requires_telemetry_sources(
    configured_sources: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE,
        "production-access-key",
    )

    if configured_sources is None:
        monkeypatch.delenv(
            TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE,
            raising=False,
        )
    else:
        monkeypatch.setenv(
            TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE,
            configured_sources,
        )

    sys.modules.pop(MODULE_NAME, None)

    with pytest.raises(
        RuntimeError,
        match="B52_TELEMETRY_SOURCES must be configured",
    ):
        importlib.import_module(MODULE_NAME)


@pytest.mark.parametrize(
    "configured_sources",
    [
        "{",
        "[]",
        "{}",
        '{"": "/tmp/telemetry.jsonl"}',
        '{"B52-001": ""}',
        '{"B52-001": 42}',
    ],
)
def test_production_app_rejects_invalid_telemetry_sources(
    configured_sources: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE,
        configured_sources,
    )
    monkeypatch.setenv(
        TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE,
        "production-access-key",
    )

    sys.modules.pop(MODULE_NAME, None)

    with pytest.raises(RuntimeError, match="B52_TELEMETRY_SOURCES"):
        importlib.import_module(MODULE_NAME)


@pytest.mark.parametrize("configured_access_key", [None, "", "   "])
def test_production_app_requires_telemetry_access_key(
    tmp_path: Path,
    configured_access_key: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE,
        json.dumps(
            {
                "B52-001": configured_registration(
                    tmp_path / "B52-001" / "telemetry.latest.json"
                ),
            }
        ),
    )

    if configured_access_key is None:
        monkeypatch.delenv(
            TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE,
            raising=False,
        )
    else:
        monkeypatch.setenv(
            TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE,
            configured_access_key,
        )

    sys.modules.pop(MODULE_NAME, None)

    with pytest.raises(
        RuntimeError,
        match="B52_TELEMETRY_ACCESS_KEY must be configured",
    ):
        importlib.import_module(MODULE_NAME)


def test_production_app_rejects_browser_key_equal_to_producer_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE,
        json.dumps(
            {
                "B52-001": configured_registration(
                    tmp_path / "B52-001" / "telemetry.latest.json"
                )
            }
        ),
    )
    monkeypatch.setenv(TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE, PRODUCER_TOKEN)
    sys.modules.pop(MODULE_NAME, None)

    with pytest.raises(
        RuntimeError,
        match="browser access key must not equal",
    ):
        importlib.import_module(MODULE_NAME)
