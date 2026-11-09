import { Avatar, Button, Input, Select, Skeleton, SkeletonItem } from "@fluentui/react-components";
import {
  Apps24Regular,
  ArrowSync20Regular,
  ArrowUpRight16Regular,
  Beaker24Regular,
  ChevronRight16Regular,
  ClipboardTask24Regular,
  Dismiss20Regular,
  History24Regular,
  Home24Regular,
  Key24Regular,
  Organization24Regular,
  PanelLeft24Regular,
  Search20Regular,
  ShieldCheckmark24Regular,
  Wallet24Regular,
} from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, loadWorkspace, roleName } from "./api";
import { ActionDialog, AssetDrawer, SecretDialog } from "./dialogs";
import { Approvals, Audit, Budgets, Keys, Organization, Overview, Policies, Registry } from "./pages";
import { AdvancedPage } from "./playground/AdvancedPage";
import { StoryPage } from "./playground/story/StoryPage";
import type { Asset, DialogState, User, Workspace } from "./types";

export type PageProps = {
  data: Workspace;
  open: (dialog: DialogState) => void;
  select: (asset: Asset) => void;
  notify: (message: string) => void;
  reveal: (secret: string) => void;
};

type NavItem = {
  path: string;
  label: string;
  icon: typeof Home24Regular;
  group: string;
  permission?: string;
  /** Only shown in demo mode. */
  demoOnly?: boolean;
};

const navigation: NavItem[] = [
  { path: "/", label: "Overview", icon: Home24Regular, group: "Workspace" },
  { path: "/assets", label: "Asset registry", icon: Apps24Regular, group: "Workspace" },
  { path: "/approvals", label: "Approvals", icon: ClipboardTask24Regular, group: "Workspace" },
  {
    path: "/playground",
    label: "Cerbos playground",
    icon: Beaker24Regular,
    group: "Governance",
    demoOnly: true,
  },
  { path: "/keys", label: "API keys", icon: Key24Regular, group: "Governance", permission: "view_keys" },
  {
    path: "/budgets",
    label: "Budgets & spend",
    icon: Wallet24Regular,
    group: "Governance",
    permission: "view_budgets",
  },
  {
    path: "/organization",
    label: "Organization",
    icon: Organization24Regular,
    group: "Governance",
    permission: "view_organization",
  },
  {
    path: "/policies",
    label: "Access policies",
    icon: ShieldCheckmark24Regular,
    group: "Governance",
    permission: "view_policies",
  },
  {
    path: "/audit",
    label: "Audit log",
    icon: History24Regular,
    group: "Governance",
    permission: "view_audit",
  },
];

