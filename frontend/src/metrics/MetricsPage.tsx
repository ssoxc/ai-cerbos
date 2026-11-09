import { Button, Spinner } from "@fluentui/react-components";
import {
  ArrowSwap24Regular,
  Beaker24Regular,
  Checkmark12Filled,
  Dismiss12Filled,
  Money24Regular,
  Play20Regular,
  Prohibited24Regular,
  ShieldCheckmark24Regular,
} from "@fluentui/react-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { PageProps } from "../App";
import { api, money } from "../api";
import { Empty } from "../components";
import "./metrics.css";
import type { Metrics, MetricsWindow, Outcome } from "./types";

const WINDOWS: { id: MetricsWindow; label: string }[] = [
  { id: "1h", label: "Last hour" },
  { id: "24h", label: "24 hours" },
  { id: "7d", label: "7 days" },
];
const OUTCOMES: { id: Outcome; label: string; hint: string }[] = [
  { id: "answered", label: "Answered", hint: "as requested" },
  { id: "downgraded", label: "Downgraded", hint: "obligation: cheaper model" },
  { id: "capped", label: "Capped", hint: "obligation: fewer tokens" },
  { id: "refused", label: "Refused", hint: "denied before any provider" },
];
const SOURCES: Record<string, { label: string; counted: string }> = {
  api: { label: "Actions in the dashboard and API", counted: "Enforcement" },
  gateway: { label: "AI spine gateway", counted: "Enforcement" },
  litellm: { label: "Inside LiteLLM", counted: "Enforcement" },
  dashboard: { label: "Dashboard lookups: which controls to show", counted: "Lookup, excluded" },
  playground: { label: "Playground what-ifs", counted: "Simulation, excluded" },
};

const count = (n: number) => new Intl.NumberFormat("en-US").format(n);
const percent = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : "0%");
/** Demo calls cost fractions of a cent, so small amounts keep their digits. */
const cost = (micros: number) =>
  micros && micros < 1_000_000 ? `$${(micros / 1_000_000).toFixed(4)}` : money(micros, 2);

export function MetricsPage({ data }: PageProps) {
  const [range, setRange] = useState<MetricsWindow>("24h");
  const queryClient = useQueryClient();
  const metrics = useQuery({
    queryKey: ["metrics", range],
    queryFn: () => api<Metrics>(`/api/metrics?window=${range}`),
    refetchInterval: 15_000,
  });
  const traffic = useMutation({
    mutationFn: () => api("/api/playground/traffic", "POST"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["metrics"] }),
  });

  return (
    <div className="metrics-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">MEASURED, NOT ASSUMED</div>
          <h1>Governance metrics</h1>
          <p>
            Two sources, kept apart. Cerbos's own decision log says who was allowed or refused, by which rule.
            The AI spine's budget ledger, kept inside LiteLLM, says what each call cost.
          </p>
        </div>
        <div className="mx-heading-actions">
          <fieldset className="mx-window">
            <legend className="sr-only">Time window</legend>
            {WINDOWS.map((w) => (
              <button
                key={w.id}
                type="button"
                aria-pressed={range === w.id}
                className={range === w.id ? "active" : ""}
                onClick={() => setRange(w.id)}
              >
                {w.label}
              </button>
            ))}
          </fieldset>
          {data.demo_mode && (
            <Button
              appearance="primary"
              icon={traffic.isPending ? <Spinner size="tiny" /> : <Play20Regular />}
              disabled={traffic.isPending}
              onClick={() => traffic.mutate()}
            >
              {traffic.isPending ? "Sending sample calls…" : "Run sample traffic"}
            </Button>
          )}
        </div>
      </div>
      {traffic.isError && <div className="error-banner">{(traffic.error as Error).message}</div>}
      {metrics.isError && <div className="error-banner">{(metrics.error as Error).message}</div>}
      {metrics.data ? (
        <Report m={metrics.data} />
      ) : (
        !metrics.isError && <Spinner label="Reading Cerbos's decision log…" />
      )}
    </div>
  );
}

