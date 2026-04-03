# =============================================================================
# server/skills/web_reader/run.py — Web Reader Skill Execution
# =============================================================================
#
# PURPOSE:
#   Fetches a URL, strips HTML, extracts clean text content.
#   The LLM never sees raw HTML — only clean, extracted text.
#
# INPUT: Reads input.json from current directory
#   { "url": str, "question": str (optional) }
#
# OUTPUT: Writes output.json to current directory
#   Success: { "success": true, "result": str, "metadata": {...} }
#   Error:   { "success": false, "error": str, "metadata": {...} }
#
# EXECUTION STEPS:
#   1. Read input.json → extract url and question
#   2. Fetch URL via requests.get (timeout=15s)
#   3. Parse HTML with BeautifulSoup
#   4. Remove script, style, nav, footer, ad elements
#   5. Extract clean text via .get_text(separator="\n")
#   6. Truncate at 50,000 characters
#   7. Write result to output.json with metadata (url, chars_read, title)
#
# ERROR HANDLING:
#   - HTTP errors → write error to output.json
#   - Parse errors → write error to output.json
#   - Timeout → write error to output.json
#   - Never crash silently
#
# IMPORTS NEEDED:
#   import json
#   import requests
#   from bs4 import BeautifulSoup
#
# MUST COMPLETE WITHIN 30 SECONDS.
# =============================================================================

import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

MAX_CONTENT_LENGTH = 50_000
FETCH_TIMEOUT = 15

# Tags that carry zero informational value for the LLM and bloat the output.
STRIP_TAGS = [
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "nav",
    "footer",
    "header",
]

# CSS class / id substrings that almost always denote ad or boilerplate blocks.
AD_PATTERNS = re.compile(
    r"ad[-_]?banner|advert|sidebar|cookie|popup|modal|newsletter|promo",
    re.IGNORECASE,
)

INPUT_PATH = Path("input.json")
OUTPUT_PATH = Path("output.json")


# ------------------------------------------------------------------ helpers --

def write_output(data: dict) -> None:
    """Atomically (enough) write the result dict to output.json."""
    OUTPUT_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_error(message: str, url: str | None = None) -> None:
    """Convenience wrapper — writes a well-formed error output."""
    write_output({
        "success": False,
        "error": message,
        "metadata": {"url": url},
    })


def collapse_whitespace(text: str) -> str:
    """
    Collapse runs of blank lines / spaces into readable paragraphs.
    Keeps single newlines between blocks but removes the 15-blank-line
    chasms that boilerplate-heavy pages tend to produce.
    """
    # Replace any run of 3+ newlines with exactly 2 (one blank line).
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of spaces/tabs (but not newlines) on each line.
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def strip_boilerplate(soup: BeautifulSoup) -> None:
    """
    Remove elements that never contain useful article content:
    scripts, styles, navs, footers, ad-related divs, etc.
    Mutates *soup* in place.
    """
    # 1. Remove well-known non-content tags entirely.
    for tag_name in STRIP_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()

    # 2. Remove elements whose class or id smells like an ad / boilerplate.
    for element in soup.find_all(True):
        classes = " ".join(element.get("class", []))
        element_id = element.get("id", "") or ""
        haystack = f"{classes} {element_id}"
        if AD_PATTERNS.search(haystack):
            element.decompose()


