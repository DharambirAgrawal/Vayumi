TOOLS = [
    {
        "name": "memory_search",
        "description": (
            "Search long-term memory for relevant facts, past conversations, meetings, "
            "files, links, images, or user preferences. Always call this at the start "
            "of a turn before generating a response."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "speaker_id": {
                    "type": "string",
                    "description": "Filter to one person's memories. Omit to search all.",
                },
                "type_filter": {
                    "type": "string",
                    "enum": ["meeting", "link", "image", "audio", "file", "fact", "preference", "any"],
                    "description": "Filter by memory type. Omit to search all types.",
                },
                "date_from": {"type": "string", "description": "ISO date e.g. 2026-03-01"},
                "date_to": {"type": "string", "description": "ISO date e.g. 2026-03-31"},
                "source_url": {
                    "type": "string",
                    "description": "Filter to a URL or domain e.g. github.com",
                },
                "top_k": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_ingest",
        "description": (
            "Save a file, image, audio clip, link, or meeting recording to long-term "
            "memory. Call this immediately when the user shares any URL, file, image, "
            "or audio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_type": {
                    "type": "string",
                    "enum": ["audio", "image", "file", "link", "meeting"],
                    "description": "Type of content being ingested",
                },
                "content": {"type": "string", "description": "URL string, or base64-encoded file data"},
                "speaker_id": {"type": "string", "description": "Who is sharing this"},
                "date": {"type": "string", "description": "ISO date if known e.g. 2026-03-03"},
                "title": {"type": "string", "description": "Optional human-readable title"},
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For meetings only: list of speaker_ids who attended",
                },
            },
            "required": ["source_type", "content", "speaker_id"],
        },
    },
    {
        "name": "memory_save",
        "description": (
            "Save a standalone fact, preference, or event to long-term memory. "
            "Call this after a turn when something worth remembering was said."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact in plain English"},
                "speaker_id": {"type": "string", "description": "Who this belongs to"},
                "memory_type": {
                    "type": "string",
                    "enum": ["fact", "preference", "event", "relationship"],
                    "description": "Category of this memory",
                },
                "expires_at": {
                    "type": "string",
                    "description": "ISO date if this should expire. Omit for permanent.",
                },
            },
            "required": ["content", "speaker_id", "memory_type"],
        },
    },
    {
        "name": "memory_delete",
        "description": (
            "Delete a specific memory. Call when user asks to forget/remove something "
            "specific and pass the memory_id from a prior memory_search call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "ID from memory_search results"},
                "speaker_id": {
                    "type": "string",
                    "description": "Owner of the memory (for permission check)",
                },
            },
            "required": ["memory_id", "speaker_id"],
        },
    },
    {
        "name": "memory_update",
        "description": (
            "Update an existing memory when a fact has changed. "
            "Get memory_id from prior memory_search results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "ID of the memory to update"},
                "new_content": {
                    "type": "string",
                    "description": "The updated fact in plain English",
                },
                "speaker_id": {"type": "string", "description": "Owner of the memory"},
            },
            "required": ["memory_id", "new_content", "speaker_id"],
        },
    },
    {
        "name": "memory_update_by_query",
        "description": (
            "Find the best matching memory using a query and update it in one step. "
            "Use this when user corrects a fact but memory_id is not known."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query to find target memory to update"},
                "new_content": {"type": "string", "description": "Updated memory content"},
                "speaker_id": {"type": "string", "description": "Owner of memory"},
            },
            "required": ["query", "new_content", "speaker_id"],
        },
    },
    {
        "name": "memory_delete_links",
        "description": (
            "Delete link memories in bulk for a speaker. "
            "Use domain to delete domain-specific links, or set delete_all=true to remove all links."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "speaker_id": {"type": "string", "description": "Owner of memory links"},
                "domain": {"type": "string", "description": "Optional domain filter, e.g. github.com"},
                "delete_all": {
                    "type": "boolean",
                    "description": "If true, delete all links for speaker regardless of domain",
                },
            },
            "required": ["speaker_id"],
        },
    },
    {
        "name": "memory_get_user_model",
        "description": "Return the current personalization model for a speaker, including emotional trend history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "speaker_id": {
                    "type": "string",
                    "description": "Speaker id to load personalization model for.",
                }
            },
            "required": ["speaker_id"],
        },
    },
    {
        "name": "memory_add_turn",
        "description": "Add one conversation turn to short-term memory buffer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "speaker_id": {"type": "string", "description": "Speaker id of this turn."},
                "text": {"type": "string", "description": "Raw turn text."},
            },
            "required": ["speaker_id", "text"],
        },
    },
    {
        "name": "memory_flush_session",
        "description": "Flush short-term session into durable memory and refresh personalization model.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
