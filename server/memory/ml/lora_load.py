from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


class LoRALoader:
    """Loads and unloads per-speaker LoRA adapters."""

    def __init__(self, lora_root: str = "./ml/lora"):
        self.lora_root = Path(lora_root)
        self._loaded: Dict[str, object] = {}

    def load(self, speaker_id: str, base_model_path: str) -> object:
        adapter_path = self.lora_root / speaker_id
        metadata_path = adapter_path / "metadata.json"
        metadata = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                metadata = {}

        model = {
            "base_model": base_model_path,
            "adapter": str(adapter_path) if adapter_path.exists() else None,
            "speaker_id": speaker_id,
            "metadata": metadata,
        }
        self._loaded[speaker_id] = model
        return model

    def unload(self, speaker_id: str) -> None:
        if speaker_id in self._loaded:
            del self._loaded[speaker_id]

    def has_adapter(self, speaker_id: str) -> bool:
        return (self.lora_root / speaker_id).exists()
