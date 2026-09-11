# AImixE Data Collection Module

Terminal-first, UI-ready collection of language resources. Standalone: Python 3.11+
standard library only, no third-party packages. The plan is in `PLAN.md`.

## Install

Python 3.11 or newer. No third-party packages.

If Python is missing: Linux `sudo apt install python3` (or your distribution's equivalent);
macOS type `python3` in Terminal and accept the command-line tools prompt, or `brew install
python`; Windows use the installer from python.org and tick "Add python.exe to PATH". Check
with `python3 --version` (Windows: `python --version`).

- **Without installing** (Linux, macOS): use `bin/aimixe` as below.
- **Any OS, including Windows**: `pip install .` from this folder puts an `aimixe` command on
  your PATH, so `aimixe collect` works in PowerShell, cmd, or any shell. Alternatively run
  `python -m aimixe_collect ...` with `src` on `PYTHONPATH`.
- Optional: `pdftotext` (poppler) improves PDF text extraction and is used when found.
- **Windows without Python**: `python3 tools/build_windows_bundle.py` builds a portable zip
  (Python's embeddable distribution plus this module). Unzip, double-click `aimixe-ui.cmd`
  or run `aimixe collect` from a terminal in that folder. Built without a Windows machine,
  so untested until someone runs it there.

## Run

```bash
bin/aimixe collect                       # interactive workflow
bin/aimixe collect nst                   # start with a language
bin/aimixe collect nst --profile         # language profile menu
bin/aimixe collect nst --offline         # offline collection (asks for folders)
bin/aimixe collect nst --scan ~/Documents
bin/aimixe collect nst --import ~/linguistic-data
bin/aimixe collect nst --online          # online collection menu
bin/aimixe collect nst --catalogue --yes # catalogue search, non-interactive
bin/aimixe collect nst --agent --yes     # agent search, non-interactive
bin/aimixe collect catalogue list | add [--file x.toml] | remove <name>
bin/aimixe collect import dictionary.pdf [-l nst] [--mode copy|move|reference]
bin/aimixe collect history [COL-20260911-001]
bin/aimixe collect review
bin/aimixe collect resume COL-20260911-001
bin/aimixe collect ui [--port 8765] [--no-browser]   # local web interface, same services
```

Data lives in `~/.aimixe/` (override with `AIMIXE_HOME` or `--home DIR`):

```
~/.aimixe/
├── config/config.toml
├── catalogues/
├── database/aimixe.db            authoritative metadata index
├── languages/<id>/
│   ├── language.json             profile with per-value provenance
│   ├── resources/<category>/     originals, write-once, read-only
│   ├── extracted/  metadata/  manifests/
├── cache/  temp/  logs/
```

## Tests

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests -v
```

## Layout

`src/aimixe_collect/cli/` is presentation only. Everything else is reachable through
`services/app.py` (`App`) so a graphical interface can reuse it unchanged:
`language/` (resolution), `profile/` (schema, model, enrichment), `discovery/`,
`catalogues/`, `agent/`, `relevance/`, `ingestion/` (the shared pipeline),
`classification/`, `dedup/`, `extraction/`, `storage/`, `db/`, `sessions/`, `review/`.

Bundled data in `src/aimixe_collect/data/`: ISO 639-3 tables, ISO 15924, ISO 3166 country
names, and a Glottolog 5.3 / CLDR extract (CC-BY-4.0, see `reference-SOURCES.md`).

## Limitations

- OLAC, ELAR, PARADISEC and Pangloss have no machine-readable search the module can use, so
  they are "lookup" providers: you get a URL to open, nothing is fetched.
- The built-in PDF text extractor handles plainly encoded PDFs; scanned or CID-encoded PDFs
  yield little text (reported as low quality). Install `pdftotext` for better results.
- Fuzzy duplicate detection covers text. Image and audio fingerprints are declared hooks and
  are not computed (no decoders in the standard library).
- Relevance scoring is heuristic. Uncertain results go to the review queue; names shared by
  many languages ("Zhuang", "Naga") count as weak evidence on purpose.
- Web search without API keys depends on DuckDuckGo's HTML page, Bing's RSS feed and the
  Wikipedia API. DuckDuckGo sometimes answers with a bot check; the run reports it and the
  other backends carry on. A keyed search API can be configured under `[agent.search_api]`.
- The web interface has no login; it binds to 127.0.0.1 only.
- Tested on Linux. macOS should behave the same; on Windows use the `pip install` route
  (the `bin/aimixe` script is a Unix shell script). Not yet verified on Windows.

## Exit codes

0 success · 10 own check failed · 20 not evaluable (feature not in this build) · 40 invalid
input · 50 configuration · 70 internal.

## Phase status

- Phase 1 (this build): interactive workflow, language resolver, profile with progressive
  questioning and provenance, local registry, storage, SQLite, import, offline scan,
  SHA-256 deduplication, sessions, history, review queue.
- Phase 2 (this build): catalogue provider architecture, Online Collection → Catalogue
  Search, `catalogue add|list|remove`, online provenance. Built-in providers: Glottolog,
  Zenodo, Internet Archive and Kaipuleohone (DSpace) query real APIs; OLAC, ELAR, PARADISEC
  and Pangloss are honest "lookup" providers that hand you a URL because they offer no
  machine-readable search. Custom providers are TOML files (`lookup`, `api_json`,
  `html_links`); a university DSpace repository is the built-in `dspace` class with another
  `base` URL. Catalogue-asserted language facts (family, parent grouping, dialects,
  glottocode) go to the review queue, never straight into the profile.
- Phase 3 (this build): Agent Search. `AgentProvider` interface (`analyze`, `classify`,
  `generate_search_queries`, `enrich_language_profile`) with `RuleBasedAgent` (no model,
  offline) and `CliAgent` (any command-line model tool from `data/agents.toml`: claude,
  codex, gemini, agy, qwen, ollama, llm, or a custom command; answers are combined with the
  rule-based baseline and a failing tool degrades gracefully). Web search backends without
  API keys: DuckDuckGo, Bing RSS, Wikipedia, plus a configurable keyed JSON API. The
  orchestrator follows the fifteen steps of the specification: queries from every profile
  field, bounded page following (robots.txt, depth, per-host and file caps), downloadable
  and repository links (Zenodo, Internet Archive, GitHub), relevance before download,
  learning during the session (a variety found on a page produces new queries in the next
  round and sharpens relevance scoring) and profile facts proposed to the review queue with
  the supporting quote. Configure under `[agent]` in `config.toml`.
- Phase 4 (this build): content extraction as the pipeline's last stage, writing
  `text.txt`, `metadata.json` and `pages.json` under `extracted/<id>/` for text, HTML, XML
  annotation formats (ELAN, FLEx, LIFT, TextGrid, TEI, CoNLL), Office/OpenDocument/EPUB and
  PDF (built-in extractor; `pdftotext` is used and recorded when installed). Extracted text
  feeds relevance scoring and classification. Archives are listed; members are ingested as
  resources of their own when `[archives] ingest_members = true`, with provenance
  `archive!member`. Offline Collection also looks inside text-bearing files (`[scan]
  content`) so a file whose name says nothing is still found. Fuzzy duplicate detection
  links near-identical text resources (MinHash, `[dedup] threshold`) without merging or
  deleting anything; image and audio fingerprints are declared hooks that state why they
  are not computed.
- Phase 5 (this build): a local web interface, `aimixe collect ui`. A standard-library
  HTTP server bound to 127.0.0.1 serves one page whose JSON API calls the same `services/`
  as the CLI: find/confirm a language, the grouped profile with per-value provenance and
  editing, Catalogue Search (search → choose a minimum relevance → download), Agent Search
  (edit the planned queries → run with a live log), Offline Collection, Import, the existing
  collection with resource detail (provenance, extracted files, near-duplicates), the review
  queue, history and catalogue management. Long runs are background jobs the page polls.
  No authentication: it is meant for the local machine; use SSH port forwarding for a remote one.

## Licence

MIT (see the repository's `LICENSE`; data terms in `THIRD_PARTY_DATA.md`). The bundled language data under `src/aimixe_collect/data/` keeps its own terms; see `data/REGISTRIES.md` and `data/reference-SOURCES.md`.
