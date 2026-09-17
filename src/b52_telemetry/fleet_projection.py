from __future__ import annotations

from typing import Literal, TypeAlias, TypedDict

from b52_telemetry.contract import TelemetryPayload
from b52_telemetry.source import (
    TelemetrySourceInvalid,
    TelemetrySourceUnavailable,
)
from b52_telemetry.source_registry import B52InstanceId, TelemetrySourceRegistry

FleetSourceState: TypeAlias = Literal["AVAILABLE", "UNAVAILABLE", "INVALID"]


class AvailableFleetMember(TypedDict):
    instance_id: str
    source_state: Literal["AVAILABLE"]
    telemetry: TelemetryPayload


class UnavailableFleetMember(TypedDict):
    instance_id: str
    source_state: Literal["UNAVAILABLE"]
    telemetry: None


class InvalidFleetMember(TypedDict):
    instance_id: str
    source_state: Literal["INVALID"]
    telemetry: None


FleetMember: TypeAlias = (
    AvailableFleetMember | UnavailableFleetMember | InvalidFleetMember
)


class FleetSnapshot(TypedDict):
    instances: list[FleetMember]


def _project_member(
    registry: TelemetrySourceRegistry,
    instance_id: B52InstanceId,
) -> FleetMember:
    source = registry.resolve(instance_id)

    try:
        telemetry = source.read()
    except TelemetrySourceUnavailable:
        return {
            "instance_id": instance_id.value,
            "source_state": "UNAVAILABLE",
            "telemetry": None,
        }
    except TelemetrySourceInvalid:
        return {
            "instance_id": instance_id.value,
            "source_state": "INVALID",
            "telemetry": None,
        }

    return {
        "instance_id": instance_id.value,
        "source_state": "AVAILABLE",
        "telemetry": telemetry,
    }


def project_fleet(
    registry: TelemetrySourceRegistry,
) -> FleetSnapshot:
    return {
        "instances": [
            _project_member(registry, instance_id)
            for instance_id in registry.instance_ids()
        ]
    }
