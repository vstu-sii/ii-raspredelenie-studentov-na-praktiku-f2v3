
```markdown
# ВКР-трекер

Умная система сопровождения цикла выпускных квалификационных работ (ВКР) кафедры: сроки и напоминания, каталог тем, автоматическая сборка проекта приказа, рефчекер библиографии по ГОСТ Р 7.0.5-2008, LLM-ревью кода и нормоконтроль PDF.

[![CI](https://github.com/vstu-sii/ii-raspredelenie-studentov-na-praktiku-f2v3/actions/workflows/ci.yml/badge.svg)](https://github.com/vstu-sii/ii-raspredelenie-studentov-na-praktiku-f2v3/actions/workflows/ci.yml)

**Прод (hello-world):** https://vkr-red.vercel.app/


## Как поднять

    cp .env.example .env
    docker compose -f compose.dev.yml up --build

Приложение: http://localhost:8000 · Swagger: http://localhost:8000/docs

## Структура репозитория

- `app/` — код приложения (FastAPI)
- `public/` — статика прода (Vercel)
- `docs/` — документация (deploy, PRD, глоссарий и др.)
- `.github/workflows/` — CI
- `.github/PULL_REQUEST_TEMPLATE.md` — шаблон PR
- `compose.dev.yml` — dev-окружение одной командой
- `Dockerfile` — образ приложения
- `requirements.txt` — Python-зависимости

## Правила веток

- `main` — изменения только через PR с зелёным CI
- Имя ветки лабы строится по образцу lab1-delivery-initiation, lab1-product-vo-initiation
- Один PR на роль на лабу; доработки — коммитами в ту же ветку
```
