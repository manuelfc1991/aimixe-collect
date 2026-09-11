"""Agent Search: rule-based agent, CLI-backed agent with a fake tool, and the orchestrator over local pages."""
import contextlib
import io
import json
import os
import stat
import unittest
from unittest import mock
from pathlib import Path

from aimixe_collect.agent.base import AnalysisContext, Evidence
from aimixe_collect.agent.cli_agent import CliAgent, extract_json
from aimixe_collect.agent.registry import build_agent
from aimixe_collect.agent.rule_based import RuleBasedAgent, extract_facts
from aimixe_collect.discovery.web import WebHit, WebSearchBackend, fetch_page, normalise_url
from helpers import TempHome

PAGE = """<html><head><title>Tangsa language – documentation</title>
<meta name="description" content="Resources for the Tangsa language of Arunachal Pradesh"></head>
<body><nav><a href="https://facebook.com/x">fb</a></nav>
<h1>Tangsa</h1>
<p>Tangsa, also known as Tase and Tangshang, is spoken in Changlang district. Mossang is a Tangsa variety
with its own orthography. Approximately 8,500 speakers were counted.</p>
<p><a href="grammar.txt">Tangsa grammar sketch (txt)</a></p>
<p><a href="recipes.txt">Recipes</a></p>
<p><a href="mossang.html">Mossang page</a></p>
<p><a href="https://example.org/unrelated">Unrelated site</a></p>
</body></html>"""

MOSSANG = """<html><head><title>Mossang wordlist</title></head><body>
<p>A Mossang (Tangsa) wordlist.</p><p><a href="mossang_words.txt">Mossang wordlist download</a></p></body></html>"""


class LocalBackend(WebSearchBackend):
    name = "local"

    def __init__(self, root: Path):
        self.root = root
        self.queries: list[str] = []

    def search(self, query, limit=10):
        self.queries.append(query)
        if "Mossang" in query:
            return [WebHit(url=(self.root / "mossang.html").as_uri(), title="Mossang wordlist", query=query)]
        return [WebHit(url=(self.root / "index.html").as_uri(), title="Tangsa language", snippet="Tangsa resources",
                       query=query)]


