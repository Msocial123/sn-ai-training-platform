"""
Shared LLM client, used by agents that generate free-text (summaries,
draft KB articles, open-ended chat) and multi-agent reasoning. Provider
priority, each one falling through to the next on failure rather than
giving up immediately:
  1. Ollama (self-hosted, qwen3.8:27b) -- our own infrastructure, no
     external account entitlement gate. Primary provider.
  2. openai.gpt-oss-120b-1:0 (Bedrock bedrock-runtime endpoint).
  3. Amazon Nova Pro (Bedrock bedrock-runtime endpoint).
  4. Anthropic (if ANTHROPIC_API_KEY is set).
  5. Raises LLMError -- callers fall back to a template response.

GPT-5.5 deliberately excluded per instruction -- only gpt-oss-120b and
Nova Pro are used from Bedrock. (bedrock_client.py still has
complete_gpt55()/gpt55_configured() defined and unused, in case that
changes later.)

Callers should catch LLMError specifically (not a bare except) so a
provider failure degrades to the template fallback instead of 500ing the
whole request -- that's the resilience property the break tests check.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bedrock_client  # noqa: E402
import ollama_client  # noqa: E402

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


class LLMError(Exception):
    """Raised for any LLM provider failure. Callers catch this one type."""


# Set to the provider that ACTUALLY generated the most recent successful
# completion -- not just "what's configured." provider() below reports
# this, not a guess, precisely because reporting the configured priority
# as if it were the result already caused one real false-positive in this
# project (Nova Pro was reported as "working" purely because it was
# top-of-chain, when every call was actually silently hitting the
# template fallback). Never repeat that: this string only changes inside
# a successful return, right below.
LAST_PROVIDER_USED = "none (template fallback)"


def is_configured() -> bool:
    return ollama_client.is_configured() or bedrock_client.is_configured() or bool(ANTHROPIC_API_KEY)


def provider() -> str:
    """The provider that generated the LAST successful completion --
    ground truth, not a priority-order guess. Before any call has ever
    succeeded, honestly reports the template fallback."""
    return LAST_PROVIDER_USED


def complete(system_prompt: str, user_prompt: str, max_tokens: int = 500) -> str:
    """Raises LLMError only if EVERY configured provider fails -- callers
    must catch it and use their own template fallback, never let it 500
    the request."""
    global LAST_PROVIDER_USED
    errors = []

    try:
        text = ollama_client.complete(system_prompt, user_prompt, max_tokens)
        LAST_PROVIDER_USED = f"ollama ({ollama_client.MODEL_ID})"
        return text
    except ollama_client.OllamaError as e:
        errors.append(f"Ollama: {e}")

    if bedrock_client.is_configured():
        try:
            text = bedrock_client.complete(system_prompt, user_prompt, max_tokens, model_id=bedrock_client.GPT_OSS_120B_MODEL_ID)
            LAST_PROVIDER_USED = f"bedrock ({bedrock_client.GPT_OSS_120B_MODEL_ID})"
            return text
        except bedrock_client.BedrockError as e:
            errors.append(f"gpt-oss-120b: {e}")

        try:
            text = bedrock_client.complete(system_prompt, user_prompt, max_tokens)  # default MODEL_ID (Nova Pro)
            LAST_PROVIDER_USED = f"bedrock ({bedrock_client.MODEL_ID})"
            return text
        except bedrock_client.BedrockError as e:
            errors.append(f"Nova Pro: {e}")

    if ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=max_tokens,
                system=system_prompt, messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            LAST_PROVIDER_USED = f"anthropic ({ANTHROPIC_MODEL})"
            return text
        except Exception as e:
            errors.append(f"Anthropic: {e}")

    LAST_PROVIDER_USED = "none (template fallback)"
    if errors:
        raise LLMError(" | ".join(errors))
    raise LLMError("No LLM provider configured")


def complete_fast(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str:
    """Same fallback chain as complete(), but tries Ollama's smaller/
    faster qwen3:8b first instead of qwen3.8:27b -- for latency-sensitive
    callers (chat) where the ~1-3 minute wait a 27B CPU-only response
    takes would be a broken experience. Still falls through to Bedrock/
    Anthropic/template exactly like complete() if even the fast model
    isn't available."""
    global LAST_PROVIDER_USED
    errors = []

    try:
        text = ollama_client.complete_fast(system_prompt, user_prompt, max_tokens)
        LAST_PROVIDER_USED = f"ollama ({ollama_client.FAST_MODEL_ID})"
        return text
    except ollama_client.OllamaError as e:
        errors.append(f"Ollama (fast): {e}")

    if bedrock_client.is_configured():
        try:
            text = bedrock_client.complete(system_prompt, user_prompt, max_tokens, model_id=bedrock_client.GPT_OSS_120B_MODEL_ID)
            LAST_PROVIDER_USED = f"bedrock ({bedrock_client.GPT_OSS_120B_MODEL_ID})"
            return text
        except bedrock_client.BedrockError as e:
            errors.append(f"gpt-oss-120b: {e}")

        try:
            text = bedrock_client.complete(system_prompt, user_prompt, max_tokens)
            LAST_PROVIDER_USED = f"bedrock ({bedrock_client.MODEL_ID})"
            return text
        except bedrock_client.BedrockError as e:
            errors.append(f"Nova Pro: {e}")

    if ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=max_tokens,
                system=system_prompt, messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            LAST_PROVIDER_USED = f"anthropic ({ANTHROPIC_MODEL})"
            return text
        except Exception as e:
            errors.append(f"Anthropic: {e}")

    LAST_PROVIDER_USED = "none (template fallback)"
    if errors:
        raise LLMError(" | ".join(errors))
    raise LLMError("No LLM provider configured")
