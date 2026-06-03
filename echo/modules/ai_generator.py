"""AI content generation using Anthropic Claude."""
from __future__ import annotations

from typing import Any

from echo.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from echo.core.logger import get_logger

log = get_logger("echo.modules.ai_generator")


def generate_content(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1024,
) -> str:
    """Call Anthropic Claude to generate content. Returns the text response."""
    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — returning placeholder content")
        return f"[AI generation unavailable — ANTHROPIC_API_KEY not configured]\n\nPrompt was: {prompt}"

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs)
        text = response.content[0].text
        log.info("AI generation complete model=%s tokens=%s", ANTHROPIC_MODEL, response.usage.output_tokens)
        return text

    except Exception as exc:
        log.exception("AI generation failed: %s", exc)
        raise


def generate_linkedin_post(topic: str, brand: str = "", **kwargs: Any) -> str:
    system = (
        "You are an expert B2G/GovCon content strategist. "
        "Write a professional LinkedIn post that is concise, engaging, and ends with a clear CTA."
    )
    prompt = f"Write a LinkedIn post about: {topic}"
    if brand:
        prompt += f"\nBrand context: {brand}"
    return generate_content(prompt, system=system, **kwargs)


def generate_intelligence_summary(data: dict[str, Any], topic: str = "") -> str:
    system = "You are a GovCon market intelligence analyst. Summarize the key insights concisely."
    prompt = f"Summarize this market data:\n{data}"
    if topic:
        prompt = f"Topic: {topic}\n\n" + prompt
    return generate_content(prompt, system=system)


def generate_prospect_dm(
    prospect_name: str,
    *,
    company: str = "",
    role: str = "",
    angle: str = "",
    brand: str = "",
) -> str:
    """Draft a short, personalized outreach DM for a GovCon prospect."""
    system = (
        "You are a GovCon business-development specialist. Write a concise, personalized "
        "LinkedIn direct message (3-5 sentences) that opens a relationship — specific, "
        "non-spammy, no hard sell, ends with a low-friction question. No subject line."
    )
    lines = [f"Prospect: {prospect_name}"]
    if role:
        lines.append(f"Role: {role}")
    if company:
        lines.append(f"Company: {company}")
    if angle:
        lines.append(f"Angle/context: {angle}")
    if brand:
        lines.append(f"Sender brand: {brand}")
    return generate_content("\n".join(lines), system=system, max_tokens=512)


def generate_strategic_comment(
    post_context: str,
    *,
    angle: str = "",
    brand: str = "",
) -> str:
    """Draft a strategic, value-adding comment to leave on a GovCon post."""
    system = (
        "You are a GovCon thought leader. Write a short (2-4 sentence) comment that adds "
        "genuine insight to the post, positions the author as helpful (not promotional), "
        "and invites further discussion. No hashtags, no link-dropping."
    )
    prompt = f"Post to comment on:\n{post_context}"
    if angle:
        prompt += f"\n\nDesired angle: {angle}"
    if brand:
        prompt += f"\nCommenter brand: {brand}"
    return generate_content(prompt, system=system, max_tokens=400)
