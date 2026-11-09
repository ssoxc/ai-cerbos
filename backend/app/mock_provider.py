"""Deterministic OpenAI-compatible provider. This makes no external AI calls.

Streams like OpenAI when asked: one word per chunk, then, with
stream_options.include_usage, a final chunk carrying the token usage.
"""

import hmac
import json
import os
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

app = FastAPI(title="ai-cerbos deterministic demo provider")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
def completion(body: dict, authorization: str = Header(default="")):
    expected = os.environ.get("MOCK_PROVIDER_KEY", "")
    if not expected or not hmac.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(401, "Invalid provider credential")
    max_tokens = min(int(body.get("max_tokens", 128)), 2048)
    words = [
        "Your",
        "request",
        "passed",
        "Cerbos",
        "authorization,",
        "model",
        "access",
        "checks,",
        "and",
        "atomic",
        "budget",
        "reservations.",
        "This",
        "deterministic",
        "demonstration",
        "uses",
        "LiteLLM",
        "without",
        "calling",
        "an",
        "external",
        "AI",
        "provider.",
    ]
    content = " ".join(words[:max_tokens])
    prompt_tokens = sum(len(m["content"].encode("utf-8")) + 16 for m in body["messages"]) + 32
    completion_tokens = min(len(words), max_tokens)
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    finish = "stop" if completion_tokens < max_tokens else "length"
    if body.get("stream"):
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        return StreamingResponse(
            stream(
                str(body.get("model") or "governed-demo"),
                words[:max_tokens],
                finish,
                usage,
                include_usage,
            ),
            media_type="text/event-stream",
        )
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": str(body.get("model") or "governed-demo"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": usage,
    }


def stream(model, words, finish, usage, include_usage):
    base = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
    }

    def event(choices, **extra):
        return f"data: {json.dumps({**base, 'choices': choices, **extra})}\n\n"

    yield event(
        [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]
    )
    for index, word in enumerate(words):
        time.sleep(0.01)  # Visible streaming, still fast.
        text = word if index == 0 else f" {word}"
        yield event([{"index": 0, "delta": {"content": text}, "finish_reason": None}])
    yield event([{"index": 0, "delta": {}, "finish_reason": finish}])
    if include_usage:
        yield event([], usage=usage)
    yield "data: [DONE]\n\n"
