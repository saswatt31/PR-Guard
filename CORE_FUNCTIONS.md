# Core functions

This is a guided tour of the functions that carry the most risk, in the order a real
pull request moves through the system. Each entry gives the signature, the behaviour that
matters, the failure handling, and the tests that exercise it.

> Evidence legend
>
> - **Executed locally:** the Python suite, the Next.js suite/build/E2E, the demo suite and
>   the local smoke were run on the development machine.
> - **Mocked:** GitHub, LLM providers and the Docker daemon are replaced by fakes or
>   `httpx.MockTransport` in tests.
> - **Not verified:** no real Docker container, live GitHub App installation, live Groq or
>   Anthropic call, or GitHub Actions run has been executed. Functions that depend on
>   those services are described as designed, not as proven end to end.
>
> Latest measured numbers: backend **426 passed, 1 skipped, 95.16%**; dashboard **34
> passed**, 98.18% statements / 92.30% branches / 100% functions / 99.25% lines; demo
> E2E **4 passed** with no backend; demo repo **11 passed, 100%**. The single skip is the
> real-Docker-daemon test.

## Map

| Area | Function | File | Why it matters |
| --- | --- | --- | --- |
| Ingress | `verify_signature` | `backend/app/webhooks/signature.py` | Authenticates every webhook before JSON parsing. |
| Ingress | `process_event` | `backend/app/webhooks/handler.py` | Deduplicates deliveries/commits and owns the enqueue transaction. |
| Queue | `claim_next_job` | `backend/app/queue/worker.py` | Atomic claim; prevents two workers processing one run. |
| Queue | `reclaim_stale_jobs` | `backend/app/queue/worker.py` | Recovers crashes without looping forever. |
| GitHub | `build_app_jwt` | `backend/app/github/auth.py` | Signs the short-lived App JWT. |
| GitHub | `GitHubClient.installation_token` | `backend/app/github/client.py` | Exchanges the JWT for a cached installation token. |
| GitHub | `safe_extract_tarball` | `backend/app/github/repo.py` | Turns an untrusted archive into a workspace without traversal or bombs. |
| Diff | `parse_diff` | `backend/app/diff/parser.py` | Extracts changed new-file lines from unified diffs. |
| Diff | `extract_functions` | `backend/app/diff/extract.py` | Tree-sitter extraction of importable TS/JS functions. |
| Diff | `analyze_diff` | `backend/app/diff/analyzer.py` | Joins diff paths to the checked-out tree safely. |
| Coverage | `parse_istanbul_coverage` | `backend/app/coverage/istanbul.py` | Turns Istanbul JSON into function hit counts. |
| Coverage | `CoverageReport.function_hits` | `backend/app/coverage/istanbul.py` | Correlates a function with its measured executions. |
| Coverage | `find_gaps` | `backend/app/coverage/gap.py` | Chooses what is untested, using coverage first and references second. |
| Config | `load_repo_config` | `backend/app/config/repo.py` | Validates untrusted `.prguard.yml` before it can influence commands. |
| LLM | `BudgetedLLM.complete` | `backend/app/llm/budget.py` | Enforces per-run call/token/cost caps. |
| Graph | `build_agent_graph` | `backend/app/agents/graph.py` | Declares the deterministic control flow and retry cap. |
| Graph | `run_agent_pipeline` | `backend/app/agents/graph.py` | Converts graph state into a typed result, including cost and coverage. |
| Graph | `_write_node` | `backend/app/agents/graph.py` | Turns gaps into written, statically checked drafts. |
| Graph | `_execute_node` | `backend/app/agents/graph.py` | Verifies drafts against Vitest and coverage; the trust decision. |
| Graph | `_fix_node` | `backend/app/agents/graph.py` | Bounded repair loop; only failed drafts are rewritten. |
| Safety | `validate_proposal` | `backend/app/agents/safety.py` | Static policy before code reaches the workspace. |
| Safety | `write_test_proposal` | `backend/app/agents/safety.py` | Refuses writes outside the repository or over symlinks. |
| Results | `parse_vitest_results` | `backend/app/agents/results.py` | Maps per-file Vitest outcomes to specific drafts. |
| Sandbox | `DockerSandboxRunner.run` | `backend/app/sandbox/docker.py` | Applies the security controls and returns a typed result. |
| Sandbox | `validate_command` / `validate_executable` | `backend/app/sandbox/security.py` | Rejects shell strings, NULs and non-allow-listed binaries. |
| Orchestration | `RunProcessor.process` | `backend/app/run_processor.py` | Owns one run from download to cleanup. |
| Orchestration | `RunProcessor._baseline` | `backend/app/run_processor.py` | Measures the PR's own coverage before generation. |
| Orchestration | `RunProcessor._persist` | `backend/app/run_processor.py` | Replaces child rows atomically on retry. |
| Orchestration | `RunProcessor._post_comment` | `backend/app/run_processor.py` | Posts one verified-only comment and records its id. |
| Comment | `format_pr_comment` | `backend/app/comment.py` | Renders only verified tests and bounded unverified reasons. |
| API | `list_runs` | `backend/app/api/routes.py` | Validated filtering/pagination for the dashboard. |
| API | `get_run` | `backend/app/api/routes.py` | One query with eager-loaded child records. |
| Dashboard | `getRuns` / `getRun` / `getStats` | `dashboard/lib/api.ts` | Server-side API access with typed errors; switches to static data in demo mode. |
| Demo | `getDemoRuns` / `getDemoRun` / `getDemoStats` | `dashboard/lib/demo.ts` | Pure in-process filtering and lookup over committed JSON. |
| Demo | `DemoBanner` | `dashboard/components/DemoBanner.tsx` | Permanent provenance: date, commit, fakes and links. |
| Demo | `capture_demo_data` | `scripts/capture_demo_data.py` | Exports and sanitizes a genuine local run into the API shape. |
| Demo | `execute` | `backend/scripts/demo_smoke.py` | The only end-to-end execution available without Docker. |

