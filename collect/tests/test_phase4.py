"""Phase 4: content extraction, archive inspection, content-aware scanning, fuzzy duplicates."""
import json
import re
import tarfile
import unittest
import zipfile
import zlib
from pathlib import Path

from aimixe_collect.classification.formats import detect_format
from aimixe_collect.dedup.fuzzy import similarity, text_signature
from aimixe_collect.extraction.archives import inspect_archive
from aimixe_collect.extraction.pdf import extract_pdf_text
from aimixe_collect.extraction.text import extract_text
from helpers import TempHome


def make_pdf(path: Path, lines: list[str], compress: bool = False) -> None:
    content = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({l}) Tj 0 -14 Td" for l in lines) + " ET"
    stream = content.encode()
    filt = ""
    if compress:
        stream = zlib.compress(stream)
        filt = " /Filter /FlateDecode"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)}{filt} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def make_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')


class ExtractionTests(unittest.TestCase):
    def test_pdf_plain_and_compressed(self):
        with TempHome() as t:
            for compress in (False, True):
                pdf = t.docs / f"tangsa_{compress}.pdf"
                make_pdf(pdf, ["A Grammar of Tangsa", "Chapter 1: Phonology of the Mossang variety"], compress)
                text, info = extract_pdf_text(pdf)
                self.assertIn("Grammar of Tangsa", text)
                self.assertIn("Mossang", text)
                self.assertEqual(info["pages"], 1)
                self.assertIn(info["extractor"], ("builtin", "pdftotext"))

    def test_docx_html_eaf_json(self):
        with TempHome() as t:
            docx = t.docs / "notes.docx"
            make_docx(docx, ["Field notes on Tangsa", "Elicited in Changlang"])
            text, info, _ = extract_text(docx, detect_format(docx))
            self.assertIn("Field notes on Tangsa", text)
            self.assertIn("Changlang", text)
            html = t.docs / "page.html"
            html.write_text("<html><head><title>T</title><script>var x=1</script></head><body><p>Tangsa &amp; Nocte</p></body></html>")
            text, _, _ = extract_text(html, detect_format(html))
            self.assertEqual(text, "Tangsa & Nocte")
            eaf = t.docs / "a.eaf"
            eaf.write_text('<ANNOTATION_DOCUMENT><ANNOTATION_VALUE>nga tangsa</ANNOTATION_VALUE><ANNOTATION_VALUE>hello</ANNOTATION_VALUE></ANNOTATION_DOCUMENT>')
            text, _, _ = extract_text(eaf, detect_format(eaf))
            self.assertEqual(text, "nga tangsa\nhello")
            js = t.docs / "d.json"
            js.write_text(json.dumps({"language": "Tangsa", "entries": [{"form": "nu", "gloss": "water"}]}))
            text, _, _ = extract_text(js, detect_format(js))
            self.assertIn("water", text)

    def test_pipeline_writes_extracted_files_and_uses_contents(self):
        with TempHome() as t:
            p = t.tangsa()
            # a file whose name says nothing, but whose contents are about Tangsa: import it and check derived files
            pdf = t.docs / "scan0042.pdf"
            make_pdf(pdf, ["Tangsa wordlist collected at Changlang", "nu water", "van fire"])
            res = t.app.import_service.run(p, pdf)
            o = res.outcomes[0]
            self.assertEqual(o.status, "stored")
            ex = {e["kind"]: Path(e["path"]) for e in t.app.resources.extractions(o.resource_id)}
            self.assertIn("text", ex)
            self.assertIn("metadata", ex)
            self.assertTrue(ex["text"].exists())
            self.assertIn("Tangsa wordlist", ex["text"].read_text())
            self.assertIn("/extracted/", str(ex["text"]))
            meta = json.loads(ex["metadata"].read_text())
            self.assertEqual(meta["format"], "pdf")
            # contents refined classification: "wordlist" came from the text, not the filename
            types = {r["type"] for r in t.app.conn.execute("SELECT type FROM resource_type WHERE resource_id=?", (o.resource_id,))}
            self.assertIn("wordlist", types)
            # the original is untouched
            self.assertEqual(pdf.read_bytes()[:5], b"%PDF-")

    def test_offline_content_scan_finds_unnamed_files(self):
        with TempHome() as t:
            p = t.tangsa()
            hidden = t.docs / "list3.txt"
            hidden.write_text("Tangsa wordlist, Mossang variety\nnu water\nvan fire\n" * 3)
            res = t.app.collection_service.run_offline(p, [hidden], content_scan=True)
            self.assertEqual(len(res.outcomes), 1)
            o = res.outcomes[0]
            self.assertEqual(o.candidate.detection_method, "content")
            self.assertIn("Tangsa", o.candidate.matched_terms)
            self.assertIn(o.status, ("stored", "uncertain_review"))
            res2 = t.app.collection_service.run_offline(p, [t.docs / "recipes.txt"], content_scan=True)
            self.assertEqual(res2.outcomes, [])
            res3 = t.app.collection_service.run_offline(p, [hidden], content_scan=False)
            self.assertEqual(res3.outcomes, [])


