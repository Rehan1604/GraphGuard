"""Safety checks around machine-written text: privacy aliases, citation checking, wording checks."""
import re
import string

CITATION_RE = re.compile(r"\[((?:[FK]\d+)(?:\s*,\s*[FK]\d+)*)\]")
ALIAS_RE = re.compile(r"ACCT_[A-Z]+")


class Pseudonymizer:
    """Swaps real account ids for neutral tokens (ACCT_A, ACCT_B, ...) before anything
    leaves this computer, and swaps them back in the answer that comes home."""

    def __init__(self, account_ids: list[str]):
        self.to_alias: dict[str, str] = {}
        self.to_real: dict[str, str] = {}
        for real in dict.fromkeys(account_ids):  # unique, original order
            alias = f"ACCT_{self._letters(len(self.to_alias))}"
            self.to_alias[real] = alias
            self.to_real[alias] = real

    @staticmethod
    def _letters(n: int) -> str:
        out = ""
        n += 1
        while n:
            n, rem = divmod(n - 1, 26)
            out = string.ascii_uppercase[rem] + out
        return out

    def alias(self, real: str) -> str:
        return self.to_alias.get(real, real)

    def alias_text(self, text: str) -> str:
        """Replace any real account id that appears inside free text (like the analyst's question)."""
        for real in sorted(self.to_alias, key=len, reverse=True):
            pattern = rf"(?<![A-Za-z0-9_-]){re.escape(real)}(?![A-Za-z0-9_-])"
            text = re.sub(pattern, self.to_alias[real], text)
        return text

    def restore(self, text: str) -> str:
        return ALIAS_RE.sub(lambda m: self.to_real.get(m.group(0), m.group(0)), text)


def validate_citations(text: str, valid_ids: set[str]) -> tuple[str, list[str], list[str]]:
    """Keep citations that point at a source we really supplied. Remove the rest.
    Returns (cleaned text, valid ids cited, invalid ids removed)."""
    cited: list[str] = []
    removed: list[str] = []

    def fix(match: re.Match[str]) -> str:
        ids = [part.strip() for part in match.group(1).split(",")]
        good = [i for i in ids if i in valid_ids]
        cited.extend(good)
        removed.extend(i for i in ids if i not in valid_ids)
        return f"[{', '.join(good)}]" if good else ""

    cleaned = CITATION_RE.sub(fix, text)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned, list(dict.fromkeys(cited)), list(dict.fromkeys(removed))


_TRIGGERS = re.compile(r"\b(fraud\w*|launder\w*|criminal\w*|crime\w*|illegal\w*|guilty)\b", re.I)
_HEDGES = re.compile(
    r"\b(not|no|never|cannot|can't|isn't|aren't|doesn't|don't|may|might|could|possible|possibly|potential|"
    r"whether|if|would|rule out|innocent|legitimate|proof|prove|probability|indicat\w+|suggest\w*)\b",
    re.I,
)


def find_accusatory_language(text: str) -> list[str]:
    """Sentences that talk about fraud or crime without any hedging word. A soft safety net, not a judge."""
    flagged = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if _TRIGGERS.search(sentence) and not _HEDGES.search(sentence):
            flagged.append(sentence.strip())
    return flagged


HEADINGS = {
    "why it was flagged": "Why it was flagged",
    "possible innocent explanations": "Possible innocent explanations",
    "suggested next steps": "Suggested next steps for the analyst",
}


def parse_sections(text: str) -> list[tuple[str, list[str]]]:
    """Split plain text into (heading, bullet items). Unknown layouts become one 'Explanation' section."""
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key = re.sub(r"[#*:_]", "", line).strip().lower()
        heading = next((v for k, v in HEADINGS.items() if key.startswith(k)), None)
        if heading and len(key) < 60:
            current = (heading, [])
            sections.append(current)
            continue
        item = re.sub(r"^(?:[-*\u2022]\s+|\d+[.)]\s+)", "", line)
        if current is None:
            current = ("Explanation", [])
            sections.append(current)
        current[1].append(item)
    return sections