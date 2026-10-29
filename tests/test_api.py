import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.repository import Repository
from ml.models.baseline import Baseline, Profile
from ml.models.quality import screen
from ml.tracing import Tracer
from tests.test_baseline import TITLE, no_sleep, response


@pytest.fixture
def setup(tmp_path):
    repo = Repository(tmp_path / "test.sqlite3")
    repo.seed([Profile(teacher_id=1, scientific_areas=["информационные системы"])])
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response()))
    model = Baseline(upstream, Tracer("local", tmp_path / "trace"), api_key="test", sleep=no_sleep)
    with TestClient(create_app(repo, model)) as client:
        yield client, repo, model
    repo.close()


def test_contract_and_persistence(setup):
    client, repo, _ = setup
    result = client.post("/api/generate/selected", json={"selections": [{"teacher_id": 1, "count": 1}]})
    assert result.status_code == 200
    data = result.json()
    assert data["created"] == 1
    topic = data["topics"][0]
    contract = yaml.safe_load(Path("api/openapi.yaml").read_text())
    assert set(contract["components"]["schemas"]["Topic"]["required"]) <= topic.keys()
    assert repo.topic(topic["id"])["title"] == TITLE
    assert topic["status"] == "draft"
    assert topic["similarity_method"] == "local-lexical"
    assert topic["quality_state"] == "review"
    assert datetime.fromisoformat(topic["created_at"])


@pytest.mark.parametrize("payload", [
    {"selections": []}, {"selections": [{"teacher_id": 1, "count": 0}]},
    {"selections": [{"teacher_id": 1, "count": 51}]},
    {"selections": [{"teacher_id": 1, "count": 1}] * 2},
    {"selections": [{"teacher_id": "1", "count": 1}]},
    {"selections": [{"teacher_id": 1, "count": 1}], "extra": "x"},
])
def test_bad_input(setup, payload):
    assert setup[0].post("/api/generate/selected", json=payload).status_code == 422


def test_not_found_before_call(setup):
    client, _, _ = setup
    assert client.post("/api/generate/selected", json={"selections": [{"teacher_id": 999, "count": 1}]}).status_code == 404


def test_stream_and_regeneration(setup):
    client, repo, _ = setup
    result = client.post("/api/generate/selected/stream", json={"selections": [{"teacher_id": 1, "count": 1}]})
    events = [json.loads(l) for l in result.text.splitlines()]
    assert events[0]["type"] == "start" and events[-1]["type"] == "final"
    topic = repo.batch(events[-1]["batch_id"])[0]
    regenerated = client.post(f'/api/topics/{topic["id"]}/regenerate')
    assert regenerated.status_code == 200 and regenerated.json()["id"] == topic["id"]
    assert client.post("/api/topics/999/regenerate").status_code == 404


def test_provider_failure_atomic(setup):
    client, repo, model = setup
    model.api_key = ""
    result = client.post("/api/generate/selected", json={"selections": [{"teacher_id": 1, "count": 1}]})
    assert result.status_code == 503 and repo.batch(1) == []
    events = [json.loads(l) for l in client.post("/api/generate/selected/stream", json={
        "selections": [{"teacher_id": 1, "count": 1}]}).text.splitlines()]
    assert events[-1]["type"] == "error" and repo.batch(2) == []


def test_evaluation_requires_real_references(setup):
    client, _, _ = setup
    client.post("/api/generate/selected", json={"selections": [{"teacher_id": 1, "count": 1}]})
    assert client.post("/api/evaluation/run?batch_id=1").status_code == 400
    assert client.post("/api/evaluation/run?batch_id=999").status_code == 404


def test_quality_exact_duplicate():
    profile = Profile(teacher_id=1, scientific_areas=["информационные системы"], past_topics=[TITLE])
    result = screen(TITLE, profile, [], [])
    assert result["similarity_method"] == "exact-duplicate" and result["quality_state"] == "blocked"


def test_integration_uses_same_baseline(setup):
    client, _, model = setup
    assert client.post("/api/integrations/check/mistral").json()["status"] == "connected"
    model.api_key = ""
    assert client.post("/api/integrations/check/mistral").json()["status"] == "unconfigured"
