from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.ratelimit import rate_limited
from app.evaluation.runner import EvaluationReport, cached_report

router = APIRouter(prefix="/api")


@router.get("/evaluation", response_model=EvaluationReport, dependencies=[Depends(rate_limited)])
def evaluation(
    dataset: Literal["benchmark", "simulator"] = "benchmark",
    seed: Annotated[int, Query(ge=0, le=1_000_000)] = 42,
    n_events: Annotated[int, Query(ge=50, le=2000)] = 240,
) -> EvaluationReport:
    """Run the synthetic evaluation in memory (nothing is written to your database).
    The same seed always gives the same metrics. Results are cached per (dataset, seed, n_events)."""
    return cached_report(dataset, seed, n_events)