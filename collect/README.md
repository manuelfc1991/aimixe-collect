# AImixE Data Collection Module

Terminal-first, UI-ready collection of language resources. Standalone: Python 3.11+
standard library only, no third-party packages. The plan is in `PLAN.md`.

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