---

## 1. Webhook ingress

### `verify_signature(payload, signature_header, secret) -> bool`

`backend/app/webhooks/signature.py`

```python
payload: bytes
signature_header: str | None   # "sha256=<64 hex>"
secret: str
```

Computes `HMAC-SHA-256(secret, raw_body)` and compares it with
`hmac.compare_digest`. It deliberately returns `False` instead of raising for missing,
empty, malformed or wrong-length headers so the route can return one uniform 401.

The route reads the body through a size-limited stream **before** verification, then
verifies **before** `json.loads`. Re-serialising the JSON would change the bytes and break
the signature. Empty payloads and empty secrets are rejected.

- **Failure:** `False` -> HTTP 401; body over `MAX_WEBHOOK_BYTES` -> HTTP 413.
- **Tests:** `backend/tests/test_signature.py` covers valid, invalid, missing prefix,
  wrong length, empty body/secret and uppercase hex.
- **Interview angle:** why constant-time comparison matters, and why the raw body is the
  only correct input.

### `process_event(db, settings, *, event, payload, payload_bytes, delivery_id) -> WebhookOutcome`

`backend/app/webhooks/handler.py`

The FastAPI-independent business transaction:

1. `ping` -> `pong`; any event other than `pull_request` -> `ignored_event`.
2. Only `opened` and `synchronize` are accepted.
3. A `delivery_id` already present -> `duplicate_delivery`, returning the existing run id
   when available.
4. Pydantic validates the payload shape. Validation errors become
   `InvalidPayloadError` without echoing attacker data.
5. Fork policy: if `is_fork` and `!settings.allow_fork_prs`, the run is created as
   `skipped` with a human summary and **no job**.
6. Otherwise `Delivery`, `Run` and `Job(pending)` are inserted in one session. The
   `(repo_full_name, head_sha)` unique index (`uq_runs_repo_head`) returns
   `duplicate_commit` without spending again.
7. `IntegrityError` is treated as a concurrent race; the unique indexes win and the
   duplicate lookup is retried.

Because the job row commits with the run, a crash after the 202 cannot lose the work.
Because deduplication is a unique index rather than an in-memory set, it survives restarts.

- **Tests:** `backend/tests/test_webhooks.py` (ping, unsupported event/action, fork skip,
  duplicate delivery, duplicate commit, invalid payload, concurrent race).
- **Interview angle:** why the handler is separate from FastAPI, and why both delivery and
  commit identity are deduplicated.

### `github_webhook(request)`

`backend/app/webhooks/routes.py`

Reads a bounded stream, verifies the signature, requires `X-GitHub-Event` and
`X-GitHub-Delivery`, parses JSON, and calls `process_event` in the threadpool. Returns
`202` for every accepted/duplicate/skipped outcome, `200` only for `ping`, and `400`/`401`/
`413` for bad input. The response contains only `status`, optional `run_id` and optional
`reason`; no payload is reflected.

---

## 2. Durable queue

### `claim_next_job(db) -> Job | None`

`backend/app/queue/worker.py`

Selects the oldest `pending` job ordered by `(created_at, id)`, sets it to `processing`,
increments `attempts`, records `started_at`, and moves its run to `running`. The transaction
is short and uses SQLite's single-writer property. The returned job is expunged so the
caller can read it after the session closes.

The docstring notes the production alternative: Postgres `SELECT ... FOR UPDATE SKIP
LOCKED`. There is exactly one worker in this deployment, so a database-level claim plus the
single-process loop is sufficient.

### `reclaim_stale_jobs(db, settings) -> int`

A job is stale when its `started_at` is older than
`install_timeout + test_timeout * job_max_attempts + 120s`. Below the attempt cap it is
returned to `pending` and the run to `queued`; at the cap it is failed with an explicit
reason. This is a crash-recovery mechanism, not a retry policy for application errors:
ordinary run failures are finished by `_finish_job` and do not become pending again.

### `Worker.process_once() -> bool` and the loop

`process_once` claims one job, awaits the processor, and always finishes the job row:
success -> `done` and run `succeeded` unless it was already failed/skipped; exception ->
`failed` with `TypeError: message` in `runs.error`. `CancelledError` is re-raised so
shutdown is not recorded as a normal failure. The loop reclaims stale jobs once, then
polls with a stop-event wait. `start`/`stop` are idempotent and bound shutdown at 10s.

- **Tests:** `backend/tests/test_worker.py` covers claim ordering, success/failure,
  cancellation, stale reclaim below/at the cap, start/stop and the processor exception path.
- **Interview angle:** why a durable row beats `BackgroundTasks`, and what remains unsafe
  with more than one worker.

---

## 3. GitHub boundary

### `build_app_jwt(app_id, private_key, *, now=None) -> str`

