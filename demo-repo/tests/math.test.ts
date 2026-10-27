import { describe, expect, it } from "vitest";

import { add, clamp, mean } from "../src/math";

describe("add", () => {
  it("adds positive and negative numbers", () => {
    expect(add(2, 3)).toBe(5);
    expect(add(-2, 3)).toBe(1);
  });
});

describe("clamp", () => {
  it("returns the value when it is inside the range", () => {
    expect(clamp(5, 0, 10)).toBe(5);
  });

  it("clamps to the lower and upper bounds", () => {
    expect(clamp(-4, 0, 10)).toBe(0);
    expect(clamp(42, 0, 10)).toBe(10);
  });

  it("rejects an inverted range", () => {
    expect(() => clamp(1, 10, 0)).toThrow(RangeError);
  });
});

describe("mean", () => {
  it("averages a non-empty list", () => {
    expect(mean([1, 2, 3, 4])).toBe(2.5);
  });

  it("rejects an empty list", () => {
    expect(() => mean([])).toThrow(RangeError);
  });
});
