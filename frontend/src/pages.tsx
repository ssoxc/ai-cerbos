import {
  Badge,
  Button,
  Input,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  Select,
  Tab,
  TabList,
} from "@fluentui/react-components";
import {
  Add20Regular,
  ArrowDownload20Regular,
  ArrowRight20Regular,
  ArrowUpRight16Regular,
  Bot24Regular,
  CheckmarkCircle20Regular,
  ChevronRight16Regular,
  Clock20Regular,
  Copy20Regular,
  Grid24Regular,
  Info20Regular,
  Key24Regular,
  LockClosed20Regular,
  Organization24Regular,
  PeopleTeam24Regular,
  Play20Regular,
  PlugConnected24Regular,
  Search20Regular,
  ShieldCheckmark24Regular,
  Sparkle24Regular,
  TextBulletList24Regular,
  Wallet24Regular,
} from "@fluentui/react-icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { PageProps } from "./App";
import { api, gatewayBaseUrl, kindName, money, relativeTime, roleName } from "./api";
import { ActivityList, AssetIcon, AssetTable, BudgetMeter, Empty, SectionTitle, Status } from "./components";
import type { ApiKey } from "./types";

function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

export function Overview({ data, open, select }: PageProps) {
  const navigate = useNavigate();
  const [kind, setKind] = useState("all");
  const pending = data.approvals.filter((a) => a.status === "pending");
  const teamBudgets = data.budgets.filter((b) => b.scope === "team");
  const shownBudgets = teamBudgets.length
    ? teamBudgets
    : data.assets.flatMap((asset) => (asset.kind === "agent" && asset.budget ? [asset.budget] : []));
  const spent = shownBudgets.reduce((sum, b) => sum + b.spent_micros, 0);
  const cap = shownBudgets.reduce((sum, b) => sum + b.limit_micros, 0);
  const assets = data.assets.filter((asset) => kind === "all" || asset.kind === kind);
  return (
    <>
      <PageHeading
        eyebrow="YOUR AI CONTROL CENTER"
        title="Everything AI. Under control."
        description="A shared home for your AI assets, access, and spending."
        action={
          data.permissions.register_asset && (
            <Button
              appearance="primary"
              icon={<Add20Regular />}
              size="large"
              onClick={() => open({ type: "register" })}
            >
              Register asset
            </Button>
          )
        }
      />
      <div className="scope-strip">
        <span className="live-dot" />
        Your workspace at a glance
        <span className="scope-text">
          {data.departments.length === 1
            ? data.departments[0].name
            : `${data.departments.length} operating units`}
          <span className="middle-dot">·</span>
          {roleName(data.user.roles[0])}
        </span>
      </div>
      {data.demo_mode && (
        <MessageBar intent="info" layout="multiline">
          <MessageBarBody>
            <MessageBarTitle>New here? Open the Cerbos playground.</MessageBarTitle>
            See what each person can do and why, change a rule and watch every decision follow, and see Cerbos
            governing models, model catalogs and MCP tools inside LiteLLM.
          </MessageBarBody>
          <MessageBarActions>
            <Button appearance="primary" onClick={() => navigate("/playground")}>
              Open the Cerbos playground
            </Button>
          </MessageBarActions>
        </MessageBar>
      )}
      <div className="metrics-grid">
        <div className="metric">
          <div>
            <span>Registered assets</span>
            <span className="metric-icon">
              <Bot24Regular />
            </span>
          </div>
          <strong>{data.assets.length.toString().padStart(2, "0")}</strong>
          <p>
            <span className="mini-dot green" />
            {data.assets.filter((a) => a.status === "active").length} active in your view
          </p>
        </div>
        <div className="metric">
          <div>
            <span>Budget consumed</span>
            <span className="metric-icon">
              <Wallet24Regular />
            </span>
          </div>
          <strong>{money(spent)}</strong>
          <p>
            {money(cap)} approved cap{" "}
            <span className="metric-percent">{cap ? Math.round((spent / cap) * 100) : 0}%</span>
          </p>
        </div>
        <div className="metric">
          <div>
            <span>Pending requests</span>
            <span className="metric-icon">
              <Clock20Regular />
            </span>
          </div>
          <strong>{pending.length.toString().padStart(2, "0")}</strong>
          <p>
            <span className="mini-dot amber" />
            {pending.filter((a) => a.permissions.approve).length
              ? `${pending.filter((a) => a.permissions.approve).length} ready for your review`
              : "Following the approval workflow"}
          </p>
        </div>
        <div className="metric">
          <div>
            <span>Governed teams</span>
            <span className="metric-icon">
              <PeopleTeam24Regular />
            </span>
          </div>
          <strong>{data.teams.length.toString().padStart(2, "0")}</strong>
          <p>
            <ShieldCheckmark24Regular />
            Scoped access by Cerbos
          </p>
        </div>
      </div>
      <div className="governance-banner">
        <div className="banner-icon">
          <ShieldCheckmark24Regular />
        </div>
        <div>
          <h3>Move fast. Keep the guardrails.</h3>
          <p>Every asset has an owner. Every action has a policy. Every request has a limit.</p>
        </div>
        <Button
          appearance="transparent"
          onClick={() => navigate("/policies")}
          icon={<ArrowRight20Regular />}
          iconPosition="after"
        >
          Explore your access
        </Button>
        <div className="banner-pattern" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
      <div className="overview-grid">
        <section className="panel registry-panel">
          <SectionTitle
            title="Your asset registry"
            description="Discover what your teams are building."
            action={
              <Button
                appearance="transparent"
                onClick={() => navigate("/assets")}
                icon={<ArrowUpRight16Regular />}
                iconPosition="after"
              >
                View all
              </Button>
            }
          />
          <div className="panel-tabs">
            <TabList selectedValue={kind} onTabSelect={(_, details) => setKind(String(details.value))}>
              {[
                ["all", "All assets"],
                ["agent", "Agents"],
                ["mcp", "MCP servers"],
                ["skill", "Skills"],
              ].map(([id, label]) => (
                <Tab value={id} key={id}>
                  {label}
                </Tab>
              ))}
            </TabList>
            <span className="quiet-count">{assets.length} assets</span>
          </div>
          <AssetTable assets={assets.slice(0, 5)} onSelect={select} />
          <button type="button" className="table-footer" onClick={() => navigate("/assets")}>
            Explore the full registry
            <ArrowRight20Regular />
          </button>
        </section>
        <aside className="overview-side">
          <section className="panel review-panel">
            <SectionTitle
              title="Approval inbox"
              action={<span className="count-bubble">{pending.length}</span>}
            />
            {pending.slice(0, 3).map((a) => (
              <button
                key={a.id}
                type="button"
                className="inbox-item"
                onClick={() =>
                  a.permissions.approve ? open({ type: "review", approval: a }) : navigate("/approvals")
                }
              >
                <span className={`request-type-icon ${a.kind}`}>
                  {a.kind === "key" ? (
                    <Key24Regular />
                  ) : a.kind === "budget" ? (
                    <Wallet24Regular />
                  ) : (
                    <Bot24Regular />
                  )}
                </span>
                <span>
                  <strong>{a.title}</strong>
                  <small>
                    {a.requester_name}
                    <span className="middle-dot">·</span>
                    {relativeTime(a.created_at)}
                  </small>
                </span>
                <ChevronRight16Regular />
              </button>
            ))}
            {!pending.length && (
              <div className="all-clear">
                <CheckmarkCircle20Regular />
                <p>All caught up.</p>
                <span>No pending requests in your scope.</span>
              </div>
            )}
            <Button
              className="inbox-link"
              appearance="transparent"
              onClick={() => navigate("/approvals")}
              icon={<ArrowRight20Regular />}
              iconPosition="after"
            >
              Open approvals
            </Button>
          </section>
          <section className="panel budget-panel">
            <SectionTitle
              title={teamBudgets.length ? "Team budgets" : "Asset budgets"}
              action={<span className="small-label">USD</span>}
            />
            {shownBudgets.slice(0, 3).map((b) => (
              <div className="team-budget" key={b.id}>
                <div>
                  <strong>{b.name}</strong>
                  <span>{b.limit_micros ? Math.round((b.spent_micros / b.limit_micros) * 100) : 0}%</span>
                </div>
                <div className="meter-track">
                  <span
                    style={{
                      width: `${Math.min(100, b.limit_micros ? (b.spent_micros / b.limit_micros) * 100 : 0)}%`,
                    }}
                  />
                </div>
                <small>
                  {money(b.spent_micros)} of {money(b.limit_micros)}
                </small>
              </div>
            ))}
            {!shownBudgets.length && (
              <p className="muted">Budget details are restricted to their owners and administrators.</p>
            )}
            <div className="subtle-note">
              <LockClosed20Regular />
              Limits enforced before each request
            </div>
          </section>
        </aside>
      </div>
      <section className="panel activity-panel">
        <SectionTitle
          title="Recent activity"
          action={
            <Button
              appearance="transparent"
              onClick={() => navigate("/audit")}
              icon={<ArrowUpRight16Regular />}
              iconPosition="after"
            >
              Audit log
            </Button>
          }
        />
        <ActivityList events={data.events} limit={3} />
      </section>
    </>
  );
}

