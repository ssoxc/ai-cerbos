import type { Workspace } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** The parsed error body, for endpoints that return structured details. */
    public body: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "ai-cerbos" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  // Gateway errors (nginx 502/504) and empty bodies are not JSON; never let the parser
  // throw in place of a readable ApiError, or the 401 handling below is skipped.
  const text = await response.text();
  let data: { detail?: unknown } = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = {};
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail
          .map((e: { msg: string; loc: string[] }) => `${e.loc.slice(1).join(" ")}: ${e.msg}`)
          .join(". ")
      : typeof data.detail === "string"
        ? data.detail
        : "";
    throw new ApiError(
      response.status,
      detail || `The server returned an unexpected response (HTTP ${response.status}). Please try again.`,
      data as Record<string, unknown>,
    );
  }
  return data as T;
}

/** The governed gateway is served from the same origin as the dashboard. */
export const gatewayBaseUrl = () => `${window.location.origin}/v1`;

export async function loadWorkspace(): Promise<Workspace> {
  try {
    return await api<Workspace>("/api/state");
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    const health = await api<{ demo_mode: boolean }>("/api/health");
    if (!health.demo_mode) throw error;
    await api("/api/session", "POST", { user_id: "morgan" });
    return api<Workspace>("/api/state");
  }
}

export const money = (micros: number, decimals = 0) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: decimals,
  }).format(micros / 1_000_000);
export const roleName = (role: string) =>
  ({
    viewer: "Viewer",
    developer: "Developer",
    developer_admin: "Developer admin",
    cost_center_admin: "Cost center admin",
    executive_admin: "Executive admin",
    api_key_approver: "API key approver",
    finance_admin: "Finance admin",
  })[role] || role;
export const kindName = (kind: string) =>
  ({ agent: "AI agent", mcp: "MCP server", skill: "Agent skill" })[kind] || kind;
export function relativeTime(date: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(date).getTime()) / 60000));
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return `${Math.floor(minutes / 1440)}d ago`;
}
