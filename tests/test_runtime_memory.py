"""Tests for server-side session memory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from geoagent.runtime.memory import SessionStore
from geoagent.tools.chat_context import ChatTurn


@pytest.fixture()
def session_store(tmp_path: Path) -> SessionStore:
    return SessionStore(root=tmp_path / "sessions")


def test_create_and_append_messages(session_store: SessionStore) -> None:
    record = session_store.create_session(title="Test session")
    session_store.append_message(record.session_id, role="user", content="Hello")
    session_store.append_message(record.session_id, role="assistant", content="Hi there")

    messages = session_store.list_messages(record.session_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["content"] == "Hi there"


def test_load_history_for_llm(session_store: SessionStore) -> None:
    record = session_store.create_session()
    session_store.append_message(record.session_id, role="user", content="Q1")
    session_store.append_message(record.session_id, role="assistant", content="A1")

    history = session_store.load_history_for_llm(record.session_id)
    assert history == [
        ChatTurn(role="user", content="Q1"),
        ChatTurn(role="assistant", content="A1"),
    ]


def test_append_episode(session_store: SessionStore) -> None:
    record = session_store.create_session()
    session_store.append_episode(
        record.session_id,
        {"episode_id": "ep-1", "tools_called": ["query_historical"]},
    )
    episodes = session_store.list_episodes(record.session_id)
    assert len(episodes) == 1
    assert episodes[0]["tools_called"] == ["query_historical"]


def test_get_or_create_with_client_id(session_store: SessionStore) -> None:
    record = session_store.get_or_create_session("client-uuid-123", title="Synced")
    assert record.session_id == "client-uuid-123"
    again = session_store.get_or_create_session("client-uuid-123")
    assert again.session_id == "client-uuid-123"


def test_build_artifact_context_missing_aoi(session_store: SessionStore) -> None:
    context = session_store.build_artifact_context("missing_aoi")
    assert "missing" in context
