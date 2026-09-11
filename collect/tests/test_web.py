"""Web interface: the JSON API over the services, and the HTTP server end to end."""
import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from aimixe_collect.web.api import Api, ApiError
from aimixe_collect.web.jobs import JobManager
from aimixe_collect.web.server import make_handler
from helpers import TempHome


def wait_job(api, job_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = api.handle("GET", f"/api/jobs/{job_id}", {}, {})
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


class ApiTests(unittest.TestCase):
    def test_workflow_through_api(self):
        with TempHome() as t:
            api = Api(t.home, JobManager())
            st = api.handle("GET", "/api/status", {}, {})
            self.assertIn("catalogues", st)
            self.assertEqual(st["languages"], [])
            # §1 resolve + confirm
            res = api.handle("GET", "/api/resolve", {"q": "Tangsa"}, {})
            self.assertEqual(res["status"], "exact")
            self.assertEqual(res["matches"][0]["iso639_3"], "nst")
            opened = api.handle("POST", "/api/languages/open", {}, {"query": "Tangsa", "index": 0})
            self.assertEqual(opened["language_id"], "nst")
            self.assertTrue(opened["created"])
            # §2 profile: schema, status, set a value from a web form
            sch = api.handle("GET", "/api/schema", {}, {})
            self.assertEqual([g["name"] for g in sch["groups"]],
                             ["identity", "orthography_location", "resources", "community_status", "translation_publication"])
            lang = api.handle("GET", "/api/languages/nst", {}, {})
            self.assertEqual(lang["profile"]["name"], "Tangsa")
            self.assertIn(("orthography_location", "orthography_status"), [tuple(x) for x in lang["status"]["to_ask"]])
            api.handle("POST", "/api/languages/nst/profile", {}, {"group": "resources", "field": "recordings",
                                                                  "form": {"state": "yes", "detail": "ELAR deposit"}})
            api.handle("POST", "/api/languages/nst/profile", {}, {"group": "orthography_location", "field": "places",
                                                                  "form": {"value": "Changlang, district, Arunachal Pradesh, India"}})
            api.handle("POST", "/api/languages/nst/profile", {}, {"group": "community_status", "field": "speakers_basis",
                                                                  "form": {"type": "census", "year": "2011", "source": "Census of India"}})
            lang = api.handle("GET", "/api/languages/nst", {}, {})
            self.assertEqual(lang["profile"]["resources"]["recordings"], {"state": "yes", "detail": "ELAR deposit"})
            self.assertEqual(lang["profile"]["orthography_location"]["places"][0]["type"], "district")
            self.assertEqual(lang["profile"]["community_status"]["speakers_basis"]["year"], 2011)
            self.assertEqual(lang["profile"]["provenance"]["resources"]["recordings"][0]["source_type"], "user")
            with self.assertRaises(ApiError):
                api.handle("POST", "/api/languages/nst/profile", {}, {"group": "identity", "field": "nope", "form": {}})
            # §9 import as a job
            job = api.handle("POST", "/api/jobs", {}, {"kind": "import", "language_id": "nst",
                                                       "params": {"path": str(t.docs / "Tangsa_grammar_sketch.txt")}})
            j = wait_job(api, job["job_id"])
            self.assertEqual(j["status"], "finished", j.get("error"))
            self.assertEqual(j["result"]["outcomes"][0]["status"], "stored")
            self.assertEqual(j["result"]["session"]["mode"], "Import")
            # §8 offline scan as a job
            job = api.handle("POST", "/api/jobs", {}, {"kind": "offline", "language_id": "nst",
                                                       "params": {"roots": [str(t.docs)], "content": False}})
            j = wait_job(api, job["job_id"])
            self.assertEqual(j["status"], "finished", j.get("error"))
            self.assertGreaterEqual(j["result"]["scan"]["hits"], 2)
            self.assertTrue(any("duplicate" in line for line in j["log"]))
            # collection, resource detail, history, review
            rs = api.handle("GET", "/api/languages/nst/resources", {}, {})
            self.assertGreaterEqual(len(rs["resources"]), 2)
            rid = rs["resources"][0]["id"]
            detail = api.handle("GET", f"/api/resources/{rid}", {}, {})
            self.assertTrue(detail["sources"])
            hist = api.handle("GET", "/api/history", {"language": "nst"}, {})
            self.assertEqual({s["mode"] for s in hist["sessions"]}, {"Import", "Offline Collection"})
            sess = api.handle("GET", f"/api/sessions/{hist['sessions'][0]['id']}", {}, {})
            self.assertTrue(sess["events"])
            review = api.handle("GET", "/api/review", {"language": "nst"}, {})
            if review["items"]:
                item = review["items"][0]
                api.handle("POST", f"/api/review/{item['id']}/accept", {}, {})
                self.assertNotIn(item["id"], [i["id"] for i in api.handle("GET", "/api/review", {}, {})["items"]])
            # catalogues management
            api.handle("POST", "/api/catalogues", {}, {"name": "uni", "kind": "lookup", "url": "https://u.example/{q}", "what": "x"})
            self.assertIn("uni", [c["name"] for c in api.handle("GET", "/api/catalogues", {}, {})["catalogues"]])
            api.handle("DELETE", "/api/catalogues/uni", {}, {})
            with self.assertRaises(ApiError):
                api.handle("DELETE", "/api/catalogues/uni", {}, {})
            # home page data: state, next step, last collection
            home = api.handle("GET", "/api/home", {}, {})
            card = home["languages"][0]
            self.assertEqual(card["id"], "nst")
            self.assertGreaterEqual(card["resources"], 2)
            self.assertEqual(card["last_session"]["mode"], "Offline Collection")
            self.assertTrue(card["next_step"])
            self.assertIn("version", api.handle("GET", "/api/status", {}, {}))
            # agent plan (no network; planning only)
            plan = api.handle("GET", "/api/languages/nst/agent/plan", {}, {})
            self.assertTrue(plan["queries"])
            with self.assertRaises(ApiError):
                api.handle("GET", "/api/nothing", {}, {})

    def test_create_local_language(self):
        with TempHome() as t:
            api = Api(t.home, JobManager())
            r = api.handle("POST", "/api/languages/create", {}, {"name": "Made Up", "code": "zzz9"})
            self.assertTrue(r["language_id"].startswith("x-"))
            lang = api.handle("GET", f"/api/languages/{r['language_id']}", {}, {})
            self.assertEqual(lang["profile"]["identifier_type"], "local")


class ServerTests(unittest.TestCase):
    def test_http_end_to_end(self):
        with TempHome() as t:
            api = Api(t.home, JobManager())
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
            port = server.server_address[1]
            th = threading.Thread(target=server.serve_forever, daemon=True)
            th.start()
            try:
                base = f"http://127.0.0.1:{port}"
                html = urllib.request.urlopen(base + "/").read().decode()
                self.assertIn("Enter language name or ISO 639-3 code", html)
                js = urllib.request.urlopen(base + "/app.js").read().decode()
                self.assertIn("Language detected", js)
                for item in ("1. Online Collection", "Catalogue Search", "Agent Search", "Offline Collection",
                             "Import Files / Folder", "View Existing Collection", "Review Queue"):
                    self.assertTrue(item.split(". ")[-1] in html or item.split(". ")[-1] in js, item)
                data = json.loads(urllib.request.urlopen(base + "/api/resolve?q=nst").read())
                self.assertEqual(data["matches"][0]["language_id"], "nst")
                req = urllib.request.Request(base + "/api/languages/open", data=json.dumps({"query": "nst", "index": 0}).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
                self.assertEqual(json.loads(urllib.request.urlopen(req).read())["language_id"], "nst")
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(base + "/api/languages/zzz")
                self.assertEqual(cm.exception.code, 404)
                self.assertEqual(json.loads(cm.exception.read())["error"], "no language zzz")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
