import sqlite3
import time


class Memory:
    """Local, private memory: durable facts the user (or the agent) wants kept."""

    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS facts ("
            "id INTEGER PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL)"
        )
        self._db.commit()

    def remember(self, text: str) -> None:
        self._db.execute("INSERT INTO facts (text, created) VALUES (?, ?)", (text, time.time()))
        self._db.commit()

    def recent(self, limit: int = 20) -> list[str]:
        rows = self._db.execute(
            "SELECT text FROM facts ORDER BY created DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r[0] for r in rows]
