# Interview Q&A (say it out loud)

Short answers first. Add detail only if they ask.

## The big picture
1. **What is GraphGuard?** A tool that watches synthetic money transfers and flags patterns a human should review, such as money moving in a chain or circle. It flags patterns, it doesn't accuse.
2. **Why did you build it?** To practise building a whole system end to end: data, detection, workflow, real-time, UI, evaluation, deployment, with honest measurement.
3. **Why synthetic data?** Real transaction data is private. Synthetic data is safe, repeatable, and I know the ground truth, so I can measure.
4. **Is this used by a bank?** No. It is an educational project.

## Detection
5. **How does detection work?** I build a graph where accounts are nodes and transfers are edges, then run four rules: pass-through chain, circular flow, burst, and fan.
6. **Why rules, not machine learning?** There is no real labelled data, and rules are explainable: each alert says which rule fired and why.
7. **What is a pass-through chain?** Money enters an account and leaves soon after, again and again, like a relay.
8. **How do you find cycles?** Depth-first search over the transfer graph with limits on length and time. A loop only counts if its smallest transfer is at least 80% of its largest, because a real round trip brings back about the same money. Loops that are the same route are de-duplicated.
9. **What does the risk score mean?** Points from the rules, capped at 100. Low under 40, medium 40-69, high 70+. It is not a probability.
10. **How do you avoid duplicate alerts?** Each finding gets a fingerprint hash. If the same pattern appears again, the existing alert is updated when its evidence grows.
11. **What bug did evaluation find?** One loop was reported seven times because of parallel transfers. I fixed it by treating the same route as one loop.

## Data and correctness
12. **Why integer cents?** Floating point can't store money exactly; 0.1 + 0.2 is not 0.3.
13. **What is idempotent ingest?** Sending the same transaction twice is safe. Same id and same body returns OK; same id with a different body is rejected with 409.
14. **Why UTC timestamps?** One timezone avoids ordering bugs.
15. **Why SQLite?** Zero setup for a demo. The cost is a single writer.

## Alerts and workflow
16. **What states can an alert have?** New, in review, escalated, dismissed. Escalate or dismiss requires a comment.
17. **Why append-only history?** Auditability: you can see who changed what, and when.
18. **Why keep notes separate from evidence?** Evidence is what the system found; notes are human opinion. Mixing them would blur the audit trail.

## Real-time
19. **How does live data reach the browser?** A WebSocket. Each event has a sequence number; if the browser reconnects it asks for what it missed, or does a full resync if the gap is too large.
20. **Why do you check the Origin on the WebSocket?** Browsers don't apply CORS to WebSockets, so I check it myself.

## Assistant (RAG)
21. **What is RAG here?** Retrieval-augmented generation: find relevant guidance text, combine with facts from the database, then explain.
22. **How do you stop it making things up?** Facts are computed from the database and labelled F1, F2...; guidance is labelled K1...; citations are validated; accusatory wording is flagged. A rule-based fallback is used when no model is set.
23. **What leaves your machine if an LLM is configured?** Pseudonymized ids (ACCT_A, ...) and facts. Names, notes and analyst names are never sent.
24. **Why TF-IDF and not embeddings?** Offline, deterministic, and good enough for six short documents. Embeddings would help for paraphrase.

## Evaluation
25. **How good is it?** On my synthetic benchmark (seed 42): precision 52/70 (74.3%), recall 40/40. Across 20 seeds precision was 66.7%-74.6%, and 69.4%-75.0% on 20 seeds I kept aside. The baseline got 23.2% precision.
26. **Isn't 100% recall suspicious?** Yes: the planted patterns match the rules by design. It proves the rules do what I wrote, not that they work on real data.
27. **What would make the evaluation more convincing?** Independently written test cases, public datasets with labels, and a person other than me labelling.
28. **What are the false positives?** Mostly benign look-alikes: payroll that looks like a fan, split bills that look like a loop, payouts that look like a chain. 16 of 18 on seed 42.

## Engineering and operations
29. **What did you do for security?** Config validation, secrets only from the environment and masked in logs, CORS allow-list, rate limiting, request-size limit, security headers, docs off in production, non-root containers.
30. **Liveness vs readiness?** Liveness: process is up. Readiness: it can do real work, which means the database works.
31. **Why one worker?** State is in memory. Scaling out needs a shared store.
32. **What would you do next?** Authentication, Postgres, a shared queue/Redis, independent test data, and more rules guided by real analysts.
33. **What is your biggest limitation?** The data is synthetic, so I can't claim real-world accuracy.
34. **What did you learn?** That my first tests passed on one system and hid a bug on another. I now test on the platform I ship to.
35. **You said precision was about 72%. Did you improve it?** I looked at the false alarms before changing anything. Two were genuine defects: random loops of unrelated payments counted as cycles, and one burst was reported twice. Fixing them removed all the false alarms from ordinary background traffic and took the simulator stream from 16/21 to 13/13. But headline precision on 20 held-out seeds stayed at about 72%, because the rest are benign look-alikes the rules cannot tell apart. I did not tune thresholds until my own look-alikes disappeared, since that would only fit my benchmark.
36. **Why did a recall drop appear mid-change?** My first version applied the amount check after choosing one loop per route, so an unrelated payment on the same route could be chosen, rejected, and hide the real loop. One of 800 planted patterns was missed. Moving the check before the selection fixed it, and there is a test for it.
37. **How would you really raise precision?** Add a new signal: whether the accounts have a history of regular payments (payroll recurs, laundering usually doesn't). That needs history and better data than my synthetic set.
