from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Tuple

from memory.errors import MemoryTrainingError
from memory.stores.explicit import ExplicitStore


class EmbeddingFineTuner:
    """Builds training pairs and runs optional sentence-transformers fine-tuning."""

    def __init__(self, explicit_store: ExplicitStore):
        self.explicit_store = explicit_store

    def build_training_pairs(self, speaker_id: str, min_records: int = 50) -> List[Tuple[str, str, int]]:
        records = self.explicit_store.filter(speaker_id=speaker_id, limit=max(min_records, 200))
        pairs: List[Tuple[str, str, int]] = []
        summaries = [r.summary for r in records if r.summary]

        for i in range(0, len(summaries) - 1, 2):
            pairs.append((summaries[i], summaries[i + 1], 1))
        for i in range(0, len(summaries) - 2, 3):
            pairs.append((summaries[i], summaries[i + 2], 0))
        return pairs

    def train(self, speaker_id: str, output_dir: str = "./ml/adapters/", epochs: int = 3, batch_size: int = 16) -> str:
        out = Path(output_dir) / speaker_id
        out.mkdir(parents=True, exist_ok=True)

        pairs = self.build_training_pairs(speaker_id=speaker_id)
        if not pairs:
            raise MemoryTrainingError("Not enough records to build embedding training pairs.")

        (out / "pairs.jsonl").write_text(
            "\n".join(json.dumps({"text_a": a, "text_b": b, "label": int(lbl)}) for a, b, lbl in pairs),
            encoding="utf-8",
        )

        trained = False
        if os.getenv("MEMORY_DISABLE_EMBEDDING_TRAINING", "0") == "1":
            (out / "TRAINING_SKIPPED.txt").write_text(
                "Training skipped by MEMORY_DISABLE_EMBEDDING_TRAINING=1",
                encoding="utf-8",
            )
            (out / "metadata.json").write_text(
                json.dumps(
                    {
                        "speaker_id": speaker_id,
                        "pair_count": len(pairs),
                        "epochs": epochs,
                        "batch_size": batch_size,
                        "trained": False,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return str(out)

        try:
            from sentence_transformers import InputExample, SentenceTransformer, losses
            from torch.utils.data import DataLoader

            model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            examples = [InputExample(texts=[a, b], label=float(lbl)) for a, b, lbl in pairs]
            dataloader = DataLoader(examples, shuffle=True, batch_size=max(1, min(batch_size, 32)))
            train_loss = losses.CosineSimilarityLoss(model)
            warmup_steps = max(1, len(dataloader) // 10)
            model.fit(
                train_objectives=[(dataloader, train_loss)],
                epochs=max(1, epochs),
                warmup_steps=warmup_steps,
                output_path=str(out),
            )
            trained = True
        except Exception as exc:
            (out / "TRAINING_SKIPPED.txt").write_text(
                f"Training skipped due to runtime constraints: {exc}",
                encoding="utf-8",
            )

        (out / "metadata.json").write_text(
            json.dumps(
                {
                    "speaker_id": speaker_id,
                    "pair_count": len(pairs),
                    "epochs": epochs,
                    "batch_size": batch_size,
                    "trained": trained,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(out)

    def load(self, speaker_id: str) -> object:
        adapter_path = Path("./ml/adapters") / speaker_id
        try:
            from sentence_transformers import SentenceTransformer

            if adapter_path.exists():
                return SentenceTransformer(str(adapter_path))
            return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        except Exception:
            return {
                "speaker_id": speaker_id,
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "adapter_path": str(adapter_path) if adapter_path.exists() else None,
            }
