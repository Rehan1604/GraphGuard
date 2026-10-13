"""Does retrieval actually find the right passage? Measured, not assumed.

30 questions are written in everyday words that deliberately avoid copying the library's own headings. Each lists
the passage(s) a sensible reviewer would accept. Every retriever is scored on:
  hit@1  - the best result is acceptable
  hit@3  - an acceptable passage is in the top three
  MRR    - 1/rank of the first acceptable passage, averaged (1.0 is perfect)

The questions were written by the project author before looking at any retriever's output, and the set is small.
Treat the numbers as a sanity check of the three retrievers against each other, not as a general benchmark."""
from __future__ import annotations

import argparse
import json

import numpy as np

from app.config import get_settings
from app.rag.chunking import Chunk, load_chunks
from app.rag.embeddings import FastEmbedEmbedder, LsaEmbedder
from app.rag.lexical import TfidfIndex

# question -> acceptable passages as "file#section"
QUERIES: list[tuple[str, list[str]]] = [
    ("money that comes back to the account it started from", ["circular_flows.md#What the pattern is"]),
    ("why would someone send funds around in a ring", ["circular_flows.md#Why it can matter"]),
    ("could a refund explain a loop of transfers", ["legitimate_business_flows.md#Refunds and reversals", "circular_flows.md#Innocent explanations"]),
    ("an employer paying lots of staff on the same day", ["legitimate_business_flows.md#Payroll and bulk payouts", "many_counterparties.md#Innocent explanations"]),
    ("one account suddenly dealing with many different people", ["many_counterparties.md#What the pattern is"]),
    ("what should I examine after a flurry of transfers on one account", ["transfer_bursts.md#What to check next"]),
    ("a platform that takes a cut and pays sellers quickly", ["legitimate_business_flows.md#Marketplace and platform settlements", "pass_through_chains.md#Innocent explanations"]),
    ("funds hopping through several accounts with little kept", ["pass_through_chains.md#What the pattern is"]),
    ("does a high number mean the person is guilty", ["reading_risk_scores.md#What the score does not mean", "reviewing_alerts.md#Evidence versus conclusions"]),
    ("when should I hand an alert to a senior colleague", ["reviewing_alerts.md#When to escalate"]),
    ("how do I write up my decision for the record", ["reviewing_alerts.md#Documenting your review"]),
    ("what does the machine learning percentage mean", ["reading_ml_scores.md#What the triage score is", "reading_ml_scores.md#How to read it"]),
    ("can I trust the model on real customers", ["reading_ml_scores.md#Limits of the estimate"]),
    ("what kinds of suspicious activity will this tool miss", ["what_graphguard_cannot_see.md#Patterns it does not look for"]),
    ("activity spread slowly across several weeks", ["what_graphguard_cannot_see.md#Things outside its view"]),
    ("does the account normally behave this way", ["account_context.md#Comparing with the account's usual behaviour"]),
    ("is the account a company or a private person", ["account_context.md#What to look at first"]),
    ("learn from how earlier alerts were closed", ["learning_from_past_cases.md#Why past decisions matter", "learning_from_past_cases.md#How this tool uses them"]),
    ("what information gets shared with an outside AI service", ["learning_from_past_cases.md#How this tool uses them"]),
    ("friends dividing a restaurant bill", ["legitimate_business_flows.md#Shared costs and group payments"]),
    ("a spike of payments on salary day", ["legitimate_business_flows.md#Busy periods", "legitimate_business_flows.md#Payroll and bulk payouts"]),
    ("too many false alarms, what can I do", ["reviewing_alerts.md#Handling false positives", "reading_risk_scores.md#Thresholds and false positives"]),
    ("how fast do the transfers need to follow each other for a chain", ["pass_through_chains.md#What the pattern is"]),
    ("harmless reasons the same amount would come back", ["circular_flows.md#Innocent explanations"]),
    ("why does a rapid series of payments deserve attention", ["transfer_bursts.md#Why it can matter"]),
    ("steps to verify an alert about lots of counterparties", ["many_counterparties.md#What to check next"]),
    ("separate what the data shows from my own opinion", ["reviewing_alerts.md#Evidence versus conclusions"]),
    ("what the numerical risk rating is made of", ["reading_risk_scores.md#What the score means"]),
    ("middle accounts that keep almost nothing of what they receive", ["pass_through_chains.md#What the pattern is"]),
    ("is a low score safe to ignore", ["reading_ml_scores.md#How to read it", "reading_ml_scores.md#Limits of the estimate", "reading_risk_scores.md#What the score does not mean"]),
]


def _key(c: Chunk) -> str:
    return f"{c.source}#{c.section}"


def _score(ranked_keys: list[list[str]]) -> dict[str, float]:
    hits1 = hits3 = 0
    rr = 0.0
    for (_, relevant), ranking in zip(QUERIES, ranked_keys):
        ranks = [i for i, k in enumerate(ranking, start=1) if k in relevant]
        first = ranks[0] if ranks else None
        hits1 += first == 1
        hits3 += first is not None and first <= 3
        rr += 1 / first if first else 0.0
    n = len(QUERIES)
    return {"hit@1": round(hits1 / n, 3), "hit@3": round(hits3 / n, 3), "mrr": round(rr / n, 3)}


def rank_lexical(chunks: list[Chunk]) -> list[list[str]]:
    idx = TfidfIndex(chunks)
    return [[_key(c) for c, _ in idx.search(q, top_k=len(chunks), min_score=0.0)] for q, _ in QUERIES]


def rank_dense(chunks: list[Chunk], embedder) -> list[list[str]]:
    embedder.fit([c.index_text for c in chunks])
    docs = embedder.embed_documents([c.index_text for c in chunks])
    out = []
    for q, _ in QUERIES:
        scores = docs @ embedder.embed_query(q)
        order = np.argsort(-scores, kind="stable")
        out.append([_key(chunks[i]) for i in order])
    return out


def evaluate(include_neural: bool = True) -> dict:
    chunks = load_chunks()
    results = {
        "questions": len(QUERIES),
        "passages_in_library": len(chunks),
        "systems": {
            "lexical TF-IDF (word matching)": _score(rank_lexical(chunks)),
            "offline embeddings (LSA)": _score(rank_dense(chunks, LsaEmbedder())),
        },
    }
    if include_neural:
        model = get_settings().rag_embedding_model
        try:
            results["systems"][f"neural embeddings ({model})"] = _score(rank_dense(chunks, FastEmbedEmbedder(model)))
        except Exception as exc:
            results["neural_unavailable"] = f"{type(exc).__name__}: {exc}"
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.rag")
    ap.add_argument("--no-neural", action="store_true", help="skip the neural model (no download)")
    args = ap.parse_args(argv)
    r = evaluate(include_neural=not args.no_neural)
    print(f"{r['questions']} questions over {r['passages_in_library']} passages\n")
    print(f"{'retriever':58s} hit@1  hit@3   MRR")
    for name, m in r["systems"].items():
        print(f"{name:58s} {m['hit@1']:.3f}  {m['hit@3']:.3f}  {m['mrr']:.3f}")
    if "neural_unavailable" in r:
        print(f"\nneural embeddings not run: {r['neural_unavailable']}")
    print("\nNote: small hand-written question set; a sanity check, not a general benchmark.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
