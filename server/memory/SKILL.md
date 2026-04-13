# memory - SKILL.md

## What this is
A multi-layer, multimodal memory system for AI agents. Stores and retrieves facts,
preferences, relationships, meetings, files, images, audio, and links across
sessions and multiple speakers.

## Initialize
from memory import MemorySystem
mem = MemorySystem(speaker_id="alice")

## At the START of every agent turn
results = mem.search("query about current topic")
# inject results.context into system prompt before generating response

## At the END of every agent turn
mem.save(content="fact or preference", memory_type="fact", speaker_id="alice")

## When user shares a file, image, audio, link, or meeting
mem.ingest(source_type="link", content="https://github.com/org/repo", speaker_id="alice")

## Pass tools to LLM
from memory.tools import TOOLS
# pass TOOLS to your provider's tool-calling API

## Tool call flow
memory_search  -> call at start of every turn
memory_ingest  -> call when user shares any file/URL/audio/image
memory_save    -> call after turn if something worth keeping was said
memory_delete  -> call when user says "forget that"
memory_update  -> call when a fact has changed
