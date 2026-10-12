# GraphGuard

An educational financial-transaction monitoring and investigation platform that runs on **synthetic data only**.
It finds *patterns for human review*. An alert is never an accusation.

Everything core works with **no API key and no internet**. The AI assistant is optional.

## Documents
- [Architecture](docs/ARCHITECTURE.md) - diagram and design decisions
- [Demo script](docs/DEMO.md) - three minutes
- [Trade-offs and limitations](docs/TRADEOFFS.md)
- [Interview Q&A](docs/INTERVIEW.md)
- [Resume bullets](docs/RESUME.md) - measured numbers only

## What it does
- Stores accounts and transactions (money as integer cents, UTC timestamps, idempotent ingest).
- Detects four patterns with deterministic, configurable rules: pass-through chains, circular flows, transfer bursts, many-counterparty fans. Each gets a points-based 0-100 score (not a probability).
- Turns findings into alerts with a review workflow (new / in review / escalated / dismissed), notes and an append-only history.
- Streams simulated live activity over a WebSocket.
- Explains alerts with a grounded assistant (facts from the database + guidance from a small library; rule-based fallback; optional LLM).
- Measures itself on a labelled synthetic benchmark (precision, recall, F1, baseline comparison).

## Run it on Windows (PowerShell)
Backend:
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest -q
uvicorn app.main:app --reload --port 8000
```
Frontend (second window):
```powershell
cd frontend
npm ci
npm run dev
```
Open http://localhost:5173. API docs (development only): http://localhost:8000/docs

## Run with Docker
```powershell
docker compose up --build
```
Dashboard http://localhost:5173, API http://localhost:8000. Ports are bound to `127.0.0.1` (this computer only).
The Docker files have been checked by tests that read them, but **have not been run by the author's tooling** - if `docker compose up --build` fails on your machine, that is a bug to report.

## Configuration
Copy `.env.example` to `.env`. Every variable is optional in development; `.env.example` lists them all.
In production the app refuses to start on unsafe settings (wildcard CORS, bad origins, AI provider without a model or key).
Never commit `.env`. Keys are read from the environment and are never logged (logs report only whether a key is present).

## Tests
- Backend: `cd backend; python -m pytest -q`
- Frontend: `cd frontend; npm run lint; npx vitest run; npm run build`
- Benchmark: `cd backend; python -m app.evaluation`

## API (all under `/api` unless noted)
| Area | Endpoints |
|---|---|
| Health | `GET /api/health` (alive), `GET /api/ready` (database usable) |
| Data | `POST/GET /accounts`, `POST/GET /transactions`, `GET /stats`, `GET /graph` |
| Detection | `POST /detection/run`, `GET /detection/config` |
| Alerts | `POST /alerts/scan`, `GET /alerts`, `GET /alerts/{id}`, `POST /alerts/{id}/notes`, `POST /alerts/{id}/status` |
| Simulation | `GET /simulation`, `POST /simulation/start|pause|resume|reset`, WebSocket `/ws/events` |
| Assistant | `GET /assistant/status`, `POST /alerts/{id}/assistant`, `GET /knowledge` |
| Evaluation | `GET /evaluation` |

## Security and reliability
Request ids on every response, JSON logs with secret redaction, access log without query strings, request size limit,
per-client rate limit on expensive endpoints (429 + Retry-After), generic error responses, security headers,
CORS allow-list (no credentials), docs off in production, non-root containers.

## Known limitations (read before quoting numbers)
- **Synthetic data only.** Benchmark scores describe how the rules perform on data written by the same author; they say little about real-world accuracy.
- Recall on the benchmark is 100% by construction (the planted patterns match the rules); precision is the informative number.
- **One server process.** The live stream, simulator and rate limiter keep state in memory, so do not run multiple workers.
- The rate limiter is per-process and keyed by client address (behind a proxy, all users may share one address).
- The body-size limit checks the `Content-Length` header; it does not stop a chunked upload without one.
- SQLite is single-writer: fine for a demo, not for heavy concurrent load.
- No authentication or user accounts.
- No performance or throughput figures have been measured.
