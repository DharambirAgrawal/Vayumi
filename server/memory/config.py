from dataclasses import dataclass

from memory.constants import (
    DEFAULT_MEMORY_BLOB_DIR,
    DEFAULT_MEMORY_COLLECTION,
    DEFAULT_MEMORY_DB_PATH,
    DEFAULT_MEMORY_ML_DIR,
    DEFAULT_MEMORY_PROVIDER_MODE,
    DEFAULT_QDRANT_URL,
)


@dataclass
class MemoryConfig:
    # provider strategy
    provider_mode: str = DEFAULT_MEMORY_PROVIDER_MODE  # auto | cloud | local

    # stores
    qdrant_url: str = DEFAULT_QDRANT_URL
    qdrant_collection: str = DEFAULT_MEMORY_COLLECTION
    semantic_backend: str = "auto"  # auto | hosted | local | memory
    db_path: str = str(DEFAULT_MEMORY_DB_PATH)
    blob_dir: str = str(DEFAULT_MEMORY_BLOB_DIR)
    graphiti_uri: str = "bolt://localhost:7687"
    graphiti_user: str = "neo4j"
    graphiti_password: str = "password"
    graph_backend: str = "auto"  # auto | hosted | local | memory

    # models
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    whisper_model: str = "base"
    llm_model: str = "claude-sonnet-4-6"

    # limits
    short_term_tokens: int = 4000
    retrieval_top_k: int = 5
    chunk_size: int = 400
    chunk_overlap: int = 200

    # ml (optional)
    lora_base_model: str = "unsloth/llama-3-8b-bnb-4bit"
    lora_dir: str = str(DEFAULT_MEMORY_ML_DIR / "lora")
    adapter_dir: str = str(DEFAULT_MEMORY_ML_DIR / "adapters")

    # s3 (optional)
    use_s3: bool = False
    blob_backend: str = "auto"  # auto | s3 | disk
    s3_bucket: str = ""
    s3_endpoint: str = ""
