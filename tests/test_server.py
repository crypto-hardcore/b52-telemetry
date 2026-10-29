from __future__ import annotations

from typing import Any

import uvicorn

from b52_telemetry import server


def test_production_server_binds_to_loopback_with_exactly_one_worker(
    monkeypatch: Any,
) -> None:
    invocation: dict[str, Any] = {}

    def fake_run(app: str, **kwargs: Any) -> None:
        invocation["app"] = app
        invocation.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("WEB_CONCURRENCY", "8")

    server.main()

    assert invocation == {
        "app": "b52_telemetry.main:app",
        "host": "127.0.0.1",
        "port": 8000,
        "workers": 1,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1",
    }
