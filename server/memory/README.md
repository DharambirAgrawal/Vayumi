# MemoryOS

A persistent, multimodal memory layer for AI agents.

## What is included

- Unified API via `MemorySystem`
- Multi-store retrieval (explicit, semantic, graph)
- Ingestion pipelines for file, image, audio, link, and meeting transcript
- User personalization model
- Tool schemas for LLM tool-calling

## Project layout

- `memory/` - package source
- `tests/` - pytest suite
- `requirements.txt` - dependencies are now centralized in the repo root
- `.runtime/` - centralized runtime artifacts (pytest temp/cache, coverage data)

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r ../../requirements.txt
pytest -q
```

## Basic usage

```python
from memory import MemorySystem, MemoryType

mem = MemorySystem(speaker_id="alice")
mem.save("Alice prefers concise responses", MemoryType.PREFERENCE)
result = mem.search("What does Alice prefer?")
print(result.context)
```

## Notes

This scaffold uses production-style interfaces, with local fallback behavior for heavy integrations.
You can progressively replace placeholders with actual providers (Qdrant, Whisper, Graph DB, etc.).

## Runtime Artifacts

- `data/memory/memory.db`: default SQLite database path for all memory record types.
- `data/memory/blobs/`: default local blob storage for binary memory assets.
- `.runtime/pytest-tmp`: pytest temp directory used by fixtures such as `tmp_path`.
- `.runtime/.pytest_cache`: pytest cache state.
- `.runtime/.coverage`: coverage data file when running coverage-enabled test commands.

Storage model note:
- There is one canonical SQLite DB (`memory_records` table) that stores every memory type (`fact`, `preference`, `event`, `relationship`, `link`, `file`, `image`, `audio`, `meeting`).
- Different media types are separated by the `type` column and optional `blob_path`/`chunk_ids`, not by separate DB files.

Note: most tests pass explicit temporary paths, so test-created DB/blob data is isolated under `.runtime/pytest-tmp`.
