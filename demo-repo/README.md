# PR-Guard demo repository

A deliberately small TypeScript library with a fully tested baseline. It exists so
PR-Guard can be demonstrated on a real pull request without pointing the GitHub App at
somebody else's code.

## Baseline

```bash
npm ci
npm test
npm run test:coverage
npm run typecheck
```

The checked-in tests cover every existing function, so the baseline coverage run is
green. The library is intentionally boring: two modules, no framework, no network.

## Create the demo pull request

`demo-pr.patch` adds a new `normalizeScore` function and exports it. It intentionally
ships **without tests**, so the coverage gap finder has a real function to target.

1. Push this directory as its own GitHub repository (or copy it into a scratch repo) and
   install the PR-Guard GitHub App on it.
2. Create a branch and apply the patch:

   ```bash
   git checkout -b demo/normalize-score
   git apply demo-pr.patch
   git add src/index.ts src/score.ts
   git commit -m "feat: add score normalization"
   git push -u origin demo/normalize-score
   ```

3. Open a pull request. PR-Guard should:
   - parse the changed `src/index.ts` and new `src/score.ts`;
   - find `normalizeScore` as uncovered by baseline coverage;
   - generate a Vitest test, execute it in the sandbox with the network disabled;
   - post only the verified test in one PR comment and show the run in the dashboard.

The expected generated test covers the clamp, the invalid-range guard and finite inputs.
If the model proposes a weak test, the fixer gets at most two rounds (`.prguard.yml`).

## Useful failure demos

- Delete an `expect()` from a test and open a PR: the baseline still runs, but the
  generated draft is rejected if it cannot pass.
- Add a function that reads `process.env` or imports `node:fs`: the static test policy
  rejects the proposal before execution.
- Set `include_ui_tests: true` and change a DOM helper: the writer is allowed to emit a
  jsdom test, but the sandbox still runs Vitest only.

## Notes

- The repository is standalone; it is not a workspace package of the parent project.
- `npm ci` requires the checked-in `package-lock.json`.
- The parent CI runs this suite as a smoke test, but it does not run the PR-Guard
  pipeline. Docker/LLM/GitHub execution is verified separately (or reported as skipped
  when the daemon/credentials are unavailable).
