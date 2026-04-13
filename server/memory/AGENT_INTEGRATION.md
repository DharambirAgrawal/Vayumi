# MemoryOS Agent Integration Guide

This file is the agent-facing operating guide for MemoryOS.
Read this file to know how to start the agent, pass context, call memory functions, control short-term memory, and manage personalization and emotion.

## What MemoryOS Does

MemoryOS gives your agent:
- Long-term memory search and retrieval
- Saving facts, preferences, events, relationships
- Ingesting links, files, images, audio, and meetings
- Updating and deleting memories
- Short-term turn memory for the active conversation
- User personalization and emotional trend tracking

## Core Rule

Use MemoryOS in three layers:
- Startup layer: always-on session context
- Turn layer: query-specific memory search context
- Session layer: short-term conversation turns and end-of-turn flush

Do not dump every memory into the prompt.
Always keep context bounded and relevant.

## Startup: What Happens First

When the agent process starts, or when a new user session begins, build the baseline system prompt automatically.

This startup context should include:
- Your normal assistant policy
- The active `speaker_id`
- The personalization profile from MemoryOS
- Any fixed session rules you want always present

Example:

```python
from memory import MemorySystem, MemoryType
from memory.tools import TOOLS

mem = MemorySystem(speaker_id="alice")

base_system_prompt = "You are a helpful assistant."
speaker_id = "alice"
user_model = mem.get_user_model(speaker_id)
profile_block = mem.personalization.to_system_prompt(user_model)

startup_system_prompt = (
    f"{base_system_prompt}\n\n"
    f"[SESSION]\n"
    f"Active speaker_id: {speaker_id}\n\n"
    f"{profile_block}"
)
```

What this means:
- The startup prompt is always loaded.
- It is the stable base for the whole session.
- Personalization belongs here because it should persist across turns.

## Every Turn: What Happens Next

At the start of every user turn, do a memory search for the current query.

```python
results = mem.search("user query here", speaker_id="alice")
turn_context = results.context
system_prompt = f"{startup_system_prompt}\n\n{turn_context}"
```

What this does:
- Pulls only relevant memories for the current question
- Keeps the prompt focused
- Adds fresh context on top of the startup baseline

The turn context should usually contain:
- Relevant facts
- Relevant preferences
- Relevant recent events
- Relevant meetings or links if they matter to the query

## During the Turn: What To Keep Updating

While the user is talking, keep the short-term buffer updated.

```python
mem.add_turn("alice", "latest user message text")
```

Use short-term memory for:
- Conversation history in the current session
- Local turn-by-turn continuity
- Later extraction into durable memories

Short-term memory is not the same as long-term memory.
It is meant to hold the active conversation until you flush it.

## What Happens In the Middle

During the middle of the conversation, the agent should continually do this loop:

1. Read the startup system prompt.
2. Search memory for the current query.
3. Merge search context into the prompt.
4. Respond to the user.
5. Add the turn to short-term memory.
6. Ingest shared files/links/images/audio/meetings immediately.
7. Save durable facts/preferences/events/relationships when they matter.
8. Update or delete memories if the user corrects something.

That is the normal operating cycle.

## Ingest Rules

If the user shares content, ingest it immediately.

```python
mem.ingest("link", "https://example.com", speaker_id="alice")
mem.ingest("file", file_base64, speaker_id="alice", title="notes")
mem.ingest("image", image_base64, speaker_id="alice", title="screenshot")
mem.ingest("audio", audio_base64, speaker_id="alice", title="voice note")
mem.ingest("meeting", transcript_text, speaker_id="alice", participants=["alice", "bob"])
```

Use ingest for:
- Links
- Files
- Images
- Audio
- Meeting transcripts

## Save Rules

Use `save()` for durable memory facts that should persist beyond the current turn.

```python
mem.save("Alice prefers concise responses", MemoryType.PREFERENCE, speaker_id="alice")
mem.save("Alice works on payments QA", MemoryType.FACT, speaker_id="alice")
mem.save("Alice has a meeting on Friday", MemoryType.EVENT, speaker_id="alice")
```

Use save for:
- Facts
- Preferences
- Events
- Relationships

Do not use save for every utterance.
Only save things that matter later.

## Update Rules

Use `update()` when you already know the memory id.

```python
mem.update(memory_id, "new corrected content", speaker_id="alice")
```

Use `update_by_query()` when the user corrects something but you do not have the id.

```python
mem.update_by_query(
    query="manager name is Jhon",
    new_content="manager name is John",
    speaker_id="alice",
)
```

Use update when:
- A fact changed
- A correction was made
- Old content needs to be replaced rather than duplicated

## Delete Rules

Use `delete()` for one exact memory.

