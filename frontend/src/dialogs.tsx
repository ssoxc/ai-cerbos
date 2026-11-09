import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  Field,
  Input,
  OverlayDrawer,
  Select,
  Textarea,
} from "@fluentui/react-components";
import {
  ArrowRight20Regular,
  Checkmark20Regular,
  Copy20Regular,
  Delete20Regular,
  Dismiss20Regular,
  Edit20Regular,
  Key24Regular,
  LockClosed20Regular,
  ShieldCheckmark24Regular,
  Wallet24Regular,
} from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, gatewayBaseUrl, kindName, money } from "./api";
import { AssetIcon, BudgetMeter, Status } from "./components";
import type { Asset, DialogState, PolicyCheck, Workspace } from "./types";

function defaults(dialog: DialogState, data: Workspace): Record<string, string> {
  const common = {
    name: "",
    description: "",
    kind: "agent",
    team_id: data.user.team_ids[0] || "",
    department_id: data.user.department_ids[0] || "",
    visibility: data.user.team_ids.length ? "team" : "private",
    endpoint: "",
    budget: "100",
    reason: "",
    rpm: "30",
    tpm: "20000",
    days: "30",
    asset_id: data.assets.find((a) => a.permissions.request_key)?.id || "",
    note: "",
    decision: "approve",
    user_id: "",
    grant: "true",
  };
  if (dialog.type === "edit")
    return {
      ...common,
      name: dialog.asset.name,
      description: dialog.asset.description,
      endpoint: dialog.asset.endpoint,
    };
  if (dialog.type === "asset-budget")
    return { ...common, budget: String((dialog.asset.budget?.limit_micros || 0) / 1_000_000) };
  if (dialog.type === "budget") return { ...common, budget: String(dialog.budget.limit_micros / 1_000_000) };
  if (dialog.type === "key-request")
    return { ...common, asset_id: dialog.asset?.id || common.asset_id, budget: "25" };
  if (dialog.type === "review")
    return {
      ...common,
      budget: String(dialog.approval.payload.budget || 0),
      rpm: String(dialog.approval.payload.rpm || 30),
      tpm: String(dialog.approval.payload.tpm || 20000),
    };
  return common;
}