class ArchiveTests(unittest.TestCase):
    def test_inspect_and_ingest_members(self):
        with TempHome() as t:
            p = t.tangsa()
            z = t.docs / "Tangsa_materials.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("dictionary/tangsa_dict.txt", "nu water\nvan fire\n")
                zf.writestr("notes/readme.txt", "collected 2019\n")
                zf.writestr("../evil.txt", "nope")
            members = inspect_archive(z, "zip")
            self.assertEqual(len(members), 3)
            # default: the archive is stored and listed, members are not ingested
            res = t.app.import_service.run(p, z)
            o = res.outcomes[0]
            self.assertEqual(o.status, "stored")
            self.assertIn("archive", o.types)
            meta = {r["key"]: r["value"] for r in t.app.conn.execute(
                "SELECT key, value FROM resource_metadata WHERE resource_id=?", (o.resource_id,))}
            self.assertEqual(meta["archive_members"], "3")
            # opt in: members become resources with provenance pointing into the archive
            t.app.config.values.setdefault("archives", {})["ingest_members"] = True
            tgz = t.docs / "Tangsa_tar.tgz"
            with tarfile.open(tgz, "w:gz") as tf:
                tf.add(t.docs / "Tangsa_grammar_sketch.txt", arcname="grammar/Tangsa_grammar_sketch.txt")
            res = t.app.import_service.run(p, tgz)
            o = res.outcomes[0]
            self.assertIn("1 archive member(s) ingested", o.message)
            rows = t.app.resources.for_language("nst")
            member = [r for r in rows if r["original_name"] == "Tangsa_grammar_sketch.txt"]
            self.assertEqual(len(member), 1)
            src = t.app.resources.sources(member[0]["id"])[0]
            self.assertIn("!grammar/Tangsa_grammar_sketch.txt", src["original_path"])
            self.assertEqual(src["detection_method"], "archive_member")
            self.assertFalse(list(t.app.paths.temp.glob("archive-*")))


class FuzzyTests(unittest.TestCase):
    def test_minhash_similarity(self):
        base = " ".join(f"word{i}" for i in range(400))
        a = text_signature(base)
        b = text_signature(base.replace("word10 ", "word10 extra ").replace("word300", "changed"))
        c = text_signature(" ".join(f"other{i}" for i in range(400)))
        self.assertGreater(similarity(a, b), 0.85)
        self.assertLess(similarity(a, c), 0.05)
        self.assertIsNone(text_signature("too short"))

    def test_near_duplicates_are_linked_not_merged(self):
        with TempHome() as t:
            p = t.tangsa()
            body = "Tangsa wordlist. " + " ".join(f"entry{i} gloss{i}" for i in range(300))
            f1 = t.docs / "Tangsa_list_v1.txt"
            f2 = t.docs / "Tangsa_list_v2.txt"
            f1.write_text(body)
            f2.write_text(body + " one more line")
            r1 = t.app.import_service.run(p, f1).outcomes[0]
            r2 = t.app.import_service.run(p, f2).outcomes[0]
            self.assertEqual(r1.status, "stored")
            self.assertEqual(r2.status, "stored")            # different bytes: not an exact duplicate
            self.assertIn("near-duplicate of", r2.message)
            nd = t.app.resources.near_duplicates(r2.resource_id)
            self.assertEqual(nd[0]["other_id"], r1.resource_id)
            self.assertGreater(nd[0]["similarity"], 0.85)
            self.assertEqual(len(t.app.resources.near_duplicates(r1.resource_id)), 1)   # symmetric
            files = list(t.app.paths.resources_dir("nst", "text").iterdir())
            self.assertEqual(len(files), 2)                  # both originals kept


if __name__ == "__main__":
    unittest.main()
