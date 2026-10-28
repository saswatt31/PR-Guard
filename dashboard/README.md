# PR-Guard dashboard

Read-only Next.js 15 console for persisted PR-Guard runs. The FastAPI service owns all
writes; in live mode this app only calls `GET /api/runs`, `GET /api/runs/{id}`,
`GET /api/stats` and `GET /api/demo`.

## Demo mode (public Vercel deployment)

```bash
NEXT_PUBLIC_DEMO_MODE=true npm run build
npm run start
```

`NEXT_PUBLIC_DEMO_MODE=true` makes every data accessor read the committed JSON under
`public/demo-data/` with **zero backend calls and zero secrets**. The banner, disabled live
links and capture metadata come from `public/demo-data/manifest.json`.

The JSON is not hand-written. It is exported from a real local pipeline run:

```bash
# from the repository root
.venv/Scripts/python.exe scripts/capture_demo_data.py
# or export an existing data/demo.db without re-running the pipeline
.venv/Scripts/python.exe scripts/capture_demo_data.py --no-smoke
```

The default capture runs `backend/scripts/demo_smoke.py`: real worker, real npm install,
real Vitest and real SQLite persistence. It uses `FakeLLM`, fake GitHub and
`LocalSandboxRunner`; those caveats are written into the manifest and shown in the banner.
It is **not** a Docker, live-GitHub or live-LLM run.

Vercel settings for this app:

| Setting | Value |
| --- | --- |
| Root Directory | `dashboard` |
| Framework Preset | Next.js |
| Build Command | `npm run build` (default) |
| Output Directory | `.next` (default) |
| Environment Variable | `NEXT_PUBLIC_DEMO_MODE=true` |

No `vercel.json` is required. Do not add `PRGUARD_API_URL` or any secret to the demo
project.

## Local development (live backend)

```bash
npm ci
PRGUARD_API_URL=http://localhost:8000 npm run dev
```

Open <http://localhost:3000>. `PRGUARD_API_URL` is used by server components, so the API
can stay on a private network. `NEXT_PUBLIC_API_URL` is only a fallback for local
development and the API-docs link.

## Checks

```bash
npm test                     # Vitest + React Testing Library
npm run test:coverage        # 90% statement/line gate, 85% branches
npm run typecheck
npm run build
npm run test:e2e             # mock API + Next build
npm run test:e2e:demo        # demo build + no-backend journey, desktop and mobile
```

The live-mode Playwright suite uses `e2e/mock-api.mjs`, a deterministic fixture server. It
verifies rendering and navigation, not live FastAPI or GitHub integration. Backend API
behaviour is covered by `backend/tests/test_api.py`.

The demo-mode suite uses `e2e/demo/demo.spec.ts` and points `PRGUARD_API_URL` at a closed
port. It asserts that the browser makes no `/api/` requests.

## Container

`Dockerfile` builds Next standalone output (`NEXT_OUTPUT_STANDALONE=1`) and runs it as uid
1001. The Compose service passes `PRGUARD_API_URL=http://api:8000` and publishes port 3000.

The dashboard has no authentication in this build. Put it behind SSO/VPN or a reverse-proxy
allow-list before exposing it; it displays repository names, test code and sandbox logs.
The public demo contains only the sanitized `acme/prguard-demo` fixture.
