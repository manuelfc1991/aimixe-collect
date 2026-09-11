# AImixE Data Collection Module — Implementation Plan

Date: 2026-09-11
Location: `/home/work/AIMIXE_CODES/aimixe-ours/collect/`
Status: **plan only, awaiting approval. No code written.**

This plan follows the specification section by section. Nothing in the specification is
dropped, merged away, or replaced. Where the specification says "may", "suggested" or
"the exact schema may be improved", this plan states the concrete choice and marks it
`[choice]` so it can be overruled before building starts.

---

## 0. Ground rules for this build

| Rule | Decision |
|---|---|
| Standalone | New package in this directory. **No code import from** `reference/`, `aimixe-tools-with-*`, or anything outside this folder. |
| Data reuse only | Copy bundled **data files** (ISO 639-3 tables, ISO 15924 table, Glottolog-derived `reference.csv`, their provenance/licence notes) into this package. Nothing else is copied. |
| Runtime | Python 3.11+ (3.14.4 installed), standard library only. SQLite via `sqlite3`, config via `tomllib`, HTTP via `urllib`. `[choice]` — matches the house style and avoids pip. |
| Interface separation | `cli/` holds prompts, menus, printing only. Everything else lives in `services/` and below, callable by a future UI without change. |
| Never modify originals | Originals are stored write-once; derived content goes to `extracted/`. |
| Provenance everywhere | Every profile value and every resource carries source, method, date, confidence. |

### Data files to copy (with their licence/provenance notes)

From `aimixe-tools-with-claude/new_tools/survey/src/aimixe_survey/data/` and
`.../new_tools/collect/src/aimixe_collect/data/` (identical ISO files in both):

| File | Size | Used for |
|---|---|---|
| `iso-639-3.tab` | 178 KB | Code → reference name, scope, type |
| `iso-639-3_Name_Index.tab` | 205 KB | Every name a code is listed under (alternative names) |
| `iso-639-3_Retirements.tab` | 19 KB | Retired codes and their replacements |
| `iso-639-3-macrolanguages.tab` | 4.6 KB | Macrolanguage ↔ member mapping (feeds `parent`) |
| `iso15924.txt` | 14 KB | Script codes and names |
| `reference.csv` | 2.1 MB, 8,083 rows | Glottolog 5.3 + CLDR: family, classification, macroarea, countries, dialects, alternative names, likely script, endangerment, documentation level |
| `REGISTRIES.md`, `reference-SOURCES.md`, `reference-meta.json` | small | Provenance, sha256, licences (CC-BY-4.0 attribution for Glottolog) |

Verified: `Tangsa` → `nst` (via `reference.csv` names) and `njb` → Nocte Naga both resolve offline.

`catalogues.toml` and `agents.toml` from the other trees are **not** copied as-is; the
formats are noted in §4 and §20 as prior art, and this module defines its own.

---

## 1. Main Workflow — `aimixe collect`

Entry point: `bin/aimixe` (sh launcher) → `python3 -m aimixe_collect` → `cli.main()`.
`aimixe collect` with no arguments starts the interactive workflow.

Step 1 prompt, exactly:

```text
Enter language name or ISO 639-3 code:
>
```

Accepted input, resolved in this order by `LanguageResolver`:

1. ISO 639-3 code (exact, case-insensitive; retired codes report their replacement)
2. Language name (reference name in `iso-639-3.tab`)
3. Known alternative name (`iso-639-3_Name_Index.tab` + `reference.csv` `names`)
4. Known dialect/language alias (`reference.csv` `dialects`)
5. Names in the **local language registry** (profiles already stored in `~/.aimixe/languages/*/language.json`, including user-added aliases and varieties)

Matching uses Unicode NFKD folding (case and diacritic insensitive). Local registry is
searched first, as the spec requires; bundled tables next.

Outcomes:

- **One confident match** → show the detected-language block and confirm:

  ```text
  Language detected

  Name: Tangsa
  ISO 639-3: nst
  Alternative names: Tangshang, Tase
  Region: India / Myanmar

  Continue with this language? [Y/n]
  ```