```python
mem.delete(memory_id, speaker_id="alice")
```

Use `delete_links()` for link cleanup.

```python
mem.delete_links(speaker_id="alice", domain="github.com")
mem.delete_links(speaker_id="alice", delete_all=True)
```

Use delete when:
- The user says to forget something
- A wrong memory must be removed
- A whole domain of links should be cleared

## Short-Term Memory Control

Short-term memory stores the current conversation turns.

Use it to:
- Preserve the live conversation state
- Keep recent user messages available before flushing
- Feed the session summarizer at the end

Control it with:
- `add_turn(speaker_id, text)`
- `get_short_term()`
- `flush_session()`

Behavior:
- It accumulates recent turns
- It has a token budget internally
- Older turns drop out when needed
- It is cleared after flush

## Flush Behavior

At the end of a turn or after a meaningful chunk of conversation, call `flush_session()`.

```python
mem.flush_session()
```

What flush does:
- Reads short-term conversation turns
- Extracts save-worthy facts, preferences, events, and relationships
- Saves those durable memories
- Updates the personalization model
- Clears the short-term buffer

Think of flush as:
- Convert conversation -> summarized durable memory
- Update user model
- Reset session buffer

## Emotion and Personalization

MemoryOS tracks personalization through the user model.

The model can help your agent adapt:
- Response length
- Communication style
- Topics of interest
- Frequent people mentioned by the user
- Emotional pattern over time

Use `get_user_model()` to read it.

```python
model = mem.get_user_model("alice")
```

Use personalization in the startup prompt:

```python
profile_block = mem.personalization.to_system_prompt(model)
```

How emotion is handled:
- Short-term session content influences the user model
- Emotional trend gets updated at flush time
- The model can reflect patterns like stressed, positive, stable, or terse under pressure

How to control it:
- Feed `add_turn()` continuously during the conversation
- Call `flush_session()` at the end of the session or major interaction chunk
- Let MemoryOS update the user model from the transcript

Important:
- Emotion is not a separate prompt gimmick
- It is part of personalization
- It should shape tone and response style, not override the user’s actual request

## Context Budget and Prompt Safety

Memory context must stay bounded.

Use this rule:
- Startup prompt stays stable
- Search context is only for the current turn
- Large memories may be truncated in returned context
- Keep only the most relevant results in the prompt

Practical guidance:
- Search with a query relevant to the current user turn
- Use small `top_k` values unless the turn really needs more context
- Do not append every stored memory

## Constant Context Passing

The agent should keep context flowing across the conversation like this:

1. Startup system prompt is loaded once.
2. Each turn does a memory search.
3. Search context is appended to the startup prompt.
4. The current user turn is added to short-term memory.
5. End-of-turn flush turns the session into durable memory.
6. The updated personalization model is used in the next startup prompt.

That loop is the core of the system.

## Tool-Calling Support

Pass the tool schemas from MemoryOS to your tool-capable agent.

```python
from memory.tools import TOOLS
```

Available tools:
- `memory_search`
- `memory_ingest`
- `memory_save`
- `memory_update`
- `memory_update_by_query`
- `memory_delete`
- `memory_delete_links`
- `memory_get_user_model`
- `memory_add_turn`
- `memory_flush_session`

Recommended tool usage:
- Search at start of every turn
- Ingest when new user content arrives
- Save durable items at end of turn
- Update when facts change
- Delete when the user asks to forget
- Flush session when the conversation chunk ends

## Full Control Loop Example

```python
from memory import MemorySystem, MemoryType

mem = MemorySystem(speaker_id="alice")

# Startup
model = mem.get_user_model("alice")
startup_system_prompt = (
    "You are a helpful assistant.\n\n"
    "[SESSION]\nActive speaker_id: alice\n\n"
    f"{mem.personalization.to_system_prompt(model)}"
)

# Start of turn
query = "What did we decide about the release notes?"
search_results = mem.search(query, speaker_id="alice")
system_prompt = f"{startup_system_prompt}\n\n{search_results.context}"

# During turn
mem.add_turn("alice", query)

# If user shares content
mem.ingest("link", "https://example.com/release", speaker_id="alice")

# Save durable facts if needed
mem.save("Release notes should stay concise", MemoryType.PREFERENCE, speaker_id="alice")

# End of turn
mem.flush_session()
```

## What Not To Do

- Do not keep every past turn in the system prompt
- Do not skip the startup personalization block
- Do not use long-term save for every conversational line
- Do not forget to flush the short-term buffer
- Do not ignore corrections or forget requests

## Notes

- `MemoryType` values: fact, preference, event, relationship, link, file, image, audio, meeting.
- Use one `speaker_id` consistently per user.
- For async stacks, use `AsyncMemorySystem` from `memory.async_api`.