from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Dict, List

from memory.models import UserModel
from memory.stores.explicit import ExplicitStore


class PersonalizationLayer:
    """Builds and maintains a lightweight user model."""

    def __init__(self, explicit_store: ExplicitStore):
        self.explicit_store = explicit_store

    @staticmethod
    def _emotion_score(text: str) -> int:
        lowered = text.lower()
        positive = ["great", "happy", "excited", "good", "awesome", "thanks"]
        negative = ["stressed", "urgent", "angry", "upset", "bad", "overwhelmed", "tired", "frustrated"]
        score = 0
        for token in positive:
            if token in lowered:
                score += 1
        for token in negative:
            if token in lowered:
                score -= 1
        return score

    def get_model(self, speaker_id: str) -> UserModel:
        raw = self.explicit_store.get_user_model(speaker_id)
        if not raw:
            return UserModel(
                speaker_id=speaker_id,
                communication_style="direct",
                preferred_length="normal",
                topics_of_interest=[],
                frequent_people={},
                emotional_patterns="unknown",
                last_updated=datetime.utcnow(),
                emotional_history=[],
            )
        return UserModel(
            speaker_id=raw.get("speaker_id", speaker_id),
            communication_style=raw.get("communication_style", "direct"),
            preferred_length=raw.get("preferred_length", "normal"),
            topics_of_interest=list(raw.get("topics_of_interest", [])),
            frequent_people=dict(raw.get("frequent_people", {})),
            emotional_patterns=raw.get("emotional_patterns", "unknown"),
            last_updated=datetime.fromisoformat(raw.get("last_updated", datetime.utcnow().isoformat())),
            emotional_history=list(raw.get("emotional_history", [])),
        )

    def update_from_session(self, speaker_id: str, transcript: str, saved_facts: List[Dict]) -> UserModel:
        model = self.get_model(speaker_id)
        lines = [ln.strip() for ln in transcript.splitlines() if ln.strip()]

        avg_words = sum(len(ln.split()) for ln in lines) / max(len(lines), 1)
        preferred = "concise" if avg_words < 12 else "detailed" if avg_words > 30 else "normal"

        topics = set(model.topics_of_interest)
        frequent_people = dict(model.frequent_people)
        for fact in saved_facts:
            content = str(fact.get("content", "")).lower()
            for token in content.split():
                if len(token) >= 6 and token.isalpha():
                    topics.add(token)

            if " is " in content and any(role in content for role in ["manager", "lead", "designer", "engineer"]):
                parts = content.split(" is ", 1)
                name = parts[0].strip().title()
                role = parts[1].strip()[:64]
                if name:
                    frequent_people[name] = role

        sample = "\n".join(lines[-min(10, len(lines)) :]) if lines else ""
        session_emotion = self._emotion_score(sample)
        emotional_history = list(model.emotional_history)
        emotional_history.append(
            {
                "ts": datetime.utcnow().isoformat(),
                "score": session_emotion,
                "line_count": len(lines),
            }
        )
        emotional_history = emotional_history[-200:]

        recent = emotional_history[-10:]
        avg_recent = sum(item.get("score", 0) for item in recent) / max(1, len(recent))
        emotional = "stable"
        if avg_recent <= -1:
            emotional = "under sustained pressure"
        elif avg_recent >= 1:
            emotional = "generally positive"
        elif lines and all(len(ln.split()) < 8 for ln in lines[-min(5, len(lines)) :]):
            emotional = "often terse under pressure"

        updated = replace(
            model,
            preferred_length=preferred,
            topics_of_interest=sorted(topics)[:50],
            frequent_people=frequent_people,
            emotional_patterns=emotional,
            last_updated=datetime.utcnow(),
            emotional_history=emotional_history,
        )
        self.explicit_store.upsert_user_model(speaker_id, updated)
        return updated

    def to_system_prompt(self, model: UserModel) -> str:
        topics = ", ".join(model.topics_of_interest[:8]) if model.topics_of_interest else "none noted"
        if model.frequent_people:
            people = ", ".join(f"{name} ({role})" for name, role in model.frequent_people.items())
        else:
            people = "none noted"
        return (
            "[ABOUT THIS USER]\n"
            f"Communication style: {model.communication_style}.\n"
            f"Preferred response length: {model.preferred_length}.\n"
            f"Topics of interest: {topics}.\n"
            f"Frequent people: {people}.\n"
            f"Emotional pattern: {model.emotional_patterns}.\n"
            f"Emotion history points: {len(model.emotional_history)}."
        )

    def extract_preferences(self, text: str) -> List[Dict]:
        lowered = text.lower()
        triggers = ["i prefer", "i like", "i dislike", "please", "don't", "do not"]
        if any(t in lowered for t in triggers):
            return [{"content": text.strip(), "memory_type": "preference"}]
        return []
