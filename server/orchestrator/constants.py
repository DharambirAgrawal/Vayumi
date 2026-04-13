from __future__ import annotations


class Capability:
    RESEARCH = "research"
    COMMUNICATION = "communication"
    PRODUCTIVITY = "productivity"
    DATA = "data"


class ToolId:
    CURRENT_TIME = "current_time"
    CURRENT_DATE = "current_date"
    WEB_SEARCH = "web_search"
    READ_URL = "read_url"
    URL_SUMMARIZER = "url_summarizer"
    ANALYZE_IMAGE = "analyze_image"
    TRANSCRIBE_AUDIO = "transcribe_audio"
    ANALYZE_VIDEO = "analyze_video"
    EMAIL_READER = "email_reader"
    DOC_GENERATOR = "doc_generator"
    DATA_ANALYZER = "data_analyzer"

    MEMORY_SEARCH = "memory_search"
    MEMORY_SAVE = "memory_save"
    MEMORY_UPDATE = "memory_update"
    MEMORY_UPDATE_BY_QUERY = "memory_update_by_query"
    MEMORY_DELETE = "memory_delete"
    MEMORY_INGEST = "memory_ingest"
    MEMORY_DELETE_LINKS = "memory_delete_links"
    MEMORY_GET_USER_MODEL = "memory_get_user_model"
    MEMORY_ADD_TURN = "memory_add_turn"
    MEMORY_FLUSH_SESSION = "memory_flush_session"


class WorkerEvent:
    TOOL_STATUS = "tool_status"
    CHUNK = "chunk"
    DONE = "done"
    PAUSED = "paused"


class TaskSignal:
    STEP = "STEP"
    DONE = "DONE"
    NEEDS_INFO = "NEEDS_INFO"
    ERROR = "ERROR"
    CAPABILITY_GAP = "CAPABILITY_GAP"


class OrchestratorEvent:
    TOOL_STATUS = "tool_status"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETE = "task_complete"
    TASK_WAITING = "task_waiting"
    TASK_ERROR = "task_error"
    AGENT_THINKING = "agent_thinking"
    AGENT_RESPONSE_END = "agent_response_end"
    CHATBOT_RESPONSE = "chatbot_response"
    ERROR = "error"


DIRECT_TOOL_FINALIZE = {
    ToolId.CURRENT_TIME,
    ToolId.CURRENT_DATE,
    ToolId.READ_URL,
    ToolId.ANALYZE_IMAGE,
    ToolId.TRANSCRIBE_AUDIO,
    ToolId.ANALYZE_VIDEO,
    ToolId.WEB_SEARCH,
    ToolId.MEMORY_SEARCH,
    ToolId.MEMORY_SAVE,
    ToolId.MEMORY_UPDATE,
    ToolId.MEMORY_UPDATE_BY_QUERY,
    ToolId.MEMORY_DELETE,
    ToolId.MEMORY_INGEST,
    ToolId.MEMORY_DELETE_LINKS,
    ToolId.MEMORY_GET_USER_MODEL,
    ToolId.MEMORY_ADD_TURN,
    ToolId.MEMORY_FLUSH_SESSION,
}


CAPABILITY_ROUTING: dict[str, list[str]] = {
    Capability.RESEARCH: [ToolId.WEB_SEARCH, ToolId.URL_SUMMARIZER, ToolId.READ_URL],
    Capability.COMMUNICATION: [ToolId.EMAIL_READER],
    Capability.PRODUCTIVITY: [ToolId.DOC_GENERATOR, ToolId.WEB_SEARCH],
    Capability.DATA: [ToolId.DATA_ANALYZER, ToolId.WEB_SEARCH],
}
