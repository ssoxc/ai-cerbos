"""LiteLLM's Cerbos guard (infra/cerbos_guard.py): how it bills normal and streamed answers.

LiteLLM is not installed here, so its CustomLogger base class is stubbed; every method
under test is the guard's own code. The ledger calls are recorded instead of sent.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_guard():
    stub = types.ModuleType("litellm.integrations.custom_logger")
    stub.CustomLogger = type("CustomLogger", (), {"__init__": lambda self: None})
    for name in ("litellm", "litellm.integrations"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["litellm.integrations.custom_logger"] = stub
    here = Path(__file__).resolve()
    path = next(
        p / "infra" / "cerbos_guard.py"
        for p in here.parents
        if (p / "infra" / "cerbos_guard.py").exists()
    )
    spec = importlib.util.spec_from_file_location("cerbos_guard_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard_module = load_guard()


@pytest.fixture
def guard():
    guard = guard_module.CerbosGuard()
    guard.calls = []

    async def ledger_call(reservation_id, action, body):
        guard.calls.append((action, body))
        return {"status": "settled", "actual_micros": 123} if action == "settle" else {}

    guard.ledger_call = ledger_call
    return guard


def request(stream=True):
    return {
        "model": "governed-demo",
        "max_tokens": 10,
        "stream": stream,
        "metadata": {
            "ledger": {"reservation_id": "r1", "reserved_micros": 900},
            "cerbos": {
                "requested_model": "governed-premium",
                "obligations": {"model": "governed-demo"},
                "data_classification": "internal",
            },
        },
    }


async def chunks(final_usage=True):
    yield SimpleNamespace(usage=None, text="Hello")
    yield SimpleNamespace(usage=None, text=" world")
    if final_usage:
        yield SimpleNamespace(usage={"prompt_tokens": 40, "completion_tokens": 2}, text="")


def test_a_stream_is_settled_from_its_final_usage_before_it_ends(guard):
    data = request()
    seen = []

    async def consume():
        async for chunk in guard.async_post_call_streaming_iterator_hook(None, chunks(), data):
            seen.append(chunk.text)
        seen.append("end")

    asyncio.run(consume())
    assert seen == ["Hello", " world", "", "end"]
    (action, body), *_ = guard.calls
    assert action == "settle"
    assert (body["input_tokens"], body["output_tokens"]) == (40, 2)
    assert body["answered_model"] == "governed-demo"
    assert body["requested_model"] == "governed-premium"
    assert len(guard.calls) == 1 and data["metadata"]["ledger"]["charged_micros"] == 123


def test_a_stream_that_stops_early_holds_the_funds(guard):
    data = request()

    async def consume_one():
        stream = guard.async_post_call_streaming_iterator_hook(None, chunks(), data)
        await anext(stream)
        await stream.aclose()  # The client went away mid-answer.
        await asyncio.gather(*guard.pending)

    asyncio.run(consume_one())
    assert [action for action, _ in guard.calls] == ["hold"]
    assert "stopped before it finished" in guard.calls[0][1]["reason"]


def test_a_stream_without_usage_is_held_not_released(guard):
    async def consume():
        async for _ in guard.async_post_call_streaming_iterator_hook(
            None, chunks(final_usage=False), request()
        ):
            pass

    asyncio.run(consume())
    assert [action for action, _ in guard.calls] == ["hold"]


def test_a_normal_answer_settles_once(guard):
    data = request(stream=False)
    response = SimpleNamespace(usage={"prompt_tokens": 40, "completion_tokens": 2})
    asyncio.run(guard.async_post_call_success_hook(data, None, response))
    asyncio.run(guard.async_post_call_success_hook(data, None, response))
    assert [action for action, _ in guard.calls] == ["settle"]


def test_the_success_hook_leaves_streams_to_the_stream_hook(guard):
    asyncio.run(guard.async_post_call_success_hook(request(), None, SimpleNamespace(usage=None)))
    assert guard.calls == []


@pytest.mark.parametrize(
    ("error", "action"),
    [
        (SimpleNamespace(status_code=400), "release"),
        (SimpleNamespace(status_code=500), "hold"),
        (type("ReadTimeout", (Exception,), {})(), "hold"),
    ],
)
def test_failures_release_only_when_nothing_was_done(guard, error, action):
    asyncio.run(guard.async_post_call_failure_hook(request(stream=False), error, None))
    assert [a for a, _ in guard.calls] == [action]


def test_streamed_requests_ask_for_usage_and_reserve(guard):
    async def check(principal, resources, action):
        return [
            {
                "actions": {"invoke": "EFFECT_ALLOW"},
                "outputs": [
                    {
                        "action": "invoke",
                        "src": "resource.model.vdefault#standard-for-every-key",
                        "val": {"effect": "allow", "reason": "ok"},
                    }
                ],
            }
        ]

    reserved = []

    async def reserve(key_id, data, classification):
        reserved.append((key_id, data["model"], data["max_tokens"]))
        return {"reservation_id": "r9", "amount_micros": 500}

    guard.check, guard.reserve = check, reserve
    data = {
        "model": "governed-demo",
        "max_tokens": 64,
        "stream": True,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    principal = {"id": "key:k1", "roles": ["api_key"], "attr": {}}
    asyncio.run(guard.authorize_model(principal, data))
    assert data["stream_options"] == {"include_usage": True}
    assert reserved == [("k1", "governed-demo", 64)]
    assert data["metadata"]["ledger"] == {"reservation_id": "r9", "reserved_micros": 500}
