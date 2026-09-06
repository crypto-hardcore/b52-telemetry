from __future__ import annotations

import json
from pathlib import Path

from b52_telemetry.contract import (
    TelemetryContractError,
    TelemetryPayload,
    validate_telemetry_payload,
)


class TelemetrySourceError(RuntimeError):
    """Base error for failures at the read-only telemetry source boundary."""


class TelemetrySourceUnavailable(TelemetrySourceError):
    """Raised when the canonical telemetry snapshot cannot be read."""


class TelemetrySourceInvalid(TelemetrySourceError):
    """Raised when the telemetry source does not contain a valid snapshot."""


class TelemetryFileSource:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> TelemetryPayload:
        try:
            payload_text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TelemetrySourceUnavailable(
                f"telemetry source unavailable: {self._path}"
            ) from exc

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise TelemetrySourceInvalid(
                "telemetry source contains invalid JSON"
            ) from exc

        try:
            return validate_telemetry_payload(payload)
        except TelemetryContractError as exc:
            raise TelemetrySourceInvalid(
                "telemetry source contains an invalid canonical snapshot"
            ) from exc