def extract_title(soup: BeautifulSoup) -> str:
    """Best-effort page title extraction."""
    # Prefer <title> tag, fall back to first <h1>.
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def _normalize_author_value(value) -> str:
    """Normalize author metadata from common HTML / JSON-LD shapes."""
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        for key in ("name", "author", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

    if isinstance(value, list):
        for item in value:
            candidate = _normalize_author_value(item)
            if candidate:
                return candidate

    return ""


def extract_author(soup: BeautifulSoup) -> str:
    """Best-effort author extraction from meta tags and JSON-LD."""
    meta_selectors = (
        ("meta", {"name": "author"}),
        ("meta", {"property": "article:author"}),
        ("meta", {"property": "og:article:author"}),
        ("meta", {"name": "parsely-author"}),
        ("meta", {"name": "byl"}),
    )

    for tag_name, attrs in meta_selectors:
        element = soup.find(tag_name, attrs=attrs)
        if not element:
            continue
        content = element.get("content") or element.get("value") or ""
        if isinstance(content, str) and content.strip():
            return content.strip()

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = script.string or script.get_text(strip=True)
        if not raw_json:
            continue
        try:
            payload = json.loads(raw_json)
        except Exception:
            continue

        queue = [payload]
        while queue:
            item = queue.pop(0)
            if isinstance(item, dict):
                author_value = item.get("author")
                author = _normalize_author_value(author_value)
                if author:
                    return author
                queue.extend(v for v in item.values() if isinstance(v, (dict, list)))
            elif isinstance(item, list):
                queue.extend(item)

    return ""


# -------------------------------------------------------------------- main --

def main() -> None:
    # ---------------------------------------------------------------- #
    # 1. Read input.json                                                #
    # ---------------------------------------------------------------- #
    url: str | None = None

    try:
        raw_input = INPUT_PATH.read_text(encoding="utf-8")
        input_data = json.loads(raw_input)
    except FileNotFoundError:
        write_error("input.json not found")
        return
    except json.JSONDecodeError as exc:
        write_error(f"input.json is not valid JSON: {exc}")
        return

    url = input_data.get("url")
    if not url or not isinstance(url, str):
        write_error("Missing or invalid 'url' in input.json", url=url)
        return

    url = url.strip()

    # Ensure the URL has a scheme so requests doesn't choke.
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # question is optional — kept here in case future logic needs it.
    _ = input_data.get("question", "Summarize this page")

    # ---------------------------------------------------------------- #
    # 2. Fetch the URL                                                  #
    # ---------------------------------------------------------------- #
    try:
        response = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; SkillRunner/1.0; "
                    "+https://github.com/example/skillrunner)"
                ),
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
            allow_redirects=True,
        )
        response.raise_for_status()

    except requests.exceptions.Timeout:
        write_error(
            f"HTTP request timed out after {FETCH_TIMEOUT}s",
            url=url,
        )
        return
    except requests.exceptions.ConnectionError as exc:
        write_error(f"Connection failed: {exc}", url=url)
        return
    except requests.exceptions.TooManyRedirects:
        write_error("Too many redirects", url=url)
        return
    except requests.exceptions.HTTPError as exc:
        write_error(
            f"HTTP {response.status_code}: {exc}",  # noqa: F821
            url=url,
        )
        return
    except requests.exceptions.RequestException as exc:
        write_error(f"Request failed: {exc}", url=url)
        return

    # ---------------------------------------------------------------- #
    # 3. Parse HTML with BeautifulSoup                                  #
    # ---------------------------------------------------------------- #
    try:
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        write_error(f"HTML parsing failed: {exc}", url=url)
        return

    # ---------------------------------------------------------------- #
    # 4. Extract title before we start decomposing elements             #
    # ---------------------------------------------------------------- #
    title = extract_title(soup)
    author = extract_author(soup)

    # ---------------------------------------------------------------- #
    # 5. Remove script, style, nav, footer, ad elements                 #
    # ---------------------------------------------------------------- #
    strip_boilerplate(soup)

    # ---------------------------------------------------------------- #
    # 6. Extract clean text                                             #
    # ---------------------------------------------------------------- #
    raw_text = soup.get_text(separator="\n")
    clean_text = collapse_whitespace(raw_text)

    if not clean_text:
        write_error(
            "Page fetched successfully but no text content could be extracted",
            url=url,
        )
        return

    # ---------------------------------------------------------------- #
    # 7. Truncate at MAX_CONTENT_LENGTH                                 #
    # ---------------------------------------------------------------- #
    truncated = False
    if len(clean_text) > MAX_CONTENT_LENGTH:
        clean_text = clean_text[:MAX_CONTENT_LENGTH]
        truncated = True

    # ---------------------------------------------------------------- #
    # 8. Write output.json                                              #
    # ---------------------------------------------------------------- #
    write_output({
        "success": True,
        "result": clean_text,
        "metadata": {
            "url": url,
            "chars_read": len(clean_text),
            "title": title,
            "author": author,
            "truncated": truncated,
        },
    })


if __name__ == "__main__":
    main()