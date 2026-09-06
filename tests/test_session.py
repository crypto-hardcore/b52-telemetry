from __future__ import annotations

from b52_telemetry.session import SessionStore


def test_create_returns_recognized_session() -> None:
    store = SessionStore()

    session_id = store.create()

    assert session_id
    assert store.contains(session_id)


def test_create_returns_distinct_sessions() -> None:
    store = SessionStore()

    first_session_id = store.create()
    second_session_id = store.create()

    assert first_session_id != second_session_id
    assert store.contains(first_session_id)
    assert store.contains(second_session_id)


def test_unknown_session_is_not_recognized() -> None:
    store = SessionStore()

    assert not store.contains("unknown-session")


def test_revoke_removes_existing_session() -> None:
    store = SessionStore()
    session_id = store.create()

    store.revoke(session_id)

    assert not store.contains(session_id)


def test_revoke_unknown_session_is_idempotent() -> None:
    store = SessionStore()

    store.revoke("unknown-session")

    assert not store.contains("unknown-session")


def test_sessions_are_process_store_local() -> None:
    first_store = SessionStore()
    second_store = SessionStore()

    session_id = first_store.create()

    assert first_store.contains(session_id)
    assert not second_store.contains(session_id)
