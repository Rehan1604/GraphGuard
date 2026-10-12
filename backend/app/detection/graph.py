from bisect import bisect_left, bisect_right

import networkx as nx

from app.schemas import Transaction


class _TimeIndex:
    """Transactions sorted by time, so 'everything between 10:00 and 10:30'
    is found by binary search instead of scanning the whole list."""

    def __init__(self, txs: list[Transaction]):
        self.txs = sorted(txs, key=lambda t: (t.timestamp, t.id))
        self.times = [t.timestamp.timestamp() for t in self.txs]

    def between(self, start: float, end: float) -> list[Transaction]:
        lo = bisect_left(self.times, start)
        hi = bisect_right(self.times, end)
        return self.txs[lo:hi]


class TransactionGraph:
    """Accounts are nodes; each transaction is a directed edge source -> target.
    NetworkX stores the graph. NetworkX algorithms ignore time, so the
    time-aware searching is done by our rules using the indexes below."""

    def __init__(self, transactions: list[Transaction]):
        self.transactions = sorted(transactions, key=lambda t: (t.timestamp, t.id))
        self.graph = nx.MultiDiGraph()  # "Multi": two accounts can share many edges
        for tx in self.transactions:
            self.graph.add_edge(tx.source_account_id, tx.target_account_id, key=tx.id, tx=tx)

        self._outgoing: dict[str, _TimeIndex] = {}
        self._touching: dict[str, _TimeIndex] = {}
        for node in self.graph.nodes:
            out_txs = [tx for _, _, tx in self.graph.out_edges(node, data="tx")]
            in_txs = [tx for _, _, tx in self.graph.in_edges(node, data="tx")]
            self._outgoing[node] = _TimeIndex(out_txs)
            self._touching[node] = _TimeIndex(out_txs + in_txs)

    @property
    def accounts(self) -> list[str]:
        return sorted(self.graph.nodes)

    def outgoing_between(self, account: str, start: float, end: float) -> list[Transaction]:
        return self._outgoing[account].between(start, end)

    def touching(self, account: str) -> _TimeIndex:
        return self._touching[account]

    def connected_groups(self) -> int:
        return nx.number_weakly_connected_components(self.graph)