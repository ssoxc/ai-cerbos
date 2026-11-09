import { Badge, Button } from "@fluentui/react-components";
import {
  ArrowRight16Regular,
  Bot24Regular,
  PlugConnected24Regular,
  Search24Regular,
  ShieldCheckmark24Regular,
  Sparkle24Regular,
} from "@fluentui/react-icons";
import type { ReactNode } from "react";
import { kindName, money, relativeTime } from "./api";
import type { Asset, AuditEvent, Budget } from "./types";

export function AssetIcon({ kind, small = false }: { kind: string; small?: boolean }) {
  return (
    <span className={`asset-icon ${kind} ${small ? "small" : ""}`}>
      {kind === "agent" ? (
        <Bot24Regular />
      ) : kind === "mcp" ? (
        <PlugConnected24Regular />
      ) : (
        <Sparkle24Regular />
      )}
    </span>
  );
}

export function Status({ value }: { value: string }) {
  const label =
    {
      active: "Active",
      pending: "Pending approval",
      approved: "Approved",
      declined: "Declined",
      revoked: "Revoked",
      cancelled: "Cancelled",
      expired: "Expired",
    }[value] || value;
  return (
    <Badge
      appearance="tint"
      color={
        value === "active" || value === "approved"
          ? "success"
          : value === "pending"
            ? "warning"
            : value === "declined" || value === "revoked"
              ? "danger"
              : "informative"
      }
      className="status"
    >
      <span className={`status-dot ${value}`} />
      {label}
    </Badge>
  );
}

export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Search24Regular />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function SectionTitle({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function BudgetMeter({ budget, compact = false }: { budget: Budget; compact?: boolean }) {
  const fraction = budget.limit_micros
    ? (budget.spent_micros + budget.reserved_micros) / budget.limit_micros
    : 0;
  return (
    <div className={`budget-meter ${compact ? "compact" : ""}`}>
      <div className="budget-amount">
        <strong>{money(budget.spent_micros, compact ? 0 : 2)}</strong>
        <span> / {money(budget.limit_micros)}</span>
      </div>
      <div className="meter-track">
        <span
          className={fraction > 0.85 ? "high" : ""}
          style={{ width: `${Math.min(fraction * 100, 100)}%` }}
        />
      </div>
      {!compact && (
        <div className="meter-caption">
          <span>{Math.round(fraction * 100)}% committed</span>
          <span>{money(budget.reserved_micros, 4)} reserved</span>
        </div>
      )}
    </div>
  );
}

export function AssetTable({ assets, onSelect }: { assets: Asset[]; onSelect: (asset: Asset) => void }) {
  if (!assets.length)
    return (
      <Empty
        title="No assets found"
        description="Try a different search or register an asset to get started."
      />
    );
  return (
    <div className="table-scroll">
      <table className="asset-table">
        <thead>
          <tr>
            <th>Asset name</th>
            <th>Team</th>
            <th>Status</th>
            <th>Budget cap</th>
            <th>
              <span className="sr-only">Open asset</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {assets.map((asset) => (
            <tr key={asset.id}>
              <td>
                <button type="button" className="asset-name-button" onClick={() => onSelect(asset)}>
                  <AssetIcon kind={asset.kind} />
                  <span>
                    <strong>{asset.name}</strong>
                    <small>
                      {kindName(asset.kind)}
                      <span className="middle-dot">·</span>
                      {asset.visibility === "global"
                        ? "Global"
                        : asset.visibility === "private"
                          ? "Private"
                          : "Team access"}
                    </small>
                  </span>
                </button>
              </td>
              <td>
                <span className="team-cell">{asset.team_name}</span>
              </td>
              <td>
                <Status value={asset.status} />
              </td>
              <td>
                {asset.kind === "agent" && asset.budget ? (
                  <BudgetMeter budget={asset.budget} compact />
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>
                <Button
                  appearance="subtle"
                  icon={<ArrowRight16Regular />}
                  aria-label={`View ${asset.name}`}
                  onClick={() => onSelect(asset)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ActivityList({ events, limit = 4 }: { events: AuditEvent[]; limit?: number }) {
  return (
    <div className="activity-list">
      {events.slice(0, limit).map((event) => (
        <div className="activity-item" key={event.id}>
          <span className="activity-icon">
            <ShieldCheckmark24Regular />
          </span>
          <div>
            <p>
              <strong>{event.actor_name}</strong> {event.type.replaceAll(".", " · ").replaceAll("_", " ")}
            </p>
            <span>{typeof event.detail.name === "string" ? event.detail.name : event.resource_id}</span>
          </div>
          <time dateTime={event.created_at}>{relativeTime(event.created_at)}</time>
        </div>
      ))}
      {!events.length && <p className="muted padded">Your activity will appear here.</p>}
    </div>
  );
}
