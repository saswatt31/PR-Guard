import Link from "next/link";

import type { RunStatus } from "@/lib/types";

function pageHref({
  limit,
  offset,
  status,
  repo,
}: {
  limit: number;
  offset: number;
  status: RunStatus | "";
  repo: string;
}): string {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (repo) params.set("repo", repo);
  if (limit !== 25) params.set("limit", String(limit));
  if (offset > 0) params.set("offset", String(offset));
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

export function Pagination({
  total,
  limit,
  offset,
  status,
  repo,
}: {
  total: number;
  limit: number;
  offset: number;
  status: RunStatus | "";
  repo: string;
}) {
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <nav className="pagination" aria-label="Run pages">
      <span>
        Showing {start}–{end} of {total}
      </span>
      <div className="pagination-actions">
        {hasPrevious ? (
          <Link
            className="button quiet"
            href={pageHref({
              limit,
              offset: Math.max(0, offset - limit),
              status,
              repo,
            })}
            rel="prev"
          >
            ← Previous
          </Link>
        ) : (
          <span className="button quiet" aria-disabled="true">
            ← Previous
          </span>
        )}
        {hasNext ? (
          <Link
            className="button quiet"
            href={pageHref({
              limit,
              offset: offset + limit,
              status,
              repo,
            })}
            rel="next"
          >
            Next →
          </Link>
        ) : (
          <span className="button quiet" aria-disabled="true">
            Next →
          </span>
        )}
      </div>
    </nav>
  );
}
