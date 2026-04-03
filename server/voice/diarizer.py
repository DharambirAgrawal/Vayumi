# # =============================================================================
# # server/voice/diarizer.py — Speaker Identification (SpeechBrain ECAPA-TDNN)
# # =============================================================================
# #
# # PURPOSE:
# #   Identifies WHO is speaking using voice embeddings. The primary question
# #   it answers: "Is this the owner or someone else?" This controls memory
# #   access and context hiding. Uses SpeechBrain's ECAPA-TDNN model for
# #   speaker verification embeddings.
# #
# # MODEL: SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb)
# #   - Accuracy: State-of-the-art for speaker verification
# #   - Latency: ~200-400ms per embedding on CPU (runs via asyncio.to_thread)
# #   - Model size: ~400MB download (cached after first run in server/models/speaker_encoder)
# #   - Output: 192-dimensional embedding vector per audio segment
# #   - Loaded ONCE at server startup, shared across all sessions
# #
# # ACCURACY EXPECTATIONS (from doc Section 10.2):
# #   Owner vs one guest:            High (~90%+)
# #   Owner vs known contact:        Good (~85%) if enrolled
# #   Differentiating 2 unknowns:    Moderate (~70-80%) within session
# #   Same person, diff conditions:  Lower (whisper, illness, phone speaker)
# #   3+ simultaneous speakers:      Low (cross-talk degrades quality)
# #
# # RECOGNITION_THRESHOLD: float = 0.75 (cosine similarity threshold)
# #   Above threshold → recognized speaker
# #   Below threshold → unknown/guest (safe fallback — no private data exposed)
# #
# # CLASS: SpeakerIdentifier
# #
# #   __init__(self):
# #     - Loads SpeechBrain encoder:
# #       self.encoder = EncoderClassifier.from_hparams(
# #         source="speechbrain/spkrec-ecapa-voxceleb",
# #         savedir=str(server.paths.DEFAULT_SPEAKER_ENCODER_CACHE)
# #       )
# #     - self.session_speakers: dict = {} — temporary speaker tracks per session
# #
# #   async identify(self, audio_segment: bytes, user_id: str) -> str:
# #     Identifies speaker from audio segment.
# #     Steps:
# #       1. Generate embedding via asyncio.to_thread(self._embed, audio_segment)
# #       2. Load known speakers for this user from contacts table
# #          (sqlite_store.get_contacts_with_voice(user_id))
# #       3. Compare embedding against each known speaker via cosine similarity
# #       4. If similarity > RECOGNITION_THRESHOLD → return known speaker's persona_id
# #       5. If no match → assign temporary session speaker ID (speaker_1, speaker_2...)
# #          Store embedding in self.session_speakers for within-session consistency
# #       6. Return speaker_id
# #
# #   def _embed(self, audio_segment: bytes) -> np.ndarray:
# #     BLOCKING — called via asyncio.to_thread.
# #     Converts raw audio bytes to torch tensor, runs through encoder.
# #     signal = torch.tensor(audio_segment).unsqueeze(0)
# #     return self.encoder.encode_batch(signal).squeeze().numpy()
# #
# #   async register_speaker(self, user_id: str, name: str, audio_sample: bytes):
# #     Enrolls a new speaker (used during "Meet Chris" flow).
# #     Steps:
# #       1. Generate embedding via asyncio.to_thread(self._embed, audio_sample)
# #       2. Save to contacts table via sqlite_store:
# #          save_contact_voice(user_id, name, embedding)
# #
# #   def get_session_embedding(self, speaker_id: str) -> np.ndarray | None:
# #     Returns the voice embedding for a temporary session speaker.
# #     Used by PersonaAgent during "Meet Chris" flow to retrieve
# #     the unknown speaker's embedding before saving it to contacts.
# #
# # FALLBACK BEHAVIOR:
# #   When uncertain (similarity between thresholds):
# #   → Default to guest (safe — no private data exposed)
# #   Owner can correct: "Vayumi, that's me" or "That's Chris"
# #
# # IMPORTS NEEDED:
# # =============================================================================

# import asyncio

# import numpy as np
# import torch
# from speechbrain.inference.speaker import EncoderClassifier

# from server.paths import DEFAULT_SPEAKER_ENCODER_CACHE

# RECOGNITION_THRESHOLD = 0.75


# class SpeakerIdentifier:
#     def __init__(self):
#         DEFAULT_SPEAKER_ENCODER_CACHE.mkdir(parents=True, exist_ok=True)
#         self.encoder = EncoderClassifier.from_hparams(
#             source="speechbrain/spkrec-ecapa-voxceleb",
#             savedir=str(DEFAULT_SPEAKER_ENCODER_CACHE),
#         )
#         self.session_speakers: dict[str, np.ndarray] = {}

#     async def identify(self, audio_segment: bytes, user_id: str) -> str:
#         pass

#     def _embed(self, audio_segment: bytes) -> np.ndarray:
#         pass

#     async def register_speaker(self, user_id: str, name: str, audio_sample: bytes):
#         pass

#     def get_session_embedding(self, speaker_id: str) -> np.ndarray | None:
#         pass

# =============================================================================
# server/voice/diarizer.py — Speaker Identification (SpeechBrain ECAPA-TDNN)
# =============================================================================

import asyncio
import logging
import struct
from typing import Optional

import numpy as np
import torch
from speechbrain.inference.speaker import EncoderClassifier

