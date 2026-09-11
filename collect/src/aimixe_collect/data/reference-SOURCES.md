# Where the reference extract comes from

`data/reference.csv` is a derivative work. It is built by
`tools/build-reference.py` from the sources below, keeping only the columns
the survey asks about. Neither source is redistributed whole.

## Glottolog 5.3

* Licence: **CC-BY-4.0**
* Source: https://github.com/glottolog/glottolog-cldf (`cldf/languages.csv`)
* Cite as: Hammarström, Harald & Forkel, Robert & Haspelmath, Martin & Bank, Sebastian. 2024. Glottolog 5.3. Leipzig: Max Planck Institute for Evolutionary Anthropology.

## Unicode CLDR main

* Licence: **Unicode-3.0**
* Source: https://github.com/unicode-org/cldr (`common/supplemental/likelySubtags.xml`)
* Cite as: Unicode Common Locale Data Repository. likelySubtags. Used only for the script a language would likely be written in, which is not a claim that it is written.

## ISO 639-3 2026

* Licence: **free to download and use**
* Source: https://iso639-3.sil.org (`iso-639-3.tab`)
* Cite as: SIL International. ISO 639-3 code tables.

## What was kept

8,083 languages, by ISO 639-3 code: the catalogue's name,
its Glottolog code, its family and family code, its macroarea, the countries
it is recorded in, and the names Glottolog lists for its dialects.

## What the tool does with it

It proposes one field — `identification.family` — and a person confirms it,
like any other suggestion. The dialect names are **not** proposed as an
answer to `varieties`: the instrument asks for the community's own words for
its varieties, and these are an outsider's. They are offered as something to
ask about in the field.

Built 2026-09-10T04:09:01+00:00.
