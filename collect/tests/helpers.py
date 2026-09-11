import shutil
import tempfile
from pathlib import Path

from aimixe_collect.language.registry import load_registry
from aimixe_collect.services.app import App


class TempHome:
    """A throwaway ~/.aimixe with sample files to collect."""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="aimixe-test-"))
        self.home = self.root / "home"
        self.docs = self.root / "docs"
        (self.docs / "tangsa_stuff").mkdir(parents=True)
        (self.docs / "tangsa_stuff" / "Mossang_wordlist.txt").write_text("a wordlist\n")
        (self.docs / "Tangsa_grammar_sketch.txt").write_text("grammar text\n")
        (self.docs / "recipes.txt").write_text("unrelated\n")
        (self.docs / "dup_copy.txt").write_text("grammar text\n")
        (self.docs / "notes.eaf").write_text('<ANNOTATION_DOCUMENT><TIER LANG_REF="nst"/></ANNOTATION_DOCUMENT>')
        self.app = App(self.home, registry=load_registry())
        return self

    def __exit__(self, *exc):
        self.app.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def tangsa(self):
        res = self.app.language_service.resolve("Tangsa")
        profile, _ = self.app.language_service.open_from_resolution(res.best)
        return profile
