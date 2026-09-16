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


def canonical_payload(generated_at: str) -> dict[str, object]:
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "generated_at": generated_at,
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

    registry = TelemetrySourceRegistry(
        {
            first_id: tmp_path / "first.json",
            second_id: tmp_path / "second.json",
        }
    )

    assert registry.instance_ids() == (first_id, second_id)


def test_registry_resolves_independent_canonical_sources(tmp_path: Path) -> None:
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    first_payload = canonical_payload("2026-09-16T03:00:00+00:00")
    second_payload = canonical_payload("2026-09-16T03:00:01+00:00")

    write_payload(first_path, first_payload)
    write_payload(second_path, second_payload)

    first_id = B52InstanceId("B52-001")
    second_id = B52InstanceId("B52-002")

    registry = TelemetrySourceRegistry(
        {
            first_id: first_path,
            second_id: second_path,
        }
    )

    assert registry.resolve(first_id).read() == first_payload
    assert registry.resolve(second_id).read() == second_payload


def test_registry_rejects_unknown_instance_identity(tmp_path: Path) -> None:
    registry = TelemetrySourceRegistry(
        {
            B52InstanceId("B52-001"): tmp_path / "first.json",
        }
    )

    with pytest.raises(
        UnknownTelemetrySource,
        match="unknown B-52 telemetry source: B52-999",
    ):
        registry.resolve(B52InstanceId("B52-999"))
