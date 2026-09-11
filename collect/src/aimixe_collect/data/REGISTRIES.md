# Bundled registries

Fetched by `tools/fetch-registry.py`. These ship with the tool so that
identifying a language works with no network at all.

Fetched on 2026-09-08.

| File | What | Authority | sha256 | Bytes |
|---|---|---|---|---|
| `iso-639-3.tab` | ISO 639-3 code set | SIL International, the ISO 639-3 registration authority | `7a5ac370703ea0897356a8c383f2147865caf479e41c1c7bd96cc4c5f65e6907` | 178,280 |
| `iso-639-3_Name_Index.tab` | ISO 639-3 name index — every name a language is listed under | SIL International | `3a1bb6c4df06cfb3677fee89564e0cf9d957a8e3d91feb61cd8eb7d352369450` | 204,602 |
| `iso-639-3_Retirements.tab` | ISO 639-3 retirements — codes withdrawn, and what replaced them | SIL International | `c4c5105798541859ce6f0125572132dfcfaf6ab8485ed6a77ca9592404386cb8` | 19,046 |
| `iso-639-3-macrolanguages.tab` | which individual languages sit inside each macrolanguage | SIL International | `fb01a86376d9c1abfc96d16be1b6dcffb4776a1f52fa22338d4979e9ffe1822f` | 4,609 |
| `iso15924.txt` | ISO 15924 script codes | Unicode Consortium, the ISO 15924 registration authority | `98a9be293c706f7e6302e9a54ed959c36f15f53e4ca618356d80c10be2928426` | 14,444 |

## Where they came from

- `iso-639-3.tab` — https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3.tab
- `iso-639-3_Name_Index.tab` — https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3_Name_Index.tab
- `iso-639-3_Retirements.tab` — https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3_Retirements.tab
- `iso-639-3-macrolanguages.tab` — https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3-macrolanguages.tab
- `iso15924.txt` — https://www.unicode.org/iso15924/iso15924.txt

## Terms

The ISO 639-3 tables are published by SIL International as the registration
authority, and the ISO 15924 table by the Unicode Consortium. Both are
published for public use in identifying languages and scripts, which is
exactly what they are used for here. Check the current terms at the URLs
above before redistributing this package outside your organisation.

## Keeping them current

```
aimixe survey update-languages     # refetch, verify, record the new release
```

Rows already in a store keep the release they were resolved against, so a
refresh never silently changes what a past decision was based on.

## Added for the AImixE Data Collection Module

| File | What | Source |
|---|---|---|
| `countries.tsv` | ISO 3166-1 alpha-2 code → country name, used only to display regions | Debian `iso-codes` package (`/usr/share/iso-codes/json/iso_3166-1.json`), LGPL-2.1 |
| `reference.csv` | Glottolog 5.3 + CLDR extract; see `reference-SOURCES.md` and `reference-meta.json` | copied 2026-09-11 from the AImixE survey tool's bundled data |
