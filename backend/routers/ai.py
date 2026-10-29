"""Routes implement the Lab 2 paths; application wires repository and baseline."""
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.schemas import GenerateRequest, IntegrationRequest
from ml.models.baseline import Baseline, BaselineError, Profile
from ml.models.quality import screen

router = APIRouter(prefix="/api")


def profiles_for(body, repo):
    profiles = [repo.profile(selection.teacher_id) for selection in body.selections]
    if any(p is None for p in profiles):
        raise HTTPException(404, "Один из преподавателей не найден")
    return profiles


def topic_record(title, profile, generation, history, batch_titles):
    now = datetime.now(timezone.utc).isoformat()
    return {"id": 0, "teacher_id": profile.teacher_id,
            "teacher_name": f"Преподаватель {profile.teacher_id}", "teacher_contact": "",
            "title": title, "rationale": None, "generation_source": "mistral-ai",
            "generation_model": generation.model, "status": "draft", "manual_edit": False,
            "created_at": now, "updated_at": now,
            **screen(title, profile, history, batch_titles)}


async def generate_batch(body, request, profiles, batch_id, progress=None):
    repo, model = request.app.state.repo, request.app.state.baseline
    history, topics = repo.history(), []
    for index, (selection, profile) in enumerate(zip(body.selections, profiles), 1):
        generation = await model.generate(profile, selection.count, body.focus,
                                          f"batch-{batch_id}-{uuid4()}")
        for title in generation.titles:
            topics.append(topic_record(title, profile, generation, history,
                                       [t["title"] for t in topics]))
        if progress:
            await progress(index, len(topics))
    # Recheck all peers so duplicate status does not depend on generation order.
    for index, topic in enumerate(topics):
        profile = next(p for p in profiles if p.teacher_id == topic["teacher_id"])
        topic.update(screen(topic["title"], profile, history,
                            [t["title"] for j, t in enumerate(topics) if j != index]))
    repo.save_topics(batch_id, topics)
    return {"created": len(topics), "topics": topics, "batch_id": batch_id,
            "mode": "mistral-ai", "warning": "Lexical-only; требуется ручная проверка"}


@router.post("/generate/selected")
async def generate_selected(body: GenerateRequest, request: Request):
    profiles = profiles_for(body, request.app.state.repo)
    async with request.app.state.generation_lock:
        batch_id = request.app.state.repo.reserve_batch()
        try:
            return await generate_batch(body, request, profiles, batch_id)
        except BaselineError as error:
            raise HTTPException(503, str(error)) from error


@router.post("/generate/selected/stream")
async def generate_stream(body: GenerateRequest, request: Request):
    profiles = profiles_for(body, request.app.state.repo)

    async def stream():
        async with request.app.state.generation_lock:
            batch_id = request.app.state.repo.reserve_batch()
            state = {"batch_id": batch_id, "total": sum(s.count for s in body.selections),
                     "created": 0, "completed_groups": 0, "total_groups": len(profiles),
                     "stage": "generation"}
            def line(kind, **extra):
                return json.dumps({**state, "type": kind, **extra}, ensure_ascii=False) + "\n"
            yield line("start")
            queue = asyncio.Queue()
            async def progress(index, count):
                await queue.put((index, count))
            task = asyncio.create_task(generate_batch(body, request, profiles, batch_id, progress))
            try:
                while not task.done():
                    try:
                        index, count = await asyncio.wait_for(queue.get(), timeout=1)
                        state.update(completed_groups=index, created=count)
                        yield line("progress", message="Кандидаты сформированы; сохранение в конце набора")
                    except asyncio.TimeoutError:
                        yield line("heartbeat", message="Ожидаем ответ модели")
                result = await task
                state.update(created=result["created"], completed_groups=len(profiles), stage="done")
                yield line("final", mode=result["mode"], warning=result["warning"])
            except BaselineError as error:
                yield line("error", created=0, message=str(error))
            finally:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, BaselineError):
                    pass
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/topics/{topic_id}/regenerate")
async def regenerate(topic_id: int, request: Request):
    repo = request.app.state.repo
    async with request.app.state.generation_lock:
        old = repo.topic(topic_id)
        if not old:
            raise HTTPException(404, "Тема не найдена")
        profile = repo.profile(old["teacher_id"])
        try:
            generation = await request.app.state.baseline.generate(profile, 1, None, str(uuid4()))
        except BaselineError as error:
            raise HTTPException(503, str(error)) from error
        topic = topic_record(generation.titles[0], profile, generation, repo.history(), [])
        topic.update(id=topic_id, created_at=old["created_at"])
        repo.replace_topic(topic_id, topic)
        return topic


@router.post("/evaluation/run")
async def evaluate(request: Request, batch_id: int = Query(gt=0), reference_count: int = Query(80, ge=50, le=100)):
    repo = request.app.state.repo
    topics = repo.batch(batch_id)
    if topics is None:
        raise HTTPException(404, "Набор не найден")
    # Do not invent an expert reference corpus for this endpoint.
    references = list(dict.fromkeys(t for topic in topics
                                    for t in repo.profile(topic["teacher_id"]).past_topics))
    if not topics or len(references) < reference_count:
        raise HTTPException(400, "Недостаточно референсных тем для оценки; загрузите реальный корпус")
    from ml.models.quality import closest, words
    items = []
    for topic in topics:
        novelty = 100 - closest(topic["title"], references[:reference_count])[0]
        specificity = min(100, len(words(topic["title"])) * 8)
        practicality = 100 if "разработ" in topic["title"].casefold() else 0
        fit = topic["profile_relevance_score"]
        items.append({"topic_id": topic["id"], "title": topic["title"], "teacher_name": topic["teacher_name"],
                      "teacher_fit": fit, "specificity": specificity, "practicality": practicality,
                      "novelty": novelty, "overall": round((fit + specificity + practicality + novelty) / 4, 2)})
    return repo.save_evaluation({"batch_id": batch_id, "reference_count": reference_count,
                                "topic_count": len(topics), "mode": "local-heuristic-not-expert",
                                "metrics": {"mean_overall": sum(i["overall"] for i in items) / len(items)},
                                "items": items, "created_at": datetime.now(timezone.utc).isoformat()})


@router.post("/integrations/check/mistral")
async def check_mistral(request: Request, body: IntegrationRequest | None = None):
    base = request.app.state.baseline
    key = body.api_key if body and body.api_key is not None else base.api_key
    if not key:
        return {"status": "unconfigured", "message": "MISTRAL_API_KEY отсутствует"}
    try:
        probe = Baseline(base.client, base.tracer, api_key=key,
                         model=body.chat_model if body and body.chat_model else base.model, max_attempts=1)
        await probe.generate(Profile(teacher_id=1, scientific_areas=["информационные системы"]),
                             1, None, "integration-" + str(uuid4()))
        return {"status": "connected", "message": "Получен валидный structured output"}
    except (BaselineError, ValueError) as error:
        return {"status": "error", "message": str(error)}
