from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Optional


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_page_text_from_scrapling(page) -> str:
    selectors = [
        "article *::text",
        "main *::text",
        "body *::text",
        "body::text",
        "::text",
    ]
    for selector in selectors:
        try:
            values = page.css(selector).getall()
            text = " ".join(str(value).strip() for value in values if str(value).strip())
            if text:
                return text
        except Exception:
            continue

    for attr in ("text", "content", "html"):
        value = getattr(page, attr, None)
        if isinstance(value, str) and value.strip():
            return value

    return str(page)


def _instructional_summary(text: str, instruction: str, max_chars: int = 4000) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""

    lowered = instruction.lower().strip()
    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", cleaned) if segment.strip()]

    if not lowered:
        return cleaned[:max_chars]

    if any(token in lowered for token in ["short", "brief", "concise", "tldr", "tl;dr"]):
        return " ".join(sentences[:3])[:max_chars]

    if any(token in lowered for token in ["bullet", "bullets", "list", "points"]):
        return "\n".join(f"- {sentence}" for sentence in sentences[:5])[:max_chars]

    if any(token in lowered for token in ["quote", "quotes", "extract"]):
        quoted = re.findall(r'"([^"]{6,})"', cleaned)
        if quoted:
            return "\n".join(f'- "{item}"' for item in quoted[:5])[:max_chars]

    if any(token in lowered for token in ["table", "json"]):
        key_points = sentences[:5]
        return json.dumps({"instruction": instruction, "key_points": key_points}, indent=2)[:max_chars]

    if any(token in lowered for token in ["steps", "how to", "instructions", "guide"]):
        return "\n".join(f"{index + 1}. {sentence}" for index, sentence in enumerate(sentences[:5]))[:max_chars]

    return " ".join(sentences[:5])[:max_chars]


def _read_bytes_from_url(url: str, timeout: float = 12.0, max_bytes: int = 8_000_000) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Vayumi/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("remote payload too large")
        return data


def _fetch_with_scrapling(url: str, prefer_dynamic: bool = True) -> tuple[str, str]:
    try:
        scrapling_fetchers = importlib.import_module("scrapling.fetchers")
        fetcher = getattr(scrapling_fetchers, "Fetcher")
        page = fetcher.get(url)
        return _extract_page_text_from_scrapling(page), "scrapling-fetcher"
    except Exception:
        if not prefer_dynamic:
            raise

    try:
        scrapling_fetchers = importlib.import_module("scrapling.fetchers")
        async_dynamic_session = getattr(scrapling_fetchers, "AsyncDynamicSession")

        async def _run() -> str:
            async with async_dynamic_session(headless=True) as session:
                page = await session.fetch(url)
                return _extract_page_text_from_scrapling(page)

        return asyncio.run(_run()), "scrapling-dynamic"
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def _coerce_binary_payload(payload: bytes | str) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if not isinstance(payload, str):
        raise TypeError(f"Unsupported payload type: {type(payload)!r}")

    text = payload.strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]

    try:
        return base64.b64decode(text, validate=True)
    except Exception:
        return text.encode("utf-8", errors="ignore")


def read_url(
    url: str,
    instruction: str = "",
    prefer_dynamic: bool = True,
    max_chars: int = 8000,
) -> str:
    try:
        cleaned_text = ""
        fetch_method = ""

        try:
            cleaned_text, fetch_method = _fetch_with_scrapling(url, prefer_dynamic=prefer_dynamic)
        except Exception:
            raw = _read_bytes_from_url(url)
            cleaned_text = raw.decode("utf-8", errors="ignore")
            fetch_method = "urllib"
    except Exception as exc:
        reason = str(exc)
        lowered = reason.lower()
        status = "blocked" if any(token in lowered for token in ["403", "401", "forbidden", "denied", "protected"]) else "error"
        return json.dumps(
            {
                "url": url,
                "fetchable": False,
                "status": status,
                "reason": reason,
                "instruction": instruction,
            }
        )

    if not cleaned_text.strip():
        return json.dumps(
            {
                "url": url,
                "fetchable": False,
                "status": "empty",
                "reason": "URL content was empty",
                "instruction": instruction,
                "fetch_method": fetch_method,
            }
        )

    if "<html" in cleaned_text.lower() or "<body" in cleaned_text.lower() or "</" in cleaned_text:
        cleaned_text = _strip_html(cleaned_text)

    cleaned_text = " ".join(cleaned_text.split())
    if not cleaned_text:
        return json.dumps(
            {
                "url": url,
                "fetchable": False,
                "status": "empty",
                "reason": "URL content was empty",
                "instruction": instruction,
                "fetch_method": fetch_method,
            }
        )

    summary = _instructional_summary(cleaned_text, instruction, max_chars=max_chars)
    return json.dumps(
        {
            "url": url,
            "fetchable": True,
            "status": "ok",
            "fetch_method": fetch_method,
            "instruction": instruction,
            "summary": summary,
            "clean_text": cleaned_text[:max_chars],
            "chars": len(cleaned_text),
        }
    )