- **Several candidates** → numbered list to pick from, plus "none of these".
- **No confident match** → start the language-identification and profile-enrichment step
  (§2). The user may proceed with a local identifier when no ISO code exists
  (`x-<slug>`, clearly labelled as local, never presented as ISO). `[choice]`

Rule: the system collects missing information **progressively**; it never forces every
field. It asks only fields that are missing, uncertain, contradictory, or required for
reliable identification and collection.

---

## 2. Language Profile Enrichment

### 2.0 Progress display

Sections shown with `✓` done, `●` current, `○` pending, exactly as specified:

```text
Language Profile

✓ Basic identification
● Names and classification
○ Location and varieties
○ Resources
○ Community
○ Translation and publication
```

Each section is one screen with its `Language Profile – <Section>` heading. Every field
prompt can be answered, left blank (skipped), or given `?` for help. `[choice]` on `?`.

### 2.1 Names and Classification (`identity`)

Fields: `family`, `alternate_names`, `exonyms`, `notes`, `parent`, `scripts`.
Multi-value fields: `alternate_names`, `exonyms`, `scripts` (comma or `;` separated input,
stored as lists). `parent` is flexible free text plus optional `type`
(parent language / dialect group / macrolanguage / subgroup / broader grouping); never
forced. Scripts entered by name or ISO 15924 code are normalised to `{code, name}` while
keeping the user's original text.

### 2.2 Orthography, Varieties and Location (`orthography_location`)

Fields: `orthography_status`, `literacy`, `varieties`, `region`, `places`, `other_languages`.

- `orthography_status`: suggested values `standardized, partially_standardized,
  community_orthography, experimental, multiple_orthographies, unwritten, unknown`;
  free text also accepted and stored verbatim alongside the nearest suggested value.
- `varieties`: list.
- `places`: list of `{name, type, region, country}`; typed one place per line, with
  `type` and `country` prompted only if not inferable. Region and country pre-filled from
  `reference.csv` `countries`/`macroarea` where available (provenance `local_database`).
- `other_languages`: list; each entry may carry a role tag (lingua franca, regional,
  national, neighbouring, education, religion, trade) when the user gives one.

### 2.3 Existing Language Resources (`resources`)

Fields: `resources` (summary), `written`, `recordings`, `studies`, `digital`, `speakers`.

Availability fields accept the states `yes, no, unknown, limited, reported, historical`
(plus free text). Stored as `{state, detail}` so a boolean is never forced.
`speakers` accepts an integer or a range/approximation (`~8500`, `8000-9000`).

**Feeds discovery**: if `recordings` is `yes/limited/reported`, the query planner adds
the recordings query family (`"<language>" recordings`, `audio archive`,
`documentation audio`, `ELAR`, `PARADISEC`); same pattern for `written` (dictionary,
primer, grammar), `studies` (grammar, thesis, phonology), `digital` (corpus, dataset,
software, keyboard, font).

### 2.4 Speaker Information and Community Status (`community_status`)

Fields: `speakers_basis`, `transmission`, `age_spread`, `used`, `displaced`, `community`.

- `speakers_basis`: `{type, year, source}`; type from `census, academic study,
  community estimate, government report, fieldwork, Ethnologue, Glottolog, unknown` or free text.
- `transmission`: `strong, ongoing, declining, limited, not_transmitted, unknown` + free text detail.
- `age_spread`: `{children, young_adults, adults, elderly}` each `true/false/unknown`,
  plus an optional descriptive note.
- `used`: list from `home, community, education, religion, ceremonies, media, government,
  market, workplace, literature, digital communication` + free additions.
- `displaced`: `yes, no, partial, historical, unknown`; never assumed.
- `community`: structured free text with optional sub-lists: community names,
  self-identification, organisations, language committees, cultural organisations,
  educational initiatives, documentation initiatives, institutions.

### 2.5 Translation and Publication (`translation_publication`)

