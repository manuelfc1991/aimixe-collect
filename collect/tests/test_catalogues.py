"""Catalogue providers and the online collection run, offline via file:// URLs and a fake provider."""
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from aimixe_collect.catalogues.base import CatalogueProvider, CatalogueResult, DownloadableFile, ProfileProposal
from aimixe_collect.catalogues.configurable import ConfigurableProvider, path_get
from aimixe_collect.catalogues.registry import build_provider
from aimixe_collect.cli import main as cli_main
from helpers import TempHome


class FakeProvider(CatalogueProvider):
    name = "fake"
    description = "a test catalogue"

    def __init__(self, docs: Path):
        super().__init__({})
        self.docs = docs

    def search(self, language_profile, limit=25):
        good = self.docs / "Tangsa_grammar_sketch.txt"
        return [
            CatalogueResult(provider="fake", kind="record", title="A Tangsa grammar sketch",
                            landing_url="https://example.org/tangsa-grammar", licence="CC-BY-4.0",
                            language="nst", types=["grammar"], files=[DownloadableFile(url=good.as_uri())],
                            query="Tangsa",
                            proposals=[ProfileProposal("orthography_location", "varieties", ["Mossang"], 0.72,
                                                       "https://example.org/tangsa-grammar")]),
            CatalogueResult(provider="fake", kind="record", title="Recipes of the world",
                            landing_url="https://example.org/recipes", query="Tangsa"),
            CatalogueResult(provider="fake", kind="record", title="Naga hills survey (record only)",
                            landing_url="https://example.org/naga-survey", description="mentions Rangpang villages",
                            query="Tangsa"),
            CatalogueResult(provider="fake", kind="lookup", title="fake: open the archive page",
                            landing_url="https://example.org/search?q=Tangsa", query="Tangsa"),
        ]


class CatalogueRunTests(unittest.TestCase):
    def test_search_scores_before_download_and_ingests_through_pipeline(self):
        with TempHome() as t:
            p = t.tangsa()
            svc = t.app.catalogue_service
            report = svc.search(p, providers=[FakeProvider(t.docs)])
            actions = {s.result.title: s.action for s in report.results}
            self.assertEqual(actions["A Tangsa grammar sketch"], "download")
            self.assertEqual(actions["Recipes of the world"], "skip")
            self.assertEqual(len(report.lookups), 1)
            svc.registry.entries["fake"] = type("E", (), {"provider": FakeProvider(t.docs), "name": "fake",
                                                          "enabled": True, "source": "test"})()
            run = svc.collect(p, report)
            statuses = {o.candidate.title.split(" · ")[0]: o.status for o in run.outcomes}
            self.assertEqual(statuses["A Tangsa grammar sketch"], "stored")
            self.assertEqual(statuses["Naga hills survey (record only)"], "uncertain_review")
            # provenance for the online resource (§16)
            stored = [o for o in run.outcomes if o.status == "stored"][0]
            src = t.app.resources.sources(stored.resource_id)[0]
            self.assertEqual(src["method"], "catalogue")
            self.assertEqual(src["catalogue"], "fake")
            self.assertEqual(src["source_url"], "https://example.org/tangsa-grammar")
            self.assertTrue(src["resource_url"].startswith("file://"))
            self.assertEqual(src["query"], "Tangsa")
            self.assertEqual(src["licence"], "CC-BY-4.0")
            self.assertIsNotNone(src["download_date"])
            self.assertIsNone(src["original_path"])
            self.assertIn("grammar", stored.types)
            # record without files became a metadata resource
            meta = [o for o in run.outcomes if o.candidate.title.startswith("Naga hills")][0]
            self.assertIn("metadata", meta.types)
            # the catalogue's language fact went to review, not into the profile
            self.assertEqual(run.report.proposals, 1)
            p2 = t.app.language_service.load("nst")
            self.assertNotIn("Mossang", p2.collected("orthography_location", "varieties"))
            self.assertEqual([i.kind for i in t.app.review_service.pending("nst") if i.kind == "profile_field"],
                             ["profile_field"])
            # lookups are kept in a manifest and the session counts everything
            self.assertTrue(run.lookup_manifest and run.lookup_manifest.exists())
            s = t.app.collection_service.summary(run.session_id)
            self.assertEqual(s.mode, "Catalogue Search")
            self.assertEqual(s.discovered, 4)
            self.assertEqual(s.downloaded, 2)
            self.assertEqual(s.pending_review, 2)   # one uncertain resource + one profile proposal
            self.assertFalse(list((t.app.paths.temp).glob("download-*")), "temp download dir cleaned")

    def test_configurable_api_json_provider_over_file_url(self):
        with TempHome() as t:
            p = t.tangsa()
            api = t.docs / "api.json"
            api.write_text(json.dumps({"hits": {"hits": [
                {"metadata": {"title": "Tangsa wordlist", "license": {"id": "cc-by"}, "resource_type": {"type": "dataset"}},
                 "links": {"self_html": "https://example.org/r/1"},
                 "files": [{"links": {"self": (t.docs / "tangsa_stuff" / "Mossang_wordlist.txt").as_uri()}}]}]}}))
            cfg = {"name": "local_api", "kind": "api_json", "url": api.as_uri() + "?q={q}", "items": "hits.hits",
                   "fields": {"title": "metadata.title", "url": "links.self_html", "download": "files[].links.self",
                              "licence": "metadata.license.id", "types": "metadata.resource_type.type"}}
            prov = build_provider(cfg)
            self.assertIsInstance(prov, ConfigurableProvider)
            results = prov.search(p)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].title, "Tangsa wordlist")
            self.assertEqual(results[0].licence, "cc-by")
            self.assertEqual(results[0].types, ["dataset"])
            self.assertEqual(len(results[0].files), 1)

    def test_path_get(self):
        d = {"a": {"b": [{"c": 1}, {"c": 2}]}}
        self.assertEqual(path_get(d, "a.b[].c"), [1, 2])
        self.assertEqual(path_get(d, "a.b.c"), [1, 2])
        self.assertIsNone(path_get(d, "a.x"))

    def test_lookup_provider_needs_code(self):
        with TempHome() as t:
            local = t.app.language_service.create_local("Made Up")
            prov = build_provider({"name": "x", "kind": "lookup", "url": "https://e.org/{code}", "asks_by": "code"})
            self.assertEqual(prov.search(local), [])
            ok, why = prov.available_for(local)
            self.assertFalse(ok)
            self.assertIn("ISO 639-3", why)

    def test_builtin_registry_and_management(self):
        with TempHome() as t:
            svc = t.app.catalogue_service
            names = {e.name for e in svc.list()}
            self.assertTrue({"olac", "glottolog", "elar", "paradisec", "kaipuleohone", "pangloss", "zenodo",
                             "internet_archive"} <= names)
            self.assertFalse(svc.registry.errors)
            path = svc.add({"name": "My Repo", "kind": "lookup", "url": "https://repo.example/{q}", "what": "test"})
            self.assertTrue(path.exists())
            self.assertIn("my_repo", {e.name for e in svc.list()})
            with self.assertRaises(ValueError):
                svc.add({"name": "bad", "kind": "api_json"})   # no url
            self.assertIn("removed", svc.remove("my_repo"))
            self.assertNotIn("my_repo", {e.name for e in svc.list()})
            msg = svc.remove("pangloss")
            self.assertIn("disabled", msg)
            self.assertFalse(svc.get("pangloss").enabled)
            self.assertIn('"pangloss"', (t.app.paths.config / "config.toml").read_text())

    def test_catalogue_cli(self):
        with TempHome() as t:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli_main.main(["catalogue", "list", "--home", str(t.home)])
            self.assertEqual(code, 0)
            self.assertIn("zenodo", out.getvalue())
            toml = t.docs / "cat.toml"
            toml.write_text('name = "uni"\nkind = "lookup"\nurl = "https://uni.example/search?q={q}"\nwhat = "uni repo"\n')
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli_main.main(["catalogue", "add", "--file", str(toml), "--home", str(t.home)]), 0)
                self.assertEqual(cli_main.main(["catalogue", "remove", "uni", "--home", str(t.home)]), 0)
                self.assertEqual(cli_main.main(["catalogue", "remove", "nope", "--home", str(t.home)]), 40)


