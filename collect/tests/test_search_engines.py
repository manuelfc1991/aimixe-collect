"""Search engines as data: json / rss / html kinds over file:// fixtures, registry, CLI commands."""
import contextlib
import io
import json
import unittest
from pathlib import Path

from aimixe_collect.catalogues import http
from aimixe_collect.discovery.search_engines import EngineBackend, SearchEngineRegistry, load_builtin
from aimixe_collect.cli import main as cli_main
from helpers import TempHome


class EngineKindsTests(unittest.TestCase):
    def test_json_rss_html(self):
        with TempHome() as t:
            d = t.docs
            (d / "api.json").write_text(json.dumps({"results": [
                {"url": "https://a.example/tangsa", "title": "Tangsa grammar", "content": "a grammar"},
                {"url": "https://b.example/x", "title": "Other"}]}))
            (d / "feed.xml").write_text('<rss><channel><item><title>T1</title><link>https://r.example/1</link>'
                                        '<description>d1</description></item><item><title>T2</title>'
                                        '<link>https://r.example/2</link></item></channel></rss>')
            (d / "page.html").write_text('<html><body><h3><a href="/link?url=abc">Res &amp; one</a></h3>'
                                         '<h3><a href="https://h.example/two">Two</a></h3></body></html>')
            j = EngineBackend({"name": "j", "kind": "json", "url": (d / "api.json").as_uri() + "?q={q}", "items": "results",
                               "fields": {"url": "url", "title": "title", "snippet": "content"}})
            hits = j.search('"Tangsa" language')
            self.assertEqual([h.url for h in hits], ["https://a.example/tangsa", "https://b.example/x"])
            self.assertEqual(hits[0].snippet, "a grammar")
            rss = EngineBackend({"name": "r", "kind": "rss", "url": (d / "feed.xml").as_uri() + "?q={q}"})
            self.assertEqual([h.title for h in rss.search("x")], ["T1", "T2"])
            h = EngineBackend({"name": "h", "kind": "html", "url": (d / "page.html").as_uri() + "?q={q}",
                               "link_pattern": r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', "base": "https://h.example"})
            hits = h.search("x")
            self.assertEqual(hits[0].url, "https://h.example/link?url=abc")
            self.assertEqual(hits[0].title, "Res & one")
            self.assertEqual(hits[1].url, "https://h.example/two")

    def test_bot_check_and_keys(self):
        with TempHome() as t:
            blocked = t.docs / "blocked.html"
            blocked.write_text("<html>Please complete the captcha to continue</html>")
            b = EngineBackend({"name": "b", "kind": "html", "url": blocked.as_uri() + "?q={q}",
                               "link_pattern": r'class="res"[^>]*href="([^"]+)"', "blocked_pattern": "captcha"})
            with self.assertRaises(http.HttpError):
                b.search("x")
            k = EngineBackend({"name": "k", "kind": "json", "url": "https://x/{key}?q={q}", "needs_key": True})
            self.assertFalse(k.available()[0])
            self.assertIn("AIMIXE_SEARCH_KEY_K", k.available()[1])
            k2 = EngineBackend({"name": "k", "kind": "json", "url": "https://x/{key}?q={q}", "needs_key": True}, key="abc")
            self.assertTrue(k2.available()[0])
            self.assertIn("/abc?q=", k2._url("q"))
            with self.assertRaises(ValueError):
                EngineBackend({"name": "bad", "kind": "soap", "url": "x"})

    def test_builtin_table_is_valid(self):
        names = [c["name"] for c in load_builtin()]
        self.assertTrue({"duckduckgo", "bing", "wikipedia", "searxng", "brave", "google_cse", "serpapi", "baidu", "sogou"} <= set(names))
        for c in load_builtin():
            EngineBackend(c)   # every shipped entry parses


class RegistryAndCliTests(unittest.TestCase):
    def test_registry_and_service(self):
        with TempHome() as t:
            svc = t.app.agent_service
            names = {e["name"] for e in svc.engines()}
            self.assertIn("baidu", names)
            self.assertEqual([b.name for b in svc.backends()], ["duckduckgo", "bing", "wikipedia"])
            svc.set_backends(["wikipedia", "bing"])
            self.assertEqual([b.name for b in svc.backends()], ["wikipedia", "bing"])
            self.assertIn('search_backends = ["wikipedia", "bing"]', (t.app.paths.config / "config.toml").read_text())
            with self.assertRaises(ValueError):
                svc.set_backends(["nope"])
            # keyed engine is left out until a key exists
            svc.set_backends(["brave", "wikipedia"])
            self.assertEqual([b.name for b in svc.backends()], ["wikipedia"])
            t.app.config.values["agent"]["search_keys"] = {"brave": "k"}
            self.assertEqual([b.name for b in svc.backends()], ["brave", "wikipedia"])
            # add a user engine over a local fixture, test it, remove it
            api = t.docs / "mine.json"
            api.write_text(json.dumps({"hits": [{"link": "https://m.example/1", "name": "Mine"}]}))
            path = svc.add_engine({"name": "My Engine", "kind": "json", "url": api.as_uri() + "?q={q}", "items": "hits",
                                   "fields": {"url": "link", "title": "name"}, "what": "test"})
            self.assertTrue(path.exists())
            self.assertIn("my_engine", {e["name"] for e in svc.engines()})
            hits = svc.test_engine("my_engine", "anything")
            self.assertEqual(hits[0].url, "https://m.example/1")
            svc.set_backends(["my_engine"])
            self.assertIn("removed", svc.remove_engine("my_engine"))
            self.assertNotIn("my_engine", {e["name"] for e in svc.engines()})
            self.assertEqual(t.app.config.values["agent"]["search_backends"], [])

    def test_cli_search_commands(self):
        with TempHome() as t:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli_main.main(["search", "list", "--home", str(t.home)]), 0)
            self.assertIn("baidu", out.getvalue())
            self.assertIn("needs key", out.getvalue())
            toml = t.docs / "eng.toml"
            api = t.docs / "e.json"
            api.write_text(json.dumps({"r": [{"u": "https://e.example/1", "t": "E"}]}))
            toml.write_text(f'name = "eng"\nkind = "json"\nurl = "{api.as_uri()}?q={{q}}"\nitems = "r"\n[fields]\nurl = "u"\ntitle = "t"\n')
            with contextlib.redirect_stdout(out), unittest.mock.patch("builtins.input", side_effect=["y"]):
                self.assertEqual(cli_main.main(["search", "add", "--file", str(toml), "--home", str(t.home)]), 0)
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli_main.main(["search", "test", "eng", "x", "--home", str(t.home)]), 0)
                self.assertEqual(cli_main.main(["search", "use", "eng", "wikipedia", "--home", str(t.home)]), 0)
                self.assertEqual(cli_main.main(["search", "remove", "eng", "--home", str(t.home)]), 0)
                self.assertEqual(cli_main.main(["search", "test", "nope", "--home", str(t.home)]), 40)
            self.assertIn("https://e.example/1", out.getvalue())


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
