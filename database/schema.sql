-- Lab 2 / VKR Topic Generator: reference PostgreSQL schema (V35)
-- Source: backend/app/models.py in vkr-topic-generator-site-v35-stable-export.
-- Design artifact, NOT an Alembic migration: do not execute on an existing database.
-- Application-side Python defaults are applied by SQLAlchemy; SQL defaults are not added here.
-- The same ORM also supports SQLite; this DDL targets PostgreSQL.
-- Secret values (API keys, service account JSON) are not included.

BEGIN;

CREATE TABLE app_settings (
	id INTEGER NOT NULL, 
	mistral_api_key TEXT, 
	mistral_chat_model VARCHAR(255), 
	mistral_embedding_model VARCHAR(255), 
	google_service_account_json TEXT, 
	google_share_with_email VARCHAR(255), 
	google_spreadsheet_id VARCHAR(255), 
	default_topic_count INTEGER NOT NULL, 
	default_generation_focus TEXT, 
	similarity_green_max FLOAT NOT NULL, 
	similarity_yellow_max FLOAT NOT NULL, 
	similarity_calibrated BOOLEAN NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE generation_batches (
	id SERIAL NOT NULL, 
	focus TEXT, 
	selections JSON NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_generation_batches_created_at ON generation_batches (created_at);

CREATE TABLE similarity_calibration_pairs (
	id SERIAL NOT NULL, 
	left_title TEXT NOT NULL, 
	right_title TEXT NOT NULL, 
	similarity_score FLOAT NOT NULL, 
	similarity_method VARCHAR(50) NOT NULL, 
	label VARCHAR(20), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_similarity_calibration_pairs_created_at ON similarity_calibration_pairs (created_at);

CREATE TABLE teachers (
	id SERIAL NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	topic_count INTEGER NOT NULL, 
	department VARCHAR(255), 
	position VARCHAR(255), 
	email VARCHAR(255), 
	telegram VARCHAR(255), 
	phone VARCHAR(100), 
	research_areas JSON NOT NULL, 
	orcid VARCHAR(100), 
	scopus_id VARCHAR(100), 
	courses JSON NOT NULL, 
	technologies JSON NOT NULL, 
	publications JSON NOT NULL, 
	openalex_id VARCHAR(100), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_teachers_full_name ON teachers (full_name);

CREATE TABLE past_topics (
	id SERIAL NOT NULL, 
	teacher_id INTEGER NOT NULL, 
	title TEXT NOT NULL, 
	year INTEGER, 
	source_file VARCHAR(255), 
	source_sheet VARCHAR(255), 
	source_row INTEGER, 
	source_project VARCHAR(100), 
	is_reference BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(teacher_id) REFERENCES teachers (id) ON DELETE CASCADE
);

CREATE INDEX ix_past_topics_is_reference ON past_topics (is_reference);
CREATE INDEX ix_past_topics_teacher_id ON past_topics (teacher_id);

CREATE TABLE quality_evaluation_runs (
	id SERIAL NOT NULL, 
	batch_id INTEGER NOT NULL, 
	reference_count INTEGER NOT NULL, 
	topic_count INTEGER NOT NULL, 
	mode VARCHAR(50) NOT NULL, 
	metrics JSON NOT NULL, 
	items JSON NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(batch_id) REFERENCES generation_batches (id) ON DELETE CASCADE
);

CREATE INDEX ix_quality_evaluation_runs_batch_id ON quality_evaluation_runs (batch_id);
CREATE INDEX ix_quality_evaluation_runs_created_at ON quality_evaluation_runs (created_at);

CREATE TABLE generated_topics (
	id SERIAL NOT NULL, 
	teacher_id INTEGER NOT NULL, 
	title TEXT NOT NULL, 
	rationale TEXT, 
	keywords JSON NOT NULL, 
	generation_source VARCHAR(32) NOT NULL, 
	generation_model VARCHAR(255), 
	profile_relevance_score FLOAT, 
	matched_research_areas JSON NOT NULL, 
	profile_directions JSON NOT NULL, 
	foreign_profile_directions JSON NOT NULL, 
	profile_relevance_method VARCHAR(80), 
	similarity_score FLOAT NOT NULL, 
	closest_past_topic TEXT, 
	teacher_similarity_score FLOAT NOT NULL, 
	teacher_closest_topic TEXT, 
	global_similarity_score FLOAT NOT NULL, 
	global_closest_topic TEXT, 
	global_closest_teacher VARCHAR(255), 
	batch_similarity_score FLOAT NOT NULL, 
	batch_closest_topic TEXT, 
	batch_closest_teacher VARCHAR(255), 
	similarity_method VARCHAR(50) NOT NULL, 
	teacher_similarity_method VARCHAR(50) NOT NULL, 
	global_similarity_method VARCHAR(50) NOT NULL, 
	batch_similarity_method VARCHAR(50) NOT NULL, 
	source_past_topic_id INTEGER, 
	status VARCHAR(32) NOT NULL, 
	manual_edit BOOLEAN NOT NULL, 
	generation_index INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(teacher_id) REFERENCES teachers (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_past_topic_id) REFERENCES past_topics (id) ON DELETE SET NULL
);

CREATE INDEX ix_generated_topics_source_past_topic_id ON generated_topics (source_past_topic_id);
CREATE INDEX ix_generated_topics_status ON generated_topics (status);
CREATE INDEX ix_generated_topics_teacher_id ON generated_topics (teacher_id);

CREATE TABLE generation_batch_topics (
	batch_id INTEGER NOT NULL, 
	topic_id INTEGER NOT NULL, 
	PRIMARY KEY (batch_id, topic_id), 
	FOREIGN KEY(batch_id) REFERENCES generation_batches (id) ON DELETE CASCADE, 
	UNIQUE (topic_id), 
	FOREIGN KEY(topic_id) REFERENCES generated_topics (id) ON DELETE CASCADE
);

COMMIT;