export function ActionDialog({
  dialog,
  data,
  onClose,
  notify,
}: {
  dialog: DialogState;
  data: Workspace;
  onClose: () => void;
  notify: (message: string) => void;
}) {
  const [form, setForm] = useState(() => defaults(dialog, data));
  const queryClient = useQueryClient();
  const set = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const titles = {
    register: "Register an asset",
    edit: "Edit asset",
    "asset-budget": "Propose a budget change",
    budget: "Update budget limit",
    "key-request": "Request an API key",
    review: "Review request",
    department: "New operating unit",
    "assign-admin": "Manage cost administrators",
    delegate: "Delegate cost editing",
    delete: "Archive this asset?",
    revoke: "Revoke this API key?",
  };
  const mutation = useMutation({
    mutationFn: async () => {
      switch (dialog.type) {
        case "register":
          return api("/api/assets", "POST", {
            name: form.name,
            description: form.description,
            kind: form.kind,
            team_id: form.team_id || null,
            department_id: form.department_id,
            visibility: form.visibility,
            endpoint: form.endpoint,
            tags: [],
            budget: form.budget,
          });
        case "edit":
          return api(`/api/assets/${dialog.asset.id}`, "PATCH", {
            name: form.name,
            description: form.description,
            endpoint: form.endpoint,
            version: dialog.asset.version,
          });
        case "asset-budget":
          return api(`/api/assets/${dialog.asset.id}/budget-requests`, "POST", {
            amount: form.budget,
            reason: form.reason,
          });
        case "budget":
          return api(`/api/budgets/${dialog.budget.id}`, "PATCH", {
            amount: form.budget,
            reason: form.reason,
          });
        case "key-request":
          return api("/api/key-requests", "POST", {
            name: form.name,
            asset_id: form.asset_id,
            budget: form.budget,
            rpm: Number(form.rpm),
            tpm: Number(form.tpm),
            days: Number(form.days),
            reason: form.reason,
          });
        case "review":
          return api(`/api/approvals/${dialog.approval.id}/decision`, "POST", {
            decision: form.decision,
            note: form.note,
            ...(dialog.approval.kind === "key" && form.decision === "approve"
              ? { budget: form.budget, rpm: Number(form.rpm), tpm: Number(form.tpm) }
              : {}),
          });
        case "department":
          return api("/api/departments", "POST", { name: form.name, description: form.description });
        case "assign-admin":
          return api(`/api/departments/${dialog.department.id}/cost-admins`, "PUT", {
            user_id: form.user_id,
            grant: form.grant === "true",
          });
        case "delegate":
          return api(`/api/teams/${dialog.team.id}/delegations`, "PUT", {
            user_id: form.user_id,
            grant: form.grant === "true",
          });
        case "delete":
          return api(`/api/assets/${dialog.asset.id}`, "DELETE");
        case "revoke":
          return api(`/api/keys/${dialog.key.id}/revoke`, "POST");
      }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspace"] });
      await queryClient.invalidateQueries({ queryKey: ["policy"] });
      notify(
        dialog.type === "register"
          ? "Asset submitted. Your cost-center administrator will review it."
          : dialog.type === "key-request"
            ? "API key request sent to the Agents team for approval."
            : dialog.type === "asset-budget"
              ? "Budget change submitted. The existing limit stays in effect until approval."
              : dialog.type === "review"
                ? "Decision recorded in the audit trail."
                : "Change saved and recorded in the audit trail.",
      );
      onClose();
    },
  });
  const input = (
    key: string,
    label: string,
    options: { type?: string; min?: number; max?: number; required?: boolean; hint?: string } = {},
  ) => (
    <Field
      label={label}
      required={options.required !== false}
      hint={options.hint ? { children: options.hint, className: "field-hint" } : undefined}
    >
      <Input
        className="field-input"
        value={form[key] || ""}
        onChange={(_, details) => set(key, details.value)}
        type={(options.type as "number" | "text") || "text"}
        required={options.required !== false}
        min={options.min}
        max={options.max}
        minLength={key === "name" ? 3 : undefined}
        maxLength={key === "name" ? 120 : undefined}
        step={options.type === "number" ? "any" : undefined}
      />
    </Field>
  );
  const textarea = (key: string, label: string, minLength = 5) => (
    <Field label={label} required>
      <Textarea
        className="field-textarea"
        value={form[key] || ""}
        onChange={(_, details) => set(key, details.value)}
        required
        minLength={minLength}
        maxLength={2000}
        resize="vertical"
        rows={3}
      />
    </Field>
  );
  const budgetInput = input("budget", "Budget cap (USD)", { type: "number", min: 0, max: 1000000 });
  const submitLabel =
    dialog.type === "delete"
      ? "Archive asset"
      : dialog.type === "revoke"
        ? "Revoke key"
        : dialog.type === "review"
          ? form.decision === "approve"
            ? "Approve request"
            : "Decline request"
          : ["register", "asset-budget", "key-request", "edit"].includes(dialog.type)
            ? "Submit for approval"
            : "Save changes";
  return (
    <Dialog
      open
      onOpenChange={(_, details) => {
        if (!details.open && !mutation.isPending) onClose();
      }}
    >
      <DialogSurface className="action-dialog">
        <DialogBody>
          <DialogTitle
            action={
              <Button
                appearance="subtle"
                icon={<Dismiss20Regular />}
                aria-label="Close dialog"
                disabled={mutation.isPending}
                onClick={onClose}
              />
            }
          >
            {titles[dialog.type]}
          </DialogTitle>
          <form
            className="dialog-form"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            <DialogContent className="form-content">
              {(dialog.type === "register" || dialog.type === "edit") && (
                <>
                  <p className="dialog-intro">
                    {dialog.type === "register"
                      ? "Add a building block to your workspace. Your operating unit’s cost administrator will review it before it becomes active."
                      : "Changes require reapproval. The asset will pause until its new version is approved."}
                  </p>
                  {input("name", "Asset name")}
                  {textarea("description", "What does this asset do?", 10)}
                  {dialog.type === "register" && (
                    <>
                      <div className="form-grid">
                        <Field label="Asset type">
                          <Select
                            className="field-select"
                            value={form.kind}
                            onChange={(e) => set("kind", e.target.value)}
                          >
                            <option value="agent">AI agent</option>
                            <option value="mcp">MCP server</option>
                            <option value="skill">Agent skill</option>
                          </Select>
                        </Field>
                        <Field label="Visibility">
                          <Select
                            className="field-select"
                            value={form.visibility}
                            onChange={(e) => {
                              set("visibility", e.target.value);
                              if (e.target.value === "private") set("team_id", "");
                            }}
                          >
                            <option value="team" disabled={!form.team_id}>
                              Team
                            </option>
                            <option value="private">Private (personal)</option>
                            <option value="global">Global catalog</option>
                          </Select>
                        </Field>
                      </div>
                      <div className="form-grid">
                        <Field label="Operating unit">
                          <Select
                            className="field-select"
                            value={form.department_id}
                            onChange={(e) => {
                              const dept = e.target.value;
                              const teamId =
                                data.teams.find(
                                  (t) => t.department_id === dept && data.user.team_ids.includes(t.id),
                                )?.id || "";
                              setForm((f) => ({
                                ...f,
                                department_id: dept,
                                team_id: teamId,
                                visibility: teamId ? "team" : "private",
                              }));
                            }}
                          >
                            {data.departments
                              .filter((d) => data.user.department_ids.includes(d.id))
                              .map((d) => (
                                <option key={d.id} value={d.id}>
                                  {d.name}
                                </option>
                              ))}
                          </Select>
                        </Field>
                        <Field label="Owning team">
                          <Select
                            className="field-select"
                            value={form.team_id}
                            onChange={(e) => {
                              set("team_id", e.target.value);
                              if (!e.target.value) set("visibility", "private");
                              else if (form.visibility === "private") set("visibility", "team");
                            }}
                          >
                            <option value="">Personal asset</option>
                            {data.teams
                              .filter(
                                (t) =>
                                  t.department_id === form.department_id && data.user.team_ids.includes(t.id),
                              )
                              .map((t) => (
                                <option key={t.id} value={t.id}>
                                  {t.name}
                                </option>
                              ))}
                          </Select>
                        </Field>
                      </div>
                      {form.kind === "agent" && budgetInput}
                    </>
                  )}
                  {input("endpoint", "Endpoint or reference URL", {
                    required: false,
                    hint: "HTTPS URL. Stored as registry metadata; never fetched automatically.",
                  })}
                  <div className="form-note">
                    <ShieldCheckmark24Regular />
                    Approval is required before this asset can be used.
                  </div>
                </>
              )}
              {(dialog.type === "asset-budget" || dialog.type === "budget") && (
                <>
                  <p className="dialog-intro">
                    {dialog.type === "asset-budget"
                      ? `Propose a new spending cap for ${dialog.asset.name}. Your cost-center administrator makes the final decision.`
                      : `Set the cumulative spending cap for ${dialog.budget.name}. The limit cannot fall below spent and reserved funds.`}
                  </p>
                  {budgetInput}
                  {textarea("reason", "Reason for this change")}
                </>
              )}
              {dialog.type === "key-request" && (
                <>
                  <p className="dialog-intro">
                    The Agents team reviews API access. Your key will be restricted to the selected agent, the
                    demo model, and your approved limits.
                  </p>
                  {input("name", "Project / key name")}
                  <Field label="Approved agent" required>
                    <Select
                      className="field-select"
                      value={form.asset_id}
                      onChange={(e) => set("asset_id", e.target.value)}
                      required
                    >
                      <option value="">Choose an agent</option>
                      {data.assets
                        .filter((a) => a.permissions.request_key)
                        .map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                    </Select>
                  </Field>
                  <div className="form-grid">
                    {budgetInput}
                    {input("days", "Expires in (days)", { type: "number", min: 1, max: 90 })}
                  </div>
                  <div className="form-grid">
                    {input("rpm", "Requests per minute", { type: "number", min: 1, max: 600 })}
                    {input("tpm", "Tokens per minute", { type: "number", min: 256, max: 1000000 })}
                  </div>
                  {textarea("reason", "What will you use this key for?")}
                </>
              )}
              {dialog.type === "review" && (
                <>
                  <div className="review-summary">
                    <span className="small-label">{dialog.approval.kind.toUpperCase()} REQUEST</span>
                    <h3>{dialog.approval.title}</h3>
                    <p>{dialog.approval.reason}</p>
                    <div>
                      {dialog.approval.requester_name}
                      <span className="middle-dot">·</span>
                      {dialog.approval.department_name}
                    </div>
                    <strong>
                      {money(Number(dialog.approval.payload.budget || 0) * 1_000_000)} requested
                    </strong>
                  </div>
                  <Field label="Decision">
                    <Select
                      className="field-select"
                      value={form.decision}
                      onChange={(e) => set("decision", e.target.value)}
                    >
                      <option value="approve">Approve</option>
                      <option value="decline">Decline</option>
                    </Select>
                  </Field>
                  {dialog.approval.kind === "key" && form.decision === "approve" && (
                    <>
                      <p className="muted">
                        You may reduce the requested limits. Increasing them requires a new request.
                      </p>
                      {budgetInput}
                      <div className="form-grid">
                        {input("rpm", "Requests per minute", { type: "number", min: 1 })}
                        {input("tpm", "Tokens per minute", { type: "number", min: 256 })}
                      </div>
                    </>
                  )}
                  {textarea("note", "Review note")}
                </>
              )}
              {dialog.type === "department" && (
                <>
                  <p className="dialog-intro">
                    Create an operating unit with a zero spending cap. Assign a cost administrator to
                    establish its budget.
                  </p>
                  {input("name", "Operating unit name")}
                  {textarea("description", "Description")}
                </>
              )}
              {(dialog.type === "assign-admin" || dialog.type === "delegate") && (
                <>
                  <p className="dialog-intro">
                    {dialog.type === "assign-admin"
                      ? `Assign or remove a dedicated cost-center administrator for ${dialog.department.name}.`
                      : `Allow a team member to propose agent budget changes for ${dialog.team.name}. Every proposal still requires independent approval.`}
                  </p>
                  <Field
                    label={dialog.type === "assign-admin" ? "Cost-center administrator" : "Team member"}
                    required
                  >
                    <Select
                      className="field-select"
                      value={form.user_id}
                      onChange={(e) => set("user_id", e.target.value)}
                      required
                    >
                      <option value="">Choose a person</option>
                      {data.users
                        .filter((user) =>
                          dialog.type === "assign-admin"
                            ? user.roles.includes("cost_center_admin")
                            : user.team_ids.includes(dialog.team.id) &&
                              user.roles.some((r) => r === "developer" || r === "viewer"),
                        )
                        .map((user) => (
                          <option key={user.id} value={user.id}>
                            {user.name}
                            {dialog.type === "delegate" && dialog.team.cost_editor_ids.includes(user.id)
                              ? " · access granted"
                              : ""}
                          </option>
                        ))}
                    </Select>
                  </Field>
                  <Field label="Action">
                    <Select
                      className="field-select"
                      value={form.grant}
                      onChange={(e) => set("grant", e.target.value)}
                    >
                      <option value="true">Grant access</option>
                      <option value="false">Revoke access</option>
                    </Select>
                  </Field>
                </>
              )}
              {dialog.type === "delete" && (
                <p className="dialog-intro">
                  <strong>{dialog.asset.name}</strong> will leave the active registry. Its API keys will be
                  revoked and pending requests cancelled. The audit history is retained.
                </p>
              )}
              {dialog.type === "revoke" && (
                <p className="dialog-intro">
                  <strong>{dialog.key.name}</strong> will stop accepting new requests immediately. Requests
                  already in progress may complete. Create a new request if access is needed again.
                </p>
              )}
              {mutation.error && (
                <div className="form-error" role="alert">
                  {mutation.error.message}
                </div>
              )}
            </DialogContent>
            <DialogActions className="form-actions">
              <Button type="button" onClick={onClose} disabled={mutation.isPending}>
                Cancel
              </Button>
              <Button appearance="primary" type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Saving…" : submitLabel}
              </Button>
            </DialogActions>
          </form>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export function AssetDrawer({
  asset,
  onClose,
  open,
  userId,
}: {
  asset: Asset | null;
  onClose: () => void;
  open: (dialog: DialogState) => void;
  userId: string;
}) {
  const policy = useQuery({
    queryKey: ["policy", userId, asset?.id],
    queryFn: () => api<PolicyCheck>(`/api/policy-check/${asset?.id}`),
    enabled: !!asset,
  });
  const action = (dialog: DialogState) => {
    onClose();
    open(dialog);
  };
  return (
    <OverlayDrawer
      position="end"
      size="medium"
      open={!!asset}
      onOpenChange={(_, details) => {
        if (!details.open) onClose();
      }}
    >
      <DrawerHeader>
        <DrawerHeaderTitle
          action={
            <Button
              appearance="subtle"
              icon={<Dismiss20Regular />}
              aria-label="Close asset details"
              onClick={onClose}
            />
          }
        >
          Asset details
        </DrawerHeaderTitle>
      </DrawerHeader>
      {asset && (
        <DrawerBody className="asset-drawer">
          <div className="drawer-asset-heading">
            <AssetIcon kind={asset.kind} />
            <Status value={asset.status} />
          </div>
          <span className="small-label">
            {kindName(asset.kind)}
            <span className="middle-dot">·</span>Version {asset.version}
          </span>
          <h2>{asset.name}</h2>
          <p className="drawer-description">{asset.description}</p>
          <div className="tags">
            {asset.tags.map((tag) => (
              <Badge key={tag} className="tag-badge" appearance="outline">
                {tag}
              </Badge>
            ))}
          </div>
          <div className="drawer-actions">
            {asset.permissions.edit && (
              <Button icon={<Edit20Regular />} onClick={() => action({ type: "edit", asset })}>
                Edit asset
              </Button>
            )}
            {asset.permissions.request_key && (
              <Button
                appearance="primary"
                icon={<Key24Regular />}
                onClick={() => action({ type: "key-request", asset })}
              >
                Request key
              </Button>
            )}
            {asset.permissions.request_budget && (
              <Button icon={<Wallet24Regular />} onClick={() => action({ type: "asset-budget", asset })}>
                Propose budget
              </Button>
            )}
          </div>
          <dl className="asset-metadata">
            <div>
              <dt>Owner</dt>
              <dd>{asset.owner_name}</dd>
            </div>
            <div>
              <dt>Team</dt>
              <dd>{asset.team_name}</dd>
            </div>
            <div>
              <dt>Operating unit</dt>
              <dd>{asset.department_name}</dd>
            </div>
            <div>
              <dt>Visibility</dt>
              <dd>{asset.visibility}</dd>
            </div>
            {asset.kind === "agent" && (
              <div>
                <dt>Model</dt>
                <dd>
                  <code>{asset.model}</code>
                </dd>
              </div>
            )}
            {asset.endpoint && (
              <div>
                <dt>Reference URL</dt>
                <dd>
                  <code>{asset.endpoint}</code>
                </dd>
              </div>
            )}
          </dl>
          {asset.budget && asset.kind === "agent" && (
            <div className="drawer-budget">
              <h3>Approved budget</h3>
              <BudgetMeter budget={asset.budget} />
            </div>
          )}
          <div className="decision-panel">
            <div className="decision-heading">
              <ShieldCheckmark24Regular />
              <h3>Your access to this asset</h3>
              <span className="live-dot" />
            </div>
            <p>Live decisions from Cerbos for your current identity.</p>
            {policy.isLoading && <p>Evaluating permissions…</p>}
            {policy.error && <p className="form-error">{policy.error.message}</p>}
            {Object.entries(policy.data?.decisions || asset.permissions).map(([name, allowed]) => (
              <div className="decision-row" key={name}>
                <span>
                  {{
                    view: "View asset",
                    edit: "Edit asset",
                    delete: "Archive asset",
                    request_budget: "Propose budget",
                    request_key: "Request API key",
                    use: "Use agent",
                  }[name] || name}
                </span>
                <span className={allowed ? "allowed" : "denied"}>
                  {allowed ? <Checkmark20Regular /> : <LockClosed20Regular />}
                  {allowed ? "Allowed" : "Denied"}
                </span>
              </div>
            ))}
            {policy.data && (
              <details className="decision-raw">
                <summary>Inspect policy input</summary>
                <pre>
                  {JSON.stringify(
                    { principal: policy.data.principal, resource: policy.data.resource },
                    null,
                    2,
                  )}
                </pre>
              </details>
            )}
          </div>
          {asset.permissions.delete && (
            <Button
              appearance="subtle"
              className="danger-action"
              icon={<Delete20Regular />}
              onClick={() => action({ type: "delete", asset })}
            >
              Archive asset
            </Button>
          )}
        </DrawerBody>
      )}
    </OverlayDrawer>
  );
}

export function SecretDialog({ secret, onClose }: { secret: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  return (
    // The backend reveals a key exactly once. "alert" ignores Escape and backdrop clicks,
    // so the secret can only be dismissed through the explicit button below.
    <Dialog
      modalType="alert"
      open={!!secret}
      onOpenChange={(_, details) => {
        if (!details.open) {
          setCopied(false);
          onClose();
        }
      }}
    >
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Your API key is ready</DialogTitle>
          <DialogContent>
            <p className="dialog-intro">
              Copy this key now. It can only be revealed once. Keep it in your project’s secret store.
            </p>
            <pre className="secret-value">{secret}</pre>
            <div className="form-note">
              <LockClosed20Regular />
              Base URL: {gatewayBaseUrl()}
              <br />
              Model: governed-demo
              <br />
              Include a unique Idempotency-Key header for each request.
            </div>
            {error && <p role="alert">{error}</p>}
          </DialogContent>
          <DialogActions>
            <Button
              icon={<Copy20Regular />}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(secret);
                  setCopied(true);
                } catch {
                  setError("Clipboard unavailable. Select and copy the key above.");
                }
              }}
            >
              {copied ? "Copied" : "Copy key"}
            </Button>
            <Button
              appearance="primary"
              icon={<ArrowRight20Regular />}
              iconPosition="after"
              onClick={() => {
                setCopied(false);
                onClose();
              }}
            >
              I’ve saved my key
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
