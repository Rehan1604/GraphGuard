"""The retriever: finds guidance passages AND similar past cases for an alert, by meaning.

Two kinds of memory are searched:
  * the guidance library (markdown notes written for this project), and
  * "case memory": alerts that analysts in THIS workspace already dismissed or escalated, with their comments.
    That is the part that makes the assistant learn from your own team's decisions."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings
from app.rag import vectorstore as vs
from app.rag.chunking import Chunk, load_chunks
from app.rag.embeddings import Embedder, build_embedder
from app.rag.lexical import CORE_SECTIONS

RULE_LABELS = {"pass_through_chain": "Pass-through chain", "cycle": "Circular flow", "burst": "Transfer burst", "fan": "Many counterparties"}


@dataclass(frozen=True)
class CaseHit:
    alert_id: int
    rule: str
    status: str
    summary: str
    comment: str
    score: float


class Retriever:
    def __init__(self, chunks: list[Chunk], embedder: Embedder, note: str):
        self.chunks = chunks
        self.embedder = embedder
        self.note = note
        fingerprint = hashlib.sha1("".join(sorted(c.id + c.index_text for c in chunks)).encode()).hexdigest()[:10]
        self.space = f"{embedder.name}|{fingerprint}"
        self._by_id = {c.id: c for c in chunks}
        self._lock = threading.Lock()

    # --- guidance library ----------------------------------------------------------------------
    def _kb_items(self) -> list[vs.Item]:
        return [
            vs.Item(f"kb:{c.id}", "kb", c.rules, c.source, c.title, c.section, c.text, c.index_text) for c in self.chunks
        ]

    def search(self, conn: sqlite3.Connection, query: str, rule: str | None = None, top_k: int = 4, min_score: float | None = None):
        """Passages whose MEANING is closest to the query, best first. If a rule is given, only guidance for that
        rule (or general guidance) is considered."""
        with self._lock:
            vs.sync(conn, "kb", self._kb_items(), self.embedder, self.space)
        hits = vs.search(
            conn, self.embedder.embed_query(query), "kb", self.space,
            rules=(rule, "general") if rule else None, top_k=top_k,
            min_score=self.embedder.min_score if min_score is None else min_score,
        )
        return [(self._by_id[h.id.removeprefix("kb:")], h.score) for h in hits]

    def core_chunks(self, rule: str) -> list[Chunk]:
        return [c for c in self.chunks if c.rules == rule and c.section in CORE_SECTIONS]

    # --- case memory --------------------------------------------------------------------------
    @staticmethod
    def _case_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return conn.execute(
            """SELECT a.id, a.rule, a.status, a.summary,
                      (SELECT h.comment FROM alert_history h
                        WHERE h.alert_id = a.id AND h.event = 'status_changed' AND h.to_status = a.status
                        ORDER BY h.id DESC LIMIT 1) AS comment
               FROM alerts a WHERE a.status IN ('dismissed', 'escalated')"""
        ).fetchall()

    def similar_cases(self, conn: sqlite3.Connection, alert_id: int, rule: str, query: str, top_k: int = 3) -> list[CaseHit]:
        """Past reviewed alerts of the same pattern whose reviewer comment is closest in meaning to the query."""
        items = [
            vs.Item(f"case:{r['id']}", "case", r["rule"], str(r["id"]), r["summary"], r["status"], r["comment"],
                    f"{RULE_LABELS.get(r['rule'], r['rule'])} alert, {r['status']}. {r['comment']}")
            for r in self._case_rows(conn) if r["comment"]
        ]
        with self._lock:
            vs.sync(conn, "case", items, self.embedder, self.space)
        hits = vs.search(
            conn, self.embedder.embed_query(query), "case", self.space, rules=(rule,), top_k=top_k,
            min_score=self.embedder.min_score, exclude=frozenset({f"case:{alert_id}"}),
        )
        return [CaseHit(int(h.source), h.rule, h.section, h.title, h.text, h.score) for h in hits]


@lru_cache(maxsize=4)
def _build(preference: str, model_name: str) -> Retriever:
    chunks = load_chunks()
    embedder, note = build_embedder(preference, model_name, [c.index_text for c in chunks])
    return Retriever(chunks, embedder, note)


def get_retriever() -> Retriever:
    s = get_settings()
    return _build(s.rag_embedder, s.rag_embedding_model)
