from __future__ import annotations

import atexit
import datetime
import json
import mimetypes
import multiprocessing as mp
import os
import queue
import re
import subprocess
import shutil
import time
import tempfile
from pathlib import Path
from typing import Any

import cv2
import gradio as gr
import imageio_ffmpeg
import litert_lm

SYSTEM_MESSAGES = [
    {
        "role": "system",
        "content": [
            {"type": "text", "text": "You are a helpful assistant."}
        ],
    }
]


def get_current_time() -> str:
    """Returns the current date and time."""
    print("[tool_call] get_current_time")
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_numbers(a: float, b: float) -> float:
    """Adds two numbers.

    Args:
        a: The first number.
        b: The second number.
    """
    print(f"[tool_call] add_numbers(a={a}, b={b})")
    return a + b


AGENT_TOOLS = [get_current_time, add_numbers]


def _build_function_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "add_numbers",
                "description": "Adds two numbers together (a + b).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "First number"},
                        "b": {"type": "number", "description": "Second number"},
                    },
                    "required": ["a", "b"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "Returns the current date and time as formatted text.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    ]


FUNCTION_SCHEMAS = _build_function_schemas()
FUNCTION_SCHEMA_INDEX = {item["function"]["name"]: item["function"] for item in FUNCTION_SCHEMAS}
FUNCTION_CALL_PATTERN = re.compile(r"<start_function_call>call:(\w+)\{([^}]*)\}</?end_function_call>")

AGENT_SYSTEM_MESSAGE = (
    "You are a function-routing engine for a local assistant. "
    "Strictly output one function call and no extra prose. "
    "Use this exact format with scalar values only: "
    "<start_function_call>call:function_name{key:value}<end_function_call>.\n\n"
    "Routing rules:\n"
    "1) Use get_current_time for current date/time questions.\n"
    "2) Use add_numbers for addition/math sum requests.\n"
    "3) Use integer types for integer fields where possible.\n"
    "4) Do not invent keys that are not in schema.\n"
    "5) If no function applies, answer normally in plain text.\n\n"
    f"Functions JSON schema:\n{json.dumps(FUNCTION_SCHEMAS, indent=2)}"
)


def _coerce_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value


def _parse_function_call(output: str) -> dict[str, Any]:
    match = FUNCTION_CALL_PATTERN.search(output)
    if not match:
        return {"success": False, "error": "Could not parse function call pattern"}

    function_name = match.group(1)
    params_str = match.group(2)
    params: dict[str, Any] = {}

    escaped_pairs = re.findall(r"(\w+):<escape>([^<]+)<escape>", params_str)
    if escaped_pairs:
        for key, value in escaped_pairs:
            params[key] = _coerce_scalar(value.strip())
        return {"success": True, "function_name": function_name, "params": params}

    if params_str.strip():
        for pair in params_str.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue
            key, value = pair.split(":", 1)
            params[key.strip()] = _coerce_scalar(value.strip())

    return {"success": True, "function_name": function_name, "params": params}


def _validate_params(function_schema: dict[str, Any], params: dict[str, Any]) -> tuple[bool, str]:
    parameter_schema = function_schema.get("parameters", {})
    properties = parameter_schema.get("properties", {})
    required = parameter_schema.get("required", [])

    for key in required:
        if key not in params:
            return False, f"Missing required param: {key}"

    for key, value in params.items():
        if key not in properties:
            return False, f"Unexpected param: {key}"

        expected_type = properties[key].get("type")
        if expected_type == "number" and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            return False, f"Param '{key}' must be number"
        if expected_type == "integer" and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False, f"Param '{key}' must be integer"
        if expected_type == "string" and not isinstance(value, str):
            return False, f"Param '{key}' must be string"
        if expected_type == "boolean" and not isinstance(value, bool):
            return False, f"Param '{key}' must be boolean"

    return True, "ok"


def _execute_agent_function(function_name: str, params: dict[str, Any]) -> Any:
    function_map = {
        "add_numbers": add_numbers,
        "get_current_time": get_current_time,
    }
    if function_name not in function_map:
        raise ValueError(f"Unknown function: {function_name}")
    return function_map[function_name](**params)

_engine_ctx = None
_engine = None
_conversation_ctx = None
_conversation = None
_model_path: Path | None = None
_worker_proc: mp.Process | None = None
_worker_req_q: mp.Queue | None = None
_worker_resp_q: mp.Queue | None = None
_video_temp_dirs: list[Path] = []


def _model_search_roots() -> list[Path]:
    default_root = (Path.cwd() / "models/llm/gemma4-e2b").resolve()
    configured_root = Path(os.environ.get("LITERT_MODEL_ROOT", str(default_root))).expanduser()

    roots: list[Path] = []
    for root in [configured_root, Path("./models"), Path("./my_model")]:
        resolved = root.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def find_model_path() -> Path:
    roots = _model_search_roots()
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(sorted(root.rglob("*.litertlm")))

    if not candidates:
        searched = "\n - ".join(str(root) for root in roots)
        raise FileNotFoundError(
            "No .litertlm model found. Searched:\n"
            f" - {searched}\n"
            "Set LITERT_MODEL_ROOT to your model directory if needed."
        )

    for candidate in candidates:
        if "qualcomm" not in candidate.name.lower():
            return candidate
    return candidates[0]


def _worker_main(model_path: str, cache_dir: str, req_q: mp.Queue, resp_q: mp.Queue) -> None:
    litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)

    engine_ctx = None
    conversation_ctx = None
    engine = None
    conversation = None
    agent_mode_enabled = False

    def recreate_conversation() -> None:
        nonlocal conversation_ctx, conversation

        if conversation_ctx is not None:
            conversation_ctx.__exit__(None, None, None)

        if agent_mode_enabled:
            messages = SYSTEM_MESSAGES + [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": AGENT_SYSTEM_MESSAGE,
                        }
                    ],
                }
            ]
            conversation_ctx = engine.create_conversation(messages=messages)
        else:
            conversation_ctx = engine.create_conversation(messages=SYSTEM_MESSAGES)
        conversation = conversation_ctx.__enter__()

    try:
        engine_ctx = litert_lm.Engine(
            model_path,
            backend=litert_lm.Backend.CPU,
            vision_backend=litert_lm.Backend.CPU,
            audio_backend=litert_lm.Backend.CPU,
            cache_dir=cache_dir,
        )
        engine = engine_ctx.__enter__()
        recreate_conversation()

        while True:
            req = req_q.get()
            if req is None or req.get("cmd") == "stop":
                break

            if req.get("cmd") == "reset":
                if "enabled" in req:
                    agent_mode_enabled = bool(req["enabled"])
                recreate_conversation()
                resp_q.put({"ok": True, "agent_mode": agent_mode_enabled})
                continue

            if req.get("cmd") == "set_mode":
                requested_mode = bool(req.get("enabled", False))
                if requested_mode != agent_mode_enabled:
                    agent_mode_enabled = requested_mode
                    recreate_conversation()
                resp_q.put({"ok": True, "agent_mode": agent_mode_enabled})
                continue

            if req.get("cmd") == "chat":
                try:
                    if agent_mode_enabled:
                        response = conversation.send_message(req["message"])
                        raw_output = _response_text(response)
                        call_info = _parse_function_call(raw_output)

                        if not call_info.get("success"):
                            resp_q.put({"ok": True, "event": "done", "response": response})
                            continue

                        function_name = call_info["function_name"]
                        params = call_info["params"]

                        function_schema = FUNCTION_SCHEMA_INDEX.get(function_name)
                        if function_schema is None:
                            resp_q.put(
                                {
                                    "ok": True,
                                    "event": "done",
                                    "response": {
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": f"Function call failed: unknown function '{function_name}'.",
                                            }
                                        ]
                                    },
                                }
                            )
                            continue

                        valid, reason = _validate_params(function_schema, params)
                        if not valid:
                            resp_q.put(
                                {
                                    "ok": True,
                                    "event": "done",
                                    "response": {
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": f"Function call failed validation: {reason}",
                                            }
                                        ]
                                    },
                                }
                            )
                            continue

                        result = _execute_agent_function(function_name, params)
                        resp_q.put(
                            {
                                "ok": True,
                                "event": "done",
                                "response": {
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": f"{function_name}({params}) -> {result}",
                                        }
                                    ]
                                },
                            }
                        )
                        continue

                    if req.get("stream"):
                        for chunk in conversation.send_message_async(req["message"]):
                            chunk_text = ""
                            for item in chunk.get("content", []):
                                if item.get("type") == "text":
                                    chunk_text += item.get("text", "")
                            if chunk_text:
                                resp_q.put({"ok": True, "event": "chunk", "text": chunk_text})
                        resp_q.put({"ok": True, "event": "done"})
                    else:
                        response = conversation.send_message(req["message"])
                        resp_q.put({"ok": True, "event": "done", "response": response})
                except Exception as exc:
                    resp_q.put({"ok": False, "error": str(exc)})
                continue

            resp_q.put({"ok": False, "error": "Unknown worker command"})
    finally:
        if conversation_ctx is not None:
            conversation_ctx.__exit__(None, None, None)
        if engine_ctx is not None:
            engine_ctx.__exit__(None, None, None)


