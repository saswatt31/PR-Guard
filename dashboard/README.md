# PR-Guard dashboard

Read-only Next.js 15 console for persisted PR-Guard runs. The FastAPI service owns all
writes; this app only calls `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/stats` and
`GET /api/demo`.

## Local development

```bash
npm ci
PRGUARD_API_URL=http://localhost:8000 npm run dev
```

Open <http://localhost:3000>. `PRGUARD_API_URL` is used by server components, so the API
can stay on a private network. `NEXT_PUBLIC_API_URL` is only a fallback for local
development and the API-docs link.

## Checks

```bash
npm test                 # Vitest + React Testing Library
npm run test:coverage    # 90% statement/line gate, 85% branches
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e         # builds, starts the mock API + Next, runs Chromium
```

The Playwright suite uses `e2e/mock-api.mjs`, a deterministic fixture server. It verifies
rendering and navigation, not live FastAPI or GitHub integration. Backend API behaviour is
covered by `backend/tests/test_api.py`.

## Container

`Dockerfile` builds Next standalone output and runs it as uid 1001. The Compose service
passes `PRGUARD_API_URL=http://api:8000` and publishes port 3000.

The dashboard has no authentication in this build. Put it behind SSO/VPN or a reverse-proxy
allow-list before exposing it; it displays repository names, test code and sandbox logs.
