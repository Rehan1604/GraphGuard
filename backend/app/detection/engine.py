from app.detection.graph import TransactionGraph
from app.detection.models import DetectionConfig, DetectionResult
from app.detection.rules import find_bursts, find_cycles, find_fans, find_pass_through_chains
from app.schemas import Transaction


def run_detection(
    transactions: list[Transaction], config: DetectionConfig | None = None
) -> DetectionResult:
    """Pure function: same transactions + same config -> same findings, always.
    It never touches the database or the network, which makes it easy to test."""
    cfg = config or DetectionConfig()
    unique = list({t.id: t for t in transactions}.values())  # the same transaction id twice is still one transaction
    tg = TransactionGraph(unique)

    findings = (
        find_pass_through_chains(tg, cfg)
        + find_cycles(tg, cfg)
        + find_bursts(tg, cfg)
        + find_fans(tg, cfg)
    )
    findings.sort(key=lambda f: (-f.risk_score, f.window_start, f.rule, f.accounts))

    return DetectionResult(
        config=cfg,
        transactions_analyzed=len(tg.transactions),
        accounts_in_graph=len(tg.accounts),
        connected_groups=tg.connected_groups() if tg.accounts else 0,
        findings=findings,
    )