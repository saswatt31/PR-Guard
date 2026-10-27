import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricCard } from "@/components/MetricCard";
import { Pagination } from "@/components/Pagination";
import { RunTable } from "@/components/RunTable";
import { RunsFilter } from "@/components/RunsFilter";
import { StatusBadge } from "@/components/StatusBadge";
import type { RunSummary } from "@/lib/types";

function summary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "run-1",
    repo_full_name: "acme/demo",
    pr_number: 7,
    head_sha: "1234567890abcdef",
    status: "succeeded",
    summary: "1 verified",
    files_changed: 1,
    functions_found: 1,
    tests_generated: 2,
    tests_verified: 1,
    cost_usd: 0.0012,
    coverage_delta: 10,
    duration_ms: 1500,
    created_at: "2026-10-27T12:00:00Z",
    updated_at: "2026-10-27T12:00:00Z",
    ...overrides,
  };
}

describe("StatusBadge and MetricCard", () => {
  it("normalizes a status into a stable class and label", () => {
    const { container } = render(<StatusBadge status="SUCCEEDED" />);

    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(container.querySelector(".status-succeeded")).not.toBeNull();
  });

  it("renders a custom status label", () => {
    render(<StatusBadge status="failed" label="Rejected" />);

    expect(screen.getByText("Rejected")).toHaveAttribute("data-status", "failed");
  });

  it("renders a metric and optional detail", () => {
    render(<MetricCard label="Verified tests" value="12" detail="of 14 drafts" accent />);

    expect(screen.getByText("Verified tests")).toBeInTheDocument();
    expect(screen.getByText("12")).toHaveClass("accent");
    expect(screen.getByText("of 14 drafts")).toBeInTheDocument();
  });
});

describe("RunTable", () => {
  it("renders run links, counts and signed coverage deltas", () => {
    render(
      <RunTable
        runs={[
          summary(),
          summary({
            id: "run-2",
            repo_full_name: "acme/broken",
            status: "failed",
            head_sha: "fedcba9876543210",
            coverage_delta: -2,
            cost_usd: 0.0042,
            duration_ms: 2500,
            summary: null,
          }),
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: "acme/demo" })).toHaveAttribute(
      "href",
      "/runs/run-1",
    );
    expect(screen.getByText("#7 · 1234567")).toBeInTheDocument();
    expect(screen.getByText("+10.00 pp")).toHaveClass("delta-positive");
    expect(screen.getByText("-2.00 pp")).toHaveClass("delta-negative");
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("1.5 s")).toBeInTheDocument();
    expect(screen.getByText("$0.0012")).toBeInTheDocument();
    expect(screen.getByText("1 verified")).toHaveAttribute("title", "1 verified");
  });

  it("renders a neutral delta when coverage was not measured", () => {
    render(<RunTable runs={[summary({ coverage_delta: null, summary: null })]} />);

    expect(screen.getByText("—")).toHaveClass("delta-neutral");
  });
});

describe("RunsFilter", () => {
  it("preselects active filters and offers a clear link", () => {
    render(<RunsFilter status="failed" repo="acme/demo" />);

    expect(screen.getByLabelText("Status")).toHaveValue("failed");
    expect(screen.getByLabelText("Repo")).toHaveValue("acme/demo");
    expect(screen.getByRole("link", { name: "Clear" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("button", { name: "Filter" })).toBeInTheDocument();
    expect(screen.getByRole("search")).toHaveAttribute("action", "/");
  });

  it("hides clear when no filter is active", () => {
    render(<RunsFilter />);

    expect(screen.queryByRole("link", { name: "Clear" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toHaveValue("");
  });
});

describe("Pagination", () => {
  it("links to the next page with active filters", () => {
    render(
      <Pagination total={40} limit={25} offset={0} status="failed" repo="acme/demo" />,
    );

    expect(screen.getByText("Showing 1–25 of 40")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Next →" })).toHaveAttribute(
      "href",
      "/?status=failed&repo=acme%2Fdemo&offset=25",
    );
    expect(screen.getByText("← Previous")).toHaveAttribute("aria-disabled", "true");
  });

  it("links back to the previous page and disables next at the end", () => {
    render(<Pagination total={40} limit={25} offset={25} status="" repo="" />);

    expect(screen.getByText("Showing 26–40 of 40")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Previous" })).toHaveAttribute("href", "/");
    expect(screen.getByText("Next →")).toHaveAttribute("aria-disabled", "true");
  });

  it("renders an empty range for an empty result", () => {
    render(<Pagination total={0} limit={25} offset={0} status="" repo="" />);

    expect(screen.getByText("Showing 0–0 of 0")).toBeInTheDocument();
  });
});
