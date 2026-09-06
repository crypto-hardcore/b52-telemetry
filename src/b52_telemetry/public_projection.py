from __future__ import annotations

from typing import TypeAlias

from b52_telemetry.contract import JsonValue, TelemetryPayload

PublicTelemetryPayload: TypeAlias = dict[str, JsonValue]


def project_public_telemetry(
    telemetry: TelemetryPayload,
) -> PublicTelemetryPayload:
    projection: PublicTelemetryPayload = {
        "generated_at": telemetry["generated_at"],
    }

    market = telemetry.get("market")
    if isinstance(market, dict):
        projection["market"] = {
            "symbol": market.get("symbol"),
            "price": market.get("price"),
        }
    else:
        projection["market"] = None

    return projection
