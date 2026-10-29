"""python -m ml.experiments.run --mode live|mock --output <directory>"""
import argparse
import asyncio
import csv
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from ml.models.baseline import Baseline, BaselineError, Profile, PROMPT_VERSION
from ml.models.quality import screen
from ml.tracing import Tracer


async def run(args):
    load_dotenv()
    dataset = Path(args.dataset)
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    tracer = Tracer(mode="local", path=output / "attempts.jsonl", capture=False) if args.mode == "mock" else Tracer()
    rows, answers = [], []
    for case in cases:
        def fixture(request):
            data = {"teachers": [{"teacher_id": case["teacher_id"], "titles": case["mock_titles"]}]}
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(data, ensure_ascii=False)}}]})
        transport = httpx.MockTransport(fixture) if args.mode == "mock" else None
        async with httpx.AsyncClient(transport=transport) as client:
            model = Baseline(client, tracer, api_key="mock-only" if args.mode == "mock" else None)
            profile = Profile.model_validate({k: case[k] for k in ["teacher_id", "scientific_areas", "past_topics"]})
            row = {"case_id": case["id"], "mode": args.mode, "model": model.model,
                   "prompt_version": PROMPT_VERSION, "request_id": str(uuid4()),
                   "status": "error", "latency_ms": None, "prompt_tokens": None,
                   "completion_tokens": None, "attempts": None, "requested": case["count"], "returned": 0}
            started = time.perf_counter()
            try:
                result = await model.generate(profile, case["count"], case.get("focus"), row["request_id"])
                row.update(status="ok", latency_ms=result.latency_ms, prompt_tokens=result.prompt_tokens,
                           completion_tokens=result.completion_tokens, attempts=result.attempts,
                           returned=len(result.titles))
                answers.append({"case_id": case["id"], "mode": args.mode,
                                "generation_source": "fixture" if args.mode == "mock" else "mistral-ai",
                                "titles": result.titles,
                                "screening": [screen(t, profile, profile.past_topics,
                                    [other for other in result.titles if other != t]) for t in result.titles]})
            except BaselineError as error:
                row.update(error=str(error), latency_ms=round((time.perf_counter() - started) * 1000, 2))
            rows.append(row)
    tracer.flush()
    fields = list(rows[0]) + (["error"] if any("error" in r for r in rows) else [])
    with (output / "requests.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (output / "answers.jsonl").write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in answers), encoding="utf-8")
    latencies = sorted(r["latency_ms"] for r in rows if r["status"] == "ok")
    summary = {"mode": args.mode, "is_model_benchmark": args.mode == "live",
               "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
               "cases": len(rows), "successful": len(latencies),
               "success_rate": len(latencies) / len(rows),
               "latency_p50_ms": latencies[(len(latencies) - 1) // 2] if latencies else None,
               "latency_max_ms": max(latencies) if latencies else None,
               "tokens_known": all(r["prompt_tokens"] is not None for r in rows),
               "retrieval_metrics": None, "retrieval_reason": "No retrieval in Lab 2 baseline",
               "human_acceptance": None, "model": rows[0]["model"], "prompt_version": PROMPT_VERSION}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if any(r["status"] != "ok" for r in rows):
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["live", "mock"])
    parser.add_argument("--dataset", default="docs/quality/golden-dataset/lab3-seed.jsonl")
    parser.add_argument("--output", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
