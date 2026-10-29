from __future__ import annotations

from typing import Final, TypeAlias, cast

TELEMETRY_SCHEMA_VERSION: Final = 10

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
TelemetryPayload: TypeAlias = dict[str, JsonValue]


class TelemetryContractError(ValueError):
    """Raised when a payload is not a supported canonical B-52 telemetry snapshot."""


def validate_telemetry_payload(payload: object) -> TelemetryPayload:
    """Validate the external boundary of a canonical B-52 telemetry snapshot.

    B-52 owns the meaning of all telemetry fields. This companion validates only
    the versioned serialized envelope required to consume that telemetry safely.
    It does not reconstruct, reinterpret, or derive trading state.
    """
    if not isinstance(payload, dict):
        raise TelemetryContractError("telemetry payload must be a JSON object")

    schema_version = payload.get("schema_version")
    if schema_version != TELEMETRY_SCHEMA_VERSION:
        raise TelemetryContractError(
            "unsupported telemetry schema version: "
            f"{schema_version!r}; expected {TELEMETRY_SCHEMA_VERSION}"
        )

    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise TelemetryContractError("generated_at must be a non-empty string")

    instance = payload.get("instance")
    if not isinstance(instance, str) or not instance:
        raise TelemetryContractError("instance must be a non-empty string")

    environment = payload.get("environment")
    if not isinstance(environment, str) or not environment:
        raise TelemetryContractError("environment must be a non-empty string")

    position_sizing_leverage = payload.get("position_sizing_leverage")
    if (
        isinstance(position_sizing_leverage, bool)
        or not isinstance(position_sizing_leverage, int)
        or position_sizing_leverage < 1
    ):
        raise TelemetryContractError(
            "position_sizing_leverage must be a positive integer"
        )

    phase = payload.get("phase")
    if not isinstance(phase, str) or not phase:
        raise TelemetryContractError("phase must be a non-empty string")

    system = payload.get("system")
    if not isinstance(system, dict):
        raise TelemetryContractError("system must be a JSON object")

    market = payload.get("market")
    if market is not None and not isinstance(market, dict):
        raise TelemetryContractError("market must be a JSON object or null")

    mission = payload.get("mission")
    if mission is not None and not isinstance(mission, dict):
        raise TelemetryContractError("mission must be a JSON object or null")

    return cast(TelemetryPayload, payload)
