from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

TELEMETRY_PATH_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_PATH"
TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE = "B52_TELEMETRY_ACCESS_KEY"
MODULE_NAME = "b52_telemetry.main"


def import_main() -> object:
    sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


def test_production_app_uses_configured_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry_path = tmp_path / "telemetry.latest.json"
    monkeypatch.setenv(
        TELEMETRY_PATH_ENVIRONMENT_VARIABLE,
        str(telemetry_path),
    )
    monkeypatch.setenv(
        TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE,
        "production-access-key",
    )

    main = import_main()

    assert isinstance(main.app, FastAPI)
    assert main.telemetry_path_from_environment() == telemetry_path
    assert main.telemetry_access_key_from_environment() == "production-access-key"


@pytest.mark.parametrize("configured_path", [None, "", "   "])
def test_production_app_requires_telemetry_path(
    configured_path: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        TELEMETRY_ACCESS_KEY_ENVIRONMENT_VARIABLE,
        "production-access-key",
    )

    if configured_path is None:
        monkeypatch.delenv(
            TELEMETRY_PATH_ENVIRONMENT_VARIABLE,
            raising=False,
        )
    else:
        monkeypatch.setenv(
            TELEMETRY_PATH_ENVIRONMENT_VARIABLE,
            configured_path,
        )

    sys.modules.pop(MODULE_NAME, None)

    with pytest.raises(
        RuntimeError,
        match="B52_TELEMETRY_PATH must be configured",
    ):
        importlib.import_module(MODULE_NAME)


@pytest.mark.parametrize("configured_access_key", [None, "", "   "])
def test_production_app_requires_telemetry_access_key(
    tmp_path: Path,
    configured_access_key: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        TELEMETRY_PATH_ENVIRONMENT_VARIABLE,
        str(tmp_path / "telemetry.latest.json"),
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