Signs RS256 with `iat = now - 60` (clock-skew tolerance) and `exp = now + 540`, with `iss`
as a **string** because PyJWT requires a string issuer. Missing app id/key raises
`GitHubAuthError`; any signing error is normalised to the same error without leaking key
material.

- **Tests:** `backend/tests/test_github_auth.py` decodes the token and checks claims,
  expiry and error paths.
- **Interview angle:** App JWT vs installation token; why the JWT is short-lived and never
  used for repository requests.

### `GitHubClient.installation_token(installation_id, *, force=False) -> str`

Caches `(token, expires_at - 1 minute)` in memory. A cached token is reused until one
minute before expiry; `force=True` refreshes after a 401. It posts the App JWT to
`/app/installations/{id}/access_tokens`, validates `token` and `expires_at`, and never
writes the token to SQLite or logs.

### `GitHubClient._repo_request(...)` and the three operations

Adds the standard GitHub headers and `Authorization: token <installation token>`, performs
the request, and retries exactly once on 401 with a forced refresh. `get_pull_request_diff`
asks for `application/vnd.github.v3.diff`; `download_tarball` enforces
`max_repo_tarball_bytes`; `post_comment` requires `id` and `html_url` in the response.
Errors become `GitHubAPIError(status, safe_message)` with newlines removed and the message
capped at 500 characters.

- **Tests:** `backend/tests/test_github_client.py` uses `httpx.MockTransport` for success,
  error, 401-refresh, oversized tarball and malformed comment responses.
- **Not verified:** no live App installation or GitHub API call was made.

### `safe_extract_tarball(data, destination, *, max_files=20_000, max_bytes=200 MiB) -> int`

`backend/app/github/repo.py`

Reads the tar in memory and rejects, before writing:

- more than `max_files` members;
- any member that is not a regular file or directory (symlinks, hardlinks, devices);
- backslashes, NULs, absolute paths or `..` parts;
- duplicate resolved targets;
- targets whose resolved path is not under the destination;
- negative sizes, cumulative size over `max_bytes`, or a member that grows while reading.

It strips exactly one top-level GitHub directory (`owner-repo-sha/`) and returns the number
of files written. Archive/OS errors become `RepoExtractionError`. This replaces `git clone`
because the service needs no git binary, no hooks and no submodules, and the attack surface
is easier to reason about.

- **Tests:** `backend/tests/test_repo_extract.py` covers valid extraction, traversal,
  absolute paths, symlinks, duplicates, size/count caps and malformed gzip.
- **Interview angle:** why "just use `tarfile.extractall`" is unsafe, and why a tar
  download beats a clone for a stateless worker.

---

## 4. Diff and function extraction

### `parse_diff(diff_text) -> list[FileDiff]`

Handles `diff --git`, quoted paths, `new file`/`deleted file`, renames, binary markers,
`---`/`+++` fallbacks, CRLF, hunk headers and `\ No newline`. `FileDiff.changed_new_lines`
is the set of **new-file** line numbers that are additions or modifications; context lines
do not count. Empty diff lines are treated as context because some tools drop the leading
space. Files with no path are discarded at the end.

- **Tests:** `backend/tests/test_diff_parser.py` covers additions, modifications,
  deletions, renames, binary files, quoted paths, CRLF and malformed hunks.

### `extract_functions(source, file_path) -> list[FunctionInfo]`

Tree-sitter TypeScript/TSX parsing. It extracts only declarations a test can import:

- top-level function declarations;
- top-level `const`/`let`/`var` arrow/function expressions;
- class methods;
- methods on exported object literals;
- `export default` functions/classes.

It records `name`, `qualified_name` (e.g. `Score.normalize`), signature, source (capped at
6,000 chars), start/end line, `exported`, `is_async`, `is_ui` and `is_new`. It skips
constructors, private `#` names, unsupported identifier keys and `.d.ts` files. A fresh
parser is created per call to avoid cross-thread state.

- **Tests:** `backend/tests/test_function_extract.py` covers functions, arrows, classes,
  object methods, default exports, overloads, private members and unsupported files.
- **Interview angle:** why AST parsing beats regex for signatures, and what "exported"
  means for a unit test's import path.

### `mark_only_changed(functions, changed_lines, is_new_file, added_lines=None)`

Returns only functions whose line range intersects changed new-file lines. On a new file
every function is included and marked `is_new=True`. Otherwise `is_new` is true only when
the entire function range consists of added lines. This is why editing one line inside a
200-line function still targets that function, but editing an unrelated line does not.

### `analyze_diff(diff_text, repo_root) -> DiffAnalysis`

Parses the diff once, then for each non-deleted, non-binary file:

- rejects absolute/traversing paths;
- resolves the path and requires it to stay under the repository root;
- requires the file to exist in the checkout (a diff can reference a path the tarball does
  not contain);
- caps source at 1.5 MB;
- reads with `errors="replace"` so a non-UTF-8 file does not crash analysis;
- extracts functions and filters by changed lines.

All skipped/failed files are appended to `analysis.errors` rather than aborting the run.
This keeps a malformed or huge file from hiding the rest of the PR.

- **Tests:** `backend/tests/test_diff_analyzer.py` includes escape attempts, missing files,
  oversized files, deleted/binary files and multiple files.

---

## 5. Coverage and gap selection

### `parse_istanbul_coverage(data, repo_root=None) -> CoverageReport`

`backend/app/coverage/istanbul.py`

