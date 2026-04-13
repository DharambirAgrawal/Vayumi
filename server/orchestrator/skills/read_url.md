Link reading guidance:
- Use `read_url` when the task depends on one link and the user wants a specific output shape.
- Pass `instruction` for style control such as short summary, bullets, steps, or quote extraction.
- The tool first tries a lightweight Scrapling fetch path and falls back to HTML cleanup when needed.
- If the page is protected, blocked, empty, or fetchable=false, report `CAPABILITY_GAP` with the tool reason.
- Prefer a single URL per call unless the user explicitly asks for multiple links.