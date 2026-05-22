from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from server.transport.client_control import ClientControlSession

RespondVia = Literal["voice_and_chat", "chat_only"]
InterruptPolicy = Literal["replace", "queue"]
InputKind = Literal["voice", "chat", "proactive", "system"]


@dataclass(frozen=True)
class RespondViaDecision:
    respond_via: RespondVia
    interrupt_policy: InterruptPolicy


def compute_respond_via(
    *,
    capabilities_tts: bool,
    client_state: ClientControlSession,
    input_kind: InputKind,
) -> RespondViaDecision:
    """Rule 13 decision table (PLAN.md §7.5)."""
    if input_kind == "voice":
        return RespondViaDecision(respond_via="voice_and_chat", interrupt_policy="replace")

    if input_kind == "system":
        return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")

    if input_kind == "chat":
        if not capabilities_tts:
            return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")
        if client_state.playback == "playing":
            return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")
        if client_state.route == "none":
            return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")
        if client_state.mode == "meeting":
            return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")
        if not client_state.visible:
            return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")
        return RespondViaDecision(respond_via="voice_and_chat", interrupt_policy="queue")

    # proactive (notifier)
    if not client_state.visible:
        return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")
    if client_state.capture == "recording":
        return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")
    if client_state.mode == "meeting":
        return RespondViaDecision(respond_via="chat_only", interrupt_policy="queue")
    # NEEDS_INFO and DONE default to voice_and_chat when gates pass (caller may refine)
    return RespondViaDecision(respond_via="voice_and_chat", interrupt_policy="queue")


def apply_respond_via_override(
    directive: str | None,
    current: RespondVia,
) -> RespondVia:
    if directive is None:
        return current
    if directive == "chat":
        return "chat_only"
    if directive == "voice":
        return "voice_and_chat"
    return "voice_and_chat"