@unittest.skipUnless(os.environ.get("AIMIXE_LIVE"), "set AIMIXE_LIVE=1 to hit the real catalogues")
class LiveCatalogueTests(unittest.TestCase):
    def test_live_search_tangsa(self):
        with TempHome() as t:
            p = t.tangsa()
            svc = t.app.catalogue_service
            report = svc.search(p)
            self.assertIn("glottolog", report.providers)
            self.assertTrue(report.results)
            titles = " ".join(s.result.title for s in report.results).lower()
            self.assertIn("tangsa", titles)


if __name__ == "__main__":
    unittest.main()


class SurnameLikeNameTests(unittest.TestCase):
    """Regression: 'Zhuang' is an alternative name of Yongnan Zhuang and a common surname (reported by the user)."""

    def test_author_names_do_not_count(self):
        from aimixe_collect.relevance.scorer import score_text, terms_from_profile
        with TempHome() as t:
            res = t.app.language_service.resolve("zyn")
            p, _ = t.app.language_service.open_from_resolution(res.best)
            terms = terms_from_profile(p)
            junk = ["Isopsestis poculiformis Zhuang, Owada & Wang 2015 new species from Guangxi China",
                    "Nectria triseptata Z. Q. Zeng & W. Y. Zhuang", "Anelpistina levidensis Espinasa & Zhuang 2009"]
            for txt in junk:
                self.assertLess(score_text(terms, txt, catalogue_types=["publication"]).score, 30, txt)
            about = score_text(terms, "How Standard Zhuang has Met with Market Forces in China", catalogue_types=["publication"])
            self.assertTrue(30 <= about.score < 50, about)       # weak: "Zhuang" names a dozen languages
            self.assertTrue(any("shared name" in r for r in about.reasons))
            exact = score_text(terms, "Yongnan Zhuang wordlist collected in Long An county")
            self.assertGreaterEqual(exact.score, 90)
            # a term is evidence once, even when it is both an alternative name and the parent macrolanguage
            self.assertEqual(sum("Zhuang" in r for r in about.reasons), 1)
