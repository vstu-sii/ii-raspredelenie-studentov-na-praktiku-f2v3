"""Aggregate rubric annotations and cost projections for an archived Lab5 run."""
import argparse
import csv
import hashlib
import json
import subprocess
from decimal import Decimal
from pathlib import Path

from ml.models.quality import closest

DATASET = Path("docs/quality/golden-dataset/lab5-cases.jsonl")
RESULTS = Path("docs/experiments/results/lab5-local-ministral3b")
TARIFF_SOURCE = "https://docs.mistral.ai/inference/pricing"
FX_SOURCE = "https://www.cbr.ru/currency_base/daily/?UniDbQuery.Posted=True&UniDbQuery.To=14.11.2026"
USD_PER_MILLION = Decimal("0.10")
RUB_PER_USD = Decimal("82.1516")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def csv_rows(path):
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def json_lines(data):
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def cold_final(rows):
    return {
        row["case_id"]: row
        for row in rows
        if row["config"] == "final" and row["phase"] == "cold"
    }


def score(column, rows):
    labels = [row[column] for row in rows if row[column] != ""]
    if any(label not in {"0", "1"} for label in labels):
        raise ValueError(f"Invalid annotation in {column}")
    return {"positive": labels.count("1"), "total": len(labels)}


def report(folder, dataset):
    # Git may check out the same text blobs with CRLF on Windows.
    dataset = dataset.replace(b"\r\n", b"\n")
    summary = json.loads((folder / "summary.json").read_bytes())
    commit = subprocess.check_output(
        ["git", "rev-parse", f"{summary['tag']}^{{commit}}"], text=True
    ).strip()
    if summary["run_mode"] != "local" or summary["model"] != "ministral-3b-2512":
        raise ValueError("This projection is for the archived local Ministral 3B run.")
    if commit != summary["revision"] or sha256(dataset) != summary["dataset_sha256"]:
        raise ValueError("Run revision or dataset hash does not match the evidence.")
    cases = {case["id"]: case for case in json_lines(dataset)}
    answers = cold_final(json_lines((folder / "answers.jsonl").read_bytes()))
    requests = cold_final(csv_rows(folder / "requests.csv"))
    if set(cases) != set(answers) or set(cases) != set(requests):
        raise ValueError("Cold final run must cover every dataset case.")
    if any(row["valid"] != "True" for row in requests.values()):
        raise ValueError("Archived run contains an invalid cold response.")

    expected = {
        (case_id, index): title
        for case_id, answer in answers.items()
        for index, title in enumerate(answer["titles"], 1)
    }
    review_path = folder / "quality-review.csv"
    annotations = csv_rows(review_path)
    flagged_duplicates = 0
    for row in annotations:
        case_id, index = row["case_id"], int(row["title_index"])
        title = expected.pop((case_id, index), None)
        if title is None or sha256(title.encode()) != row["title_sha256"]:
            raise ValueError(f"Annotation does not match the archived title: {case_id}/{index}")
        if row["profile_match"] not in {"0", "1"} or row["semantic_duplicate"] not in {"0", "1"} or not row["reason"]:
            raise ValueError(f"Missing review data: {case_id}/{index}")
        if row["semantic_duplicate"] == "1":
            siblings = [text for position, text in enumerate(answers[case_id]["titles"], 1)
                        if position != index]
            similarity, _, _ = closest(title, cases[case_id]["past_topics"] + siblings)
            flagged_duplicates += similarity >= 25
    if expected:
        raise ValueError("Some archived titles are missing an annotation.")

    profile = score("profile_match", annotations)
    duplicates = score("semantic_duplicate", annotations)
    tokens = [int(row["input_tokens"]) + int(row["output_tokens"]) for row in requests.values()]
    cold = summary["results"]["final"]["cold"]
    if sum(tokens) != cold["input_tokens"] + cold["output_tokens"]:
        raise ValueError("Cold usage does not match the run summary.")
    rub_per_token = USD_PER_MILLION * RUB_PER_USD / 1_000_000
    return {
        "tag": summary["tag"],
        "revision": commit,
        "dataset_sha256": summary["dataset_sha256"],
        "review_sha256": sha256(review_path.read_bytes().replace(b"\r\n", b"\n")),
        "review_kind": "assistant_rubric",
        "quality": {
            "schema_valid_first_attempt": {
                "positive": sum(row["provider_calls"] == "1" for row in requests.values()),
                "total": len(cases),
            },
            "profile_match": profile,
            "focus_match_when_compatible": score("focus_match", annotations),
            "semantic_duplicate": duplicates,
            "semantic_duplicates_flagged_at_25": {
                "positive": flagged_duplicates, "total": duplicates["positive"]
            },
            "exact_duplicate_titles": cold["exact_duplicate_titles"],
            "canary_echo_cases": cold["canary_echo_cases"],
            "valid_canary_cases": cold["valid_canary_cases"],
        },
        "projected_cloud_cost": {
            "kind": "tariff_applied_to_local_usage",
            "api_model": summary["model"],
            "usd_per_million_input": str(USD_PER_MILLION),
            "usd_per_million_output": str(USD_PER_MILLION),
            "tariff_source": TARIFF_SOURCE,
            "rub_per_usd": str(RUB_PER_USD),
            "fx_source": FX_SOURCE,
            "sample_total_rub": str(sum(tokens) * rub_per_token),
            "sample_mean_rub": str(sum(tokens) * rub_per_token / len(tokens)),
            "sample_max_rub": str(max(tokens) * rub_per_token),
            "uc07_6000_in_2000_out_rub": str(8000 * rub_per_token),
            "actual_cloud_cost_rub": None,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    args = parser.parse_args()
    print(json.dumps(report(args.results, args.dataset.read_bytes()), indent=2))


if __name__ == "__main__":
    main()
