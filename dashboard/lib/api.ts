import type { DemoInfo, RunDetail, RunList, RunStats, RunStatus } from "./types";

export const API_URL = (
  process.env.PRGUARD_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface RunQuery {
  limit?: number;
  offset?: number;
  status?: RunStatus | "";
  repo?: string;
}

function queryString(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`PR-Guard API is unreachable at ${API_URL}`, 0);
  }

  if (!response.ok) {
    let detail = response.statusText || "request failed";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Keep the status text when the body is not JSON.
    }
    throw new ApiError(`PR-Guard API returned ${response.status}: ${detail}`, response.status);
  }
  return (await response.json()) as T;
}

export async function getRuns(query: RunQuery = {}): Promise<RunList> {
  const suffix = queryString({
    limit: query.limit,
    offset: query.offset,
    status: query.status,
    repo: query.repo?.trim(),
  });
  return request<RunList>(`/api/runs${suffix}`);
}

export function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`);
}

export function getStats(): Promise<RunStats> {
  return request<RunStats>("/api/stats");
}

export function getDemoInfo(): Promise<DemoInfo> {
  return request<DemoInfo>("/api/demo");
}
