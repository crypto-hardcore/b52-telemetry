from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from b52_telemetry.app import create_app
from b52_telemetry.contract import TELEMETRY_SCHEMA_VERSION, TelemetryPayload


def allow_telemetry_access(_: Request) -> None:
    return None


def create_test_app(path: Path) -> FastAPI:
    return create_app(path, telemetry_authorizer=allow_telemetry_access)


def canonical_payload() -> dict[str, object]:
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "generated_at": "2026-09-06T00:15:02+00:00",
        "system": {
            "https": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "websocket": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "authentication": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "stream_freshness": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "evidence_continuity": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "sqlite": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "reconciliation": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
        },
        "market": {
            "symbol": "BTCUSDC",
            "price": "79508.10",
            "observed_at": "2026-09-06T00:15:02+00:00",
        },
        "mission": None,
    }


def write_payload(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )


def test_latest_returns_canonical_payload_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["future_b52_field"] = {
        "owned_by": "B-52",
        "value": "authoritative",
    }
    write_payload(path, payload)

    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 200
    assert response.json() == payload


def test_latest_returns_503_when_source_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source unavailable",
    }


def test_latest_returns_503_when_source_contains_invalid_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    path.write_text('{"schema_version":3', encoding="utf-8")
    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source invalid",
    }


def test_latest_returns_503_for_unsupported_schema(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["schema_version"] = 2
    write_payload(path, payload)
    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source invalid",
    }


def test_latest_does_not_reject_old_canonical_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["generated_at"] = "2025-01-01T00:00:00+00:00"
    write_payload(path, payload)
    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 200
    assert response.json()["generated_at"] == "2025-01-01T00:00:00+00:00"


def test_stream_returns_canonical_payload_as_sse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from b52_telemetry import app as app_module
    from b52_telemetry.source import (
        TelemetryFileSource,
        TelemetrySourceUnavailable,
    )

    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["future_b52_field"] = {
        "owned_by": "B-52",
        "value": "authoritative",
    }
    write_payload(path, payload)

    original_read = TelemetryFileSource.read
    read_count = 0

    def read_once_then_unavailable(
        self: TelemetryFileSource,
    ) -> TelemetryPayload:
        nonlocal read_count
        read_count += 1

        if read_count == 1:
            return original_read(self)

        raise TelemetrySourceUnavailable("source became unavailable")

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(TelemetryFileSource, "read", read_once_then_unavailable)
    monkeypatch.setattr(app_module, "async_sleep", no_sleep)

    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == (
        "data:"
        + json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n\n"
    )


def test_stream_returns_503_when_source_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/stream")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source unavailable",
    }


def test_stream_returns_503_when_source_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    path.write_text('{"schema_version":3', encoding="utf-8")
    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/stream")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source invalid",
    }


def test_stream_closes_if_source_becomes_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from b52_telemetry import app as app_module
    from b52_telemetry.source import (
        TelemetryFileSource,
        TelemetrySourceInvalid,
    )

    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    write_payload(path, payload)

    original_read = TelemetryFileSource.read
    read_count = 0

    def read_once_then_invalid(
        self: TelemetryFileSource,
    ) -> TelemetryPayload:
        nonlocal read_count
        read_count += 1

        if read_count == 1:
            return original_read(self)

        raise TelemetrySourceInvalid("source became invalid")

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(TelemetryFileSource, "read", read_once_then_invalid)
    monkeypatch.setattr(app_module, "async_sleep", no_sleep)

    client = TestClient(create_test_app(path))

    response = client.get("/api/telemetry/stream")

    assert response.status_code == 200
    assert response.text.count("\n\n") == 1


