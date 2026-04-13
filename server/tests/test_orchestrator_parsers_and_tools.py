from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from orchestrator import directive_parser
from orchestrator import function_parser
from orchestrator.capability_router import resolve
from orchestrator.main_agent import _heuristic_reply
from orchestrator.tools import execute_function, get_schemas_for_main_llm, get_schemas_for_task
from orchestrator.tools import media as media_tools
import main as server_main
from memory.tools import TOOLS as MEMORY_TOOLS


PNG_BASE64_SAMPLE = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6X5X8AAAAASUVORK5CYII="
)


def test_parse_function_call_with_mixed_values() -> None:
    text = (
        '<start_function_call>call:web_search{query:"latest ai regulation",top_k:5,flag:true,'
        'meta:{"a":1},tags:["x","y"]}<end_function_call>'
    )
    out = function_parser.parse_function_call(text)

    assert out["success"] is True
    assert out["function_name"] == "web_search"
    assert out["params"]["query"] == "latest ai regulation"
    assert out["params"]["top_k"] == 5
    assert out["params"]["flag"] is True
    assert out["params"]["meta"]["a"] == 1
    assert out["params"]["tags"] == ["x", "y"]


def test_extract_text_from_dict_content() -> None:
    payload = {"content": [{"type": "text", "text": "Hello"}, {"type": "text", "text": " world"}]}
    assert function_parser.extract_text(payload) == "Hello world"


def test_directive_parser_multiple_directives() -> None:
    blob = (
        "[DELEGATE]\n"
        "task: Summarize latest robotics policy\n"
        "capability: research\n\n"
        "[STOP]\n"
        "task_id: task_1\n\n"
        "[ANSWER_TO]\n"
        "task_id: task_2\n"
        "answer: Use Q3 metrics\n\n"
        "[MODE_SWITCH]\n"
        "mode: meeting\n"
    )
    directives = directive_parser.parse(blob)
    assert [d["type"] for d in directives] == ["DELEGATE", "STOP", "ANSWER_TO", "MODE_SWITCH"]


def test_main_llm_heuristic_reply_directive_and_tool_path() -> None:
    meeting = _heuristic_reply("please switch to meeting mode")
    assert "[MODE_SWITCH]" in meeting

    search = _heuristic_reply("search latest chip act updates")
    assert "<start_function_call>" in search
    assert "web_search" in search


def test_tool_registry_schema_filters_and_execution() -> None:
    main_schemas = get_schemas_for_main_llm()
    names = {schema["function"]["name"] for schema in main_schemas}
    memory_names = {tool["name"] for tool in MEMORY_TOOLS}
    assert memory_names.issubset(names)
    assert {"web_search", "memory_search", "memory_save", "memory_update", "read_url", "analyze_image", "transcribe_audio", "analyze_video"}.issubset(names)

    task_schemas = get_schemas_for_task(["doc_generator", "missing_tool"])
    assert len(task_schemas) == 1
    assert task_schemas[0]["function"]["name"] == "doc_generator"

    assert "read_url" in resolve(["research"])

    unknown = execute_function("does_not_exist", {})
    assert unknown.startswith("ERROR: Unknown function")


def test_data_analyzer_execution() -> None:
    result = execute_function("data_analyzer", {"numbers": [1, 2, 3, 4]})
    parsed = json.loads(result)
    assert parsed["count"] == 4
    assert parsed["avg"] == pytest.approx(2.5)


def test_media_tool_calls_handle_base64_payloads() -> None:
    image_result = execute_function("analyze_image", {"image_data": PNG_BASE64_SAMPLE})
    audio_result = execute_function("transcribe_audio", {"audio_data": base64.b64encode(b"audio-bytes").decode("ascii")})
    video_result = execute_function("analyze_video", {"video_data": base64.b64encode(b"video-bytes").decode("ascii")})

    assert "Image" in image_result or "summary" in image_result
    assert audio_result
    assert video_result


def test_read_url_applies_instruction_and_reports_blocked_page(monkeypatch) -> None:
    monkeypatch.setattr(
        media_tools,
        "_fetch_with_scrapling",
        lambda url, prefer_dynamic=True: (_ for _ in ()).throw(RuntimeError("scrapling unavailable")),
    )
    monkeypatch.setattr(media_tools, "_read_bytes_from_url", lambda url, timeout=12.0, max_bytes=8_000_000: b"<html><body><h1>Title</h1><p>First line. Second line. Third line.</p></body></html>")

    payload = json.loads(
        execute_function(
            "read_url",
            {"url": "https://example.com/article", "instruction": "tell me in short", "prefer_dynamic": False},
        )
    )
    assert payload["fetchable"] is True
    assert payload["status"] == "ok"
    assert "First line" in payload["summary"]

    monkeypatch.setattr(
        media_tools,
        "_read_bytes_from_url",
        lambda url, timeout=12.0, max_bytes=8_000_000: (_ for _ in ()).throw(PermissionError("403 Forbidden")),
    )
    blocked = json.loads(execute_function("read_url", {"url": "https://example.com/private"}))
    assert blocked["fetchable"] is False
    assert blocked["status"] in {"blocked", "error"}


def test_instructional_summary_variants() -> None:
    text = (
        "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence. "
        "A quoted line: \"important thing\". Another quoted line: \"follow up\"."
    )

    short = media_tools._instructional_summary(text, "short summary")
    bullets = media_tools._instructional_summary(text, "give bullets")
    steps = media_tools._instructional_summary(text, "write steps")

    assert short.count(".") <= 3
    assert bullets.startswith("-")
    assert "1." in steps


@pytest.mark.asyncio
async def test_attachment_context_includes_media_summaries(monkeypatch):
    monkeypatch.setattr(server_main, "external_read_url", lambda url: json.dumps({"url": url, "summary": "link summary"}))
    monkeypatch.setattr(server_main, "external_analyze_image", lambda data: json.dumps({"summary": "image summary"}))
    monkeypatch.setattr(server_main, "external_transcribe_audio", lambda data: json.dumps({"transcript": "audio transcript"}))
    monkeypatch.setattr(server_main, "external_analyze_video", lambda data: json.dumps({"summary": "video summary"}))

    context = await server_main._compose_transcript_with_attachments(
        "Check these files",
        [
            {"type": "link", "url": "https://example.com/post"},
            {"type": "image", "data": PNG_BASE64_SAMPLE},
            {"type": "audio", "data": base64.b64encode(b"audio-bytes").decode("ascii")},
            {"type": "video", "data": base64.b64encode(b"video-bytes").decode("ascii")},
        ],
    )

    assert "link summary" in context
    assert "image summary" in context
    assert "audio transcript" in context
    assert "video summary" in context