Reads the `fnMap` and `f` maps per file, preserving function names and declaration/location
ranges with hit counts. It prefers the explicit `total.lines.pct`; if absent, it computes
the percentage from `statementMap`/`s` counts. Paths are normalised from host or container
prefixes (`/workspace/repo/`, `/repo/`, `/workspace/`) to repository-relative POSIX paths.
Non-object entries, entries without `fnMap`, and malformed descriptors are ignored rather
than raising.

### `CoverageReport.function_hits(path, name, start_line, end_line) -> int | None`

`None` means "the report does not know this function"; `0` means "known and never
executed". Resolution order:

1. exact/normalised file path, then a unique suffix match, then a unique basename match;
2. functions with the same name that overlap the source line range;
3. if none overlap, the nearest same-name function within 5 lines.

The overlap rule disambiguates repeated method names; the nearest rule handles tooling that
records declarations slightly differently.

### `find_gaps(functions, repo_root, *, coverage=None, enabled_paths=None) -> GapResult`

For each changed function:

- test files, disabled paths and non-exported functions are **skipped** with a reason;
- `default` exports are decided by sibling test files, because the local import name is
  arbitrary;
- with coverage: `hits > 0` -> covered; `hits == 0` -> gap;
- without coverage: a test file containing the identifier -> covered; otherwise a gap,
  with sibling tests attached as context.

The fallback intentionally over-reports gaps. Test-file scanning is bounded (2,000 files,
500 KB per file, 20 MB total) and skips build/vendor directories, so a hostile repository
cannot make gap analysis read unbounded data.

- **Tests:** `backend/tests/test_istanbul_coverage.py` and `backend/tests/test_gap.py`
  cover hits/zero/missing entries, path normalisation, default exports, non-exported
  functions, path filters, reference matching and bounds.
- **Interview angle:** why coverage is authoritative, and why the no-coverage fallback is
  allowed to be wrong in the "propose a test" direction.

---

## 6. Repository configuration

### `RepoConfig` and `load_repo_config(root) -> RepoConfig`

The config comes from the **PR head**, so it is untrusted. `load_repo_config` reads the
first of `.prguard.yml` / `.prguard.yaml`, caps it at 64 KB, requires a YAML mapping and
validates it with Pydantic. A missing file returns defaults; an invalid file raises
`RepoConfigError` and aborts before any command runs (the default is not silently
substituted).

Bounds and rules:

| Field | Rule |
| --- | --- |
| `enabled_paths` | max 50 patterns, 200 chars each, no absolute/traversal |
| `install_command`, `test_command` | string parsed with `shlex` or argv list; executable allow-list; no shell |
| `results_file`, `coverage_file` | relative, inside repo, must end in `.json` |
| `max_fix_attempts` | 0-3 |
| `max_tests` | 1-20 |
| `max_llm_calls` | 1-100 or null |
| `max_total_tokens` | 1,000-2,000,000 or null |
| `max_cost_usd` | 0-100 or null |
| booleans | `include_ui_tests`, `review_code`, `post_comment`, `sandbox_install_network`, `run_baseline_coverage` |

Config can tighten the LLM caps but cannot change the sandbox backend, disable test-phase
network isolation, or grant extra privilege.

- **Tests:** `backend/tests/test_repo_config.py` covers defaults, both filenames, size,
  invalid YAML, shell strings, disallowed executables, traversal, bounds and tightening.
- **Interview angle:** treating a repo file as untrusted even though it is "configuration",
  and why errors abort rather than falling back.

---

## 7. LLM layer

### `LLMClient` protocol and `LLMResponse`

`backend/app/llm/base.py`

```python
async def complete(messages, *, max_tokens=1200, temperature=0.0, json_mode=False) -> LLMResponse
```

`LLMResponse` carries `text`, `model`, input/output token counts and `cost_usd`. `LLMError`
is the normalised provider failure; `BudgetExceeded` is a distinct subclass so graph nodes
can stop the run without treating it as a transient provider error. `estimate_tokens` is a
crude 4-chars-per-token helper used only by `FakeLLM` and tests, not for billing.

### `BudgetedLLM.complete(...)`

Checks the call cap **before** the call, then records the response and checks token/cost
caps **after**. This ordering is deliberate: a provider can ignore `max_tokens`, so the
only honest options are "allow one overshoot and record it" or "lose the response after
paying for it". The implementation chooses the former and surfaces the overshoot in
`CostSummary` and the run record. Caps are positive-validated in the constructor.

- **Tests:** `backend/tests/test_llm_budget.py` covers call cap, token cap, cost cap,
  accumulation, rounding and invalid caps.
- **Interview angle:** pre-call vs post-call enforcement, and why a hard provider-side
  budget is still needed in production.

### `build_llm_client` / `build_budgeted_llm`

`fake` -> `FakeLLM`; `groq` -> requires `GROQ_API_KEY`; `anthropic` -> requires
`ANTHROPIC_API_KEY`; anything else raises. `.prguard.yml` values override settings only
when present. `FakeLLM` understands the prompt tags, emits a valid Vitest proposal, and
returns deterministic token counts with zero cost.

- **Tests:** `backend/tests/test_llm_clients.py` uses `httpx.MockTransport` for the Groq and
  Anthropic request/response shapes, error mapping and token metadata.
- **Not verified:** no live provider call.

---

## 8. Agent graph

### `build_agent_graph(deps)`

`backend/app/agents/graph.py`

A `StateGraph[AgentState]` with six nodes and explicit conditional edges:

