from __future__ import annotations


def doc_generator(title: str, content: str, format: str = "markdown") -> str:
    if format not in {"markdown", "pdf", "docx", "txt"}:
        return f"ERROR: Unsupported format: {format}"
    return (
        "Generated draft document (not persisted). "
        f"title={title}, format={format}, chars={len(content)}"
    )
