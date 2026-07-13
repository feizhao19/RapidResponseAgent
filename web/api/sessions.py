"""HTTP handlers for server-side chat sessions."""

from __future__ import annotations

from typing import Any

from geoagent.runtime.memory import SessionStore

_store = SessionStore()


def create_session(*, title: str = "New chat", session_id: str | None = None) -> dict[str, Any]:
    record = _store.create_session(title=title, session_id=session_id)
    return record.to_dict()


def get_session_payload(session_id: str) -> dict[str, Any]:
    record = _store.get_session(session_id)
    messages = _store.list_messages(session_id)
    return {
        **record.to_dict(),
        "messages": messages,
    }


def list_episodes(session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    return _store.list_episodes(session_id, limit=limit)
