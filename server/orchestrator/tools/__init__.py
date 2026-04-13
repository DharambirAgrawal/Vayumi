from __future__ import annotations

from typing import Any

from ..constants import ToolId
from .media import analyze_image, analyze_video, read_url, transcribe_audio
from .date_time import current_date, current_time, echo_text
from .data_analyzer import data_analyzer
from .doc_generator import doc_generator
from .email_reader import email_reader
from .memory_ops import (
    memory_add_turn,
    memory_delete,
    memory_delete_links,
    memory_flush_session,
    memory_get_user_model,
    memory_ingest,
    memory_save,
    memory_search,
    memory_update,
    memory_update_by_query,
)
from .url_summarizer import url_summarizer
from .web_search import web_search
from memory.tools import TOOLS as MEMORY_TOOLS


def _schema_from_memory_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


MEMORY_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    tool["name"]: _schema_from_memory_tool(tool) for tool in MEMORY_TOOLS
}


def _memory_schema(name: str) -> dict[str, Any]:
    return MEMORY_TOOL_SCHEMAS[name]

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "current_time": {
        "fn": current_time,
        "schema": {
            "type": "function",
            "function": {
                "name": "current_time",
                "description": "Get current UTC time.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    "current_date": {
        "fn": current_date,
        "schema": {
            "type": "function",
            "function": {
                "name": "current_date",
                "description": "Get current UTC date.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    "echo_text": {
        "fn": echo_text,
        "schema": {
            "type": "function",
            "function": {
                "name": "echo_text",
                "description": "Echo back text for tool-call smoke testing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to echo back."}
                    },
                    "required": ["text"],
                },
            },
        },
        "has_skill_doc": False,
        "main_llm_direct": False,
    },
    ToolId.WEB_SEARCH: {
        "fn": web_search,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.WEB_SEARCH,
                "description": "Search the web for current information.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query, 3-8 words."}
                    },
                    "required": ["query"],
                },
            },
        },
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.READ_URL: {
        "fn": read_url,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.READ_URL,
                "description": "Fetch, clean, and summarize a URL. Can follow an instruction like short, bullets, steps, or extract quotes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Absolute URL to read."},
                        "instruction": {
                            "type": "string",
                            "description": "Optional instruction for how to summarize the page.",
                        },
                        "prefer_dynamic": {
                            "type": "boolean",
                            "description": "Prefer a dynamic fetch path when available.",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum characters to return in the cleaned content.",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
        "has_skill_doc": True,
        "main_llm_direct": True,
    },
    ToolId.ANALYZE_IMAGE: {
        "fn": analyze_image,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.ANALYZE_IMAGE,
                "description": "Describe an uploaded image attachment.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_data": {
                            "type": "string",
                            "description": "Base64-encoded image bytes.",
                        }
                    },
                    "required": ["image_data"],
                },
            },
        },
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.TRANSCRIBE_AUDIO: {
        "fn": transcribe_audio,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.TRANSCRIBE_AUDIO,
                "description": "Transcribe an uploaded audio attachment.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "audio_data": {
                            "type": "string",
                            "description": "Base64-encoded audio bytes.",
                        }
                    },
                    "required": ["audio_data"],
                },
            },
        },
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.ANALYZE_VIDEO: {
        "fn": analyze_video,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.ANALYZE_VIDEO,
                "description": "Describe an uploaded video attachment by sampling frames and audio.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "video_data": {
                            "type": "string",
                            "description": "Base64-encoded video bytes.",
                        }
                    },
                    "required": ["video_data"],
                },
            },
        },
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.URL_SUMMARIZER: {
        "fn": url_summarizer,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.URL_SUMMARIZER,
                "description": "Read and summarize content from a URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Absolute URL to summarize."}
                    },
                    "required": ["url"],
                },
            },
        },
        "has_skill_doc": True,
        "main_llm_direct": False,
    },
    ToolId.EMAIL_READER: {
        "fn": email_reader,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.EMAIL_READER,
                "description": "Read/search inbox messages using a natural-language query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query over email data."}
                    },
                    "required": ["query"],
                },
            },
        },
        "has_skill_doc": True,
        "main_llm_direct": False,
    },
    ToolId.DOC_GENERATOR: {
        "fn": doc_generator,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.DOC_GENERATOR,
                "description": "Generate a document draft in markdown, pdf, docx, or txt format.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Document title."},
                        "content": {"type": "string", "description": "Document body content."},
                        "format": {
                            "type": "string",
                            "enum": ["markdown", "pdf", "docx", "txt"],
                            "description": "Output format.",
                        },
                    },
                    "required": ["title", "content"],
                },
            },
        },
        "has_skill_doc": True,
        "main_llm_direct": False,
    },
    ToolId.DATA_ANALYZER: {
        "fn": data_analyzer,
        "schema": {
            "type": "function",
            "function": {
                "name": ToolId.DATA_ANALYZER,
                "description": "Run quick descriptive stats on numeric data.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "numbers": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Numeric values to analyze.",
                        }
                    },
                    "required": ["numbers"],
                },
            },
        },
        "has_skill_doc": False,
        "main_llm_direct": False,
    },
    ToolId.MEMORY_SEARCH: {
        "fn": memory_search,
        "schema": _memory_schema(ToolId.MEMORY_SEARCH),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_SAVE: {
        "fn": memory_save,
        "schema": _memory_schema(ToolId.MEMORY_SAVE),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_UPDATE: {
        "fn": memory_update,
        "schema": _memory_schema(ToolId.MEMORY_UPDATE),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_UPDATE_BY_QUERY: {
        "fn": memory_update_by_query,
        "schema": _memory_schema(ToolId.MEMORY_UPDATE_BY_QUERY),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_DELETE: {
        "fn": memory_delete,
        "schema": _memory_schema(ToolId.MEMORY_DELETE),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_INGEST: {
        "fn": memory_ingest,
        "schema": _memory_schema(ToolId.MEMORY_INGEST),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_DELETE_LINKS: {
        "fn": memory_delete_links,
        "schema": _memory_schema(ToolId.MEMORY_DELETE_LINKS),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_GET_USER_MODEL: {
        "fn": memory_get_user_model,
        "schema": _memory_schema(ToolId.MEMORY_GET_USER_MODEL),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_ADD_TURN: {
        "fn": memory_add_turn,
        "schema": _memory_schema(ToolId.MEMORY_ADD_TURN),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    ToolId.MEMORY_FLUSH_SESSION: {
        "fn": memory_flush_session,
        "schema": _memory_schema(ToolId.MEMORY_FLUSH_SESSION),
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
}


def get_schemas_for_main_llm() -> list[dict[str, Any]]:
    return [item["schema"] for item in TOOL_REGISTRY.values() if item["main_llm_direct"]]


def get_schemas_for_task(tool_ids: list[str]) -> list[dict[str, Any]]:
    return [TOOL_REGISTRY[tool_id]["schema"] for tool_id in tool_ids if tool_id in TOOL_REGISTRY]


def get_tool_ids_with_skill_docs(tool_ids: list[str]) -> list[str]:
    return [tool_id for tool_id in tool_ids if TOOL_REGISTRY.get(tool_id, {}).get("has_skill_doc")]


def get_all_tool_ids() -> list[str]:
    return list(TOOL_REGISTRY.keys())


def execute_function(name: str, params: dict[str, Any]) -> str:
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return f"ERROR: Unknown function {name}"

    try:
        result = entry["fn"](**params)
        return str(result)
    except Exception as exc:  # pragma: no cover - defensive
        return f"ERROR: {exc}"
