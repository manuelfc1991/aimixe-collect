# aimixe-tools-ours

AImixE tools, built to specification and kept independent of each other.

| Tool | Folder | What it is |
|---|---|---|
| Data Collection Module | [`collect/`](collect/) | `aimixe collect` — terminal-first, UI-ready collection of language resources: language resolution and profile, catalogue and agent search, offline scanning, import, shared ingestion pipeline, review queue, local web interface. See `collect/README.md` and `collect/PLAN.md`. |

Requirements: Python 3.11+, standard library only.

```bash
cd collect
bin/aimixe collect            # interactive
bin/aimixe collect ui         # local web interface
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

## Licence

MIT, see `LICENSE`. Bundled language data (Glottolog, ISO 639-3, ISO 15924, ISO 3166) keeps its own terms, listed in `THIRD_PARTY_DATA.md`.
