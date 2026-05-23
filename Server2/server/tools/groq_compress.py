from __future__ import annotations

from server.logger import get_logger

log = get_logger("tools.groq_compress")

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MIN_CHARS_TO_COMPRESS = 2500
TARGET_CHARS = 2200


async def groq_compress_article(
    *,
    api_key: str,
    query: str,
    title: str,
    url: str,
    text: str,
    model: str = DEFAULT_MODEL,
) -> str:
    """Use Groq chat to shrink long article text for downstream local LLM."""
    body = text.strip()
    if len(body) < MIN_CHARS_TO_COMPRESS:
        return body

    try:
        from groq import AsyncGroq
    except ImportError:
        log.warning("groq_compress.missing_package")
        return body[:TARGET_CHARS]

    client = AsyncGroq(api_key=api_key)
    prompt = (
        f"Research query: {query}\n"
        f"Source: {title} ({url})\n\n"
        f"Article text:\n{body[:14_000]}\n\n"
        "Write a dense factual summary under 200 words. "
        "Keep numbers, dates, and company names. No URLs. Prose only."
    )
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You compress web articles for a research assistant.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.2,
        )
    except Exception as exc:
        log.warning("groq_compress.failed", error=str(exc), url=url[:80])
        return body[:TARGET_CHARS]

    choice = response.choices[0].message.content if response.choices else None
    if not choice or not str(choice).strip():
        return body[:TARGET_CHARS]
    out = str(choice).strip()
    log.info("groq_compress.ok", url=url[:80], in_chars=len(body), out_chars=len(out))
    return out
