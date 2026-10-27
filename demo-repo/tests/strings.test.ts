import { describe, expect, it } from "vitest";

import { slugify, titleCase } from "../src/strings";

describe("slugify", () => {
  it("lowercases and hyphenates words", () => {
    expect(slugify("  Hello, PR Guard!  ")).toBe("hello-pr-guard");
  });

  it("trims leading and trailing separators", () => {
    expect(slugify("---Already-Slugged---")).toBe("already-slugged");
  });

  it("returns an empty string when nothing remains", () => {
    expect(slugify("!!!")).toBe("");
  });
});

describe("titleCase", () => {
  it("normalizes mixed-case words", () => {
    expect(titleCase("hELLO   wORLD")).toBe("Hello World");
  });

  it("handles an empty string", () => {
    expect(titleCase("   ")).toBe("");
  });
});
