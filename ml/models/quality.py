"""Local, conservative screening. No retrieval and no LLM judge."""
import re


def words(text):
    return set(re.findall(r"[\w]+", text.casefold()))


def closest(title, references):
    best = (0.0, None, "none")
    for reference in references:
        a, b = words(title), words(reference)
        exact = " ".join(title.casefold().split()) == " ".join(reference.casefold().split())
        score = 100.0 if exact else round(100 * len(a & b) / max(1, len(a | b)), 2)
        if score > best[0]:
            best = (score, reference, "exact-duplicate" if exact else "local-lexical")
    return best


def screen(title, profile, history, batch_titles):
    teacher = closest(title, profile.past_topics)
    global_ = closest(title, history)
    batch = closest(title, batch_titles)
    peak = max([teacher, global_, batch], key=lambda item: item[0])
    matches = [a for a in profile.scientific_areas if words(a) & words(title)]
    reasons = ["Ручное подтверждение обязательно; lexical-only не доказывает отсутствие смысловых дублей"]
    if not matches:
        reasons.append("Лексическое совпадение с профилем не найдено")
    if len(words(title)) < 7:
        reasons.append("Слишком общая формулировка")
    if peak[0] >= 25:
        reasons.append("Возможный дубль по lexical-only шкале 25/50")
    return {
        "keywords": sorted(words(title))[:8],
        "profile_relevance_score": round(100 * len(matches) / len(profile.scientific_areas), 2),
        "matched_research_areas": matches, "profile_directions": profile.scientific_areas,
        "foreign_profile_directions": [], "profile_relevance_method": "lexical-overlap-heuristic",
        "similarity_score": peak[0], "closest_past_topic": peak[1],
        "similarity_method": peak[2] if peak[2] == "exact-duplicate" else "local-lexical",
        "teacher_similarity_score": teacher[0], "teacher_closest_topic": teacher[1],
        "teacher_similarity_method": teacher[2],
        "global_similarity_score": global_[0], "global_closest_topic": global_[1],
        "global_closest_teacher": None, "global_similarity_method": global_[2],
        "batch_similarity_score": batch[0], "batch_closest_topic": batch[1],
        "batch_closest_teacher": None, "batch_similarity_method": batch[2],
        "quality_state": "blocked" if peak[0] >= 50 else "review",
        "quality_reasons": reasons,
    }
