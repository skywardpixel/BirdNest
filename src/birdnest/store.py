"""SQLite manifest backing dedupe and `birdnest list` (DESIGN.md 3)."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    tweet_id   TEXT NOT NULL,
    idx        INTEGER NOT NULL,
    author     TEXT,
    path       TEXT NOT NULL,
    sha256     TEXT,
    bytes      INTEGER,
    kind       TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tweet_id, idx)
);
"""


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with closing(self._conn()) as c:
            c.executescript(SCHEMA)
            c.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def existing(self, tweet_id: str, idx: int) -> sqlite3.Row | None:
        """A row only counts if the file is still on disk."""
        with closing(self._conn()) as c:
            row = c.execute(
                "SELECT * FROM media WHERE tweet_id=? AND idx=?", (tweet_id, idx)
            ).fetchone()
        if row and Path(row["path"]).exists():
            return row
        return None

    def record(self, *, tweet_id, idx, author, path: Path, kind, source_url) -> None:
        with closing(self._conn()) as c:
            c.execute(
                "INSERT OR REPLACE INTO media"
                " (tweet_id, idx, author, path, sha256, bytes, kind, source_url)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (tweet_id, idx, author, str(path), sha256_of(path),
                 path.stat().st_size, kind, source_url),
            )
            c.commit()

    def list(self, author: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        q = "SELECT * FROM media"
        args: list = []
        if author:
            q += " WHERE author = ?"
            args.append(author.lstrip("@"))
        q += " ORDER BY fetched_at DESC LIMIT ?"
        args.append(limit)
        with closing(self._conn()) as c:
            return list(c.execute(q, args))