```
START -> analyze -> find_gaps
find_gaps --(no gaps)--> review -> END
find_gaps --(gaps)-----> write -> execute
execute --(failures and attempts < max_fix_attempts)--> fix -> execute
execute --(otherwise)--------------------------------> review -> END
```

The retry counter is `state["attempts"]`, incremented by the fixer and checked by
`_route_after_execute`. `max_fix_attempts` is the **run-level** cap from `.prguard.yml`
(D023); a draft is rewritten at most that many times, and per-draft `attempts` is persisted
for display. Dependencies (settings, config, budgeted LLM, sandbox, repo root, baseline
coverage, precomputed analysis) are injected via `AgentDependencies`, which is what makes
the graph testable without network, Docker or a model.

### `run_agent_pipeline(deps, diff_text) -> PipelineResult`

Builds the initial state, invokes the graph, and converts the final state into:

- `analysis`, `gaps`, `verified`, `rejected`, `errors`, `review`;
- `coverage_before`/`after` and the rounded delta;
- `cost` from `deps.llm.summary`;
- `sandbox_results` and per-node `steps` for the dashboard.

Drafts that were still failing at the cap are converted into `RejectedTest` entries so the
comment can name them. `verified` is deduplicated by file path. Errors are capped at 25
entries of 2,000 characters by `_add_error`.

### `_write_node(deps, state)`

For each gap, up to `max_tests` total drafts:

1. suggest a test path, then `unique_test_path` to avoid colliding with a user test;
2. build the prompt with source, signature, existing tests and gap reason;
3. call the budgeted LLM with `json_mode=True` and `max_tokens=1800`;
4. parse strict JSON with Pydantic, select the proposal for this function, require
   `framework == "vitest"`;
5. run `validate_proposal`, reject overwriting an existing path, write the file;
6. record a concise error and continue on parse/safety/OS errors.

A budget error breaks the loop (no point calling again); a provider error skips that gap
and continues. The step is marked `failed` only when there were gaps and zero drafts were
written.

### `_execute_node(deps, state)` — the trust decision

This is the most important node:

1. If no drafts, skip without running anything.
2. Reuse a successful baseline install when available; otherwise run install with the
   configured network policy. Install failure rejects **every** draft with the install
   reason and does not run tests.
3. Clear stale results/coverage files, run the configured test command with
   `network_disabled=True`.
4. Parse the Vitest JSON report. A **present report that omits a draft** rejects that
   draft; only a completely missing report falls back to the process exit status.
5. Load post-run coverage. If the target function is known to coverage and has zero hits,
   reject the draft even if Vitest passed ("passed but did not execute the target").
6. Split drafts into `verified` and `failed`; failures carry a truncated error for the
   fixer.

This is why "verified" means more than "the command exited zero".

### `_fix_node(deps, state)`

Takes only the failed drafts, asks the LLM to fix the test (not the source), re-validates
the proposal, forces the original path, increments `attempts`, writes the file, and marks
the draft as failed again if the fix output is unusable. It never re-runs the sandbox
itself; the graph edge returns to `execute`, keeping execution in one place.

### `_review_node(deps, state)`

Optional (`review_code`). Calls the model with a 600-token budget, the diff (capped at
12,000 chars), and the verified/rejected path lists. Budget exhaustion or provider errors
return `review=None` and append an error; they do not fail the run. Review text is capped at
8,000 characters.

- **Tests:** `backend/tests/test_agent_graph.py` covers no-gap short circuit, write/fix/
  execute routing, install reuse/failure, missing/partial reports, zero-hit coverage
  rejection, budget exhaustion, UI filtering, max tests, review on/off and error paths.
- **Interview angle:** why verification lives outside the LLM, why the fixer gets a fresh
  sandbox execution, and how the retry cap is enforced.

---

## 9. Generated-test policy and result parsing

### `validate_proposal(root, proposal, *, expected_function, expected_source) -> TestProposal`

Static checks before writing:

- source path and function name must match the gap (a model cannot redirect the target);
- test path must be relative, inside the repository, end in a test suffix, and differ from
  the source;
- content non-empty, <= 30,000 chars, <= 600 lines, no NUL;
- must contain an `it()`/`test()` block and an `expect()`;
- forbidden code: `child_process`, `fs`, HTTP/net, `vm`, `worker_threads`, `eval`,
  `new Function`, `process.env`, `process.exit`, `require()`, dynamic `import()`;
- imports limited to approved packages or repository-relative paths that do not escape.

It returns a normalised proposal, so later code never re-derives the path.

The docstring is explicit: this is **not** the security boundary. It is deterministic
feedback plus defence in depth; obfuscated code can pass a syntactic policy. The container
and its network/limit controls are the boundary.

- **Tests:** `backend/tests/test_agent_safety.py` covers each rejection and the accepted
  path.
- **Interview angle:** why deny-list checks alone are insufficient, and why the write path
  is still checked for traversal/symlinks despite the sandbox.

### `write_test_proposal(root, proposal) -> Path`

Resolves the target under the repository root, refuses the write if it escapes, refuses to
overwrite a symlink, creates parent directories, and writes UTF-8. It is the last
filesystem gate before execution.

### `parse_vitest_results_file(path, known_paths)` / `parse_vitest_results(data, known_paths)`

