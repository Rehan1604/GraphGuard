from app.rag.models import CaseMatch, Fact, Passage

SYSTEM_PROMPT = """You are an investigation-support assistant inside a transaction-monitoring tool that runs on synthetic data.

Rules you must follow:
1. Use ONLY the FACTS and GUIDANCE given below. Do not add outside knowledge about these accounts.
2. After every statement that comes from them, cite the source id in square brackets, like [F2], [K1] or [C1]. Cite only ids that exist.
3. Never state or imply that fraud, money laundering or any crime has happened. You may describe patterns and suggest what a human reviewer could check. The decision always belongs to a human.
4. Do not invent numbers, accounts, dates or reasons. If something is not in the sources, say it is not known.
5. Account names look like ACCT_A. Use them exactly as written.
6. Write plain text with exactly these three headings, each on its own line:
Why it was flagged
Possible innocent explanations
Suggested next steps for the analyst
Under each heading write short lines that start with "- ". Keep the whole answer under 250 words."""


def build_user_prompt(question: str, facts: list[Fact], passages: list[Passage], cases: list[CaseMatch] | None = None) -> str:
    fact_lines = "\n".join(f"[{f.id}] {f.text}" for f in facts)
    guidance_lines = "\n".join(
        f"[{p.id}] ({p.title}, section: {p.section})\n{p.text}" for p in passages
    )
    # Past cases: ONLY the outcome is sent. The reviewer's comment stays on this computer.
    case_lines = "\n".join(f"[{c.id}] A past alert of the same pattern in this workspace was {c.status}." for c in cases or [])
    case_block = f"SIMILAR PAST CASES (outcome only):\n{case_lines}\n\n" if case_lines else ""
    return (
        f"QUESTION FROM THE ANALYST:\n{question}\n\n"
        f"FACTS (verified from the transaction database):\n{fact_lines}\n\n"
        f"GUIDANCE (from the educational procedure library; general, not about these accounts):\n{guidance_lines}\n\n"
        f"{case_block}"
        "Answer the question using the three headings."
    )