import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  API_URL,
  ApiError,
  getDemoInfo,
  getRun,
  getRuns,
  getStats,
} from "@/lib/api";

function jsonResponse(value: unknown, status = 200, statusText = "OK"): Response {
  return new Response(JSON.stringify(value), {
    status,
    statusText,
    headers: { "Content-Type": "application/json" },
  });
}

describe("dashboard API client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds filtered, paginated run queries and disables caching", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, limit: 10, offset: 20 }),
    );

    const result = await getRuns({
      limit: 10,
      offset: 20,
      status: "failed",
      repo: " acme/demo ",
    });

    expect(result.total).toBe(0);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_URL}/api/runs?limit=10&offset=20&status=failed&repo=acme%2Fdemo`,
      expect.objectContaining({
        cache: "no-store",
        headers: { Accept: "application/json" },
      }),
    );
  });

  it("omits empty filters and trailing question marks", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, limit: 25, offset: 0 }));

    await getRuns({ status: "", repo: "  " });

    expect(fetchMock).toHaveBeenCalledWith(`${API_URL}/api/runs`, expect.any(Object));
  });

  it("loads a run with an encoded id and the other read endpoints", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ id: "run-1" }))
      .mockResolvedValueOnce(jsonResponse({ total_runs: 2 }))
      .mockResolvedValueOnce(jsonResponse({ enabled: true, run_count: 2 }));

    await expect(getRun("run/a b")).resolves.toEqual({ id: "run-1" });
    await expect(getStats()).resolves.toEqual({ total_runs: 2 });
    await expect(getDemoInfo()).resolves.toEqual({ enabled: true, run_count: 2 });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${API_URL}/api/runs/run%2Fa%20b`,
      `${API_URL}/api/stats`,
      `${API_URL}/api/demo`,
    ]);
  });

  it("surfaces the API's JSON detail on an error", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "run not found" }, 404, "Not Found"),
    );

    const error = await getRun("missing").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404 });
    expect((error as Error).message).toContain("run not found");
  });

  it("falls back to status text for a non-JSON error", async () => {
    fetchMock.mockResolvedValue(
      new Response("not json", {
        status: 502,
        statusText: "Bad Gateway",
        headers: { "Content-Type": "text/plain" },
      }),
    );

    await expect(getStats()).rejects.toThrow("PR-Guard API returned 502: Bad Gateway");
  });

  it("reports an unreachable API with a useful base URL", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));

    await expect(getStats()).rejects.toMatchObject({ status: 0 });
    await expect(getStats()).rejects.toThrow(API_URL);
  });
});
