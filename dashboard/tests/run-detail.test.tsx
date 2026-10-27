import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunDetailView } from "@/components/RunDetailView";
import { makeRun, makeSandbox } from "./fixtures";

describe("RunDetailView", () => {
  it("renders verified code, evidence, review and metadata", () => {
    render(<RunDetailView run={makeRun()} />);

    expect(screen.getByRole("heading", { level: 1, name: "acme/demo" })).toBeInTheDocument();
    expect(screen.getByText("50.0% → 60.0%")).toBeInTheDocument();
    expect(screen.getByText("+10.00 pp across the run")).toBeInTheDocument();
    expect(screen.getByText("18.5 s")).toBeInTheDocument();
    expect(screen.getByText("$0.0012")).toBeInTheDocument();
    expect(screen.getByText("1,500 tokens")).toBeInTheDocument();

    expect(screen.getByText("it('adds', () => expect(add(1, 2)).toBe(3));")).toBeInTheDocument();
    expect(screen.getByText("sandbox test failed")).toBeInTheDocument();
    expect(screen.queryByText("it('broken', () => { throw new Error(); });")).not.toBeInTheDocument();

    expect(screen.getByText("npx vitest run --coverage")).toBeInTheDocument();
    expect(screen.getByText(/Test Files/)).toBeInTheDocument();
    expect(screen.getByText("No blocking issues.")).toBeInTheDocument();
    expect(screen.getByText("No blocking issues.").closest(".review-copy")).not.toBeNull();

    expect(screen.getByText("parsed 1 changed file")).toBeInTheDocument();
    expect(screen.getByText("find_gaps")).toBeInTheDocument();
    expect(screen.getByText("execute · attempt 2")).toBeInTheDocument();
    expect(screen.getByText("files: 1")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Open PR ↗" })).toHaveAttribute(
      "href",
      "https://github.com/acme/demo/pull/7",
    );
    expect(screen.getAllByRole("link", { name: /comment/i }).length).toBeGreaterThan(0);
    expect(screen.getByText(/"max_tests": 8/)).toBeInTheDocument();
    expect(screen.queryByText("not posted")).not.toBeInTheDocument();
  });

  it("renders honest empty and failure states", () => {
    render(
      <RunDetailView
        run={makeRun({
          summary: null,
          comment_url: null,
          comment_id: null,
          review: null,
          tests: [],
          steps: [],
          sandbox_runs: [makeSandbox({ stdout: "", stderr: "", coverage: null })],
          error: "worker crashed",
          coverage_before: null,
          coverage_delta: null,
        })}
      />,
    );

    expect(screen.getByText("No summary was recorded for this run.")).toBeInTheDocument();
    expect(
      screen.getByText(/No test passed verification for this run/),
    ).toBeInTheDocument();
    expect(screen.getByText("No agent steps recorded.")).toBeInTheDocument();
    expect(screen.getByText("No output captured.")).toBeInTheDocument();
    expect(screen.getByText("worker crashed")).toBeInTheDocument();
    expect(screen.getByText("not posted")).toBeInTheDocument();
    expect(screen.queryByText("View comment ↗")).not.toBeInTheDocument();
  });

  it("shows the no-execution note when only the baseline ran", () => {
    render(<RunDetailView run={makeRun({ sandbox_runs: [] })} />);

    expect(
      screen.getByText(/No generated-test execution was recorded/),
    ).toBeInTheDocument();
  });

  it("caps step detail chips and keeps the timeline readable", () => {
    render(
      <RunDetailView
        run={makeRun({
          steps: [
            {
              ...makeRun().steps[0],
              detail: {
                one: 1,
                two: true,
                three: "x",
                four: [1, 2],
                five: { nested: true },
                six: null,
                seven: "shown-sixth",
                eight: "hidden",
              },
            },
          ],
        })}
      />,
    );

    const step = screen.getByText("analyze").closest("li");
    expect(step).not.toBeNull();
    const chips = within(step as HTMLElement).getAllByText(/:/);
    expect(chips).toHaveLength(6);
    expect(screen.getByText("seven: shown-sixth")).toBeInTheDocument();
    expect(screen.queryByText("eight: hidden")).not.toBeInTheDocument();
  });
});
