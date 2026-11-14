"""One small document store on SQLite. Collections hold JSON documents in insertion order."""
import json
import sqlite3
import threading
from pathlib import Path

from pydantic import BaseModel

from . import config

COLLECTIONS = [
    "events",
    "facts",
    "record",
    "waiting",
    "flags",
    "diffs",
    "proposals",
    "decisions",
    "outbox",
    "answers",
    "checks",
    "plan",
    "project",
    "rules",
]


class Store:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS docs ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, collection TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, "
            "UNIQUE (collection, id))"
        )
        self._db.commit()

    def put(self, collection: str, doc_id: str, body: BaseModel | dict) -> None:
        text = body.model_dump_json() if isinstance(body, BaseModel) else json.dumps(body)
        with self._lock:
            self._db.execute(
                "INSERT INTO docs (collection, id, body) VALUES (?, ?, ?) "
                "ON CONFLICT (collection, id) DO UPDATE SET body = excluded.body",
                (collection, doc_id, text),
            )
            self._db.commit()

    def get(self, collection: str, doc_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT body FROM docs WHERE collection = ? AND id = ?", (collection, doc_id)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, collection: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT body FROM docs WHERE collection = ? ORDER BY seq", (collection,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def delete(self, collection: str, doc_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM docs WHERE collection = ? AND id = ?", (collection, doc_id))
            self._db.commit()

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM docs")
            self._db.commit()


_store: Store | None = None
_stores: dict[Path, Store] = {}
_stores_lock = threading.Lock()


def store() -> Store:
    global _store
    path = (config.data_dir() / "aurora.sqlite").resolve()
    with _stores_lock:
        # Existing callers reset the singleton between runs. Keep that reset contract.
        if _store is None:
            _stores.clear()
        if path not in _stores:
            _stores[path] = Store(path)
        _store = _stores[path]
        return _store
