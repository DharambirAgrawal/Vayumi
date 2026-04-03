# =============================================================================
# server/memory/sqlite_store.py — SQLite Wrapper (User-Scoped Queries)
# =============================================================================
#
# PURPOSE:
#   Wraps all SQLite database operations. ALL queries include user_id
#   filtering — there is no way to accidentally access another user's data.
#   Handles structured data: users, reminders, meetings, contacts, memory
#   episodes, and injected flags.
#
# DATABASE SETUP:
#   Default path: server/data/vayumi.db (see server.paths.DEFAULT_SQLITE_DB)
#   Pragmas (set at connection time):
#     PRAGMA journal_mode=WAL     — better concurrent read/write performance
#     PRAGMA busy_timeout=5000    — wait up to 5s on lock contention
#
# TABLES (created via init_db):
#   users           — User accounts (user_id PK, display_name, email, password_hash,
#                     voice_embedding, embedding_model_version, profile JSON, enabled_mcps JSON)
#   reminders       — Timed reminders (id PK, user_id FK, text, due_datetime, completed)
#   meetings        — Meeting records (id PK, user_id FK, title, started_at, ended_at,
#                     attendees JSON, notes, summary, action_items JSON)
#   contacts        — Known speakers (id PK, user_id FK, name, role, voice_embedding,
#                     embedding_model_version, relationship_context, last_seen)
#   memory_episodes — Episodic memory metadata (id PK, user_id FK, speaker_id, content,
#                     embedding_id, timestamp, sensitivity, tags JSON)
#   injected_flags  — Flag log (id PK, user_id FK, source, event_type, data JSON,
#                     injected_at, acknowledged)
#
# ISOLATION RULES (from doc Section 3.3 — enforced in every query):
#   memories:      WHERE user_id = :current_user_id
#   reminders:     WHERE user_id = :current_user_id
#   meetings:      WHERE user_id = :current_user_id
#   contacts:      WHERE user_id = :current_user_id
#   flags:         WHERE user_id = :current_user_id
#   vector_search: filter={'user_id': current_user_id}
#
# IMPORTS NEEDED:
# =============================================================================

import json
import logging
import sqlite3
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

from server.auth.models import UserAccount
from server.paths import DEFAULT_SQLITE_DB

logger = logging.getLogger(__name__)


