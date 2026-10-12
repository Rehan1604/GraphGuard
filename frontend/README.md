# GraphGuard dashboard

React + TypeScript + Vite + Tailwind. See the [project README](../README.md) for how to run everything.

```powershell
npm ci
npm run dev      # http://localhost:5173 (expects the API on http://localhost:8000)
npx vitest run   # tests
npm run build    # production build
```

The API address can be changed with `VITE_API_URL` (see `.env.example`).
