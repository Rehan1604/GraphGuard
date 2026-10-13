"""A small vector store kept in the app's own SQLite database (table rag_vectors).

Search is exact: one matrix multiplication against every stored vector of the right kind. That is perfectly fast for
hundreds or thousands of rows; at millions you would move to an approximate index (FAISS, pgvector).

Rows belong to a "space" (the embedder plus a fingerprint of the library). Vectors from different spaces are never
compared, and a changed library or embedder re-embeds automatically."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_vectors (
    id        TEXT PRIMARY KEY,         -- 'kb:<chunk id>' or 'case:<alert id>'
    kind      TEXT NOT NULL,            -- 'kb' (library passage) | 'case' (a reviewed past alert)
    rule      TEXT NOT NULL,            -- which alert rule it concerns, or 'general'
    source    TEXT NOT NULL,
    title     TEXT NOT NULL,
    section   TEXT NOT NULL,
    text      TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    space     TEXT NOT NULL,
    dim       INTEGER NOT NULL,
    vector    BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rag_kind ON rag_vectors(kind, space);
"""


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    rule: str
    source: str
    title: str
    section: str
    text: str  # what is shown to the reader
    embed_text: str  # what the embedder reads (title and section help it understand the passage)

    @property
    def text_hash(self) -> str:
        return hashlib.sha1((self.embed_text + "\x00" + self.text).encode()).hexdigest()


@dataclass(frozen=True)
class Hit:
    id: str
    rule: str
    source: str
    title: str
    section: str
    text: str
    score: float


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def sync(conn: sqlite3.Connection, kind: str, items: list[Item], embedder, space: str) -> int:
    """Make the stored rows of this kind match `items`. Only new, changed or other-space rows are embedded.
    Returns how many rows were (re)embedded."""
    ensure_schema(conn)
    have = {r["id"]: (r["text_hash"], r["space"]) for r in conn.execute("SELECT id, text_hash, space FROM rag_vectors WHERE kind = ?", (kind,))}
    todo = [i for i in items if have.get(i.id) != (i.text_hash, space)]
    if todo:
        vectors = embedder.embed_documents([i.embed_text for i in todo]).astype(np.float32)
        conn.executemany(
            """INSERT OR REPLACE INTO rag_vectors
               (id, kind, rule, source, title, section, text, text_hash, space, dim, vector)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(i.id, i.kind, i.rule, i.source, i.title, i.section, i.text, i.text_hash, space, vectors.shape[1], v.tobytes())
             for i, v in zip(todo, vectors)],
        )
    stale = set(have) - {i.id for i in items}
    if stale:
        conn.executemany("DELETE FROM rag_vectors WHERE id = ?", [(s,) for s in stale])
    if todo or stale:
        conn.commit()
    return len(todo)


def search(
    conn: sqlite3.Connection, query: np.ndarray, kind: str, space: str,
    rules: tuple[str, ...] | None = None, top_k: int = 4, min_score: float = 0.0, exclude: frozenset[str] = frozenset(),
) -> list[Hit]:
    ensure_schema(conn)
    sql = "SELECT * FROM rag_vectors WHERE kind = ? AND space = ?"
    params: list = [kind, space]
    if rules:
        sql += f" AND rule IN ({','.join('?' * len(rules))})"
        params += list(rules)
    rows = [r for r in conn.execute(sql, params).fetchall() if r["id"] not in exclude]
    if not rows:
        return []
    matrix = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    scores = matrix @ query.astype(np.float32)
    ranked = sorted(zip(rows, scores), key=lambda p: (-float(p[1]), p[0]["id"]))  # ties broken by id: deterministic
    return [
        Hit(r["id"], r["rule"], r["source"], r["title"], r["section"], r["text"], round(float(s), 4))
        for r, s in ranked[:top_k] if s >= min_score
    ]
