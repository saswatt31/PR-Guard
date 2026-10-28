import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DemoBanner } from "@/components/DemoBanner";
import { RunDetailView } from "@/components/RunDetailView";
import {
  getDemoInfo,
  getDemoManifest,
  getDemoRun,
  getDemoRuns,
  getDemoStats,
} from "@/lib/demo";
import { makeRun } from "./fixtures";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("committed demo capture", () => {
  it("loads the manifest, list, stats and detail from static JSON", () => {
    const manifest = getDemoManifest();
    const runs = getDemoRuns();
    const first = runs.items[0];

    expect(manifest.run_count).toBeGreaterThan(0);
    expect(manifest.git_commit_short).toMatch(/^[0-9a-f]{7}$/);
    expect(manifest.provider).toContain("FakeLLM");
    expect(manifest.sandbox).toContain("LocalSandboxRunner");
    expect(manifest.caveats.join(" ")).toContain("not a security boundary");

    expect(runs.total).toBe(manifest.run_count);
    expect(first).toBeDefined();
    expect(getDemoRun(first.id)?.steps.length).toBeGreaterThan(0);
    expect(getDemoRun(first.id)?.tests.length).toBeGreaterThan(0);
    expect(getDemoStats().total_runs).toBe(manifest.run_count);
    expect(getDemoInfo()).toEqual({ enabled: true, run_count: manifest.run_count });
  });

  it("filters, paginates and reports unknown ids without a backend", () => {
    expect(getDemoRuns({ status: "failed" }).total).toBe(0);
    expect(getDemoRuns({ status: "succeeded" }).total).toBeGreaterThan(0);
    expect(getDemoRuns({ repo: "prguard-demo" }).items.length).toBeGreaterThan(0);
    expect(getDemoRuns({ repo: "not-a-repo" }).items).toHaveLength(0);
    expect(getDemoRuns({ limit: 1, offset: 1 }).items).toHaveLength(0);
    expect(getDemoRun("missing")).toBeNull();
  });

  it("switches the API client to static data with zero fetch calls", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const api = await import("@/lib/api");

    await expect(api.getStats()).resolves.toMatchObject({ total_runs: 1 });
    await expect(api.getRuns({ status: "succeeded" })).resolves.toMatchObject({ total: 1 });
    await expect(api.getDemoInfo()).resolves.toEqual({ enabled: true, run_count: 1 });
    await expect(api.getRun("missing")).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("DemoBanner", () => {
  it("shows capture date, commit, provenance and both links", () => {
    const manifest = getDemoManifest();
    const captured = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(manifest.captured_at));
    render(<DemoBanner manifest={manifest} />);

    const banner = screen.getByTestId("demo-banner");
    expect(banner).toHaveTextContent(
      /Demo mode: replaying recorded results from real runs/,
    );
    expect(banner).toHaveTextContent(`captured ${captured}`);
    expect(banner).toHaveTextContent(`commit ${manifest.git_commit_short}`);
    expect(banner).toHaveTextContent(/FakeLLM/);
    expect(banner).toHaveTextContent(/LocalSandboxRunner/);
    expect(screen.getByRole("link", { name: /Repository/ })).toHaveAttribute(
      "href",
      manifest.repo_url,
    );
    expect(screen.getByRole("link", { name: /Recording guide/ })).toHaveAttribute(
      "href",
      manifest.recording_url,
    );
  });
});

describe("RunDetailView in demo mode", () => {
  it("labels the capture and disables live GitHub actions with an explanation", () => {
    render(<RunDetailView run={makeRun()} demo />);

    expect(screen.getByTestId("demo-detail-note")).toHaveTextContent(/FakeLLM/);
    expect(screen.getByText("Open PR unavailable")).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("link", { name: "Open PR ↗" })).not.toBeInTheDocument();
    expect(screen.getByText("#7 (recorded fixture)")).toBeInTheDocument();
  });
});