def test_public_snapshot_returns_only_approved_projection(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["system"] = {
        "authentication": {
            "state": "HEALTHY",
            "observed_at": "2026-09-06T00:15:02+00:00",
        },
    }
    payload["mission"] = {
        "lifecycle": {
            "lifecycle_id": "private-lifecycle-id",
            "beginning_wallet_balance": "5000.00",
        },
    }
    payload["future_b52_field"] = {
        "private": "authoritative-but-not-public",
    }
    write_payload(path, payload)

    client = TestClient(create_test_app(path))

    response = client.get("/api/public/snapshot")

    assert response.status_code == 200
    assert response.json() == {
        "generated_at": payload["generated_at"],
        "market": {
            "symbol": "BTCUSDC",
            "price": "79508.10",
        },
    }


def test_public_snapshot_returns_503_when_source_is_unavailable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    client = TestClient(create_test_app(path))

    response = client.get("/api/public/snapshot")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source unavailable",
    }


def test_public_snapshot_returns_503_when_source_is_invalid(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    path.write_text('{"schema_version":3', encoding="utf-8")
    client = TestClient(create_test_app(path))

    response = client.get("/api/public/snapshot")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source invalid",
    }


def test_public_snapshot_does_not_require_telemetry_authorization(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    write_payload(path, payload)

    authorization_calls = 0

    def deny_if_called(_: Request) -> None:
        nonlocal authorization_calls
        authorization_calls += 1
        raise AssertionError("public endpoint invoked telemetry authorizer")

    client = TestClient(
        create_app(
            path,
            telemetry_authorizer=deny_if_called,
        )
    )

    response = client.get("/api/public/snapshot")

    assert response.status_code == 200
    assert authorization_calls == 0


def test_latest_telemetry_denies_access_by_default(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    write_payload(path, canonical_payload())

    client = TestClient(create_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "telemetry access denied",
    }


def test_stream_telemetry_denies_access_by_default(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    write_payload(path, canonical_payload())

    client = TestClient(create_app(path))

    response = client.get("/api/telemetry/stream")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "telemetry access denied",
    }


def test_latest_telemetry_invokes_authorizer_before_returning_payload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    write_payload(path, payload)

    authorization_calls = 0

    def authorize(_: Request) -> None:
        nonlocal authorization_calls
        authorization_calls += 1

    client = TestClient(
        create_app(
            path,
            telemetry_authorizer=authorize,
        )
    )

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 200
    assert response.json() == payload
    assert authorization_calls == 1


def test_stream_telemetry_invokes_authorizer_before_opening_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    write_payload(path, payload)

    authorization_calls = 0

    def authorize(_: Request) -> None:
        nonlocal authorization_calls
        authorization_calls += 1

    async def stop_after_first_frame(_: float) -> None:
        path.unlink()

    monkeypatch.setattr(
        "b52_telemetry.app.async_sleep",
        stop_after_first_frame,
    )

    client = TestClient(
        create_app(
            path,
            telemetry_authorizer=authorize,
        )
    )

    response = client.get("/api/telemetry/stream")

    assert response.status_code == 200
    assert response.text.count("\n\n") == 1
    assert authorization_calls == 1


def create_https_client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="https://testserver")


def test_session_creation_accepts_valid_access_key(tmp_path: Path) -> None:
    from b52_telemetry.authorization import SessionTelemetryAuthorizer
    from b52_telemetry.session import SessionStore

    path = tmp_path / "telemetry.latest.json"
    store = SessionStore()

    client = create_https_client(
        create_app(
            path,
            telemetry_authorizer=SessionTelemetryAuthorizer(store),
            session_store=store,
            telemetry_access_key="expected-access-key",
        )
    )

    response = client.post(
        "/api/session",
        json={"access_key": "expected-access-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert "b52_telemetry_session" in response.cookies


def test_session_creation_rejects_invalid_access_key(tmp_path: Path) -> None:
    from b52_telemetry.session import SessionStore

    path = tmp_path / "telemetry.latest.json"

    client = create_https_client(
        create_app(
            path,
            session_store=SessionStore(),
            telemetry_access_key="expected-access-key",
        )
    )

    response = client.post(
        "/api/session",
        json={"access_key": "wrong-access-key"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "invalid access credential",
    }


def test_session_creation_is_unavailable_without_session_configuration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    client = create_https_client(create_app(path))

    response = client.post(
        "/api/session",
        json={"access_key": "anything"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "session authentication unavailable",
    }


def test_session_status_reports_authenticated_session(tmp_path: Path) -> None:
    from b52_telemetry.session import SessionStore

    path = tmp_path / "telemetry.latest.json"
    store = SessionStore()

    client = create_https_client(
        create_app(
            path,
            session_store=store,
            telemetry_access_key="expected-access-key",
        )
    )

    login_response = client.post(
        "/api/session",
        json={"access_key": "expected-access-key"},
    )

    assert login_response.status_code == 200

    response = client.get("/api/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}


def test_session_status_reports_unauthenticated_without_valid_session(
    tmp_path: Path,
) -> None:
    from b52_telemetry.session import SessionStore

    path = tmp_path / "telemetry.latest.json"

    client = create_https_client(
        create_app(
            path,
            session_store=SessionStore(),
            telemetry_access_key="expected-access-key",
        )
    )

    response = client.get("/api/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}


def test_delete_session_revokes_authenticated_session(tmp_path: Path) -> None:
    from b52_telemetry.session import SessionStore

    path = tmp_path / "telemetry.latest.json"
    store = SessionStore()

    client = create_https_client(
        create_app(
            path,
            session_store=store,
            telemetry_access_key="expected-access-key",
        )
    )

    login_response = client.post(
        "/api/session",
        json={"access_key": "expected-access-key"},
    )
    session_id = login_response.cookies["b52_telemetry_session"]

    response = client.delete("/api/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    assert not store.contains(session_id)


def test_authenticated_cookie_grants_latest_telemetry(tmp_path: Path) -> None:
    from b52_telemetry.authorization import SessionTelemetryAuthorizer
    from b52_telemetry.session import SessionStore

    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    write_payload(path, payload)

    store = SessionStore()

    client = create_https_client(
        create_app(
            path,
            telemetry_authorizer=SessionTelemetryAuthorizer(store),
            session_store=store,
            telemetry_access_key="expected-access-key",
        )
    )

    login_response = client.post(
        "/api/session",
        json={"access_key": "expected-access-key"},
    )

    assert "b52_telemetry_session" in login_response.cookies

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 200
    assert response.json() == payload


def test_missing_session_cookie_is_rejected_by_session_authorizer(
    tmp_path: Path,
) -> None:
    from b52_telemetry.authorization import SessionTelemetryAuthorizer
    from b52_telemetry.session import SessionStore

    path = tmp_path / "telemetry.latest.json"
    write_payload(path, canonical_payload())

    store = SessionStore()

    client = create_https_client(
        create_app(
            path,
            telemetry_authorizer=SessionTelemetryAuthorizer(store),
            session_store=store,
            telemetry_access_key="expected-access-key",
        )
    )

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "telemetry authentication required",
    }


def test_authenticated_cookie_grants_telemetry_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from b52_telemetry.authorization import SessionTelemetryAuthorizer
    from b52_telemetry.session import SessionStore

    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    write_payload(path, payload)

    store = SessionStore()

    async def stop_after_first_frame(_: float) -> None:
        path.unlink()

    monkeypatch.setattr(
        "b52_telemetry.app.async_sleep",
        stop_after_first_frame,
    )

    client = create_https_client(
        create_app(
            path,
            telemetry_authorizer=SessionTelemetryAuthorizer(store),
            session_store=store,
            telemetry_access_key="expected-access-key",
        )
    )

    login_response = client.post(
        "/api/session",
        json={"access_key": "expected-access-key"},
    )

    assert login_response.status_code == 200
    assert "b52_telemetry_session" in login_response.cookies

    response = client.get("/api/telemetry/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("\n\n") == 1