Fields: `translation`, `publication`. Each is a list of entries `{kind, title, date,
organisation, url, note}` where only `kind` or a free description is required.
Translation kinds listed in the spec (Bible, religious, government, educational,
literature, health, dictionaries, websites, subtitles, parallel text); publication kinds
(books, primers, textbooks, newspapers, magazines, community, academic, dictionaries,
grammar books). Known titles feed Catalogue and Agent Search as exact-title queries.

### 2.6 Progressive Questioning

Before asking anything, compute known vs missing per field from the stored profile plus
what the bundled data supplies. Show:

```text
Language profile found.

Known:
✓ Family
✓ Alternative names
✓ Region
✓ Script

Missing:
- Orthography status
- ...

Complete missing profile information? [Y/n]
```

Then the four-way menu exactly as specified:

```text
1. Complete missing information
2. Review existing profile
3. Edit profile
4. Skip and continue collection
```

A field is re-asked only if missing, marked uncertain (confidence below threshold,
default 0.6 `[choice]`), contradictory (multiple disagreeing values), or the user chose
Edit. Bundled-data values are pre-filled with provenance `local_database` and shown as
"known", never silently accepted as user-confirmed.

### 2.7 Question Groups

Defined once, as data, in `profile/schema.py` (and mirrored in `data/profile-groups.toml`
for the future UI):

```text
identity:                 family alternate_names exonyms notes parent scripts
orthography_location:     orthography_status literacy varieties region places other_languages
resources:                resources written recordings studies digital speakers
community_status:         speakers_basis transmission age_spread used displaced community
translation_publication:  translation publication
```

Each field entry carries: label, prompt text, help text, value type (text / list /
structured / state), suggested values, multi-valued flag, and which discovery signals it
feeds. The CLI renders from this table; a UI can render from the same table.

### 2.8 Language Profile Data Model

`language.json` per language, matching the spec's shape, with two additions that do not
remove anything: a `schema_version` and a per-field provenance envelope (§2.9).

```json
{
  "schema_version": 1,
  "id": "nst",
  "name": "Tangsa",
  "iso639_3": "nst",
  "identity": {...}, "orthography_location": {...}, "resources": {...},
  "community_status": {...}, "translation_publication": {...}
}
```

Growth without redesign: profile fields are stored in SQLite as rows in a
`profile_value` table keyed by `(language_id, group, field, value_index)` with a JSON
value column, not as one column per field. Adding a field is a schema-table entry, not a
migration. `language.json` is regenerated from the database (the database is authoritative).

### 2.9 Field Provenance

Every stored value is an envelope:

```json
{ "value": 8500, "source_type": "census", "source": "Census of India",
  "year": 2011, "confidence": 0.9, "recorded_at": "...", "session_id": "..." }
```

`source_type` ∈ `user, local_database, catalogue, agent, academic_source,
government_source, community_source, inferred, unknown`.

Disagreement is preserved: a field may hold several envelopes; one may be marked
`preferred` by the user, none is deleted. Review/Edit shows all of them.

---

## 3. Collection Modes

After identification and profile step, show exactly:

```text
Data Collection

Language: Tangsa [nst]

1. Online Collection
2. Offline Collection
3. Import Files / Folder
4. View Existing Collection
5. Language Profile
6. Exit

Select:
>
```

Three collection mechanisms in the core: online, offline system discovery, direct import.
"View Existing Collection" lists stored resources with type, format, relevance, source.
"Language Profile" re-enters §2 menus.

---

## 4. Online Collection

```text
Online Collection

1. Catalogue Search
2. Agent Search
3. Back
```

### 4.1 Catalogue Search — provider architecture

Abstract base `CatalogueProvider` in `catalogues/base.py`:

```python
class CatalogueProvider:
    name: str
    def search(self, language_profile) -> list[CandidateResource]: ...
    def fetch(self, result) -> FetchedResult: ...
    def extract_metadata(self, result) -> ResourceMetadata: ...
    def download(self, resource, dest) -> DownloadResult: ...
```

Providers receive the **complete profile** and may use ISO code, name, alternative
names, exonyms, varieties, region, places, family, parent, scripts, community names,
known publications, known translations.

