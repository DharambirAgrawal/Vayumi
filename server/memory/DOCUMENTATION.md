# MemoryOS - Detailed Memory Documentation

This document is intentionally detailed and covers only the memory system in this repository.
It excludes unrelated concerns such as websocket transport, deployment topology, and non-memory orchestration.

## 1. System Purpose

MemoryOS provides a persistent multimodal memory layer for AI agents.
It is responsible for:
- Capturing information from user turns and shared artifacts.
- Persisting that information across sessions.
- Returning only relevant memory context during future turns.

The memory package supports:
- Text memories (fact, preference, event, relationship)
- File memories
- Link memories
- Image memories
- Audio memories
- Meeting memories

## 2. Memory Lifecycle

### 2.1 Start of agent turn
- Call memory search with the current user query.
- Inject returned context into the prompt before response generation.

### 2.2 During turn
- If the user shares a URL/file/image/audio/meeting transcript, ingest immediately.

### 2.3 End of turn
- Save durable facts/preferences/events/relationships from the turn.
- Update or delete prior memories if the user corrected information.

## 3. High-Level Architecture

Package: memory/

### Core control plane
- memory/__init__.py - MemorySystem public API.
- memory/config.py - runtime settings.
- memory/models.py - shared datatypes.
- memory/tools.py - tool schemas for LLM tool-calling.

### Memory logic
- memory/router.py - extract/classify/save-worthiness logic.
- memory/retrieval.py - multi-source retrieval and rerank.
- memory/short_term.py - in-session turn buffer.
- memory/personalization.py - user model updates and prompt shaping.

### Ingestion pipelines
- memory/ingestion/file.py
- memory/ingestion/link.py
- memory/ingestion/image.py
- memory/ingestion/audio.py
- memory/ingestion/meeting.py

### Stores
- memory/stores/explicit.py - SQLite canonical memory index.
- memory/stores/semantic.py - semantic search store interface and fallback implementation.
- memory/stores/graph.py - relationship graph store interface and fallback implementation.
- memory/stores/blobs.py - raw file/blob persistence.

### Optional ML modules
- memory/ml/embedding_finetune.py
- memory/ml/lora_train.py
- memory/ml/lora_load.py

## 4. Public API (MemorySystem)

File: memory/__init__.py

Implemented methods:
- search(query, speaker_id=None, type_filter=None, date_from=None, date_to=None, source_url=None, top_k=5)
- ingest(source_type, content, speaker_id=None, date=None, title=None, participants=None)
- save(content, memory_type, speaker_id=None, expires_at=None)
- delete(memory_id, speaker_id=None)
- update(memory_id, new_content, speaker_id=None)
- get_user_model(speaker_id=None)
- get_short_term()
- add_turn(speaker_id, text)
- flush_session()

Behavior summary:
- Ingest dispatches by source_type.
- Save writes to explicit + semantic stores.
- Delete attempts semantic/graph/blob/explicit removal.
- Update re-embeds summary and rewrites chunk refs.
- flush_session runs router extraction + personalization update.

Compatibility note:
- Public API shape is stable and synchronous.
- provider_mode was added as a compatible constructor option.

## 5. Data Model

File: memory/models.py

### 5.1 MemoryType enum
- fact
- preference
- event
- relationship
- link
- file
- image
- audio
- meeting

### 5.2 MemoryRecord
Fields:
- id
- type
- summary
- speaker_id
- created_at
- source_url
- blob_path
- chunk_ids
- graph_node_id
- metadata

### 5.3 SearchResult and SearchResponse
- SearchResult carries scored retrieval rows.
- SearchResponse carries prompt-ready context plus raw results.

### 5.4 IngestResponse
- memory_id
- store
- chunk_count
- success

### 5.5 UserModel
- speaker profile for communication and personalization behavior.

## 6. Stores: Detailed Status

## 6.1 ExplicitStore (SQLite)
File: memory/stores/explicit.py

Implemented:
- insert/get/update/delete/filter
- get_user_model/upsert_user_model

Role:
- Canonical index and metadata source.
- Other stores reference memory_id stored here.

Status: production-capable for local persistence.

## 6.2 BlobStore
File: memory/stores/blobs.py

Implemented:
- save/load/load_as_base64/delete/exists

Role:
- Persists original binary assets (image/audio/file/transcript).

Status:
- Local disk path implemented.
- S3-compatible mode exists in config and class surface; advanced cloud-hardening remains future work.

## 6.3 SemanticStore
File: memory/stores/semantic.py

Implemented:
- upsert/search/delete/delete_by_memory_id
- sentence-transformers embedding path when model/runtime available
- sparse in-memory fallback if encoder unavailable

Role:
- semantic similarity retrieval.

Current gap:
- Hosted vector backend adapter exists with automatic fallback to in-memory mode.
- Additional production hardening (telemetry, retries, robust hosted filtering coverage) remains.

## 6.4 GraphStore
File: memory/stores/graph.py

Implemented:
- add_entity/add_relationship/search/get_person_meetings/get_entity/delete_node/resolve_alias
- date range filtering in search and get_person_meetings
- in-memory entity and edge handling

Role:
- entity/relationship retrieval and cross-memory linkage.

Current gap:
- Hosted Neo4j backend adapter exists with automatic fallback to in-memory mode.
- Additional production hardening and deeper graph traversal features remain.

## 7. Ingestion Pipelines: Detailed Status

## 7.1 FileIngester
File: memory/ingestion/file.py

