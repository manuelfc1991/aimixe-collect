import json
import unittest

from aimixe_collect.profile import schema
from aimixe_collect.profile.model import FieldValue, Profile
from helpers import TempHome


class ProfileModelTests(unittest.TestCase):
    def test_groups_match_specification(self):
        expected = {
            "identity": ["family", "alternate_names", "exonyms", "notes", "parent", "scripts"],
            "orthography_location": ["orthography_status", "literacy", "varieties", "region", "places", "other_languages"],
            "resources": ["summary", "written", "recordings", "studies", "digital", "speakers"],
            "community_status": ["speakers_basis", "transmission", "age_spread", "used", "displaced", "community"],
            "translation_publication": ["translation", "publication"],
        }
        for g in schema.GROUPS:
            self.assertEqual(sorted(f.name for f in g.fields), sorted(expected[g.name]))

    def test_disagreement_is_preserved(self):
        p = Profile(id="x", name="X")
        p.add("resources", "speakers", FieldValue(8500, source_type="local_database", source="Glottolog", confidence=0.6))
        p.add("resources", "speakers", FieldValue(12000, source_type="catalogue", source="Ethnologue", confidence=0.7))
        self.assertTrue(p.is_contradictory("resources", "speakers"))
        self.assertEqual(len(p.field_values("resources", "speakers")), 2)
        p.set_user_value("resources", "speakers", 9000)
        self.assertEqual(p.display_value("resources", "speakers"), 9000)
        self.assertEqual(len(p.field_values("resources", "speakers")), 3)   # nothing replaced
        self.assertFalse(p.is_contradictory("resources", "speakers"))     # a preferred value settles it

    def test_multi_value_fields_merge_sources(self):
        p = Profile(id="x", name="X")
        p.add("identity", "alternate_names", FieldValue(["A", "B"], source_type="local_database"))
        p.set_user_value("identity", "alternate_names", ["b", "C"])
        self.assertEqual(p.collected("identity", "alternate_names"), ["b", "C", "A"])   # the user's values lead

    def test_export_shape_and_provenance(self):
        p = Profile(id="nst", name="Tangsa", iso639_3="nst")
        p.set_user_value("resources", "speakers", 8500)
        doc = p.to_json()
        for key in ("id", "name", "iso639_3", "identity", "orthography_location", "resources",
                    "community_status", "translation_publication"):
            self.assertIn(key, doc)
        env = doc["provenance"]["resources"]["speakers"][0]
        self.assertEqual(env["value"], 8500)
        self.assertEqual(env["source_type"], "user")
        json.dumps(doc)  # serialisable

    def test_every_field_feeds_discovery_or_is_descriptive(self):
        """Specification §23: profile fields must inform collection, not sit as passive metadata."""
        feeding = set(schema.fields_feeding("query")) | set(schema.fields_feeding("relevance")) | \
            set(schema.fields_feeding("offline")) | set(schema.fields_feeding("classify"))
        descriptive_only = {("identity", "notes"), ("orthography_location", "literacy"),
                            ("resources", "speakers"), ("community_status", "speakers_basis"),
                            ("community_status", "transmission"), ("community_status", "age_spread")}
        for g, f in schema.all_fields():
            self.assertTrue((g.name, f.name) in feeding or (g.name, f.name) in descriptive_only,
                            f"{g.name}.{f.name} feeds nothing")


class ProfileServiceTests(unittest.TestCase):
    def test_enrichment_and_status(self):
        with TempHome() as t:
            p = t.tangsa()
            self.assertEqual(p.id, "nst")
            self.assertEqual(p.name, "Tangsa")
            st = t.app.profile_service.status(p)
            known = {f for _, f in st.known}
            self.assertTrue({"family", "alternate_names", "region", "scripts", "varieties"} <= known)
            self.assertIn(("community_status", "transmission"), st.uncertain)   # low-confidence AES mapping
            self.assertIn(("orthography_location", "orthography_status"), st.to_ask)
            self.assertNotIn(("identity", "family"), st.to_ask)
            self.assertEqual(st.group_state("translation_publication"), "empty")
            # local registry finds the stored profile first, by a user-added alias
            t.app.profile_service.set_value(p, "identity", "exonyms", ["Rangpan people"])
            res = t.app.language_service.resolve("Rangpan people")
            self.assertEqual(res.status, "exact")
            self.assertEqual(res.best.source, "local_registry")
            # language.json is regenerated
            doc = json.loads(t.app.paths.language_json("nst").read_text())
            self.assertEqual(doc["identity"]["exonyms"], ["Rangpan people"])

    def test_local_language(self):
        with TempHome() as t:
            p = t.app.language_service.create_local("Made Up Tongue")
            self.assertEqual(p.identifier_type, "local")
            self.assertTrue(p.id.startswith("x-"))
            self.assertIsNone(p.iso639_3)
            res = t.app.language_service.resolve("made up tongue")
            self.assertEqual(res.best.language_id, p.id)


if __name__ == "__main__":
    unittest.main()
