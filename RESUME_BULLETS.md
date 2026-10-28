# Resume bullets, pitch and interview answers

Everything below uses measured values from this repository. No percentage-improvement,
user-count or latency claim is invented. Each bullet points to the command or file that
produced it.

## Resume bullets

- **Built PR-Guard, a GitHub App that makes LLM-generated Vitest tests earn their way into a
  pull request.** It parses changed TypeScript functions with tree-sitter, uses Istanbul
  function-hit counts to find real gaps, and publishes only tests that pass in a sandbox and
  execute the target function. Backed by **426 passing backend tests** (1 skipped real-Docker
  test) at **95.16% branch-aware coverage**.
  *Source: `README.md` verification table; reproduce with `cd backend && pytest -q --cov=app`.*

- **Implemented a verification gate that separates generation from trust.** Generated code is
  statically validated, installed once, executed with the network disabled in Docker, checked
  against per-file Vitest results and coverage, repaired through a capped fixer, and persisted
  as six auditable steps. The real local smoke produced **1 verified test**, moved coverage
  **78.57% → 100.00%**, and recorded **9,246 ms**, **2 `FakeLLM` calls** and **1,294 tokens**.
  *Source: `dashboard/public/demo-data/manifest.json`, `details.json`; reproduce with
  `backend/scripts/demo_smoke.py`.*

- **Shipped a zero-backend demo dashboard on Vercel from genuine local captures.** Added a
  build-time JSON loader behind `NEXT_PUBLIC_DEMO_MODE=true`, a permanent provenance banner
  (capture date, commit, fakes, sandbox mode), disabled live actions, and a no-backend
  Playwright journey. **34 dashboard tests** pass at **98.18% statements / 92.30% branches /
  100% functions / 99.25% lines**; **4 demo E2E tests** pass on desktop and mobile with zero
  `/api/` requests.
  *Source: `dashboard/tests/demo.test.tsx`, `dashboard/e2e/demo/demo.spec.ts`,
  `dashboard/coverage/coverage-summary.json` (generated locally by `npm run test:coverage`).*

- **Added CI, sanitization and supply-chain checks before calling it done.** CI runs backend
  lint/tests/coverage, the demo build, live-mode E2E and the no-backend demo E2E. The capture
  exporter strips local paths and secret-named keys and refuses output that matches a secret
  pattern; a full-history gitleaks scan covered **10 commits / 940,184 bytes with no leaks**,
  and `npm audit` reports **0 vulnerabilities**.
  *Source: `.github/workflows/ci.yml`, `scripts/capture_demo_data.py`, `README.md`.*

## 60-second pitch

"I built PR-Guard because 'the LLM wrote a test' is not evidence that the test is any good.
It is a GitHub App for TypeScript repos: when a PR adds a function the existing suite never
executes, it asks an LLM for a focused Vitest test, then treats that code as hostile. The
test has to pass inside a network-disabled Docker sandbox and actually hit the target
function before it reaches the PR. Everything else is reported as unverified with a reason.
The orchestration is a LangGraph state machine over a durable SQLite job queue, and every
step, token and sandbox log is persisted to a read-only Next.js dashboard.

I verified what I could locally: 426 backend tests, a real npm/Vitest smoke run that moved
coverage from 78.57% to 100%, and a public Vercel demo that replays one sanitized capture
with no backend, no secrets and a permanent banner saying exactly what is fake. Docker,
live GitHub and live model calls are the parts I have not been able to run, and I say that
before anyone asks."

## Five hardest questions, answered honestly

### 1. "Did you actually run this against Docker, GitHub and a real LLM?"

No. Docker was not installed on the build machine, so the real-daemon test is **skipped**,
not passed; no image built and Compose never started. GitHub and the LLM are faked in the
processor tests and the smoke run (`FakeLLM`, in-process fake GitHub). The parts that are
real are the Python orchestration, npm install, Vitest execution, Istanbul parsing, SQLite
persistence and the static dashboard. The README, manifest and UI all name those boundaries.
I would not claim production readiness until the Docker and live-provider paths run.

### 2. "How do you stop a malicious test or a prompt injection?"

