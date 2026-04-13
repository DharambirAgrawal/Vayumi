from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

from memory.errors import MemoryTrainingError
from memory.stores.explicit import ExplicitStore


class LoRATrainer:
    """LoRA training facade for user-style adapters."""

    def __init__(self, explicit_store: ExplicitStore):
        self.explicit_store = explicit_store

    def build_dataset(self, speaker_id: str, min_sessions: int = 50) -> List[Dict]:
        rows = self.explicit_store.filter(speaker_id=speaker_id, limit=max(min_sessions, 200))
        dataset: List[Dict] = []
        for row in rows:
            dataset.append(
                {
                    "instruction": f"Recall memory for {speaker_id}",
                    "response": row.summary,
                }
            )
        return dataset

    def train(
        self,
        speaker_id: str,
        base_model: str = "unsloth/llama-3-8b-bnb-4bit",
        output_dir: str = "./ml/lora/",
        epochs: int = 2,
        rank: int = 16,
        lora_alpha: int = 32,
    ) -> str:
        out = Path(output_dir) / speaker_id
        out.mkdir(parents=True, exist_ok=True)

        dataset = self.build_dataset(speaker_id=speaker_id)
        if not dataset:
            raise MemoryTrainingError("Not enough memory records to build LoRA dataset.")

        (out / "dataset.jsonl").write_text(
            "\n".join(json.dumps(row) for row in dataset),
            encoding="utf-8",
        )

        # Training can be expensive; gate real training to explicit opt-in.
        enable_real_train = os.getenv("MEMORY_ENABLE_LORA_TRAIN", "0") == "1"
        trained = False
        reason = "Real LoRA training disabled by default. Set MEMORY_ENABLE_LORA_TRAIN=1 to enable."

        if enable_real_train:
            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer

                _ = (rank, lora_alpha, epochs)  # reserved for full PEFT pipeline expansion
                tokenizer = AutoTokenizer.from_pretrained(base_model)
                model = AutoModelForCausalLM.from_pretrained(base_model)
                tokenizer.save_pretrained(out)
                model.save_pretrained(out)
                trained = True
                reason = "Base model artifacts saved. Full PEFT fine-tuning can be added on top of this path."
            except Exception as exc:
                reason = f"Real LoRA training attempt failed: {exc}"

        (out / "metadata.json").write_text(
            json.dumps(
                {
                    "speaker_id": speaker_id,
                    "base_model": base_model,
                    "epochs": epochs,
                    "rank": rank,
                    "lora_alpha": lora_alpha,
                    "dataset_size": len(dataset),
                    "trained": trained,
                    "note": reason,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(out)
