export function add(a: number, b: number): number {
  return a + b;
}

export function clamp(value: number, min: number, max: number): number {
  if (min > max) {
    throw new RangeError("min must be less than or equal to max");
  }
  return Math.min(Math.max(value, min), max);
}

export function mean(values: readonly number[]): number {
  if (values.length === 0) {
    throw new RangeError("mean requires at least one value");
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}
