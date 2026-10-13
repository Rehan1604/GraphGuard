import json
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import SecretStr

from app.alerts.models import AlertDetail
from app.config import Settings, get_settings
from app.db import connect, init_db
from app.detection.engine import run_detection
from app.main import app
from app.rag.chunking import chunk_document, load_chunks, parse_front_matter
from app.rag.facts import build_facts
from app.rag.grounding import Pseudonymizer, find_accusatory_language, parse_sections, validate_citations
from app.rag.llm import AnthropicClient, OpenAICompatibleClient, build_client, describe_provider
from app.rag.embeddings import LsaEmbedder
from app.rag.index import Retriever
from app.rag.lexical import tokenize
from app.rag.routes import get_llm
from app.rag.service import answer_question, retrieve_for_alert
from tests.test_alerts import chain_client  # noqa: F401  (fixture)
from tests.test_detection import scenario


# ---- helpers -----------------------------------------------------------------
def detail_for(rule: str, accounts_first: str, extra=None) -> AlertDetail:
    """Build an AlertDetail from the detection scenario, exactly as the alert pipeline would."""
    txs = scenario()
    by_id = {t.id: t for t in txs}
    finding = next(f for f in run_detection(txs).findings if f.rule == rule and f.accounts[0] == accounts_first)
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    return AlertDetail(
        id=1, rule=finding.rule, risk_score=finding.risk_score, priority=finding.priority, summary=finding.summary,
        accounts=finding.accounts, status="new", window_start=finding.window_start, window_end=finding.window_end,
        evidence_count=len(finding.transaction_ids), created_at=now, updated_at=now,
        contributions=finding.contributions, evidence=[by_id[i] for i in finding.transaction_ids], notes=[], history=[],
        allowed_next_statuses=["in_review"], comment_required_for=["escalated", "dismissed"],
    )


@pytest.fixture(scope="module")
def retriever():
    """Meaning-based retriever using the offline embedder, so tests never need a download."""
    chunks = load_chunks()
    embedder = LsaEmbedder()
    embedder.fit([c.index_text for c in chunks])
    return Retriever(chunks, embedder, "test")


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "rag.db"
    init_db(path)
    c = connect(path)
    yield c
    c.close()


GOOD = (
    "Why it was flagged\n- Money moved through ACCT_A, ACCT_B, ACCT_C and ACCT_D [F2].\n"
    "Possible innocent explanations\n- A payroll account may forward funds [K1].\n"
    "Suggested next steps for the analyst\n- Compare with the accounts' earlier history [K2]."
)


def openai_client(reply, calls=None, status=200, key="sk-secret"):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if isinstance(reply, Exception):
            raise reply
        body = reply if isinstance(reply, (dict, list)) else {"choices": [{"message": {"content": reply}}]}
        return httpx.Response(status, json=body)

    return OpenAICompatibleClient(key, "test-model", None, 5, transport=httpx.MockTransport(handler))


# ---- chunking ------------------------------------------------------------------
def test_library_is_chunked_by_section_with_metadata():
    chunks = load_chunks()
    assert len(chunks) == 42 and len({c.id for c in chunks}) == 42
    assert {c.source for c in chunks} >= {"pass_through_chains.md", "circular_flows.md", "reviewing_alerts.md", "reading_ml_scores.md", "learning_from_past_cases.md"}
    first = next(c for c in chunks if c.id == "pass_through_chains#3")
    assert (first.title, first.section, first.rules) == ("Pass-through chains", "Innocent explanations", "pass_through_chain")
    assert all(c.text and c.section and c.title for c in chunks)


def test_front_matter_and_long_sections(tmp_path):
    meta, body = parse_front_matter("---\ntitle: T\nrules: cycle\n---\n## A\nx")
    assert meta == {"title": "T", "rules": "cycle"} and body.strip().startswith("## A")
    doc = tmp_path / "long.md"
    doc.write_text("## Big\n" + "\n".join(f"- line number {i} with some padding words" for i in range(60)))
    chunks = chunk_document(doc, max_chars=300)
    assert len(chunks) > 3 and all(len(c.text) <= 300 for c in chunks)
    assert {c.section for c in chunks} == {"Big"} and chunks[0].title == "long" and chunks[0].rules == "general"
    empty = tmp_path / "empty.md"
    empty.write_text("just text, no sections")
    assert chunk_document(empty) == []


