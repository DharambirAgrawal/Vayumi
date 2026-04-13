Use url_summarizer for pages where current content matters.
- Validate URL is absolute.
- Prefer one URL at a time.
- If the user wants a specific format, use `read_url` with an `instruction` value instead of generic summarization.
- If summary returns ERROR, report CAPABILITY_GAP with exact reason.
