from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from fastapi import HTTPException, Request

TelemetryAuthorizer: TypeAlias = Callable[[Request], None]


def deny_telemetry_access(_: Request) -> None:
    raise HTTPException(
        status_code=403,
        detail="telemetry access denied",
    )
