"""Direct import of a file or folder (specification §9)."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..discovery.candidate import CandidateResource, PipelineOutcome
from ..profile.model import Profile
from ..storage.object_store import STORAGE_MODES
from .collection_service import RunResult

if TYPE_CHECKING:
    from .app import App


class ImportService:
    def __init__(self, app: "App"):
        self.app = app

    def candidates(self, profile: Profile, target: Path, mode: str) -> list[CandidateResource]:
        target = target.expanduser()
        if not target.exists():
            raise FileNotFoundError(str(target))
        if mode not in STORAGE_MODES:
            raise ValueError(f"import mode must be one of {STORAGE_MODES}")
        files: list[Path] = []
        if target.is_file():
            files.append(target)
        else:
            excl = {e.lower() for e in self.app.config.get("scan", "exclude_dirs", [])}
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if d.lower() not in excl]
                files.extend(Path(dirpath) / f for f in sorted(filenames))
        return [CandidateResource(language_id=profile.id, method="import", local_path=f,
                                  original_path=str(f), import_method=mode, user_asserted=True,
                                  detection_method="manual_import")
                for f in files]

    def run(self, profile: Profile, target: Path, mode: str | None = None,
            on_outcome: Callable[[PipelineOutcome], None] | None = None,
            on_progress: Callable[[int, int], None] | None = None) -> RunResult:
        mode = mode or self.app.config.storage_mode
        cands = self.candidates(profile, target, mode)
        col = self.app.collection_service
        sid = col.start_session(profile, "Import", {"target": str(target), "mode": mode, "files": len(cands)})
        result = RunResult(session_id=sid)
        try:
            for i, out in enumerate(col.iter_candidates(profile, sid, iter(cands)), 1):
                result.outcomes.append(out)
                if on_progress:
                    on_progress(i, len(cands))
                if on_outcome:
                    on_outcome(out)
            status = "finished"
        except KeyboardInterrupt:
            status = "interrupted"
        col.finish_session(sid, status)
        return result
