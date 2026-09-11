import unittest

from aimixe_collect.language.registry import fold, load_registry


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = load_registry()

    def test_fold(self):
        self.assertEqual(fold("Tangsá"), "tangsa")
        self.assertEqual(fold("Naga, Tase"), "naga tase")

    def test_code_lookup(self):
        rec = self.reg.by_code("nst")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.family, "Sino-Tibetan")
        self.assertIn("Tangsa", rec.alt_names)
        self.assertEqual(self.reg.region_text(rec), "India / Myanmar")

    def test_alternative_name_resolves(self):
        cands = self.reg.find("Tangsa")
        self.assertEqual(cands[0].record.code, "nst")
        self.assertEqual(cands[0].matched_on, "alternate_name")

    def test_dialect_alias_resolves(self):
        cands = self.reg.find("Hakhun")   # a Nocte variety in Glottolog
        self.assertTrue(any(c.record.code == "njb" and c.matched_on == "dialect" for c in cands))

    def test_retired_code_redirects(self):
        cands = self.reg.find("fri")
        self.assertEqual(cands[0].record.code, "fry")
        self.assertEqual(cands[0].matched_on, "retired_code")

    def test_unknown(self):
        self.assertEqual(self.reg.find("zzqqxx"), [])

    def test_scripts(self):
        self.assertEqual(self.reg.script("Latn").name, "Latin")
        self.assertEqual(self.reg.script("myanmar").code, "Mymr")
        self.assertEqual(self.reg.script("Tangsa").code, "Tnsa")


if __name__ == "__main__":
    unittest.main()
