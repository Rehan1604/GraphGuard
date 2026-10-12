from app.rag.models import Fact, Passage

SYSTEM_PROMPT = """You are an investigation-support assistant inside a transaction-monitoring tool that runs on synthetic data.

Rules you must follow:
1. Use ONLY the FACTS and GUIDANCE given below. Do not add outside knowledge about these accounts.
2. After every statement that comes from them, cite the source id in square brackets, like [F2] or [K1]. Cite only ids that exist.
3. Never state or imply that fraud, money laundering or any crime has happened. You may describe patterns and suggest what a human reviewer could check. The decision always belongs to a human.
4. Do not invent numbers, accounts, dates or reasons. If something is not in the sources, say it is not known.
5. Account names look like ACCT_A. Use them exactly as written.
6. Write plain text with exactly these three headings, each on its own line:
Why it was flagged
Possible innocent explanations
Suggested next steps for the analyst
Under each heading write short lines that start with "- ". Keep the whole answer under 250 words."""


def build_user_prompt(question: str, facts: list[Fact], passages: list[Passage]) -> str:
    fact_lines = "\n".join(f"[{f.id}] {f.text}" for f in facts)
    guidance_lines = "\n".join(
        f"[{p.id}] ({p.title}, section: {p.section})\n{p.text}" for p in passages
    )
    return (
        f"QUESTION FROM THE ANALYST:\n{question}\n\n"
        f"FACTS (verified from the transaction database):\n{fact_lines}\n\n"
        f"GUIDANCE (from the educational procedure library; general, not about these accounts):\n{guidance_lines}\n\n"
        "Answer the question using the three headings."
    )