Provider registry: built-in providers discovered by class registration; user providers
from `~/.aimixe/catalogues/*.toml`. A TOML-configured provider is a `ConfigurableProvider`
with `kind = "api" | "oai_pmh" | "url_template"` , URL template with placeholders
(`{code} {name} {alt_names} {variety} ...`), response format, and result field mapping.

Built-in providers planned (Phase 2, each a separate file, each optional and skippable
when offline or when the provider needs a code the language lacks):
OLAC (OAI-PMH), Glottolog (JSON API), ELAR, PARADISEC, Kaipuleohone, Pangloss, Zenodo
(REST), Internet Archive (advanced-search API), generic university repository (OAI-PMH),
generic dictionary/corpus repository, custom URL/API. Providers that only support
building a URL (no fetchable API) return `lookup` candidates carrying the URL for review,
never fabricated contents.

Commands:

```bash
aimixe collect catalogue add
aimixe collect catalogue list
aimixe collect catalogue remove
```

`catalogue add` is guided (name, kind, base URL, placeholders, format, licence note) and
writes one TOML file.

---

## 5. Catalogue Discovery — resource coverage

Candidate resources carry `format` and `resource_type` separately (§14). The candidate
model and classifier vocabulary covers the full list in the spec: dictionaries, word
lists, lexicons, grammars, grammar sketches, descriptive documents, phonology,
orthography, morphology, syntax, corpora, parallel corpora, transcriptions, interlinear
glossed text, elicitation materials, narratives, stories, books, papers, theses, articles,
documentation, field notes, metadata, audio, video, images, maps, fonts, keyboard layouts,
scripts, software, datasets, archives, ZIP/TAR packages. Non-text is first-class.

---

## 6. Agent Search

`agent/search.py` orchestrates a session using an `AgentProvider` (§20) plus
non-LLM tooling (HTTP fetch, HTML link extraction). Steps map 1:1 to the spec:

| # | Spec step | Implementation |
|---|---|---|
| 1 | Understand profile | Build `SearchContext` from the full profile |
| 2 | Generate queries | `QueryPlanner`: rule-based templates over every profile field + `AgentProvider.generate_search_queries()` |
| 3 | Search public web/repos | `WebSearchBackend` interface; implementations: agent-CLI-backed search, configurable search API. Provider-independent |
| 4 | Follow relevant pages | Bounded crawler (depth, per-host limits, robots.txt respected) |
| 5 | Discover downloadable resources | Link extraction by extension/content-type/`Content-Disposition` |
| 6 | Discover datasets/archives | Same, plus known repository URL patterns |
| 7 | Identify metadata | HTML meta, Dublin Core, OAI headers, PDF info, file headers |
| 8 | Language relation check | §7 relevance engine |
| 9 | Estimate relevance | §7 score 0–100 |
| 10 | Detect duplicates | URL normalisation + SHA-256 after download (§13) |
| 11 | Download allowed resources | Respect robots/licence; size cap configurable |
| 12 | Store source URL | Provenance record |
| 13 | Store discovery metadata | Query, page chain, date |
| 14 | Classify | §14 classifier |
| 15 | Learn and re-query | `SessionKnowledge`: new varieties/names/places found → new queries in the same session; **proposed** to the profile via the review queue (§18), never written directly |

Example flow honoured: discovering "Mossang is a Tangsa variety" generates
`Mossang dictionary`, `Mossang language documentation`, `Mossang Tangsa corpus`.

---

## 7. Resource Relevance Detection

`relevance/scorer.py`, deterministic and explainable. Each signal yields a weighted
contribution and a human-readable reason. Signals: ISO code match, exact name, alternate
name, exonym, variety, geographic, community, family, parent, script, metadata language
field, document contents, catalogue classification, known publication, known translation.
An `AgentProvider.analyze()` opinion may add a bounded adjustment `[choice]`, recorded as
its own signal.

