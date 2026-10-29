from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

from b52_telemetry.persistence import (
    CONTROL_XATTR,
    METADATA_VERSION,
    ControlMetadata,
    accept_snapshot,
    establish_baseline,
    read_accepted_snapshot,
    write_control_metadata,
)
from b52_telemetry.source_registry import (
    B52InstanceId,
    ProducerAuthorization,
    TelemetrySourceRegistration,
    TelemetrySourceRegistry,
)

PRODUCER_TOKEN = "b52r_v1_" + "A" * 43
PRODUCER_DIGEST = sha256(PRODUCER_TOKEN.encode("utf-8")).hexdigest()


def registration(
    path: Path,
    *,
    enabled: bool = True,
    generation: int = 1,
) -> TelemetrySourceRegistration:
    return TelemetrySourceRegistration(
        path=path,
        producer=ProducerAuthorization(
            enabled=enabled,
            authorization_generation=generation,
            credential_sha256=PRODUCER_DIGEST,
        ),
    )


def registry(
    sources: dict[B52InstanceId, Path],
    *,
    enabled: bool = True,
    generation: int = 1,
) -> TelemetrySourceRegistry:
    for identity, path in sources.items():
        try:
            os.getxattr(path.parent, CONTROL_XATTR)
        except OSError:
            if path.exists():
                write_control_metadata(
                    path,
                    ControlMetadata(
                        version=METADATA_VERSION,
                        fleet_identity=identity.value,
                        ordering_epoch_generation=generation,
                        current_authorization_generation=generation,
                        snapshot_required=True,
                    ),
                )
            else:
                establish_baseline(
                    path,
                    fleet_identity=identity.value,
                    authorization_generation=generation,
                )
    return TelemetrySourceRegistry(
        {
            identity: TelemetrySourceRegistration(
                path=path,
                producer=ProducerAuthorization(
                    enabled=enabled,
                    authorization_generation=generation,
                    credential_sha256=sha256(
                        f"test-producer-{identity.value}".encode("utf-8")
                    ).hexdigest(),
                ),
            )
            for identity, path in sources.items()
        }
    )


def write_accepted(
    path: Path,
    payload: dict[str, object],
    *,
    identity: str = "B52-001",
    generation: int = 1,
    sequence: int = 1,
) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if path.exists():
        accepted = read_accepted_snapshot(
            path,
            fleet_identity=identity,
            authorization_generation=generation,
        )
        assert accepted is not None
        sequence = max(sequence, accepted.metadata.sequence + 1)
    else:
        establish_baseline(
            path,
            fleet_identity=identity,
            authorization_generation=generation,
        )
    accept_snapshot(
        path,
        fleet_identity=identity,
        authorization_generation=generation,
        sequence=sequence,
        body=body,
    )
    return body
