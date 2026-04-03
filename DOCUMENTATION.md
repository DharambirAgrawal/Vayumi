# Vayumi — Full Technical Documentation
### Superhuman Personal AI Agent: Architecture, Design, and Implementation Guide

**Version:** 2.3  
**Author:** Vayumi Project  
**Status:** Architecture & Design Phase  

---

## Table of Contents

1. [Project Vision](#1-project-vision)
   - 1.1 [Core Principles](#core-principles)
2. [System Overview](#2-system-overview)
3. [Multi-User Account Model](#3-multi-user-account-model)
   - 3.1 [How It Works](#31-how-it-works)
   - 3.2 [User Registration and Authentication](#32-user-registration-and-authentication)
   - 3.3 [Data Isolation Rules](#33-data-isolation-rules)
   - 3.4 [Per-User Configuration](#34-per-user-configuration)
   - 3.5 [Rate Limiting Per User](#35-rate-limiting-per-user)
4. [Architecture: The Central Consciousness](#4-architecture-the-central-consciousness)
   - 4.1 [What the Central Consciousness Does](#41-what-the-central-consciousness-does)
   - 4.2 [Orchestrator Prompt](#42-orchestrator-prompt-permanent-core)
   - 4.3 [Dynamic Context Injection](#43-dynamic-context-injection)
   - 4.4 [Token Budget Allocation](#44-token-budget-allocation)
5. [Context Engine — How Human-Like Context Works](#5-context-engine--how-human-like-context-works)
   - 5.1 [The Human Analogy](#51-the-human-analogy)
   - 5.2 [Persona Contexts](#52-persona-contexts)
   - 5.3 [Automatic Context Switch Example](#53-automatic-context-switch-example)
   - 5.4 [Context Switch Rules](#54-context-switch-rules)
6. [Memory System](#6-memory-system)
   - 6.1 [Three-Layer Architecture](#61-memory-architecture--three-layers)
   - 6.2 [Memory Write](#62-memory-write--when-and-how)
   - 6.3 [Memory Read](#63-memory-read--dynamic-retrieval)
   - 6.4 [Memory Ownership and Isolation](#64-memory-ownership-and-isolation)
   - 6.5 [Memory Sharing Between Personas](#65-memory-sharing-between-personas)
7. [Agent Layer — Multi-Agent Internal Loop](#7-agent-layer--multi-agent-internal-loop)
   - 7.1 [The Agents](#71-the-agents)
   - 7.2 [Multi-Run Agentic Loop](#72-multi-run-agentic-loop)
   - 7.3 [When Does Multi-Run Trigger?](#73-when-does-multi-run-trigger)
   - 7.4 [Long-Running Task Pattern](#74-long-running-task-pattern--instant-feedback--background-work)
   - 7.5 [Deferred Tasks — "Tell Me Later"](#75-deferred-tasks--tell-me-later)
8. [Skill System](#8-skill-system)
   - 8.1 [Skill vs MCP](#81-skill-vs-mcp)
   - 8.2 [Skill Registry](#82-skill-registry)
   - 8.3 [Skill Execution Flow](#83-skill-execution-flow)
   - 8.4 [Adding a New Skill](#84-adding-a-new-skill-zero-core-changes)
9. [MCP (Tool) Layer](#9-mcp-tool-layer)
   - 9.1 [MCP Categories](#91-mcp-categories)
   - 9.2 [MCP Registry](#92-mcp-registry)
   - 9.3 [Dynamic Flag Injection](#93-dynamic-flag-injection-via-mcp)
10. [Voice Pipeline](#10-voice-pipeline)
    - 10.1 [Full Audio Flow](#101-full-audio-flow)
    - 10.2 [Diarization + Speaker Identification](#102-diarization--speaker-identification)
      - [Realistic Accuracy Expectations](#realistic-accuracy-expectations)
      - [Learning a New Person — "Meet Chris" Flow](#learning-a-new-person--meet-chris-flow)
      - [Phase 1 Person Detection Scope (In/Out)](#phase-1-person-detection-scope-inout)
    - 10.3 [Echo Cancellation and Self-Voice Suppression](#103-echo-cancellation-and-self-voice-suppression)
    - 10.4 [Streaming Response](#104-streaming-response-speak-while-thinking)
    - 10.5 [Kokoro-ONNX TTS](#105-kokoro-onnx-tts-integration)
11. [Interrupt and Mode Handling](#11-interrupt-and-mode-handling)
    - 11.1 [Interrupt Detection](#111-interrupt-detection)
    - 11.2 [Mode System](#112-mode-system)
    - 11.3 [Wake Word and Activation Model](#113-wake-word-and-activation-model)
12. [Client/Server Architecture](#12-clientserver-architecture)
    - 12.1 [Design Principle](#121-design-principle)
    - 12.2 [Server Stack](#122-server-stack)
    - 12.3 [Client Stack (Browser)](#123-client-stack-browser)
    - 12.4 [Client Stack (ESP32-S3-AUDIO-Board)](#124-client-stack-esp32-s3-audio-board)
    - 12.5 [WebSocket Protocol](#125-websocket-protocol)
    - 12.6 [Unified WebSocket Handler](#126-unified-websocket-handler--single-entry-point)
    - 12.7 [Session Management](#127-session-management)
    - 12.8 [Response Streaming](#128-response-streaming)
13. [Data Storage Design](#13-data-storage-design)
    - 13.1 [SQLite Schema](#131-sqlite-schema)
    - 13.2 [Vector DB (ChromaDB)](#132-vector-db-chromadb)
    - 13.3 [Embedding Strategy](#133-embedding-strategy)
    - 13.4 [SQLite Concurrency](#134-sqlite-concurrency)
14. [LLM Strategy — Groq + Gemini](#14-llm-strategy--groq--gemini)
    - 14.1 [Model Routing](#141-model-routing)
    - 14.2 [Rate Limit Management](#142-rate-limit-management)
    - 14.3 [Streaming Implementation](#143-streaming-implementation)
15. [API and Communication Contracts](#15-api-and-communication-contracts)
    - 15.1 [Internal Agent Interface](#151-internal-agent-interface)
    - 15.2 [Skill Interface Contract](#152-skill-interface-contract)
16. [Concurrency Model](#16-concurrency-model)
17. [Error Handling and Resilience](#17-error-handling-and-resilience)
18. [Security and Trust Model](#18-security-and-trust-model)
    - 18.1 [LLM Command Trust](#181-llm-command-trust)
    - 18.2 [Client Trust](#182-client-trust)
    - 18.3 [User Data Isolation](#183-user-data-isolation)
19. [Phase 1 Build Plan](#19-phase-1-build-plan)
    - 19.1 [Phase 1 Components](#191-phase-1-components)
    - 19.2 [Phase 1 Milestones](#192-phase-1-milestones)
    - 19.3 [Phase 2 (Future)](#193-phase-2-future)
20. [Future Extensibility](#20-future-extensibility)
    - [Appendix A: Directory Structure](#appendix-a-directory-structure)
    - [Appendix B: Key Design Decisions](#appendix-b-key-design-decisions-rationale)
    - [Appendix C: Environment Setup](#appendix-c-environment-setup)

---

## 1. Project Vision

Vayumi is a **superhuman personal AI agent** — a Jarvis-like intelligence that lives beside you. It does not just answer questions. It listens, understands context, remembers people and meetings, takes actions on your behalf, and grows more personalized over time.

Multiple users can each have their own Vayumi account on the same server — like having separate accounts on the same platform. Each user gets their own profile, memories, reminders, contacts, and conversation history, completely isolated from other users.

### Core Principles

**1. Context flows automatically, not manually.**  
Just like a human doesn't consciously decide "I am now speaking to my professor, I should be formal" — it just happens. Vayumi builds and switches context automatically based on who is speaking, what mode it is in, and what has happened in recent memory.

**2. Minimum context, maximum intelligence.**  
The system is designed so that at any given moment, only the *relevant* context is loaded into the LLM's window. Memory exists in layers — permanent identity, medium-term episodic, and short-term conversational — and only what is needed for the current task is surfaced.

**3. Text in, text out. Everything else is internal.**  
The core of Vayumi is a clean pipeline: audio or text comes in, passes through intelligence layers, and text or audio goes out. All complexity — multi-agent reasoning, memory retrieval, skill execution, MCP calls — happens inside this pipeline invisibly.

**4. Scales infinitely by design.**  
Adding a new skill or MCP tool should require zero changes to the core. You write a skill file or register an MCP, and Vayumi discovers it automatically.

**5. Client and server are fully separated.**  
The server holds all intelligence. The client (ESP32, browser, phone app) only needs to stream audio/text and receive responses. Switching clients requires no server changes.

**6. Multi-user by default.**  
Every piece of data — memories, reminders, contacts, sessions — is owned by a specific user. The system never mixes data between users. Adding a new user requires zero code changes.

---

## 2. System Overview

```
┌─────────────────────────────────────────────────────────┐
│                        CLIENT                           │
│  (Browser / ESP32 / Mobile App)                         │
│                                                         │
│  • Login/auth → get session token                       │
│  • Microphone → WebSocket stream                        │
│  • Speaker ← TTS audio stream                           │
│  • UI display ← text/status events                      │
│  • Button/voice commands → mode switch events           │
└──────────────────────┬──────────────────────────────────┘
                       │ WebSocket (bidirectional)
                       │ Events: audio_chunk, text_in,
                       │         interrupt, mode_switch,
                       │         speaker_change
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 VAYUMI SERVER                            │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │              AUTH + SESSION LAYER                 │   │
│  │  • User authentication (token-based)             │   │
│  │  • Session creation with user_id binding         │   │
│  │  • All downstream queries scoped to user_id      │   │
│  └─────────────────────┬────────────────────────────┘   │
│                        │                                 │
│  ┌─────────────────────▼────────────────────────────┐   │
│  │              INPUT GATEWAY                       │   │
│  │  • Groq Whisper STT + Diarization               │   │
│  │  • Speaker identification (within user session)  │   │
│  │  • Interrupt detection                           │   │
│  │  • Mode gate (meeting / normal / focus)          │   │
│  └─────────────────────┬────────────────────────────┘   │
│                        │                                 │
│  ┌─────────────────────▼────────────────────────────┐   │
│  │          CENTRAL CONSCIOUSNESS                   │   │
│  │  (Orchestrator Agent)                            │   │
│  │                                                  │   │
│  │  • Dynamic context builder (user-scoped)         │   │
│  │  • Persona context selector                      │   │
│  │  • Intent router                                 │   │
│  │  • Multi-agent coordinator                       │   │
│  │  • Skill registry lookup                         │   │
│  │  • MCP registry lookup                           │   │
│  └──┬──────────┬──────────┬──────────┬─────────────┘   │
│     │          │          │          │                   │
│  ┌──▼──┐  ┌───▼──┐  ┌────▼──┐  ┌───▼────┐              │
│  │MEM  │  │TASK  │  │SEARCH │  │PERSONA │              │
│  │AGENT│  │AGENT │  │AGENT  │  │AGENT   │              │
│  └──┬──┘  └───┬──┘  └────┬──┘  └───┬────┘              │
│     │         │           │         │                    │
│  ┌──▼─────────▼───────────▼─────────▼────────────────┐  │
│  │                  SKILL RUNNER                      │  │
│  │  • Loads skill .md files on demand                │  │
│  │  • Executes skill logic                           │  │
│  │  • Returns structured result                      │  │
│  └───────────────────────┬───────────────────────────┘  │
│                          │                               │
│  ┌───────────────────────▼──────────────────────────┐   │
│  │              OUTPUT GATEWAY                      │   │
│  │  • Response assembly                             │   │
│  │  • Kokoro-ONNX TTS (local)                       │   │
│  │  • Audio stream to client                        │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │          STORAGE LAYER (user-scoped)             │   │
│  │  • SQLite (structured: meetings, reminders)      │   │
│  │  • ChromaDB (semantic memory search)             │   │
│  │  • File store (docs, outputs)                    │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Multi-User Account Model

Vayumi supports multiple users on the same server, the same way a platform like Claude or Facebook works — one shared infrastructure, but each user has their own completely isolated account.

### 3.1 How It Works

Each registered user gets:
- Their own **profile** (name, preferences, tone, goals)
- Their own **memories** (conversations, episodic memory, meeting notes)
- Their own **reminders, contacts, and calendar data**
- Their own **conversation sessions** (working memory)
- Their own **persona contexts** (people they interact with)
- Their own **MCP configurations** (which integrations are enabled)

User A cannot see User B's reminders, memories, or conversations. The server is shared, but data is completely separated.

### 3.2 User Registration and Authentication

```python
class UserAccount:
    user_id: str              # Unique identifier (e.g., "user_rahul")
    display_name: str         # "Rahul"
    email: str                # For login
    password_hash: str        # bcrypt hashed
    voice_embedding: bytes    # For voice-based identification
    embedding_model_version: str  # Track which model generated this embedding
    profile: dict             # JSON: occupation, goals, tone, language (stored as TEXT in SQLite)
    enabled_mcps: list        # JSON array of enabled MCP names
    created_at: datetime
```

Authentication flow:
1. **Browser/Mobile**: User logs in with email/password, receives a JWT token
2. **ESP32**: Uses a pre-shared device token linked to a user_id
3. **WebSocket (canonical)**: First client message must be `{"type":"auth","token":"..."}`.
4. **Compatibility mode (optional)**: Query-param token may be accepted only for legacy clients, but is not the primary path.
5. Every request after authentication is scoped to that `user_id`

### 3.3 Data Isolation Rules

Every database table and vector DB query includes a `user_id` filter. There is no way to accidentally access another user's data.

```python
ISOLATION_RULES = {
    "memories":     "WHERE user_id = :current_user_id",
    "reminders":    "WHERE user_id = :current_user_id",
    "meetings":     "WHERE user_id = :current_user_id",
    "contacts":     "WHERE user_id = :current_user_id",
    "flags":        "WHERE user_id = :current_user_id",
    "vector_search": "filter={'user_id': current_user_id}",
}
```

### 3.4 Per-User Configuration

Instead of a single global config, each user has their own profile stored in the `users` table:

```json
{
  "user_id": "user_rahul",
  "display_name": "Rahul",
  "profile": {
    "occupation": "CS student",
    "goals": ["Build Vayumi", "Learn AI agents"],
    "tone_preference": "casual and direct",
    "language": "en"
  },
  "enabled_mcps": ["web_search", "gmail"]
}
```

Permanent memory (Layer 1) is loaded from this per-user profile, not from a global file.

### 3.5 Rate Limiting Per User

With multiple users making concurrent requests, rate limits are tracked per user to ensure fairness:

```python
class PerUserRateLimiter:
    def __init__(self, max_rpm_per_user=10, max_tpm_per_user=50000):
        self.user_usage = {}  # user_id -> {rpm_count, tpm_count, window_start}

    def check(self, user_id, estimated_tokens):
        usage = self.user_usage.get(user_id, new_window())
        if usage.rpm_count >= self.max_rpm_per_user:
            return False, "Rate limit reached, please wait"
        if usage.tpm_count + estimated_tokens > self.max_tpm_per_user:
            return False, "Token budget exhausted for this window"
        return True, None
```

The global LLM rate limits (Groq API limits) are still tracked globally, but the per-user limiter ensures one user cannot starve others.

---

## 4. Architecture: The Central Consciousness

The Central Consciousness is **not a single LLM call.** It is an orchestrator — a coordinator that decides *which agents need to run*, *what context to inject*, and *how to assemble the final response*. Think of it as the prefrontal cortex: it doesn't do all the thinking, but it coordinates what runs and what doesn't.

### 4.1 What the Central Consciousness Does

1. **Receives** the parsed input (text + speaker ID + user_id + interrupt flag + mode)
2. **Builds** the minimal context window for this turn (permanent prompt + user profile + dynamic inject + conversation window)
3. **Decides** whether this is conversational (direct reply), tool-requiring (run skill/MCP), background (run memory agent silently), or complex (multi-agent loop)
4. **Coordinates** agents running in parallel where possible
5. **Streams** partial responses to the output gateway while agents are still running
6. **Commits** memory updates and logs after response is delivered (scoped to user_id)

### 4.2 Orchestrator Prompt (Permanent Core)

This is the smallest possible permanent system prompt — it defines Vayumi's identity and how it thinks. It never changes at runtime.

```text
You are Vayumi, a superhuman personal AI agent.
You are always aware of:
- Who you are serving (the authenticated user's profile)
- Who is speaking (speaker_id from diarizer)
- What mode you are in (normal / meeting / focus)
- What context is active (loaded from context engine)
- What skills and tools are available (from registry summaries)

Your job in each turn:
1. Understand intent
2. Decide: respond directly OR route to skill/tool OR run multi-step
3. Never fake capabilities — if you cannot do it, say so honestly
4. Respond naturally like a human assistant would
5. Be brief unless depth is needed
```

Everything else — user profile, persona contexts, recent memory, skill list — is **dynamically injected** per turn. The permanent prompt stays under 300 tokens.

### 4.3 Dynamic Context Injection

Each turn, the context builder assembles the LLM input like this:

```text
[PERMANENT SYSTEM PROMPT]          ← ~300 tokens, always present
[USER IDENTITY BLOCK]              ← ~150 tokens, loaded from authenticated user's profile
[ACTIVE PERSONA CONTEXT]           ← ~200 tokens, depends on speaker in the room
[INJECTED FLAGS]                   ← 0-100 tokens, only if something happened
[RELEVANT MEMORIES]                ← 0-500 tokens, retrieved by vector search (user-scoped)
[SKILL REGISTRY SUMMARY]           ← ~100 tokens, names + 1-line descriptions only
[MCP REGISTRY SUMMARY]             ← ~50 tokens, user's enabled MCPs listed
[CONVERSATION WINDOW]              ← last N turns, trimmed to fit budget
[CURRENT INPUT]                    ← the user's message this turn
```

The context builder has a **token budget** system. If memories + conversation history would exceed budget, older conversation is trimmed first, then less-relevant memories are dropped.

### 4.4 Token Budget Allocation

The total context budget varies by task complexity:

| Scenario | Total Budget | Breakdown |
|---|---|---|
| Simple conversation | ~2500 tokens | 300 system + 150 user + 200 persona + 100 skills + 50 MCPs + ~1700 for conversation + input |
| With memory retrieval | ~3000 tokens | Above + up to 500 tokens of retrieved memories |
| Complex task (skill) | ~4000 tokens | Above + skill doc injected (~1000 tokens) |
| Meeting mode | ~3500 tokens | Larger conversation window for meeting context |

Priority when trimming to fit budget:
1. Drop oldest conversation turns first
2. Reduce retrieved memories from 5 to 3 to 1
3. Never trim: system prompt, user identity, current input

---

## 5. Context Engine — How Human-Like Context Works

This is the most important and unique part of Vayumi's design. The goal is to replicate how humans naturally shift context based on who they are talking to, without any manual configuration per conversation.

### 5.1 The Human Analogy

When you talk to:
- **Your mother**: casual, warm, no technical jargon, family-aware topics are active
- **Your professor**: formal, task-focused, academic topics are active
- **A recruiter**: professional, career-focused, interview mode
- **A friend**: relaxed, wide range of topics, inside jokes possible

You don't *decide* to switch — it happens automatically. The context is shaped by **who is present** and **what the recent history of that relationship is.**

Vayumi replicates this through **Persona Contexts** — and each user has their own set of personas.

### 5.2 Persona Contexts

A Persona Context is a small profile block that gets injected when a recognized speaker is active. Each persona belongs to a specific user.

```json
{
  "persona_id": "rahul_self",
  "user_id": "user_rahul",
  "name": "Rahul",
  "role": "account_owner",
  "tone": "casual and direct",
  "known_facts": [
    "CS student, building Vayumi",
    "Uses Groq and HuggingFace",
    "Previous project: web reader skill"
  ],
  "active_topics": ["AI agents", "memory systems", "ESP32"],
  "memory_access": "full"
}
```

```json
{
  "persona_id": "guest_unknown",
  "user_id": "user_rahul",
  "name": "Unknown Guest",
  "role": "visitor",
  "tone": "polite and neutral",
  "known_facts": [],
  "active_topics": [],
  "memory_access": "none"
}
```

When the diarizer detects a speaker change, the context engine:
1. Identifies speaker (by voice embedding or name if introduced)
2. Loads their Persona Context (scoped to the authenticated user's persona list)
3. Hides sensitive/personal context that shouldn't be shared with non-owners
4. Adjusts tone directive accordingly

### 5.3 Automatic Context Switch Example

```text
Situation: Rahul (authenticated user) is working with Vayumi.
           A friend walks in.

Timeline:
T=0    Vayumi is in deep work context with Rahul — reading emails,
       technical tone, full memory access.

T=1    Diarizer detects new speaker (Speaker_2).
       No voice match found → load "guest" persona.
       
T=2    Vayumi automatically:
       - Hides Rahul's private context from response
       - Shifts tone to "warm, neutral, greeting mode"
       - Reduces memory access to public-only
       - Does NOT forget Rahul's session (still held in working memory)
       
T=3    Friend says: "Is this Vayumi? Can I try?"
       Vayumi responds: "Hi! Yes, I'm Vayumi. What's your name?"
       
T=4    Rahul says: "Actually, can you also check my 3pm reminder?"
       Diarizer confirms Speaker_1 = Rahul (account owner).
       Vayumi handles BOTH: responds to Rahul's reminder AND
       continues greeting the friend — multi-speaker aware.
       
T=5    Friend leaves (silence from Speaker_2 for threshold period).
       Vayumi context engine notes guest departure.
       Full context restored for Rahul.
```

This is not managed by the LLM's prompt alone — it is managed by the **context engine as infrastructure** that wraps what the LLM sees.

### 5.4 Context Switch Rules

```python
class ContextSwitchRules:
    GUEST_ARRIVAL_THRESHOLD_SECONDS = 2
    GUEST_DEPARTURE_THRESHOLD_SECONDS = 30

    HIDE_FROM_NON_OWNER = [
        "user_private_memories",
        "email_content",
        "calendar_details",
        "financial_data",
        "reminders"
    ]

    TONE_MAP = {
        "account_owner": "casual, personalized, full context",
        "known_contact": "warm, context from relationship history",
        "guest": "polite, neutral, minimal context",
        "unknown": "friendly but cautious"
    }
```

---

## 6. Memory System

Memory is the hardest problem in AI agents. The goal: **store everything, surface only what matters, use minimum tokens.**

All memory is **owned by a user**. User A's memories are never visible to User B.

### 6.1 Memory Architecture — Three Layers

```
┌─────────────────────────────────────────────────────┐
│  LAYER 1: PERMANENT MEMORY                          │
│  (Always injected, never changes unless updated)    │
│                                                     │
│  • User identity (name, occupation, goals)          │
│  • Core preferences (tone, language, style)         │
│  • Key relationships (family, colleagues)           │
│  • System capabilities (what Vayumi can/can't do)   │
│                                                     │
│  Storage: users table → profile JSON field          │
│  Size: <200 tokens per user                         │
│  Scope: per user_id                                 │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  LAYER 2: EPISODIC MEMORY                           │
│  (Retrieved on demand via semantic search)          │
│                                                     │
│  • Past conversations (summarized)                  │
│  • Meetings attended + notes                        │
│  • Tasks completed / pending                        │
│  • Important events with timestamps                 │
│  • Relationship history per person                  │
│                                                     │
│  Storage: ChromaDB (Phase 1, migrate to Qdrant      │
│  for production) + SQLite for structured fields     │
│  Size: Unlimited. Only top-K retrieved per turn.    │
│  Scope: per user_id                                 │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  LAYER 3: WORKING MEMORY                            │
│  (Active conversation window, discarded after)      │
│                                                     │
│  • Last N turns of current conversation             │
│  • Current task state                               │
│  • Active skill execution context                   │
│  • Injected flags (email arrived, reminder due)     │
│                                                     │
│  Storage: Python dict (Phase 1 single-instance)     │
│  Future: Redis for multi-instance deployment        │
│  Size: Managed to fit token budget                  │
│  Scope: per session (session is bound to user_id)   │
└─────────────────────────────────────────────────────┘
```

### 6.2 Memory Write — When and How

Memory is written by the **Memory Agent** running in the background after each response. It does NOT block the response. The flow is:

```text
User speaks → Vayumi responds (immediate)
                     ↓ (async, after response)
             Memory Agent wakes up
             → Decides if this turn is "memorable"
             → Summarizes if conversation chunk > threshold
             → Embeds and stores in ChromaDB (tagged with user_id)
             → Updates SQLite if structured data (date, person, task)
```

**What gets saved:**
- Conversations summarized every 10-20 turns into episodic chunks
- Explicit things user said to remember
- Meeting notes (in meeting mode, everything is captured)
- Tasks and reminders with timestamps
- People mentioned with context

**What does NOT get saved:**
- Every single turn verbatim (too much storage, too many tokens to retrieve)
- Skill execution logs (discarded after success/failure noted)
- TTS audio (only text)

### 6.3 Memory Read — Dynamic Retrieval

When building context for a turn, the memory agent does:

```python
def retrieve_relevant_memories(user_input, user_id, speaker_id, mode, top_k=5):
    query_embedding = embed(user_input)

    results = vector_db.query(
        embedding=query_embedding,
        filter={"user_id": user_id},
        top_k=top_k
    )

    if has_time_reference(user_input):
        time_results = sqlite.query_by_date(user_id=user_id, date=today)
        results += time_results

    return format_for_injection(results)
```

Example injection into context:

```text
[RELEVANT MEMORIES]
- 2 days ago: Discussed Vayumi memory architecture, decided on 3-layer system
- Yesterday: Had meeting with Prof. Sharma, topic: project deadline March 15
- Today 9am: Reminder set for "submit assignment"
```

### 6.4 Memory Ownership and Isolation

Every memory record has a `user_id` field. This is enforced at the storage layer — not by the LLM.

```python
class MemoryRecord:
    id: str
    user_id: str            # Owner of this memory
    speaker_id: str         # Who was speaking when this was recorded
    content: str            # Summarized content
    embedding_id: str       # Reference to vector DB
    timestamp: datetime
    sensitivity: str        # "private" | "shared" | "public"
    tags: list[str]
```

When User A queries memories, the storage layer automatically adds `WHERE user_id = 'user_a'`. There is no code path that can retrieve User B's memories from User A's session.

### 6.5 Memory Sharing Between Personas

Within a single user's session, memory is filtered by **persona access level** at retrieval time:

```python
PERSONA_MEMORY_ACCESS = {
    "account_owner": "all",          # The authenticated user sees everything
    "known_contact": "shared_only",  # See memories tagged as shareable
    "guest": "none",                 # No memory access
}
```

The Memory Agent tags every memory with sensitivity when writing: `private`, `shared`, or `public`. When a guest is present in the room, only `public` memories (if any) are surfaced.

---

## 7. Agent Layer — Multi-Agent Internal Loop

Vayumi is not a single LLM call. It is a **team of specialized agents** coordinated by the Central Consciousness. Each agent runs a focused LLM call on a smaller, specific task.

### 7.1 The Agents

| Agent | Responsibility | Runs |
|---|---|---|
| **Orchestrator** | Decides what to do, routes, assembles final response | Every turn |
| **Memory Agent** | Reads + writes memory, retrieves relevant context | Background (async) |
| **Task Agent** | Handles multi-step task execution, calls skills | When task detected |
| **Search Agent** | Decides if web search needed, runs it, summarizes | On demand |
| **Persona Agent** | Manages speaker state, context switching | On speaker change |
| **Interrupt Handler** | Detects interruptions mid-speech, stops/redirects | Continuous listener |

All agents receive a `user_id` in their context so every operation is user-scoped.

### 7.2 Multi-Run Agentic Loop

For complex tasks (e.g., "read this PDF and summarize action items"), the Task Agent runs multiple passes:

```text
Turn: "Read the PDF I uploaded and list action items"

Pass 1 (Orchestrator):
  → Intent: complex document task
  → Load skill: pdf_reader
  → Route to Task Agent

Pass 2 (Task Agent):
  → Read skill doc: skills/pdf_reader/SKILL.md
  → Understand: requires python, extract text
  → Plan: [extract_text, chunk, summarize_each_chunk, aggregate]
  → Execute plan step by step

Pass 3 (Task Agent, after extraction):
  → Text extracted successfully
  → Now summarize with LLM: list action items

Pass 4 (Orchestrator):
  → Receive result from Task Agent
  → Format naturally
  → Stream to output

[Background] Memory Agent:
  → Log: "User processed PDF: meeting_notes.pdf" (tagged with user_id)
  → Store summary in episodic memory with timestamp
```

The user sees a smooth response. They do not see any of the passes happening.

### 7.3 When Does Multi-Run Trigger?

```python
MULTI_RUN_TRIGGERS = [
    "task requires skill execution",
    "task requires reading skill documentation first",
    "task has more than 2 dependent steps",
    "search needed + then reasoning on results",
    "MCP call + interpretation required",
    "result quality check needed (self-review pass)"
]
```

For simple conversation, only the Orchestrator runs. For skill execution, Task Agent joins. Memory Agent always runs in background.

### 7.4 Long-Running Task Pattern — Instant Feedback + Background Work

Many tasks (skill execution, web scraping, PDF reading, complex searches) take 1-30 seconds in Phase 1. The user should **never sit in silence** during this time. The pattern is:

```text
Phase 1: INSTANT ACKNOWLEDGMENT (< 500ms after intent parsed)
  → Orchestrator detects: this task will take time
  → Immediately generates a short acknowledgment:
    "Sure, let me read that for you."
    "On it — checking that now."
    "Let me pull that up, one moment."
  → Acknowledgment is streamed to TTS + text instantly
  → User hears Vayumi respond immediately

Phase 2: BACKGROUND EXECUTION (1-30 seconds in Phase 1)
  → Task Agent / Skill runs in background (asyncio task)
  → Session state tracks: task_id, status, started_at
  → If task takes >10 seconds, optional progress update:
    "Still reading — it's a long article."
  → Client shows processing indicator

Phase 3: RESULT DELIVERY
  → Task completes → result returned to Orchestrator
  → Orchestrator formats result naturally
  → Streams to user sentence by sentence
  → Memory Agent logs the result in background
```

```python
async def handle_long_task(orchestrator, session, intent, task_fn):
    # Orchestrator PREPARES content + state transitions.
    # ws/handler.py owns stream_response() and actual client streaming.
    ack = generate_instant_ack(intent)
    session.task_state = {"status": "running", "started_at": time.time()}
    result = await task_fn()
    session.task_state = {"status": "idle"}
    formatted = await orchestrator.format_result(session, result)
    return {"ack": ack, "result": formatted}
```

This pattern applies to: skill execution, multi-step searches, document processing, any MCP that takes >2 seconds. For fast operations (<1 second, like setting a reminder), the response is just delivered directly — no acknowledgment needed.

### 7.5 Deferred Tasks — "Tell Me Later"

Users can request information and defer the delivery:

```text
User types URL + says: "Read this, I'll ask you about it later"

1. Orchestrator detects: read intent + defer intent
2. Instant ack: "Got it, I'll read that and keep it ready."
3. Skill runs in background → result stored in episodic memory
   tagged: {user_id, artifact_type: "deferred_read", source_url, summary, created_at}
4. User does 50 more conversations about other things
5. Later, user says: "What was that article about?"
6. Memory retrieval: semantic search + artifact_type filter matches the stored summary
7. Vayumi responds with the summary — even hours/days later
```

This works because the result is stored in episodic memory (ChromaDB + SQLite), not just working memory. Working memory would lose it after the session ends. Episodic memory persists forever.

---

## 8. Skill System

A **skill** is a documented capability that requires time or execution — reading a PDF, generating a document, scraping a webpage. Skills are NOT always-available. They are looked up when needed and executed when triggered.

Skills are independent add-ons. Adding or removing a skill requires zero changes to the core system. Execution isolation for skills will be designed per-skill when they are built.

### 8.1 Skill vs MCP

| | Skill | MCP (Tool) |
|---|---|---|
| **What it is** | A documented multi-step capability | A callable function/API |
| **Stored as** | Markdown file (SKILL.md) | Registered endpoint |
| **Speed** | Slower (execution time) | Fast (API call) |
| **When loaded** | On demand when task matches | Some always-on, rest on demand |
| **Context cost** | Only the relevant skill doc loaded | Only the tool name+description |
| **Examples** | PDF reader, doc generator, web scraper | Web search, calendar, email |

**Key insight:** Skills are like instructional manuals. When Vayumi needs to do something complex, it looks up the manual (skill doc), reads it, then executes. It doesn't read all manuals all the time — only the one it needs.

### 8.2 Skill Registry

The skill registry is a lightweight index — **only names and one-line descriptions.** The full skill doc is never loaded into context unless that skill is being executed.

```json
{
  "skills": [
    {
      "id": "web_reader",
      "name": "Web Reader",
      "description": "Given a URL, reads the page content and answers questions about it",
      "trigger_keywords": ["url", "website", "read this link", "open this"],
      "doc_path": "skills/web_reader/SKILL.md"
    },
    {
      "id": "pdf_reader",
      "name": "PDF Reader",
      "description": "Reads and extracts content from uploaded PDF files",
      "trigger_keywords": ["pdf", "document", "file"],
      "doc_path": "skills/pdf_reader/SKILL.md"
    }
  ]
}
```

This registry (~100 tokens) is always in context. The full skill doc (~1000+ tokens) is only injected when that skill is being used.

### 8.3 Skill Execution Flow

URLs, file paths, and similar inputs come via **text input** (typed in the chat UI), not voice — you can't speak a URL. The voice and text paths converge at the orchestrator.

```text
User types in chat: "Read this https://example.com/article and tell me the main points"
  OR
User says: "Read that link I just sent" (URL was sent via text a moment ago)

1. Orchestrator sees: "URL present + read intent"
2. Immediate acknowledgment → "Sure, let me read that for you."
   (streamed to TTS + text immediately — user gets instant feedback)
3. Skill registry lookup → matches "web_reader"
4. Task Agent loads: skills/web_reader/SKILL.md
5. Skill run.py executes:
   - Fetches the URL
   - Strips HTML, extracts clean text (no raw HTML goes to LLM)
   - Writes clean text to output.json
6. Task Agent receives clean text → LLM summarizes (only clean text, not raw page)
7. Orchestrator formats response → streams to user
8. Skill doc removed from context (not needed anymore)
```

**Key details:**
- The skill's `run.py` handles all extraction and cleaning. The LLM never sees raw HTML — only clean, extracted text.
- The user gets instant voice/text feedback ("Sure, let me read that") before the skill runs. They don't sit in silence wondering if Vayumi heard them.

### 8.4 Adding a New Skill (Zero Core Changes)

To add a new skill:
1. Create `skills/your_skill/SKILL.md` with documentation
2. Create `skills/your_skill/run.py` with execution logic
3. Add one entry to `skill_registry.json`
4. Done — Vayumi can now use it

No changes to orchestrator, no changes to agents, no changes to server.

---

## 9. MCP (Tool) Layer

MCPs are **callable tools** — fast, atomic operations that return a result. Think of them as APIs Vayumi can call. Each user can enable/disable MCPs independently.

### 9.1 MCP Categories

**Always-On MCPs** (always listed in context, Vayumi can call any time):

```text
- web_search: Search the web for current information
- get_datetime: Current date and time
- set_reminder: Create a reminder (scoped to user_id)
- get_reminders: List today's reminders (scoped to user_id)
```

**On-Demand MCPs** (registered but not in permanent context, enabled per user):

```text
- gmail: Read/send email (loaded when user enables email integration)
- google_calendar: Read/create calendar events
- smart_home: Control lights, temperature (when connected)
```

### 9.2 MCP Registry

```json
{
  "always_on": [
    {
      "name": "web_search",
      "description": "Search the web. Use for: news, prices, current events, facts that may have changed.",
      "when_to_use": "When user asks about something time-sensitive or you don't know the answer"
    },
    {
      "name": "set_reminder",
      "description": "Set a timed reminder for the user",
      "when_to_use": "When user says 'remind me' or sets a time-based task"
    }
  ],
  "on_demand": [
    {
      "name": "gmail",
      "description": "Read and send emails from user's Gmail",
      "requires_auth": true
    }
  ]
}
```

### 9.3 Dynamic Flag Injection via MCP

External services can push flags into Vayumi's context mid-conversation. Flags are scoped to the user who owns that integration.

**Example — Email Arrival:**

```text
Background: Gmail MCP is monitoring User A's inbox.
Event: New email arrives from "Prof. Sharma"

Gmail MCP pushes flag to Vayumi server:
{
  "type": "flag_inject",
  "user_id": "user_rahul",
  "source": "gmail",
  "data": {
    "event": "new_email",
    "from": "Prof. Sharma",
    "subject": "Project Deadline Update",
    "email_id": "msg_abc123",
    "preview": "The deadline has been moved..."
  }
}

Context builder injects into Rahul's next turn:
[INJECTED FLAG]
New email from Prof. Sharma: "Project Deadline Update"
Email ID: msg_abc123 (use gmail MCP to read full content if asked)

Vayumi says naturally: "By the way, you just got an email from Prof. Sharma 
about your project deadline. Want me to read it?"
```

The email full content is NOT loaded — only the flag. If user says "yes, read it", then the gmail MCP is called with the stored `email_id`.

---

## 10. Voice Pipeline

### 10.1 Full Audio Flow

```text
MICROPHONE (Client)
    ↓ raw audio chunks (WebSocket, authenticated session)

[0] ECHO CANCELLATION (before anything else)
    → ESP32: hardware AEC removes Vayumi's own speaker output from mic input
      (server receives clean audio — never hears Vayumi's voice)
    → Browser: Web Audio API echoCancellation + server-side state gating
    → Server gating: during playback_state=PLAYING, VAD uses higher
      energy threshold + minimum duration to avoid false triggers
    
INPUT GATEWAY (Server)
    ↓
[1] VOICE ACTIVITY DETECTION
    → Detects speech vs silence
    → Only sends speech segments for STT
    → Echo-aware: checks session.playback_state before treating
      detected speech as user input (see Section 10.3)
    
[2] GROQ WHISPER STT
    → Transcribes speech to text
    → Fast, accurate, supports multiple languages
    
[3] DIARIZER
    → Speaker segmentation (Speaker_1, Speaker_2, ...)
    → Voice embedding comparison to user's known speakers
    → Returns: {text, speaker_id, timestamp, confidence}
    
[4] INTERRUPT DETECTION
    → Is this interrupting an ongoing Vayumi response?
    → If yes: flag interrupt + emit interrupt event
    → Echo-cancelled audio means only real user speech triggers this
    
[5] MODE GATE
    → Meeting mode? → Log everything, selective response
    → Normal mode? → Pass to Central Consciousness
    
CENTRAL CONSCIOUSNESS (processes, responds — user-scoped)
    ↓
[6] KOKORO-ONNX TTS (Local, Fast)
    → Text → Audio
    → Streaming: starts speaking before full text is ready
    → Voice is consistent, natural
    
[7] AUDIO STREAM → Client
    → WebSocket audio chunks
    → Client plays immediately
    → Server sets session.playback_state = PLAYING
    → Client sends {"type":"playback_done"} when finished
      → Server sets session.playback_state = IDLE
```

### 10.2 Diarization + Speaker Identification

#### Embedding Model: SpeechBrain ECAPA-TDNN

The diarizer uses **SpeechBrain's ECAPA-TDNN model** (`spkrec-ecapa-voxceleb`) for voice embeddings:

- **Accuracy:** State-of-the-art for speaker verification — achieves the ~90% owner-vs-guest accuracy documented below
- **Latency:** ~200-400ms per embedding on CPU. Acceptable for Phase 1 since diarization runs in parallel with STT, not sequentially
- **Model size:** ~400MB download (cached after first run)
- **Output:** 192-dimensional embedding vector per audio segment

The model is loaded once at server startup and shared across all sessions.

#### How It Works

Speaker identification works within the context of the authenticated user's known contacts:

```python
from speechbrain.inference.speaker import EncoderClassifier

class SpeakerIdentifier:
    def __init__(self):
        self.encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="server/models/speaker_encoder"
        )
        self.session_speakers = {}

    async def identify(self, audio_segment, user_id):
        embedding = await asyncio.to_thread(self._embed, audio_segment)
        known_speakers = load_known_speakers(user_id)

        for known_id, known_embedding in known_speakers.items():
            similarity = cosine_similarity(embedding, known_embedding)
            if similarity > RECOGNITION_THRESHOLD:
                return known_id

        new_id = f"speaker_{len(self.session_speakers) + 1}"
        self.session_speakers[new_id] = embedding
        return new_id

    def _embed(self, audio_segment):
        """Blocking call — run via asyncio.to_thread."""
        signal = torch.tensor(audio_segment).unsqueeze(0)
        return self.encoder.encode_batch(signal).squeeze().numpy()

    async def register_speaker(self, user_id, name, audio_sample):
        embedding = await asyncio.to_thread(self._embed, audio_sample)
        save_contact_voice(user_id, name, embedding)
```

#### Realistic Accuracy Expectations

Voice embedding diarization is **not perfect.** Here is what to expect:

| Scenario | Accuracy | Notes |
|---|---|---|
| **Owner vs one guest** | High (~90%+) | The most common case. Owner's voice is enrolled at registration with a good sample. One other person is clearly "not the owner." |
| **Owner vs known contact** | Good (~85%) | If the contact has been enrolled (voice sample stored). Quality depends on enrollment audio quality. |
| **Differentiating 2 unknown guests** | Moderate (~70-80%) | Within a single session, the diarizer can tell them apart by embedding distance. But it can't name them — they're "speaker_2" and "speaker_3". |
| **Same person, different conditions** | Lower | Whispering, illness, phone speaker, background noise — the same person can sound different enough to confuse the diarizer. |
| **3+ simultaneous speakers** | Low | Cross-talk and overlapping speech degrade embedding quality. Best-effort only. |

**Phase 1 approach:** The diarizer's main job is answering one question: **"Is this the owner or not?"** That distinction is the most reliable and the most important (it controls memory access and context hiding). Fine-grained multi-guest identification is a nice-to-have, not critical.

**Fallback behavior:** When the diarizer is uncertain (similarity score between thresholds), it defaults to treating the speaker as a guest (safe default — no private data exposed). The owner can always correct: "Vayumi, that's me" or "That's Chris."

#### Learning a New Person — "Meet Chris" Flow

When the owner introduces someone, Vayumi can learn their voice and build a persona automatically:

```text
Scenario: Only Rahul (owner) and one unknown speaker exist in session.

T=0  Rahul is talking to Vayumi normally. (Speaker_1 = Rahul)

T=1  New voice detected. Diarizer assigns: Speaker_2 (unknown).
     Guest persona loaded. Private context hidden.

T=2  Rahul says: "Vayumi, this is Chris, he's my college friend."

     What happens:
     1. Orchestrator parses: introduction intent + name "Chris" + relationship "college friend"
     2. Persona Agent:
        a. Takes Speaker_2's voice embedding from session_speakers
        b. Saves to contacts table:
           INSERT INTO contacts (user_id, name, role, voice_embedding,
              relationship_context, last_seen)
           VALUES ('user_rahul', 'Chris', 'known_contact',
              <embedding>, 'college friend', NOW())
        c. Creates persona context:
           {
             "persona_id": "chris",
             "user_id": "user_rahul",
             "name": "Chris",
             "role": "known_contact",
             "tone": "friendly, warm",
             "known_facts": ["college friend"],
             "memory_access": "shared_only"
           }
     3. Context Builder reloads: Chris now gets "shared" memory access,
        warmer tone, and Vayumi remembers who he is.
     4. Vayumi responds: "Nice to meet you, Chris!"

T=3  Chris is now a known contact. For THIS session and ALL future sessions:
     - Diarizer matches Chris's voice → loads his persona
     - Vayumi remembers he's Rahul's college friend
     - Memory tagged "shared" is visible when Chris speaks
     - Private memories remain hidden from Chris
     - Relationship context grows over time (Memory Agent logs interactions)

NEXT SESSION (days/weeks later):
     Chris walks in again.
     Diarizer extracts voice embedding → matches stored embedding for "Chris"
     → Persona loaded automatically.
     Vayumi: "Hey Chris, good to see you again."
     No introduction needed. Vayumi remembers.
```

**What grows over time:** Each conversation with Chris adds to his persona. The Memory Agent logs things like "Chris mentioned he's applying for grad school" or "Chris and Rahul discussed the hackathon project." Next time Chris visits, the context builder retrieves these memories, and Vayumi's responses are informed by the relationship history.

**Manual correction:** If the diarizer gets it wrong (e.g., assigns Chris's voice to the wrong speaker), the owner can correct it via:
- Voice: "Vayumi, that was Chris talking, not a guest"
- Client UI: `speaker_label` message (reassign a speaker_id to a name)

Both paths call `persona_agent.label_speaker()` which updates the session and optionally re-enrolls the voice embedding.

#### Phase 1 Person Detection Scope (In/Out)

**In scope (required for Phase 1):**
- Reliable `owner` vs `non-owner` distinction
- Known-contact matching when confidence is high
- Safe fallback to `guest_unknown` when uncertain
- Manual relabel/correction via voice or `speaker_label`
- Meeting mode speaker-tagged transcript + summary

**Out of scope (defer to later phases):**
- Accurate attribution with 3+ overlapping speakers
- Perfect identity under heavy noise/reverb/phone audio
- Automatic stable identity for unknown guests across homes/devices
- Fully autonomous correction of all diarization mistakes without user confirmation

### 10.3 Echo Cancellation and Self-Voice Suppression

The most critical audio problem: Vayumi's speaker output is picked up by its own microphone. Without echo cancellation, the system hears itself, transcribes its own words, and responds to itself in a feedback loop.

**Two-layer solution:**

```text
Layer 1 — ESP32 Hardware AEC (primary, on-device)
═══════════════════════════════════════════════════
ESP-ADF audio front-end pipeline runs on the ESP32-S3:

  Microphone (raw)  ──┐
                      ├── AEC ──> NS ──> BSS ──> Clean audio ──> WebSocket
  Speaker (ref sig) ──┘

  AEC  = Acoustic Echo Cancellation (subtracts speaker output from mic input)
  NS   = Noise Suppression (removes ambient noise)
  BSS  = Blind Source Separation (isolates human voice from residual noise)

Result: The server receives audio with Vayumi's own voice already removed.
The server never hears its own TTS output. This is the primary defense.

Layer 2 — Server-Side State Gating (fallback, also covers browser client)
═════════════════════════════════════════════════════════════════════════════
The session tracks playback state:

  session.playback_state: IDLE | PLAYING

  When IDLE:
    → Normal VAD sensitivity
    → Any detected speech is treated as user input

  When PLAYING (TTS audio streaming to client):
    → VAD threshold raised (higher energy required)
    → Minimum sustained duration required (>300ms continuous speech)
    → Short bursts of detected speech are IGNORED (likely echo residue)
    → Only loud, sustained human speech triggers interrupt detection

  Transitions:
    → stream_response() starts sending audio → playback_state = PLAYING
    → Client sends {"type":"playback_done"} → playback_state = IDLE
```

**Why both layers?**

| Client | Layer 1 (Hardware AEC) | Layer 2 (Server Gating) |
|---|---|---|
| ESP32 | Yes — ESP-ADF pipeline | Safety net only |
| Browser | No hardware AEC; relies on Web Audio API `echoCancellation:true` | Primary defense |
| Mobile (future) | Depends on device | Always active |

```python
import numpy as np

class VADResult:
    def __init__(self, has_speech: bool):
        self.has_speech = has_speech

class VADEngine:
    def __init__(self):
        self.detector = ...  # silero-vad model (recommended) or webrtcvad
        self.normal_threshold = 0.5     # silero probability threshold for IDLE
        self.echo_threshold = 0.8       # raised threshold during PLAYING
        self.min_sustained_ms = 300     # minimum speech duration to pass echo gate
        self._speech_buffer_ms = 0      # accumulated speech duration

    async def process(self, audio_chunk: bytes, session) -> VADResult:
        probability = self.detector(audio_chunk)
        has_speech = probability > self.normal_threshold

        if not has_speech:
            self._speech_buffer_ms = 0
            return VADResult(has_speech=False)

        if session.playback_state == "PLAYING":
            if probability < self.echo_threshold:
                self._speech_buffer_ms = 0
                return VADResult(has_speech=False)
            chunk_ms = len(audio_chunk) / (16000 * 2) * 1000  # 16kHz 16-bit mono
            self._speech_buffer_ms += chunk_ms
            if self._speech_buffer_ms < self.min_sustained_ms:
                return VADResult(has_speech=False)

        self._speech_buffer_ms = 0
        return VADResult(has_speech=True)
```

**Interrupt during speech — two paths:**

1. **Wake word path (most reliable):** ESP32's ESP-SR detects "Hi Vayumi" even while the speaker is playing, because AEC separates user voice from speaker output. ESP32 sends `{"type":"interrupt"}`. Works even if echo cancellation is imperfect.

2. **Echo-cancelled speech path:** User says "stop" or "wait" without the wake word. AEC removes Vayumi's voice, clean audio reaches server, VAD detects speech during SPEAKING state, interrupt is triggered. Less reliable than wake word in noisy environments.

---

### 10.4 Streaming Response (Speak While Thinking)

Vayumi does NOT wait for the full LLM response before speaking. It uses a streaming pipeline:

```text
LLM streams tokens → 
    Sentence boundary detector → 
        TTS converts sentence → 
            Audio sent to client →
                Client plays audio

While first sentence plays → LLM is generating next sentence
```

This feels natural. User starts hearing Vayumi speak within ~500ms of asking.

### 10.5 Kokoro-ONNX TTS Integration

```python
from kokoro_onnx import Kokoro
import numpy as np
import io, wave

class TTSEngine:
    # Default paths: server/models/kokoro-v0_19.onnx and server/models/voices.bin
    # (see server.paths.DEFAULT_KOKORO_ONNX, DEFAULT_KOKORO_VOICES)
    def __init__(self, model_path="server/models/kokoro-v0_19.onnx", voices_path="server/models/voices.bin"):
        self.tts = Kokoro(model_path, voices_path)
        self.default_voice = "af"
        self._stopped = False
        self._paused = False

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize a single sentence. Returns (samples, sample_rate).
        Called via asyncio.to_thread() from stream_response to avoid blocking."""
        samples, sr = self.tts.create(text, voice=self.default_voice, speed=1.0)
        return samples, sr

    async def stop(self):
        self._stopped = True

    async def pause(self):
        self._paused = True

    async def resume(self):
        self._paused = False

def pcm_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    """Convert raw PCM float32 samples to WAV bytes for WebSocket transmission."""
    buf = io.BytesIO()
    pcm16 = (samples * 32767).astype(np.int16)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()
```

---

## 11. Interrupt and Mode Handling

### 11.1 Interrupt Detection

An interrupt occurs when the user speaks while Vayumi is speaking. Echo cancellation (Section 10.3) ensures that Vayumi's own voice does not trigger false interrupts.

```text
Session States (activation_state):
- SLEEP: Waiting for wake word or button press. No audio streaming.
         ESP32: on-device wake word detection active. Browser: mic off.
- ACTIVE: Listening for user speech. VAD at normal sensitivity.
- SPEAKING: Vayumi is responding (TTS playing). playback_state = PLAYING.
            Echo gating active — only sustained loud speech or wake word triggers interrupt.
- INTERRUPTED: User spoke during Vayumi's response. TTS stopped/paused.

Playback States (playback_state — controls echo gating):
- IDLE: Nothing playing. VAD at normal sensitivity.
- PLAYING: TTS audio streaming to client. VAD at raised threshold.

State transitions:
  SLEEP → ACTIVE:        wake word detected / button pressed / mic click
  ACTIVE → SPEAKING:     Vayumi starts responding (TTS begins)
  ACTIVE → SLEEP:        30s silence timeout (active window expired)
  SPEAKING → ACTIVE:     Vayumi finishes speaking (client sends playback_done)
  SPEAKING → INTERRUPTED: User interrupts (echo-cancelled speech or wake word)
  INTERRUPTED → ACTIVE:  Interrupt handled, ready for next input

Interrupt triggers (during SPEAKING state):
  1. Wake word via ESP32 ESP-SR (works through speaker audio — most reliable)
  2. VAD detects echo-cancelled user speech above raised threshold
  3. User says "stop", "wait", or "hold on" (detected via echo-cancelled path)
  4. Client sends explicit interrupt event (button press)
```

```python
class InterruptHandler:
    async def handle(self, session, action: str):
        """Handle a typed interrupt. Called by handle_interrupt (client button)
        or by handle_speech_interrupt after classifying the speech."""
        if action == "stop":
            await tts_engine.stop()
            if session.task_state.get("status") == "running":
                session.task_state = {"status": "idle"}
            session.activation_state = "ACTIVE"

        elif action == "redirect":
            await tts_engine.stop()
            session.activation_state = "ACTIVE"
            # Caller will route the new input to process_user_turn

        elif action == "add_context":
            await tts_engine.pause()
            session.activation_state = "INTERRUPTED"
            # Caller merges context, then calls tts_engine.resume() or
            # regenerates response → activation_state back to SPEAKING

        session.playback_state = "IDLE"
        session.reset_active_window_timer()

    async def handle_speech_interrupt(self, session, audio_bytes):
        """Called when VAD detects speech during SPEAKING state.
        Transcribes the speech, classifies intent, then dispatches."""
        text = await stt.transcribe(audio_bytes)
        action = self._classify_interrupt(text)
        await self.handle(session, action)
        if action == "redirect":
            speaker_id = await diarizer.identify(audio_bytes, session.user_id)
            await process_user_turn(session, text, speaker_id, source="voice")

    def _classify_interrupt(self, text: str) -> str:
        """Classify transcribed interrupt speech into action type."""
        stop_words = {"stop", "quit", "cancel", "shut up", "be quiet", "enough"}
        pause_words = {"wait", "hold on", "pause", "one sec", "hang on"}
        text_lower = text.lower().strip()
        if any(w in text_lower for w in stop_words):
            return "stop"
        if any(w in text_lower for w in pause_words):
            return "add_context"
        return "redirect"
```

### 11.2 Mode System

Modes change Vayumi's behavior globally without changing the core architecture. Mode state is per-session (and therefore per-user).

**Normal Mode (Default)**

```text
- Full conversational capability
- All skills and tools available
- Balanced context
- Responds to authenticated user
```

**Meeting Mode**

```text
Activation: "Vayumi, meeting mode" or button press

Behavior:
- Diarizer sensitivity increased (capture all speakers)
- Everything transcribed with speaker + timestamp
- Minimal verbal responses (avoid disrupting the meeting)
- Background: builds structured meeting notes
- Smart interruption: only responds if directly called by name
- On meeting end: "Vayumi, end meeting" → 
  generates full meeting summary + action items
  stores in episodic memory (owned by authenticated user)
```

**Focus Mode**

```text
Activation: "Vayumi, focus mode"

Behavior:
- No proactive interruptions
- Responses only on direct questions
- Filters non-critical flag injections
- Minimizes context switching overhead
```

```python
class ModeManager:
    MODES = {
        "normal": NormalMode(),
        "meeting": MeetingMode(),
        "focus": FocusMode(),
    }

    def switch(self, session, mode_name, trigger="voice"):
        old_mode = session.mode
        self.MODES[old_mode].on_exit(session)
        session.mode = mode_name
        self.MODES[mode_name].on_enter(session)
```

### 11.3 Wake Word and Activation Model

Vayumi is **not** always listening. It uses a wake-then-active-window model: the user activates Vayumi with a wake word or button, Vayumi stays active for a conversational window, then goes back to sleep.

```text
State machine:

  SLEEP ──(wake word / button)──> ACTIVE ──(30s silence)──> SLEEP
                                    │                          ^
                                    └──(each user turn)────────┘
                                         resets 30s timer

  ACTIVE ──(Vayumi starts speaking)──> SPEAKING
  SPEAKING ──(Vayumi finishes)──> ACTIVE (timer resets)
  SPEAKING ──(user interrupts)──> INTERRUPTED ──> ACTIVE
```

**Per-client activation behavior:**

| Client | Wake Word | Activation | Notes |
|---|---|---|---|
| ESP32 | "Hi Vayumi" via ESP-SR (on-device, no server round-trip) | Wake word or physical button press | ESP-SR runs locally on S3's DSP. Works even while speaker is playing (AEC separates voices). |
| Browser | None (Phase 1) | Click mic button to activate | Optional JS-based wake word (e.g., Porcupine) is a Phase 2 feature. |
| Mobile (future) | Configurable | Button or wake word | Depends on platform capabilities. |

**Active window behavior:**

After activation, Vayumi enters ACTIVE state and listens continuously. The active window timer (default: 30 seconds of silence) determines when Vayumi goes back to sleep:

- Each user turn (speech or text) resets the timer
- Each Vayumi response resets the timer (via `playback_done`)
- A natural back-and-forth conversation keeps the session active indefinitely without re-saying the wake word
- After 30 seconds of no activity, the server sends `{"type":"sleep"}` to the client
- ESP32: LED goes dim, stops streaming audio, returns to on-device wake word listening
- Browser: mic indicator turns off, UI shows "sleeping" state

**Meeting mode exception:** In meeting mode, the active window timer is disabled. Vayumi stays active for the entire meeting duration. Wake word is not needed for logging — only for directing a command to Vayumi mid-meeting.

**Wake word during speech (the echo problem solution):**

The wake word is the **most reliable** way to interrupt Vayumi while it's speaking. Even if echo cancellation is imperfect (noisy room, low volume), ESP-SR is designed to detect the wake phrase through speaker audio because AEC separates the reference signal. This is the guaranteed interrupt path.

**Critical scenario behavior:**

| # | State | Scenario | What Happens |
|---|---|---|---|
| 1 | SLEEP | User says "Hi Vayumi" (ESP32) | ESP-SR detects wake word on-device. ESP32 sends `{"type":"wake"}`. LED turns blue. Session moves to ACTIVE. Timer starts (30s). |
| 2 | SLEEP | User presses button (ESP32) | Same as wake word — sends `{"type":"wake"}`, moves to ACTIVE. Bypasses wake word detection. |
| 3 | SLEEP | User clicks mic (browser) | Same — sends `{"type":"wake"}`, moves to ACTIVE. |
| 4 | SLEEP | Non-owner says "Hi Vayumi" | Anyone can wake it (Phase 1 — wake word is not voice-verified). System activates, diarizer identifies speaker as guest, guest gets limited access per persona rules. |
| 5 | SLEEP | TV/radio triggers false wake | ESP-SR confidence threshold filters most false triggers. If it does activate, no one speaks, 30s timeout returns to SLEEP. Minimal cost (no STT/LLM calls — VAD detects no speech). |
| 6 | ACTIVE | User speaks a command | Normal flow: VAD → STT → diarizer → orchestrator → TTS. Session moves to SPEAKING. Timer resets. |
| 7 | ACTIVE | 30 seconds of silence | Timer fires. Server sends `{"type":"sleep"}`. ESP32 LED dims, stops streaming, returns to wake word listening. Session moves to SLEEP. |
| 8 | ACTIVE | Background noise (TV, music) | VAD filters non-speech. If VAD triggers, STT returns empty/garbage text, orchestrator ignores it (intent: `no_action`). No response, timer keeps ticking. |
| 9 | SPEAKING | User says "Vayumi, stop" | Wake word path: ESP-SR detects "Vayumi" through AEC. ESP32 sends `{"type":"interrupt","action":"stop"}`. Server stops TTS, cancels task. Session moves to ACTIVE. |
| 10 | SPEAKING | User says "wait" / "hold on" | Echo-cancelled speech path: AEC removes Vayumi's voice. Clean audio reaches server. VAD detects speech during SPEAKING → interrupt triggered. STT transcribes "wait" → pause TTS. |
| 11 | SPEAKING | Nobody interrupts, Vayumi finishes | Client sends `{"type":"playback_done"}`. Server sets `playback_state = IDLE`. Session moves to ACTIVE. Timer resets (30s). Listens for follow-up. |
| 12 | SPEAKING | Vayumi's own voice picked up by mic | ESP32: hardware AEC subtracts speaker output from mic. Server receives clean audio, VAD sees silence. No false trigger. Browser: Web Audio `echoCancellation:true` + server-side gating (raised threshold during PLAYING). |
| 13 | ACTIVE (task running) | User speaks during LLM/skill processing | No echo issue (nothing playing — `activation_state` is still ACTIVE, `task_state.status = "running"`). VAD detects speech normally. If cancel ("never mind"): cancel task. If new question: queue it, process after current task. |
| 14 | ACTIVE (task running) | Long task, user says "Vayumi?" | Already handled by instant acknowledgment (Section 7.4). If user asks again, system recognizes status check and responds "Still working on it" (based on `task_state`). |

**ESP32 connection lifecycle:**

| Scenario | What Happens |
|---|---|
| Boot / power on | Connects WiFi → WebSocket → `{"type":"auth","token":"<device_token>"}` → session created → SLEEP mode. LED flashes green briefly, then dims. |
| WiFi drops mid-conversation | ESP32 attempts reconnection (exponential backoff). LED flashes red. Server session alive for 60s grace period. On reconnect: re-auth, resume. Grace period expired: session cleaned up. |
| Browser and ESP32 both connected | Separate sessions for same `user_id`. Each operates independently. Memory shared (same user). No cross-device audio conflict. |

---

## 12. Client/Server Architecture

### 12.1 Design Principle

**The server knows everything. The client knows nothing.**

The client is purely an I/O device:
- Sends: auth token, audio chunks, text input, button events, mode switches
- Receives: audio chunks, text, status events, UI updates

This means:
- ESP32 can be a client (just sends mic audio, plays speaker audio)
- Browser can be a client (WebSocket + audio)
- Mobile app can be a client
- Any future client works with zero server changes

### 12.2 Server Stack

```text
FastAPI (Python)
├── WebSocket endpoint: /ws/vayumi → ws/handler.py (unified handler)
├── REST endpoints:
│   ├── POST /api/auth/register
│   ├── POST /api/auth/login
│   ├── GET  /api/users/me
│   ├── GET  /api/memory (user-scoped)
│   ├── GET  /api/skills
│   └── GET  /api/config (user-scoped)
├── Background services:
│   ├── Memory Agent (async loop, per-session)
│   ├── Flag Injection listener (user-scoped)
│   └── Mode manager (per-session)
└── Storage:
    ├── SQLite: users, reminders, meetings, contacts
    ├── ChromaDB: vector embeddings (user-scoped)
    └── File store: /var/vayumi/files/{user_id}/
```

### 12.3 Client Stack (Browser)

```text
React or Vanilla JS
├── Login screen → auth token
├── WebSocket connection to server
├── First WS message: {"type":"auth","token":"..."} (canonical)
├── Optional legacy compatibility: token in query param (if enabled)
├── MediaRecorder API → audio chunks → WS
├── Audio playback: AudioContext
├── UI: status indicator, transcript display, mode button
└── Events sent: audio_chunk, text_input, interrupt, mode_switch
```

### 12.4 Client Stack (ESP32-S3-AUDIO-Board)

**Hardware:** ESP32-S3-AUDIO-Board (ESP32-S3R8, 16MB Flash, 8MB PSRAM)

| Component | Chip | Role |
|---|---|---|
| Controller | ESP32-S3R8 | Dual-core LX7 @ 240MHz, WiFi + BLE 5 |
| Mic ADC | ES7210 | Quad-channel ADC, dual digital microphone array |
| Speaker DAC | ES8311 | Audio codec for speaker output |
| Wake word | ESP-SR | On-device wake word detection ("Hi Vayumi"), runs on S3's DSP |
| LED ring | 7x WS2812B RGB | Status indicator (programmable colors/patterns) |
| RTC | PCF85063 | Real-time clock for alarms/scheduled wake-ups |
| Storage | NVS | Stores device token, WiFi credentials, user config |

**Framework:** ESP-IDF + ESP-ADF (C). MicroPython/Arduino cannot access the ADF audio front-end pipeline required for hardware AEC.

```text
ESP-IDF + ESP-ADF (C)
├── WiFi → WebSocket to server
├── Device token in NVS → auto-auth as linked user_id
│   First message: {"type":"auth","token":"<device_token>"}
├── Audio front-end pipeline (ESP-ADF):
│   I2S mic (ES7210) → AEC + NS + BSS → clean audio buffer
│   AEC reference signal ← I2S speaker (ES8311) output
│   Result: echo-cancelled audio sent to server
├── Wake word detection (ESP-SR):
│   Runs continuously during SLEEP state
│   On detection: sends {"type":"wake"} → starts audio streaming
│   Works through speaker playback (AEC separates voices)
├── WebSocket audio streaming:
│   Clean audio buffer → base64 → {"type":"audio_chunk"} → server
│   Server audio chunks → decode → I2S speaker (ES8311)
├── Button handler:
│   Short press → {"type":"wake"} (manual activation)
│   Long press → {"type":"mode_switch"}
├── LED ring status:
│   Dim/off = SLEEP (wake word listening only)
│   Blue pulse = ACTIVE (listening for user speech)
│   Yellow = PROCESSING (waiting for response)
│   White stream = SPEAKING (TTS playing)
│   Red flash = error / WiFi disconnected
└── Playback tracking:
    Sends {"type":"playback_done"} when TTS audio finishes playing
```

### 12.5 WebSocket Protocol

All messages are JSON. Audio data is base64-encoded within JSON messages (not raw binary frames). The canonical auth flow is: first message must be `auth`.

**Client → Server:**

```json
{"type": "auth", "token": "jwt_token_here"}
{"type": "wake"}
{"type": "audio_chunk", "data": "<base64_audio>"}
{"type": "text_input", "text": "What's my schedule today?"}
{"type": "interrupt", "action": "stop"}
{"type": "playback_done"}
{"type": "mode_switch", "mode": "meeting"}
{"type": "speaker_label", "speaker_id": "speaker_2", "name": "Rohan"}
```

| Message | When sent | Purpose |
|---|---|---|
| `auth` | First message after connection | Authenticate with JWT |
| `wake` | Wake word detected or button pressed | Transitions session from SLEEP to ACTIVE |
| `audio_chunk` | During ACTIVE/SPEAKING states | Streamed mic audio (echo-cancelled on ESP32) |
| `text_input` | User types in browser/app | Text-based input (URLs, commands) |
| `interrupt` | User interrupts during SPEAKING | Stop/pause current response |
| `playback_done` | Client finishes playing TTS audio | Signals server to set `playback_state = IDLE` and transition to ACTIVE |
| `mode_switch` | User requests mode change | Switch to meeting/focus/normal mode |
| `speaker_label` | User corrects speaker identity | Relabel a speaker_id to a known name |

**Server → Client:**

```json
{"type": "auth_ok", "user_id": "user_rahul", "session_id": "sess_abc"}
{"type": "auth_error", "message": "Invalid token"}
{"type": "status", "state": "listening"}
{"type": "status", "state": "processing"}
{"type": "status", "state": "speaking"}
{"type": "sleep"}
{"type": "transcript", "text": "What's my schedule today?", "speaker": "rahul"}
{"type": "response_text", "text": "You have a meeting at 3pm.", "is_final": false}
{"type": "response_text", "text": "", "is_final": true}
{"type": "audio_chunk", "data": "<base64_audio>"}
{"type": "mode_changed", "mode": "meeting"}
{"type": "flag_notify", "source": "gmail", "preview": "New email from Prof. Sharma"}
```

| Message | When sent | Purpose |
|---|---|---|
| `sleep` | Active window timeout (30s silence) | Tells client to stop streaming audio, return to wake word listening (ESP32) or show sleeping UI (browser) |
| `status` | State transitions | Informs client of current session state for UI updates |

### 12.6 Unified WebSocket Handler — Single Entry Point

All WebSocket communication flows through **one handler function**. This is the only place **client realtime messages** enter the server. Everything else is called from here. This design means: one place to debug, one place to add logging, one place to add new message types.

```python
async def websocket_endpoint(websocket: WebSocket):
    """Single entry point for all WebSocket communication.
    Auth → session creation → message loop → cleanup.
    Every message type dispatches to a typed handler."""

    session = await authenticate_connection(websocket)
    if not session:
        return

    try:
        await message_loop(session, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        await cleanup_session(session)
```

```python
async def authenticate_connection(websocket: WebSocket) -> Session | None:
    await websocket.accept()
    first_message = await websocket.receive_json()

    if first_message.get("type") != "auth":
        await websocket.close(code=4001, reason="Auth required")
        return None

    user_id = validate_token(first_message["token"])
    # Optional legacy compatibility (disabled by default):
    # if not user_id:
    #     qp_token = websocket.query_params.get("token")
    #     if qp_token:
    #         user_id = validate_token(qp_token)
    if not user_id:
        await websocket.send_json({"type": "auth_error", "message": "Invalid token"})
        await websocket.close(code=4003)
        return None

    session = create_session(user_id, websocket)
    await websocket.send_json({
        "type": "auth_ok",
        "user_id": user_id,
        "session_id": session.session_id
    })
    return session
```

```python
MESSAGE_HANDLERS = {
    "wake":          handle_wake,
    "audio_chunk":   handle_audio_chunk,
    "text_input":    handle_text_input,
    "interrupt":     handle_interrupt,
    "playback_done": handle_playback_done,
    "mode_switch":   handle_mode_switch,
    "speaker_label": handle_speaker_label,
}

async def message_loop(session: Session, websocket: WebSocket):
    async for raw in websocket.iter_json():
        msg_type = raw.get("type", "unknown")
        handler = MESSAGE_HANDLERS.get(msg_type)
        if handler:
            await handler(session, raw)
        else:
            await websocket.send_json({
                "type": "error",
                "message": f"Unknown message type: {msg_type}"
            })
```

Each typed handler is a standalone async function. Adding a new message type = adding one function + one dict entry. No if/elif chains.

```python
async def handle_wake(session, msg):
    session.activation_state = "ACTIVE"
    session.reset_active_window_timer()
    await send_status(session, "listening")

async def handle_audio_chunk(session, msg):
    if session.activation_state == "SLEEP":
        return
    audio_bytes = base64.b64decode(msg["data"])
    vad_result = await vad.process(audio_bytes, session)
    if not vad_result.has_speech:
        return
    if session.activation_state == "SPEAKING":
        await interrupt_handler.handle_speech_interrupt(session, audio_bytes)
        return
    text = await stt.transcribe(audio_bytes)
    speaker_id = await diarizer.identify(audio_bytes, session.user_id)
    session.reset_active_window_timer()
    await process_user_turn(session, text, speaker_id, source="voice")

async def handle_text_input(session, msg):
    text = msg["text"]
    if session.activation_state == "SLEEP":
        session.activation_state = "ACTIVE"
    session.reset_active_window_timer()
    await process_user_turn(session, text, session.user_id, source="text")

async def handle_interrupt(session, msg):
    action = msg.get("action", "stop")
    await interrupt_handler.handle(session, action)
    # handle() sets activation_state and playback_state per action type
    await send_status(session, "listening")

async def handle_playback_done(session, msg):
    session.playback_state = "IDLE"
    session.activation_state = "ACTIVE"
    session.reset_active_window_timer()
    await send_status(session, "listening")

async def handle_mode_switch(session, msg):
    new_mode = msg["mode"]
    mode_manager.switch(session, new_mode, trigger="client")
    await session.websocket.send_json({"type": "mode_changed", "mode": new_mode})

async def handle_speaker_label(session, msg):
    await persona_agent.label_speaker(
        session, msg["speaker_id"], msg.get("name")
    )
```

`process_user_turn` is the shared function that both voice and text input converge into:

```python
async def send_status(session, state: str):
    await session.send({"type": "status", "state": state})

CANCEL_WORDS = {"never mind", "cancel", "forget it", "stop", "don't bother"}

async def process_user_turn(session, text: str, speaker_id: str, source: str):
    """Single processing path for all user input regardless of source.
    Owns all state transitions for SPEAKING/PLAYING."""
    if session.task_state.get("status") == "running":
        session.input_queue.append({"text": text, "speaker_id": speaker_id, "source": source})
        await send_status(session, "queued")
        return

    session.working_memory.append({"role": "user", "text": text, "speaker": speaker_id})
    await send_status(session, "processing")

    context = await context_builder.build(session, text, speaker_id)
    result = await orchestrator.run(session, context, text)

    session.activation_state = "SPEAKING"
    session.playback_state = "PLAYING"

    if isinstance(result, dict) and "ack" in result:
        await stream_response(session, result["ack"])
        await stream_response(session, result["result"])
    else:
        await stream_response(session, result)

    asyncio.create_task(memory_agent.process_turn(session, text, result))
    _drain_input_queue(session)

async def _drain_input_queue(session):
    """Process queued inputs after a task completes. Rules:
    - If ANY queued item is a cancel intent → discard entire queue
    - Otherwise → process only the LAST item (most recent intent wins)
    - Older items are discarded (stale context)"""
    if not session.input_queue:
        return
    queue = session.input_queue
    session.input_queue = []

    if any(item["text"].lower().strip() in CANCEL_WORDS for item in queue):
        return

    last = queue[-1]
    await process_user_turn(session, last["text"], last["speaker_id"], last["source"])
```

**Why this design matters:**
- One file, one entry point — easy to debug
- Handler dict — easy to extend
- `process_user_turn` — voice and text share the same pipeline, no duplication
- `stream_response` — reused for every response (ack, result, conversation)
- `cleanup_session` — guaranteed cleanup on disconnect

### 12.7 Session Management

```python
class Session:
    session_id: str
    user_id: str              # Authenticated user this session belongs to
    websocket: WebSocket      # The active connection
    client_type: str          # "browser" | "esp32" | "mobile"
    active_speaker: str       # Current speaker persona_id
    mode: str                 # Current mode ("normal" | "meeting" | "focus")
    working_memory: list      # Current conversation turns
    task_state: dict          # {"status": "idle"} or {"status": "running", "task_id": ..., "started_at": ...}
    input_queue: list         # Queued user inputs received while a task is running
    connected_at: datetime

    # Activation state (Section 11.3), echo gating (Section 10.3)
    activation_state: str     # "SLEEP" | "ACTIVE" | "SPEAKING" | "INTERRUPTED"
    playback_state: str       # "IDLE" | "PLAYING" (controls echo gating in VAD)
    _active_window_handle: asyncio.TimerHandle | None  # Cancel handle for active window

    async def send(self, data: dict):
        """Single method to send JSON to this session's client."""
        await self.websocket.send_json(data)

    def reset_active_window_timer(self):
        """Reset the 30s active window. Called on every user turn and playback_done."""
        if self.mode == "meeting":
            return
        if self._active_window_handle:
            self._active_window_handle.cancel()
        loop = asyncio.get_event_loop()
        self._active_window_handle = loop.call_later(30, lambda: asyncio.create_task(self._on_active_timeout()))

    async def _on_active_timeout(self):
        """Called when active window expires. Transition to SLEEP."""
        self.activation_state = "SLEEP"
        await self.send({"type": "sleep"})
```

Each WebSocket connection gets one Session bound to a user_id. Session state lives in a Python dict (Phase 1). On reconnect (ESP32 WiFi drop), session can be restored by session_id if the user_id matches. New sessions start in `SLEEP` activation state with `IDLE` playback state.

Identity contract (must stay consistent across the stack):

| Field | Meaning | Source | Example |
|---|---|---|---|
| `user_id` | Authenticated account owner. Used for data isolation. | Auth/JWT | `user_rahul` |
| `speaker_id` | Physical speaker track for the current utterance. | Diarizer (voice) or defaults to `user_id` for text input | `speaker_2`, `rahul` |
| `persona_id` | Context persona loaded for response policy/tone/access. | Persona Agent mapping from `speaker_id` | `rahul_self`, `chris`, `guest_unknown` |

Mapping rules:
1. Voice input: diarizer emits `speaker_id` → Persona Agent maps to `persona_id` using user-scoped contacts.
2. Text input: `speaker_id = user_id` unless explicitly overridden by client metadata.
3. Context/policy uses `persona_id`; storage isolation always uses `user_id`.
4. If mapping fails or confidence is low: `persona_id = guest_unknown` (safe fallback).

### 12.8 Response Streaming

All responses (acknowledgments, results, conversation) flow through one streaming function:

```python
async def stream_response(session: Session, response: str | AsyncIterator[str]):
    """Stream text response to client as both text and TTS audio.
    Uses 1-sentence lookahead: pre-synthesizes sentence N+1 while N is being sent.
    Caller (process_user_turn) must set activation_state/playback_state
    BEFORE calling this. State resets on playback_done from client."""
    if isinstance(response, str):
        sentences = split_into_sentences(response)
    else:
        sentences = [s async for s in response] if hasattr(response, '__aiter__') else list(response)

    if not sentences:
        return

    next_audio_task = asyncio.create_task(
        asyncio.to_thread(tts.synthesize, sentences[0])
    )

    for i, sentence in enumerate(sentences):
        if session.activation_state == "INTERRUPTED":
            next_audio_task.cancel()
            break

        samples, sr = await next_audio_task

        if i + 1 < len(sentences):
            next_audio_task = asyncio.create_task(
                asyncio.to_thread(tts.synthesize, sentences[i + 1])
            )

        audio_bytes = pcm_to_wav(samples, sr)
        await session.send({"type": "response_text", "text": sentence, "is_final": False})
        await session.send({"type": "audio_chunk", "data": base64.b64encode(audio_bytes).decode()})

    if session.activation_state != "INTERRUPTED":
        await session.send({"type": "response_text", "text": "", "is_final": True})
```

**State ownership:** `stream_response` does NOT set `activation_state` or `playback_state`. The caller (`process_user_turn`) owns all state transitions:

```python
# In process_user_turn (the caller):
session.activation_state = "SPEAKING"
session.playback_state = "PLAYING"
await stream_response(session, response)
# State is NOT reset here — client sends playback_done when audio finishes,
# which triggers handle_playback_done → resets to ACTIVE/IDLE.
```

**TTS note:** `tts.synthesize(sentence)` calls `kokoro_tts.create(text, voice, speed)` which returns `(samples: ndarray, sample_rate: int)`. The `pcm_to_wav` utility converts the raw PCM samples to WAV bytes for WebSocket transmission.

This function is called for everything — quick replies, skill results, meeting summaries, instant acknowledgments. One path, consistent behavior.

---

## 13. Data Storage Design

### 13.1 SQLite Schema

```sql
-- Users (account holders)
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    voice_embedding BLOB,
    embedding_model_version TEXT,
    profile TEXT,              -- JSON: occupation, goals, tone, language
    enabled_mcps TEXT,         -- JSON array of enabled MCP names
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Reminders
CREATE TABLE reminders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    text TEXT,
    due_datetime DATETIME,
    created_at DATETIME,
    completed BOOLEAN DEFAULT 0
);

-- Meetings
CREATE TABLE meetings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    title TEXT,
    started_at DATETIME,
    ended_at DATETIME,
    attendees TEXT,       -- JSON array
    notes TEXT,           -- Full transcript/notes
    summary TEXT,         -- AI-generated summary
    action_items TEXT     -- JSON array
);

-- Contacts / Known Speakers (per user)
CREATE TABLE contacts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    name TEXT,
    role TEXT,
    voice_embedding BLOB,
    embedding_model_version TEXT,
    relationship_context TEXT,
    last_seen DATETIME
);

-- Memory Episodes (per user)
CREATE TABLE memory_episodes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    speaker_id TEXT,
    content TEXT,
    embedding_id TEXT,
    timestamp DATETIME,
    sensitivity TEXT,      -- private / shared / public
    tags TEXT               -- JSON array of topic tags
);

-- Flags Log (per user)
CREATE TABLE injected_flags (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    source TEXT,
    event_type TEXT,
    data TEXT,              -- JSON
    injected_at DATETIME,
    acknowledged BOOLEAN DEFAULT 0
);
```

### 13.2 Vector DB (ChromaDB)

ChromaDB is used for Phase 1. For production with multiple users and larger data volumes, migrate to Qdrant hosted.

```python
import chromadb

# Runtime default: server.paths.DEFAULT_VECTORDB_DIR → <repo>/server/data/vectordb
client = chromadb.PersistentClient(path="server/data/vectordb")

memory_collection = client.get_or_create_collection(
    name="episodic_memory",
    metadata={"hnsw:space": "cosine"}
)

# Store (always include user_id in metadata)
memory_collection.add(
    documents=["User discussed Vayumi memory architecture, 3-layer system"],
    embeddings=[embedding_vector],
    metadatas=[{
        "user_id": "user_rahul",
        "speaker_id": "rahul",
        "timestamp": "2026-03-15",
        "sensitivity": "private"
    }],
    ids=["mem_001"]
)

# Retrieve (always filter by user_id)
results = memory_collection.query(
    query_embeddings=[query_embedding],
    n_results=5,
    where={"user_id": "user_rahul"}
)
```

Deferred artifacts for "tell me later" are stored with explicit metadata:

```python
memory_collection.add(
    documents=["Article summary: 3 key points about reinforcement learning..."],
    embeddings=[embedding_vector],
    metadatas=[{
        "user_id": "user_rahul",
        "artifact_type": "deferred_read",
        "source_url": "https://example.com/article",
        "created_at": "2026-03-30T10:00:00Z",
        "sensitivity": "private"
    }],
    ids=["deferred_001"]
)
```

Deferred retrieval precedence:
1. Filter by `user_id` and `artifact_type = deferred_read`
2. Rank by semantic similarity
3. Re-rank by recency (`created_at`)
4. Return top-k

**Migration trigger:** When any single user exceeds ~50,000 memory entries or total entries across all users exceed ~200,000, consider migrating to Qdrant for better query performance.

### 13.3 Embedding Strategy

- **Provider:** HuggingFace sentence-transformers (local, free)
- **Model:** `all-MiniLM-L6-v2` (fast, 384-dim, good quality)
- **When to embed:** After memory is written (async, never blocks response)

```python
from sentence_transformers import SentenceTransformer

embedder = SentenceTransformer('all-MiniLM-L6-v2')

def embed(text: str) -> list[float]:
    return embedder.encode(text).tolist()
```

If the embedding model is changed in the future, all stored embeddings become incompatible. The `embedding_model_version` field in the users and contacts tables tracks which model generated each voice embedding, enabling future migration.

### 13.4 SQLite Concurrency

SQLite has write-locking limitations. With multiple background agents writing asynchronously, configure WAL mode for better concurrent performance:

```python
import sqlite3

# Runtime default: server.paths.DEFAULT_SQLITE_DB → <repo>/server/data/vayumi.db
conn = sqlite3.connect("server/data/vayumi.db")
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

**Production migration:** When deploying with 3+ concurrent users or moving to cloud, migrate from SQLite to PostgreSQL. The schema is designed to be compatible — only connection strings change.

---

## 14. LLM Strategy — Groq + Gemini

### 14.1 Model Routing

Different agents use different models based on task type and latency requirements. Specific model names will change over time — the important principle is the **routing strategy**: fast/cheap for simple tasks, smart/capable for complex ones.

| Agent | Strategy | Primary (Groq) | Fallback (Gemini) |
|---|---|---|---|
| Orchestrator | Fast + cheap, routing only | `llama-3.1-8b-instant` | `gemini-2.0-flash` |
| Task Agent | Smart, multi-step reasoning | `llama-3.3-70b-versatile` | `gemini-2.0-flash` |
| Memory Agent | Simple summarization | `llama-3.1-8b-instant` | — |
| Search Agent | Query building + summary | `llama-3.1-8b-instant` | — |
| Complex reasoning | High intelligence needed | `gemini-2.0-flash` | `gemini-1.5-pro` |

**Why two providers:** Groq offers extremely fast inference (low latency) which is critical for conversational flow. Gemini serves as the fallback when Groq is rate-limited and as the primary for tasks that need stronger reasoning.

### 14.2 Rate Limit Management

```python
class LLMRouter:
    groq_limits = {
        "llama-3.1-8b-instant": {"rpm": 30, "tpm": 131072},
        "llama-3.3-70b-versatile": {"rpm": 30, "tpm": 131072},
    }

    def route(self, user_id, task_type, estimated_tokens):
        if not self.per_user_limiter.check(user_id, estimated_tokens):
            return None, "User rate limit exceeded"

        model = self.select_groq_model(task_type)
        if self.within_global_rate_limit(model, estimated_tokens):
            return ("groq", model)

        return ("gemini", self.select_gemini_model(task_type))

    def select_groq_model(self, task_type):
        if task_type in ["orchestrate", "memory", "search"]:
            return "llama-3.1-8b-instant"
        else:
            return "llama-3.3-70b-versatile"
```

### 14.3 Streaming Implementation

```python
from groq import AsyncGroq

async def stream_llm(prompt, model="llama-3.1-8b-instant"):
    client = AsyncGroq(api_key=GROQ_API_KEY)

    stream = await client.chat.completions.create(
        model=model,
        messages=prompt,
        stream=True,
        max_tokens=1000
    )

    async for chunk in stream:
        token = chunk.choices[0].delta.content
        if token:
            yield token
```

---

## 15. API and Communication Contracts

### 15.1 Internal Agent Interface

All agents follow the same interface:

```python
class BaseAgent:
    async def run(self, context: AgentContext) -> AgentResult:
        raise NotImplementedError

    async def run_background(self, context: AgentContext) -> None:
        raise NotImplementedError

class AgentContext:
    user_id: str             # Authenticated user
    input_text: str
    speaker_id: str
    mode: str
    working_memory: list
    injected_flags: list
    skill_registry: SkillRegistry
    mcp_registry: MCPRegistry

class AgentResult:
    response_text: str | None
    memories_to_write: list
    skills_executed: list
    flags_consumed: list
    follow_up_tasks: list
```

### 15.2 Skill Interface Contract

Every skill must:
1. Have a `SKILL.md` with: description, input format, output format, requirements, example
2. Have a `run.py` that reads `input.json` and writes `output.json`
3. Complete within 30 seconds
4. Handle errors gracefully (write error to output.json, never crash silently)

```python
# skills/web_reader/run.py
import json

with open("input.json") as f:
    input_data = json.load(f)

url = input_data["url"]
question = input_data.get("question", "Summarize this page")

# ... do work ...

with open("output.json", "w") as f:
    json.dump({
        "success": True,
        "result": "Main points: ...",
        "metadata": {"url": url, "chars_read": 4200}
    }, f)
```

---

## 16. Concurrency Model

Vayumi uses Python's `asyncio` for all concurrent operations. There are no threads — everything is async/await.

### How Agents Run Concurrently

The canonical processing path is `process_user_turn` in `ws/handler.py` (Section 12.6). Within the orchestrator, agents may run concurrently:

```python
async def orchestrator_run(session, context, text):
    """Inside orchestrator.run() — may dispatch agents concurrently."""
    intent = await classify_intent(context, text)

    if intent.needs_task_agent:
        task_result, _ = await asyncio.gather(
            task_agent.run(context),
            memory_agent.process_turn(session, text, context)
        )
        return assemble(intent, task_result)
    else:
        asyncio.create_task(memory_agent.process_turn(session, text, context))
        return intent.response_text
```

### Concurrent WebSocket Sessions

Each WebSocket connection runs in its own async task. Sessions do not share mutable state — each session has its own working memory, mode, and task state. The only shared resources are:
- **SQLite** (handled by WAL mode + busy timeout)
- **ChromaDB** (thread-safe by default)
- **LLM rate limiter** (uses an async lock)

```python
class RateLimiterLock:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._usage = {}

    async def acquire(self, model, tokens):
        async with self._lock:
            # Check and update usage atomically
            ...
```

---

## 17. Error Handling and Resilience

### Per-Component Failure Behavior

| Component | Failure | Recovery |
|---|---|---|
| **Groq API** | Timeout or rate limit | Auto-fallback to Gemini via LLMRouter |
| **Gemini API** | Timeout or error | Return error message to user: "I'm having trouble thinking right now" |
| **ChromaDB write** | Write fails | Log error, retry once async. Memory is not critical-path. |
| **ChromaDB read** | Query fails | Skip memory injection for this turn. Respond without memories. |
| **SQLite write** | Write fails | Retry with exponential backoff (up to 3 times). Log error. |
| **STT (Groq Whisper)** | Transcription fails | Send "I didn't catch that, could you repeat?" to client |
| **TTS (Kokoro)** | Synthesis fails | Send text-only response to client (degrade gracefully) |
| **Skill execution** | Timeout (>30s) or crash | Return error to orchestrator: "I couldn't complete that task" |
| **WebSocket disconnect** | Connection drops | Session preserved for reconnect window (60s). After that, cleaned up. |
| **Diarizer** | Speaker ID fails or confidence is low | Default to guest/unknown speaker (safe fallback, no private data exposure) |

### Error Logging

All errors are logged with structured JSON format including a correlation ID that traces through the entire turn:

```python
{
    "correlation_id": "turn_abc123",
    "user_id": "user_rahul",
    "session_id": "sess_xyz",
    "component": "llm_router",
    "error": "groq_rate_limit_exceeded",
    "action": "fallback_to_gemini",
    "timestamp": "2026-03-30T14:22:00Z"
}
```

---

## 18. Security and Trust Model

### 18.1 LLM Command Trust

**The LLM is NOT trusted to run arbitrary commands.** It can only:
- Request to run a pre-registered skill by ID
- Call a pre-registered MCP tool by name
- Write to the conversation output

It cannot:
- Directly execute shell commands
- Access the filesystem outside designated skill directories
- Call network endpoints not in MCP registry
- Read environment variables or secrets
- Access data belonging to other users

All LLM tool calls pass through the Orchestrator's validation layer before execution.

### 18.2 Client Trust

- All clients must authenticate before any data exchange
- Browser clients use JWT tokens (short-lived, refreshable)
- ESP32 uses pre-shared device tokens linked to a specific user_id
- No client can directly modify memory or config
- All client actions go through the Orchestrator

### 18.3 User Data Isolation

- Every database query is scoped by `user_id`
- Vector DB queries always include `user_id` in the filter
- File storage is separated by user: `/var/vayumi/files/{user_id}/`
- There is no admin API that can access all users' data (by design)

---

## 19. Phase 1 Build Plan

Phase 1 is **core-only**. No complex skills yet. The goal: a working, natural conversational agent with multi-user support and clean client/server architecture that is ready to accept new skills and tools.

### 19.1 Phase 1 Components

```text
Core Server (FastAPI)
User auth (register, login, JWT tokens)
WebSocket handler (auth + audio in/out)
Groq Whisper STT integration
Kokoro-ONNX TTS integration  
Central Consciousness (Orchestrator Agent)
Basic Memory Agent (write summaries async)
Skill Registry (JSON, empty to start)
MCP Registry (web_search always-on)
Context Builder (user-scoped permanent + working memory)
Interrupt Handler (basic stop/redirect)
Browser client (login + mic + speaker + status UI)
SQLite setup (users, reminders, contacts tables)
ChromaDB setup (episodic memory, user-scoped)
```

### 19.2 Phase 1 Milestones

**Week 1: Server skeleton + voice pipeline (build order matters)**
- Day 1: FastAPI + WebSocket skeleton + auth (register/login/JWT) → test: connect with token, get auth_ok
- Day 2: Session object + message_loop + all handlers (stubbed) → test: send any message type, get a response
- Day 3: Groq Whisper STT + VAD (silero-vad) → test: send audio, get transcript back
- Day 4: Kokoro TTS + stream_response with lookahead → test: hardcoded text → get audio back
- Day 5: Wire STT → hardcoded orchestrator → TTS → test: full audio round-trip end to end

**Week 2: Central Consciousness + memory**
- Orchestrator with basic context builder (user-scoped)
- Memory Agent (write async, tagged with user_id)
- ChromaDB + SQLite connected
- Can remember things across sessions (per user)

**Week 3: Skill + MCP layer scaffolding**
- Skill registry loaded
- MCP registry loaded (web_search enabled)
- Task Agent can load and read a skill doc
- First skill: web_reader

**Week 4: Context engine + persona + ESP32**
- Diarizer integrated
- Persona context switching (per user's contact list)
- Meeting mode
- Interrupt detection
- ESP32-S3-AUDIO-Board basic firmware (WiFi, WebSocket, AEC pipeline, wake word)

### 19.3 Phase 2 (Future)

- Email MCP integration with flag injection
- Calendar MCP
- PDF reader skill
- Document generator skill
- ESP32 advanced features (OTA updates, battery management, LCD display)
- Focus mode and smart home MCPs
- Skill execution isolation (designed per-skill when built)

---

## 20. Future Extensibility

### Adding a New Skill (Example: PDF Reader)

```text
1. Create: skills/pdf_reader/SKILL.md
2. Create: skills/pdf_reader/run.py
3. Add to skill_registry.json:
   {"id": "pdf_reader", "description": "Reads PDF files and extracts content"}
4. Done. No other changes.
```

### Adding a New MCP (Example: Spotify)

```text
1. Implement: mcps/spotify.py (wraps Spotify API)
2. Add to mcp_registry.json:
   {"name": "spotify", "description": "Control Spotify playback"}
3. User enables it in their settings or by saying "connect Spotify"
4. Done. No other changes.
```

### Adding a New Client (Example: Mobile App)

```text
1. Implement WebSocket client in mobile framework
2. Add login screen, store JWT token
3. Send/receive same JSON protocol
4. Done. Server is unchanged.
```

### Adding a New User

```text
1. User registers via /api/auth/register
2. Profile created in users table
3. Empty memory space ready
4. Done. No code changes needed.
```

### Scaling to Cloud

```text
1. Move SQLite → PostgreSQL
2. Move ChromaDB → Qdrant hosted
3. Move Python dict sessions → Redis
4. Deploy FastAPI to server
5. Update client WebSocket URL
6. Done. All other code unchanged.
```

---

## Appendix A: Directory Structure

```text
vayumi/
├── server/
│   ├── .env.example                ← Template for API keys / JWT secret (copy to server/.env)
│   ├── paths.py                    ← Resolved server/data and server/models paths (cwd-independent)
│   ├── main.py                     ← FastAPI app entrypoint, mounts routes
│   ├── ws/
│   │   └── handler.py              ← Unified WebSocket handler (single entry point)
│   ├── auth/
│   │   ├── router.py               ← Register, login, token endpoints
│   │   ├── jwt_handler.py          ← Token creation + validation
│   │   └── models.py               ← UserAccount model
│   ├── core/
│   │   ├── orchestrator.py         ← Central Consciousness
│   │   ├── context_builder.py      ← Dynamic context assembly (user-scoped)
│   │   ├── mode_manager.py         ← Mode switching (per-session)
│   │   └── interrupt_handler.py    ← Interrupt detection + handling
│   ├── agents/
│   │   ├── base_agent.py           ← BaseAgent interface
│   │   ├── memory_agent.py
│   │   ├── task_agent.py
│   │   ├── search_agent.py
│   │   └── persona_agent.py
│   ├── voice/
│   │   ├── stt.py                  ← Groq Whisper wrapper
│   │   ├── tts.py                  ← Kokoro-ONNX wrapper
│   │   ├── diarizer.py             ← Speaker identification
│   │   └── vad.py                  ← Voice activity detection
│   ├── skills/
│   │   ├── skill_runner.py         ← Loads skill docs, executes
│   │   ├── skill_registry.json     ← Names + 1-line descriptions
│   │   ├── web_reader/
│   │   │   ├── SKILL.md
│   │   │   └── run.py
│   │   └── [future skills here]
│   ├── mcps/
│   │   ├── mcp_registry.json
│   │   ├── web_search.py
│   │   ├── reminders.py
│   │   └── [future MCPs here]
│   ├── memory/
│   │   ├── vector_store.py         ← ChromaDB wrapper (user-scoped queries)
│   │   ├── sqlite_store.py         ← SQLite wrapper (user-scoped queries)
│   │   └── embedder.py             ← HuggingFace embeddings
│   ├── llm/
│   │   ├── router.py               ← LLMRouter (Groq primary, Gemini fallback)
│   │   ├── groq_client.py          ← Groq API wrapper
│   │   └── gemini_client.py        ← Gemini API wrapper
│   ├── config/
│   │   └── settings.json           ← Server-level settings (ports, paths, limits)
│   ├── data/
│   │   ├── vayumi.db               ← SQLite (users, reminders, meetings, etc.)
│   │   └── vectordb/               ← ChromaDB persistent
│   └── models/
│       ├── kokoro-v0_19.onnx       ← Kokoro TTS (download separately)
│       ├── voices.bin              ← Kokoro voice embeddings (download separately)
│       └── speaker_encoder/        ← SpeechBrain ECAPA cache (downloaded on first run)
├── client/
│   ├── browser/
│   │   ├── .env.example            ← URL / config reference (static JS does not load .env by default)
│   │   ├── index.html
│   │   ├── app.js                  ← Login + WebSocket + audio logic
│   │   └── ui.js                   ← Status, transcript UI
│   └── esp32/                      ← ESP32-S3-AUDIO-Board firmware (ESP-IDF + ESP-ADF)
│       ├── main/
│       │   ├── main.c              ← App entrypoint, WiFi init, task orchestration
│       │   ├── audio_pipeline.c    ← ESP-ADF pipeline: I2S → AEC+NS+BSS → clean buffer
│       │   ├── ws_client.c         ← WebSocket client, auth, send/receive audio + JSON
│       │   ├── wake_word.c         ← ESP-SR wake word detection ("Hi Vayumi")
│       │   └── led.c              ← RGB LED ring status (sleep/active/speaking/error)
│       ├── CMakeLists.txt
│       └── sdkconfig               ← ESP-IDF build config
├── requirements.txt
└── README.md
```

---

## Appendix B: Key Design Decisions (Rationale)

**Skill docs are Markdown files, not code**  
Readable by both humans and LLMs. Easy to add/edit without programming. The LLM reads the doc to understand what to do.

**Context budget enforced strictly**  
Prevents context bloat which degrades LLM quality and increases cost. Clear priority rules for what gets trimmed.

**Memory Agent is async**  
Never blocks the response. User doesn't wait for memory writes. If memory write fails, the conversation still works.

**TTS starts streaming before full response**  
Dramatically reduces perceived latency. Feels natural — like a human starting to speak.

**WebSocket for all client comms**  
Works on ESP32, browser, mobile with the same protocol. Bidirectional, low-latency.

**ChromaDB for Phase 1, Qdrant for production**  
ChromaDB is simple to set up locally and good enough for development. Qdrant handles production scale and multi-user better.

**Python dict for Phase 1 sessions, Redis for production**  
Avoids external dependency in development. Redis swap is a one-line change for production.

**SQLite with WAL mode for Phase 1, PostgreSQL for production**  
WAL handles moderate concurrent writes. PostgreSQL is the production path when scaling beyond 3 users or deploying to cloud.

**Vector DB for episodic memory**  
Semantic search is far superior to keyword matching for "what did I talk about last week?"

**Personas filtered at context builder level**  
LLM never needs to decide what to hide — the infrastructure handles it. Security by architecture, not by prompt.

**LLM cannot directly execute commands**  
Security first. All tool calls validated before execution.

**Every table has user_id**  
Data isolation by design. No code path can accidentally leak data between users.

---

## Appendix C: Environment Setup

### Required API Keys

| Service | Key | Purpose |
|---|---|---|
| Groq | `GROQ_API_KEY` | STT (Whisper) + LLM inference |
| Google AI | `GEMINI_API_KEY` | Fallback LLM |

### Required Model Downloads

| Model | Size | Purpose |
|---|---|---|
| `server/models/kokoro-v0_19.onnx` + `server/models/voices.bin` | ~80MB | Local TTS (place files here) |
| `all-MiniLM-L6-v2` | ~80MB | Local text embeddings (auto-downloaded by sentence-transformers) |
| `spkrec-ecapa-voxceleb` | ~400MB | Speaker verification embeddings (auto-downloaded by SpeechBrain on first run) |

### System Dependencies

```text
Python 3.11+
FastAPI + uvicorn
chromadb
sentence-transformers
groq (Python SDK — use AsyncGroq for non-blocking LLM calls)
google-generativeai (Python SDK)
kokoro-onnx
bcrypt (for password hashing)
PyJWT (for token auth)
numpy (PCM conversion, audio processing)
torch + torchaudio (SpeechBrain dependency — install CPU-only: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu)
silero-vad (voice activity detection — recommended over webrtcvad)
speechbrain (voice embeddings for diarizer speaker identification, uses ECAPA-TDNN)
```

### Quick Start (Phase 1)

```bash
# Clone and setup
cd vayumi
pip install -r requirements.txt

# Server secrets: copy server/.env.example → server/.env and edit, then export
# (or wire python-dotenv in server/main.py to load server/.env)
cp server/.env.example server/.env
# export GROQ_API_KEY / GEMINI_API_KEY / VAYUMI_JWT_SECRET as needed

# Run server
uvicorn server.main:app --host 0.0.0.0 --port 8000

# Browser client: static files; see client/browser/.env.example for URL conventions
open client/browser/index.html
```

---

*Document Version 2.4 — Added: input queue drain rules (cancel discards all, otherwise last-item-wins), TTS lookahead buffer (pre-synthesize sentence N+1 while N plays for gap-free speech), SpeechBrain ECAPA-TDNN specified as diarizer model with latency/accuracy notes and async embedding, torch dependency added, Week 1 day-by-day build order*  
*Previous: v2.3 — stream_response state ownership, TTS API fix, echo gating, wake word, ESP32 firmware*  
*Next update: After Phase 1 server skeleton is complete*