Score 0–100 mapped to the spec's bands: 90–100 very high, 70–89 high, 50–69 possible,
30–49 weak, 0–29 unrelated. Resources ≥ 70 are stored as `confirmed`; 30–69 stored as
`uncertain` and queued for review; < 30 recorded as rejected candidates (URL and reason
only, no download) `[choice]`. All thresholds configurable.

---

## 8. Offline Collection

`discovery/offline.py` scans user-chosen roots (default prompt; `--scan <path>` in CLI).
Matching terms derived from the profile: name, ISO code, alternate names, exonyms,
varieties, community names, places, known titles, authors, organisations. Matched
against file names, folder names, and (Phase 4) file contents/metadata. Every hit becomes
a candidate with `detection_method` (filename / path / metadata / content), `confidence`,
`original_path`, `scan_date`, then flows through the shared pipeline (§10). Nothing is
moved or altered on the user's disk; storage mode defaults to Copy.

---

## 9. Direct Import

```bash
aimixe collect import /path/to/folder
aimixe collect import dictionary.pdf
```

Steps: hash (SHA-256), duplicate check, file type detection (extension + magic bytes),
metadata extraction, classification, association with the selected language, preserve
original, record original location, ingestion record. Modes `copy | move | reference`,
default `copy`. Folders are walked recursively; each file is one candidate.

---

## 10. Shared Ingestion Pipeline

One class, `ingestion/pipeline.py: IngestionPipeline.run(candidate, session)`, used by
all four discovery mechanisms. Stages, in order, each a separate module with a single
function so they are testable and swappable:

```text
Discovery → Candidate Resource → Language Relevance Detection → Validation →
Metadata Extraction → SHA-256 Hash → Duplicate Detection → Resource Classification →
Provenance Recording → Storage → Database Index → Optional Content Extraction
```

Only the discovery mechanism differs. Pipeline returns a typed outcome:
`stored | duplicate_linked | uncertain_review | rejected | failed`, which sessions count.

---

## 11. Storage Architecture

Root `~/.aimixe/` (override via `AIMIXE_HOME` `[choice]`), layout exactly as specified:

```text
~/.aimixe/
├── config/            config.toml
├── catalogues/        user catalogue provider TOML files
├── database/aimixe.db
├── languages/<id>/
│   ├── language.json
│   ├── resources/{documents,text,dictionaries,corpora,audio,video,images,archives,other}/
│   ├── extracted/
│   ├── metadata/
│   └── manifests/
├── cache/
├── temp/
└── logs/
```

Files stored under `resources/<category>/<sha256-prefix>-<safe-original-name>`; written to
`temp/` first, fsync, atomic rename, read-only mode. The database is the authoritative
metadata index; `language.json` and `manifests/` are regenerated projections.

### SQLite schema (initial, `[choice]` on names)

| Table | Purpose |
|---|---|
| `language` | id, name, iso639_3, identifier_type (iso/local), created/updated |
| `profile_value` | language_id, group, field, idx, value_json, source_type, source, year, confidence, preferred, session_id, recorded_at |
| `resource` | id, sha256, size, format, mime, stored_path, storage_mode, created_at |
| `resource_language` | resource_id, language_id, relevance_score, band, status (confirmed/uncertain/rejected), reasons_json |
| `resource_type` | resource_id, type, confidence, source (rule/agent/user) — multi-tag |
| `resource_source` | resource_id, session_id, method (catalogue/agent/offline/import), source_url, catalogue, resource_url, query, discovery_date, download_date, licence, original_path, detection_method, confidence, import_method |
| `resource_metadata` | resource_id, key, value, extracted_by |
| `extraction` | resource_id, kind, path, created_at |
| `session` | id (COL-YYYYMMDD-NNN), language_id, mode, started, finished, counters (discovered, relevant, downloaded, duplicates, failed, pending_review), status |
| `session_event` | session_id, ts, level, message, data_json — append-only |
| `review_item` | id, kind (resource/profile_field), payload_json, confidence, source_ref, status (pending/accepted/rejected/skipped), decided_at, decided_by |
| `catalogue_provider` | name, path, enabled, added_at |
| `schema_meta` | version |

