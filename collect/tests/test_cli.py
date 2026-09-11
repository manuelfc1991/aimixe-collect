"""CLI tests: scripted stdin, argument surface, and the CLI/service separation rule."""
import contextlib
import io
import re
import unittest
from pathlib import Path
from unittest import mock

from aimixe_collect.cli import main as cli_main
from aimixe_collect.cli import profile_wizard
from aimixe_collect.profile import schema
from helpers import TempHome

SRC = Path(__file__).resolve().parents[1] / "src" / "aimixe_collect"


def run_cli(argv, stdin=""):
    out = io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(out), \
            mock.patch("builtins.input", side_effect=_fake_input(stdin)):
        code = cli_main.main(argv)
    return code, out.getvalue()


def _fake_input(text):
    lines = iter(text.splitlines())

    def _inp(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError
    return _inp


class CliTests(unittest.TestCase):
    def test_interactive_language_prompt_and_menu(self):
        with TempHome() as t:
            code, out = run_cli(["--home", str(t.home)], stdin="Tangsa\ny\nn\n6\n")
            self.assertEqual(code, 0)
            self.assertIn("Enter language name or ISO 639-3 code:", out)
            self.assertIn("Language detected", out)
            self.assertIn("Name: Tangsa", out)
            self.assertIn("ISO 639-3: nst", out)
            self.assertIn("Continue with this language? [Y/n]", out)
            self.assertIn("Complete missing profile information? [Y/n]", out)
            for item in ("1. Online Collection", "2. Offline Collection", "3. Import Files / Folder",
                         "4. View Existing Collection", "5. Language Profile", "6. Exit"):
                self.assertIn(item, out)

    def test_online_submenu(self):
        with TempHome() as t:
            code, out = run_cli(["--home", str(t.home)], stdin="nst\ny\nn\n1\n3\n6\n")
            self.assertEqual(code, 0)
            self.assertIn("1. Catalogue Search", out)
            self.assertIn("2. Agent Search", out)
            self.assertIn("3. Back", out)

    def test_non_interactive_scan_and_history(self):
        with TempHome() as t:
            code, out = run_cli(["nst", "--yes", "--scan", str(t.docs), "--home", str(t.home)])
            self.assertEqual(code, 0)
            self.assertIn("Collection Session: COL-", out)
            self.assertIn("Mode: Offline Collection", out)
            self.assertRegex(out, r"Discovered: \d+")
            code, out = run_cli(["history", "--home", str(t.home)])
            self.assertEqual(code, 0)
            self.assertIn("Offline Collection", out)

    def test_import_subcommand(self):
        with TempHome() as t:
            code, out = run_cli(["import", str(t.docs / "recipes.txt"), "-l", "nst", "--home", str(t.home)])
            self.assertEqual(code, 0)
            self.assertIn("Mode: Import", out)
            self.assertIn("Downloaded: 1", out)

    def test_unknown_language_offers_identification(self):
        with TempHome() as t:
            code, out = run_cli(["--home", str(t.home)], stdin="zzqqxx\n3\n")
            self.assertEqual(code, 0)
            self.assertIn("No language found", out)
            self.assertIn("Create a new language profile", out)

    def test_unknown_session_is_invalid(self):
        with TempHome() as t:
            code, _ = run_cli(["history", "COL-19990101-999", "--home", str(t.home)])
            self.assertEqual(code, 40)

    def test_cli_is_presentation_only(self):
        """Architecture rule (§19): nothing outside cli/ imports cli/."""
        for py in SRC.rglob("*.py"):
            if "cli" in py.parts or py.name == "__main__.py":
                continue
            text = py.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"from \.+cli(?:\.|\s+import)|import aimixe_collect\.cli\b|from aimixe_collect\.cli\b",
                                f"{py} imports the CLI")


