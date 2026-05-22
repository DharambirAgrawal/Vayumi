from __future__ import annotations

from pathlib import Path

from server.voice.tts.kokoro import _resolve_onnx_model_path, _resolve_voices_path


def test_resolve_onnx_returns_none_for_empty_dir(tmp_path: Path) -> None:
    kokoro_dir = tmp_path / "kokoro"
    kokoro_dir.mkdir()
    assert _resolve_onnx_model_path(kokoro_dir) is None


def test_resolve_onnx_returns_file_when_present(tmp_path: Path) -> None:
    kokoro_dir = tmp_path / "kokoro"
    kokoro_dir.mkdir()
    onnx = kokoro_dir / "model.onnx"
    onnx.write_bytes(b"\x00")
    assert _resolve_onnx_model_path(kokoro_dir) == onnx


def test_resolve_onnx_prefers_kokoro_v1_name(tmp_path: Path) -> None:
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    (tts_dir / "other.onnx").write_bytes(b"\x00")
    preferred = tts_dir / "kokoro-v1.0.onnx"
    preferred.write_bytes(b"\x00")
    assert _resolve_onnx_model_path(tts_dir) == preferred


def test_resolve_voices_prefers_voices_v1_bin(tmp_path: Path) -> None:
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    preferred = tts_dir / "voices-v1.0.bin"
    preferred.write_bytes(b"\x00")
    assert _resolve_voices_path(tts_dir) == preferred
