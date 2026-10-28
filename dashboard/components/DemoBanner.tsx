import type { DemoManifest } from "@/lib/types";

function capturedDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown date";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/**
 * Permanent provenance banner. It is rendered from `manifest.json`, so the
 * date and commit cannot drift from the committed capture.
 */
export function DemoBanner({ manifest }: { manifest: DemoManifest }) {
  return (
    <aside
      className="demo-banner"
      role="status"
      data-testid="demo-banner"
      title="Demo mode has no backend. This deployment only replays the committed capture."
    >
      <div className="shell demo-banner-inner">
        <span className="demo-badge">Demo</span>
        <div className="demo-copy">
          <p>
            Demo mode: replaying recorded results from real runs (captured{" "}
            {capturedDate(manifest.captured_at)}, commit{" "}
            <code>{manifest.git_commit_short}</code>).
          </p>
          <p className="demo-sub">
            Local smoke capture · {manifest.provider} · {manifest.github} · {manifest.sandbox}.
          </p>
        </div>
        <div className="demo-links">
          <a href={manifest.repo_url} target="_blank" rel="noreferrer">
            Repository ↗
          </a>
          <a
            href={manifest.recording_url}
            target="_blank"
            rel="noreferrer"
            title="Recording steps and the embed location. The video is not committed to the repository."
          >
            Recording guide ↗
          </a>
        </div>
      </div>
    </aside>
  );
}
