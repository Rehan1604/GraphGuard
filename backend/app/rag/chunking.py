"""Step 1 of RAG: turn documents into small, labelled pieces ("chunks")."""
import re
from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


@dataclass(frozen=True)
class Chunk:
    id: str  # e.g. "pass_through_chains#3"
    source: str  # file name
    title: str  # document title
    section: str  # the "## heading" this piece came from
    text: str
    rules: str  # which alert rule this guidance is for, or "general"

    @property
    def index_text(self) -> str:
        """What the search engine reads. Title and section help matching."""
        return f"{self.title} {self.section} {self.text}"


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    """Documents start with a small header between '---' lines (title, rules)."""
    if not raw.startswith("---"):
        return {}, raw
    end = raw.find("\n---", 3)
    if end == -1:
        return {}, raw
    meta: dict[str, str] = {}
    for line in raw[3:end].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, raw[end + 4 :]


def _split_long(text: str, max_chars: int) -> list[str]:
    """Break an overly long section at line boundaries so no piece is too big."""
    pieces, current = [], ""
    for line in text.splitlines():
        if current and len(current) + len(line) + 1 > max_chars:
            pieces.append(current.strip())
            current = ""
        current += line + "\n"
    if current.strip():
        pieces.append(current.strip())
    return pieces


def chunk_document(path: Path, max_chars: int = 900) -> list[Chunk]:
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    title = meta.get("title", path.stem)
    rules = meta.get("rules", "general")
    chunks: list[Chunk] = []
    # re.split with a capture group returns [intro, heading1, body1, heading2, body2, ...]
    parts = re.split(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE)
    for heading, section_text in zip(parts[1::2], parts[2::2]):
        for piece in _split_long(section_text.strip(), max_chars):
            chunks.append(
                Chunk(
                    id=f"{path.stem}#{len(chunks) + 1}",
                    source=path.name,
                    title=title,
                    section=heading,
                    text=piece,
                    rules=rules,
                )
            )
    return chunks


def load_chunks(directory: Path = KNOWLEDGE_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(chunk_document(path))
    return chunks