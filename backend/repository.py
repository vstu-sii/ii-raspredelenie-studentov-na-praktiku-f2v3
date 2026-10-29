"""Small SQLite adapter for an independently runnable AI branch.

Delivery can replace this adapter with the shared SQLAlchemy repository.
No teacher names or contacts are sent to the LLM.
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from ml.models.baseline import Profile


class Repository:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS teachers(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS topics(id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL,
                                             payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluations(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        ''')

    def seed(self, profiles):
        with self.db:
            for profile in profiles:
                self.db.execute("INSERT OR IGNORE INTO teachers VALUES (?, ?)",
                                (profile.teacher_id, profile.model_dump_json()))

    def profile(self, teacher_id):
        row = self.db.execute("SELECT payload FROM teachers WHERE id=?", (teacher_id,)).fetchone()
        return Profile.model_validate_json(row[0]) if row else None

    def history(self):
        titles = []
        for row in self.db.execute("SELECT payload FROM teachers"):
            titles.extend(Profile.model_validate_json(row[0]).past_topics)
        for row in self.db.execute("SELECT payload FROM topics"):
            titles.append(json.loads(row[0])["title"])
        return titles

    def reserve_batch(self):
        with self.db:
            return self.db.execute("INSERT INTO batches(created_at) VALUES (?)",
                                   (datetime.now(timezone.utc).isoformat(),)).lastrowid

    def save_topics(self, batch_id, topics):
        # Atomic commit: a provider error never leaves half a batch in storage.
        with self.db:
            for topic in topics:
                cursor = self.db.execute("INSERT INTO topics(batch_id,payload) VALUES (?,?)", (batch_id, "{}"))
                topic["id"] = cursor.lastrowid
                self.db.execute("UPDATE topics SET payload=? WHERE id=?",
                                (json.dumps(topic, ensure_ascii=False), topic["id"]))
        return topics

    def topic(self, topic_id):
        row = self.db.execute("SELECT payload FROM topics WHERE id=?", (topic_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def replace_topic(self, topic_id, topic):
        with self.db:
            self.db.execute("UPDATE topics SET payload=? WHERE id=?", (json.dumps(topic), topic_id))

    def batch(self, batch_id):
        if not self.db.execute("SELECT id FROM batches WHERE id=?", (batch_id,)).fetchone():
            return None
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM topics WHERE batch_id=?", (batch_id,))]

    def save_evaluation(self, result):
        with self.db:
            cursor = self.db.execute("INSERT INTO evaluations(payload) VALUES ('{}')")
            result["id"] = cursor.lastrowid
            self.db.execute("UPDATE evaluations SET payload=? WHERE id=?", (json.dumps(result), result["id"]))
        return result

    def close(self):
        self.db.close()
