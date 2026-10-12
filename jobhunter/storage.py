"""Persistência local; cada operação abre sua própria conexão SQLite."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_COMPANY = {"name": "Bosch", "url": "https://careers.bosch.com/", "provider": "smartrecruiters", "identifier": "BoschGroup"}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL, identifier TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS searches (
                    id TEXT PRIMARY KEY, filters TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS favorites (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deliveries (
                    job_id TEXT NOT NULL, channel TEXT NOT NULL, PRIMARY KEY(job_id, channel));
                CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            db.execute("UPDATE searches SET status='interrupted' WHERE status='running'")
            if not db.execute("SELECT 1 FROM metadata WHERE name='initialized'").fetchone():
                if not db.execute("SELECT 1 FROM companies LIMIT 1").fetchone():
                    self.add_company(DEFAULT_COMPANY, db)
                db.execute("INSERT INTO metadata VALUES('initialized','true')")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def companies(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM companies ORDER BY name")]

    def add_company(self, company, connection=None):
        if connection is None:
            with self.connection() as db:
                return self.add_company(company, db)
        cursor = connection.execute("INSERT INTO companies(name,url,provider,identifier) VALUES(?,?,?,?)",
                                    tuple(company[key] for key in ("name", "url", "provider", "identifier")))
        return cursor.lastrowid

    def update_company(self, identifier, enabled=None, remove=False):
        with self.connection() as db:
            if remove:
                db.execute("DELETE FROM companies WHERE id=?", (identifier,))
            else:
                db.execute("UPDATE companies SET enabled=? WHERE id=?", (int(bool(enabled)), identifier))

    def start_search(self, identifier, filters):
        with self.connection() as db:
            db.execute("INSERT INTO searches(id,filters,status,created_at) VALUES(?,?,?,?)",
                       (identifier, json.dumps(filters), "running", datetime.now(timezone.utc).isoformat()))

    def finish_search(self, identifier, result, status="done"):
        with self.connection() as db:
            db.execute("UPDATE searches SET result=?,status=? WHERE id=?", (json.dumps(result), status, identifier))

    def search(self, identifier):
        with self.connection() as db:
            row = db.execute("SELECT * FROM searches WHERE id=?", (identifier,)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "status": row["status"], "filters": json.loads(row["filters"]),
                "created_at": row["created_at"], **json.loads(row["result"])}

    def recent_searches(self):
        with self.connection() as db:
            rows = db.execute("SELECT id,filters,status,created_at FROM searches ORDER BY created_at DESC LIMIT 20").fetchall()
        return [{**dict(row), "filters": json.loads(row["filters"])} for row in rows]

    def favorite(self, job, remove=False):
        with self.connection() as db:
            if remove:
                db.execute("DELETE FROM favorites WHERE id=?", (job["id"],))
            else:
                db.execute("INSERT OR REPLACE INTO favorites VALUES(?,?)", (job["id"], json.dumps(job)))

    def favorites(self):
        with self.connection() as db:
            return [json.loads(row["payload"]) for row in db.execute("SELECT payload FROM favorites")]

    def delivered(self, job_id, channel):
        with self.connection() as db:
            return bool(db.execute("SELECT 1 FROM deliveries WHERE job_id=? AND channel=?", (job_id, channel)).fetchone())

    def mark_delivered(self, ids, channel):
        with self.connection() as db:
            db.executemany("INSERT OR IGNORE INTO deliveries VALUES(?,?)", [(identifier, channel) for identifier in ids])
