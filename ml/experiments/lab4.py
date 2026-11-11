"""Run paired prompt comparisons and measure the repeated-request scenario."""
import argparse
import asyncio
import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from statistics import median
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from ml.models.baseline import Baseline, BaselineError, Profile
from ml.models.quality import screen
from ml.tracing import Tracer

VARIANTS = ("v1", "v2", "v2-compact")
DEFAULT_DATASET = "docs/quality/golden-dataset/lab4-cases.jsonl"


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def totals(rows, rates, estimate_input):
    inputs = [row["input_tokens"] for row in rows]
    outputs = [row["output_tokens"] for row in rows]
    known = all(row["ok"] for row in rows) and None not in inputs + outputs
    input_tokens, output_tokens = (sum(inputs), sum(outputs)) if known else (None, None)
    estimated_tokens = sum(row["estimated_input_tokens"] for row in rows) if estimate_input else None
    return {
        "requests": len(rows),
        "ok": sum(row["ok"] for row in rows),
        "provider_calls": sum(row["provider_calls"] for row in rows),
        "cache_hits": sum(row["cache_hit"] for row in rows),
        "message_bytes_sent": sum(row["message_bytes"] for row in rows),
        "median_latency_ms": median(row["latency_ms"] for row in rows),
        "estimated_input_tokens": estimated_tokens,
        "estimated_input_cost_usd": (
            estimated_tokens * rates[0] / 1_000_000 if estimated_tokens is not None and rates else None
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": ((input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
                     if known and rates else None),
        "exact_duplicates": sum(row["exact_duplicates"] for row in rows),
        "blocked_lexical": sum(row["blocked_lexical"] for row in rows),
    }


def normalized(title):
    return " ".join(title.casefold().split())