Reads a capped (5 MB) JSON report. For each `testResults` entry whose name matches a known
draft path (exact or suffix), it counts assertions and collects failures. A file with zero
assertions, a skipped/pending/todo assertion, a non-`passed` assertion, or a non-passing
file status fails. Missing/unreadable/oversized/invalid reports return `{}`; the caller
distinguishes "no report at all" from "report present but draft absent".

- **Tests:** `backend/tests/test_agent_results.py` covers passed, failed, skipped, empty,
  missing file, invalid JSON, path matching and size caps.

---

## 10. Sandbox

### `DockerSandboxRunner.run(workspace, command, *, phase="test", network_disabled=True, timeout_seconds=None, env=None, labels=None) -> SandboxResult`

`backend/app/sandbox/docker.py`

Order of operations:

1. `validate_command` (argv-only, max 64 args, no NUL, max 4,096 chars each);
2. `validate_executable` (bare `node`, `npm`, `npx`, `pnpm`, `yarn`, `vitest`,
   `playwright`);
3. `validate_workspace` (resolved directory);
4. reject unknown phases and reject `phase="test"` with `network_disabled=False`;
5. choose timeout, build `SandboxLimits`, build the fixed environment;
6. make the workspace writable by uid 10001;
7. create the container with non-root user, read-only root, workspace-only rw bind, memory,
   `nano_cpus`, PID limit, `cap_drop=ALL`, `no-new-privileges`, `/tmp` noexec/nosuid
   tmpfs, 64 MB `/dev/shm`, `init=True`, run labels and `prguard.sandbox=true`;
8. start, wait with a timeout, decode stdout/stderr, map the outcome;
9. remove the container unconditionally in `finally`.

Docker errors and request errors become an `error` result rather than an exception, so the
worker can persist a clean failure. A timeout kills the container and reports `timeout`
with the exit code if available. Logs are head/tail truncated, not silently cut.

- **Tests:** `backend/tests/test_sandbox_docker.py` uses a fake Docker client to assert the
  exact kwargs, network policy, timeout kill, removal on error/success, log decoding, image
  pull behaviour, env rejection and factory selection. **The real-daemon test in the same
  file is skipped when Docker is unavailable** (the measured condition here).
- **Not verified:** no container was actually created on this machine.
- **Interview angle:** which flags matter and why, plus the Docker-outside-of-Docker
  caveat documented in `SECURITY.md`.

### `validate_command`, `validate_executable`, `_safe_extra_env`

`backend/app/sandbox/security.py`

`SandboxCommand` is the argv invariant: non-empty, <= 64 args, string-only, no NUL, each
<= 4,096 chars. `validate_executable` lowercases, strips `.cmd`, rejects path separators
(so a caller cannot pass `./evil` or `C:\evil`) and checks the allow-list. `_safe_extra_env`
rejects secret-looking names, NUL/`=`, non-strings and anything outside
`CI|NODE_ENV|NODE_OPTIONS|TZ|LANG|LC_ALL|NPM_CONFIG_*|VITEST_*|PLAYWRIGHT_*|PRGUARD_*`.
Docker starts from a fixed baseline; local mode copies only a host allow-list needed by
Node.

- **Tests:** covered by the sandbox/security test modules, including Windows `.cmd`.
- **Interview angle:** why an argv allow-list is not a sandbox by itself (npm scripts still
  run arbitrary code), and why the environment is fixed rather than inherited.

### `LocalSandboxRunner.run(...)`

Same command/phase validation, but uses `subprocess.Popen` with `shell=False`, a fresh
process group/creation flags, a timeout that kills the tree (`taskkill /T` on Windows,
`killpg` on POSIX), and the local env allow-list. It reports
`isolation="local (NOT a security boundary)"` and `network_disabled=False` **even when the
caller asked for network isolation**, because it cannot enforce it. This is the backend used
by the local smoke, the demo capture and the dashboard screenshots; it must never be
presented as Docker isolation.

---

## 11. Run orchestration

### `RunProcessor.process(run_id)`

`backend/app/run_processor.py`

1. Load `RunContext` (repo, PR, SHAs, installation) or raise if the run is missing.
2. Create a fresh temporary workspace, optionally under `workspace_root`.
3. Fetch the diff and the head tarball with the installation token.
4. `safe_extract_tarball`, load `.prguard.yml`, persist the public config.
5. `analyze_diff`, then `_baseline`.
6. Build `AgentDependencies` (baseline coverage, installed flag, shared sandbox) and run
   the graph.
7. Persist results (replace child rows), then post one comment if configured.
8. In `finally`: remove the workspace and close the GitHub client if the processor owns it.

The five collaborators are injectable (`github`, `sandbox`, `workspace_root`,
`llm_factory`, `pipeline_runner`), which is how the tests and the smoke run exercise the
real orchestration without a network or daemon.

### `_baseline(...) -> BaselineOutcome`

Skips when `run_baseline_coverage` is false or there are no changed functions. Otherwise:

1. run install with `network_disabled = not sandbox_install_network`;
2. on install failure, return `failed` with the install output and **do not run tests**;
3. clear the results/coverage files so stale data cannot be mistaken for this run;
4. run the test command with `network_disabled=True`;
5. load coverage if present, record `line_pct`, and return `succeeded` only if the test
   process passed.

A failed baseline is not fatal to the run: the graph still proceeds with no coverage (and
falls back to reference detection). The step detail records install/test status and exit
code so the dashboard shows the truth.

### `_persist(...)`

In one transaction:

