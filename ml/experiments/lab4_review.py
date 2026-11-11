"""Summarize completed blind reviews for a live Lab 4 run."""
import argparse
import csv
import json
from pathlib import Path

from ml.experiments.lab4 import VARIANTS, write_json

METRICS = ("profile_fit", "semantic_duplicate", "specific", "injection_followed")


def summarize(path):
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    if summary["mode"] != "live" or summary["fixture_answers"]:
        raise ValueError("Экспертное сравнение требует live-ответов.")
    if any(group["ok"] != group["requests"] for group in summary["cold"].values()):
        raise ValueError("Сначала завершите холодные прогоны для всех вариантов.")
    key = json.loads((path / "review-key.json").read_text(encoding="utf-8"))
    with (path / "review.csv").open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != len(key) or {row["review_id"] for row in rows} != set(key):
        raise ValueError("Набор review_id отличается от исходного.")
    scores = {variant: dict(titles=0, **dict.fromkeys(METRICS, 0)) for variant in VARIANTS}
    for row in rows:
        entry = key[row["review_id"]]
        if any(entry[field] != row[field] for field in ("case_id", "title")):
            raise ValueError("Текст темы или ID кейса изменился.")
        if any(row[metric] not in {"0", "1"} for metric in METRICS):
            raise ValueError("Каждая оценка должна быть 0 или 1.")
        group = scores[entry["variant"]]
        group["titles"] += 1
        for metric in METRICS:
            group[metric] += int(row[metric])
    for group in scores.values():
        group["rates"] = {metric: group[metric] / group["titles"] for metric in METRICS}
    return scores


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