---

## 12. Supported File Types

`classification/formats.py`: extension and magic-byte table for text, structured data
(CSV/TSV/JSON/XML/YAML/TOML), office (DOC/DOCX/ODT/PPT/XLS/XLSX), PDF, audio (WAV/MP3/FLAC/
OGG/M4A), video (MP4/MKV/MOV/WEBM), images (PNG/JPG/TIFF/GIF/SVG), archives (ZIP/TAR/GZ/
7Z/RAR), linguistic annotation (EAF, TextGrid, FLEx/FLExText, Toolbox, LIFT, CoNLL, XIGT,
TEI, ELAN pfsx), datasets (Parquet, SQLite, HDF5, CLDF). Unknown → `format = "unknown"`,
stored under `other/`. **No file is ever rejected for format.**

---

## 13. Duplicate Detection

SHA-256 computed on a streaming read before permanent storage. Existing hash → no second
copy; a new `resource_source` row is attached to the existing resource and the session
counts a duplicate. `dedup/` exposes a `DuplicateDetector` interface with `exact()` now
and a `fuzzy()` slot (Phase 4: MinHash for text, perceptual hash for images, audio
fingerprint hook).

---

## 14. Resource Classification

`format` and `resource_type` are separate columns. Types (closed list from the spec, all
present): `dictionary lexicon wordlist corpus grammar phonology morphology syntax
orthography translation parallel_text transcription interlinear_text audio video image
field_notes research metadata software archive unknown`. Multiple tags allowed. Rule-based
classifier first (filename, metadata, extension, catalogue category, content keywords);
`AgentProvider.classify()` optional second opinion, stored with its own source.

---

## 15. Preserve Originals

Originals are read-only after storage. Derived output goes to
`extracted/<resource-id>/{text.txt, metadata.json, pages.json, ...}` and is indexed in
`extraction`. Re-extraction never touches the original.

---

## 16. Provenance

Recorded per the spec, per discovery method:

- Online: source URL, catalogue, resource URL, discovery method, search query,
  discovery date, download date, licence.
- Offline: original filesystem path, scan date, detection method, confidence.
- Import: original path, import date, import method.

Profile values: §2.9 envelope.

---

## 17. Collection Sessions

Every run creates `COL-YYYYMMDD-NNN`. Summary printed at end and on demand, exactly in
the spec's shape (Discovered, Relevant, Downloaded, Duplicates, Failed, Pending review).
`aimixe collect history` lists sessions; `aimixe collect history <id>` shows one.
Sessions are resumable: interrupted sessions keep status `interrupted` and their
candidate list, and `aimixe collect resume <id>` continues `[choice]`.

---

## 18. Review Queue

`aimixe collect review` and menu access. Items: uncertain resources (score 30–69) and
proposed profile facts from agent/catalogue discoveries. Prompt exactly as specified with
`[A] Accept [R] Reject [V] View source [S] Skip`. Accept on a profile fact writes a new
provenance envelope (`source_type = agent` or `catalogue`, with the confidence) and marks
it user-accepted; the canonical profile is never written by low-confidence discovery
without this step.

---

## 19. Architecture — package layout