- updates the run counters, cost, coverage, delta, summary and duration;
- deletes and re-inserts steps, generated tests, sandbox runs and review, so a retried run
  does not duplicate rows;
- persists verified tests as `verified` and rejected ones as `rejected` with the reason;
- stores sandbox executions with argv, network flag, status, exit code, timeout, duration,
  truncated logs and coverage summary;
- stores the review with `cost_usd=0.0` because its cost is already in the run total.

Only verified proposals are persisted as `verified`; the dashboard and comment both rely on
that distinction.

### `_post_comment(...)`

Checks the run row for an existing `comment_id` and returns early if present. Renders the
comment, posts it, then stores the id and a 500-char URL. Results are persisted **before**
this step, so a posting failure leaves the evidence available; the run is marked failed by
the worker because the exception propagates. A crash after GitHub accepts the comment but
before the id is stored can duplicate on retry (D026, documented residual risk).

- **Tests:** `backend/tests/test_run_processor.py` covers diff/tarball fetch, config
  persistence, baseline skip/failure/coverage, pipeline result persistence, retry
  replacement, comment skip/post/failure, workspace cleanup and missing run.
- **Smoke:** `backend/scripts/demo_smoke.py` ran this path against the demo repo (local
  sandbox, fake GitHub, FakeLLM), producing one verified test and a 78.57% -> 100.00%
  coverage delta.

---

## 12. Comment rendering

### `format_pr_comment(run_id, result, *, max_chars=60_000, max_test_chars=6_000) -> str`

Builds a hidden run marker, a title with the verified count, coverage/cost/changed
summary, then `<details>` blocks containing **only verified** test code. Rejected drafts
appear as name/reason bullets, never as runnable snippets. Warnings are capped (5) and
reasons truncated (300 chars). A fenced block uses four backticks if the content contains
three, which limits fence breakout.

It reserves 120 characters per block, omits blocks that would exceed `max_chars`, and adds
a visible note when tests are omitted. If the body still exceeds the cap, it is truncated
with a visible marker. Inline code strips backticks; all text is whitespace-collapsed and
NUL-stripped.

- **Tests:** `backend/tests/test_comment.py` covers verified-only rendering, truncation,
  omitted tests, rejected/warning caps, no-gap output and marker sanitisation.
- **Interview angle:** why unverified content is never shown as code, and how Markdown
  injection is bounded without relying on a Markdown sanitiser.

---

## 13. Read-only API and dashboard client

### `list_runs(request, limit=25, offset=0, status=None, repo=None) -> RunList`

FastAPI validates `limit` (1-100), `offset` (>=0), the status enum and a 255-char repo
filter at the edge. The query builds only parameterised filters; the repo substring uses
`lower(...).contains(..., autoescape=True)`. It counts with the same filters, orders by
`created_at DESC, id DESC`, and returns typed `RunSummary` rows.

### `get_run(request, run_id) -> RunDetail`

One query with `selectinload` for steps, tests, sandbox runs and review; 404 when missing.
No N+1 per child table.

### `stats(request) -> RunStats`

Aggregates status counts, generated/verified test sums, total cost, average coverage delta
and average duration. Empty sums are coerced to zero; average delta stays `None` when no
run has one.

- **Tests:** `backend/tests/test_api.py` covers empty/filtered/paginated lists, invalid
  query values, 404, stats and the demo flag.

### `getRuns` / `getRun` / `getStats` / `getDemoInfo`

`dashboard/lib/api.ts`

Server-side `fetch` with `cache: "no-store"`, `Accept: application/json`, URL base from
`PRGUARD_API_URL` (fallback `NEXT_PUBLIC_API_URL`, then localhost). Network failures become
`ApiError(..., 0)`; non-2xx responses parse a string `detail` when possible and preserve
the status. This is the only API surface the dashboard uses, and it contains no mutation.

When `NEXT_PUBLIC_DEMO_MODE=true`, each function returns data from `lib/demo.ts` before any
fetch. `getDemoRuns` applies the same status/repo filters and limit/offset slicing; `getDemoRun`
returns `null` for an unknown id and `api.ts` converts that to `ApiError(404)`. The JSON is
imported, so there is no runtime file read and no API URL.

- **Tests:** 34 Vitest/React Testing Library cases, including the demo loader, banner,
  capture provenance, disabled live actions, error card, filters, pagination, detail
  evidence and empty states; Playwright runs three navigation tests against the
  deterministic mock API and four demo tests against the static capture (desktop + mobile).
- **Not verified:** no Playwright run against live FastAPI; the live-mode E2E uses
  `mock-api.mjs`.

---

## 14. Demo mode, capture and deployment

### `getDemoRuns(query) -> RunList`, `getDemoRun(runId) -> RunDetail | null`

`dashboard/lib/demo.ts`

The demo loader imports `public/demo-data/{details,runs,stats,manifest}.json` at build time.
It is a pure function over arrays: no `fetch`, no filesystem, no environment URL. The run
list applies the same status equality and case-insensitive repository substring as the API,
clamps `limit` to 1–100 and treats a negative offset as zero. The detail lookup is a linear
`find` over one or more committed runs. Unknown ids return `null`, and `lib/api.ts` maps that
to `ApiError(404)`, so the existing `notFound()` page still works.

`DEMO_MODE` accepts `true` or `1`, case-insensitively. It is read once at module load. There
is no runtime toggle: the deployment is either built as a replay or as a live client.

