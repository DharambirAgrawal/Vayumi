from __future__ import annotations

import ast
import re
from typing import Any, Dict

FUNCTION_CALL_PATTERN = re.compile(
    r"<start_function_call>\s*call:(?P<name>[a-zA-Z_][\w]*)\{(?P<params>[\s\S]*?)\}\s*<end_function_call>",
    flags=re.IGNORECASE,
)


def extract_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        if "text" in response and isinstance(response["text"], str):
            return response["text"]
        content = response.get("content")
        if isinstance(content, list):
            return "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return ""
    if hasattr(response, "text"):
        value = getattr(response, "text")
        if isinstance(value, str):
            return value
    if hasattr(response, "candidates"):
        chunks = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None)
            if not parts:
                continue
            for part in parts:
                text = getattr(part, "text", "")
                if text:
                    chunks.append(text)
        return "".join(chunks)
    return str(response)


def _coerce_value(raw_value: str) -> Any:
    v = raw_value.strip()
    if not v:
        return ""

    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    if v.lower() == "null":
        return None

    try:
        return ast.literal_eval(v)
    except Exception:
        pass

    try:
        if "." in v:
            return float(v)
        return int(v)
    except Exception:
        return v.strip('"').strip("'")


def _parse_params(params_text: str) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    src = params_text.strip()
    if not src:
        return params

    # Try python-like dict first for robust parsing.
    try:
        parsed = ast.literal_eval("{" + src + "}")
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    current = []
    depth = 0
    in_quote = None
    pairs = []

    for ch in src:
        if ch in {'"', "'"}:
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
        elif in_quote is None:
            if ch in "[{(":
                depth += 1
            elif ch in "]})":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                pairs.append("".join(current))
                current = []
                continue
        current.append(ch)

    if current:
        pairs.append("".join(current))

    for pair in pairs:
        if ":" not in pair:
            continue
        key, value = pair.split(":", 1)
        params[key.strip().strip('"').strip("'")] = _coerce_value(value)

    return params


def parse_function_call(text: str) -> dict[str, Any]:
    match = FUNCTION_CALL_PATTERN.search(text)
    if not match:
        return {"success": False, "error": "No function call tag found"}

    function_name = match.group("name")
    params_blob = match.group("params")

    try:
        params = _parse_params(params_blob)
    except Exception as exc:
        return {"success": False, "error": f"Failed to parse params: {exc}"}

    return {"success": True, "function_name": function_name, "params": params}