```text
collect/
├── bin/aimixe                      sh launcher → python3 -m aimixe_collect
├── pyproject.toml                  metadata only; no third-party deps
├── src/aimixe_collect/
│   ├── __main__.py
│   ├── cli/                        presentation + interaction ONLY
│   │   ├── main.py                 argparse: collect, import, history, review, catalogue, resume
│   │   ├── interactive.py          the aimixe collect workflow (menus in §1, §3, §4)
│   │   ├── profile_wizard.py       §2 sections, progress display, progressive questioning
│   │   ├── review_ui.py            §18
│   │   └── render.py               tables, progress glyphs, prompts
│   ├── services/                   application services (CLI and future UI call these)
│   │   ├── language_service.py     resolve, create, load, confirm
│   │   ├── profile_service.py      known/missing, set value with provenance, groups
│   │   ├── collection_service.py   start session, run mode, summary
│   │   ├── import_service.py
│   │   ├── review_service.py
│   │   ├── catalogue_service.py    add/list/remove providers
│   │   └── history_service.py
│   ├── language/                   Language Resolution
│   │   ├── registry.py             bundled ISO/Glottolog tables, folding, candidates
│   │   ├── local_registry.py       ~/.aimixe/languages index
│   │   └── resolver.py             ordered resolution (§1)
│   ├── profile/                    Language Profile
│   │   ├── schema.py               groups, fields, prompts, types (§2.7)
│   │   ├── model.py                Profile, FieldValue envelope (§2.8, §2.9)
│   │   └── enrich.py               pre-fill from bundled data with provenance
│   ├── discovery/
│   │   ├── candidate.py            CandidateResource
│   │   ├── catalogue_search.py
│   │   ├── agent_search.py         §6 orchestration, SessionKnowledge
│   │   ├── query_planner.py        profile → queries
│   │   ├── offline_scan.py         §8
│   │   └── web.py                  fetch, link extraction, robots
│   ├── catalogues/                 Catalogue Providers
│   │   ├── base.py                 CatalogueProvider interface
│   │   ├── registry.py             built-in + user TOML providers
│   │   ├── configurable.py         TOML-driven provider
│   │   └── builtin/                olac.py glottolog.py elar.py paradisec.py kaipuleohone.py
│   │                               pangloss.py zenodo.py internet_archive.py ...
│   ├── agent/                      AI/Agent Layer
│   │   ├── base.py                 AgentProvider interface (§20)
│   │   ├── rule_based.py           RuleBasedAgent (always available, offline)
│   │   ├── cli_agent.py            generic subprocess agent driven by TOML (Claude/OpenAI/Qwen/local CLIs)
│   │   └── registry.py             pick provider from config
│   ├── relevance/scorer.py         §7
│   ├── ingestion/                  §10 pipeline + one module per stage
│   ├── classification/             formats.py, resource_types.py, classifier.py
│   ├── dedup/                      exact.py, fuzzy.py (Phase 4)
│   ├── extraction/                 Phase 4 text/metadata/archive extraction
│   ├── storage/                    paths.py, object_store.py, manifests.py
│   ├── db/                         connection.py, schema.sql, migrations.py, repositories/
│   ├── sessions/                   session ids, counters, events, resume
│   ├── review/                     queue model
│   ├── config.py                   ~/.aimixe/config/config.toml, AIMIXE_HOME
│   ├── logging_setup.py            JSONL logs in ~/.aimixe/logs
│   └── data/                       copied ISO/Glottolog tables + provenance notes,
│                                   profile-groups.toml, formats.toml, resource-types.toml,
│                                   builtin-catalogues.toml, agents.toml
└── tests/                          stdlib unittest; fixtures with tiny sample files
```

`cli/` imports `services/`; nothing else imports `cli/`. Enforced by a test that greps
imports.

---

## 20. Agent Independence

```python
class AgentProvider:
    name: str
    def analyze(self, context) -> Analysis: ...
    def classify(self, resource) -> list[TypeTag]: ...
    def generate_search_queries(self, language_profile) -> list[Query]: ...
    def enrich_language_profile(self, evidence) -> list[ProposedFact]: ...
```

Implementations: `RuleBasedAgent` (default, no network, no model), `CliAgent` configured
from `data/agents.toml` / user config (entries for claude, codex, gemini, qwen, ollama,
llm; `command = "... {prompt}"`, `local = true|false`). Future `ClaudeAgent`,
`OpenAIAgent`, `QwenAgent`, `LocalAgent` are additional classes behind the same
interface; nothing in discovery or ingestion references a vendor. Agent output is parsed
as JSON, validated, and always produces **proposals**, never direct writes.

---

## 21. CLI Commands

Interactive: `aimixe collect`.

Non-interactive (all delivered; each maps to one service call):