export default function App() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notification, setNotification] = useState("");
  const [secret, setSecret] = useState("");
  const [search, setSearch] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const workspace = useQuery({ queryKey: ["workspace"], queryFn: loadWorkspace });
  const data = workspace.data;
  const users = useQuery({
    queryKey: ["demo-users"],
    queryFn: () => api<User[]>("/api/demo-users"),
    enabled: data?.demo_mode === true,
  });
  const services = useQuery({
    queryKey: ["services"],
    queryFn: () => api<Record<string, string>>("/api/services"),
    enabled: !!data,
    refetchInterval: 30000,
  });
  const identity = useMutation({
    mutationFn: async (userId: string) => {
      setDialog(null);
      setSelectedId(null);
      setSecret("");
      setNotification("");
      // A workspace refetch started under the previous cookie must not land after the
      // switch and overwrite the new persona's state.
      await queryClient.cancelQueries({ queryKey: ["workspace"] });
      await api("/api/session", "POST", { user_id: userId });
      const next = await api<Workspace>("/api/state");
      await queryClient.cancelQueries({ queryKey: ["workspace"] });
      queryClient.removeQueries({ queryKey: ["policy"] });
      queryClient.setQueryData(["workspace"], next);
      navigate("/");
    },
  });

  if (!data || identity.isPending) {
    if (workspace.isError || identity.isError)
      return (
        <main className="boot-state">
          <span className="brand-symbol">
            <ShieldCheckmark24Regular />
          </span>
          <h1>Let’s get your workspace connected.</h1>
          <p>{workspace.error?.message || identity.error?.message}</p>
          <Button appearance="primary" onClick={() => workspace.refetch()}>
            Try again
          </Button>
          <p className="muted">Start the local services with Docker Compose to open ai-cerbos.</p>
        </main>
      );
    return (
      <main className="loading-shell">
        <div className="loading-brand">ai-cerbos</div>
        <Skeleton>
          <SkeletonItem size={32} />
          <div className="loading-metrics">
            {[1, 2, 3, 4].map((id) => (
              <SkeletonItem key={id} size={128} />
            ))}
          </div>
          <SkeletonItem size={128} />
          <SkeletonItem size={128} />
        </Skeleton>
        <p>Connecting your governed workspace…</p>
      </main>
    );
  }

  const props: PageProps = {
    data,
    open: setDialog,
    select: (asset) => setSelectedId(asset.id),
    notify: setNotification,
    reveal: setSecret,
  };
  const selected = data.assets.find((asset) => asset.id === selectedId) || null;
  const current =
    navigation.find((item) => item.path === location.pathname)?.label ||
    navigation.find((item) => item.path !== "/" && location.pathname.startsWith(`${item.path}/`))?.label ||
    "Workspace";
  const pending = data.approvals.filter((a) => a.status === "pending").length;
  const accessibleNavigation = navigation.filter(
    (item) => (!item.permission || data.permissions[item.permission]) && (!item.demoOnly || data.demo_mode),
  );

  return (
    <div className="app-shell">
      {mobileNav && (
        <button
          type="button"
          aria-label="Close navigation"
          className="nav-overlay"
          onClick={() => setMobileNav(false)}
        />
      )}
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <NavLink to="/" className="brand">
          <span className="brand-symbol">
            <ShieldCheckmark24Regular />
          </span>
          <span>
            ai-cerbos<span className="brand-dot">.</span>
          </span>
          <span className="poc-label">POC</span>
        </NavLink>
        <div className="workspace-switch">
          <span className="workspace-avatar">A</span>
          <div>
            <strong>Acme workspace</strong>
            <small>AI governance platform</small>
          </div>
          <span className="workspace-indicator" />
        </div>
        <nav aria-label="Main navigation">
          {["Workspace", "Governance"].map((group) => (
            <div className="nav-group" key={group}>
              <p>{group}</p>
              {accessibleNavigation
                .filter((item) => item.group === group)
                .map((item) => (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.path === "/"}
                    onClick={() => setMobileNav(false)}
                    className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                    {item.path === "/approvals" && pending > 0 && (
                      <span className="nav-count">{pending}</span>
                    )}
                  </NavLink>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-panel">
            <div>
              <span className={`connection-dot ${services.data?.cerbos !== "connected" ? "offline" : ""}`} />
              <span>Cerbos policies</span>
              <small>{services.data?.cerbos === "connected" ? "Live" : "Checking"}</small>
            </div>
            <div>
              <span className={`connection-dot ${services.data?.litellm !== "connected" ? "offline" : ""}`} />
              <span>LiteLLM gateway</span>
              <small>{services.data?.litellm === "connected" ? "Live" : "Checking"}</small>
            </div>
          </div>
          <div className="sidebar-caption">
            <span className="tiny-square" />
            {data.demo_mode ? "Sample workspace · local POC" : "Governed workspace"}
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <Button
              className="mobile-menu"
              appearance="subtle"
              icon={<PanelLeft24Regular />}
              aria-label="Open navigation"
              onClick={() => setMobileNav(true)}
            />
            <span>Workspace</span>
            <ChevronRight16Regular />
            <strong>{current}</strong>
          </div>
          <div className="topbar-actions">
            <form
              className="global-search"
              onSubmit={(event) => {
                event.preventDefault();
                navigate(`/assets?q=${encodeURIComponent(search)}`);
              }}
            >
              <Input
                className="field-input"
                aria-label="Search assets"
                placeholder="Search your workspace"
                contentBefore={<Search20Regular />}
                value={search}
                onChange={(_, details) => setSearch(details.value)}
              />
              <kbd>↵</kbd>
            </form>
            <span className="topbar-divider" />
            <Avatar name={data.user.name} size={32} color="brand" />
            <div className="identity-control">
              <strong>{data.user.name}</strong>
              {data.demo_mode ? (
                <Select
                  className="persona-select"
                  aria-label="Switch demo persona"
                  value={data.user.id}
                  onChange={(event) => identity.mutate(event.target.value)}
                >
                  {(users.data || [data.user]).map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.name} · {roleName(user.roles[0])}
                      {user.roles.includes("api_key_approver") ? " / key approver" : ""}
                    </option>
                  ))}
                </Select>
              ) : (
                <small>{roleName(data.user.roles[0])}</small>
              )}
            </div>
          </div>
        </header>
        {(notification || identity.error) && (
          <div className="notice" role="status">
            <ShieldCheckmark24Regular />
            <span>{notification || identity.error?.message}</span>
            <Button
              appearance="subtle"
              icon={<Dismiss20Regular />}
              aria-label="Dismiss notification"
              onClick={() => {
                setNotification("");
                identity.reset();
              }}
            />
          </div>
        )}
        {workspace.isError && (
          <div className="error-banner" role="alert">
            {workspace.error.message}
            <Button onClick={() => workspace.refetch()} icon={<ArrowSync20Regular />}>
              Retry
            </Button>
          </div>
        )}
        <main className="page">
          <Routes>
            <Route path="/" element={<Overview {...props} />} />
            <Route path="/assets" element={<Registry {...props} />} />
            <Route path="/approvals" element={<Approvals {...props} />} />
            <Route
              path="/playground"
              element={data.demo_mode ? <StoryPage {...props} /> : <Navigate to="/" replace />}
            />
            <Route
              path="/playground/advanced"
              element={data.demo_mode ? <AdvancedPage {...props} /> : <Navigate to="/" replace />}
            />
            <Route
              path="/keys"
              element={data.permissions.view_keys ? <Keys {...props} /> : <Navigate to="/" replace />}
            />
            <Route
              path="/budgets"
              element={data.permissions.view_budgets ? <Budgets {...props} /> : <Navigate to="/" replace />}
            />
            <Route
              path="/organization"
              element={
                data.permissions.view_organization ? <Organization {...props} /> : <Navigate to="/" replace />
              }
            />
            <Route
              path="/policies"
              element={data.permissions.view_policies ? <Policies {...props} /> : <Navigate to="/" replace />}
            />
            <Route
              path="/audit"
              element={data.permissions.view_audit ? <Audit {...props} /> : <Navigate to="/" replace />}
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <footer className="page-footer">
            <span>
              ai-cerbos <span className="middle-dot">·</span> A little more control. A lot more possibility.
            </span>
            <a href="/docs" target="_blank" rel="noreferrer">
              API reference <ArrowUpRight16Regular />
            </a>
          </footer>
        </main>
      </div>
      {dialog && (
        <ActionDialog
          key={`${dialog.type}-${"asset" in dialog ? dialog.asset?.id : ""}`}
          dialog={dialog}
          data={data}
          onClose={() => setDialog(null)}
          notify={setNotification}
        />
      )}
      <AssetDrawer
        asset={selected}
        onClose={() => setSelectedId(null)}
        open={setDialog}
        userId={data.user.id}
      />
      <SecretDialog secret={secret} onClose={() => setSecret("")} />
    </div>
  );
}
