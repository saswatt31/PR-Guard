"use client";

import Link from "next/link";

export default function RunError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="error-panel" role="alert">
      <h2>Could not load this run</h2>
      <p>{error.message}</p>
      <p>
        The API may be unavailable, or this deployment may have been restarted. Check the
        API health endpoint and try again.
      </p>
      <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
        <button className="button primary" type="button" onClick={reset}>
          Try again
        </button>
        <Link className="button" href="/">
          Back to runs
        </Link>
      </div>
    </section>
  );
}
