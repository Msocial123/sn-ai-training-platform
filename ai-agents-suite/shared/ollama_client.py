"""
Self-hosted LLM client -- Ollama running on our own dedicated
"llm-inference" node (see k8s/ollama/ollama.yaml, terraform/karpenter.tf).
No external API, no account entitlement gate to wait on; this is genuinely
in our control, which is exactly why it's the top-priority provider in
llm_client.py.

Two models are pulled onto the same instance (same disk, same server,
just a different model_id per request -- no extra infrastructure):
  - qwen3.8:27b (MODEL_ID)      -- higher quality, ~1-3 min per call on
    this CPU-only node. Used where quality matters more than latency
    (Now Assist summaries, Knowledge Article drafts).
  - qwen3:8b (FAST_MODEL_ID)    -- much faster (~10-20s typical), lower
    quality. Used where responsiveness matters more (Virtual Agent chat --
    nobody should wait 2 minutes for a chat reply).

The only real failure mode here is "not ready yet" -- either the pod
hasn't scheduled/started, or a model pull hasn't finished. Raises
OllamaError (never a raw requests exception), same pattern as
bedrock_client.py, so callers fall back cleanly.

Both models are qwen3 "thinking" models: Ollama returns their reasoning
trace in a separate message.thinking field, distinct from the final
message.content. This matters a lot for max_tokens -- a request can burn
its entire token budget on the <think> trace and finish with content=""
(done_reason="length") before ever writing the actual answer. That's a
real bug we hit (a summary silently coming back empty/truncated), not
just a style choice, so every request explicitly disables it with
"think": false. We also set "keep_alive" generously so the model stays
resident in RAM between requests -- reloading a model from disk is a
~100s one-time cost per pod lifetime (or after 5 min idle, Ollama's
default keep_alive), completely separate from actual generation time,
and repeating that on every sporadic classroom question would be a bad
experience.
"""
import os
import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
MODEL_ID = os.environ.get("OLLAMA_MODEL", "qwen3.8:27b")
FAST_MODEL_ID = os.environ.get("OLLAMA_FAST_MODEL", "qwen3:8b")


class OllamaError(Exception):
    """Raised for any Ollama failure -- not ready, timeout, malformed
    response. Callers should catch this one type and fall back."""


def is_configured() -> bool:
    # Always "configured" -- it's our own in-cluster service, not an
    # external credential someone has to supply. Availability (is the pod
    # actually up and the model pulled) is what complete() below finds
    # out for real, on each call.
    return True


def complete(system_prompt: str, user_prompt: str, max_tokens: int = 500, timeout: int = 170, model: str | None = None) -> str:
    # CPU-only inference on the 27B model is genuinely slow -- 170s (just
    # under nginx's 180s proxy_read_timeout) rather than a typical API
    # client's usual 20-30s default. Callers using the fast model should
    # pass a shorter timeout of their own.
    model_id = model or MODEL_ID
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,  # see module docstring -- without this, num_predict
                         # can be entirely consumed by the <think> trace and
                         # content comes back empty.
        "keep_alive": "30m",  # keep the model resident between requests --
                               # a cold (re)load is ~100s, separate from and
                               # on top of actual generation time.
        "options": {"num_predict": max_tokens},
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
    except requests.exceptions.Timeout:
        raise OllamaError(f"Ollama request timed out after {timeout}s -- model may still be loading/pulling")
    except requests.exceptions.ConnectionError as e:
        raise OllamaError(f"Ollama not reachable (pod not up yet?): {e}")
    except requests.exceptions.RequestException as e:
        raise OllamaError(f"Ollama request failed: {e}")

    if resp.status_code == 404:
        raise OllamaError(f"Model '{model_id}' not found -- still pulling, or pull failed")
    if resp.status_code >= 400:
        raise OllamaError(f"Ollama returned {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        text = data["message"]["content"]
    except (ValueError, KeyError, TypeError) as e:
        raise OllamaError(f"Unexpected Ollama response shape: {e}")

    if not text.strip():
        # Defensive backstop for the thinking-eats-the-budget failure mode
        # (see module docstring) -- "think": false should prevent this, but
        # if it ever recurs, treat it as a failure and fall through to the
        # next provider rather than silently returning blank text.
        reason = data.get("done_reason", "unknown")
        raise OllamaError(f"Ollama returned empty content (done_reason={reason}) -- likely ran out of tokens on reasoning")

    return text


def complete_fast(system_prompt: str, user_prompt: str, max_tokens: int = 300, timeout: int = 120) -> str:
    """qwen3:8b instead of the 27B default -- for latency-sensitive
    callers (chat) where a 1-3 minute wait would be a broken experience.
    With thinking disabled and the model kept warm (see module docstring),
    a steady-state call is typically single-digit seconds; 120s of
    headroom is for the rare cold-load case (first call after the pod
    (re)starts, or a 30+ min gap) rather than the normal path."""
    return complete(system_prompt, user_prompt, max_tokens, timeout=timeout, model=FAST_MODEL_ID)