from server.paths import DEFAULT_SPEAKER_ENCODER_CACHE
from server.memory.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cosine-similarity threshold for positive speaker recognition.
# Above  → recognised speaker (return their persona_id)
# Below  → unknown / guest   (safe fallback — no private data exposed)
# ---------------------------------------------------------------------------
RECOGNITION_THRESHOLD: float = 0.75


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two 1-D vectors."""
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SpeakerIdentifier:
    """
    Identifies WHO is speaking using SpeechBrain ECAPA-TDNN embeddings.

    Primary question answered: "Is this the owner or someone else?"
    Controls memory access and context hiding downstream.
    """

    def __init__(self):
        DEFAULT_SPEAKER_ENCODER_CACHE.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Loading ECAPA-TDNN speaker encoder (cache=%s) …",
            DEFAULT_SPEAKER_ENCODER_CACHE,
        )
        self.encoder: EncoderClassifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(DEFAULT_SPEAKER_ENCODER_CACHE),
        )
        logger.info("Speaker encoder loaded.")

        # Dedicated SQLite access for diarizer contact voice lookups/enrollment.
        self.sqlite_store = SQLiteStore()

        # Temporary speaker tracks for the current server lifetime.
        # Maps a synthetic speaker_id ("speaker_1", …) → embedding vector.
        self.session_speakers: dict[str, np.ndarray] = {}

        # Monotonic counter for assigning new temporary speaker IDs
        self._next_speaker_idx: int = 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def identify(self, audio_segment: bytes, user_id: str) -> str:
        """
        Identify who is speaking in *audio_segment*.

        Returns:
            - A known contact's ``persona_id`` if the voice matches an enrolled
              speaker above ``RECOGNITION_THRESHOLD``.
            - A stable temporary session ID (``"speaker_1"``, ``"speaker_2"``, …)
              for unrecognised voices.  Within a session the same unknown voice
              will consistently receive the same temporary ID.
        """
        # 1. Generate embedding (blocking model call on thread)
        embedding = await asyncio.to_thread(self._embed, audio_segment)

        # 2. Load enrolled speakers for this user
        known_speakers = await asyncio.to_thread(
            self.sqlite_store.get_contacts_with_voice, user_id
        )
        # known_speakers: list of dicts with at least {"persona_id": str, "embedding": np.ndarray}

        # 3. Compare against every known speaker
        best_score: float = -1.0
        best_persona_id: Optional[str] = None

        for contact in known_speakers or []:
            contact_embedding = contact.get("embedding")
            if contact_embedding is None:
                continue
            # Ensure numpy array
            if not isinstance(contact_embedding, np.ndarray):
                contact_embedding = np.array(contact_embedding, dtype=np.float32)

            score = _cosine_similarity(embedding, contact_embedding)
            if score > best_score:
                best_score = score
                best_persona_id = contact.get("persona_id")

        # 4. Above threshold → recognised
        if best_score > RECOGNITION_THRESHOLD and best_persona_id is not None:
            logger.debug(
                "Speaker recognised as %s (score=%.3f)",
                best_persona_id,
                best_score,
            )
            return best_persona_id

        # 5. No match among known contacts → check session speakers for
        #    within-session consistency
        for spk_id, spk_emb in self.session_speakers.items():
            score = _cosine_similarity(embedding, spk_emb)
            if score > RECOGNITION_THRESHOLD:
                logger.debug(
                    "Matched existing session speaker %s (score=%.3f)",
                    spk_id,
                    score,
                )
                return spk_id

        # 6. Completely new voice — assign a fresh temporary ID
        new_id = f"speaker_{self._next_speaker_idx}"
        self._next_speaker_idx += 1
        self.session_speakers[new_id] = embedding
        logger.info(
            "New unknown speaker assigned %s (best known score=%.3f)",
            new_id,
            best_score,
        )
        return new_id

    def _embed(self, audio_segment: bytes) -> np.ndarray:
        """
        BLOCKING — always call via ``asyncio.to_thread``.

        Converts raw 16-bit PCM audio bytes into a 192-dim ECAPA-TDNN
        embedding vector.
        """
        # Interpret raw bytes as signed 16-bit PCM samples
        num_samples = len(audio_segment) // 2
        if num_samples == 0:
            # Return a zero vector so callers never crash on empty input
            return np.zeros(192, dtype=np.float32)

        pcm_ints = struct.unpack(f"<{num_samples}h", audio_segment[: num_samples * 2])
        # Normalise to float32 in [-1, 1]
        signal = torch.tensor(pcm_ints, dtype=torch.float32) / 32768.0
        # SpeechBrain expects shape (batch, time)
        signal = signal.unsqueeze(0)

        with torch.no_grad():
            embedding = self.encoder.encode_batch(signal)

        return embedding.squeeze().cpu().numpy()

    async def register_speaker(
        self, user_id: str, name: str, audio_sample: bytes
    ) -> None:
        """
        Enrol a new named speaker (e.g. the "Meet Chris" flow).

        Generates an embedding from *audio_sample* and persists it alongside
        the contact *name* in the SQLite contacts table.
        """
        embedding = await asyncio.to_thread(self._embed, audio_sample)
        await asyncio.to_thread(
            self.sqlite_store.save_contact_voice, user_id, name, embedding
        )
        logger.info("Registered speaker '%s' for user=%s", name, user_id)

    def get_session_embedding(self, speaker_id: str) -> Optional[np.ndarray]:
        """
        Return the voice embedding for a temporary session speaker.

        Used by PersonaAgent during the "Meet Chris" flow to retrieve an
        unknown speaker's embedding before saving it to contacts.
        """
        return self.session_speakers.get(speaker_id)