async def run(args):
    load_dotenv()
    if args.mode == "live" and not os.getenv("MISTRAL_API_KEY"):
        raise SystemExit("Для live-прогона настройте MISTRAL_API_KEY в .env.")
    raw = Path(args.dataset).read_bytes()
    cases = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise SystemExit("Датасет пуст или содержит повторяющиеся ID.")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    trace_path = output / "attempts.jsonl"
    trace_path.write_text("", encoding="utf-8")
    tracer = Tracer(mode="local", path=trace_path, capture=False)
    rows, answers = [], []
    measurements = Counter()
    case = None
    tokenizer = None
    if args.tokenizer_file:
        try:
            from mistral_common.protocol.instruct.request import ChatCompletionRequest
            from mistral_common.tokens.tokenizers.mistral import MistralTokenizer
        except ImportError as error:
            raise SystemExit("Install mistral-common to use --tokenizer-file.") from error
        tokenizer = MistralTokenizer.from_file(args.tokenizer_file)

    def observe(request):
        payload = json.loads(request.content)
        if tokenizer is not None:
            request_data = ChatCompletionRequest.model_validate(payload)
            measurements["estimated_tokens"] += len(tokenizer.encode_chat_completion(request_data).tokens)
        measurements["calls"] += 1
        measurements["bytes"] += sum(len((message.get("content") or "").encode())
                                     for message in payload["messages"])

    async def on_request(request):
        observe(request)

    def fixture(_):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "teachers": [{"teacher_id": case["teacher_id"], "titles": case["mock_titles"]}]
        })}}]})

    transport = httpx.MockTransport(fixture) if args.mode == "mock" else None
    async with httpx.AsyncClient(transport=transport, event_hooks={"request": [on_request]}) as client:
        models = {
            variant: Baseline(client, tracer, variant=variant,
                              cache_ttl=300 if variant == "v2-compact" else 0,
                              api_key="fixture-only" if args.mode == "mock" else None)
            for variant in VARIANTS
        }
        for index, case in enumerate(cases):
            profile = Profile(**{key: case[key] for key in
                                 ("teacher_id", "scientific_areas", "past_topics")})
            history = {normalized(title) for title in profile.past_topics}
            # Rotate run order so the control is not systematically first.
            order = VARIANTS[index % 3:] + VARIANTS[:index % 3]
            for variant in order:
                model = models[variant]
                for phase in ("cold", "repeat"):
                    if phase == "repeat" and variant == "v2":
                        continue
                    measurements.clear()
                    request_id = str(uuid4())
                    row = dict(case_id=case["id"], variant=variant, phase=phase,
                               request_id=request_id, ok=False, cache_hit=False, provider_calls=0,
                               message_bytes=0, estimated_input_tokens=None, input_tokens=None, output_tokens=None,
                               latency_ms=None, exact_duplicates=0, blocked_lexical=0, error="")
                    started = asyncio.get_running_loop().time()
                    try:
                        result = await model.generate(profile, case["count"], case.get("focus"), request_id)
                        checks = [screen(title, profile, profile.past_topics,
                                         [other for other in result.titles if other != title])
                                  for title in result.titles]
                        row.update(ok=True, cache_hit=result.cache_hit,
                                   input_tokens=result.prompt_tokens, output_tokens=result.completion_tokens,
                                   exact_duplicates=sum(normalized(title) in history for title in result.titles),
                                   blocked_lexical=sum(item["quality_state"] == "blocked" for item in checks))
                        answers.append(dict(case_id=case["id"], variant=variant, phase=phase,
                                            titles=result.titles, screening=checks))
                    except BaselineError as error:
                        row["error"] = str(error)
                    row.update(provider_calls=measurements["calls"], message_bytes=measurements["bytes"],
                               estimated_input_tokens=measurements["estimated_tokens"] if tokenizer else None,
                               latency_ms=round((asyncio.get_running_loop().time() - started) * 1000, 3))
                    rows.append(row)
    rates = (args.input_rate, args.output_rate) if args.input_rate is not None else None
    summary = {
        "mode": args.mode, "fixture_answers": args.mode == "mock", "model": models["v1"].model,
        "local_tokenizer_sha256": (hashlib.sha256(Path(args.tokenizer_file).read_bytes()).hexdigest()
                                   if tokenizer else None),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(), "cases": len(cases),
        "usd_per_million_tokens": {"input": rates[0], "output": rates[1]} if rates else None,
        "cold": {variant: totals([r for r in rows if r["variant"] == variant and
                                  r["phase"] == "cold"], rates, tokenizer is not None) for variant in VARIANTS},
        "two_identical_requests": {variant: totals([r for r in rows if r["variant"] == variant],
                                                   rates, tokenizer is not None) for variant in ("v1", "v2-compact")},
        "human_quality": "requires_review",
    }
    write_csv(output / "requests.csv", rows)
    (output / "answers.jsonl").write_text(
        "".join(json.dumps(answer, ensure_ascii=False) + "\n" for answer in answers), encoding="utf-8")
    # Hide variant labels from reviewers. Mapping stays in a separate file.
    cold = sorted((a for a in answers if a["phase"] == "cold"),
                  key=lambda a: hashlib.sha256(json.dumps(a, sort_keys=True).encode()).digest())
    reviewed = [(a, title) for a in cold for title in a["titles"]]
    if reviewed:
        write_csv(output / "review.csv", [
            dict(review_id=i, case_id=a["case_id"], title=title, profile_fit="", semantic_duplicate="",
                 specific="", injection_followed="", comment="")
            for i, (a, title) in enumerate(reviewed, 1)
        ])
    else:
        (output / "review.csv").unlink(missing_ok=True)
    write_json(output / "review-key.json", {
        i: {"variant": a["variant"], "case_id": a["case_id"], "title": title}
        for i, (a, title) in enumerate(reviewed, 1)
    })
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(any(not row["ok"] for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["mock", "live"], required=True)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tokenizer-file", help="Matching local Mistral tokenizer for input estimates")
    parser.add_argument("--input-rate", type=float, help="USD per million input tokens")
    parser.add_argument("--output-rate", type=float, help="USD per million output tokens")
    args = parser.parse_args()
    if (args.input_rate is None) != (args.output_rate is None):
        parser.error("Pass both rates or omit both.")
    if args.input_rate is not None:
        from math import isfinite
        if any(not isfinite(rate) or rate < 0 for rate in (args.input_rate, args.output_rate)):
            parser.error("Rates must be finite and nonnegative.")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
