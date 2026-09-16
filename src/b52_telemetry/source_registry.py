from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from b52_telemetry.source import TelemetryFileSource


class TelemetrySourceRegistryError(ValueError):
    """Base error for invalid telemetry source registry operations."""


class UnknownTelemetrySource(TelemetrySourceRegistryError):
    """Raised when no telemetry source is registered for a B-52 instance."""


@dataclass(frozen=True, slots=True)
class B52InstanceId:
    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("B-52 instance id must be a non-empty string")

        if self.value != self.value.strip():
            raise ValueError(
                "B-52 instance id must not contain leading or trailing whitespace"
            )


class TelemetrySourceRegistry:
    def __init__(
        self,
        source_paths: Mapping[B52InstanceId, Path],
    ) -> None:
        if not source_paths:
            raise ValueError("telemetry source registry must not be empty")

        self._sources: Mapping[B52InstanceId, TelemetryFileSource] = MappingProxyType(
            {
                instance_id: TelemetryFileSource(path)
                for instance_id, path in source_paths.items()
            }
        )

    def instance_ids(self) -> tuple[B52InstanceId, ...]:
        return tuple(self._sources)

    def resolve(self, instance_id: B52InstanceId) -> TelemetryFileSource:
        try:
            return self._sources[instance_id]
        except KeyError as exc:
            raise UnknownTelemetrySource(
                f"unknown B-52 telemetry source: {instance_id.value}"
            ) from exc
