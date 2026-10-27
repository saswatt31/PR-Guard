import Link from "next/link";

import type { RunStatus } from "@/lib/types";

const STATUSES: RunStatus[] = ["succeeded", "failed", "running", "queued", "skipped"];

export function RunsFilter({
  status = "",
  repo = "",
}: {
  status?: RunStatus | "";
  repo?: string;
}) {
  const active = Boolean(status || repo);
  return (
    <form className="filter-bar" action="/" method="get" role="search">
      <div className="filter-field">
        <label htmlFor="status-filter">Status</label>
        <select id="status-filter" name="status" defaultValue={status}>
          <option value="">All</option>
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {value[0].toUpperCase() + value.slice(1)}
            </option>
          ))}
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="repo-filter">Repo</label>
        <input
          id="repo-filter"
          name="repo"
          type="search"
          placeholder="owner/name"
          defaultValue={repo}
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <button className="button primary" type="submit">
        Filter
      </button>
      {active ? (
        <Link className="button quiet" href="/">
          Clear
        </Link>
      ) : null}
      <span className="filter-spacer" />
      <span className="panel-kicker">Newest first</span>
    </form>
  );
}
