"""The documents must not rot: links resolve, and claims we cannot back are not made."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["README.md", *[f"docs/{n}" for n in ("ARCHITECTURE.md", "DEMO.md", "TRADEOFFS.md", "INTERVIEW.md", "RESUME.md")]]
BANNED = ["production-ready", "catches fraud", "detects fraud", "ai-powered detection", "99%", "events/sec", "ms latency"]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_all_documents_exist():
    for rel in DOCS:
        assert (ROOT / rel).is_file(), rel


def test_relative_links_resolve():
    for rel in DOCS:
        base = (ROOT / rel).parent
        for target in re.findall(r"\]\(([^)#\s]+)\)", read(rel)):
            if "://" in target:
                continue
            assert (base / target).exists(), f"{rel} links to missing {target}"


def test_no_claims_we_cannot_back():
    for rel in DOCS:
        # RESUME.md lists the banned phrases on purpose, under "Do not write"
        text = read(rel).lower()
        if rel.endswith("RESUME.md"):
            text = text.split("**do not write:**")[0] + text.split("**if asked")[1] if "**if asked" in text else text
        for phrase in BANNED:
            assert phrase not in text, f"{rel} contains unbackable phrase '{phrase}'"


def test_documents_state_the_synthetic_data_limit():
    for rel in ("README.md", "docs/TRADEOFFS.md", "docs/RESUME.md"):
        assert "synthetic" in read(rel).lower(), rel


def test_resume_numbers_match_the_benchmark():
    """The quoted benchmark figures must still be what the code produces."""
    from app.evaluation.runner import cached_report

    report = cached_report("benchmark", 42, 240)
    text = read("docs/RESUME.md") + read("docs/TRADEOFFS.md")
    g = report.graph
    assert f"{g.precision.numerator}/{g.precision.denominator}" in text.replace("(", "").replace(")", "") or "52/70" in text
    assert (g.precision.numerator, g.precision.denominator) == (52, 70)
    assert (g.recall.numerator, g.recall.denominator) == (40, 40)
