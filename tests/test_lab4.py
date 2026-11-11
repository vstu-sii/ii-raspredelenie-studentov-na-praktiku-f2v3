import asyncio
import json

import httpx
import pytest

from ml.models.baseline import Baseline, Profile
from ml.tools.history import dispatch
from ml.tracing import Tracer
from tests.test_baseline import response


def test_cache_isolated_by_profile_and_bypassed_on_regeneration(tmp_path):
    async def run():
        calls = []

        def handler(request):
            data = json.loads(request.content)
            payload = json.loads(data["messages"][1]["content"])
            calls.append(payload)
            return response(teacher_id=payload["teacher_id"])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = Baseline(client, Tracer("local", tmp_path / "trace"), api_key="mock",
                             variant="v2-compact", cache_ttl=60)
            profile = Profile(teacher_id=1, scientific_areas=["информационные системы"],
                              past_topics=[str(i) for i in range(12)])
            original = await model.generate(profile, 1, "вкр", "a")
            cached = await model.generate(profile, 1, "вкр", "b")
            assert cached.cache_hit and cached.prompt_tokens == cached.completion_tokens == 0
            assert cached.request_id == "b" and cached.titles == original.titles
            assert len(calls) == 1 and len(calls[0]["past_topics"]) == 6
            await model.generate(profile, 1, "вкр", "c", use_cache=False)
            await model.generate(profile.model_copy(update={"teacher_id": 2}), 1, "вкр", "d")
            await model.generate(profile, 1, "другой фокус", "e")
            assert [call["teacher_id"] for call in calls] == [1, 1, 2, 1]

    asyncio.run(run())


def call(teacher_id, limit=2):
    return {"id": "AbC123456", "type": "function", "function": {
        "name": "read_topic_history",
        "arguments": json.dumps({"teacher_id": teacher_id, "limit": limit}),
    }}


def test_tool_scope_validation_and_timeout():
    async def run():
        calls = 0

        async def read():
            nonlocal calls
            calls += 1
            await asyncio.sleep(2)
            return ["Старая тема"]

        assert (await dispatch(call(2), teacher_id=1, read=read))["status"] == "forbidden"
        assert (await dispatch(call(1, 7), teacher_id=1, read=read))["status"] == "invalid_arguments"
        assert calls == 0
        assert (await dispatch(call(1), teacher_id=1, read=read, timeout=0.01))["status"] == "timeout"
        assert calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("requested_id", [1, 99])
def test_real_tool_protocol_and_scoped_fallback(tmp_path, requested_id):
    async def run():
        requests = []

        def handler(request):
            data = json.loads(request.content)
            requests.append(data)
            if len(requests) == 1:
                assert data["tools"][0]["function"]["name"] == "read_topic_history"
                assert json.loads(data["messages"][1]["content"])["past_topics"] == []
                return httpx.Response(200, json={
                    "choices": [{"message": {"tool_calls": [call(requested_id)]}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                })
            assert "tools" not in data
            if requested_id == 1:
                tool = data["messages"][-1]
                assert tool["tool_call_id"] == "AbC123456"
                assert json.loads(tool["content"]) == {"status": "ok", "titles": ["Архивная тема"]}
            else:
                assert len(data["messages"]) == 2
                assert json.loads(data["messages"][1]["content"])["past_topics"] == ["Архивная тема"]
            return response()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = Baseline(client, Tracer("local", tmp_path / "trace"), api_key="mock",
                             variant="v2", history_tool=True)
            profile = Profile(teacher_id=1, scientific_areas=["информационные системы"],
                              past_topics=["Архивная тема"])
            result = await model.generate(profile, 1, None, "test")
            assert (result.prompt_tokens, result.completion_tokens) == (111, 32)
            assert len(requests) == 2

    asyncio.run(run())