class SQLiteStore:
    """
    User-scoped SQLite persistence layer.

    Every public method that touches user data requires a ``user_id``
    parameter and embeds it directly into the ``WHERE`` clause, making
    cross-user data leakage structurally impossible.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, db_path: str | Path | None = None):
        path = Path(db_path) if db_path is not None else DEFAULT_SQLITE_DB
        path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.row_factory = sqlite3.Row

        self.init_db()
        logger.info("SQLiteStore ready — %s", path)

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("SQLiteStore connection closed")

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def init_db(self):
        """Create all tables if they do not already exist."""
        cur = self.conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id                TEXT PRIMARY KEY,
                display_name           TEXT NOT NULL,
                email                  TEXT UNIQUE NOT NULL,
                password_hash          TEXT NOT NULL,
                voice_embedding        BLOB,
                embedding_model_version TEXT,
                profile                TEXT DEFAULT '{}',
                enabled_mcps           TEXT DEFAULT '[]'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id            TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL,
                text          TEXT NOT NULL,
                due_datetime  TEXT NOT NULL,
                completed     INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                title        TEXT NOT NULL,
                started_at   TEXT,
                ended_at     TEXT,
                attendees    TEXT DEFAULT '[]',
                notes        TEXT DEFAULT '',
                summary      TEXT DEFAULT '',
                action_items TEXT DEFAULT '[]',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id                      TEXT PRIMARY KEY,
                user_id                 TEXT NOT NULL,
                name                    TEXT NOT NULL,
                role                    TEXT DEFAULT '',
                voice_embedding         BLOB,
                embedding_model_version TEXT,
                relationship_context    TEXT DEFAULT '',
                last_seen               TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS memory_episodes (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                speaker_id   TEXT,
                content      TEXT NOT NULL,
                embedding_id TEXT,
                timestamp    TEXT NOT NULL,
                sensitivity  TEXT DEFAULT 'normal',
                tags         TEXT DEFAULT '[]',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS injected_flags (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                source       TEXT NOT NULL,
                event_type   TEXT NOT NULL,
                data         TEXT DEFAULT '{}',
                injected_at  TEXT NOT NULL,
                acknowledged INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        self.conn.commit()
        logger.debug("Database tables verified / created")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        """Convert a sqlite3.Row to a plain dict, or None."""
        if row is None:
            return None
        return dict(row)

    @staticmethod
    def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
        return [dict(r) for r in rows]

    def _row_to_user(self, row: sqlite3.Row | None) -> UserAccount | None:
        """Deserialise a *users* row into a UserAccount model instance."""
        if row is None:
            return None
        d = dict(row)
        return UserAccount(
            user_id=d["user_id"],
            display_name=d["display_name"],
            email=d["email"],
            password_hash=d["password_hash"],
            voice_embedding=d.get("voice_embedding"),
            embedding_model_version=d.get("embedding_model_version"),
            profile=json.loads(d.get("profile") or "{}"),
            enabled_mcps=json.loads(d.get("enabled_mcps") or "[]"),
        )

    # ------------------------------------------------------------------
    # User operations
    # ------------------------------------------------------------------

    def create_user(self, user: UserAccount) -> None:
        """Insert a new user account."""
        self.conn.execute(
            """
            INSERT INTO users
                (user_id, display_name, email, password_hash,
                 voice_embedding, embedding_model_version,
                 profile, enabled_mcps)
            VALUES
                (:user_id, :display_name, :email, :password_hash,
                 :voice_embedding, :embedding_model_version,
                 :profile, :enabled_mcps)
            """,
            {
                "user_id": user.user_id,
                "display_name": user.display_name,
                "email": user.email,
                "password_hash": user.password_hash,
                "voice_embedding": user.voice_embedding,
                "embedding_model_version": user.embedding_model_version,
                "profile": json.dumps(user.profile if user.profile else {}),
                "enabled_mcps": json.dumps(
                    user.enabled_mcps if user.enabled_mcps else []
                ),
            },
        )
        self.conn.commit()

    def get_user(self, user_id: str) -> UserAccount | None:
        """Fetch a user by primary key."""
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id = :user_id",
            {"user_id": user_id},
        ).fetchone()
        return self._row_to_user(row)

    def get_user_by_email(self, email: str) -> UserAccount | None:
        """Fetch a user by email address (for login)."""
        row = self.conn.execute(
            "SELECT * FROM users WHERE email = :email",
            {"email": email},
        ).fetchone()
        return self._row_to_user(row)

    def update_user_profile(self, user_id: str, profile: dict) -> None:
        """Overwrite the JSON profile blob for a given user."""
        self.conn.execute(
            """
            UPDATE users
               SET profile = :profile_json
             WHERE user_id = :user_id
            """,
            {
                "profile_json": json.dumps(profile),
                "user_id": user_id,
            },
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Reminder operations (all scoped by user_id)
    # ------------------------------------------------------------------

    def create_reminder(
        self,
        user_id: str,
        reminder_id: str,
        text: str,
        due_datetime: datetime,
    ) -> None:
        """Create a timed reminder for a user."""
        self.conn.execute(
            """
            INSERT INTO reminders (id, user_id, text, due_datetime, completed)
            VALUES (:id, :user_id, :text, :due_datetime, 0)
            """,
            {
                "id": reminder_id,
                "user_id": user_id,
                "text": text,
                "due_datetime": due_datetime.isoformat(),
            },
        )
        self.conn.commit()

    def get_reminders(
        self, user_id: str, filter_type: str = "today"
    ) -> list[dict]:
        """
        Retrieve reminders for a user.

        filter_type
            ``"today"``   — due today (regardless of completed status)
            ``"pending"`` — not yet completed (any date)
            ``"all"``     — every reminder ever created
        """
        base = "SELECT * FROM reminders WHERE user_id = :user_id"
        params: dict = {"user_id": user_id}

        if filter_type == "today":
            today_start = datetime.combine(date.today(), datetime.min.time())
            today_end = today_start + timedelta(days=1)
            base += " AND due_datetime >= :start AND due_datetime < :end"
            params["start"] = today_start.isoformat()
            params["end"] = today_end.isoformat()
        elif filter_type == "pending":
            base += " AND completed = 0"

        base += " ORDER BY due_datetime ASC"

        rows = self.conn.execute(base, params).fetchall()
        return self._rows_to_dicts(rows)

    def complete_reminder(self, user_id: str, reminder_id: str) -> None:
        """Mark a reminder as completed (user-scoped)."""
        self.conn.execute(
            """
            UPDATE reminders
               SET completed = 1
             WHERE id = :id AND user_id = :user_id
            """,
            {"id": reminder_id, "user_id": user_id},
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Meeting operations (all scoped by user_id)
    # ------------------------------------------------------------------

    def create_meeting(self, user_id: str, meeting_data: dict) -> None:
        """Insert a new meeting record."""
        meeting_id = meeting_data.get("id", str(uuid.uuid4()))
        self.conn.execute(
            """
            INSERT INTO meetings
                (id, user_id, title, started_at, ended_at,
                 attendees, notes, summary, action_items)
            VALUES
                (:id, :user_id, :title, :started_at, :ended_at,
                 :attendees, :notes, :summary, :action_items)
            """,
            {
                "id": meeting_id,
                "user_id": user_id,
                "title": meeting_data.get("title", ""),
                "started_at": meeting_data.get("started_at", ""),
                "ended_at": meeting_data.get("ended_at", ""),
                "attendees": json.dumps(meeting_data.get("attendees", [])),
                "notes": meeting_data.get("notes", ""),
                "summary": meeting_data.get("summary", ""),
                "action_items": json.dumps(
                    meeting_data.get("action_items", [])
                ),
            },
        )
        self.conn.commit()

    def update_meeting(
        self, user_id: str, meeting_id: str, updates: dict
    ) -> None:
        """
        Apply partial updates to an existing meeting (user-scoped).

        Only keys present in *updates* are written; other columns are
        left untouched.  JSON-typed columns (``attendees``,
        ``action_items``) are serialised automatically.
        """
        # Map of column → value, serialising JSON fields as needed.
        json_columns = {"attendees", "action_items"}
        set_clauses: list[str] = []
        params: dict = {"user_id": user_id, "meeting_id": meeting_id}

        for key, value in updates.items():
            param_name = f"u_{key}"
            if key in json_columns:
                params[param_name] = json.dumps(value)
            else:
                params[param_name] = value
            set_clauses.append(f"{key} = :{param_name}")

        if not set_clauses:
            return

        sql = (
            f"UPDATE meetings SET {', '.join(set_clauses)} "
            f"WHERE id = :meeting_id AND user_id = :user_id"
        )
        self.conn.execute(sql, params)
        self.conn.commit()

    def get_meetings(self, user_id: str, limit: int = 10) -> list[dict]:
        """Return the most recent meetings for a user."""
        rows = self.conn.execute(
            """
            SELECT * FROM meetings
             WHERE user_id = :user_id
             ORDER BY started_at DESC
             LIMIT :limit
            """,
            {"user_id": user_id, "limit": limit},
        ).fetchall()

        results: list[dict] = []
        for row in rows:
            d = dict(row)
            d["attendees"] = json.loads(d.get("attendees") or "[]")
            d["action_items"] = json.loads(d.get("action_items") or "[]")
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Contact operations (all scoped by user_id)
    # ------------------------------------------------------------------

    def create_contact(self, user_id: str, contact_data: dict) -> None:
        """Insert a new contact for a user."""
        contact_id = contact_data.get("id", str(uuid.uuid4()))
        self.conn.execute(
            """
            INSERT INTO contacts
                (id, user_id, name, role, voice_embedding,
                 embedding_model_version, relationship_context, last_seen)
            VALUES
                (:id, :user_id, :name, :role, :voice_embedding,
                 :embedding_model_version, :relationship_context, :last_seen)
            """,
            {
                "id": contact_id,
                "user_id": user_id,
                "name": contact_data.get("name", ""),
                "role": contact_data.get("role", ""),
                "voice_embedding": contact_data.get("voice_embedding"),
                "embedding_model_version": contact_data.get(
                    "embedding_model_version"
                ),
                "relationship_context": contact_data.get(
                    "relationship_context", ""
                ),
                "last_seen": contact_data.get(
                    "last_seen", datetime.utcnow().isoformat()
                ),
            },
        )
        self.conn.commit()

    def get_contacts(self, user_id: str) -> list[dict]:
        """Return all contacts belonging to a user."""
        rows = self.conn.execute(
            "SELECT * FROM contacts WHERE user_id = :user_id ORDER BY name",
            {"user_id": user_id},
        ).fetchall()
        return self._rows_to_dicts(rows)

    def get_contacts_with_voice(self, user_id: str) -> list[dict]:
        """
        Return contacts that have a voice embedding enrolled.

        Used by the diarizer to match incoming speaker segments against
        known voices.
        """
        rows = self.conn.execute(
            """
            SELECT * FROM contacts
             WHERE user_id = :user_id
               AND voice_embedding IS NOT NULL
             ORDER BY name
            """,
            {"user_id": user_id},
        ).fetchall()
        return self._rows_to_dicts(rows)

    def save_contact_voice(
        self, user_id: str, name: str, embedding: bytes
    ) -> None:
        """
        Insert or update a contact's voice embedding.

        If a contact with the given *name* already exists for this user,
        the embedding is updated in place.  Otherwise a new contact row
        is created.
        """
        existing = self.conn.execute(
            """
            SELECT id FROM contacts
             WHERE user_id = :user_id AND name = :name
            """,
            {"user_id": user_id, "name": name},
        ).fetchone()

        now = datetime.utcnow().isoformat()

        if existing:
            self.conn.execute(
                """
                UPDATE contacts
                   SET voice_embedding = :embedding,
                       last_seen = :last_seen
                 WHERE id = :id AND user_id = :user_id
                """,
                {
                    "embedding": embedding,
                    "last_seen": now,
                    "id": existing["id"],
                    "user_id": user_id,
                },
            )
        else:
            self.conn.execute(
                """
                INSERT INTO contacts
                    (id, user_id, name, role, voice_embedding,
                     relationship_context, last_seen)
                VALUES
                    (:id, :user_id, :name, '', :embedding, '', :last_seen)
                """,
                {
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "name": name,
                    "embedding": embedding,
                    "last_seen": now,
                },
            )

        self.conn.commit()

    # ------------------------------------------------------------------
    # Memory episode operations (all scoped by user_id)
    # ------------------------------------------------------------------

    def create_memory_episode(
        self, user_id: str, episode_data: dict
    ) -> None:
        """Store an episodic memory entry for later semantic retrieval."""
        episode_id = episode_data.get("id", str(uuid.uuid4()))
        self.conn.execute(
            """
            INSERT INTO memory_episodes
                (id, user_id, speaker_id, content, embedding_id,
                 timestamp, sensitivity, tags)
            VALUES
                (:id, :user_id, :speaker_id, :content, :embedding_id,
                 :timestamp, :sensitivity, :tags)
            """,
            {
                "id": episode_id,
                "user_id": user_id,
                "speaker_id": episode_data.get("speaker_id"),
                "content": episode_data.get("content", ""),
                "embedding_id": episode_data.get("embedding_id"),
                "timestamp": episode_data.get(
                    "timestamp", datetime.utcnow().isoformat()
                ),
                "sensitivity": episode_data.get("sensitivity", "normal"),
                "tags": json.dumps(episode_data.get("tags", [])),
            },
        )
        self.conn.commit()

    def query_by_date(self, user_id: str, date_str: str) -> list[dict]:
        """
        Retrieve memory episodes that occurred on a given date.

        Parameters
        ----------
        date_str : str
            ISO date string (``YYYY-MM-DD``).  Matches episodes whose
            ``timestamp`` starts with this prefix.
        """
        rows = self.conn.execute(
            """
            SELECT * FROM memory_episodes
             WHERE user_id = :user_id
               AND timestamp LIKE :date_prefix
             ORDER BY timestamp ASC
            """,
            {
                "user_id": user_id,
                "date_prefix": f"{date_str}%",
            },
        ).fetchall()

        results: list[dict] = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d.get("tags") or "[]")
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Flag operations (all scoped by user_id)
    # ------------------------------------------------------------------

    def insert_flag(self, user_id: str, flag_data: dict) -> None:
        """Record an injected flag (calendar event, notification, etc.)."""
        flag_id = flag_data.get("id", str(uuid.uuid4()))
        self.conn.execute(
            """
            INSERT INTO injected_flags
                (id, user_id, source, event_type, data,
                 injected_at, acknowledged)
            VALUES
                (:id, :user_id, :source, :event_type, :data,
                 :injected_at, 0)
            """,
            {
                "id": flag_id,
                "user_id": user_id,
                "source": flag_data.get("source", ""),
                "event_type": flag_data.get("event_type", ""),
                "data": json.dumps(flag_data.get("data", {})),
                "injected_at": flag_data.get(
                    "injected_at", datetime.utcnow().isoformat()
                ),
            },
        )
        self.conn.commit()

    def get_pending_flags(self, user_id: str) -> list[dict]:
        """Return all un-acknowledged flags for a user."""
        rows = self.conn.execute(
            """
            SELECT * FROM injected_flags
             WHERE user_id = :user_id
               AND acknowledged = 0
             ORDER BY injected_at ASC
            """,
            {"user_id": user_id},
        ).fetchall()

        results: list[dict] = []
        for row in rows:
            d = dict(row)
            d["data"] = json.loads(d.get("data") or "{}")
            results.append(d)
        return results

    def acknowledge_flag(self, user_id: str, flag_id: str) -> None:
        """Mark a flag as acknowledged (user-scoped)."""
        self.conn.execute(
            """
            UPDATE injected_flags
               SET acknowledged = 1
             WHERE id = :id AND user_id = :user_id
            """,
            {"id": flag_id, "user_id": user_id},
        )
        self.conn.commit()