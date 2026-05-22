from __future__ import annotations

import asyncio

import pytest

from server.voice.interrupt import InterruptController
from server.voice.types import SpeechState


@pytest.mark.asyncio
async def test_interrupt_button_returns_idle() -> None:
    ctrl = InterruptController()
    ctrl.begin_thinking("turn-1")
    ctrl.begin_speaking()

    await ctrl.handle_interrupt("button")

    assert ctrl.state == SpeechState.IDLE


@pytest.mark.asyncio
async def test_interrupt_wake_returns_idle_and_drops_utterance() -> None:
    ctrl = InterruptController()
    ctrl.begin_speaking()

    await ctrl.handle_interrupt("wake")

    assert ctrl.state == SpeechState.IDLE
    assert ctrl.should_drop_utterance() is True


@pytest.mark.asyncio
async def test_cancel_turn_task() -> None:
    ctrl = InterruptController()
    ctrl.begin_thinking("turn-2")

    async def long_running() -> None:
        await asyncio.sleep(10)

    task = asyncio.create_task(long_running())
    ctrl.attach_turn_task(task)

    await ctrl.handle_interrupt("button")

    with pytest.raises(asyncio.CancelledError):
        await task
