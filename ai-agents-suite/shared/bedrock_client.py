"""
Amazon Bedrock client using a Bedrock API key (bearer token) -- plain
HTTPS + Authorization: Bearer, no boto3 / AWS SigV4 credentials needed.
This is what AWS_BEARER_TOKEN_BEDROCK is for.

Three Bedrock-hosted models, same bearer token for all, two different
APIs depending on the model:
  - Amazon Nova Pro: bedrock-runtime endpoint, Converse API (complete()).
  - openai.gpt-oss-20b-1:0: SAME bedrock-runtime/Converse API as Nova Pro
    -- just a different model_id passed to complete().
  - OpenAI GPT-5.5 (hosted on Bedrock): a DIFFERENT endpoint,
    bedrock-mantle, using the OpenAI-compatible Responses API
    (complete_gpt55()). Only available in us-east-1 / us-east-2, unlike
    the runtime endpoint.

Raises BedrockError (never a raw requests exception) on any failure, so
callers can catch one specific, well-understood exception type and fall
back cleanly -- this is the seam the break/resilience tests in
tests/break_test_bedrock.py exercise.
"""
import os
import requests

API_KEY = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
REGION = os.environ.get("AWS_BEDROCK_REGION", "us-east-1")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
GPT55_MODEL_ID = "openai.gpt-5.5"
GPT_OSS_20B_MODEL_ID = "openai.gpt-oss-20b-1:0"
GPT_OSS_120B_MODEL_ID = "openai.gpt-oss-120b-1:0"


class BedrockError(Exception):
    """Raised for any Bedrock failure -- timeout, throttling, bad input,
    auth failure, malformed response. Callers should catch this one type
    and fall back, not the underlying requests/HTTP exceptions."""


def is_configured() -> bool:
    return bool(API_KEY)


def _endpoint(model_id: str) -> str:
    return f"https://bedrock-runtime.{REGION}.amazonaws.com/model/{model_id}/converse"


def complete(system_prompt: str, user_prompt: str, max_tokens: int = 500, timeout: int = 20, model_id: str | None = None) -> str:
    if not is_configured():
        raise BedrockError("Bedrock not configured (AWS_BEARER_TOKEN_BEDROCK not set)")

    body = {
        "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
        "system": [{"text": system_prompt}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.4},
    }

    try:
        resp = requests.post(
            _endpoint(model_id or MODEL_ID),
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise BedrockError(f"Bedrock request timed out after {timeout}s")
    except requests.exceptions.RequestException as e:
        raise BedrockError(f"Bedrock request failed: {e}")

    if resp.status_code == 429:
        raise BedrockError("Bedrock throttled the request (429) -- back off and retry")
    if resp.status_code == 401 or resp.status_code == 403:
        raise BedrockError(f"Bedrock auth failed ({resp.status_code}) -- check AWS_BEARER_TOKEN_BEDROCK")
    if resp.status_code == 404:
        raise BedrockError(f"Model '{model_id or MODEL_ID}' not found or not enabled in region {REGION}")
    if resp.status_code >= 400:
        raise BedrockError(f"Bedrock returned {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        parts = data["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts)
    except (ValueError, KeyError, TypeError) as e:
        raise BedrockError(f"Unexpected Bedrock response shape: {e}")


def gpt55_configured() -> bool:
    # GPT-5.5 on Bedrock is only available in us-east-1 / us-east-2 --
    # the runtime endpoint's region (which could be anything) doesn't
    # apply here, so check explicitly rather than assuming REGION works.
    return bool(API_KEY) and REGION in ("us-east-1", "us-east-2")


def complete_gpt55(system_prompt: str, user_prompt: str, max_tokens: int = 500, timeout: int = 30) -> str:
    """GPT-5.5, hosted on Bedrock's bedrock-mantle endpoint via the
    OpenAI-compatible Responses API -- a different endpoint/API shape
    than Nova Pro's Converse API above, same bearer token."""
    if not gpt55_configured():
        raise BedrockError(f"GPT-5.5 not available (needs AWS_BEARER_TOKEN_BEDROCK + region us-east-1/us-east-2, got region={REGION!r})")

    url = f"https://bedrock-mantle.{REGION}.api.aws/openai/v1/responses"
    body = {
        "model": GPT55_MODEL_ID,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_output_tokens": max_tokens,
    }

    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise BedrockError(f"GPT-5.5 request timed out after {timeout}s")
    except requests.exceptions.RequestException as e:
        raise BedrockError(f"GPT-5.5 request failed: {e}")

    if resp.status_code == 429:
        raise BedrockError("GPT-5.5 throttled the request (429) -- back off and retry")
    if resp.status_code in (401, 403):
        raise BedrockError(f"GPT-5.5 auth failed ({resp.status_code}) -- check AWS_BEARER_TOKEN_BEDROCK")
    if resp.status_code == 404:
        raise BedrockError("GPT-5.5 model access not enabled for this account (404) -- same 'Bedrock model access' console step as Nova Pro, done per-model")
    if resp.status_code >= 400:
        raise BedrockError(f"GPT-5.5 returned {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        # Responses API shape: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "..."}]}]}
        text_parts = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") in ("output_text", "text"):
                        text_parts.append(c.get("text", ""))
        if not text_parts and "output_text" in data:  # some SDK versions flatten this
            text_parts = [data["output_text"]]
        if not text_parts:
            raise KeyError("no output_text found in response")
        return "".join(text_parts)
    except (ValueError, KeyError, TypeError) as e:
        raise BedrockError(f"Unexpected GPT-5.5 response shape: {e} -- raw: {resp.text[:300]}")