# ---- retrieval -----------------------------------------------------------------
def test_tokenizer_drops_filler_and_normalises_plurals():
    assert tokenize("The accounts are forwarding transfers") == ["account", "forwarding", "transfer"]


def test_retrieval_ranks_the_relevant_chunk_first(retriever, conn):
    top, score = retriever.search(conn, "money moved quickly through several accounts in a chain", rule="pass_through_chain")[0]
    assert top.source == "pass_through_chains.md" and 0 < score <= 1


def test_rule_filter_blocks_other_patterns_but_allows_general_guidance(retriever, conn):
    hits = retriever.search(conn, "loop circular money returned", rule="burst", top_k=10)
    assert hits and all(c.rules in ("burst", "general") for c, _ in hits)


def test_unrelated_question_retrieves_nothing(retriever, conn):
    assert retriever.search(conn, "recipe for chocolate cake", top_k=5) == []


def test_retrieval_is_deterministic(retriever, conn):
    q = "what should I check next"
    assert retriever.search(conn, q, rule="cycle") == retriever.search(conn, q, rule="cycle")


def test_every_alert_gets_standard_guidance_even_for_odd_questions(retriever, conn):
    assert retriever.search(conn, "recipe for chocolate cake", rule="cycle") == []  # the question alone matches nothing
    passages = retrieve_for_alert(retriever, conn, "cycle", "recipe for chocolate cake")
    assert [p.id for p in passages] == [f"K{i}" for i in range(1, len(passages) + 1)]
    assert {"Innocent explanations", "What to check next"} <= {p.section for p in passages}
    assert all(p.source == "circular_flows.md" or p.title in ("Reviewing an alert", "Reading risk scores") for p in passages)
    matched = retrieve_for_alert(retriever, conn, "cycle", "why does a loop matter")
    assert matched[0].via == "similarity" and matched[0].score > 0
    assert len({p.id for p in passages}) == len(passages) and len({p.text for p in passages}) == len(passages)


# ---- facts ----------------------------------------------------------------------
def test_chain_facts_are_computed_from_the_evidence():
    facts = build_facts(detail_for("pass_through_chain", "A1"))
    text = "\n".join(f.text for f in facts)
    assert [f.id for f in facts] == [f"F{i}" for i in range(1, len(facts) + 1)]
    assert "3 transactions" in text and "4 accounts" in text and "2,940.00 USD in total" in text
    assert "Transfer 2: A2 sent 980.00 USD to A3" in text and "10 minutes after A2 received 1,000.00 USD, forwarding 98.0% of it" in text
    assert sum(f.kind == "score" for f in facts) == 3


def test_cycle_burst_and_fan_facts():
    cycle = "\n".join(f.text for f in build_facts(detail_for("cycle", "C1")))
    assert "Loop: C1 -> C2 -> C3 -> C1." in cycle and "smallest is 98.0% of the largest" in cycle
    burst = "\n".join(f.text for f in build_facts(detail_for("burst", "B1")))
    assert "It sent 6 and received 0" in burst and "1 distinct counterparties: B2" in burst
    fan = "\n".join(f.text for f in build_facts(detail_for("fan", "F1")))
    assert "5 distinct counterparties" in fan and "sent 0 and received 5" in fan


def test_facts_can_use_aliases_without_changing_structure():
    d = detail_for("pass_through_chain", "A1")
    plain, aliased = build_facts(d), build_facts(d, name=Pseudonymizer(d.accounts).alias)
    assert [f.id for f in plain] == [f.id for f in aliased]
    assert "A1" not in "\n".join(f.text for f in aliased) and "ACCT_A" in aliased[2].text