Implemented now:
- PDF extraction (pdfplumber)
- DOCX extraction (python-docx)
- CSV extraction (pandas -> markdown table)
- JSON pretty extraction
- text/* decoding fallback
- chunking with overlap
- blob save + semantic upsert + explicit record insert

Remaining improvements:
- richer MIME sniffing and strict validation.
- extraction quality improvements for edge-format PDFs.

## 7.2 LinkIngester
File: memory/ingestion/link.py

Implemented now:
- URL type detection (GitHub vs generic)
- generic fetch path:
  - Jina Reader attempt first
  - requests + BeautifulSoup fallback
- GitHub fetch path:
  - repository metadata
  - README extraction from GitHub API
- refresh() re-fetch and re-index path

Remaining improvements:
- optional pagination/deeper repo file extraction.
- stronger retry/backoff and rate-limit strategies.

## 7.3 AudioIngester
File: memory/ingestion/audio.py

Implemented now:
- Whisper transcription when runtime supports it
- deterministic fallback summary when transcription unavailable
- sentence-based chunking + semantic indexing + blob storage

Remaining improvements:
- configurable language/task parameters.
- stronger audio format normalization before transcription.

## 7.4 ImageIngester
File: memory/ingestion/image.py

Implemented now:
- image metadata and pixel-stat derived description
- size/format/mode/brightness/palette text generation
- chunk/index/store pipeline

Remaining improvements:
- OCR enrichment for text-heavy images.
- optional remote vision provider adapter behind same interface.

## 7.5 MeetingIngester
File: memory/ingestion/meeting.py

Implemented now:
- transcript-first ingestion (core memory behavior)
- turn chunking
- meeting node + participant nodes + PARTICIPATED_IN edges
- action-item heuristic extraction
- transcript blob save
- optional diarization enhancement path (non-mandatory)

Important design note:
- Memory correctness does not depend on diarization.
- If diarization runtime is unavailable, ingestion still works.

Remaining improvements:
- richer participant mapping logic.
- model-assisted action item extraction.

## 8. Retrieval, Router, and Personalization

## 8.1 RetrievalEngine
File: memory/retrieval.py

Implemented:
- parallel strategy calls (semantic + graph + metadata)
- merge, deduplicate, rerank
- prompt-ready context builder
- multimodal block loader for image/audio blobs

Remaining improvements:
- stronger weighting calibration by query intent and user model.

## 8.2 MemoryRouter
File: memory/router.py

Implemented:
- route_turn/route_session
- classify
- resolve_entities
- should_save filtering

Remaining improvements:
- confidence calibration and entity normalization depth.

## 8.3 ShortTermBuffer
File: memory/short_term.py

Implemented:
- add/get_context/get_turns/token_count/clear/to_text
- max token trimming behavior

## 8.4 PersonalizationLayer
File: memory/personalization.py

Implemented:
- get_model
- update_from_session
- to_system_prompt
- extract_preferences

Remaining improvements:
- tighter use of user model signals in retrieval rerank.

## 9. Tool Contract for AI Agents

File: memory/tools.py

Implemented tool schemas:
- memory_search
- memory_ingest
- memory_save
- memory_delete
- memory_update

Usage contract:
- memory_search at start of turn
- memory_ingest for shared artifacts
- memory_save for durable facts/preferences/events/relationships
- memory_update for corrections
- memory_delete for forget requests

## 10. Configuration

File: memory/config.py

Includes:
- store URLs and collection/db/blob paths
- model names (embedding/whisper/llm)
- token/chunk/retrieval limits
- optional ML paths
- blob backend/s3 settings
- provider strategy fields:
  - provider_mode: auto/cloud/local
  - semantic_backend: auto/hosted/local/memory
  - graph_backend: auto/hosted/local/memory
  - blob_backend: auto/s3/disk

## 11. Remaining Work (Memory Only)

### 11.1 Critical
1. Expand hosted semantic adapter hardening (retry policy, health checks, richer provider diagnostics).
2. Expand hosted graph adapter hardening (query safeguards, diagnostics, deeper traversal patterns).
3. Propagate typed memory exceptions through all ingestion/store layers with uniform error payload mapping.
4. Add more async integration tests for concurrent workloads.

### 11.2 Important
1. Add robust retry/timeout/backoff behavior in network ingestion paths.
2. Expand meeting action extraction quality beyond keyword heuristics.
3. Improve image OCR and object-level extraction path.

### 11.3 Quality and verification
1. Test suite is now present and runnable via pytest.
2. Increase coverage for ingestion network branches and router/personalization logic.
3. Add larger concurrency and long-session regression scenarios.

### 11.4 Optional ML (memory-related but non-blocking)
- memory/ml/embedding_finetune.py now produces real pair artifacts and supports optional sentence-transformers training.
- memory/ml/lora_train.py now produces real dataset/metadata artifacts and supports opt-in training execution.
- memory/ml/lora_load.py now loads adapter metadata and tracks active adapter descriptors.

## 12. What Is Intentionally Out of Scope Here

Not part of this documentation:
- websocket API design
- cloud infrastructure deployment
- auth gateway and request transport
- non-memory orchestration systems

## 13. Recommended Next Implementation Sequence

1. Add hosted adapters for semantic and graph stores.
2. Add async wrappers and typed errors.
3. Add comprehensive tests and sample fixtures.
4. Align README and memory/SKILL.md to this exact behavior.
