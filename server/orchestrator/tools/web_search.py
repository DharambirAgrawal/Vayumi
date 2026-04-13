from __future__ import annotations

import json
import urllib.parse
import urllib.request


def web_search(query: str) -> str:
    """Search the web quickly via DuckDuckGo instant answer endpoint."""
    params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
    url = f"https://api.duckduckgo.com/?{params}"

    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            body = response.read().decode("utf-8", errors="ignore")
        payload = json.loads(body)
    except Exception as exc:
        return f"ERROR: web_search failed: {exc}"

    related = payload.get("RelatedTopics", [])
    items = []
    for item in related[:5]:
        if isinstance(item, dict) and item.get("Text"):
            items.append(
                {
                    "title": item.get("Text", ""),
                    "url": item.get("FirstURL", ""),
                    "snippet": item.get("Text", ""),
                }
            )

    answer = payload.get("AbstractText", "")
    if answer:
        items.insert(0, {"title": "Instant answer", "url": payload.get("AbstractURL", ""), "snippet": answer})

    return json.dumps({"query": query, "results": items[:5]})