def _start_worker() -> None:
    global _worker_proc, _worker_req_q, _worker_resp_q, _model_path

    if _worker_proc is not None and _worker_proc.is_alive():
        return

    _model_path = find_model_path()
    cache_dir = _model_path.parent / ".litert_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    _worker_req_q = mp.Queue()
    _worker_resp_q = mp.Queue()
    _worker_proc = mp.Process(
        target=_worker_main,
        args=(str(_model_path), str(cache_dir), _worker_req_q, _worker_resp_q),
        daemon=True,
    )
    _worker_proc.start()


def _stop_worker() -> None:
    global _worker_proc, _worker_req_q, _worker_resp_q

    if _worker_proc is None:
        return

    if _worker_proc.is_alive() and _worker_req_q is not None:
        _worker_req_q.put({"cmd": "stop"})
        _worker_proc.join(timeout=2)
        if _worker_proc.is_alive():
            _worker_proc.terminate()
            _worker_proc.join(timeout=2)

    _worker_proc = None
    _worker_req_q = None
    _worker_resp_q = None


def _cleanup_temp_dirs() -> None:
    global _video_temp_dirs

    for temp_dir in _video_temp_dirs:
        shutil.rmtree(temp_dir, ignore_errors=True)
    _video_temp_dirs = []


def _request_worker(payload: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
    _start_worker()

    if _worker_proc is None or _worker_req_q is None or _worker_resp_q is None:
        return {"ok": False, "error": "Failed to start inference worker."}

    _worker_req_q.put(payload)
    deadline = time.time() + timeout

    while time.time() < deadline:
        if not _worker_proc.is_alive():
            _stop_worker()
            _start_worker()
            return {
                "ok": False,
                "error": "LiteRT runtime crashed while handling this request. Worker has been restarted.",
            }
        try:
            return _worker_resp_q.get(timeout=0.2)
        except queue.Empty:
            continue

    return {"ok": False, "error": "Timed out waiting for model response."}


def _request_worker_stream(payload: dict[str, Any], timeout: float = 180.0):
    _start_worker()

    if _worker_proc is None or _worker_req_q is None or _worker_resp_q is None:
        yield {"ok": False, "error": "Failed to start inference worker."}
        return

    _worker_req_q.put(payload)
    deadline = time.time() + timeout

    while time.time() < deadline:
        if not _worker_proc.is_alive():
            _stop_worker()
            _start_worker()
            yield {
                "ok": False,
                "error": "LiteRT runtime crashed while handling this request. Worker has been restarted.",
            }
            return

        try:
            msg = _worker_resp_q.get(timeout=0.2)
        except queue.Empty:
            continue

        yield msg
        if msg.get("ok") and msg.get("event") == "done":
            return

    yield {"ok": False, "error": "Timed out waiting for model response."}


def _guess_media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("video/"):
            return "video"

    ext = path.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return "image"
    if ext in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
        return "audio"
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return "video"
    return "file"


def _extract_video_frames(video_path: Path, max_frames: int = 4) -> list[Path]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return []

    temp_dir = Path(tempfile.mkdtemp(prefix="litert_video_"))
    _video_temp_dirs.append(temp_dir)

    frame_paths: list[Path] = []
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if total_frames > 0:
        sample_count = min(max_frames, total_frames)
        if sample_count == 1:
            frame_indices = [0]
        else:
            frame_indices = sorted(
                {
                    int(round(index * (total_frames - 1) / (sample_count - 1)))
                    for index in range(sample_count)
                }
            )

        for index, frame_index in enumerate(frame_indices):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = capture.read()
            if not success:
                continue
            frame_path = temp_dir / f"frame_{index:02d}.jpg"
            cv2.imwrite(str(frame_path), frame)
            frame_paths.append(frame_path)
    else:
        while len(frame_paths) < max_frames:
            success, frame = capture.read()
            if not success:
                break
            frame_path = temp_dir / f"frame_{len(frame_paths):02d}.jpg"
            cv2.imwrite(str(frame_path), frame)
            frame_paths.append(frame_path)

    capture.release()
    return frame_paths


def _extract_video_audio(video_path: Path) -> Path | None:
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    temp_dir = Path(tempfile.mkdtemp(prefix="litert_video_"))
    _video_temp_dirs.append(temp_dir)

    audio_path = temp_dir / f"{video_path.stem}_audio.wav"
    command = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not audio_path.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        _video_temp_dirs.remove(temp_dir)
        return None

    return audio_path


def _extract_file_path(file_item: Any) -> Path | None:
    if isinstance(file_item, str):
        return Path(file_item)
    if isinstance(file_item, dict) and "path" in file_item:
        return Path(str(file_item["path"]))
    return None


def _build_user_message(message: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(message, dict):
        return None, ""

    text = (message.get("text") or "").strip()
    files = message.get("files") or []

    content = []
    preview_parts = []

    if text:
        content.append({"type": "text", "text": text})
        preview_parts.append(text)

    for file_item in files:
        file_path = _extract_file_path(file_item)
        if file_path is None:
            continue

        media_type = _guess_media_type(file_path)

        if media_type in {"image", "audio"}:
            content.append({"type": media_type, "path": str(file_path)})
            preview_parts.append(f"[{media_type}: {file_path.name}]")
        elif media_type == "video":
            frame_paths = _extract_video_frames(file_path)
            audio_path = _extract_video_audio(file_path)
            if frame_paths:
                preview_parts.append(
                    f"[video: {file_path.name} -> {len(frame_paths)} sampled frames]"
                )
                for index, frame_path in enumerate(frame_paths, start=1):
                    content.append({"type": "image", "path": str(frame_path)})
                    preview_parts.append(f"[frame {index}: {frame_path.name}]")
                if audio_path is not None:
                    content.append({"type": "audio", "path": str(audio_path)})
                    preview_parts.append(f"[audio track: {audio_path.name}]")
                else:
                    preview_parts.append("[no audio track extracted]")
            else:
                preview_parts.append(
                    f"[video unsupported by current LiteRT Python runtime: {file_path.name}]"
                )
        else:
            preview_parts.append(f"[unsupported: {file_path.name}]")

    if not content:
        return None, ""

    return {"role": "user", "content": content}, "\n".join(preview_parts)


def _response_text(response: dict[str, Any]) -> str:
    text_chunks = []
    for item in response.get("content", []):
        if item.get("type") == "text":
            text_chunks.append(item.get("text", ""))
    return "".join(text_chunks)


def _has_media_content(user_message: dict[str, Any]) -> bool:
    for item in user_message.get("content", []):
        if item.get("type") == "video":
            return True
    return False


def chat(message: dict[str, Any] | None, history: list[dict[str, str]] | None, agent_mode: bool):
    _start_worker()

    if history is None:
        history = []

    mode_result = _request_worker({"cmd": "set_mode", "enabled": bool(agent_mode)})
    if not mode_result.get("ok"):
        updated = history + [
            {
                "role": "assistant",
                "content": f"Error from model/runtime: {mode_result.get('error', 'Unknown error')}",
            }
        ]
        yield updated, {"text": "", "files": []}
        return

    user_message, preview = _build_user_message(message)
    if user_message is None:
        if preview:
            updated = history + [
                {"role": "user", "content": preview},
                {
                    "role": "assistant",
                    "content": (
                        "This model/runtime currently does not support video input in the Python API. "
                        "Use image or audio, or extract frames from video first."
                    ),
                },
            ]
            yield updated, {"text": "", "files": []}
            return

        yield history, {"text": "", "files": []}
        return

    updated = history + [{"role": "user", "content": preview}]
    updated.append({"role": "assistant", "content": ""})
    yield updated, {"text": "", "files": []}

    if _has_media_content(user_message):
        worker_result = _request_worker({"cmd": "chat", "message": user_message, "stream": False})
        if worker_result.get("ok"):
            assistant_text = _response_text(worker_result.get("response", {}))
            updated[-1] = {"role": "assistant", "content": assistant_text}
        else:
            updated[-1] = {
                "role": "assistant",
                "content": f"Error from model/runtime: {worker_result.get('error', 'Unknown error')}",
            }
        yield updated, {"text": "", "files": []}
        return

    if agent_mode:
        worker_result = _request_worker({"cmd": "chat", "message": user_message, "stream": False})
        if worker_result.get("ok"):
            assistant_text = _response_text(worker_result.get("response", {}))
            updated[-1] = {"role": "assistant", "content": assistant_text}
        else:
            updated[-1] = {
                "role": "assistant",
                "content": f"Error from model/runtime: {worker_result.get('error', 'Unknown error')}",
            }
        yield updated, {"text": "", "files": []}
        return

    assistant_text = ""
    for worker_msg in _request_worker_stream({"cmd": "chat", "message": user_message, "stream": True}):
        if not worker_msg.get("ok"):
            updated[-1] = {
                "role": "assistant",
                "content": f"Error from model/runtime: {worker_msg.get('error', 'Unknown error')}",
            }
            yield updated, {"text": "", "files": []}
            return

        event = worker_msg.get("event")
        if event == "chunk":
            assistant_text += worker_msg.get("text", "")
            updated[-1] = {"role": "assistant", "content": assistant_text}
            yield updated, {"text": "", "files": []}
        elif event == "done":
            if not assistant_text:
                assistant_text = _response_text(worker_msg.get("response", {}))
                updated[-1] = {"role": "assistant", "content": assistant_text}
                yield updated, {"text": "", "files": []}
            return


def new_chat(agent_mode: bool):
    _request_worker({"cmd": "reset", "enabled": bool(agent_mode)})
    return [], {"text": "", "files": []}


def main() -> None:
    _start_worker()
    atexit.register(_cleanup_temp_dirs)
    atexit.register(_stop_worker)

    with gr.Blocks(title="LiteRT-LM Multimodal Tester") as demo:
        gr.Markdown("# LiteRT-LM Multimodal Tester")
        gr.Markdown(
            f"Model: `{_model_path}`  \\nBackend: CPU  \\nUpload image/audio/video and optional text in one message."
        )

        chatbot = gr.Chatbot(height=480)
        input_box = gr.MultimodalTextbox(
            file_count="multiple",
            file_types=["image", "audio", "video"],
            placeholder="Type text and/or upload image, audio, video...",
            show_label=False,
        )

        with gr.Row():
            send_btn = gr.Button("Send", variant="primary")
            clear_btn = gr.Button("New Chat")
            agent_mode_checkbox = gr.Checkbox(
                label="Agent Mode (tools)",
                value=False,
                info="Enable schema-based function calling (time + math). Switching mode resets context.",
            )

        send_btn.click(
            chat,
            inputs=[input_box, chatbot, agent_mode_checkbox],
            outputs=[chatbot, input_box],
        )
        input_box.submit(
            chat,
            inputs=[input_box, chatbot, agent_mode_checkbox],
            outputs=[chatbot, input_box],
        )
        clear_btn.click(
            new_chat,
            inputs=[agent_mode_checkbox],
            outputs=[chatbot, input_box],
        )

    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