def analyze_image(image_data: bytes | str) -> str:
    image_data = _coerce_binary_payload(image_data)
    if not image_data:
        return "ERROR: Empty image payload"

    details = [f"Image bytes: {len(image_data)}"]
    try:
        from PIL import Image, ImageStat

        with Image.open(BytesIO(image_data)) as img:
            width, height = img.size
            fmt = img.format or "unknown"
            mode = img.mode
            details.append(f"format={fmt} size={width}x{height} mode={mode}")

            rgb = img.convert("RGB")
            stat = ImageStat.Stat(rgb)
            avg = [int(v) for v in stat.mean[:3]]
            brightness = int(sum(avg) / 3)
            tone = "dark" if brightness < 85 else "bright" if brightness > 170 else "balanced"
            details.append(f"average_rgb=({avg[0]}, {avg[1]}, {avg[2]}) lighting={tone}")

            thumb = rgb.resize((64, 64))
            colors = thumb.getcolors(maxcolors=64 * 64) or []
            if colors:
                colors.sort(key=lambda item: item[0], reverse=True)
                palette = ", ".join(f"RGB{color[1]}" for color in colors[:3])
                details.append(f"dominant_palette={palette}")
    except Exception as exc:
        details.append(f"pixel_analysis_unavailable={exc}")

    return json.dumps({"summary": " | ".join(details)})


def _extract_wav_bytes_from_audio(audio_data: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_path = tmp_path / "input.audio"
        wav_path = tmp_path / "output.wav"
        input_path.write_bytes(audio_data)

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            try:
                import imageio_ffmpeg

                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                ffmpeg_path = None

        if ffmpeg_path is None:
            raise RuntimeError("ffmpeg is unavailable")

        command = [
            ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(wav_path),
        ]
        completed = subprocess.run(command, capture_output=True, check=False, timeout=30)
        if completed.returncode != 0 or not wav_path.exists():
            raise RuntimeError(completed.stderr.decode("utf-8", errors="ignore") or "audio transcode failed")
        return wav_path.read_bytes()


def transcribe_audio(audio_data: bytes | str) -> str:
    audio_data = _coerce_binary_payload(audio_data)
    if not audio_data:
        return "ERROR: Empty audio payload"

    if os.getenv("MEMORY_DISABLE_WHISPER", "0") == "1":
        approx_secs = max(1, len(audio_data) // 32000)
        return (
            "Audio received; Whisper transcription disabled by configuration. "
            f"Captured approximately {approx_secs} seconds of audio data."
        )

    try:
        whisper = importlib.import_module("whisper")

        wav_bytes = _extract_wav_bytes_from_audio(audio_data)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as fp:
            fp.write(wav_bytes)
            fp.flush()
            model_name = os.getenv("MEMORY_WHISPER_MODEL", "base")
            model = whisper.load_model(model_name)
            result = model.transcribe(fp.name, fp16=False)
            text = str(result.get("text", "")).strip()
            if text:
                return json.dumps({"transcript": text})
    except Exception:
        pass

    approx_secs = max(1, len(audio_data) // 32000)
    return (
        "Audio received but transcription is unavailable in the current runtime. "
        f"Captured approximately {approx_secs} seconds of audio data."
    )


def analyze_video(video_data: bytes | str) -> str:
    video_data = _coerce_binary_payload(video_data)
    if not video_data:
        return "ERROR: Empty video payload"

    details = [f"Video bytes: {len(video_data)}"]
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        video_path = tmp_path / "input.mp4"
        video_path.write_bytes(video_data)

        try:
            import cv2

            capture = cv2.VideoCapture(str(video_path))
            if capture.isOpened():
                ok, frame = capture.read()
                if ok and frame is not None:
                    ok2, encoded = cv2.imencode(".jpg", frame)
                    if ok2:
                        image_summary = analyze_image(encoded.tobytes())
                        details.append(f"first_frame={image_summary}")
            capture.release()
        except Exception as exc:
            details.append(f"frame_analysis_unavailable={exc}")

        try:
            ffmpeg_path = shutil.which("ffmpeg")
            if ffmpeg_path is None:
                try:
                    import imageio_ffmpeg

                    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    ffmpeg_path = None

            if ffmpeg_path is not None:
                audio_path = tmp_path / "audio.wav"
                command = [
                    ffmpeg_path,
                    "-y",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(audio_path),
                ]
                completed = subprocess.run(command, capture_output=True, check=False, timeout=30)
                if completed.returncode == 0 and audio_path.exists():
                    transcript = transcribe_audio(audio_path.read_bytes())
                    details.append(f"audio={transcript}")
        except Exception as exc:
            details.append(f"audio_extraction_unavailable={exc}")

    return json.dumps({"summary": " | ".join(details)})