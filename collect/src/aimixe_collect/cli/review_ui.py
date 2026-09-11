"""Review queue interaction (specification §18)."""
from __future__ import annotations

from ..services.app import App
from . import render as r
from .render import Abort


def run_review(app: App, language_id: str | None = None) -> int:
    items = app.review_service.pending(language_id)
    if not items:
        r.out("Nothing to review.")
        return 0
    names = {row["id"]: (row["name"], row["iso639_3"] or row["id"]) for row in app.languages.list()}
    if language_id and language_id in names:
        r.title_bar(f"Review Queue · {names[language_id][0]} [{names[language_id][1]}] · {len(items)} item(s)")
    else:
        r.title_bar(f"Review Queue · all languages · {len(items)} item(s)")
    r.note("  Accept writes the value into the profile or confirms the resource; Reject keeps it recorded as rejected; "
           "Skip leaves it for later.")
    done = 0
    try:
        for item in items:
            while True:
                r.out()
                lang = names.get(item.language_id, (item.language_id, item.language_id))
                r.note(f"  item {items.index(item) + 1} of {len(items)} · {lang[0]} [{lang[1]}]")
                if item.kind == "profile_field":
                    r.out(r.c("Possible new language information detected", "bold"))
                    r.out()
                    r.out(f"Field: {r.c(str(item.payload.get('field')), 'bold')}")
                    r.out(f"Value: {r.c(r.fmt_value(item.payload.get('value')), 'cyan')}")
                    if item.payload.get("quote"):
                        r.out(f"Quote: “{item.payload['quote'][:200]}”")
                else:
                    r.out(r.c("Uncertain resource", "bold"))
                    r.out()
                    r.out(f"Resource: {r.c(str(item.payload.get('name')), 'bold')}")
                    r.out(f"Relevance: {r.score_text(item.payload.get('relevance'), str(item.payload.get('band')))}")
                    for reason in item.payload.get("reasons", [])[:5]:
                        r.out(f"  - {reason}")
                if item.confidence is not None:
                    r.out(f"Confidence: {int(round(item.confidence * 100))}%")
                r.out()
                r.out("Source:")
                r.out(str(item.source_ref or "—"))
                r.out()
                r.out(f"[{r.c('A', 'green', 'bold')}] Accept")
                r.out(f"[{r.c('R', 'red', 'bold')}] Reject")
                r.out(f"[{r.c('V', 'cyan', 'bold')}] View source")
                r.out(f"[{r.c('S', 'bold')}] Skip")
                ans = r.prompt().lower()
                if ans == "a":
                    app.review_service.accept(item)
                    done += 1
                    break
                if ans == "r":
                    app.review_service.reject(item)
                    done += 1
                    break
                if ans == "s":
                    app.review_service.skip(item)
                    break
                if ans == "v":
                    r.out()
                    r.out(app.review_service.source_text(item))
                    continue
                if ans in ("q", "quit", "exit"):
                    raise Abort()
    except Abort:
        r.out("Review stopped; remaining items stay in the queue.")
    return done
