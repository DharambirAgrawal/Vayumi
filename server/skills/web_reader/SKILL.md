# Web Reader Skill

## Description
Given a URL, fetches the web page, strips HTML to extract clean text content,
and returns the extracted text for further processing (summarization, Q&A, etc.).

## Input Format (input.json)
```json
{
  "url": "https://example.com/article",
  "question": "Summarize this page"
}
```
- `url` (required): The URL to fetch and read
- `question` (optional): What to do with the content. Default: "Summarize this page"

## Output Format (output.json)
```json
{
  "success": true,
  "result": "Extracted clean text content of the page...",
  "metadata": {
    "url": "https://example.com/article",
    "chars_read": 4200,
    "title": "Page Title"
  }
}
```

## Error Output
```json
{
  "success": false,
  "error": "Description of what went wrong",
  "metadata": { "url": "https://example.com/article" }
}
```

## Requirements
- `requests` or `httpx` for HTTP fetching
- `beautifulsoup4` for HTML parsing and text extraction
- No raw HTML should ever reach the LLM — only clean extracted text

## Execution Notes
- Timeout: 15 seconds for HTTP fetch
- Max content: Truncate at 50,000 characters
- Strip: scripts, styles, nav, footer, ads
- The LLM never sees raw HTML — only clean text
