from __future__ import annotations

from secrets import token_urlsafe
from threading import Lock

SESSION_TOKEN_BYTES = 32


class SessionStore:
    def __init__(self) -> None:
        self._session_ids: set[str] = set()
        self._lock = Lock()

    def create(self) -> str:
        while True:
            session_id = token_urlsafe(SESSION_TOKEN_BYTES)

            with self._lock:
                if session_id in self._session_ids:
                    continue

                self._session_ids.add(session_id)
                return session_id

    def contains(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._session_ids

    def revoke(self, session_id: str) -> None:
        with self._lock:
            self._session_ids.discard(session_id)
