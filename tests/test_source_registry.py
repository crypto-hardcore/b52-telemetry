from __future__ import annotations

import json
from pathlib import Path

import pytest

from b52_telemetry.contract import TELEMETRY_SCHEMA_VERSION
from b52_telemetry.source_registry import (
    B52InstanceId,
    TelemetrySourceRegistry,
    UnknownTelemetrySource,
)
from tests.transport_support import registry, write_accepted


def canonical_payload(generated_at: str) -> dict[str, object]:
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "instance": "deadbeef00112233deadbeef00112233",
        "environment": "testnet",
        "position_sizing_leverage": 3,
        "generated_at": generated_at,
        "phase": "AWAITING_OPERATOR",
        "system": {},
        "market": None,
        "mission": None,
    }


def write_payload(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "\t",
        "\n",
    ],
)
def test_instance_id_rejects_empty_identity(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="B-52 instance id must be a non-empty string",
    ):
        B52InstanceId(value)


@pytest.mark.parametrize(
    "value",
    [
        " B52-001",
        "B52-001 ",
        "\tB52-001",
        "B52-001\n",
    ],
)
def test_instance_id_rejects_surrounding_whitespace(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="B-52 instance id must not contain leading or trailing whitespace",
    ):
        B52InstanceId(value)


def test_instance_id_preserves_explicit_identity() -> None:
    instance_id = B52InstanceId("B52-001")

    assert instance_id.value == "B52-001"


def test_registry_requires_at_least_one_source() -> None:
    with pytest.raises(
        ValueError,
        match="telemetry source registry must not be empty",
    ):
        TelemetrySourceRegistry({})


def test_registry_exposes_registered_instance_ids(tmp_path: Path) -> None:
    first_id = B52InstanceId("B52-001")
    second_id = B52InstanceId("B52-002")

    source_registry = registry(
        {
            first_id: tmp_path / "first" / "telemetry.latest.json",
            second_id: tmp_path / "second" / "telemetry.latest.json",
        }
    )

    assert source_registry.instance_ids() == (first_id, second_id)


def test_registry_resolves_independent_canonical_sources(tmp_path: Path) -> None:
    first_path = tmp_path / "first" / "telemetry.latest.json"
    second_path = tmp_path / "second" / "telemetry.latest.json"

    first_payload = canonical_payload("2026-09-16T03:00:00+00:00")
    second_payload = canonical_payload("2026-09-16T03:00:01+00:00")

    first_id = B52InstanceId("B52-001")
    second_id = B52InstanceId("B52-002")
    write_accepted(first_path, first_payload, identity=first_id.value)
    write_accepted(second_path, second_payload, identity=second_id.value)

    source_registry = registry(
        {
            first_id: first_path,
            second_id: second_path,
        }
    )

    assert source_registry.resolve(first_id).read() == first_payload
    assert source_registry.resolve(second_id).read() == second_payload


def test_registry_rejects_unknown_instance_identity(tmp_path: Path) -> None:
    source_registry = registry(
        {
            B52InstanceId("B52-001"): tmp_path / "first" / "telemetry.latest.json",
        }
    )

    with pytest.raises(
        UnknownTelemetrySource,
        match="unknown B-52 telemetry source: B52-999",
    ):
        source_registry.resolve(B52InstanceId("B52-999"))


def test_registry_requires_one_directory_per_engine(tmp_path: Path) -> None:
    from tests.transport_support import registration

    with pytest.raises(ValueError, match="directories must be unique"):
        TelemetrySourceRegistry(
            {
                B52InstanceId("B52-001"): registration(tmp_path / "first.json"),
                B52InstanceId("B52-002"): registration(tmp_path / "second.json"),
            }
        )


def test_registry_requires_independent_producer_credentials(tmp_path: Path) -> None:
    from tests.transport_support import registration

    with pytest.raises(ValueError, match="credential digests must be unique"):
        TelemetrySourceRegistry(
            {
                B52InstanceId("B52-001"): registration(
                    tmp_path / "first" / "telemetry.latest.json"
                ),
                B52InstanceId("B52-002"): registration(
                    tmp_path / "second" / "telemetry.latest.json"
                ),
            }
        )