def _site(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(PAGE)
    (root / "mossang.html").write_text(MOSSANG)
    (root / "grammar.txt").write_text("Tangsa grammar sketch: phonology, morphology.\n")
    (root / "recipes.txt").write_text("boil water\n")
    (root / "mossang_words.txt").write_text("water  nu\nfire   van\n")


class RuleAgentTests(unittest.TestCase):
    def test_queries_use_every_profile_field(self):
        with TempHome() as t:
            p = t.tangsa()
            svc = t.app.profile_service
            svc.set_value(p, "orthography_location", "varieties", ["Mossang"])
            svc.set_value(p, "resources", "recordings", {"state": "yes", "detail": "ELAR"})
            svc.set_value(p, "orthography_location", "places", [{"name": "Changlang", "type": "district"}])
            svc.set_value(p, "translation_publication", "publication", [{"kind": "book", "title": "A Tangsa Primer"}])
            qs = RuleBasedAgent(max_queries=60).generate_search_queries(p)
            texts = [q.text for q in qs]
            self.assertIn('"Tangsa" dictionary', texts)
            self.assertIn('"Mossang" dictionary', texts)                     # the specification's example
            self.assertIn('"Mossang" language documentation', texts)
            self.assertIn('"Mossang" "Tangsa" corpus', texts)
            self.assertIn('"Tangsa" ELAR', texts)                            # recordings: yes switches the family on
            self.assertIn('"Tangsa" PARADISEC', texts)
            self.assertIn('"Tangsa" "Changlang" language', texts)
            self.assertIn('"A Tangsa Primer"', texts)
            self.assertTrue(any(q.basis == "code" for q in qs))
            self.assertEqual(len(texts), len({x.lower() for x in texts}))

    def test_fact_extraction(self):
        ev = Evidence(text=("Tangsa, also known as Tase and Tangshang, is spoken in Changlang district. "
                            "Mossang is a Tangsa variety. It belongs to the Sino-Tibetan family. "
                            "Approximately 8,500 speakers remain. It is written in the Latin script."),
                      url="https://example.org/tangsa")
        facts = extract_facts(ev, profile_name="Tangsa")
        by = {(f.group, f.field): f.value for f in facts}
        self.assertEqual(by[("orthography_location", "varieties")], ["Mossang"])
        self.assertEqual(by[("identity", "alternate_names")], ["Tase", "Tangshang"])
        self.assertEqual(by[("orthography_location", "places")][0]["name"], "Changlang")
        self.assertEqual(by[("orthography_location", "places")][0]["type"], "district")
        self.assertEqual(by[("identity", "family")], "Sino-Tibetan")
        self.assertEqual(by[("resources", "speakers")], 8500)
        self.assertEqual(by[("identity", "scripts")][0]["name"], "Latin")
        self.assertTrue(all(f.confidence < 0.7 for f in facts))
        self.assertTrue(all(f.quote for f in facts))

    def test_analyze_and_classify(self):
        with TempHome() as t:
            p = t.tangsa()
            a = RuleBasedAgent()
            good = a.analyze(AnalysisContext(p, "https://x/tangsa_grammar.pdf", "Tangsa grammar", "about tangsa"))
            bad = a.analyze(AnalysisContext(p, "https://x/recipes.pdf", "Recipes", "boil water"))
            self.assertGreaterEqual(good.score, 70)
            self.assertLess(bad.score, 30)
            from aimixe_collect.agent.base import ResourceView
            types = a.classify(ResourceView(name="tangsa_dictionary.pdf", format="pdf"))
            self.assertEqual(types[0][0], "dictionary")


class CliAgentTests(unittest.TestCase):
    def test_extract_json(self):
        self.assertEqual(extract_json('chatter\n```json\n[{"query": "x"}]\n```\nbye'), [{"query": "x"}])
        self.assertEqual(extract_json('{"score": 80, "reasons": []} trailing'), {"score": 80, "reasons": []})
        with self.assertRaises(ValueError):
            extract_json("nothing here")

    def test_fake_cli_tool_is_combined_with_baseline(self):
        with TempHome() as t:
            p = t.tangsa()
            tool = t.root / "fake_agent.py"
            tool.write_text(
                "import sys, json\n"
                "prompt = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()\n"
                "if 'search queries' in prompt:\n"
                "    print(json.dumps([{'query': 'Tangsa Naga hymnal', 'basis': 'community', 'why': 'churches publish hymnals'}]))\n"
                "elif 'Does the following' in prompt:\n"
                "    print('Sure! ' + json.dumps({'score': 95, 'reasons': ['about Tangsa'], 'language_hints': ['Mossang'], 'resource_types': ['grammar']}))\n"
                "elif 'Classify' in prompt:\n"
                "    print(json.dumps([{'type': 'grammar', 'confidence': 0.9}]))\n"
                "else:\n"
                "    print(json.dumps([{'group': 'identity', 'field': 'exonyms', 'value': ['Rangpan people'], 'confidence': 0.6, 'quote': 'called Rangpan by neighbours'}]))\n")
            agent = CliAgent({"name": "fake", "command": f"python3 {tool} {{prompt}}", "timeout": 30})
            self.assertTrue(agent.available()[0])
            qs = agent.generate_search_queries(p)
            self.assertIn("Tangsa Naga hymnal", [q.text for q in qs])
            self.assertTrue(any(q.basis == "name" for q in qs))              # baseline queries are kept
            an = agent.analyze(AnalysisContext(p, "https://x/tangsa.pdf", "Tangsa", "tangsa text"))
            self.assertEqual(an.source, "fake")
            self.assertLessEqual(an.score, 100)
            self.assertIn("Mossang", an.language_hints)
            facts = agent.enrich_language_profile(Evidence("Tangsa is called Rangpan by neighbours.", "u"))
            self.assertTrue(any(f.field == "exonyms" and f.source == "fake" for f in facts))
            broken = CliAgent({"name": "broken", "command": "definitely-not-a-command-xyz {prompt}"})
            self.assertFalse(broken.available()[0])
            self.assertTrue(broken.generate_search_queries(p))                 # degrades to the baseline
            self.assertTrue(broken.errors)

    def test_registry(self):
        self.assertIsInstance(build_agent({"provider": "rule_based"}), RuleBasedAgent)
        a = build_agent({"provider": "claude"})
        self.assertIsInstance(a, CliAgent)
        self.assertEqual(a.name, "claude")
        c = build_agent({"provider": "custom", "cli": {"command": "mytool {prompt}"}})
        self.assertEqual(c.command, "mytool {prompt}")
        with self.assertRaises(ValueError):
            build_agent({"provider": "nonexistent"})


class AgentSearchRunTests(unittest.TestCase):
    def test_orchestration_over_local_site(self):
        with TempHome() as t:
            p = t.tangsa()
            site = t.root / "site"
            _site(site)
            backend = LocalBackend(site)
            svc = t.app.agent_service
            runner = svc.runner(p, backends=[backend], agent=RuleBasedAgent(max_queries=3))
            queries = runner.plan()
            self.assertTrue(queries)
            run = svc.run(p, runner, queries)
            rep = run.report
            self.assertGreaterEqual(rep.pages_fetched, 2)
            self.assertGreaterEqual(rep.pages_relevant, 1)
            # step 15: Mossang learned from the page text → new queries in round 2 → Mossang page found
            self.assertIn("Mossang", rep.learned)
            self.assertTrue(any("Mossang" in q for q in backend.queries), backend.queries)
            self.assertTrue(any(q.basis == "learned" for q in rep.queries))
            names = {(o.candidate.url or "").rsplit("/", 1)[-1]: o for o in run.outcomes}
            self.assertIn("grammar.txt", names)
            self.assertEqual(names["grammar.txt"].status, "stored")
            self.assertIn("mossang_words.txt", names)
            self.assertNotEqual(names.get("recipes.txt") and names["recipes.txt"].status, "stored")   # unrelated file rejected
            # the relevant page itself is stored as an html resource
            self.assertTrue(any(o.candidate.local_path and str(o.candidate.local_path).endswith(".html")
                                for o in run.outcomes if o.candidate.local_path))
            # provenance (§16): source URL, resource URL, method, query, discovery/download dates
            src = t.app.resources.sources(names["grammar.txt"].resource_id)[0]
            self.assertEqual(src["method"], "agent")
            self.assertTrue(src["source_url"].endswith("index.html"))
            self.assertTrue(src["resource_url"].endswith("grammar.txt"))
            self.assertTrue(src["query"])
            self.assertIsNotNone(src["download_date"])
            # proposals reached the review queue, not the profile
            self.assertGreater(run.proposals_queued, 0)
            p2 = t.app.language_service.load("nst")
            self.assertNotIn("Mossang", p2.collected("orthography_location", "varieties"))
            fields = {i.payload["field"] for i in t.app.review_service.pending("nst") if i.kind == "profile_field"}
            self.assertIn("varieties", fields)
            self.assertIn("alternate_names", fields)
            s = t.app.collection_service.summary(run.session_id)
            self.assertEqual(s.mode, "Agent Search")
            self.assertGreaterEqual(s.downloaded, 2)
            self.assertTrue(any("query [" in e["message"] for e in t.app.sessions.events(run.session_id)))
            self.assertFalse(list(t.app.paths.temp.glob("agent-*")))

    def test_fetch_page_and_url_helpers(self):
        with TempHome() as t:
            site = t.root / "site"
            _site(site)
            page = fetch_page((site / "index.html").as_uri())
            self.assertEqual(page.title, "Tangsa language – documentation")
            self.assertIn("Mossang is a Tangsa variety", page.text)
            self.assertTrue(any(u.endswith("grammar.txt") for u, _ in page.links))
            self.assertNotIn("fb", [a for _, a in page.links])           # nav links are skipped
            self.assertEqual(page.meta["description"], "Resources for the Tangsa language of Arunachal Pradesh")
        self.assertEqual(normalise_url("HTTPS://Example.org/a/?utm_source=x&b=1#frag"), "https://example.org/a?b=1")


class AgentCliTests(unittest.TestCase):
    def test_agent_flag_non_interactive(self):
        from aimixe_collect.cli import main as cli_main
        with TempHome() as t:
            cfg = t.app.paths.config / "config.toml"
            import re as _re
            cfg.write_text(_re.sub(r"^search_backends = .*$", "search_backends = []", cfg.read_text(), flags=_re.M))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli_main.main(["nst", "--yes", "--agent", "--home", str(t.home)])
            self.assertEqual(code, 0)
            self.assertIn("Agent Search", out.getvalue())
            self.assertIn("No usable search engine", out.getvalue())


if __name__ == "__main__":
    unittest.main()


class ProviderSelectionTests(unittest.TestCase):
    def test_choices_and_persisted_selection(self):
        with TempHome() as t:
            svc = t.app.agent_service
            names = [c["name"] for c in svc.choices()]
            self.assertEqual(names[0], "rule_based")
            self.assertIn("claude", names)
            self.assertTrue([c for c in svc.choices() if c["current"]][0]["name"] == "rule_based")
            svc.set_provider("ollama")
            self.assertEqual(svc.agent().name, "ollama")
            text = (t.app.paths.config / "config.toml").read_text()
            self.assertIn('provider = "ollama"', text)
            self.assertEqual(text.count("[agent]"), 1)
            svc.set_provider("rule_based")
            self.assertIn('provider = "rule_based"', (t.app.paths.config / "config.toml").read_text())
            with self.assertRaises(ValueError):
                svc.set_provider("nonexistent")
            # the interactive chooser saves the pick
            from aimixe_collect.cli import interactive
            with mock.patch("builtins.input", side_effect=["2"]), contextlib.redirect_stdout(io.StringIO()):
                chosen = interactive.choose_agent_provider(t.app)
            self.assertEqual(chosen, names[1])


class IriTests(unittest.TestCase):
    def test_non_ascii_urls_are_percent_encoded(self):
        from aimixe_collect.catalogues.http import iri_to_uri
        self.assertEqual(iri_to_uri("https://en.wikipedia.org/wiki/Tai_Lü_language"),
                         "https://en.wikipedia.org/wiki/Tai_L%C3%BC_language")
        self.assertEqual(iri_to_uri("https://x.example/a b?q=ü#f"), "https://x.example/a%20b?q=%C3%BC#f")
        self.assertEqual(iri_to_uri("https://x.example/already%20ok?q=1"), "https://x.example/already%20ok?q=1")
        self.assertEqual(iri_to_uri("https://bücher.example/p"), "https://xn--bcher-kva.example/p")

    def test_one_bad_page_does_not_end_the_run(self):
        from aimixe_collect.agent.rule_based import RuleBasedAgent
        from aimixe_collect.discovery.web import WebHit, WebSearchBackend
        with TempHome() as t:
            p = t.tangsa()
            site = t.root / "site"
            _site(site)

            class Mixed(WebSearchBackend):
                name = "mixed"

                def search(self, query, limit=10):
                    return [WebHit(url="https://en.wikipedia.org/wiki/Tai_Lü_\udcff", title="broken", query=query),
                            WebHit(url=(site / "index.html").as_uri(), title="Tangsa language", query=query)]

            runner = t.app.agent_service.runner(p, backends=[Mixed()], agent=RuleBasedAgent(max_queries=1))
            run = t.app.agent_service.run(p, runner, runner.plan())
            self.assertEqual(run.report.pages_fetched, 1)          # the good page was still visited
            self.assertTrue(run.report.errors)                      # the bad one is reported, not fatal
