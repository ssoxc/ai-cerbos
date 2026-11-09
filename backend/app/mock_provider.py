"""Deterministic OpenAI-compatible provider. This makes no external AI calls."""

import hmac
import os
import time
import uuid

from fastapi import FastAPI, Header, HTTPException

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
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": str(body.get("model") or "governed-demo"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop" if completion_tokens < max_tokens else "length",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
