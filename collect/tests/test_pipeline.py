import os
import stat
import unittest
from pathlib import Path

from aimixe_collect.classification.formats import detect_format
from aimixe_collect.storage.object_store import sha256_file
from helpers import TempHome


class PipelineTests(unittest.TestCase):
    def test_import_copy_preserves_original_and_indexes(self):
        with TempHome() as t:
            p = t.tangsa()
            src = t.docs / "Tangsa_grammar_sketch.txt"
            res = t.app.import_service.run(p, src)
            self.assertEqual([o.status for o in res.outcomes], ["stored"])
            o = res.outcomes[0]
            self.assertEqual(o.relevance, 100)
            self.assertIn("grammar", o.types)
            self.assertTrue(src.exists(), "copy mode must leave the original in place")
            stored = Path(o.message)
            self.assertTrue(stored.exists())
            self.assertEqual(sha256_file(stored), o.sha256)
            self.assertFalse(os.stat(stored).st_mode & stat.S_IWUSR, "stored original is read-only")
            self.assertIn("/resources/text/", str(stored))
            rows = t.app.resources.for_language("nst")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "confirmed")
            s = t.app.collection_service.summary(res.session_id)
            self.assertEqual((s.discovered, s.downloaded, s.duplicates, s.failed), (1, 1, 0, 0))
            self.assertTrue(s.id.startswith("COL-"))

    def test_duplicate_links_source_without_second_file(self):
        with TempHome() as t:
            p = t.tangsa()
            t.app.import_service.run(p, t.docs / "Tangsa_grammar_sketch.txt")
            res = t.app.import_service.run(p, t.docs / "dup_copy.txt")
            self.assertEqual(res.outcomes[0].status, "duplicate_linked")
            files = list(t.app.paths.resources_dir("nst", "text").iterdir())
            self.assertEqual(len(files), 1)
            sources = t.app.resources.sources(res.outcomes[0].resource_id)
            self.assertEqual(len(sources), 2)
            self.assertEqual({s["method"] for s in sources}, {"import"})
            self.assertTrue(all(s["original_path"] for s in sources))

    def test_reference_and_move_modes(self):
        with TempHome() as t:
            p = t.tangsa()
            ref = t.docs / "recipes.txt"
            res = t.app.import_service.run(p, ref, mode="reference")
            self.assertEqual(res.outcomes[0].status, "stored")
            self.assertEqual(Path(res.outcomes[0].message), ref.resolve())
            mv = t.docs / "notes.eaf"
            res = t.app.import_service.run(p, mv, mode="move")
            self.assertFalse(mv.exists())
            self.assertTrue(Path(res.outcomes[0].message).exists())
            self.assertIn("transcription", res.outcomes[0].types)

    def test_offline_scan_uses_profile_terms_and_review_queue(self):
        with TempHome() as t:
            p = t.tangsa()
            terms = [x.text for x in t.app.collection_service.offline_terms(p)]
            self.assertIn("Tangsa", terms)
            self.assertIn("nst", terms)
            self.assertIn("Chamchang", terms)          # a Glottolog dialect name
            # user adds a variety not in any table: local files named after it must now be found
            t.app.profile_service.set_value(p, "orthography_location", "varieties", ["Mossang"])
            res = t.app.collection_service.run_offline(p, [t.docs])
            names = {o.candidate.display: o for o in res.outcomes}
            self.assertIn("Mossang_wordlist.txt", names)
            self.assertIn("Tangsa_grammar_sketch.txt", names)
            self.assertNotIn("recipes.txt", names)
            self.assertIn("Mossang", names["Mossang_wordlist.txt"].candidate.matched_terms)
            self.assertEqual(names["Tangsa_grammar_sketch.txt"].candidate.detection_method, "filename")
            self.assertEqual(res.scan_report.files_seen, 5)
            s = t.app.collection_service.summary(res.session_id)
            self.assertEqual(s.mode, "Offline Collection")
            self.assertEqual(s.discovered, len(res.outcomes))
            for o in res.outcomes:
                src = t.app.resources.sources(o.resource_id)[0]
                self.assertEqual(src["method"], "offline")
                self.assertIsNotNone(src["detection_method"])
                self.assertIsNotNone(src["confidence"])

    def test_low_relevance_offline_hit_goes_to_review(self):
        with TempHome() as t:
            p = t.tangsa()
            # a file that only mentions a place name -> weak/possible -> review, never confirmed
            t.app.profile_service.set_value(p, "orthography_location", "places",
                                            [{"name": "Changlang", "type": "district", "country": "India"}])
            (t.docs / "Changlang_market_prices.csv").write_text("a,b\n")
            res = t.app.collection_service.run_offline(p, [t.docs / "Changlang_market_prices.csv"])
            o = res.outcomes[0]
            self.assertIn(o.status, ("rejected", "uncertain_review"))
            self.assertLess(o.relevance, 70)
            confirmed = [r for r in t.app.resources.for_language("nst") if r["status"] == "confirmed"]
            self.assertEqual(confirmed, [])

    def test_unknown_extension_is_still_stored(self):
        with TempHome() as t:
            p = t.tangsa()
            weird = t.docs / "Tangsa_data.qzx"
            weird.write_bytes(b"\x00\x01\x02binary")
            res = t.app.import_service.run(p, weird)
            self.assertEqual(res.outcomes[0].status, "stored")
            self.assertEqual(detect_format(weird).format, "unknown")
            self.assertIn("/resources/other/", res.outcomes[0].message)

    def test_review_accept_confirms_resource(self):
        with TempHome() as t:
            p = t.tangsa()
            (t.docs / "Rangpan_song.wav").write_bytes(b"RIFF....WAVEfmt ")
            res = t.app.collection_service.run_offline(p, [t.docs / "Rangpan_song.wav"])
            o = res.outcomes[0]
            self.assertEqual(o.status, "uncertain_review")   # alternate name only
            self.assertIn("audio", o.types)
            items = t.app.review_service.pending("nst")
            self.assertEqual(len(items), 1)
            t.app.review_service.accept(items[0])
            self.assertEqual(t.app.resources.language_status(o.resource_id, "nst"), "confirmed")
            self.assertEqual(t.app.review_service.pending("nst"), [])

    def test_profile_field_proposal_needs_review(self):
        with TempHome() as t:
            p = t.tangsa()
            t.app.review_service.propose_profile_field(p, "orthography_location", "varieties", ["Mossang"],
                                                       0.72, "example-document.pdf")
            p = t.app.language_service.load("nst")
            self.assertNotIn("Mossang", p.collected("orthography_location", "varieties"))
            item = t.app.review_service.pending("nst")[0]
            self.assertEqual(item.kind, "profile_field")
            t.app.review_service.accept(item)
            p = t.app.language_service.load("nst")
            self.assertIn("Mossang", p.collected("orthography_location", "varieties"))

    def test_history(self):
        with TempHome() as t:
            p = t.tangsa()
            t.app.import_service.run(p, t.docs / "recipes.txt")
            t.app.collection_service.run_offline(p, [t.docs])
            hist = t.app.history_service.list()
            self.assertEqual(len(hist), 2)
            self.assertEqual({h.mode for h in hist}, {"Import", "Offline Collection"})
            self.assertTrue(t.app.history_service.events(hist[0].id))


if __name__ == "__main__":
    unittest.main()