Defence in depth, with one honest gap. Repository content is wrapped as untrusted data and
closing tags are neutralised before it enters a prompt. Generated code is path-contained,
must be a test file, has size/line limits, must contain assertions, and is rejected for
forbidden modules/APIs against an import allow-list. But the static policy is **not** the
security boundary; the container is: no network in the test phase, non-root uid 10001,
read-only root, workspace-only rw mount, `cap_drop=ALL`, `no-new-privileges`, memory/CPU/PID
limits, noexec tmpfs, timeout and unconditional removal. The residual risk is a kernel or
Docker escape, which is why I call the sandbox the boundary rather than the linter.

### 3. "Why is coverage authoritative? What if the target repo has no coverage?"

When baseline Istanbul data exists, PR-Guard looks up the target function's hit count in the
PR-head coverage report. A passing test that never executes the function is rejected. When
coverage is unavailable, it falls back to test-file references for gap selection, and the
baseline step records that coverage was not measured instead of pretending it was. The
limitation is that the fallback is weaker: a file reference does not prove the function ran.
The UI reports the measured delta only when a baseline and post-run report both exist.

### 4. "What was the hardest correctness problem?"

Idempotency and publication, not generation. A webhook can arrive twice, and the same commit
can be pushed twice; spending LLM budget twice or posting two comments is a real failure.
`runs` has a unique `(repo_full_name, head_sha)` constraint, delivery ids are unique, and the
run + job are inserted in one transaction; a concurrent `IntegrityError` is resolved by
looking up the winner. The remaining gap is the comment window: if GitHub accepts a comment
and the process dies before storing the id, a retry can duplicate it. The documented fix is
to list comments and match a hidden marker, then update instead of create.

### 5. "Why is the public demo a recording? Isn't that less impressive?"

It is less capable and more honest. A live deployment would need a GitHub App installation,
a provider key, a Docker host and a public webhook; none were available, and exposing them
would add cost and attack surface. Instead I exported one genuine local run through the same
Pydantic models as the API, sanitized paths/secrets, and built a static dashboard with a
permanent banner naming the date, commit, `FakeLLM`, fake GitHub and `LocalSandboxRunner`.
The demo has no backend and the E2E suite fails if the browser makes an `/api/` request. I
would rather show a smaller, labelled artifact than imply a live service exists.

## Real limitations to say out loud

- **Docker is unverified here.** No container, image build or Compose run; the real-daemon
  test is skipped.
- **No live GitHub or provider calls.** Adapters use fakes and `httpx.MockTransport`.
- **No GitHub Actions run yet.** The workflow is committed and the local equivalents pass.
- **The public demo is a replay of one sanitized run**, not a live service. It has no
  authentication because it contains only the `acme/prguard-demo` fixture.
- **`LocalSandboxRunner` is not a security boundary.** It runs Node as the host user with
  network access and reports `network_disabled=False`.
- **Single-instance design.** One worker and SQLite; production needs Postgres, multiple
  workers and a dedicated sandbox runner.
- **Vitest only.** No Playwright generation for target repos; UI tests are opt-in jsdom.
- **No screen recording yet.** The shot list and embed location are documented, but the video
  does not exist.

## Where the numbers come from

| Claim | Source / command |
| --- | --- |
| 426 passed, 1 skipped, 95.16% | `cd backend && pytest -q --cov=app`; table in `README.md` |
| 34 dashboard tests, coverage percentages | `cd dashboard && npm run test:coverage`; generated `coverage/coverage-summary.json` |
| 4 demo E2E, zero backend calls | `cd dashboard && npm run test:e2e:demo`; `e2e/demo/demo.spec.ts` |
| 3 live-mode E2E | `cd dashboard && npm run test:e2e`; mock API |
| 1 verified test, 78.57% → 100.00%, 9,246 ms, 2 calls, 1,294 tokens | `scripts/capture_demo_data.py`; committed `dashboard/public/demo-data/` |
| 10 commits / 940,184 bytes / 0 leaks | `gitleaks git . --log-opts=--all` (local gitleaks 8.30.1) |
| 0 npm vulnerabilities | `npm audit` in `dashboard/` and `demo-repo/` |
| Docker not verified | real-daemon test is skipped; no daemon on the build machine |
