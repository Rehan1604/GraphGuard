"""Vector store, embedders, and case memory."""
import numpy as np
import pytest

from app.db import connect, init_db
from app.rag import vectorstore as vs
from app.rag.embeddings import LsaEmbedder, build_embedder
from app.rag.index import Retriever, load_chunks

CORPUS = [
    "money moves through a chain of accounts quickly and is passed along",
    "funds go around a circle and return to the starting account",
    "one account sends many small payments in a short burst",
    "payroll pays many employees on the same day each month",
]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "v.db"
    init_db(path)
    c = connect(path)
    yield c
    c.close()


@pytest.fixture
def emb():
    e = LsaEmbedder(n_components=3)
    e.fit(CORPUS)
    return e


def items(texts):
    return [vs.Item(f"t{i}", "test", "cycle", str(i), f"T{i}", "s", t, t) for i, t in enumerate(texts)]


def test_embeddings_are_unit_length_and_deterministic(emb):
    a = emb.embed_documents(CORPUS)
    b = emb.embed_documents(CORPUS)
    assert np.allclose(a, b)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)


def test_sync_only_embeds_what_changed(conn, emb):
    assert vs.sync(conn, "test", items(CORPUS), emb, "space1") == 4
    assert vs.sync(conn, "test", items(CORPUS), emb, "space1") == 0  # nothing changed
    changed = CORPUS[:3] + ["a completely different passage about something"]
    assert vs.sync(conn, "test", items(changed), emb, "space1") == 1
    assert vs.sync(conn, "test", items(CORPUS[:2]), emb, "space1") == 0  # removals cost no embedding
    assert conn.execute("SELECT COUNT(*) FROM rag_vectors").fetchone()[0] == 2


def test_new_embedder_space_triggers_re_embedding(conn, emb):
    vs.sync(conn, "test", items(CORPUS), emb, "space1")
    assert vs.sync(conn, "test", items(CORPUS), emb, "space2") == 4


def test_search_ranks_the_matching_passage_first(conn, emb):
    vs.sync(conn, "test", items(CORPUS), emb, "s")
    hits = vs.search(conn, emb.embed_query("funds returning around a circle"), "test", "s", top_k=2)
    assert hits[0].id == "t1"
    assert hits == sorted(hits, key=lambda h: -h.score)
    none = vs.search(conn, emb.embed_query("funds"), "test", "other-space")
    assert none == []
    excluded = vs.search(conn, emb.embed_query("funds returning around a circle"), "test", "s", exclude=frozenset({"t1"}))
    assert all(h.id != "t1" for h in excluded)


def test_auto_falls_back_to_offline_when_neural_unavailable(monkeypatch):
    import app.rag.embeddings as E

    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(E, "FastEmbedEmbedder", boom)
    embedder, note = build_embedder("auto", "any-model", CORPUS)
    assert isinstance(embedder, LsaEmbedder) and "unavailable" in note
    with pytest.raises(RuntimeError):
        build_embedder("fastembed", "any-model", CORPUS)


def add_reviewed_alert(conn, alert_id, status, comment, rule="cycle"):
    conn.execute(
        "INSERT INTO alerts (id, dedup_key, rule, risk_score, priority, summary, accounts_json, contributions_json, "
        "window_start, window_end, status, created_at, updated_at) VALUES (?, ?, ?, 50, 'medium', 's', '[]', '[]', 't', 't', ?, 't', 't')",
        (alert_id, f"k{alert_id}", rule, status),
    )
    conn.execute(
        "INSERT INTO alert_history (alert_id, event, from_status, to_status, actor, comment, created_at) VALUES (?, 'status_changed', 'new', ?, 'a', ?, 't')",
        (alert_id, status, comment),
    )
    conn.commit()


def test_case_memory_finds_similar_past_comment_and_skips_itself(conn):
    chunks = load_chunks()
    e = LsaEmbedder()
    e.fit([c.index_text for c in chunks])
    r = Retriever(chunks, e, "test")
    add_reviewed_alert(conn, 1, "dismissed", "this is the monthly payroll run to staff, benign")
    add_reviewed_alert(conn, 2, "escalated", "unexplained circular transfers between new accounts")
    add_reviewed_alert(conn, 3, "dismissed", "monthly payroll payments to employees again")
    hits = r.similar_cases(conn, alert_id=3, rule="cycle", query="is this payroll to employees?", top_k=3)
    assert all(h.alert_id != 3 for h in hits)
    assert hits and hits[0].alert_id == 1