# ---- grounding ------------------------------------------------------------------
def test_citation_validation_keeps_real_sources_and_removes_invented_ones():
    text, cited, removed = validate_citations("Fast [F1]. Odd [F9]. Both [F2, K7]. Kept [K1].", {"F1", "F2", "K1"})
    assert cited == ["F1", "F2", "K1"] and removed == ["F9", "K7"]
    assert "[F9]" not in text and "[F2]" in text and "[K7]" not in text and "Odd." in text


def test_accusatory_wording_is_flagged_only_when_unhedged():
    assert find_accusatory_language("This account is clearly committing fraud.") != []
    assert find_accusatory_language("This is not proof of fraud.") == []
    assert find_accusatory_language("It may indicate laundering, which a human must judge.") == []
    assert find_accusatory_language("The transfers happened within ten minutes.") == []


def test_pseudonymizer_round_trip_and_no_prefix_collisions():
    p = Pseudonymizer(["SIM-A1", "SIM-A10"])
    assert p.alias_text("Why did SIM-A10 pay SIM-A1?") == "Why did ACCT_B pay ACCT_A?"
    assert p.restore("ACCT_B paid ACCT_A") == "SIM-A10 paid SIM-A1"
    many = Pseudonymizer([f"id{i}" for i in range(30)])
    assert many.alias("id26") == "ACCT_AA" and len(set(many.to_alias.values())) == 30


def test_section_parsing_handles_markdown_noise_and_unknown_layouts():
    parsed = parse_sections("**Why it was flagged:**\n- one\n- two\n\n## Suggested next steps\n1. check\n")
    assert parsed == [("Why it was flagged", ["one", "two"]), ("Suggested next steps for the analyst", ["check"])]
    assert parse_sections("just a paragraph") == [("Explanation", ["just a paragraph"])]


# ---- rule-based explanation (no AI) ------------------------------------------------
def test_without_a_provider_the_summary_is_rule_based_and_says_so(retriever, conn):
    a = answer_question(detail_for("pass_through_chain", "A1"), "Why was this flagged?", retriever, conn, None, True)
    e = a.explanation
    assert e.mode == "rule_based" and "not AI-generated" in e.label and e.provider is None
    assert [s.heading for s in e.sections] == ["Why it was flagged", "Possible innocent explanations", "Suggested next steps for the analyst"]
    valid = {f.id for f in a.facts} | {p.id for p in a.guidance}
    assert set(e.citations) <= valid and e.citations
    assert any("payroll" in i.lower() for i in e.sections[1].items)
    assert all("[" in i for s in e.sections[1:] for i in s.items)  # every guidance line cites its source


def test_turning_ai_off_never_calls_the_provider(retriever, conn):
    calls = []
    a = answer_question(detail_for("cycle", "C1"), "why?", retriever, conn, openai_client(GOOD, calls), use_ai=False)
    assert calls == [] and a.explanation.mode == "rule_based" and a.explanation.warnings == []


# ---- AI path (provider simulated with httpx.MockTransport: no real network) ---------
def test_ai_answer_is_labelled_grounded_and_de_aliased(retriever, conn):
    calls = []
    a = answer_question(detail_for("pass_through_chain", "A1"), "Why was A2 flagged?", retriever, conn, openai_client(GOOD, calls), True)
    e = a.explanation
    assert e.mode == "ai" and "AI-generated" in e.label and e.provider == "openai_compatible" and e.model == "test-model"
    assert "A1, A2, A3 and A4" in e.sections[0].items[0]  # aliases swapped back to real ids
    assert "ACCT_" not in json.dumps([sec.model_dump() for sec in e.sections]) and e.citations == ["F2", "K1", "K2"]
    sent = json.loads(calls[0].content)
    assert "ACCT_B" in json.dumps(sent) and "Why was ACCT_B flagged?" in sent["messages"][1]["content"]
    assert calls[0].headers["authorization"] == "Bearer sk-secret" and str(calls[0].url).endswith("/chat/completions")
    assert "Not sent" not in e.privacy_note and "Never sent" in e.privacy_note


def test_ai_request_never_contains_real_account_ids(retriever, conn):
    calls = []
    d = detail_for("pass_through_chain", "A1")
    answer_question(d, "Why did A1 send money to A2?", retriever, conn, openai_client(GOOD, calls), True)
    body = calls[0].content.decode()
    for real in ("A1", "A2", "A3", "A4"):
        assert f'"{real}"' not in body and f" {real} " not in body and f"{real}." not in body.replace("ACCT_", "")