export function Registry({ data, open, select }: PageProps) {
  const [params, setParams] = useSearchParams();
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState("all");
  const [grid, setGrid] = useState(false);
  const search = params.get("q") || "";
  const assets = data.assets.filter(
    (asset) =>
      (kind === "all" || asset.kind === kind) &&
      (status === "all" || asset.status === status) &&
      `${asset.name} ${asset.description} ${asset.tags.join(" ")} ${asset.team_name}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeading
        eyebrow="DISCOVER & BUILD"
        title="Asset registry"
        description="The right building blocks. With the right permissions."
        action={
          data.permissions.register_asset && (
            <Button appearance="primary" icon={<Add20Regular />} onClick={() => open({ type: "register" })}>
              Register asset
            </Button>
          )
        }
      />
      <div className="registry-summary">
        {[
          ["agent", "AI agents", Bot24Regular],
          ["mcp", "MCP servers", PlugConnected24Regular],
          ["skill", "Agent skills", Sparkle24Regular],
        ].map(([id, label, Icon]) => {
          const KindSymbol = Icon as typeof Bot24Regular;
          return (
            <button
              className={`registry-summary-item ${kind === id ? "selected" : ""}`}
              type="button"
              key={String(id)}
              onClick={() => setKind(kind === id ? "all" : String(id))}
            >
              <AssetIcon kind={String(id)} />
              <div>
                <span>{String(label)}</span>
                <strong>{data.assets.filter((a) => a.kind === id).length}</strong>
              </div>
              <KindSymbol className="summary-watermark" />
            </button>
          );
        })}
      </div>
      <section className="panel">
        <div className="filter-toolbar">
          <Input
            className="field-input"
            aria-label="Search registry"
            value={search}
            onChange={(_, details) => setParams(details.value ? { q: details.value } : {}, { replace: true })}
            contentBefore={<Search20Regular />}
            placeholder="Search assets, teams, or tags…"
          />
          <Select
            aria-label="Filter by status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="pending">Pending approval</option>
            <option value="declined">Declined</option>
          </Select>
          <span className="toolbar-spacer" />
          <span className="muted">{assets.length} assets</span>
          <div className="view-toggle">
            <Button
              appearance={!grid ? "secondary" : "subtle"}
              icon={<TextBulletList24Regular />}
              aria-label="List view"
              onClick={() => setGrid(false)}
            />
            <Button
              appearance={grid ? "secondary" : "subtle"}
              icon={<Grid24Regular />}
              aria-label="Grid view"
              onClick={() => setGrid(true)}
            />
          </div>
        </div>
        {grid ? (
          <div className="asset-grid">
            {assets.map((asset) => (
              <button type="button" className="asset-card" key={asset.id} onClick={() => select(asset)}>
                <div>
                  <AssetIcon kind={asset.kind} />
                  <Status value={asset.status} />
                </div>
                <span className="small-label">{kindName(asset.kind)}</span>
                <h3>{asset.name}</h3>
                <p>{asset.description}</p>
                <div className="asset-card-footer">
                  <span>{asset.team_name}</span>
                  <ArrowUpRight16Regular />
                </div>
              </button>
            ))}
            {!assets.length && (
              <Empty title="No matching assets" description="Try a different search or status." />
            )}
          </div>
        ) : (
          <AssetTable assets={assets} onSelect={select} />
        )}
      </section>
      <div className="scope-callout">
        <ShieldCheckmark24Regular />
        <span>
          Showing assets your role can access. Global catalog access does not grant edit or spending
          permissions.
        </span>
      </div>
    </>
  );
}

export function Approvals({ data, open }: PageProps) {
  const [tab, setTab] = useState("pending");
  const filtered = data.approvals.filter(
    (a) => tab === "all" || (tab === "pending" ? a.status === "pending" : a.status !== "pending"),
  );
  return (
    <>
      <PageHeading
        eyebrow="HUMAN OVERSIGHT"
        title="Approvals"
        description="A clear checkpoint for new assets, budget changes, and API access."
      />
      <section className="panel">
        <div className="panel-tabs">
          <TabList selectedValue={tab} onTabSelect={(_, details) => setTab(String(details.value))}>
            <Tab value="pending">
              Pending{" "}
              <span className="inline-count">
                {data.approvals.filter((a) => a.status === "pending").length}
              </span>
            </Tab>
            <Tab value="history">History</Tab>
            <Tab value="all">All requests</Tab>
          </TabList>
          <span className="quiet-count">Scoped to your access</span>
        </div>
        <div className="approval-list">
          {filtered.map((a) => (
            <article className="approval-row" key={a.id}>
              <span className={`request-type-icon ${a.kind}`}>
                {a.kind === "key" ? (
                  <Key24Regular />
                ) : a.kind === "budget" ? (
                  <Wallet24Regular />
                ) : (
                  <Bot24Regular />
                )}
              </span>
              <div className="approval-description">
                <div className="row-title">
                  <h3>{a.title}</h3>
                  <Status value={a.status} />
                </div>
                <p>{a.reason}</p>
                <div className="metadata-line">
                  <span>{a.requester_name}</span>
                  <span>{a.team_name}</span>
                  <span>{relativeTime(a.created_at)}</span>
                </div>
                {a.review_note && <div className="review-note">Review: {a.review_note}</div>}
              </div>
              <div className="approval-action">
                <strong>{a.payload.budget ? money(Number(a.payload.budget) * 1_000_000) : "—"}</strong>
                <small>{a.kind === "key" ? "Requested key limit" : "Requested budget"}</small>
                {a.permissions.approve && a.status === "pending" ? (
                  <Button appearance="primary" onClick={() => open({ type: "review", approval: a })}>
                    Review request
                  </Button>
                ) : (
                  <span className="small-label">
                    {a.status === "pending" ? "Awaiting approver" : "Decision recorded"}
                  </span>
                )}
              </div>
            </article>
          ))}
          {!filtered.length && (
            <Empty
              title="Nothing waiting here"
              description="Requests appear here when an asset, budget, or API key needs approval."
            />
          )}
        </div>
      </section>
      <div className="scope-callout">
        <ShieldCheckmark24Regular />
        <span>
          Approvers cannot approve their own requests. Asset and budget approvals stay within their assigned
          operating units.
        </span>
      </div>
    </>
  );
}

export function Keys({ data, open, notify, reveal }: PageProps) {
  const queryClient = useQueryClient();
  const [testResult, setTestResult] = useState("");
  const action = useMutation({
    mutationFn: async ({ key, type }: { key: ApiKey; type: "claim" | "test" }) => {
      if (type === "claim") {
        const result = await api<{ key: string }>(`/api/keys/${key.id}/claim`, "POST");
        reveal(result.key);
      } else {
        const result = await api<{
          choices: { message: { content: string } }[];
          usage: { total_tokens: number };
        }>(`/api/keys/${key.id}/test`, "POST");
        setTestResult(
          `${result.choices[0].message.content}\n\n${result.usage.total_tokens} tokens · Usage recorded across every applicable budget.`,
        );
        notify("Test request completed through the governed LiteLLM gateway.");
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace"] }),
  });
  return (
    <>
      <PageHeading
        eyebrow="CONTROLLED CONNECTIONS"
        title="API keys"
        description="Project access with an owner, an expiry date, and a hard spending limit."
        action={
          data.permissions.request_key && (
            <Button
              appearance="primary"
              icon={<Add20Regular />}
              onClick={() => open({ type: "key-request" })}
            >
              Request API key
            </Button>
          )
        }
      />
      <div className="info-banner">
        <Key24Regular />
        <div>
          <strong>One gateway. Every limit enforced.</strong>
          <p>
            Use your approved LiteLLM key with <code>{gatewayBaseUrl()}</code>. Your key can only access
            approved models and agents.
          </p>
        </div>
      </div>
      {action.error && (
        <div className="error-banner" role="alert">
          {action.error.message}
        </div>
      )}
      <section className="panel">
        <SectionTitle
          title="Issued keys"
          description={`${data.keys.filter((key) => key.status === "active").length} active keys visible to you`}
        />
        {data.keys.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Project / key</th>
                  <th>Limits</th>
                  <th>Budget</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.keys.map((key) => (
                  <tr key={key.id}>
                    <td>
                      <strong>{key.name}</strong>
                      <small className="cell-subtitle">
                        <code>{key.prefix}</code> · Expires {new Date(key.expires_at).toLocaleDateString()}
                      </small>
                    </td>
                    <td>
                      <strong className="normal-weight">{key.rpm} RPM</strong>
                      <small className="cell-subtitle">{key.tpm.toLocaleString()} TPM</small>
                    </td>
                    <td>
                      <BudgetMeter budget={key.budget} compact />
                    </td>
                    <td>
                      <Status value={new Date(key.expires_at) < new Date() ? "expired" : key.status} />
                    </td>
                    <td>
                      <div className="inline-actions">
                        {key.permissions.claim && key.status === "active" && !key.claimed && (
                          <Button
                            icon={<Copy20Regular />}
                            disabled={action.isPending}
                            onClick={() => action.mutate({ key, type: "claim" })}
                          >
                            Reveal once
                          </Button>
                        )}
                        {key.permissions.claim && key.status === "active" && (
                          <Button
                            icon={<Play20Regular />}
                            disabled={action.isPending}
                            onClick={() => action.mutate({ key, type: "test" })}
                          >
                            Test
                          </Button>
                        )}
                        {key.permissions.revoke && key.status === "active" && (
                          <Button appearance="subtle" onClick={() => open({ type: "revoke", key })}>
                            Revoke
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="Your next project starts here"
            description="Request a key for an approved agent. A member of the Agents team will review the request and set its limits."
            action={
              data.permissions.request_key && (
                <Button appearance="primary" onClick={() => open({ type: "key-request" })}>
                  Request your first key
                </Button>
              )
            }
          />
        )}
      </section>
      {testResult && (
        <section className="panel test-result">
          <SectionTitle
            title="Gateway response"
            action={
              <Badge appearance="tint" color="success">
                Completed
              </Badge>
            }
          />
          <p>{testResult}</p>
        </section>
      )}
      <div className="key-flow">
        <div>
          <span>01</span>
          <strong>Request access</strong>
          <p>Choose an agent and propose limits.</p>
        </div>
        <ArrowRight20Regular />
        <div>
          <span>02</span>
          <strong>Independent review</strong>
          <p>The Agents team approves or declines.</p>
        </div>
        <ArrowRight20Regular />
        <div>
          <span>03</span>
          <strong>Build within bounds</strong>
          <p>Reveal once. Use. Monitor. Revoke.</p>
        </div>
      </div>
    </>
  );
}

export function Budgets({ data, open }: PageProps) {
  const [scope, setScope] = useState("all");
  const budgets = data.budgets.filter((budget) => scope === "all" || budget.scope === scope);
  return (
    <>
      <PageHeading
        eyebrow="SPEND WITH INTENTION"
        title="Budgets & spend"
        description="Hard caps from the organization down to each individual API key."
      />
      <div className="budget-explainer">
        <div className="budget-hierarchy">
          {["Organization", "Operating unit", "Team", "Agent", "API key"].map((label, i) => (
            <div key={label}>
              {i > 0 && <ChevronRight16Regular />}
              <span>{label}</span>
            </div>
          ))}
        </div>
        <p>
          <LockClosed20Regular />
          Every applicable budget must have enough unreserved funds before a request can run.
        </p>
      </div>
      <section className="panel">
        <div className="panel-tabs">
          <TabList selectedValue={scope} onTabSelect={(_, details) => setScope(String(details.value))}>
            {["all", "organization", "department", "team", "asset", "key"].map((value) => (
              <Tab value={value} key={value}>
                {
                  {
                    all: "All budgets",
                    organization: "Organization",
                    department: "Operating units",
                    team: "Teams",
                    asset: "Agents",
                    key: "Keys",
                  }[value]
                }
              </Tab>
            ))}
          </TabList>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Budget owner</th>
                <th>Scope</th>
                <th>Spend & cap</th>
                <th>Available</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {budgets.map((budget) => (
                <tr key={budget.id}>
                  <td>
                    <strong>{budget.name}</strong>
                  </td>
                  <td>
                    <span className="scope-pill">
                      {budget.scope === "department" ? "Operating unit" : budget.scope}
                    </span>
                  </td>
                  <td>
                    <BudgetMeter budget={budget} />
                  </td>
                  <td className="tabular">
                    {money(
                      Math.max(0, budget.limit_micros - budget.spent_micros - budget.reserved_micros),
                      2,
                    )}
                  </td>
                  <td>
                    {budget.permissions.edit ? (
                      <Button onClick={() => open({ type: "budget", budget })}>Edit limit</Button>
                    ) : (
                      <span className="locked-label">
                        <LockClosed20Regular />
                        {budget.scope === "asset" ? "Approval required" : "Read only"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!budgets.length && (
          <Empty
            title="No budgets in this view"
            description="Select another scope to see the budgets available to you."
          />
        )}
      </section>
      <div className="scope-callout">
        <Info20Regular />
        <span>
          POC budgets are cumulative USD caps with no automatic reset. Child limits share their parent’s
          remaining budget; they do not reserve allocations.
        </span>
      </div>
    </>
  );
}

export function Organization({ data, open }: PageProps) {
  return (
    <>
      <PageHeading
        eyebrow="PEOPLE & RESPONSIBILITY"
        title="Organization"
        description="Clear ownership, from operating units to the teams building with AI."
        action={
          data.permissions.create_department && (
            <Button appearance="primary" icon={<Add20Regular />} onClick={() => open({ type: "department" })}>
              New operating unit
            </Button>
          )
        }
      />
      <div className="organization-list">
        {data.departments.map((dept) => (
          <section className="panel department-panel" key={dept.id}>
            <div className="department-heading">
              <span className="department-icon">
                <Organization24Regular />
              </span>
              <div>
                <h2>{dept.name}</h2>
                <p>{dept.description}</p>
              </div>
              {data.permissions.assign_cost_admin && (
                <Button onClick={() => open({ type: "assign-admin", department: dept })}>
                  Manage cost admins
                </Button>
              )}
            </div>
            <div className="team-grid">
              {data.teams
                .filter((t) => t.department_id === dept.id)
                .map((team) => (
                  <div className="team-card" key={team.id}>
                    <div className="team-title">
                      <PeopleTeam24Regular />
                      <h3>{team.name}</h3>
                    </div>
                    <p>
                      {data.users.filter((u) => u.team_ids.includes(team.id)).length} members in view
                      <span className="middle-dot">·</span>
                      {data.assets.filter((a) => a.team_id === team.id).length} visible assets
                    </p>
                    <div className="team-members">
                      {data.users
                        .filter((u) => u.team_ids.includes(team.id))
                        .map((user) => (
                          <span className="member-pill" key={user.id} title={roleName(user.roles[0])}>
                            {user.name.split(" ")[0]}
                            {team.cost_editor_ids.includes(user.id) && <Wallet24Regular />}
                          </span>
                        ))}
                    </div>
                    <div className="team-card-bottom">
                      <span>{team.cost_editor_ids.length} delegated cost editors</span>
                      {team.permissions.delegate_cost && (
                        <Button size="small" onClick={() => open({ type: "delegate", team })}>
                          Manage access
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
            </div>
            {!data.teams.some((t) => t.department_id === dept.id) && (
              <p className="padded muted">No teams are visible in this operating unit.</p>
            )}
            <div className="department-foot">
              <ShieldCheckmark24Regular />
              <span>
                Cost administrators:{" "}
                {data.users
                  .filter((u) => u.roles.includes("cost_center_admin") && u.department_ids.includes(dept.id))
                  .map((u) => u.name)
                  .join(", ") || "Managed at the operating-unit level"}
              </span>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}

export function Policies({ data, select }: PageProps) {
  const ownTeamAssets = data.assets.filter((a) => a.permissions.edit).length;
  return (
    <>
      <PageHeading
        eyebrow="TRUST, MADE EXPLICIT"
        title="Access policies"
        description="Your permissions come from Cerbos, evaluated against each resource."
      />
      <div className="policy-hero">
        <div>
          <span className="eyebrow">CURRENT PRINCIPAL</span>
          <h2>{data.user.name}</h2>
          <div className="role-badges">
            {data.user.roles.map((role) => (
              <Badge key={role} className="role-badge" appearance="tint" color="brand">
                {roleName(role)}
              </Badge>
            ))}
          </div>
          <p>{data.user.email}</p>
        </div>
        <div className="policy-engine">
          <ShieldCheckmark24Regular />
          <strong>Cerbos PDP</strong>
          <span>Live decisions · default policy version</span>
        </div>
      </div>
      <div className="policy-summary">
        <div>
          <strong>{data.assets.length}</strong>
          <span>Assets you can view</span>
        </div>
        <div>
          <strong>{ownTeamAssets}</strong>
          <span>Assets you can edit</span>
        </div>
        <div>
          <strong>{data.approvals.filter((a) => a.permissions.approve).length}</strong>
          <span>Requests you can decide</span>
        </div>
      </div>
      <section className="panel">
        <SectionTitle
          title="Inspect a live decision"
          description="Select an asset to see the exact allow and deny results for your current identity."
        />
        <div className="policy-assets">
          {data.assets.map((asset) => (
            <button type="button" key={asset.id} onClick={() => select(asset)}>
              <AssetIcon kind={asset.kind} />
              <span>
                <strong>{asset.name}</strong>
                <small>{asset.team_name}</small>
              </span>
              <div className="policy-chips">
                {Object.entries(asset.permissions)
                  .filter(([action, allowed]) => allowed && action !== "view")
                  .slice(0, 3)
                  .map(([action]) => (
                    <span key={action}>{action.replaceAll("_", " ")}</span>
                  ))}
              </div>
              <ChevronRight16Regular />
            </button>
          ))}
        </div>
        {!data.assets.length && (
          <Empty
            title="No asset permissions"
            description="This role manages financial limits without access to the asset catalog."
          />
        )}
      </section>
      <div className="policy-principles">
        <article>
          <ShieldCheckmark24Regular />
          <h3>Scoped authority</h3>
          <p>Team ownership and operating-unit assignments constrain every administrative action.</p>
        </article>
        <article>
          <PeopleTeam24Regular />
          <h3>Independent approval</h3>
          <p>
            Requesters cannot approve their own changes. Delegated cost editors can propose, never approve.
          </p>
        </article>
        <article>
          <LockClosed20Regular />
          <h3>Enforced on the server</h3>
          <p>Hidden buttons reflect backend decisions. Direct API calls pass the same Cerbos checks.</p>
        </article>
      </div>
    </>
  );
}

export function Audit({ data }: PageProps) {
  const [search, setSearch] = useState("");
  const filtered = data.events.filter((event) =>
    `${event.type} ${event.actor_name} ${event.resource_id}`.toLowerCase().includes(search.toLowerCase()),
  );
  function download() {
    const blob = new Blob([JSON.stringify(filtered, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ai-cerbos-audit.json";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      <PageHeading
        eyebrow="A RECORD YOU CAN FOLLOW"
        title="Audit log"
        description="Changes, decisions, and spending events, recorded with their actors."
        action={
          <Button icon={<ArrowDownload20Regular />} onClick={download}>
            Export visible events
          </Button>
        }
      />
      <section className="panel">
        <div className="filter-toolbar">
          <Input
            className="field-input"
            value={search}
            onChange={(_, details) => setSearch(details.value)}
            contentBefore={<Search20Regular />}
            placeholder="Search actors, events, or resources…"
            aria-label="Search audit log"
          />
          <span className="toolbar-spacer" />
          <span className="muted">{filtered.length} events · latest 100 visible</span>
        </div>
        <div className="table-scroll">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Actor</th>
                <th>Resource</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((event) => (
                <tr key={event.id}>
                  <td>
                    <span className="event-name">
                      <span className="mini-dot green" />
                      {event.type}
                    </span>
                  </td>
                  <td>{event.actor_name}</td>
                  <td>
                    <code>{String(event.detail.name || event.resource_id)}</code>
                  </td>
                  <td>
                    <time dateTime={event.created_at} title={new Date(event.created_at).toLocaleString()}>
                      {relativeTime(event.created_at)}
                    </time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!filtered.length && (
          <Empty title="No matching events" description="Change your search to explore the audit trail." />
        )}
      </section>
      <div className="scope-callout">
        <HistoryIcon />
        <span>
          Business changes and their events commit together. EventBus delivers from a persistent outbox;
          activity is filtered by your scope.
        </span>
      </div>
    </>
  );
}

function HistoryIcon() {
  return <ShieldCheckmark24Regular />;
}
