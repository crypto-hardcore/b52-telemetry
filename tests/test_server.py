from __future__ import annotations

from typing import Any

from b52_telemetry import server


def test_production_server_binds_only_to_loopback(monkeypatch: Any) -> None:
    invocation: dict[str, Any] = {}

    def fake_run(app: str, **kwargs: Any) -> None:
        invocation["app"] = app
        invocation.update(kwargs)

    monkeypatch.setattr(server.uvicorn, "run", fake_run)

    server.main()

    assert invocation == {
        "app": "b52_telemetry.main:app",
        "host": "127.0.0.1",
        "port": 8000,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1",
    }
