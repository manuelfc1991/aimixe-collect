"""Linguistic resource types (specification §14), separate from file format."""
from __future__ import annotations

RESOURCE_TYPES = (
    "dictionary", "lexicon", "wordlist", "corpus", "grammar", "phonology", "morphology",
    "syntax", "orthography", "translation", "parallel_text", "transcription",
    "interlinear_text", "audio", "video", "image", "field_notes", "research", "metadata",
    "software", "archive", "unknown",
)

# keyword (folded) -> type. Matched against file/folder names, titles and metadata.
KEYWORDS: dict[str, str] = {
    "dictionary": "dictionary", "dict": "dictionary", "dictionar": "dictionary", "lexicon": "lexicon",
    "lexique": "lexicon", "lexical": "lexicon", "wordlist": "wordlist", "word list": "wordlist",
    "swadesh": "wordlist", "vocabulary": "wordlist", "vocab": "wordlist", "corpus": "corpus",
    "corpora": "corpus", "texts": "corpus", "grammar": "grammar", "grammatical": "grammar",
    "sketch": "grammar", "phonology": "phonology", "phonological": "phonology", "phonetic": "phonology",
    "tone": "phonology", "morphology": "morphology", "morphological": "morphology", "verb": "morphology",
    "syntax": "syntax", "syntactic": "syntax", "clause": "syntax", "orthography": "orthography",
    "alphabet": "orthography", "spelling": "orthography", "primer": "orthography",
    "writing system": "orthography", "translation": "translation", "translated": "translation",
    "bible": "translation", "gospel": "translation", "new testament": "translation",
    "parallel": "parallel_text", "bitext": "parallel_text", "aligned": "parallel_text",
    "transcription": "transcription", "transcript": "transcription", "interlinear": "interlinear_text",
    "glossed": "interlinear_text", "igt": "interlinear_text", "flextext": "interlinear_text",
    "field notes": "field_notes", "fieldnotes": "field_notes", "notebook": "field_notes",
    "elicitation": "field_notes", "thesis": "research", "dissertation": "research", "paper": "research",
    "article": "research", "journal": "research", "proceedings": "research", "survey": "research",
    "metadata": "metadata", "imdi": "metadata", "cmdi": "metadata", "olac": "metadata",
    "keyboard": "software", "font": "software", "keyman": "software", "software": "software",
    "story": "corpus", "stories": "corpus", "narrative": "corpus", "folktale": "corpus",
    "song": "audio", "recording": "audio", "interview": "audio",
}

FORMAT_TYPES: dict[str, str] = {
    # format -> implied type
    "elan": "transcription", "praat-textgrid": "transcription", "transcriber": "transcription",
    "chat": "transcription", "exmaralda": "transcription", "flex-text": "interlinear_text",
    "xigt": "interlinear_text", "conll-u": "corpus", "conll": "corpus", "lift": "dictionary",
    "toolbox-sfm": "dictionary", "toolbox": "dictionary", "dictionary-text": "dictionary",
    "lexicon-text": "lexicon", "hunspell": "wordlist", "subtitles": "transcription",
    "font-truetype": "software", "font-opentype": "software", "font-woff": "software",
    "font-woff2": "software", "keyman-keyboard": "software", "keyman-package": "software",
    "ms-keyboard-layout": "software", "mac-keyboard-layout": "software",
    "source-python": "software", "source-javascript": "software", "source-shell": "software",
    "source-r": "software", "executable": "software", "android-package": "software",
    "java-archive": "software", "bibtex": "metadata",
}

CATEGORY_TYPES: dict[str, str] = {
    "audio": "audio", "video": "video", "images": "image", "archives": "archive",
}
