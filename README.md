# PR-Guard

GitHub App that analyzes a pull request, finds changed TypeScript functions without
tests, writes Vitest tests, **executes them in an isolated Docker sandbox**, and only
posts the tests that actually passed.

> Full docs land in Phase 10. See `ARCHITECTURE.md`, `PROGRESS.md`, `DECISIONS.md`.

## Quickstart (development)

```bash
cp .env.example .env
cd backend
python -m venv ../.venv
../.venv/Scripts/pip install -e ".[dev]"     # Windows
../.venv/Scripts/python -m pytest --cov=app  # 90% gate
```

Docker Compose (requires Docker):

```bash
docker compose up --build
```

The API is on <http://localhost:8000> (`/healthz`, `/docs`).
