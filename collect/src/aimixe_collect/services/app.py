"""Application context: wires configuration, database, registry, storage and logging.

Any interface (CLI today, GUI later) creates one ``App`` and uses the services on it.
"""
from __future__ import annotations

from pathlib import Path

from ..config import Config, bootstrap
from ..db.connection import connect
from ..db.repositories import LanguageRepo, ProfileRepo, ResourceRepo, ReviewRepo, SessionRepo
from ..language.local_registry import LocalRegistry
from ..language.registry import Registry, load_registry
from ..language.resolver import LanguageResolver
from ..logging_setup import JsonlLog, open_log
from ..storage.object_store import ObjectStore


class App:
    def __init__(self, root: Path | None = None, registry: Registry | None = None):
        self.config: Config = bootstrap(root)
        self.paths = self.config.paths
        self.conn = connect(self.paths.database)
        self.log: JsonlLog = open_log(self.paths.logs)
        self.registry: Registry = registry or load_registry()
        self.local_registry = LocalRegistry(self.paths.languages)
        self.resolver = LanguageResolver(self.registry, self.local_registry)
        self.store = ObjectStore(self.paths.temp)
        # repositories
        self.languages = LanguageRepo(self.conn)
        self.profiles = ProfileRepo(self.conn)
        self.resources = ResourceRepo(self.conn)
        self.sessions = SessionRepo(self.conn)
        self.reviews = ReviewRepo(self.conn)
        # services (imported lazily to avoid cycles)
        from .agent_service import AgentService
        from .catalogue_service import CatalogueService
        from .collection_service import CollectionService
        from .history_service import HistoryService
        from .import_service import ImportService
        from .language_service import LanguageService
        from .profile_service import ProfileService
        from .review_service import ReviewService
        self.language_service = LanguageService(self)
        self.profile_service = ProfileService(self)
        self.collection_service = CollectionService(self)
        self.import_service = ImportService(self)
        self.history_service = HistoryService(self)
        self.review_service = ReviewService(self)
        self.catalogue_service = CatalogueService(self)
        self.agent_service = AgentService(self)

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> "App":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