def test_invented_citations_are_removed_and_reported(retriever, conn):
    text = GOOD.replace("[F2]", "[F2] and also [F99]")
    a = answer_question(detail_for("cycle", "C1"), "why", retriever, conn, openai_client(text), True)
    assert a.explanation.mode == "ai" and a.explanation.invalid_citations_removed == ["F99"]
    assert "[F99]" not in json.dumps(a.explanation.model_dump()) and any("F99" in w for w in a.explanation.warnings)


def test_answer_with_no_valid_citation_is_discarded(retriever, conn):
    a = answer_question(detail_for("cycle", "C1"), "why", retriever, conn, openai_client("Why it was flagged\n- Looks odd.\n- Trust me [F77]."), True)
    assert a.explanation.mode == "rule_based" and any("cited none" in w for w in a.explanation.warnings)


@pytest.mark.parametrize(
    "reply,status,expected",
    [
        ("boom", 500, "HTTP 500"),
        ("boom", 401, "HTTP 401"),
        (httpx.ReadTimeout("slow"), 200, "timed out"),
        (httpx.ConnectError("down"), 200, "could not reach"),
        ({"unexpected": True}, 200, "unexpected response shape"),
    ],
)
def test_provider_failures_fall_back_without_leaking_secrets(retriever, conn, reply, status, expected):
    a = answer_question(detail_for("cycle", "C1"), "why", retriever, conn, openai_client(reply, status=status, key="sk-VERY-SECRET"), True)
    assert a.explanation.mode == "rule_based" and a.explanation.sections
    joined = " ".join(a.explanation.warnings)
    assert expected in joined and "sk-VERY-SECRET" not in joined and "Showing the rule-based summary" in joined


def test_unhedged_crime_language_triggers_a_warning_but_not_a_verdict(retriever, conn):
    text = GOOD.replace("[K1].", "[K1].\n- This is obviously fraud [F1].")
    a = answer_question(detail_for("cycle", "C1"), "why", retriever, conn, openai_client(text), True)
    assert a.explanation.mode == "ai" and any("without hedging" in w for w in a.explanation.warnings)


def test_anthropic_request_shape_and_response_parsing(retriever, conn):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"content": [{"type": "text", "text": GOOD}]})

    client = AnthropicClient("key-123", "some-model", None, 5, transport=httpx.MockTransport(handler))
    a = answer_question(detail_for("cycle", "C1"), "why", retriever, conn, client, True)
    sent = json.loads(calls[0].content)
    assert a.explanation.mode == "ai" and a.explanation.provider == "anthropic"
    assert calls[0].headers["x-api-key"] == "key-123" and calls[0].headers["anthropic-version"]
    assert str(calls[0].url) == "https://api.anthropic.com/v1/messages"
    assert sent["model"] == "some-model" and sent["max_tokens"] > 0 and sent["messages"][0]["role"] == "user"
    assert "ONLY the FACTS" in sent["system"]


# ---- configuration -----------------------------------------------------------------
def test_provider_configuration_rules_and_secret_hiding():
    assert describe_provider(Settings(llm_provider="none")) == (False, None)
    assert describe_provider(Settings(llm_provider="anthropic", llm_model="m"))[1].endswith("API_KEY is not set")
    assert describe_provider(Settings(llm_provider="openai_compatible"))[1].endswith("MODEL is not set")
    assert describe_provider(Settings(llm_provider="mystery", llm_model="m"))[0] is False
    local = Settings(llm_provider="openai_compatible", llm_model="llama", llm_base_url="http://localhost:11434/v1")
    assert describe_provider(local) == (True, None) and build_client(local).provider == "openai_compatible"
    assert build_client(Settings(llm_provider="none")) is None
    secret = Settings(llm_provider="anthropic", llm_model="m", llm_api_key=SecretStr("sk-hidden"))
    assert "sk-hidden" not in repr(secret) and "sk-hidden" not in str(secret.model_dump())


