-- ============================================================
-- ВКР-трекер (MVP) — схема данных
-- ADR-005: Postgres (Supabase — прод, compose — dev)
-- Соответствует UC-01..06 и ADR-002..005
-- ERD: docs/architecture/erd.puml
-- ============================================================

-- Справочник людей (единая таблица, роль определяется связями)
CREATE TABLE people (
    id          SERIAL PRIMARY KEY,
    full_name   TEXT NOT NULL,
    email       TEXT UNIQUE,
    telegram    TEXT,
    is_deputy   BOOLEAN NOT NULL DEFAULT FALSE,
    is_secretary BOOLEAN NOT NULL DEFAULT FALSE,
    is_teacher  BOOLEAN NOT NULL DEFAULT FALSE,
    is_student  BOOLEAN NOT NULL DEFAULT FALSE
);

-- Цикл ВКР (UC-01): годовой проход с окнами регламента
CREATE TABLE cycles (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,              -- «Цикл 2026/27»
    started_on  DATE NOT NULL,
    ends_on     DATE NOT NULL,
    created_by  INTEGER NOT NULL REFERENCES people(id)
);

-- Окна регламента этапов цикла (UC-01): правка дат = пересчёт напоминаний
CREATE TABLE stage_windows (
    id          SERIAL PRIMARY KEY,
    cycle_id    INTEGER NOT NULL REFERENCES cycles(id),
    stage       TEXT NOT NULL CHECK (stage IN
                ('catalog', 'pairs', 'order', 'sources',
                 'screening1', 'screening2', 'predefense')),
    opens_on    DATE NOT NULL,
    closes_on   DATE NOT NULL,
    CHECK (closes_on > opens_on),
    UNIQUE (cycle_id, stage)
);

-- Темы каталога (UC-02): без фамилий студентов
CREATE TABLE topics (
    id          SERIAL PRIMARY KEY,
    cycle_id    INTEGER NOT NULL REFERENCES cycles(id),
    teacher_id  INTEGER NOT NULL REFERENCES people(id),
    title       TEXT NOT NULL,
    carried_over BOOLEAN NOT NULL DEFAULT FALSE,  -- перенесена из прошлого цикла
    status      TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published', 'approved', 'archived')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Пары «студент — тема» (UC-03): подача из карточки темы
CREATE TABLE pairs (
    id          SERIAL PRIMARY KEY,
    topic_id    INTEGER NOT NULL UNIQUE REFERENCES topics(id),
    student_id  INTEGER NOT NULL REFERENCES people(id),
    final_title TEXT NOT NULL,              -- итоговая формулировка для диплома
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Проект приказа и приказ (UC-03)
CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,
    cycle_id    INTEGER NOT NULL REFERENCES cycles(id),
    draft       JSONB NOT NULL,             -- собранные строки: темы, руководители, шифры
    sent_at     TIMESTAMPTZ,
    rectorate_reply TEXT CHECK (rectorate_reply IN
                ('signed', 'remarks')),
    remarks     TEXT,
    published_at TIMESTAMPTZ
);

-- Строки приказа: связь пары с приказом + шифр ВКР
CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    pair_id     INTEGER NOT NULL REFERENCES pairs(id),
    topic_code  TEXT NOT NULL               -- шифр ВКР
);

-- Источники студента (UC-04): идентификатор -> ГОСТ-строка
CREATE TABLE sources (
    id          SERIAL PRIMARY KEY,
    student_id  INTEGER NOT NULL REFERENCES people(id),
    cycle_id    INTEGER NOT NULL REFERENCES cycles(id),
    identifier  TEXT NOT NULL,              -- DOI / ISBN / URL
    gost_string TEXT NOT NULL,              -- готовое описание по ГОСТ Р 7.0.5-2008
    is_foreign  BOOLEAN NOT NULL DEFAULT FALSE,
    origin      TEXT NOT NULL DEFAULT 'auto'
                CHECK (origin IN ('auto', 'manual')),  -- auto: метаданные найдены
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Кэш метаданных (ADR-003): «вечный кэш», повторный DOI не ходит наружу
CREATE TABLE meta_cache (
    identifier  TEXT PRIMARY KEY,           -- DOI / ISBN / URL
    metadata    JSONB NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Просмотры (UC-05): два рецензента, не руководитель студента
CREATE TABLE screenings (
    id          SERIAL PRIMARY KEY,
    cycle_id    INTEGER NOT NULL REFERENCES cycles(id),
    stage       TEXT NOT NULL CHECK (stage IN ('screening1', 'screening2')),
    student_id  INTEGER NOT NULL REFERENCES people(id),
    reviewer_id INTEGER NOT NULL REFERENCES people(id),
    grade       INTEGER CHECK (grade BETWEEN 2 AND 5),
    comment     TEXT,
    contact     TEXT,                        -- контакт для консультации
    graded_at   TIMESTAMPTZ,
    UNIQUE (stage, student_id, reviewer_id)
);

-- Очередь уведомлений (ADR-004): таблица вместо брокера
CREATE TABLE notifications (
    id          SERIAL PRIMARY KEY,
    cycle_id    INTEGER REFERENCES cycles(id),
    recipient_id INTEGER NOT NULL REFERENCES people(id),
    channel     TEXT NOT NULL CHECK (channel IN ('email', 'messenger')),
    payload     JSONB NOT NULL,              -- текст, событие, ссылки
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'sent', 'failed')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at     TIMESTAMPTZ
);

-- Статусы этапов по студентам: данные дашборда UC-06 и North Star
CREATE TABLE stage_status (
    id          SERIAL PRIMARY KEY,
    cycle_id    INTEGER NOT NULL REFERENCES cycles(id),
    student_id  INTEGER NOT NULL REFERENCES people(id),
    stage       TEXT NOT NULL CHECK (stage IN
                ('catalog', 'pairs', 'order', 'sources',
                 'screening1', 'screening2', 'predefense')),
    state       TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'in_window', 'done_on_time',
                                 'done_late', 'overdue')),
    -- Задел под веху 2 (ADR-005): ссылки на артефакты этапа (PDF, архив кода)
    artifact_url TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cycle_id, student_id, stage)
);

-- Индексы под дашборд (UC-06) и воркеры очереди (ADR-004)
CREATE INDEX idx_stage_status_cycle ON stage_status (cycle_id, stage, state);
CREATE INDEX idx_notifications_pending ON notifications (status, created_at);