- **Tests:** `dashboard/tests/demo.test.tsx` exercises the manifest shape, stats, list
  filtering/pagination, unknown ids and the full API switch; `dashboard/e2e/demo/demo.spec.ts`
  asserts zero backend or `/api/` requests in a real browser.
- **Interview angle:** why build-time import is safer than fetching `public/` at runtime, and
  why the demo path keeps the same interface instead of duplicating pages.

### `DemoBanner({ manifest })`

`dashboard/components/DemoBanner.tsx`

Renders the required sentence from `manifest.captured_at` and `manifest.git_commit_short`,
plus the provider/GitHub/sandbox caveats, repository link and recording-guide link. It is
rendered by `app/layout.tsx` on every route when `DEMO_MODE` is true, so a visitor cannot
reach a detail page without seeing provenance. The same layout disables the API-docs link
and changes the header pill to `Recorded · read only`.

- **Tests:** banner text, date formatting, commit, both link targets and the detail-page
  disabled action are asserted in `dashboard/tests/demo.test.tsx`.
- **Failure mode:** a malformed timestamp renders `unknown date` rather than throwing; the
  banner still states the commit and the fakes.

### `capture_demo_data.py`

`scripts/capture_demo_data.py`

The only producer of the committed JSON. By default it runs
`backend/scripts/demo_smoke.py` and then opens the resulting SQLite database. It serialises
runs through `RunDetail`, `RunSummary`, `RunStats` and `RunList`, so a schema change breaks
the capture instead of silently drifting from the API. Before writing, it:

1. replaces absolute Windows and POSIX paths with `<local-path>`;
2. redacts keys whose names match secret/token/password patterns;
3. rewrites non-demo repository names and SHAs to placeholders;
4. removes installation ids and comment URLs;
5. scans the serialized payload for GitHub, OpenAI, AWS, Google, Slack, GitLab and private-key
   patterns and refuses to write on a match;
6. records the source commit, branch, dirty state, run config and caveats in `manifest.json`.

- **Tests:** no dedicated Python test for the exporter; its output is validated by the
  dashboard demo tests and the demo E2E. The sanitizer is deliberately fail-closed, so a
  false positive stops the build rather than leaking data.
- **Limitation:** the capture uses `FakeLLM` and `LocalSandboxRunner`; the manifest says so.
  It is not evidence of Docker isolation or a live provider call.

---

## 15. Local smoke harness

### `execute(args)` in `backend/scripts/demo_smoke.py`

Creates a SQLite database and a queued delivery/run/job, copies `demo-repo`, applies
`demo-pr.patch`, packages a GitHub-style tarball, serves the diff/tarball/comment from
`DemoGitHub`, and runs the real `Worker` + `RunProcessor` with `LocalSandboxRunner` and a
scripted `BudgetedLLM(FakeLLM)`. It prints the run id, status, coverage, counts, comment
length, steps, tests and sandbox executions, writes `data/demo-comment.md`, and exits
non-zero unless the run succeeded.

This is the only end-to-end execution performed locally. It exercises real npm/Vitest and
real persistence, but **not** Docker isolation, webhook signatures, installation tokens,
GitHub API calls or provider LLMs.

---

## Test map

| Module | Test file(s) |
| --- | --- |
| Webhooks/signature | `test_signature.py`, `test_webhooks.py`, `test_payloads.py` |
| Worker/queue | `test_worker.py` |
| GitHub auth/client | `test_github_auth.py`, `test_github_client.py` |
| Tarball extraction | `test_repo_extract.py` |
| Diff parsing/extraction | `test_diff_parser.py`, `test_function_extract.py`, `test_diff_analyzer.py` |
| Istanbul/gaps | `test_istanbul_coverage.py`, `test_gap.py` |
| Repo config | `test_repo_config.py` |
| LLM budget/providers/fake | `test_llm_budget.py`, `test_llm_clients.py`, `test_agent_prompts.py` |
| Agent graph/models/parsing/results/safety | `test_agent_graph.py`, `test_agent_models.py`, `test_agent_parsing.py`, `test_agent_results.py`, `test_agent_safety.py` |
| Sandbox | `test_sandbox_docker.py` (fake client; real-daemon test skipped) |
| Run processor | `test_run_processor.py` |
| Comment | `test_comment.py` |
| API/schemas/models/settings/main | `test_api.py`, `test_schemas.py`, `test_models.py`, `test_settings.py`, `test_main.py` |
| Dashboard | `dashboard/tests/*.test.ts(x)`, `dashboard/e2e/dashboard.spec.ts` |
| Demo dashboard | `dashboard/tests/demo.test.tsx`, `dashboard/e2e/demo/demo.spec.ts` |
| Demo capture | `scripts/capture_demo_data.py` (validated by the demo dashboard tests) |
| Demo repo | `demo-repo/tests/*.test.ts` |

## What is not proven

- No real Docker container, image build or Compose stack has run here.
- No live GitHub App webhook, installation token, tarball download or comment has run here.
- No live Groq/Anthropic call has run here; adapter tests use `httpx.MockTransport`.
- The GitHub Actions workflow has not executed (no remote run yet).
- The only end-to-end run is the local smoke, which uses `LocalSandboxRunner`, `FakeLLM`
  and a fake GitHub client; the public demo replays that run's sanitized JSON.
- No screen recording exists yet; `docs/DEMO_RECORDING.md` defines the shot list and embed
  location instead of embedding an empty player.
