export type Permissions = Record<string, boolean>;
export type User = {
  id: string;
  name: string;
  email: string;
  roles: string[];
  team_ids: string[];
  admin_team_ids: string[];
  department_ids: string[];
};
export type Budget = {
  id: string;
  name: string;
  scope: string;
  department_id: string;
  team_id: string;
  limit_micros: number;
  spent_micros: number;
  reserved_micros: number;
  permissions: Permissions;
};
export type Asset = {
  id: string;
  name: string;
  description: string;
  kind: "agent" | "mcp" | "skill";
  owner_id: string;
  owner_name: string;
  team_id: string | null;
  team_name: string;
  department_id: string;
  department_name: string;
  visibility: string;
  status: string;
  endpoint: string;
  model: string;
  tags: string[];
  version: number;
  created_at: string;
  permissions: Permissions;
  budget: Budget | null;
};
export type Approval = {
  id: string;
  kind: string;
  title: string;
  resource_id: string;
  department_id: string;
  department_name: string;
  team_name: string;
  requester_id: string;
  requester_name: string;
  status: string;
  reason: string;
  review_note: string;
  payload: Record<string, string | number>;
  permissions: Permissions;
  created_at: string;
};
export type ApiKey = {
  id: string;
  name: string;
  owner_id: string;
  asset_id: string;
  prefix: string;
  models: string[];
  rpm: number;
  tpm: number;
  status: string;
  claimed: boolean;
  expires_at: string;
  budget: Budget;
  permissions: Permissions;
};
export type Team = {
  id: string;
  name: string;
  department_id: string;
  cost_editor_ids: string[];
  permissions: Permissions;
};
export type Department = { id: string; name: string; description: string };
export type AuditEvent = {
  id: string;
  type: string;
  actor_id: string;
  actor_name: string;
  resource_id: string;
  detail: Record<string, unknown>;
  created_at: string;
};
export type Workspace = {
  user: User;
  permissions: Permissions;
  assets: Asset[];
  approvals: Approval[];
  keys: ApiKey[];
  budgets: Budget[];
  teams: Team[];
  departments: Department[];
  users: User[];
  events: AuditEvent[];
  demo_mode: boolean;
  authorization: string;
  model: string;
};
export type PolicyCheck = {
  engine: string;
  policy_version: string;
  principal: Record<string, unknown>;
  resource: Record<string, unknown>;
  decisions: Permissions;
};
export type DialogState =
  | { type: "register" }
  | { type: "edit"; asset: Asset }
  | { type: "asset-budget"; asset: Asset }
  | { type: "budget"; budget: Budget }
  | { type: "key-request"; asset?: Asset }
  | { type: "review"; approval: Approval }
  | { type: "department" }
  | { type: "assign-admin"; department: Department }
  | { type: "delegate"; team: Team }
  | { type: "delete"; asset: Asset }
  | { type: "revoke"; key: ApiKey };
