"""Step 2 of RAG: find the chunks that best match a question, using TF-IDF.

TF-IDF in one sentence: a word counts for more if it is frequent in THIS chunk (TF)
but rare across ALL chunks (IDF), so "the" counts for nothing and "layering" counts for a lot."""
import math
import re
from collections import Counter

from app.rag.chunking import Chunk

STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from had has have how i if in into is it its of on "
    "or our s so than that the their them then there these they this those to us was we were what when "
    "where which who why will with would you your should could may might not no".split()
)

# The sections every rule-specific document provides. Used for "standard guidance".
CORE_SECTIONS = ("Innocent explanations", "What to check next")


def _normalise(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [_normalise(w) for w in words if len(w) > 1 and w not in STOPWORDS]


class TfidfIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        docs = [tokenize(c.index_text) for c in chunks]
        n = len(docs)
        doc_freq: Counter[str] = Counter()
        for tokens in docs:
            doc_freq.update(set(tokens))
        self.idf = {t: math.log((1 + n) / (1 + df)) + 1 for t, df in doc_freq.items()}
        self.vectors = [self._vector(tokens) for tokens in docs]

    def _vector(self, tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        vec = {t: (1 + math.log(c)) * self.idf[t] for t, c in counts.items() if t in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        return {t: v / norm for t, v in vec.items()} if norm else {}

    def search(self, query: str, rule: str | None = None, top_k: int = 4, min_score: float = 0.05) -> list[tuple[Chunk, float]]:
        """Cosine similarity between the question and every allowed chunk, best first.
        If a rule is given, only guidance for that rule (or general guidance) is considered."""
        q = self._vector(tokenize(query))
        scored = []
        for chunk, vec in zip(self.chunks, self.vectors):
            if rule is not None and chunk.rules not in (rule, "general"):
                continue
            score = sum(weight * vec.get(term, 0.0) for term, weight in q.items())
            if score >= min_score:
                scored.append((chunk, round(score, 4)))
        scored.sort(key=lambda pair: (-pair[1], pair[0].id))  # ties broken by id: deterministic
        return scored[:top_k]

    def core_chunks(self, rule: str) -> list[Chunk]:
        return [c for c in self.chunks if c.rules == rule and c.section in CORE_SECTIONS]