class WizardParsingTests(unittest.TestCase):
    def _wizard(self, t, answers):
        p = t.tangsa()
        w = profile_wizard.ProfileWizard(t.app, p)
        it = iter(answers)
        with mock.patch("builtins.input", side_effect=lambda *_: next(it)), \
                contextlib.redirect_stdout(io.StringIO()):
            return p, w

    def test_field_parsers(self):
        with TempHome() as t:
            p, w = self._wizard(t, [])
            spec = schema.field_spec
            with contextlib.redirect_stdout(io.StringIO()):
                with mock.patch("builtins.input", side_effect=["yes - ELAR deposit"]):
                    self.assertEqual(w._ask_kind("resources", spec("resources", "recordings")),
                                     {"state": "yes", "detail": "ELAR deposit"})
                with mock.patch("builtins.input", side_effect=["some recordings by a missionary"]):
                    self.assertEqual(w._ask_kind("resources", spec("resources", "written"))["state"], "reported")
                with mock.patch("builtins.input", side_effect=["~8500"]):
                    self.assertEqual(w._ask_kind("resources", spec("resources", "speakers")),
                                     {"value": 8500, "approximate": True})
                with mock.patch("builtins.input", side_effect=["8,000-9,000"]):
                    self.assertEqual(w._ask_kind("resources", spec("resources", "speakers")), {"min": 8000, "max": 9000})
                with mock.patch("builtins.input", side_effect=["Changlang, district, Arunachal Pradesh, India", ""]):
                    self.assertEqual(w._ask_kind("orthography_location", spec("orthography_location", "places")),
                                     [{"name": "Changlang", "type": "district", "region": "Arunachal Pradesh",
                                       "country": "India"}])
                with mock.patch("builtins.input", side_effect=["Hindi (lingua franca), Assamese: regional, Nocte"]):
                    self.assertEqual(w._ask_kind("orthography_location", spec("orthography_location", "other_languages")),
                                     [{"name": "Hindi", "role": "lingua franca"}, {"name": "Assamese", "role": "regional"},
                                      {"name": "Nocte"}])
                with mock.patch("builtins.input", side_effect=["Latin, Mymr"]):
                    scripts = w._ask_kind("identity", spec("identity", "scripts"))
                    self.assertEqual([s["code"] for s in scripts], ["Latn", "Mymr"])
                with mock.patch("builtins.input", side_effect=["1"]):
                    self.assertEqual(w._ask_kind("orthography_location", spec("orthography_location", "orthography_status")),
                                     "standardized")
                with mock.patch("builtins.input", side_effect=["two competing Latin orthographies"]):
                    self.assertEqual(w._ask_kind("orthography_location", spec("orthography_location", "orthography_status")),
                                     "two competing Latin orthographies")
                with mock.patch("builtins.input", side_effect=["1", "2011", "Census of India"]):
                    self.assertEqual(w._ask_kind("community_status", spec("community_status", "speakers_basis")),
                                     {"type": "census", "year": 2011, "source": "Census of India"})
                with mock.patch("builtins.input", side_effect=["yes", "yes", "yes", "no", "mostly elders"]):
                    self.assertEqual(w._ask_kind("community_status", spec("community_status", "age_spread")),
                                     {"children": True, "young_adults": True, "adults": True, "elderly": False,
                                      "note": "mostly elders"})
                with mock.patch("builtins.input", side_effect=["1, 4, weddings"]):
                    self.assertEqual(w._ask_kind("community_status", spec("community_status", "used")),
                                     ["home", "religion", "weddings"])
                with mock.patch("builtins.input", side_effect=["Tangsa Naga", "Bible translation", "New Testament", "2005",
                                                               "Bible Society", "", ""]):
                    self.assertEqual(w._ask_kind("identity", spec("identity", "parent"))["value"], "Tangsa Naga")
                    # (the second input list continues into the translation entries)
                with mock.patch("builtins.input", side_effect=["yes", "Bible translation", "New Testament", "2005",
                                                               "Bible Society", "", ""]):
                    entries = w._ask_kind("translation_publication", spec("translation_publication", "translation"))
                    self.assertEqual(entries[0]["kind"], "Bible translation")
                    self.assertEqual(entries[0]["title"], "New Testament")
                    self.assertEqual(entries[0]["organisation"], "Bible Society")
                with mock.patch("builtins.input", side_effect=["no"]):
                    self.assertEqual(w._ask_kind("translation_publication", spec("translation_publication", "publication")),
                                     [{"state": "no"}])
                with mock.patch("builtins.input", side_effect=[""]):
                    self.assertIsNone(w._ask_kind("identity", spec("identity", "notes")))

    def test_progress_display(self):
        with TempHome() as t:
            p, w = self._wizard(t, [])
            st = t.app.profile_service.status(p)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                w.show_progress(st, "identity")
            text = out.getvalue()
            self.assertIn("✓ Basic identification", text)
            self.assertIn("● Names and classification", text)
            self.assertIn("○ Translation and publication", text)
            self.assertTrue(re.search(r"Language Profile\n", text))


if __name__ == "__main__":
    unittest.main()
