from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from memory.models import IngestResponse, MemoryRecord, MemoryType
from memory.stores.explicit import ExplicitStore
from memory.stores.graph import GraphStore
from memory.stores.semantic import SemanticStore


class LinkIngester:
    """URL ingestion with basic GitHub-aware content handling."""

    def __init__(self, explicit_store: ExplicitStore, semantic_store: SemanticStore, graph_store: GraphStore):
        self.explicit_store = explicit_store
        self.semantic_store = semantic_store
        self.graph_store = graph_store

    def ingest(
        self,
        url: str,
        speaker_id: str,
        date: Optional[str] = None,
        title: Optional[str] = None,
    ) -> IngestResponse:
        parsed = urlparse(url)
        content = self.fetch_github(url) if "github.com" in parsed.netloc else self.fetch(url)

        memory_id = str(uuid.uuid4())
        chunk_id = str(uuid.uuid4())
        self.semantic_store.upsert(
            chunk_id=chunk_id,
            text=content,
            metadata={
                "memory_id": memory_id,
                "speaker_id": speaker_id,
                "type": MemoryType.LINK.value,
                "date": date,
                "source_url": url,
            },
        )

        node_id = f"link:{memory_id}"
        self.graph_store.add_entity(
            entity_id=node_id,
            entity_type="link",
            properties={
                "memory_id": memory_id,
                "speaker_id": speaker_id,
                "url": url,
                "domain": parsed.netloc,
                "title": title or parsed.path.strip("/") or parsed.netloc,
                "summary": content[:220],
            },
        )

        record = MemoryRecord(
            id=memory_id,
            type=MemoryType.LINK,
            summary=title or content[:220],
            speaker_id=speaker_id,
            created_at=datetime.utcnow(),
            source_url=url,
            chunk_ids=[chunk_id],
            graph_node_id=node_id,
            metadata={"date": date, "title": title, "domain": parsed.netloc},
        )
        self.explicit_store.insert(record)
        return IngestResponse(memory_id=memory_id, store="link", chunk_count=1, success=True)

    def fetch(self, url: str) -> str:
        # Try Jina reader first for cleaner article extraction, then fall back to direct HTML parsing.
        jina_url = f"https://r.jina.ai/{url}"
        headers = {"User-Agent": "MemoryOS/1.0 (+https://example.local)"}

        try:
            resp = requests.get(jina_url, headers=headers, timeout=12)
            if resp.ok and resp.text.strip():
                return resp.text.strip()
        except Exception:
            pass

        try:
            resp = requests.get(url, headers=headers, timeout=12)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
            body_text = " ".join(soup.get_text(" ", strip=True).split())
            if title:
                return f"Title: {title}\n\n{body_text}"[:12000]
            return body_text[:12000]
        except Exception as exc:
            return f"Failed to fetch URL content for {url}: {exc}"

    def fetch_github(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            return self.fetch(url)

        owner, repo = parts[0], parts[1]
        repo_api = f"https://api.github.com/repos/{owner}/{repo}"
        readme_api = f"https://api.github.com/repos/{owner}/{repo}/readme"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "MemoryOS/1.0 (+https://example.local)",
        }

        sections = []

        try:
            repo_resp = requests.get(repo_api, headers=headers, timeout=12)
            if repo_resp.ok:
                data = repo_resp.json()
                meta = {
                    "full_name": data.get("full_name"),
                    "description": data.get("description"),
                    "stargazers_count": data.get("stargazers_count"),
                    "language": data.get("language"),
                    "default_branch": data.get("default_branch"),
                    "html_url": data.get("html_url"),
                }
                sections.append("Repository Metadata:\n" + json.dumps(meta, indent=2))
        except Exception as exc:
            sections.append(f"Repository metadata fetch failed: {exc}")

        try:
            readme_resp = requests.get(readme_api, headers=headers, timeout=12)
            if readme_resp.ok:
                payload = readme_resp.json()
                content_b64 = payload.get("content", "")
                if content_b64:
                    decoded = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
                    sections.append("README:\n" + decoded[:20000])
        except Exception as exc:
            sections.append(f"README fetch failed: {exc}")

        if not sections:
            return self.fetch(url)

        return "\n\n".join(sections)

    def refresh(self, memory_id: str) -> IngestResponse:
        record = self.explicit_store.get(memory_id)
        if not record or not record.source_url:
            return IngestResponse(memory_id=memory_id, store="link", chunk_count=0, success=False)

        self.semantic_store.delete_by_memory_id(memory_id)
        content = self.fetch_github(record.source_url) if "github.com" in record.source_url else self.fetch(record.source_url)

        chunk_id = str(uuid.uuid4())
        self.semantic_store.upsert(
            chunk_id=chunk_id,
            text=content,
            metadata={
                "memory_id": memory_id,
                "speaker_id": record.speaker_id,
                "type": MemoryType.LINK.value,
                "source_url": record.source_url,
            },
        )
        self.explicit_store.update(memory_id, {"summary": content[:220], "chunk_ids": [chunk_id]})
        return IngestResponse(memory_id=memory_id, store="link", chunk_count=1, success=True)
