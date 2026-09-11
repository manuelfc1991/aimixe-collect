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
    r.heading(f"Review queue: {len(items)} item(s)")
    done = 0
    try:
        for item in items:
            while True:
                r.out()
                if item.kind == "profile_field":
                    r.out("Possible new language information detected")
                    r.out()
                    r.out(f"Field: {item.payload.get('field')}")
                    r.out(f"Value: {r.fmt_value(item.payload.get('value'))}")
                    if item.payload.get("quote"):
                        r.out(f"Quote: “{item.payload['quote'][:200]}”")
                else:
                    r.out("Uncertain resource")
                    r.out()
                    r.out(f"Resource: {item.payload.get('name')}")
                    r.out(f"Relevance: {item.payload.get('relevance')} ({item.payload.get('band')})")
                    for reason in item.payload.get("reasons", [])[:5]:
                        r.out(f"  - {reason}")
                if item.confidence is not None:
                    r.out(f"Confidence: {int(round(item.confidence * 100))}%")
                r.out()
                r.out("Source:")
                r.out(str(item.source_ref or "—"))
                r.out()
                r.out("[A] Accept")
                r.out("[R] Reject")
                r.out("[V] View source")
                r.out("[S] Skip")
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
