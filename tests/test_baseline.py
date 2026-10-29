import asyncio
import json

import httpx
import pytest

from ml.models.baseline import Baseline, BaselineError, Profile
from ml.tracing import Tracer

TITLE = "Разработка информационной системы планирования учебных проектов с контролем сроков"


def response(teacher_id=1, titles=None, usage=True):
    data = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
        "teachers": [{"teacher_id": teacher_id, "titles": titles or [TITLE]}]})}}]}
    if usage:
        data["usage"] = {"prompt_tokens": 100, "completion_tokens": 25}
    return httpx.Response(200, json=data)


def execute(tmp_path, handler, *, attempts=3):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Baseline(client, Tracer("local", tmp_path / "trace.jsonl"),
                                  api_key="SECRET-TEST", max_attempts=attempts, sleep=no_sleep).generate(
                Profile(teacher_id=1, scientific_areas=["информационные системы"]), 1, None, "test")
    return asyncio.run(run())


async def no_sleep(_):
    pass


def test_success_and_redacted_trace(tmp_path):
    result = execute(tmp_path, lambda _: response())
    assert result.titles == [TITLE]
    assert result.prompt_tokens == 100
    text = (tmp_path / "trace.jsonl").read_text()
    assert "SECRET-TEST" not in text and TITLE not in text
    assert json.loads(text)["http_status"] == 200


def test_retry_each_attempt_traced(tmp_path):
    calls = []
    def handler(_):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "0"}) if len(calls) == 1 else response()
    result = execute(tmp_path, handler)
    assert result.attempts == 2
    assert result.prompt_tokens is None  # Unknown usage on rate limited attempt is not zero.
    assert len((tmp_path / "trace.jsonl").read_text().splitlines()) == 2


@pytest.mark.parametrize("invalid", [response(teacher_id=2), response(titles=["bad"]),
                                    response(titles=[TITLE, TITLE]), httpx.Response(200, json={})])
def test_invalid_output_fails_without_demo(tmp_path, invalid):
    with pytest.raises(BaselineError):
        execute(tmp_path, lambda _: invalid, attempts=2)
    assert len((tmp_path / "trace.jsonl").read_text().splitlines()) == 2


def test_auth_not_retried_or_leaked(tmp_path):
    with pytest.raises(BaselineError, match="401"):
        execute(tmp_path, lambda _: httpx.Response(401, text="SECRET-TEST"))
    text = (tmp_path / "trace.jsonl").read_text()
    assert len(text.splitlines()) == 1 and "SECRET-TEST" not in text


def test_timeout_bounded(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("SECRET-TEST", request=request)
    with pytest.raises(BaselineError):
        execute(tmp_path, handler)
    text = (tmp_path / "trace.jsonl").read_text()
    assert len(text.splitlines()) == 3 and "SECRET-TEST" not in text


def test_missing_key_no_network(tmp_path):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response())) as client:
            model = Baseline(client, Tracer("local", tmp_path / "trace"), api_key="")
            with pytest.raises(BaselineError, match="MISTRAL_API_KEY"):
                await model.generate(Profile(teacher_id=1, scientific_areas=["тест"]), 1, None, "x")
    asyncio.run(run())


def test_tracing_content_capture_opt_in(tmp_path):
    tracer = Tracer("local", tmp_path / "trace", capture=True)
    with tracer.attempt("x", "model", [{"role": "user", "content": "synthetic"}], 1, "v1") as span:
        span.output("answer")
    data = json.loads((tmp_path / "trace").read_text())
    assert data["output"] == "answer" and data["input"][0]["content"] == "synthetic"
