"""Summarize completed blind reviews of generated Lab 4 answers."""
import argparse
import csv
import json
from pathlib import Path

from ml.experiments.lab4 import VARIANTS, write_json

METRICS = ("profile_fit", "semantic_duplicate", "specific", "injection_followed")


def score(rows, key):
    scores = {variant: dict(titles=0, **dict.fromkeys(METRICS, 0)) for variant in VARIANTS}
    for row in rows:
        group = scores[key[row["review_id"]]["variant"]]
        group["titles"] += 1
        for metric in METRICS:
            group[metric] += int(row[metric])
    for group in scores.values():
        group["rates"] = {
            metric: group[metric] / group["titles"] if group["titles"] else None
            for metric in METRICS
        }
    return scores


def summarize(path):
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    if summary["mode"] not in {"live", "local"} or summary["fixture_answers"]:
        raise ValueError("Оценка качества требует ответов реальной модели.")
    key = json.loads((path / "review-key.json").read_text(encoding="utf-8"))
    with (path / "review.csv").open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != len(key) or {row["review_id"] for row in rows} != set(key):
        raise ValueError("Набор review_id отличается от исходного.")
    for row in rows:
        entry = key[row["review_id"]]
        if any(entry[field] != row[field] for field in ("case_id", "title")):
            raise ValueError("Текст темы или ID кейса изменился.")
        if any(row[metric] not in {"0", "1"} for metric in METRICS):
            raise ValueError("Каждая оценка должна быть 0 или 1.")
    with (path / "requests.csv").open(encoding="utf-8", newline="") as source:
        cold = [row for row in csv.DictReader(source) if row["phase"] == "cold"]
    successful = {(row["case_id"], row["variant"]) for row in cold if row["ok"] == "True"}
    cases = {row["case_id"] for row in cold}
    comparisons = {}
    for left, right in (("v1", "v2"), ("v2", "v2-compact")):
        paired = sorted(case for case in cases if {(case, left), (case, right)} <= successful)
        paired_scores = score([row for row in rows if row["case_id"] in paired], key)
        comparisons[f"{left} vs {right}"] = {
            "case_ids": paired,
            "scores": {variant: paired_scores[variant] for variant in (left, right)},
        }
    return {
        "valid_cold_requests": {
            variant: {k: summary["cold"][variant][k] for k in ("ok", "requests")}
            for variant in VARIANTS
        },
        "all_valid_answers": score(rows, key),
        "paired": comparisons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        scores = summarize(args.output)
    except ValueError as error:
        parser.error(str(error))
    write_json(args.output / "review-summary.json", scores)
    print(json.dumps(scores, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
