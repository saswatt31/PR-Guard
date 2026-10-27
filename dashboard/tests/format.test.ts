import { describe, expect, it } from "vitest";

import {
  coverageRange,
  formatCost,
  formatDate,
  formatDelta,
  formatDuration,
  formatNumber,
  formatPct,
  formatShortDate,
  formatTokens,
  pluralize,
  shortSha,
  titleCase,
} from "@/lib/format";

describe("formatDate", () => {
  it("formats a UTC timestamp", () => {
    const value = formatDate("2026-10-27T12:00:00Z");

    expect(value).toContain("Oct 27, 2026");
    expect(value).toContain("UTC");
  });

  it("returns a fallback for invalid input", () => {
    expect(formatDate("not-a-date")).toBe("unknown");
    expect(formatShortDate("not-a-date")).toBe("unknown");
  });

  it("formats a compact UTC date", () => {
    expect(formatShortDate("2026-10-27T12:00:00Z")).toMatch(/Oct 27/);
    expect(formatShortDate("2026-10-27T12:00:00Z")).toMatch(/UTC|PM/);
  });
});

describe("formatDuration", () => {
  it("uses milliseconds, seconds and minutes", () => {
    expect(formatDuration(0)).toBe("0 ms");
    expect(formatDuration(999)).toBe("999 ms");
    expect(formatDuration(1_500)).toBe("1.5 s");
    expect(formatDuration(65_000)).toBe("1m 5s");
  });

  it("handles missing and invalid values", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
    expect(formatDuration(-1)).toBe("—");
    expect(formatDuration(Number.NaN)).toBe("—");
  });
});

describe("number and status formatting", () => {
  it("formats costs at useful precision", () => {
    expect(formatCost(0)).toBe("$0.00");
    expect(formatCost(0.0012)).toBe("$0.0012");
    expect(formatCost(1.5)).toBe("$1.50");
    expect(formatCost(null)).toBe("—");
  });

  it("formats percentages, deltas, numbers and tokens", () => {
    expect(formatPct(83.456)).toBe("83.5%");
    expect(formatPct(null)).toBe("—");
    expect(formatDelta(10)).toBe("+10.00 pp");
    expect(formatDelta(-2.5)).toBe("-2.50 pp");
    expect(formatDelta(0)).toBe("0.00 pp");
    expect(formatDelta(null)).toBe("—");
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatNumber(null)).toBe("—");
    expect(formatTokens(1500)).toBe("1,500 tokens");
    expect(formatTokens(null)).toBe("—");
  });

  it("formats hashes, labels and plural counts", () => {
    expect(shortSha("1234567890")).toBe("1234567");
    expect(titleCase("find_gaps")).toBe("Find Gaps");
    expect(titleCase("succeeded")).toBe("Succeeded");
    expect(pluralize(0, "draft")).toBe("0 drafts");
    expect(pluralize(1, "draft")).toBe("1 draft");
    expect(pluralize(2, "draft")).toBe("2 drafts");
    expect(pluralize(1, "test", "tests")).toBe("1 test");
  });

  it("describes coverage ranges without pretending a missing side was measured", () => {
    expect(coverageRange(40, 50)).toBe("40.0% → 50.0%");
    expect(coverageRange(null, 50)).toBe("not measured → 50.0%");
    expect(coverageRange(40, null)).toBe("40.0% → not measured");
    expect(coverageRange(null, null)).toBe("not measured");
  });
});
