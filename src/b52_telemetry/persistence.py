from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from secrets import compare_digest
from typing import Literal, cast
from uuid import uuid4

from b52_telemetry.contract import (
    TelemetryContractError,
    TelemetryPayload,
    validate_telemetry_payload,
)
from b52_telemetry.source import (
    TelemetryFileSource,
    TelemetrySourceInvalid,
    TelemetrySourceUnavailable,
)

SNAPSHOT_XATTR = "user.b52.transport.v1"
CONTROL_XATTR = "user.b52.transport-control.v1"
METADATA_VERSION = 1


class TransportPersistenceError(RuntimeError):
    """Base error for receiver transport persistence failures."""


class TransportStateInvalid(TransportPersistenceError):
    """Ordering metadata is absent, corrupt, or contradictory."""


class TransportCommitFailed(TransportPersistenceError):
    """A durable accepted-snapshot commit could not complete."""


class TransportOrderingRejected(TransportPersistenceError):
    """A sequence is older than or conflicts with the accepted sequence."""


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    version: int
    fleet_identity: str
    authorization_generation: int
    sequence: int
    payload_sha256: str
    accepted_at: str


@dataclass(frozen=True, slots=True)
class ControlMetadata:
    version: int
    fleet_identity: str
    ordering_epoch_generation: int
    current_authorization_generation: int
    snapshot_required: bool


@dataclass(frozen=True, slots=True)
class AcceptedSnapshot:
    body: bytes
    payload: TelemetryPayload
    metadata: SnapshotMetadata


TransportResult = Literal["accepted", "duplicate"]