```bash
aimixe collect nst
aimixe collect nst --online
aimixe collect nst --offline
aimixe collect nst --catalogue
aimixe collect nst --agent
aimixe collect nst --scan ~/Documents
aimixe collect nst --import ~/linguistic-data
aimixe collect nst --profile
aimixe collect import <path>            [--mode copy|move|reference] [--language <id>]
aimixe collect history [<session-id>]
aimixe collect review
aimixe collect catalogue add|list|remove
aimixe collect resume <session-id>      [choice]
```

`--yes` / `--no-input` skips confirmations for scripts `[choice]`.

---

## 22. Development Approach — phases and deliverables

Inspection is done (this document). Findings: no existing code is imported; bundled
language data is copied (§0). Each phase ends with tests passing and a short demo
transcript.

### Phase 1 — foundation
- `aimixe collect` interactive entry, `bin/aimixe`, config, `~/.aimixe` bootstrap
- language resolver (bundled tables + local registry), detection/confirmation screen
- language profile model, schema/groups, provenance envelopes
- progressive questioning wizard with progress display, known/missing, 4-way menu
- local language registry (`languages/<id>/language.json`)
- storage manager (paths, atomic write-once object store, category folders)
- SQLite database and repositories
- shared ingestion pipeline skeleton with all stages present (extraction stage a no-op)
- import (file/folder; copy/move/reference), offline scanning by names/aliases/varieties
- SHA-256 deduplication with source attachment
- sessions, `history`, session summary
- collection-mode menu (§3), View Existing Collection, Language Profile re-entry

### Phase 2 — catalogues
- `CatalogueProvider` interface, provider registry, TOML configurable provider
- built-in providers (§4.1 list), Online Collection submenu, Catalogue Search flow
- `catalogue add|list|remove`
- resource provenance for online resources (§16)
- rule-based classification: format detection table and resource types (§12, §14)

### Phase 3 — agent search
- `AgentProvider` interface, `RuleBasedAgent`, `CliAgent`
- query planner using every profile field, web backend interface, bounded page following
- relevance scorer with all signals and bands (§7)
- session knowledge and dynamic re-querying (§6 step 15)
- profile enrichment proposals and review queue (§18), `review` command

### Phase 4 — advanced offline and content
- content-aware offline scanning (metadata, text contents, archive inspection)
- content extraction to `extracted/` (PDF text where a stdlib-only path exists;
  external tools optional and recorded), metadata.json, pages.json
- archive inspection (ZIP/TAR listing and optional member ingestion)
- fuzzy duplicate detection slot implemented (text MinHash, image/audio hooks)

### Phase 5 — GUI
- a UI on top of `services/`; no changes to core. Out of this plan's build scope.

---

## 23. Core Principles — how each is met

| Principle | Where |
|---|---|
| terminal-first | §1, §21 |
| UI-ready | §19 `services/`, data-driven §2.7 |
| modular | §19 |
| provider-independent | §4.1 |
| agent-independent | §20 |
| language-aware, profile-aware | §6 query planner, §7 scorer, §8 scan terms all read the full profile |
| provenance-preserving | §2.9, §16 |
| duplicate-aware | §13 |
| safe | write-once originals, robots/licence respect, review before profile change |
| resumable | §17 sessions |
| extensible | TOML providers, agents, schema-as-data |
| large multilingual collections | SQLite indexes on sha256/language/session; streaming hashes; per-language folders |

Every profile field named in §23 of the spec is consumed by at least one of: query
planner (§6), relevance scorer (§7), offline term list (§8), classifier hints (§14).
A test will assert this mapping so no field becomes passive metadata.

---

## Open points for you to confirm (each marked `[choice]` above)

1. Python 3.11+ standard library only, no pip dependencies.
2. Storage root `~/.aimixe/` with `AIMIXE_HOME` override.
3. Relevance thresholds: ≥ 70 confirmed, 30–69 review queue, < 30 not downloaded.
4. Local identifier `x-<slug>` for languages with no ISO code.
5. Extra commands beyond the spec's list: `review`, `resume`, `--yes`. Say no and they go.
6. Whether an agent may adjust the relevance score (bounded) or only advise.
