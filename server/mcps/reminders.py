# =============================================================================
# server/mcps/reminders.py — Reminder MCPs (set_reminder, get_reminders)
# =============================================================================
#
# PURPOSE:
#   Manages user reminders. Two MCP functions bundled here:
#   - set_reminder: Create a new reminder with due date/time
#   - get_reminders: List reminders for the user (today's or all)
#   All reminders are scoped to user_id — one user cannot see another's.
#
# FUNCTION: set_reminder(params: dict, user_id: str) -> dict
#
#   params:
#     - "text": str — What to remind about (e.g. "submit assignment")
#     - "due_datetime": str — ISO format datetime (e.g. "2026-03-30T15:00:00")
#
#   Steps:
#     1. Parse due_datetime
#     2. Generate reminder ID (uuid4)
#     3. Insert into SQLite reminders table
#     4. Return {"success": True, "reminder_id": str, "due": str}
#
#   Error: Invalid datetime → {"success": False, "error": "Invalid date format"}
#
# FUNCTION: get_reminders(params: dict, user_id: str) -> dict
#
#   params:
#     - "filter": str (optional) — "today" (default) | "all" | "pending"
#
#   Steps:
#     1. Query SQLite: SELECT * FROM reminders WHERE user_id = :user_id
#        Apply filter (today's date range, or pending only, or all)
#     2. Return {"success": True, "reminders": [...]}
#
# =============================================================================

import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from server.memory.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


async def set_reminder(params: dict, user_id: str, sqlite_store: SQLiteStore) -> dict:
    """
    Create a new timed reminder for the user.

    Parameters
    ----------
    params : dict
        Must contain "text" (str) and "due_datetime" (ISO 8601 str).
    user_id : str
        The ID of the user creating the reminder.
    sqlite_store : SQLiteStore
        Injected database reference.

    Returns
    -------
    dict
        Status indicator, along with the created reminder ID and parsed due date.
    """
    text = params.get("text")
    due_datetime_str = params.get("due_datetime")

    if not text or not due_datetime_str:
        logger.warning("set_reminder failed: missing 'text' or 'due_datetime'")
        return {"success": False, "error": "Missing 'text' or 'due_datetime'."}

    # 1. Parse due_datetime
    try:
        # Python's fromisoformat is flexible in 3.11+, handling standard ISO strings.
        # Replace 'Z' with '+00:00' to cleanly parse UTC indicators.
        clean_date_str = due_datetime_str.replace("Z", "+00:00")
        due_datetime = datetime.fromisoformat(clean_date_str)
    except ValueError:
        logger.error("set_reminder failed: Invalid date format '%s'", due_datetime_str)
        return {
            "success": False, 
            "error": "Invalid date format. Please use ISO 8601 format (e.g., YYYY-MM-DDTHH:MM:SS)."
        }

    # 2. Generate reminder ID
    reminder_id = str(uuid4())

    # 3. Insert into SQLite (wrapped in to_thread to prevent blocking event loop)
    try:
        await asyncio.to_thread(
            sqlite_store.create_reminder,
            user_id=user_id,
            reminder_id=reminder_id,
            text=text,
            due_datetime=due_datetime
        )
        logger.info("Created reminder %s for user %s due at %s", reminder_id, user_id, due_datetime.isoformat())
    except Exception as e:
        logger.exception("Database error while creating reminder.")
        return {"success": False, "error": f"Internal database error: {str(e)}"}

    # 4. Return success
    return {
        "success": True,
        "reminder_id": reminder_id,
        "due": due_datetime.isoformat()
    }


async def get_reminders(params: dict, user_id: str, sqlite_store: SQLiteStore) -> dict:
    """
    Retrieve reminders for the user.

    Parameters
    ----------
    params : dict
        Optionally contains "filter" ("today", "all", or "pending").
    user_id : str
        The ID of the user requesting their reminders.
    sqlite_store : SQLiteStore
        Injected database reference.

    Returns
    -------
    dict
        Status indicator and a list of matching reminder records.
    """
    filter_type = params.get("filter", "today")

    # Guard against invalid filter values hallucinated by the LLM
    valid_filters = {"today", "all", "pending"}
    if filter_type not in valid_filters:
        logger.debug("Invalid filter '%s' requested, defaulting to 'today'.", filter_type)
        filter_type = "today"

    try:
        # Run the DB query in a background thread
        reminders = await asyncio.to_thread(
            sqlite_store.get_reminders,
            user_id=user_id,
            filter_type=filter_type
        )
        logger.info("Retrieved %d %s reminders for user %s", len(reminders), filter_type, user_id)
        
        return {
            "success": True,
            "reminders": reminders
        }
    except Exception as e:
        logger.exception("Database error while retrieving reminders.")
        return {"success": False, "error": f"Internal database error: {str(e)}"}


def register_handlers(mcp_runner, sqlite_store: SQLiteStore | None = None, **_kwargs) -> None:
    """Register reminder MCP handlers with the shared runner."""
    if sqlite_store is None:
        raise ValueError("sqlite_store is required to register reminder MCPs")

    async def _set(params: dict, user_id: str, **_ignored) -> dict:
        return await set_reminder(params, user_id, sqlite_store)

    async def _get(params: dict, user_id: str, **_ignored) -> dict:
        return await get_reminders(params, user_id, sqlite_store)

    mcp_runner.register_handler("set_reminder", _set)
    mcp_runner.register_handler("get_reminders", _get)