def _encode_metadata(value: SnapshotMetadata | ControlMetadata) -> bytes:
    return json.dumps(
        asdict(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _decode_object(raw: bytes, *, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportStateInvalid(f"{label} is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise TransportStateInvalid(f"{label} must be a JSON object")
    return cast(dict[str, object], decoded)


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TransportStateInvalid(f"{field} must be a positive integer")
    return value


def _decode_control(raw: bytes) -> ControlMetadata:
    value = _decode_object(raw, label="transport control metadata")
    required = {
        "version",
        "fleet_identity",
        "ordering_epoch_generation",
        "current_authorization_generation",
        "snapshot_required",
    }
    if set(value) != required:
        raise TransportStateInvalid("transport control metadata fields are invalid")
    if value["version"] != METADATA_VERSION:
        raise TransportStateInvalid("transport control metadata version is invalid")
    identity = value["fleet_identity"]
    snapshot_required = value["snapshot_required"]
    if not isinstance(identity, str) or not identity:
        raise TransportStateInvalid("transport control identity is invalid")
    if not isinstance(snapshot_required, bool):
        raise TransportStateInvalid("snapshot_required must be boolean")
    return ControlMetadata(
        version=METADATA_VERSION,
        fleet_identity=identity,
        ordering_epoch_generation=_positive_integer(
            value["ordering_epoch_generation"],
            field="ordering_epoch_generation",
        ),
        current_authorization_generation=_positive_integer(
            value["current_authorization_generation"],
            field="current_authorization_generation",
        ),
        snapshot_required=snapshot_required,
    )


def _decode_snapshot(raw: bytes) -> SnapshotMetadata:
    value = _decode_object(raw, label="accepted snapshot metadata")
    required = {
        "version",
        "fleet_identity",
        "authorization_generation",
        "sequence",
        "payload_sha256",
        "accepted_at",
    }
    if set(value) != required:
        raise TransportStateInvalid("accepted snapshot metadata fields are invalid")
    if value["version"] != METADATA_VERSION:
        raise TransportStateInvalid("accepted snapshot metadata version is invalid")
    identity = value["fleet_identity"]
    digest = value["payload_sha256"]
    accepted_at = value["accepted_at"]
    if not isinstance(identity, str) or not identity:
        raise TransportStateInvalid("accepted snapshot identity is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise TransportStateInvalid("accepted snapshot digest is invalid")
    if not isinstance(accepted_at, str) or not accepted_at:
        raise TransportStateInvalid("accepted snapshot timestamp is invalid")
    return SnapshotMetadata(
        version=METADATA_VERSION,
        fleet_identity=identity,
        authorization_generation=_positive_integer(
            value["authorization_generation"], field="authorization_generation"
        ),
        sequence=_positive_integer(value["sequence"], field="sequence"),
        payload_sha256=digest,
        accepted_at=accepted_at,
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_control_metadata(path: Path) -> ControlMetadata:
    try:
        raw = os.getxattr(path.parent, CONTROL_XATTR)
    except OSError as exc:
        raise TransportStateInvalid(
            "transport control metadata is unavailable"
        ) from exc
    return _decode_control(raw)


def write_control_metadata(path: Path, metadata: ControlMetadata) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.setxattr(path.parent, CONTROL_XATTR, _encode_metadata(metadata))
        _fsync_directory(path.parent)
    except OSError as exc:
        raise TransportCommitFailed(
            "could not persist transport control metadata"
        ) from exc


def _validate_control(
    control: ControlMetadata,
    *,
    fleet_identity: str,
    authorization_generation: int,
) -> None:
    if control.fleet_identity != fleet_identity:
        raise TransportStateInvalid(
            "transport control identity does not match registry"
        )
    if control.current_authorization_generation != authorization_generation:
        raise TransportStateInvalid(
            "transport control generation does not match registry"
        )
    if control.ordering_epoch_generation > authorization_generation:
        raise TransportStateInvalid("transport ordering epoch is in the future")


def read_accepted_snapshot(
    path: Path,
    *,
    fleet_identity: str,
    authorization_generation: int,
) -> AcceptedSnapshot | None:
    control = read_control_metadata(path)
    _validate_control(
        control,
        fleet_identity=fleet_identity,
        authorization_generation=authorization_generation,
    )

    if not control.snapshot_required:
        if path.exists():
            raise TransportStateInvalid(
                "canonical snapshot exists while baseline expects no snapshot"
            )
        return None

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as exc:
        raise TransportStateInvalid(
            "required canonical snapshot is unavailable"
        ) from exc

    try:
        parts: list[bytes] = []
        while part := os.read(descriptor, 65536):
            parts.append(part)
        try:
            raw_metadata = os.getxattr(descriptor, SNAPSHOT_XATTR)
        except OSError as exc:
            raise TransportStateInvalid(
                "accepted snapshot metadata is unavailable"
            ) from exc
    finally:
        os.close(descriptor)

    body = b"".join(parts)
    metadata = _decode_snapshot(raw_metadata)
    if metadata.fleet_identity != fleet_identity:
        raise TransportStateInvalid(
            "accepted snapshot identity does not match registry"
        )
    if not (
        control.ordering_epoch_generation
        <= metadata.authorization_generation
        <= authorization_generation
    ):
        raise TransportStateInvalid("accepted snapshot generation is inconsistent")
    if not compare_digest(sha256(body).hexdigest(), metadata.payload_sha256):
        raise TransportStateInvalid("accepted snapshot digest does not match its body")

    try:
        decoded = json.loads(body.decode("utf-8"))
        payload = validate_telemetry_payload(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TelemetryContractError) as exc:
        raise TransportStateInvalid("accepted canonical snapshot is invalid") from exc
    return AcceptedSnapshot(body=body, payload=payload, metadata=metadata)


def accept_snapshot(
    path: Path,
    *,
    fleet_identity: str,
    authorization_generation: int,
    sequence: int,
    body: bytes,
) -> TransportResult:
    current = read_accepted_snapshot(
        path,
        fleet_identity=fleet_identity,
        authorization_generation=authorization_generation,
    )
    body_digest = sha256(body).hexdigest()
    if current is not None:
        high_water_mark = current.metadata.sequence
        if sequence < high_water_mark:
            raise TransportOrderingRejected("transport sequence is older than accepted")
        if sequence == high_water_mark:
            if compare_digest(body_digest, current.metadata.payload_sha256):
                return "duplicate"
            raise TransportOrderingRejected(
                "transport sequence conflicts with accepted payload"
            )
    else:
        control = read_control_metadata(path)
        write_control_metadata(path, replace(control, snapshot_required=True))

    metadata = SnapshotMetadata(
        version=METADATA_VERSION,
        fleet_identity=fleet_identity,
        authorization_generation=authorization_generation,
        sequence=sequence,
        payload_sha256=body_digest,
        accepted_at=datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
    )
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = -1
    try:
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        remaining = memoryview(body)
        while remaining:
            written = os.write(descriptor, remaining)
            remaining = remaining[written:]
        os.setxattr(descriptor, SNAPSHOT_XATTR, _encode_metadata(metadata))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise TransportCommitFailed(
            "could not commit accepted canonical snapshot"
        ) from exc
    return "accepted"


def establish_baseline(
    path: Path,
    *,
    fleet_identity: str,
    authorization_generation: int,
) -> None:
    if path.exists():
        raise TransportStateInvalid("canonical snapshot must be absent at baseline")
    write_control_metadata(
        path,
        ControlMetadata(
            version=METADATA_VERSION,
            fleet_identity=fleet_identity,
            ordering_epoch_generation=authorization_generation,
            current_authorization_generation=authorization_generation,
            snapshot_required=False,
        ),
    )


def update_current_authorization_generation(
    path: Path,
    *,
    fleet_identity: str,
    previous_generation: int,
    authorization_generation: int,
) -> None:
    if authorization_generation != previous_generation + 1:
        raise TransportStateInvalid("authorization generation must increment by one")
    control = read_control_metadata(path)
    _validate_control(
        control,
        fleet_identity=fleet_identity,
        authorization_generation=previous_generation,
    )
    write_control_metadata(
        path,
        replace(control, current_authorization_generation=authorization_generation),
    )


def reset_ordering_baseline(
    path: Path,
    *,
    fleet_identity: str,
    previous_generation: int,
    authorization_generation: int,
) -> None:
    if authorization_generation != previous_generation + 1:
        raise TransportStateInvalid("authorization generation must increment by one")
    control = read_control_metadata(path)
    _validate_control(
        control,
        fleet_identity=fleet_identity,
        authorization_generation=previous_generation,
    )
    try:
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise TransportCommitFailed(
            "could not remove accepted canonical snapshot"
        ) from exc
    establish_baseline(
        path,
        fleet_identity=fleet_identity,
        authorization_generation=authorization_generation,
    )


class AcceptedTelemetryFileSource(TelemetryFileSource):
    def __init__(
        self,
        path: Path,
        *,
        fleet_identity: str,
        authorization_generation: int,
    ) -> None:
        super().__init__(path)
        self._accepted_path = path
        self._fleet_identity = fleet_identity
        self._authorization_generation = authorization_generation

    def read(self) -> TelemetryPayload:
        try:
            accepted = read_accepted_snapshot(
                self._accepted_path,
                fleet_identity=self._fleet_identity,
                authorization_generation=self._authorization_generation,
            )
        except TransportStateInvalid as exc:
            raise TelemetrySourceInvalid("accepted telemetry state is invalid") from exc
        if accepted is None:
            raise TelemetrySourceUnavailable(
                "telemetry source has no accepted snapshot"
            )
        return accepted.payload
