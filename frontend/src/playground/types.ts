import type { User } from "../types";

export type Effect = "allow" | "deny";

/** One Cerbos decision, explained: the named rule that decided and its reason. */
export type Decision = {
  effect: Effect;
  policy: string;
  rule: string | null;
  reason: string;
};

export type AttrValue = string | number | boolean | string[] | null;
export type Attributes = Record<string, AttrValue>;

export type Principal = { id: string; roles: string[]; attr: Attributes };

export type ResourceItem = { id: string; label: string; attr: Attributes };

export type KindInfo = {
  kind: string;
  description: string;
  actions: string[];
  resources: ResourceItem[];
};

export type PrincipalSpec = {
  persona_id?: string;
  key_owner?: string;
  roles?: string[];
  team_ids?: string[];
  admin_team_ids?: string[];
  department_ids?: string[];
  team_id?: string;
};

export type CheckSpec = {
  principal: PrincipalSpec;
  kind: string;
  resource_ids: string[];
  resource_overrides?: Attributes;
  actions?: string[];
};

export type ScenarioCheck = CheckSpec & {
  label: string;
  actions: string[];
  expect?: Record<string, Effect>;
  expect_by_resource?: Record<string, Record<string, Effect>>;
  expect_after_edit?: Record<string, Effect>;
};

export type TraceSpec = {
  label: string;
  owner: string;
  model: string;
  max_tokens: number;
  path: "gateway" | "direct";
  expect: Effect;
  data_classification?: "public" | "internal" | "confidential";
};

export type Scenario = {
  id: string;
  title: string;
  story: string;
  checks?: ScenarioCheck[];
  trace?: TraceSpec[];
  policy_edit?: { policy: string; find: string; replace: string };
};

export type DemoKey = {
  owner: string;
  name: string;
  team: string;
  key_id: string | null;
  principal: Principal;
};

export type Catalog = {
  personas: User[];
  options: {
    roles: string[];
    teams: { id: string; name: string; department_id: string }[];
    departments: { id: string; name: string }[];
  };
  kinds: KindInfo[];
  scenarios: Scenario[];
  demo_keys: DemoKey[];
  models: { id: string; tier: string }[];
  mcp_tools: { name: string; title: string; risk: string }[];
};

export type CheckResult = {
  principal: Principal;
  kind: string;
  actions: string[];
  results: { id: string; label: string; attr: Attributes; decisions: Record<string, Decision> }[];
};

export type PolicySummary = { id: string; file: string; kind: string; modified: boolean; sha: string };

export type PolicyDocument = {
  id: string;
  file: string;
  yaml: string;
  shipped_yaml: string;
  diff: string;
  sha: string;
  modified: boolean;
};

export type CompileError = {
  file: string;
  line?: number | null;
  column?: number | null;
  message: string;
  context?: string;
};

export type TestFailure = {
  suite: string;
  test: string;
  principal: string;
  resource: string;
  action: string;
  expected: string;
  actual: string;
};

export type ValidationResult = {
  compile: { ok: boolean; errors: CompileError[] };
  tests: { passed: number; failed: number; failures: TestFailure[] };
};

export type SaveResult = ValidationResult & {
  reload_seconds: number;
  sha: string;
  document: PolicyDocument;
};

export type TraceStep = {
  name: string;
  status: "allow" | "deny" | "ok" | "error" | "skipped";
  rule?: string | null;
  reason?: string;
  detail?: string;
};

export type TraceResult = {
  outcome: "allow" | "deny" | "error";
  http_status: number;
  message: string;
  steps: TraceStep[];
  reply?: string;
};

export type PendingEdit = { policy: string; find: string; replace: string; scenario: string };

// --- Story page -------------------------------------------------------------------------

export type Capability = Decision & {
  id: string;
  scope: string;
  label: string;
  was: Effect;
  changed: boolean;
};

export type WhatIf = {
  id: string;
  concept: string;
  label: string;
  hint: string;
  flips: string[];
  spotlight: string | null;
  on: boolean;
};

export type PrincipalView = {
  roles: string[];
  teams: string[];
  admin_teams: string[];
  departments: string[];
};

export type Board = {
  persona: { id: string; name: string };
  before: PrincipalView;
  after: PrincipalView;
  scopes: { id: string; title: string; subtitle: string }[];
  concepts: Record<string, string>;
  what_ifs: WhatIf[];
  spotlights: (Decision & { what_if: string; capability: string })[];
  capabilities: Capability[];
  allowed: number;
  baseline_allowed: number;
  total: number;
};

export type Preset = {
  id: string;
  title: string;
  effect: string;
  policy: string;
  affects: "litellm" | "people";
  on: boolean;
  available: boolean;
};

export type PresetResult = {
  changed: boolean;
  reload_seconds?: number;
  tests?: { passed: number; failed: number };
  presets: Preset[];
};

export type ModelCatalogResult = {
  owner: string;
  visible: string[];
  models: (Decision & { id: string; tier: string; visible: boolean })[];
};

export type ToolResult = {
  owner: string;
  tool: string;
  effect: Effect;
  rule: string | null;
  reason: string;
  result?: string;
};

export type GatewayRequest = {
  owner: string;
  model: string;
  max_tokens: number;
  path: "gateway" | "direct";
  data_classification: "public" | "internal" | "confidential";
};

export type GatewayResult = TraceResult & {
  requested_model: string;
  answered_model: string | null;
  obligations: Record<string, string | number>;
  litellm_rule: string | null;
  litellm_reason: string | null;
};

export type TrafficOutcome =
  | "answered"
  | "downgraded"
  | "capped"
  | "refused"
  | "listed"
  | "hidden"
  | "called"
  | "error";

export type TrafficCell = {
  outcome: TrafficOutcome;
  rule: string | null;
  reason: string;
  answered_model?: string | null;
  obligations?: Record<string, string | number>;
  steps?: TraceStep[];
  visible?: string[];
  result?: string;
};

export type Traffic = {
  keys: { owner: string; team: string; name: string }[];
  situations: { id: string; group: string; title: string }[];
  cells: Record<string, TrafficCell>;
  counts: Partial<Record<TrafficOutcome, number>>;
  calls: number;
  seconds: number;
};