# ---- through the real API -----------------------------------------------------------
def load_private_chain(client):
    """Accounts with distinctive ids and real-looking names, plus a note with personal details."""
    ids = ["ACC-ALPHA", "ACC-BRAVO", "ACC-CHARLIE", "ACC-DELTA"]
    names = ["Priya Sharma", "Rahul Verma", "Meera Iyer", "Arjun Nair"]
    for i, n in zip(ids, names):
        client.post("/api/accounts", json={"id": i, "name": n, "account_type": "individual"})
    rows = [("T0", 0, 1, "1000.00", "10:00"), ("T1", 1, 2, "980.00", "10:10"), ("T2", 2, 3, "960.00", "10:20")]
    for tid, s, t, amt, hhmm in rows:
        r = client.post("/api/transactions", json={"id": tid, "source_account_id": ids[s], "target_account_id": ids[t],
                                                    "amount": amt, "timestamp": f"2026-03-01T{hhmm}:00Z"})
        assert r.status_code == 201
    client.post("/api/alerts/scan")
    client.post("/api/alerts/1/notes", json={"author": "Dr. Kavita Rao", "body": "Customer Priya Sharma phoned from 98765 43210"})
    return ids, names


def test_api_answers_without_any_provider_and_changes_nothing(chain_client):
    chain_client.post("/api/alerts/scan")
    before = chain_client.get("/api/alerts/1").json()
    r = chain_client.post("/api/alerts/1/assistant", json={"question": "Why was this flagged?"})
    assert r.status_code == 200
    body = r.json()
    assert body["explanation"]["mode"] == "rule_based" and body["facts"][0]["id"] == "F1"
    assert body["guidance"] and all(g["source"].endswith(".md") for g in body["guidance"])
    assert "not proof of wrongdoing" in body["disclaimer"]
    assert chain_client.get("/api/alerts/1").json() == before  # asking never changes score, status, notes or history


def test_api_validation_and_unknown_alert(chain_client):
    chain_client.post("/api/alerts/scan")
    assert chain_client.post("/api/alerts/99/assistant", json={"question": "hi"}).status_code == 404
    assert chain_client.post("/api/alerts/1/assistant", json={"question": "   "}).status_code == 422
    assert chain_client.post("/api/alerts/1/assistant", json={"question": "x" * 501}).status_code == 422


def test_names_notes_and_real_ids_never_reach_the_provider(client):
    ids, names = load_private_chain(client)
    calls = []
    app.dependency_overrides[get_llm] = lambda: openai_client(GOOD, calls)
    try:
        r = client.post("/api/alerts/1/assistant", json={"question": f"Why did {ids[1]} forward money?"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.json()["explanation"]["mode"] == "ai"
    outgoing = calls[0].content.decode()
    for secret in ids + names + ["Kavita", "Rao", "98765", "phoned", "Customer"]:
        assert secret not in outgoing, secret
    assert "ACCT_A" in outgoing and "ACCT_D" in outgoing
    shown = json.dumps(r.json()["explanation"]["sections"])
    assert "ACC-ALPHA" in shown and "ACCT_" not in shown  # the analyst still sees real ids


def test_status_and_knowledge_endpoints(client, monkeypatch):
    s = client.get("/api/assistant/status").json()
    assert s["ai_configured"] is False and s["provider"] == "none" and "aliases" in s["privacy"]
    monkeypatch.setenv("GRAPHGUARD_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("GRAPHGUARD_LLM_MODEL", "some-model")
    get_settings.cache_clear()
    try:
        assert "API_KEY" in client.get("/api/assistant/status").json()["problem"]
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    lib = client.get("/api/knowledge").json()
    assert len(lib) == 11 and {"source", "title", "rules", "sections"} <= set(lib[0])
    hits = client.get("/api/knowledge/search", params={"q": "money returned to the starting account", "rule": "cycle"}).json()
    assert hits and hits[0]["source"] == "circular_flows.md" and hits[0]["score"] > 0
    assert client.get("/api/knowledge/search", params={"q": ""}).status_code == 422