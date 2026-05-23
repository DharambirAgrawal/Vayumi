import pytest

from server.orchestrator.plan_stream import PlanStreamHandler


@pytest.mark.asyncio
async def test_emits_first_sentence_before_delegate() -> None:
    captions: list[str] = []

    async def on_caption(text: str) -> None:
        captions.append(text)

    handler = PlanStreamHandler(on_status_caption=on_caption)
    for ch in "I'll check Tesla for you. ":
        await handler.on_token(ch)
    await handler.on_token('[DELEGATE capability=main goal="x" payload={}]')

    assert handler.ack_sent
    assert captions
    assert "Tesla" in captions[0]


@pytest.mark.asyncio
async def test_early_delegates_after_ack() -> None:
    ready: list[str] = []

    async def on_ready(buffer: str) -> None:
        ready.append(buffer)

    async def on_caption(_: str) -> None:
        pass

    handler = PlanStreamHandler(
        on_status_caption=on_caption,
        on_delegates_ready=on_ready,
    )
    spoken = "I'll look that up. "
    delegate = (
        '[DELEGATE capability=main goal="q" '
        'payload={"tool":"web_search","args":{"query":"x"}}]'
    )
    for ch in spoken:
        await handler.on_token(ch)
    assert not ready
    for ch in delegate:
        await handler.on_token(ch)

    assert ready
    assert "DELEGATE" in ready[0]
