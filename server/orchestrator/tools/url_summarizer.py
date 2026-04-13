from __future__ import annotations

import json
import re
import urllib.request


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[\\s\\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def url_summarizer(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return f"ERROR: Could not read URL: {exc}"

    text = _strip_html(body)
    if not text:
        return "ERROR: URL content was empty"

    preview = text[:3000]
    lines = [segment.strip() for segment in re.split(r"(?<=[.!?])\\s+", preview) if segment.strip()]
    summary = " ".join(lines[:4])

    return json.dumps({"url": url, "summary": summary, "chars": len(text)})
