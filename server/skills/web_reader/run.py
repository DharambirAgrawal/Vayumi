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

import requests
from bs4 import BeautifulSoup

MAX_CONTENT_LENGTH = 50000
FETCH_TIMEOUT = 15


def main():
    pass


if __name__ == "__main__":
    main()
