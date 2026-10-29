from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import Mapping

from b52_telemetry.persistence import AcceptedTelemetryFileSource
from b52_telemetry.source import TelemetryFileSource

SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}")


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


@dataclass(frozen=True, slots=True)
class ProducerAuthorization:
    enabled: bool
    authorization_generation: int
    credential_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("producer enabled status must be boolean")
        if (
            isinstance(self.authorization_generation, bool)
            or self.authorization_generation < 1
        ):
            raise ValueError("producer authorization generation must be positive")
        if SHA256_HEX_PATTERN.fullmatch(self.credential_sha256) is None:
            raise ValueError("producer credential digest must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class TelemetrySourceRegistration:
    path: Path
    producer: ProducerAuthorization

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise ValueError("telemetry source path must be absolute")


class TelemetrySourceRegistry:
    def __init__(
        self,
        registrations: Mapping[B52InstanceId, TelemetrySourceRegistration],
    ) -> None:
        if not registrations:
            raise ValueError("telemetry source registry must not be empty")

        copied = dict(registrations)
        paths = [registration.path for registration in copied.values()]
        if len(set(paths)) != len(paths):
            raise ValueError("telemetry source paths must be unique")
        parent_directories = [path.parent for path in paths]
        if len(set(parent_directories)) != len(parent_directories):
            raise ValueError("telemetry source directories must be unique")
        credential_digests = [
            registration.producer.credential_sha256 for registration in copied.values()
        ]
        if len(set(credential_digests)) != len(credential_digests):
            raise ValueError("producer credential digests must be unique")

        self._registrations = MappingProxyType(copied)
        self._sources: Mapping[B52InstanceId, TelemetryFileSource] = MappingProxyType(
            {
                instance_id: AcceptedTelemetryFileSource(
                    registration.path,
                    fleet_identity=instance_id.value,
                    authorization_generation=(
                        registration.producer.authorization_generation
                    ),
                )
                for instance_id, registration in copied.items()
            }
        )
        self._acceptance_locks = MappingProxyType(
            {instance_id: Lock() for instance_id in copied}
        )

    def instance_ids(self) -> tuple[B52InstanceId, ...]:
        return tuple(self._registrations)

    def registration(
        self,
        instance_id: B52InstanceId,
    ) -> TelemetrySourceRegistration:
        try:
            return self._registrations[instance_id]
        except KeyError as exc:
            raise UnknownTelemetrySource(
                f"unknown B-52 telemetry source: {instance_id.value}"
            ) from exc

    def resolve(self, instance_id: B52InstanceId) -> TelemetryFileSource:
        try:
            return self._sources[instance_id]
        except KeyError as exc:
            raise UnknownTelemetrySource(
                f"unknown B-52 telemetry source: {instance_id.value}"
            ) from exc

    def acceptance_lock(self, instance_id: B52InstanceId) -> Lock:
        try:
            return self._acceptance_locks[instance_id]
        except KeyError as exc:
            raise UnknownTelemetrySource(
                f"unknown B-52 telemetry source: {instance_id.value}"
            ) from exc

    def producer_credential_digests(self) -> tuple[str, ...]:
        return tuple(
            registration.producer.credential_sha256
            for registration in self._registrations.values()
        )
