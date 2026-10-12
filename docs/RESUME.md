# Resume bullets (only measured facts)

Every number below was measured. Re-run the command in brackets before quoting it, because a number you cannot reproduce in front of an interviewer is a liability.

**Project line:** GraphGuard - synthetic-data transaction monitoring and investigation platform (FastAPI, React, TypeScript, SQLite, NetworkX, WebSockets, Docker)

**Bullets (pick 3-4):**
- Built a financial-transaction monitoring platform on synthetic data: 28 REST endpoints plus a sequenced WebSocket stream, with idempotent ingest and money stored as integer cents. [`/openapi.json` in development]
- Implemented four deterministic graph/time-window detection rules (pass-through chains, circular flows, bursts, many-counterparty fans) with a points-based 0-100 risk score and an auditable alert workflow requiring a comment to escalate or dismiss.
- Evaluated detectors on a labelled synthetic benchmark with benign look-alikes and near-misses: 72.0% precision (59/82) and 100% recall (40/40, by construction) versus a naive baseline at 23.2% precision (39/168) and 50.0% strict recall; precision stayed between 67.9% and 74.0% across 20 random seeds. [`python -m app.evaluation --seed 42` and `--seeds 20`]
- Added a grounded investigation assistant (retrieval + database facts + citation validation) that works with no API key and sends only pseudonymized ids when an optional LLM is configured.
- Hardened the service: startup config validation, structured logs with secret redaction, rate limiting, security headers, CORS allow-list, non-root Docker images and Compose; 244 backend tests (pytest) and 43 frontend tests (Vitest). [`python -m pytest -q`; `npx vitest run`]

**Do not write:** any accuracy on real data, "production-ready", "real-time at N events/sec", "detects fraud", latency or scale figures, "AI-powered detection" (detection is rules; the optional LLM only explains).

**If asked "is 100% recall impressive?"** No: the benchmark's planted patterns match the rules by design. Say so first, then talk about precision and the baseline comparison.

**Verification status when this was written:** backend tests passed on a Windows laptop; Docker Compose ran with the dashboard, API and live stream working on that laptop; frontend tests and build were run in a Linux workspace.
