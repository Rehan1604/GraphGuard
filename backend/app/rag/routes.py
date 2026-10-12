import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.alerts import repository as alert_repo
from app.config import get_settings
from app.db import get_db
from app.ratelimit import rate_limited
from app.rag.llm import LLMClient, build_client, describe_provider
from app.rag.models import AskRequest, AssistantAnswer, AssistantStatus
from app.rag.retrieval import TfidfIndex
from app.rag.service import answer_question, get_index

router = APIRouter(prefix="/api")
Db = Annotated[sqlite3.Connection, Depends(get_db)]
Index = Annotated[TfidfIndex, Depends(get_index)]


def get_llm() -> LLMClient | None:
    return build_client(get_settings())


Llm = Annotated[LLMClient | None, Depends(get_llm)]

PRIVACY = (
    "When an AI provider is configured, account ids are replaced by aliases before anything is sent. "
    "Account names, analyst notes and analyst names are never sent."
)


@router.get("/assistant/status", response_model=AssistantStatus)
def assistant_status() -> AssistantStatus:
    settings = get_settings()
    usable, problem = describe_provider(settings)
    return AssistantStatus(
        ai_configured=usable, provider=settings.llm_provider, model=settings.llm_model if usable else None,
        problem=problem, privacy=PRIVACY,
    )


@router.post("/alerts/{alert_id}/assistant", response_model=AssistantAnswer, dependencies=[Depends(rate_limited)])
def ask(alert_id: int, payload: AskRequest, db: Db, index: Index, llm: Llm) -> AssistantAnswer:
    detail = alert_repo.get_alert_detail(db, alert_id)
    if detail is None:
        raise HTTPException(404, f"Alert {alert_id} not found")
    return answer_question(detail, payload.question, index, llm, payload.use_ai)


@router.get("/knowledge")
def knowledge_library(index: Index) -> list[dict]:
    """What is in the guidance library: documents and the sections they were cut into."""
    docs: dict[str, dict] = {}
    for c in index.chunks:
        doc = docs.setdefault(c.source, {"source": c.source, "title": c.title, "rules": c.rules, "sections": []})
        doc["sections"].append(c.section)
    return list(docs.values())


@router.get("/knowledge/search")
def knowledge_search(
    index: Index,
    q: Annotated[str, Query(min_length=1, max_length=300)],
    rule: str | None = None,
    top_k: Annotated[int, Query(ge=1, le=10)] = 4,
) -> list[dict]:
    """Retrieval on its own, with scores, so you can see what the search step does before any generation."""
    return [
        {"id": c.id, "source": c.source, "section": c.section, "score": s, "text": c.text}
        for c, s in index.search(q, rule=rule, top_k=top_k)
    ]