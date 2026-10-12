import json
import sqlite3
from decimal import Decimal
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from app import repository as repo
from app.db import get_db
from app.ratelimit import rate_limited
from app.detection.engine import run_detection
from app.detection.models import DetectionConfig, DetectionResult
from app.schemas import (
    Account,
    AccountCreate,
    EntityId,
    Transaction,
    TransactionCreate,
)

router = APIRouter(prefix="/api")
Db = Annotated[sqlite3.Connection, Depends(get_db)]


@router.post("/accounts", response_model=Account, status_code=201)
def create_account(payload: AccountCreate, db: Db) -> Account:
    try:
        return repo.create_account(db, payload)
    except repo.DuplicateAccountError:
        raise HTTPException(409, f"Account '{payload.id}' already exists")


@router.get("/accounts", response_model=list[Account])
def list_accounts(db: Db) -> list[Account]:
    return repo.list_accounts(db)


@router.get("/accounts/{account_id}", response_model=Account)
def get_account(account_id: EntityId, db: Db) -> Account:
    account = repo.get_account(db, account_id)
    if account is None:
        raise HTTPException(404, f"Account '{account_id}' not found")
    return account


@router.post("/transactions", response_model=Transaction, status_code=201)
def create_transaction(payload: TransactionCreate, response: Response, db: Db) -> Transaction:
    try:
        tx, created = repo.create_transaction(db, payload)
    except repo.UnknownAccountError as exc:
        raise HTTPException(422, f"Unknown account '{exc.args[0]}'")
    except repo.ConflictingTransactionError:
        raise HTTPException(
            409, f"Transaction '{payload.id}' already exists with different content"
        )
    if not created:
        response.status_code = 200  # idempotent replay of an identical event
    return tx


@router.get("/transactions", response_model=list[Transaction])
def list_transactions(
    db: Db,
    account_id: EntityId | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Transaction]:
    return repo.list_transactions(db, account_id, limit, offset)


@router.get("/transactions/{tx_id}", response_model=Transaction)
def get_transaction(tx_id: EntityId, db: Db) -> Transaction:
    tx = repo.get_transaction(db, tx_id)
    if tx is None:
        raise HTTPException(404, f"Transaction '{tx_id}' not found")
    return tx

@router.post("/detection/run", response_model=DetectionResult, dependencies=[Depends(rate_limited)])
def run_detection_now(db: Db, config: DetectionConfig | None = None) -> DetectionResult:
    """Analyse every stored transaction. Send no body to use default thresholds."""
    return run_detection(repo.all_transactions_chronological(db), config)

class Stats(BaseModel):
    accounts: int
    transactions: int
    alerts_total: int
    alerts_open: int  # alerts still 'new' or 'in_review'


@router.get("/stats", response_model=Stats)
def stats(db: Db) -> Stats:
    def count(sql: str) -> int:
        return db.execute(sql).fetchone()[0]

    return Stats(
        accounts=count("SELECT COUNT(*) FROM accounts"),
        transactions=count("SELECT COUNT(*) FROM transactions"),
        alerts_total=count("SELECT COUNT(*) FROM alerts"),
        alerts_open=count("SELECT COUNT(*) FROM alerts WHERE status IN ('new', 'in_review')"),
    )

@router.get("/detection/config", response_model=DetectionConfig)
def default_detection_config() -> DetectionConfig:
    """The thresholds the rules use when you don't send your own."""
    return DetectionConfig()


class GraphNode(BaseModel):
    id: str
    name: str
    account_type: str
    open_alerts: int  # alerts involving this account that are not dismissed


class GraphEdge(BaseModel):
    source: str
    target: str
    transaction_count: int
    total_amount: Decimal
    currency: str


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    transactions_considered: int


@router.get("/graph", response_model=GraphData)
def graph(db: Db, limit: Annotated[int, Query(ge=1, le=2000)] = 300) -> GraphData:
    """The account network built from the most recent `limit` transactions.
    Repeated transfers between the same two accounts are merged into one edge."""
    edge_rows = db.execute(
        """SELECT source_account_id, target_account_id, currency,
                  COUNT(*) AS n, SUM(amount_cents) AS cents
           FROM (SELECT * FROM transactions ORDER BY timestamp DESC, id DESC LIMIT ?)
           GROUP BY source_account_id, target_account_id, currency
           ORDER BY source_account_id, target_account_id""",
        (limit,),
    ).fetchall()
    edges = [
        GraphEdge(
            source=r["source_account_id"], target=r["target_account_id"], transaction_count=r["n"],
            total_amount=Decimal(r["cents"]).scaleb(-2), currency=r["currency"],
        )
        for r in edge_rows
    ]
    open_counts: dict[str, int] = {}
    for row in db.execute("SELECT accounts_json FROM alerts WHERE status != 'dismissed'"):
        for account in set(json.loads(row["accounts_json"])):
            open_counts[account] = open_counts.get(account, 0) + 1
    in_graph = {e.source for e in edges} | {e.target for e in edges}
    nodes = [
        GraphNode(id=r["id"], name=r["name"], account_type=r["account_type"], open_alerts=open_counts.get(r["id"], 0))
        for r in db.execute("SELECT id, name, account_type FROM accounts ORDER BY id")
        if r["id"] in in_graph
    ]
    return GraphData(nodes=nodes, edges=edges, transactions_considered=sum(e.transaction_count for e in edges))


class AlertMetrics(BaseModel):
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_rule: dict[str, int]


@router.get("/metrics/alerts", response_model=AlertMetrics)
def alert_metrics(db: Db) -> AlertMetrics:
    """Plain counts straight from the alerts table. Analyst decisions, NOT accuracy."""

    def grouped(column: str, keys: tuple[str, ...]) -> dict[str, int]:
        counts = {k: 0 for k in keys}
        for row in db.execute(f"SELECT {column} AS k, COUNT(*) AS n FROM alerts GROUP BY {column}"):
            counts[row["k"]] = row["n"]
        return counts

    by_status = grouped("status", ("new", "in_review", "escalated", "dismissed"))
    return AlertMetrics(
        total=sum(by_status.values()),
        by_status=by_status,
        by_priority=grouped("priority", ("low", "medium", "high")),
        by_rule=grouped("rule", ("pass_through_chain", "cycle", "burst", "fan")),
    )