import {
  Avatar,
  Badge,
  Button,
  MessageBar,
  MessageBarBody,
  makeStyles,
  mergeClasses,
  Spinner,
  Switch,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowClockwise20Regular,
  ArrowRight16Regular,
  CheckmarkCircle20Filled,
  DismissCircle20Filled,
  Eye20Regular,
  Flowchart20Regular,
  Play20Regular,
  ShieldKeyhole24Regular,
  SubtractCircle20Regular,
  Wallet20Regular,
  Warning20Filled,
  Wrench20Regular,
} from "@fluentui/react-icons";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  sendGatewayRequest,
  setTeamBudget,
  useRefreshAuthorization,
  useTeamBudget,
  useTraffic,
} from "../hooks";
import type {
  Catalog,
  GatewayRequest,
  GatewayResult,
  TraceStep,
  Traffic,
  TrafficCell,
  TrafficOutcome,
} from "../types";
import { Choice, SectionHeader, useStoryStyles } from "./shared";

const useStyles = makeStyles({
  keys: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
    gap: tokens.spacingHorizontalM,
  },
  keyCard: {
    display: "flex",
    gap: tokens.spacingHorizontalS,
    alignItems: "center",
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusLarge,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  groupRow: {
    textAlign: "left",
    paddingTop: tokens.spacingVerticalM,
    paddingBottom: tokens.spacingVerticalXS,
    fontSize: tokens.fontSizeBase200,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: tokens.colorNeutralForeground3,
  },
  situation: {
    textAlign: "left",
    fontWeight: tokens.fontWeightMedium,
    padding: tokens.spacingHorizontalS,
    borderBottom: `1px solid ${tokens.colorNeutralStroke3}`,
    minWidth: "200px",
  },
  cellButton: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: "2px",
    width: "100%",
    minWidth: "140px",
    padding: tokens.spacingHorizontalXS,
    borderRadius: tokens.borderRadiusMedium,
    border: "1px solid transparent",
    backgroundColor: "transparent",
    font: "inherit",
    color: "inherit",
    textAlign: "left",
    cursor: "pointer",
    ":hover": { backgroundColor: tokens.colorNeutralBackground1Hover },
    ":focus-visible": { outline: `2px solid ${tokens.colorStrokeFocus2}` },
  },
  cellChanged: {
    border: `1px solid ${tokens.colorPaletteMarigoldBorder2}`,
    backgroundColor: tokens.colorPaletteMarigoldBackground1,
  },
  cellSelected: {
    border: `1px solid ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorBrandBackground2,
  },
  flow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: tokens.spacingHorizontalS,
  },
  flowStep: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorBrandBackground2,
  },
  custom: { borderTop: `1px solid ${tokens.colorNeutralStroke2}`, paddingTop: tokens.spacingVerticalM },
  customSummary: {
    cursor: "pointer",
    fontWeight: tokens.fontWeightSemibold,
    marginBottom: tokens.spacingVerticalM,
  },
  hooks: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
    gap: tokens.spacingHorizontalM,
  },
  hook: {
    display: "flex",
    gap: tokens.spacingHorizontalS,
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorNeutralForeground1,
  },
  hookIcon: { color: tokens.colorBrandForeground1, flexShrink: 0 },
  hookTitle: { fontWeight: tokens.fontWeightSemibold, display: "block" },
  composer: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, max-content))",
    gap: tokens.spacingHorizontalL,
    alignItems: "end",
  },
  pipeline: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "stretch",
    gap: tokens.spacingHorizontalXS,
    listStyleType: "none",
    margin: 0,
    padding: 0,
  },
  node: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    minWidth: "120px",
    maxWidth: "200px",
    flex: "1 1 120px",
    padding: tokens.spacingHorizontalS,
    borderRadius: tokens.borderRadiusLarge,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  nodeAllow: {
    border: `1px solid ${tokens.colorPaletteGreenBorder2}`,
    backgroundColor: tokens.colorPaletteGreenBackground1,
  },
  nodeDeny: {
    border: `1px solid ${tokens.colorPaletteRedBorder2}`,
    backgroundColor: tokens.colorPaletteRedBackground1,
  },
  nodeSkipped: { border: `1px dashed ${tokens.colorNeutralStroke1}`, color: tokens.colorNeutralForeground3 },
  nodeCerbos: { boxShadow: `inset 0 0 0 1px ${tokens.colorBrandStroke1}` },
  nodeHead: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXS,
    fontWeight: tokens.fontWeightSemibold,
  },
  nodeSub: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
    wordBreak: "break-word",
  },
  arrow: { alignSelf: "center", color: tokens.colorNeutralForeground3 },
  headline: {
    fontSize: tokens.fontSizeBase500,
    fontWeight: tokens.fontWeightSemibold,
    margin: 0,
    lineHeight: tokens.lineHeightBase500,
  },
  headlineRow: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: tokens.spacingHorizontalM },
  allow: { color: tokens.colorPaletteGreenForeground1 },
  deny: { color: tokens.colorPaletteRedForeground1 },
  twoUp: {
    display: "grid",
    gridTemplateColumns: "minmax(280px, 1fr) minmax(0, 2fr)",
    "@media (max-width: 1100px)": { gridTemplateColumns: "minmax(0, 1fr)" },
    gap: tokens.spacingHorizontalL,
    alignItems: "start",
  },
  keyColumn: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXS },
  modelRow: { display: "flex", alignItems: "flex-start", gap: tokens.spacingHorizontalS },
  hidden: { color: tokens.colorNeutralForeground4, textDecorationLine: "line-through" },
  table: { borderCollapse: "collapse", width: "100%" },
  th: {
    textAlign: "left",
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    padding: tokens.spacingHorizontalS,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  td: {
    padding: tokens.spacingHorizontalS,
    borderBottom: `1px solid ${tokens.colorNeutralStroke3}`,
    verticalAlign: "top",
  },
  cell: { display: "flex", flexDirection: "column", gap: "2px" },
});

const STEP_LABELS: Record<string, { title: string; sub?: string; cerbos?: boolean }> = {
  "Authenticate API key": { title: "API key" },
  "Cerbos in the gateway: may the owner use this agent?": {
    title: "Cerbos in the gateway",
    sub: "asset:use",
    cerbos: true,
  },
  "Budget inside LiteLLM: reserve at every level": {
    title: "Budget check",
    sub: "inside LiteLLM, every level",
  },
  "Cerbos inside LiteLLM: may this key invoke this model?": {
    title: "Cerbos inside LiteLLM",
    sub: "model:invoke",
    cerbos: true,
  },
  Provider: { title: "Model answered" },
  "Settle actual cost": { title: "Cost settled" },
  "Release reservation": { title: "Budget released" },
  "Gateway bypassed": { title: "Gateway bypassed" },
};

function StepIcon({ status }: { status: TraceStep["status"] }) {
  const styles = useStyles();
  if (status === "allow" || status === "ok") return <CheckmarkCircle20Filled className={styles.allow} />;
  if (status === "deny") return <DismissCircle20Filled className={styles.deny} />;
  if (status === "error") return <Warning20Filled className={styles.deny} />;
  return <SubtractCircle20Regular />;
}

function Pipeline({ steps }: { steps: TraceStep[] }) {
  const styles = useStyles();
  return (
    <ol className={styles.pipeline} aria-label="Request pipeline">
      {steps.map((step, index) => {
        const label = STEP_LABELS[step.name] || { title: step.name };
        return (
          <li key={step.name} style={{ display: "contents" }}>
            {index > 0 && <ArrowRight16Regular className={styles.arrow} aria-hidden />}
            <div
              className={mergeClasses(
                styles.node,
                (step.status === "allow" || step.status === "ok") && styles.nodeAllow,
                (step.status === "deny" || step.status === "error") && styles.nodeDeny,
                step.status === "skipped" && styles.nodeSkipped,
                label.cerbos && styles.nodeCerbos,
              )}
            >
              <span className={styles.nodeHead}>
                <StepIcon status={step.status} />
                {label.title}
              </span>
              {label.sub && <span className={styles.nodeSub}>{label.sub}</span>}
              {step.rule && <span className={styles.nodeSub}>{step.rule}</span>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Short labels for the two demo keys: whose key, and which team it belongs to. */
const KEY_LABELS: Record<string, string> = {
  alex: "Alex · Platform",
  sam: "Sam · Agents",
  riley: "Riley · People Ops",
};
const keyLabel = (owner: string) => KEY_LABELS[owner] ?? owner;

function headline(result: GatewayResult): string {
  if (result.outcome === "deny") {
    const where = result.steps.find((s) => s.status === "deny")?.name.includes("LiteLLM")
      ? "inside LiteLLM"
      : "before LiteLLM";
    return `Blocked by Cerbos ${where}`;
  }
  if (result.outcome === "error") return "The request failed";
  if (result.obligations.model)
    return `Asked for ${result.requested_model}, answered by ${result.answered_model}`;
  if (result.obligations.max_tokens)
    return `Answered by ${result.answered_model}, capped at ${result.obligations.max_tokens} tokens`;
  return `Answered by ${result.answered_model ?? result.requested_model}`;
}

function RequestPanel({ catalog, ready }: { catalog: Catalog; ready: boolean }) {
  const styles = useStyles();
  const story = useStoryStyles();
  const [request, setRequest] = useState<GatewayRequest>({
    owner: "alex",
    model: "governed-premium",
    max_tokens: 256,
    path: "gateway",
    data_classification: "internal",
  });
  const send = useMutation({ mutationFn: () => sendGatewayRequest(request) });
  const set = (patch: Partial<GatewayRequest>) => setRequest((current) => ({ ...current, ...patch }));
  const result = send.data;
  const deny = result?.steps.find((s) => s.status === "deny");
  return (
    <div className={story.card}>
      <h3 className={story.cardTitle}>Send a model request</h3>
      <p className={story.muted}>
        The same request can be allowed, refused, or allowed with conditions that LiteLLM applies. Try premium
        with each key, 1024 tokens, confidential data, and bypassing the gateway.
      </p>
      <div className={styles.composer}>
        <Choice
          label="API key"
          value={request.owner}
          options={catalog.demo_keys.map((k) => ({ value: k.owner, label: keyLabel(k.owner) }))}
          onChange={(owner) => set({ owner })}
        />
        <Choice
          label="Model"
          value={request.model}
          options={[
            { value: "governed-demo", label: "Standard" },
            { value: "governed-premium", label: "Premium" },
          ]}
          onChange={(model) => set({ model })}
        />
        <Choice
          label="Max tokens"
          value={String(request.max_tokens)}
          options={[
            { value: "256", label: "256" },
            { value: "1024", label: "1024" },
          ]}
          onChange={(value) => set({ max_tokens: Number(value) })}
        />
        <Choice
          label="Data"
          value={request.data_classification}
          options={[
            { value: "public", label: "Public" },
            { value: "internal", label: "Internal" },
            { value: "confidential", label: "Confidential" },
          ]}
          onChange={(data_classification) => set({ data_classification })}
        />
        <Choice
          label="Route"
          value={request.path}
          options={[
            { value: "gateway", label: "Governed gateway" },
            { value: "direct", label: "Bypass to LiteLLM" },
          ]}
          onChange={(path) => set({ path })}
        />
        <Button
          appearance="primary"
          size="large"
          icon={send.isPending ? <Spinner size="tiny" /> : <Play20Regular />}
          disabled={!ready || send.isPending}
          onClick={() => send.mutate()}
        >
          Send
        </Button>
      </div>
      {send.error && <p role="alert">{send.error.message}</p>}
      {result && (
        <div className={story.stack} aria-live="polite">
          <div className={styles.headlineRow}>
            <p
              className={mergeClasses(
                styles.headline,
                result.outcome === "allow" ? styles.allow : styles.deny,
              )}
            >
              {headline(result)}
            </p>
            {Object.entries(result.obligations).map(([name, value]) => (
              <Badge key={name} appearance="filled" color="brand">
                Cerbos obligation: {name} → {String(value)}
              </Badge>
            ))}
          </div>
          <Pipeline steps={result.steps} />
          {(result.litellm_reason || deny?.reason) && (
            <p style={{ margin: 0 }}>
              <strong>{deny?.name.startsWith("Budget") ? "Budget ledger:" : "Cerbos:"}</strong>{" "}
              {deny?.reason ?? result.litellm_reason}{" "}
              <span className={story.mono}>
                (
                {deny?.rule ??
                  result.litellm_rule ??
                  (deny?.name.startsWith("Budget") ? "budget ledger inside LiteLLM" : "default deny")}
                )
              </span>
            </p>
          )}
          {result.outcome === "allow" && result.litellm_rule && (
            <pre className={story.code}>
              {[
                "HTTP/1.1 200 OK   (headers added by LiteLLM's Cerbos guard)",
                "x-cerbos-decision: allow",
                `x-cerbos-rule: ${result.litellm_rule}`,
                `x-cerbos-obligations: ${JSON.stringify(result.obligations)}`,
                `x-cerbos-data-classification: ${request.data_classification}`,
              ].join("\n")}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

const HOOKS = [
  {
    icon: Flowchart20Regular,
    title: "Before every model call",
    text: "Allow, refuse, or allow with conditions such as a cheaper model or fewer tokens.",
  },
  {
    icon: Wrench20Regular,
    title: "Before every MCP tool call",
    text: "Per key and per tool, using the tool's declared risk.",
  },
  {
    icon: Eye20Regular,
    title: "When listing models",
    text: "Each key's model catalog shows only what Cerbos allows.",
  },
  {
    icon: ShieldKeyhole24Regular,
    title: "On every response",
    text: "x-cerbos-* headers name the rule that applied.",
  },
  {
    icon: Wallet20Regular,
    title: "Budgets, on every model call",
    text: "Reserve the maximum cost at every level before the provider, settle the real cost after.",
  },
];

const OUTCOMES: Record<
  TrafficOutcome,
  { label: string; color: "success" | "warning" | "danger" | "informative" | "severe" }
> = {
  answered: { label: "Answered", color: "success" },
  downgraded: { label: "Downgraded", color: "warning" },
  capped: { label: "Capped", color: "warning" },
  refused: { label: "Refused", color: "danger" },
  over_budget: { label: "Over budget", color: "severe" },
  listed: { label: "Premium listed", color: "success" },
  hidden: { label: "Premium hidden", color: "informative" },
  called: { label: "Called", color: "success" },
  error: { label: "Error", color: "severe" },
};

function cellNote(cell: TrafficCell): string {
  if (cell.outcome === "downgraded") return `answered by ${cell.answered_model ?? "the standard model"}`;
  if (cell.outcome === "capped") return `at ${cell.obligations?.max_tokens} tokens`;
  if (cell.outcome === "listed" || cell.outcome === "hidden") return (cell.visible ?? []).join(", ");
  if (cell.outcome === "answered" && cell.streamed) return "streamed, billed when it ended";
  if (cell.outcome === "over_budget")
    return `${cell.reason.split(" ")[0].toLowerCase()} cap reached, inside LiteLLM`;
  return cell.rule ?? (cell.outcome === "refused" ? "default deny" : "");
}

/** How an obligation travels: Cerbos decides, LiteLLM's guard applies it, billing follows. */
function ObligationFlow({ cell }: { cell: TrafficCell }) {
  const styles = useStyles();
  const story = useStoryStyles();
  const obligation = JSON.stringify(cell.obligations ?? {});
  const steps = [
    {
      title: "1. Cerbos decides",
      text: `Rule ${cell.rule} returns ALLOW plus an obligation: ${obligation}.`,
    },
    {
      title: "2. LiteLLM's guard applies it",
      text: "The pre-call hook rewrites the request before routing; Cerbos itself never touches traffic.",
    },
    {
      title: "3. LiteLLM routes the changed request",
      text:
        cell.outcome === "downgraded"
          ? `The call goes to ${cell.answered_model}, not the premium deployment.`
          : `The model may produce at most ${cell.obligations?.max_tokens} tokens.`,
    },
    {
      title: "4. Everyone can see it",
      text: "x-cerbos-obligations on the response; the gateway bills the model that actually answered.",
    },
  ];
  return (
    <div className={styles.flow}>
      {steps.map((step) => (
        <div key={step.title} className={styles.flowStep}>
          <strong>{step.title}</strong>
          <span className={story.muted}>{step.text}</span>
        </div>
      ))}
    </div>
  );
}

function CellDetail({ situation, owner, cell }: { situation: string; owner: string; cell: TrafficCell }) {
  const story = useStoryStyles();
  return (
    <div className={story.card} aria-live="polite">
      <div className={story.row}>
        <Badge appearance="filled" color={OUTCOMES[cell.outcome].color}>
          {OUTCOMES[cell.outcome].label}
        </Badge>
        <strong>
          {situation} · {keyLabel(owner)} key
        </strong>
      </div>
      <p style={{ margin: 0 }}>
        {cell.reason}{" "}
        <span className={story.mono}>
          ({cell.rule ?? (cell.outcome === "over_budget" ? "budget ledger inside LiteLLM" : "default deny")})
        </span>
      </p>
      {(cell.outcome === "downgraded" || cell.outcome === "capped") && <ObligationFlow cell={cell} />}
      {cell.steps && cell.steps.length > 0 && <Pipeline steps={cell.steps} />}
      {cell.visible && (
        <p className={story.muted}>
          GET /v1/models returned: <span className={story.mono}>{cell.visible.join(", ")}</span>
        </p>
      )}
      {cell.result && <pre className={story.code}>{cell.result}</pre>}
    </div>
  );
}

function TrafficBoard({ catalog }: { catalog: Catalog }) {
  const styles = useStyles();
  const story = useStoryStyles();
  const traffic = useTraffic();
  const previous = useRef<Traffic | null>(null);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>("premium:alex");

  useEffect(() => {
    const data = traffic.data;
    if (!data || previous.current === data) return;
    const before = previous.current;
    setChanged(
      new Set(
        before
          ? Object.keys(data.cells).filter((key) => before.cells[key]?.outcome !== data.cells[key].outcome)
          : [],
      ),
    );
    previous.current = data;
  }, [traffic.data]);

  const data = traffic.data;
  const groups = data ? [...new Set(data.situations.map((s) => s.group))] : [];
  const obligations = (data?.counts.downgraded ?? 0) + (data?.counts.capped ?? 0);
  const selectedCell = selected && data?.cells[selected];
  const [selectedSituation, selectedOwner] = selected?.split(":") ?? [];

  return (
    <div className={story.stack}>
      <div className={styles.keys}>
        {catalog.demo_keys.map((key) => (
          <div key={key.owner} className={styles.keyCard}>
            <Avatar name={key.owner} size={32} color="brand" />
            <div>
              <strong>{keyLabel(key.owner)} key</strong>
              <div className={story.muted}>
                role api_key · team {key.team} · unit {String(key.principal.attr.department_id)} · agent{" "}
                {String(key.principal.attr.asset_id)}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className={story.card}>
        <div className={story.row} style={{ justifyContent: "space-between" }}>
          <div>
            <h3 className={story.cardTitle}>AI traffic, decided by Cerbos inside LiteLLM</h3>
            <p className={story.muted}>
              {data
                ? `${data.calls} real calls through LiteLLM in ${data.seconds} s: ${(data.counts.answered ?? 0) + (data.counts.called ?? 0)} went through unchanged, ${obligations} were changed by Cerbos obligations, ${data.counts.refused ?? 0} were refused${data.counts.over_budget ? `, ${data.counts.over_budget} were over budget` : ""}.`
                : "Every situation below is sent for every key, through the governed gateway and LiteLLM."}
            </p>
          </div>
          <Button
            icon={traffic.isFetching ? <Spinner size="tiny" /> : <ArrowClockwise20Regular />}
            disabled={traffic.isFetching}
            onClick={() => traffic.refetch()}
          >
            {traffic.isFetching ? "Sending real calls…" : "Run again"}
          </Button>
        </div>
        {traffic.error && <p role="alert">{traffic.error.message}</p>}
        {changed.size > 0 && (
          <MessageBar intent="warning">
            <MessageBarBody>
              {changed.size} {changed.size === 1 ? "outcome" : "outcomes"} changed since the last run, because
              a policy or budget changed. They are highlighted below.
            </MessageBarBody>
          </MessageBar>
        )}
        {data && (
          <div style={{ overflowX: "auto" }}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.th}>Situation</th>
                  {data.keys.map((key) => (
                    <th key={key.owner} className={styles.th}>
                      {keyLabel(key.owner)} key
                    </th>
                  ))}
                </tr>
              </thead>
              {groups.map((group) => (
                <tbody key={group}>
                  <tr>
                    <th colSpan={data.keys.length + 1} className={styles.groupRow}>
                      {group}
                    </th>
                  </tr>
                  {data.situations
                    .filter((situation) => situation.group === group)
                    .map((situation) => (
                      <tr key={situation.id}>
                        <th scope="row" className={styles.situation}>
                          {situation.title}
                        </th>
                        {data.keys.map((key) => {
                          const id = `${situation.id}:${key.owner}`;
                          const cell = data.cells[id];
                          return (
                            <td key={key.owner} className={styles.td}>
                              <button
                                type="button"
                                className={mergeClasses(
                                  styles.cellButton,
                                  changed.has(id) && styles.cellChanged,
                                  selected === id && styles.cellSelected,
                                )}
                                aria-pressed={selected === id}
                                onClick={() => setSelected(id)}
                              >
                                <Badge appearance="tint" color={OUTCOMES[cell.outcome].color}>
                                  {OUTCOMES[cell.outcome].label}
                                </Badge>
                                <span className={styles.nodeSub}>{cellNote(cell)}</span>
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                </tbody>
              ))}
            </table>
          </div>
        )}
        {!data && traffic.isFetching && <Spinner label="Issuing demo keys and sending real calls" />}
      </div>
      {selectedCell && (
        <CellDetail
          situation={data?.situations.find((s) => s.id === selectedSituation)?.title ?? ""}
          owner={selectedOwner}
          cell={selectedCell}
        />
      )}
    </div>
  );
}

/** Budgets live inside LiteLLM, so skipping the gateway cannot skip a cap. */
function BudgetCard() {
  const story = useStoryStyles();
  const state = useTeamBudget();
  const refresh = useRefreshAuthorization();
  const change = useMutation({
    mutationFn: setTeamBudget,
    onSuccess: () => refresh(),
  });
  const on = change.isPending ? change.variables : Boolean(state.data?.on);
  return (
    <div className={story.card}>
      <h3 className={story.cardTitle}>Budgets are enforced inside LiteLLM, not only at the gateway</h3>
      <p className={story.muted}>
        The API key a team receives is a LiteLLM key. If budgets were checked only in the gateway, anyone
        holding a key who can reach LiteLLM could call it directly and spend past every cap. The same gap
        exists in any design where the gateway alone counts money. Here LiteLLM's Cerbos hook reserves each
        call's maximum cost on the key, agent, team, department and organization budgets before the provider
        is called, and settles the real cost afterwards. The row <em>bypassing the gateway</em> below is
        billed the same way.
      </p>
      <Switch
        checked={on}
        disabled={change.isPending || !state.data}
        onChange={(_, details) => change.mutate(details.checked)}
        label={
          on
            ? "People Operations has spent its team budget: Riley's model calls are refused, even straight to LiteLLM"
            : "Let People Operations run out of team budget"
        }
      />
      {change.error && <p role="alert">{change.error.message}</p>}
    </div>
  );
}

export function GatewaySection({ catalog }: { catalog: Catalog }) {
  const styles = useStyles();
  const story = useStoryStyles();
  return (
    <section className={story.section} aria-labelledby="gateway-title">
      <SectionHeader
        number={3}
        id="gateway-title"
        title="Cerbos inside LiteLLM"
        description="LiteLLM, the AI gateway, asks Cerbos at four points and checks budgets on every model call. Inside LiteLLM the principal is the API key, with the team, unit and agent recorded when it was issued. Three keys from three teams send the same traffic; every cell below is a real call. Change a policy in section 2 and the board runs again."
      />
      <div className={styles.hooks}>
        {HOOKS.map((hook) => (
          <div key={hook.title} className={styles.hook}>
            <hook.icon className={styles.hookIcon} />
            <span>
              <span className={styles.hookTitle}>{hook.title}</span>
              <span className={story.muted}>{hook.text}</span>
            </span>
          </div>
        ))}
      </div>
      <BudgetCard />
      <TrafficBoard catalog={catalog} />
      <details className={styles.custom}>
        <summary className={styles.customSummary}>Build your own request</summary>
        <RequestPanel catalog={catalog} ready />
      </details>
    </section>
  );
}
