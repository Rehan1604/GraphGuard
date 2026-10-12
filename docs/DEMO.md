# Three-minute demo

Set up before the call: `docker compose up --build` (or run backend and frontend directly), open http://localhost:5173, make sure the simulation is **stopped** and the database is empty (`docker compose down -v` wipes it).

**0:00 - The idea (20 s).** "Banks watch transfers for patterns that deserve a human look, like money passing through accounts in a chain or going in circles. GraphGuard does that on synthetic data, and it flags patterns for review, never accuses anyone."

**0:20 - Start the stream (30 s).** Press start. Point at the green *Live* badge and the counters rising. "Events arrive over a WebSocket with sequence numbers, so if the connection drops it can resync."

**0:50 - An alert (40 s).** Open Alerts, pick a circular flow. Show the path, the score and the evidence. "The score is points from rules, capped at 100. It is not a probability."

**1:30 - Review workflow (30 s).** Try to dismiss without a comment (blocked). Add a comment, dismiss, show history. "Every change is recorded and a reason is required."

**2:00 - Assistant (30 s).** Ask "Why was this flagged?" Show facts F1.. and guidance K1.., then the fallback label. "No key needed. If a model is configured, ids are replaced by aliases first."

**2:30 - Honesty slide (30 s).** Open Evaluation. "On my synthetic benchmark the rules find all planted patterns but only about 71% of what they flag matches one. Recall is 100% by construction. I report that limitation instead of hiding it."

Backup if the live demo breaks: the screenshots in your notes, and `python -m app.evaluation --seed 42` in a terminal.
