from __future__ import annotations

import asyncio

from memory import MemorySystem, MemoryType
from memory.async_api import AsyncMemorySystem
from memory.ml.embedding_finetune import EmbeddingFineTuner
from memory.ml.lora_load import LoRALoader
from memory.ml.lora_train import LoRATrainer


def test_async_wrapper_end_to_end(tmp_path):
    mem = MemorySystem(
        speaker_id="dora",
        db_path=str(tmp_path / "async.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )
    async_mem = AsyncMemorySystem(mem)

    async def run_flow():
        await async_mem.save("Dora likes concise summaries", MemoryType.PREFERENCE)
        result = await async_mem.search("concise summaries")
        return result

    result = asyncio.run(run_flow())
    assert result.results


def test_ml_modules_generate_real_artifacts(tmp_path):
    mem = MemorySystem(
        speaker_id="erin",
        db_path=str(tmp_path / "ml.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    for i in range(120):
        mem.save(f"Erin memory sample {i}", MemoryType.FACT)

    emb = EmbeddingFineTuner(mem.explicit)
    emb_out = emb.train("erin", output_dir=str(tmp_path / "adapters"), epochs=1, batch_size=8)

    lora = LoRATrainer(mem.explicit)
    lora_out = lora.train("erin", output_dir=str(tmp_path / "lora"), epochs=1)

    loader = LoRALoader(lora_root=str(tmp_path / "lora"))
    loaded = loader.load("erin", base_model_path="dummy/base-model")

    assert (tmp_path / "adapters" / "erin" / "pairs.jsonl").exists()
    assert (tmp_path / "adapters" / "erin" / "metadata.json").exists()
    assert (tmp_path / "lora" / "erin" / "dataset.jsonl").exists()
    assert (tmp_path / "lora" / "erin" / "metadata.json").exists()
    assert loaded["speaker_id"] == "erin"
    assert loader.has_adapter("erin") is True
