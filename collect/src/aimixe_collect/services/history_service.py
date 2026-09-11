"""Collection history (specification §17)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .collection_service import SessionSummary

if TYPE_CHECKING:
    from .app import App


class HistoryService:
    def __init__(self, app: "App"):
        self.app = app

    def list(self, language_id: str | None = None, limit: int = 50) -> list[SessionSummary]:
        return [self.app.collection_service.summary(r["id"]) for r in self.app.sessions.list(language_id, limit)]

    def get(self, session_id: str) -> SessionSummary | None:
        if self.app.sessions.get(session_id) is None:
            return None
        return self.app.collection_service.summary(session_id)

    def events(self, session_id: str):
        return self.app.sessions.events(session_id)
