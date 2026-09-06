from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

ENVIRONMENT_VARIABLE = "B52_TELEMETRY_PATH"
MODULE_NAME = "b52_telemetry.main"


def import_main() -> object:
    sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


def test_production_app_uses_configured_telemetry_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry_path = tmp_path / "telemetry.latest.json"
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, str(telemetry_path))

    main = import_main()

    assert isinstance(main.app, FastAPI)
    assert main.telemetry_path_from_environment() == telemetry_path


@pytest.mark.parametrize("configured_path", [None, "", "   "])
def test_production_app_requires_telemetry_path(
    configured_path: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if configured_path is None:
        monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(ENVIRONMENT_VARIABLE, configured_path)

    sys.modules.pop(MODULE_NAME, None)

    with pytest.raises(
        RuntimeError,
        match="B52_TELEMETRY_PATH must be configured",
    ):
        importlib.import_module(MODULE_NAME)
