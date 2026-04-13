from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Optional


class GraphStore:
    """In-memory graph store with Graphiti-like methods."""

    def __init__(self, uri: str, user: str, password: str):
        self.uri = uri
        self.user = user
        self.password = password
        self._nodes: Dict[str, Dict] = {}
        self._edges: List[Dict] = []
        self._person_aliases: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._driver = None
        self._backend = "memory"

        self._init_neo4j_backend()

    def _init_neo4j_backend(self) -> None:
        if not self.uri or self.uri.startswith("memory://"):
            return
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            driver.verify_connectivity()
            self._driver = driver
            self._backend = "neo4j"
        except Exception:
            self._driver = None
            self._backend = "memory"

    @staticmethod
    def _sanitize_rel_type(rel_type: str) -> str:
        clean = re.sub(r"[^A-Z0-9_]", "_", rel_type.upper())
        return clean or "RELATED_TO"

    def add_entity(self, entity_id: str, entity_type: str, properties: Dict) -> str:
        if self._backend == "neo4j" and self._driver is not None:
            with self._driver.session() as session:
                session.run(
                    """
                    MERGE (n {entity_id: $entity_id})
                    SET n += $props, n.entity_type = $entity_type
                    """,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    props=properties or {},
                )

        existing = self._nodes.get(entity_id, {})
        merged = dict(existing)
        merged.update(properties or {})
        merged["entity_id"] = entity_id
        merged["entity_type"] = entity_type
        self._nodes[entity_id] = merged

        if entity_type == "person":
            speaker_id = str(merged.get("speaker_id", ""))
            name = str(merged.get("name", entity_id)).strip().lower()
            if speaker_id and name:
                self._person_aliases[speaker_id][name] = entity_id
        return entity_id

    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        properties: Optional[Dict] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
    ) -> str:
        if self._backend == "neo4j" and self._driver is not None:
            rel = self._sanitize_rel_type(rel_type)
            query = (
                f"MATCH (s {{entity_id: $source_id}}), (t {{entity_id: $target_id}}) "
                f"MERGE (s)-[r:{rel}]->(t) "
                "SET r += $props, r.valid_from = $valid_from, r.valid_to = $valid_to"
            )
            with self._driver.session() as session:
                session.run(
                    query,
                    source_id=source_id,
                    target_id=target_id,
                    props=properties or {},
                    valid_from=valid_from,
                    valid_to=valid_to,
                )

        edge = {
            "source_id": source_id,
            "target_id": target_id,
            "rel_type": rel_type,
            "properties": properties or {},
            "valid_from": valid_from,
            "valid_to": valid_to,
        }
        self._edges.append(edge)
        return f"{source_id}:{rel_type}:{target_id}:{len(self._edges)}"

    @staticmethod
    def _normalize_date(date_value: Optional[str]) -> Optional[str]:
        if not date_value:
            return None
        return str(date_value)[:10]

    @classmethod
    def _in_date_range(cls, value: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> bool:
        current = cls._normalize_date(value)
        if not current:
            return date_from is None and date_to is None

        start = cls._normalize_date(date_from)
        end = cls._normalize_date(date_to)
        if start and current < start:
            return False
        if end and current > end:
            return False
        return True

    def search(
        self,
        query: str,
        speaker_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict]:
        if self._backend == "neo4j" and self._driver is not None:
            tokens = [t.lower() for t in re.findall(r"[a-zA-Z0-9_]+", query)]
            with self._driver.session() as session:
                rows = session.run(
                    """
                    MATCH (n)
                    WHERE ($speaker_id IS NULL OR n.speaker_id IS NULL OR n.speaker_id = $speaker_id)
                      AND ($date_from IS NULL OR n.date IS NULL OR n.date >= $date_from)
                      AND ($date_to IS NULL OR n.date IS NULL OR n.date <= $date_to)
                    WITH n, toLower(toString(properties(n))) AS txt
                    WITH n, txt, [t IN $tokens WHERE txt CONTAINS t] AS matches
                    WITH n, size(matches) AS score
                    WHERE score > 0
                    RETURN n.entity_id AS node_id,
                           coalesce(n.entity_type, 'unknown') AS type,
                           coalesce(n.summary, '') AS summary,
                           toFloat(score) AS score,
                           n.memory_id AS memory_id,
                           n.speaker_id AS speaker_id
                    ORDER BY score DESC
                    LIMIT 20
                    """,
                    speaker_id=speaker_id,
                    date_from=self._normalize_date(date_from),
                    date_to=self._normalize_date(date_to),
                    tokens=tokens,
                )
                return [
                    {
                        "node_id": row["node_id"],
                        "type": row["type"],
                        "summary": row["summary"],
                        "score": float(row["score"]),
                        "memory_id": row["memory_id"],
                        "speaker_id": row["speaker_id"],
                    }
                    for row in rows
                ]

        tokens = [t.lower() for t in re.findall(r"[a-zA-Z0-9_]+", query)]
        results: List[Dict] = []
        for node_id, node in self._nodes.items():
            if speaker_id and str(node.get("speaker_id", "")) not in {"", speaker_id}:
                continue
            node_date = node.get("date") or node.get("created_at")
            if not self._in_date_range(node_date, date_from, date_to):
                continue
            text = " ".join(str(v) for v in node.values()).lower()
            score = sum(1.0 for tok in tokens if tok in text)
            if score > 0:
                results.append(
                    {
                        "node_id": node_id,
                        "type": node.get("entity_type", "unknown"),
                        "summary": node.get("summary", text[:180]),
                        "score": float(score),
                        "memory_id": node.get("memory_id"),
                        "speaker_id": node.get("speaker_id"),
                    }
                )
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]

    def get_person_meetings(
        self,
        speaker_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[str]:
        if self._backend == "neo4j" and self._driver is not None:
            with self._driver.session() as session:
                rows = session.run(
                    """
                    MATCH (p {speaker_id: $speaker_id})-[:PARTICIPATED_IN]->(m {entity_type: 'meeting'})
                    WHERE ($date_from IS NULL OR m.date IS NULL OR m.date >= $date_from)
                      AND ($date_to IS NULL OR m.date IS NULL OR m.date <= $date_to)
                    RETURN m.memory_id AS memory_id
                    """,
                    speaker_id=speaker_id,
                    date_from=self._normalize_date(date_from),
                    date_to=self._normalize_date(date_to),
                )
                return [row["memory_id"] for row in rows if row["memory_id"]]

        meeting_ids: List[str] = []
        for edge in self._edges:
            if edge["rel_type"] != "PARTICIPATED_IN":
                continue
            src = self._nodes.get(edge["source_id"], {})
            dst = self._nodes.get(edge["target_id"], {})
            if src.get("speaker_id") == speaker_id and dst.get("entity_type") == "meeting":
                if not self._in_date_range(dst.get("date") or dst.get("created_at"), date_from, date_to):
                    continue
                memory_id = dst.get("memory_id")
                if memory_id:
                    meeting_ids.append(memory_id)
        return meeting_ids

    def get_entity(self, entity_id: str) -> Dict:
        if self._backend == "neo4j" and self._driver is not None:
            with self._driver.session() as session:
                row = session.run(
                    "MATCH (n {entity_id: $entity_id}) RETURN properties(n) AS props",
                    entity_id=entity_id,
                ).single()
                if not row:
                    return {}
                return dict(row["props"])

        return dict(self._nodes.get(entity_id, {}))

    def delete_node(self, node_id: str) -> bool:
        if self._backend == "neo4j" and self._driver is not None:
            with self._driver.session() as session:
                res = session.run(
                    "MATCH (n {entity_id: $entity_id}) DETACH DELETE n RETURN count(n) AS c",
                    entity_id=node_id,
                ).single()
                deleted = bool(res and res["c"])
                if deleted:
                    return True

        existed = node_id in self._nodes
        if existed:
            del self._nodes[node_id]
        self._edges = [e for e in self._edges if e["source_id"] != node_id and e["target_id"] != node_id]
        return existed

    def resolve_alias(self, name: str, speaker_id: str) -> Optional[str]:
        if self._backend == "neo4j" and self._driver is not None:
            with self._driver.session() as session:
                row = session.run(
                    """
                    MATCH (p {entity_type: 'person', speaker_id: $speaker_id})
                    WHERE toLower(coalesce(p.name, '')) = toLower($name)
                    RETURN p.entity_id AS entity_id
                    LIMIT 1
                    """,
                    speaker_id=speaker_id,
                    name=name,
                ).single()
                if row:
                    return row["entity_id"]

        alias_map = self._person_aliases.get(speaker_id, {})
        if not alias_map:
            return None
        name_norm = name.strip().lower()
        if name_norm in alias_map:
            return alias_map[name_norm]

        best = None
        best_score = 0.0
        for alias, entity_id in alias_map.items():
            score = SequenceMatcher(a=name_norm, b=alias).ratio()
            if score > best_score:
                best = entity_id
                best_score = score
        return best if best_score >= 0.8 else None