function Report({ m }: { m: Metrics }) {
  const c = m.cerbos;
  const g = m.ledger;
  const llm = c.litellm;
  const changed = llm.outcomes.downgraded + llm.outcomes.capped;
  const allowedModelCalls = llm.model_calls - llm.outcomes.refused;
  return (
    <>
      <div className="mx-sources">
        <SourceCard
          tone="cerbos"
          title="Cerbos decision log"
          body="Written by Cerbos for every check it answers: principal, resource, action, effect, the rule that decided and its obligations. This page only reads it."
        />
        <SourceCard
          tone="ledger"
          title="AI spine budget ledger"
          body="Written from inside LiteLLM for every model call, through the gateway or not: reserved before the provider, settled after, with tokens, cost and the model that answered. Cerbos does not know prices."
        />
      </div>

      <SectionHeader
        tone="cerbos"
        source="Cerbos decision log"
        title="What Cerbos decided"
        detail="Attempts only: actions people took, AI requests at the gateway, and calls inside LiteLLM. Lookups and simulations are counted apart."
      />
      {!c.available ? (
        <div className="notice">
          Cerbos's decision log is not readable at <code>{c.log}</code>. Check the audit settings in
          cerbos/config.yaml.
        </div>
      ) : c.summary.decisions === 0 ? (
        <section className="panel">
          <Empty title="No decisions in this window" description="Run sample traffic, or widen the window." />
        </section>
      ) : (
        <>
          <div className="metrics-grid">
            <Tile
              icon={<ShieldCheckmark24Regular />}
              label="Decisions enforced"
              value={count(c.summary.decisions)}
            >
              {count(c.summary.allowed)} allowed
            </Tile>
            <Tile
              icon={<Prohibited24Regular />}
              label="Denied"
              value={percent(c.summary.denied, c.summary.decisions)}
            >
              {count(c.summary.denied)} attempts refused
            </Tile>
            <Tile icon={<ArrowSwap24Regular />} label="Changed by obligations" value={count(changed)}>
              of {count(llm.model_calls)} LiteLLM model calls
            </Tile>
            <Tile
              icon={<Beaker24Regular />}
              label="Not counted above"
              value={count(c.summary.lookups + c.summary.simulated)}
            >
              {count(c.summary.lookups)} lookups · {count(c.summary.simulated)} what-ifs
            </Tile>
          </div>

          <section className="panel mx-panel">
            <PanelTitle title="Decisions over time" detail="Every check Cerbos answered for real callers." />
            <Timeline buckets={c.timeline} range={m.window} />
          </section>

          <section className="panel mx-panel">
            <PanelTitle
              title="Inside LiteLLM: what happened to model calls"
              detail="Obligations are part of the decision: Cerbos says allow, and how."
            />
            <OutcomeTable rows={llm.by_team.map((r) => ({ label: r.team, ...r }))} heading="Team" />
            <OutcomeTable
              rows={llm.by_classification.map((r) => ({ label: r.classification, ...r }))}
              heading="Data classification"
            />
          </section>

          <div className="mx-two">
            <section className="panel mx-panel">
              <PanelTitle
                title="MCP tools and the model catalog"
                detail="Tool calls and model listings LiteLLM asked about."
              />
              <table className="mx-table">
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th>Risk</th>
                    <th className="num">Allowed</th>
                    <th className="num">Denied</th>
                  </tr>
                </thead>
                <tbody>
                  {llm.tools.map((t) => (
                    <tr key={t.tool}>
                      <td>{t.tool}</td>
                      <td className="muted">{t.risk}</td>
                      <td className="num">{count(t.allowed)}</td>
                      <td className="num">{count(t.denied)}</td>
                    </tr>
                  ))}
                  {llm.tools.length === 0 && (
                    <tr>
                      <td colSpan={4} className="muted">
                        No tool calls in this window.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              <p className="mx-footnote">
                Premium model listed {count(llm.catalog.listed)} times and hidden {count(llm.catalog.hidden)}{" "}
                times when keys asked LiteLLM for its catalog. LiteLLM checks each tool call once per payload
                it builds, so one call can appear as two decisions.
              </p>
            </section>
            <section className="panel mx-panel">
              <PanelTitle
                title="Who asked Cerbos"
                detail="Each caller tags its checks, and Cerbos records the tag."
              />
              <table className="mx-table">
                <thead>
                  <tr>
                    <th>Caller</th>
                    <th className="num">Decisions</th>
                    <th>Counted as</th>
                  </tr>
                </thead>
                <tbody>
                  {c.sources.map((s) => (
                    <tr key={s.source}>
                      <td>{SOURCES[s.source]?.label ?? s.source}</td>
                      <td className="num">{count(s.decisions)}</td>
                      <td className="muted">{SOURCES[s.source]?.counted ?? "Untagged, excluded"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>

          <section className="panel mx-panel">
            <PanelTitle
              title="Rules that decided"
              detail="Named rules from the live policies. For a reviewer, this is the policy in use, with how often it applied."
            />
            <RuleTable rules={c.top_rules} />
          </section>

          <section className="panel mx-panel">
            <PanelTitle
              title="Most refused"
              detail="Repeated refusals point to a misconfigured key or someone probing their limits."
            />
            <table className="mx-table">
              <thead>
                <tr>
                  <th>Principal</th>
                  <th className="num">Refused</th>
                  <th>Most common refusal</th>
                </tr>
              </thead>
              <tbody>
                {c.principals.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.name}
                      <div className="cell-subtitle">{p.type}</div>
                    </td>
                    <td className="num">
                      {count(p.denied)}
                      <span className="muted"> of {count(p.total)}</span>
                    </td>
                    <td className="mx-rule">
                      {p.top_rule}
                      <div className="cell-subtitle">{p.top_check}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}

      <SectionHeader
        tone="ledger"
        source="AI spine budget ledger"
        title="What it cost"
        detail="Every model call LiteLLM answered, including calls that skipped the gateway. The savings price each downgraded call at the model it asked for."
      />
      <div className="metrics-grid">
        <Tile icon={<ShieldCheckmark24Regular />} label="Requests billed" value={count(g.summary.requests)}>
          {count(g.summary.direct_requests)} skipped the gateway, still billed
        </Tile>
        <Tile icon={<Money24Regular />} label="Spend" value={cost(g.summary.spend_micros)}>
          at the answering model's price
        </Tile>
        <Tile icon={<ArrowSwap24Regular />} label="Saved by downgrades" value={cost(g.summary.saved_micros)}>
          {count(g.summary.downgraded)} downgraded · {count(g.summary.capped)} capped
        </Tile>
        <Tile
          icon={<Prohibited24Regular />}
          label="Refused by budget"
          value={count(g.summary.refused_by_budget)}
        >
          {g.summary.uncertain
            ? `${count(g.summary.uncertain)} uncertain, ${cost(g.summary.uncertain_micros)} held`
            : `${count(g.summary.refused_direct)} of them sent straight to LiteLLM`}
        </Tile>
      </div>
      <div className="mx-two">
        <section className="panel mx-panel">
          <PanelTitle title="Spend by team" />
          <SpendBars rows={g.by_team.map((r) => ({ label: r.team, ...r }))} />
        </section>
        <section className="panel mx-panel">
          <PanelTitle title="Spend by answering model" />
          <SpendBars rows={g.by_model.map((r) => ({ label: r.model, ...r }))} />
        </section>
      </div>
      <section className="panel mx-panel">
        <PanelTitle
          title="Budgets closest to their cap"
          detail="Spent plus reserved, against the approved cap."
        />
        <div className="mx-budgets">
          {g.budgets.map((b) => (
            <div key={b.id} className="mx-budget">
              <div className="mx-budget-head">
                <span>{b.name}</span>
                <span className="tabular">{Math.round(b.used * 100)}%</span>
              </div>
              <div className="meter-track">
                <span
                  className={b.used > 0.8 ? "high" : ""}
                  style={{ width: `${Math.min(b.used, 1) * 100}%` }}
                />
              </div>
              <div className="meter-caption">
                <span>
                  {cost(b.spent_micros + b.reserved_micros)} of {cost(b.limit_micros)}
                </span>
                <span>{b.scope}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel mx-panel mx-crosscheck">
        <PanelTitle title="Do the two sources agree?" />
        <div className="mx-compare">
          <div>
            <span className="mx-source-chip cerbos">Cerbos</span>
            <strong>{count(allowedModelCalls)}</strong>
            <span>model calls allowed inside LiteLLM</span>
          </div>
          <div>
            <span className="mx-source-chip ledger">Ledger</span>
            <strong>{count(g.summary.requests)}</strong>
            <span>requests billed</span>
          </div>
        </div>
        <p className="mx-footnote">
          They should match: the ledger bills every call Cerbos allows inside LiteLLM, whether or not it came
          through the gateway. A gap means calls still in flight, or records that were cleared: Cerbos's log
          is append-only and survives a demo reset, while the ledger's records do not.
          {c.oldest && ` Cerbos's log starts ${new Date(c.oldest).toLocaleString()}.`}
        </p>
      </section>
    </>
  );
}

function SourceCard({ tone, title, body }: { tone: "cerbos" | "ledger"; title: string; body: string }) {
  return (
    <div className={`mx-source ${tone}`}>
      <span className={`mx-source-chip ${tone}`}>Source</span>
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function SectionHeader({
  tone,
  source,
  title,
  detail,
}: {
  tone: "cerbos" | "ledger";
  source: string;
  title: string;
  detail: string;
}) {
  return (
    <div className="mx-section">
      <span className={`mx-source-chip ${tone}`}>Source · {source}</span>
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}

function PanelTitle({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        {detail && <p>{detail}</p>}
      </div>
    </div>
  );
}

function Tile({
  icon,
  label,
  value,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  children: React.ReactNode;
}) {
  return (
    <div className="metric">
      <div>
        <span>{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <strong>{value}</strong>
      <p>{children}</p>
    </div>
  );
}

function bucketLabel(start: string, range: MetricsWindow) {
  const date = new Date(start);
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return range === "7d" ? `${date.toLocaleDateString([], { weekday: "short" })} ${time}` : time;
}

function Timeline({ buckets, range }: { buckets: Metrics["cerbos"]["timeline"]; range: MetricsWindow }) {
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1, ...buckets.map((b) => b.allowed + b.denied));
  const ticks = [0, Math.floor(buckets.length / 2), buckets.length - 1];
  const focus = active === null ? null : buckets[active];
  return (
    <div className="mx-timeline">
      <div className="mx-legend" aria-hidden="true">
        <span>
          <i className="mx-swatch s1" />
          Allowed
        </span>
        <span>
          <i className="mx-swatch s2" />
          Denied
        </span>
        <span className="mx-axis-max">peak {count(max)} per interval</span>
      </div>
      <div className="mx-columns">
        {buckets.map((b, index) => {
          const total = b.allowed + b.denied;
          return (
            <button
              type="button"
              key={b.start}
              className={`mx-column${active === index ? " active" : ""}`}
              onMouseEnter={() => setActive(index)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(index)}
              onBlur={() => setActive(null)}
              aria-label={`${bucketLabel(b.start, range)}: ${b.allowed} allowed, ${b.denied} denied`}
            >
              <span className="mx-stack" style={{ height: `${(total / max) * 100}%` }}>
                {b.denied > 0 && <span className="mx-seg s2" style={{ flexGrow: b.denied }} />}
                {b.allowed > 0 && <span className="mx-seg s1" style={{ flexGrow: b.allowed }} />}
              </span>
            </button>
          );
        })}
        {focus && active !== null && (
          <div
            className="mx-tooltip"
            style={{ left: `${((active + 0.5) / buckets.length) * 100}%` }}
            role="status"
          >
            <strong>{bucketLabel(focus.start, range)}</strong>
            <span>
              <i className="mx-swatch s1" />
              {count(focus.allowed)} allowed
            </span>
            <span>
              <i className="mx-swatch s2" />
              {count(focus.denied)} denied
            </span>
          </div>
        )}
      </div>
      <div className="mx-xaxis" aria-hidden="true">
        {ticks.map((i) => (
          <span key={i}>{buckets[i] ? bucketLabel(buckets[i].start, range) : ""}</span>
        ))}
      </div>
    </div>
  );
}

function OutcomeTable({
  rows,
  heading,
  legend = true,
}: {
  rows: ({ label: string } & Partial<Record<Outcome, number>>)[];
  heading: string;
  legend?: boolean;
}) {
  return (
    <div className="mx-outcomes table-scroll">
      <div className="mx-legend" hidden={!legend}>
        {OUTCOMES.map((o, i) => (
          <span key={o.id} title={o.hint}>
            <i className={`mx-swatch s${i + 1}`} />
            {o.label}
          </span>
        ))}
      </div>
      <table className="mx-table">
        <thead>
          <tr>
            <th>{heading}</th>
            <th className="mx-bar-col">
              <span className="sr-only">Share</span>
            </th>
            {OUTCOMES.map((o) => (
              <th key={o.id} className="num">
                {o.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const total = OUTCOMES.reduce((sum, o) => sum + (row[o.id] ?? 0), 0);
            return (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td className="mx-bar-col">
                  <span className="mx-hbar">
                    {OUTCOMES.map((o, i) =>
                      row[o.id] ? (
                        <span
                          key={o.id}
                          className={`mx-seg s${i + 1}`}
                          style={{ flexGrow: row[o.id] }}
                          title={`${o.label}: ${row[o.id]} of ${total}`}
                        />
                      ) : null,
                    )}
                  </span>
                </td>
                {OUTCOMES.map((o) => (
                  <td key={o.id} className="num">
                    {count(row[o.id] ?? 0)}
                  </td>
                ))}
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                No model calls in this window.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function RuleTable({ rules }: { rules: Metrics["cerbos"]["top_rules"] }) {
  const max = Math.max(1, ...rules.map((r) => r.count));
  return (
    <div className="table-scroll">
      <table className="mx-table">
        <thead>
          <tr>
            <th>Rule</th>
            <th>Effect</th>
            <th className="mx-bar-col">Times applied</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <tr key={`${r.kind}#${r.rule}#${r.effect}`}>
              <td className="mx-rule">
                {r.rule}
                <div className="cell-subtitle">{r.kind}</div>
              </td>
              <td>
                <span className={`mx-effect ${r.effect}`}>
                  {r.effect === "allow" ? <Checkmark12Filled /> : <Dismiss12Filled />}
                  {r.effect === "allow" ? "Allow" : "Deny"}
                </span>
              </td>
              <td className="mx-bar-col">
                <span className="mx-count">
                  <span className="mx-single" style={{ width: `${(r.count / max) * 100}%` }} />
                  <span className="tabular">{count(r.count)}</span>
                </span>
              </td>
              <td className="mx-reason">{r.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SpendBars({ rows }: { rows: { label: string; requests: number; spend_micros: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.spend_micros));
  if (rows.length === 0) return <p className="mx-footnote">No billed requests in this window.</p>;
  return (
    <div className="mx-spend">
      {rows.map((r) => (
        <div key={r.label} className="mx-spend-row">
          <span className="mx-spend-label">
            {r.label}
            <span className="muted"> · {count(r.requests)} requests</span>
          </span>
          <span className="mx-count">
            <span className="mx-single" style={{ width: `${(r.spend_micros / max) * 100}%` }} />
            <span className="tabular">{cost(r.spend_micros)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
