from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI

from b52_telemetry.source_registry import B52InstanceId

TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_SOURCES"
TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_ACCESS_KEY"
MODULE_NAME = "b52_telemetry.main"


def import_main() -> ModuleType:
    sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


def test_production_app_uses_configured_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_path = tmp_path / "B52-001.json"
    second_path = tmp_path / "B52-002.json"

    first_payload = {
        "schema_version": 3,
        "generated_at": "2026-09-16T10:00:00+00:00",
        "system": {},
        "market": None,
        "mission": None,
    }
    second_payload = {
        "schema_version": 3,
        "generated_at": "2026-09-16T10:00:01+00:00",
        "system": {},
        "market": None,
        "mission": None,
    }

    first_path.write_text(json.dumps(first_payload), encoding="utf-8")
    second_path.write_text(json.dumps(second_payload), encoding="utf-8")

    monkeypatch.setenv(
        TELEMETRY_SOURCES_ENVIRONMENT_VARIABLE,
        json.dumps(
            {
                "B52-001": str(first_path),
                "B52-002": str(second_path),
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
                "B52-001": str(tmp_path / "telemetry.jsonl"),
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
