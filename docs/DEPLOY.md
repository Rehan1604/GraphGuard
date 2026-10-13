# Deploying GraphGuard: Render (API) + Vercel (dashboard)

The API runs as a Docker service on **Render**. The dashboard is a static site on **Vercel**. Because the browser talks to the API directly, the two need to know each other's address. That is the only tricky part, so follow the order below.

> Everything here is synthetic data. The free tiers are fine for a demo, with the limits listed at the end.

## Order of operations
1. Push the repository to GitHub (done: `Rehan1604/GraphGuard`).
2. Deploy the API on Render, with the CORS settings left empty for now.
3. Deploy the dashboard on Vercel, pointing it at the API address.
4. Go back to Render and enter the Vercel address in the two CORS settings.

## 1. API on Render
1. Render dashboard, **New**, **Blueprint**, connect the GitHub repo. Render reads `render.yaml` and proposes a web service called `graphguard-api` (Docker, free plan).
2. It will ask for two values marked "sync: false". Enter a placeholder for now:
   - `GRAPHGUARD_CORS_ORIGINS` = `["http://localhost:5173"]`
   - `GRAPHGUARD_WS_ALLOWED_ORIGINS` = `["http://localhost:5173"]`
3. Create it and wait for the first deploy (a few minutes for the image build).
4. Copy the service address, such as `https://graphguard-api.onrender.com`. Check it:
   `https://graphguard-api.onrender.com/api/ready` should show `{"status":"ready","database":"ok"}`.

No secret is needed. The AI assistant is off, and the rule-based assistant works without a key.

## 2. Dashboard on Vercel
1. Vercel, **Add New**, **Project**, import the same GitHub repo.
2. **Root Directory:** `frontend`. Framework preset: Vite (detected). Build command and output are in `frontend/vercel.json`.
3. **Environment Variables:** add `VITE_API_URL` = your Render address, with no trailing slash, for example `https://graphguard-api.onrender.com`.
   This value is baked in at build time. If you change it later, redeploy.
4. Deploy. Copy your production address, such as `https://graphguard.vercel.app`.

## 3. Tell the API about the dashboard
In Render, open the service, **Environment**, and set both to your Vercel production address (scheme and host only, no path, no trailing slash, as a JSON list):

```
GRAPHGUARD_CORS_ORIGINS=["https://graphguard.vercel.app"]
GRAPHGUARD_WS_ALLOWED_ORIGINS=["https://graphguard.vercel.app"]
```
Save. Render restarts the service. Open the Vercel address, go to **Settings**, press **Start** on the simulation, and the **Live** badge on the Overview should turn green.

## If something is wrong
| Symptom | Likely cause and fix |
|---|---|
| Browser console: "blocked by CORS policy" | `GRAPHGUARD_CORS_ORIGINS` does not exactly match the Vercel address (check `https`, spelling, no trailing slash). |
| Live badge never goes green, WebSocket closes at once | `GRAPHGUARD_WS_ALLOWED_ORIGINS` is missing the Vercel address. Browsers do not apply CORS to WebSockets, so the API checks it separately. |
| Service will not start; logs say "Invalid configuration" | A setting is unsafe or malformed (for example a path in an origin, or `*`). The message names the setting. |
| Dashboard shows errors for about a minute, then works | The free API was asleep. Open `/api/ready` first and wait for it, then reload. |
| Works on the production address but not on a Vercel "preview" address | Preview deployments have different addresses. Only the production address is allowed. |
| `404` on `/docs` | Intended: API docs are switched off in production. |
| Deploy fails on port detection | `PORT` must be `8000`, matching the Dockerfile. `render.yaml` sets it. |

## Free-tier limits (read before demoing)
- **Cold starts.** Render's free service sleeps after 15 minutes without traffic and takes about a minute to wake. Open the API address before a demo.
- **The database is temporary.** Free Render services have no persistent disk, so the SQLite file is wiped on every redeploy, restart or sleep. The dashboard will start empty after a wake-up; press Start to regenerate synthetic data. For lasting data you would need Render Postgres, which this project does not use yet.
- **750 free hours per month**, shared by your free services.
- **One instance only**, which matches the design (the stream, simulator and rate limiter keep state in memory).

## Security notes for a public URL
- There is **no login**. Anyone with the address can press Start, Pause or Reset on the simulation. That only affects synthetic data on a temporary database, but do not post the link where you would not want that. Adding authentication is the next step before anything real.
- Rate limiting covers the expensive endpoints and relies on `FORWARDED_ALLOW_IPS=*`, which tells the app to trust the visitor address Render's proxy passes along. That is safe on Render, where only the proxy can reach the container. **Do not copy that setting to a host where the container is directly reachable from the internet**, because visitors could then fake their address.
- `vercel.json` sets basic security headers. It does not set a Content-Security-Policy, because that policy must name your API address. To add one, put your Render address in `connect-src` (use `https://` and `wss://` forms) once it is known.

## What was and was not tested
The configuration files are checked by automated tests (they parse, ports and paths agree, no secrets, every setting named is a real one), and the proxy setting was tested against a locally running server. **The actual Render and Vercel deployments have not been run by the author's tooling**: they need your accounts. If a deploy fails, paste the log and it can be fixed.
