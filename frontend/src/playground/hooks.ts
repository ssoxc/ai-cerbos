import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type {
  Board,
  Catalog,
  CheckResult,
  CheckSpec,
  GatewayRequest,
  GatewayResult,
  ModelCatalogResult,
  PolicySummary,
  Preset,
  PresetResult,
  ToolResult,
  Traffic,
} from "./types";

/** Every playground query lives under this key, so one invalidation refreshes them all. */
export const PLAYGROUND = "playground";

export function useCatalog() {
  return useQuery({
    queryKey: [PLAYGROUND, "catalog"],
    queryFn: () => api<Catalog>("/api/playground/catalog"),
    staleTime: 5000,
  });
}

export const runCheck = (spec: CheckSpec) => api<CheckResult>("/api/playground/check", "POST", spec);

export function useCheck(spec: CheckSpec | null) {
  return useQuery({
    queryKey: [PLAYGROUND, "check", spec],
    queryFn: () => runCheck(spec as CheckSpec),
    enabled: !!spec && spec.resource_ids.length > 0,
    placeholderData: (previous) => previous,
  });
}

export function usePolicies() {
  return useQuery({
    queryKey: [PLAYGROUND, "policies"],
    queryFn: () => api<PolicySummary[]>("/api/policies"),
  });
}

/**
 * Refresh everything a policy or data change can affect: playground decisions, the
 * dashboard's own permissions, and asset drawer decisions.
 */
export function useRefreshAuthorization() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: [PLAYGROUND] }),
      queryClient.invalidateQueries({ queryKey: ["workspace"] }),
      queryClient.invalidateQueries({ queryKey: ["policy"] }),
    ]);
}

export const actionLabel = (action: string) =>
  ({
    view: "View",
    create: "Create",
    edit: "Edit",
    delete: "Delete",
    use: "Use",
    request_budget: "Propose budget",
    request_key: "Request key",
    approve: "Approve",
    decline: "Decline",
    claim: "Reveal key",
    revoke: "Revoke",
    delegate_cost: "Delegate budget rights",
    invoke: "Invoke model",
    list: "See in model catalog",
    call: "Call tool",
    view_keys: "API keys area",
    view_budgets: "Budgets area",
    view_organization: "Organization area",
    view_audit: "Audit log",
    view_policies: "Policies page",
    create_department: "Create unit",
    assign_cost_admin: "Assign cost admin",
    register_asset: "Register asset",
  })[action] || action;

// --- Story page -------------------------------------------------------------------------

export function useBoard(personaId: string, whatIfs: string[]) {
  return useQuery({
    queryKey: [PLAYGROUND, "board", personaId, [...whatIfs].sort()],
    queryFn: () => api<Board>("/api/playground/board", "POST", { persona_id: personaId, what_ifs: whatIfs }),
    placeholderData: (previous) => previous,
  });
}

/**
 * Every situation for every demo key, as real calls through LiteLLM. Runs on first view and
 * again whenever a policy changes (any playground invalidation), never on window focus.
 */
export function useTraffic() {
  return useQuery({
    queryKey: [PLAYGROUND, "traffic"],
    queryFn: () => api<Traffic>("/api/playground/traffic", "POST"),
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
  });
}

export function usePresets() {
  return useQuery({
    queryKey: [PLAYGROUND, "presets"],
    queryFn: () => api<Preset[]>("/api/playground/presets"),
  });
}

export const togglePreset = (id: string, on: boolean) =>
  api<PresetResult>(`/api/playground/presets/${id}`, "PUT", { on });

/** Issue the two demo keys once, before any panel uses them. */
export function useEnsureDemoKeys() {
  return useQuery({
    queryKey: [PLAYGROUND, "demo-keys"],
    queryFn: () => api<{ keys: Record<string, unknown> }>("/api/playground/demo-keys", "POST"),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  });
}

export function useModelCatalog(owner: string, enabled: boolean) {
  return useQuery({
    queryKey: [PLAYGROUND, "model-catalog", owner],
    queryFn: () => api<ModelCatalogResult>("/api/playground/model-catalog", "POST", { owner }),
    enabled,
  });
}

export const callTool = (owner: string, tool: string) =>
  api<ToolResult>("/api/playground/mcp", "POST", { owner, tool });

export const sendGatewayRequest = (request: GatewayRequest) =>
  api<GatewayResult>("/api/playground/request", "POST", request);
