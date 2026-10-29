# ВКР: AI baseline — лабораторная 3

Роль: **AI Engineer**. Генерация тем по профилю преподавателя, Mistral
`ministral-8b-2512`, структурированные ответы, трассировка и async API.
Продолжение `lab2-ai-engineer-design`, PR #6. Общая ветка `main` пока не содержит приложения.

## Быстрый запуск

Python 3.12. Команды выполнять из корня репозитория:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell вместо предыдущей команды:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements-ai.txt
cp .env.example .env
# В Windows вместо cp можно использовать Copy-Item .env.example .env
```

В `.env` задать `MISTRAL_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`
и адрес проекта `LANGFUSE_BASE_URL`. Для отладки на синтетических профилях
оставить `AI_TRACE_CONTENT=true`: prompts и ответы попадут в дашборд.
Ключи не отправлять в чат, не коммитить. С реальными данными по умолчанию
выключать запись содержимого и соблюдать ограниченный срок хранения трейсов.

Для локальной проверки без Langfuse явно установить `AI_TRACING_MODE=local`.
Этот режим пишет JSONL, но **не закрывает** требование приёмки о дашборде.

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Swagger: http://localhost:8000/docs, health: http://localhost:8000/health.
В Swagger вызвать `POST /api/generate/selected`:

```json
{"selections":[{"teacher_id":1,"count":2}],"focus":"автоматизация цикла ВКР"}
```

В профилях-примерах нет настоящих персональных данных. Темы сохраняются в
`var/ai.sqlite3`, результаты всегда `draft`. Новые реальные профили можно
подать JSON-файлом через `AI_PROFILE_PATH`; после смены уже загруженного
профиля нужен адаптер общей БД или новый локальный файл БД, seed не перезаписывает данные.

## Проверка и эксперименты

```bash
python -m pytest -q
python -m ml.experiments.run --mode mock --output docs/experiments/results/lab3-mock
python -m ml.experiments.run --mode live --output docs/experiments/results/lab3-live
```

Последняя команда обращается к платному API с ключом из `.env`.
Токены берутся из ответа провайдера; неизвестные значения остаются пустыми.
Содержимое mock-файлов — заранее заданные тестовые ответы, их задержки не являются
скоростью модели. В репозитории записан только mock-прогон.
Ноутбук: `notebooks/lab3-baseline.ipynb`. Выводы: `docs/experiments/lab3.md`.

## Границы и интеграция с Delivery / Quality

- Пути запросов взяты из `api/openapi.yaml` лабы 2.
- `backend/routers/ai.py` подключается через `include_router`; ему нужны
  `app.state.repo`, `app.state.baseline`, `app.state.generation_lock`.
- `backend/repository.py` — локальный SQLite-адаптер для автономного запуска
  AI-ветки. Общая PostgreSQL-модель и миграции остаются задачей Delivery.
- `teacher_name` здесь — техническая подпись по ID, контакты пустые. При
  интеграции Delivery подставляет отображаемые поля из общей БД.
- Все запросы набора валидируются заранее, темы сохраняются одной транзакцией.
  В случае сбоя остаётся пустой batch, без частично сохранённых тем.
- Проверка качества консервативная, lexical-only (25/50), без семантических
  embeddings; это зафиксированный долг относительно архитектуры лабы 2.
  Текущая эвристика не выдаёт темы за прошедшие экспертную проверку.
- `/api/evaluation/run` считает только явно названные локальные эвристики;
  без 50–100 реальных референсных тем вернёт 400. Это не заменяет evals Quality.
- `lab3-seed.jsonl` — синтетические входы, а не утверждённый golden dataset v2.
  Для приёмки Quality передаёт реальный датасет в `--dataset` с теми же полями.
- Retrieval не используется, поэтому retrieval-метрики — N/A.
- UI, публичный прод-URL, общий Compose и финальный eval-порог относятся
  к общей командной интеграции. Эта ветка не объявляет их выполненными.

## Перед приёмкой

1. Выполнить live-прогон на согласованном golden dataset.
2. Проверить в Langfuse prompt, ответ, usage, модель и каждую retry-попытку;
   `request_id` связывает CSV, JSONL и metadata наблюдения.
3. Добавить в отчёт реальные p50/p95 latency, токены, ошибки и ручные оценки.
4. Подключить основной embedding-режим и общий backend с Delivery.
5. После командного E2E и evals перевести draft PR в ready.
