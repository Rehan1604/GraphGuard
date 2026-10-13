"""The explanation written by fixed rules. Works with no AI, and says so."""
import re

from app.alerts.models import AlertDetail
from app.rag.facts import RULE_LABELS
from app.rag.models import CaseMatch, Fact, Passage, Section

INNOCENT = {"Innocent explanations"}
NEXT_STEPS = {"What to check next", "Documenting your review", "When to escalate", "Handling false positives"}


def _bullets(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^\s*-\s+(.+)$", text, flags=re.MULTILINE)]


def rule_based_sections(
    detail: AlertDetail, facts: list[Fact], passages: list[Passage], cases: list[CaseMatch] | None = None
) -> list[Section]:
    why = [
        f"The {RULE_LABELS.get(detail.rule, detail.rule)} rule raised this alert. Everything below is read straight from the stored transactions."
    ]
    why += [f"{f.text} [{f.id}]" for f in facts]

    innocent: list[str] = []
    steps: list[str] = []
    for p in passages:
        for bullet in _bullets(p.text):
            if p.section in INNOCENT:
                innocent.append(f"{bullet} [{p.id}]")
            elif p.section in NEXT_STEPS:
                steps.append(f"{bullet} [{p.id}]")

    if not innocent:
        innocent = ["No matching guidance was retrieved for this alert."]
    if not steps:
        steps = ["No matching guidance was retrieved for this alert."]
    sections = [
        Section(heading="Why it was flagged", items=why),
        Section(heading="Possible innocent explanations", items=innocent),
        Section(heading="Suggested next steps for the analyst", items=steps),
    ]
    if cases:
        sections.append(Section(
            heading="Similar past cases in this workspace",
            items=[f"Alert #{c.alert_id} was {c.status}: {c.comment} [{c.id}]" for c in cases],
        ))
    return sections