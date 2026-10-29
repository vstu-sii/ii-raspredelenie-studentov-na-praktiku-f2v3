# Трассировка LLM

Используется Langfuse Python SDK 4.18.0: `get_client()` и
`start_as_current_observation(as_type="generation")`.
Обёртка охватывает все вызовы baseline, включая проверку интеграции,
перегенерацию, эксперименты и каждую повторную HTTP-попытку.

Переменные окружения см. в `.env.example`. Обязательные для дашборда:
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`.
Ключ Mistral не входит в metadata. Исключения провайдера не записываются
как произвольный текст. В локальном JSONL — model, prompt_version,
request_id, attempt, http_status, latency_ms, известный token usage.

`AI_TRACE_CONTENT=true` включает prompt и ответ в SDK и JSONL. Это допустимо
для синтетических/обезличенных профилей; по умолчанию в коде — false.
В production не включать на полных текстах ВКР или контактных данных.

После запроса в дашборде Observations найти `vkr.baseline.attempt`,
отфильтровать по request_id из JSONL/CSV. При 429 должны быть видны
ошибочная попытка и последующая успешная. На завершении процесса выполняется flush.

`AI_TRACING_MODE=local` — только разработка, не дашборд.
Если выбран Langfuse без ключей, приложение не стартует с ложным сообщением
об успешной трассировке. Доставка в дашборд требует живой проверки;
наличие кода SDK само по себе её не подтверждает.

Документация: https://langfuse.com/docs/observability/sdk/overview
