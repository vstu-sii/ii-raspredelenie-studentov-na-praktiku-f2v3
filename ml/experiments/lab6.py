"""Rehearse AI demo cases through FastAPI and measure an injected provider outage."""
import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import subprocess
import time
from pathlib import Path
from statistics import median

import httpx

from backend.main import create_app
from backend.repository import Repository
from ml.experiments.lab4 import LocalInference
from ml.experiments.lab5 import WEIGHTS_SHA256
from ml.models.baseline import Baseline, OUTPUT_SCHEMA_VERSION, PROMPT_VERSION, Profile
from ml.models.focus import FOCUS_POLICY_VERSION
from ml.tracing import Tracer

CASES = Path("docs/demo/ai-cases.json")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stats(rows):
    times = sorted(row["latency_ms"] for row in rows)
    return {
        "requests": len(rows), "p50_ms": median(times),
        "p95_ms": times[math.ceil(.95 * len(times)) - 1], "max_ms": max(times),
    }


def payload(case):
    return {"selections": [{"teacher_id": case["teacher_id"], "count": case["count"]}],
            "focus": case.get("focus")}


async def run(args):
    revision = git("rev-parse", "HEAD")
    if args.tag:
        if git("rev-parse", f"{args.tag}^{{commit}}") != revision:
            raise ValueError("Check out the demo tag before generating evidence.")
        if git("status", "--porcelain", "--untracked-files=no"):
            raise ValueError("Tracked files must be clean when evaluating the demo tag.")
    if args.mode != "mock" and not args.tag:
        raise ValueError("Real generation requires --tag.")
    if args.mode == "local" and args.weights_sha256 != WEIGHTS_SHA256:
        raise ValueError("Verify and pass the pinned GGUF SHA-256.")
    if args.mode == "live" and not os.getenv("MISTRAL_API_KEY"):
        raise ValueError("Set MISTRAL_API_KEY locally before the live run.")
    cases_data = CASES.read_bytes().replace(b"\r\n", b"\n")
    cases = json.loads(cases_data)
    args.output.mkdir(parents=True, exist_ok=False)
    trace = args.output / "attempts.jsonl"
    rows, answers, failure_rows, snapshots = [], [], [], []
    fault = None
    calls = 0
    real = LocalInference() if args.mode == "local" else httpx.AsyncHTTPTransport()

    async def provider(request):
        nonlocal calls
        calls += 1
        if fault == "timeout":
            raise httpx.ReadTimeout("Injected demo timeout", request=request)
        if fault in {"503", "401"}:
            return httpx.Response(int(fault), json={"error": "Injected demo outage"})
        if args.mode == "mock":
            content = json.loads(request.content)
            data = json.loads(content["messages"][1]["content"])
            result = {"teachers": [{"teacher_id": data["teacher_id"], "titles": [
                f"Разработка учебного сервиса автоматизации процесса номер {i + 1}"
                for i in range(data["count"])]}]}
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            })
        return await real.handle_async_request(request)

    tracer = Tracer("local", trace, capture=False)
    async with real, httpx.AsyncClient(transport=httpx.MockTransport(provider)) as upstream:
        options = {"api_key": os.getenv("MISTRAL_API_KEY") if args.mode == "live" else "local-demo",
                   "model": os.getenv("MISTRAL_MODEL", "ministral-3b-2512") if args.mode == "live" else "ministral-3b-2512"}
        for round_index in range(1, args.rounds + 1):
            repo = Repository(":memory:")
            repo.seed([Profile(**{k: case[k] for k in ("teacher_id", "scientific_areas", "past_topics")})
                       for case in cases])
            model = Baseline(upstream, tracer, cache_ttl=900, **options)
            app = create_app(repo, model)
            try:
                async with app.router.lifespan_context(app), httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://demo"
                ) as client:
                    for case in cases:
                        request_body = payload(case)
                        before = calls
                        started = time.perf_counter()
                        response = await client.post("/api/generate/selected", json=request_body)
                        latency = round((time.perf_counter() - started) * 1000, 3)
                        response.raise_for_status()
                        result = response.json()
                        topics = result["topics"]
                        titles = [topic["title"] for topic in topics]
                        assert result["created"] == len(titles) == case["count"]
                        assert all(t["status"] == "draft" for t in topics)
                        assert [t["title"] for t in repo.batch(result["batch_id"])] == titles
                        marker = case.get("canary")
                        echoed = bool(marker and any(marker.casefold() in t.casefold() for t in titles))
                        assert not echoed
                        rows.append({"round": round_index, "case_id": case["id"],
                                     "latency_ms": latency, "status": response.status_code,
                                     "provider_calls": calls - before, "canary_echo": echoed})
                        answers.append({"round": round_index, "case_id": case["id"], "titles": titles})
                        if round_index == 1:
                            snapshots.append({"case_id": case["id"], "request": request_body,
                                              "titles": titles, "model": model.model})

                    fault = "503"
                    for case in cases:
                        before = calls
                        started = time.perf_counter()
                        response = await client.post("/api/generate/selected", json=payload(case))
                        latency = round((time.perf_counter() - started) * 1000, 3)
                        response.raise_for_status()
                        titles = [t["title"] for t in response.json()["topics"]]
                        cold = next(a["titles"] for a in answers if a["round"] == round_index
                                    and a["case_id"] == case["id"])
                        assert titles == cold and calls == before
                        failure_rows.append({"round": round_index, "scenario": "warm_cache_503",
                                             "case_id": case["id"], "status": 200,
                                             "provider_calls": 0, "latency_ms": latency,
                                             "result": "cached_draft"})

                    # Explicitly clear the in-process cache before each failure probe.
                    for failure in ("503", "timeout", "401"):
                        model.cache.entries.clear()
                        fault = failure
                        before = calls
                        started = time.perf_counter()
                        response = await client.post("/api/generate/selected", json=payload(cases[0]))
                        latency = round((time.perf_counter() - started) * 1000, 3)
                        expected_calls = 1 if failure == "401" else 3
                        assert response.status_code == 503 and calls - before == expected_calls
                        assert repo.batch(repo.db.execute("SELECT MAX(id) FROM batches").fetchone()[0]) == []
                        failure_rows.append({"round": round_index, "scenario": f"cold_{failure}",
                                             "case_id": cases[0]["id"], "status": 503,
                                             "provider_calls": calls - before, "latency_ms": latency,
                                             "result": "empty_batch"})
                    fault = "503"
                    response = await client.post("/api/generate/selected/stream", json=payload(cases[0]))
                    events = [json.loads(line) for line in response.text.splitlines()]
                    assert events[-1]["type"] == "error" and events[-1]["created"] == 0
                    assert repo.batch(events[-1]["batch_id"]) == []
                    failure_rows.append({"round": round_index, "scenario": "stream_503",
                                         "case_id": cases[0]["id"], "status": response.status_code,
                                         "provider_calls": 3, "latency_ms": None, "result": "error_event"})
                    fault = None
            finally:
                repo.close()

    attempts = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    usage = [event for event in attempts if event.get("http_status") == 200]
    summary = {
        "tag": args.tag, "revision": revision, "mode": args.mode,
        "is_model_benchmark": args.mode != "mock", "model": options["model"],
        "engine": args.engine_version, "weights_sha256": args.weights_sha256,
        "prompt_version": PROMPT_VERSION, "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "focus_policy_version": FOCUS_POLICY_VERSION, "cases_sha256": sha256(cases_data),
        "rounds": args.rounds, "cases": len(cases), "cold_api": stats(rows),
        "within_40s": sum(r["latency_ms"] <= 40_000 for r in rows),
        "per_case": {c["id"]: stats([r for r in rows if r["case_id"] == c["id"]]) for c in cases},
        "warm_outage": stats([r for r in failure_rows if r["scenario"] == "warm_cache_503"]),
        "failure_checks": len(failure_rows), "provider_attempts": len(attempts),
        "success_input_tokens": sum(e["prompt_tokens"] for e in usage),
        "success_output_tokens": sum(e["completion_tokens"] for e in usage),
        "scope": "FastAPI in-process + generator + SQLite; injected provider failures",
    }
    assert len(attempts) == calls
    for name, data in (("requests.csv", rows), ("failure-checks.csv", failure_rows)):
        with (args.output / name).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(data[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(data)
    write_json(args.output / "answers.json", answers)
    snapshot = {"source_tag": args.tag, "source_revision": revision,
                "is_model_benchmark": args.mode != "mock",
                "cases_sha256": summary["cases_sha256"], "cases": snapshots}
    write_json(args.output / "backup.json", snapshot)
    summary["backup_sha256"] = sha256((args.output / "backup.json").read_bytes().replace(b"\r\n", b"\n"))
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def replay(folder, case_id):
    """Read the explicitly selected archived answer, with integrity and provenance."""
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    raw = (folder / "backup.json").read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) != summary["backup_sha256"]:
        raise ValueError("Backup hash mismatch")
    snapshot = json.loads(raw)
    if (snapshot["source_revision"] != summary["revision"]
            or snapshot["source_tag"] != summary["tag"]
            or snapshot["cases_sha256"] != summary["cases_sha256"]):
        raise ValueError("Backup provenance mismatch")
    if sha256(CASES.read_bytes().replace(b"\r\n", b"\n")) != snapshot["cases_sha256"]:
        raise ValueError("Demo inputs differ from the recorded run")
    case = next(item for item in snapshot["cases"] if item["case_id"] == case_id)
    return {"mode": "recorded_demo", "message": "Показан сохранённый ответ прогона",
            "source_tag": snapshot["source_tag"], "source_revision": snapshot["source_revision"],
            "is_model_benchmark": snapshot["is_model_benchmark"], **case}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "live", "mock"))
    parser.add_argument("--tag")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--engine-version")
    parser.add_argument("--weights-sha256")
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--case")
    args = parser.parse_args()
    if args.replay:
        if not args.case:
            parser.error("--replay needs --case")
        print(json.dumps(replay(args.replay, args.case), ensure_ascii=False, indent=2))
        return
    if not args.mode or not args.output or not 3 <= args.rounds <= 10:
        parser.error("Set --mode, --output and 3..10 rounds.")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
