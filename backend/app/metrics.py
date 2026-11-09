"""Governance metrics from two sources, kept apart on purpose.

Cerbos: Cerbos's own decision log (audit.file in cerbos/config.yaml). Cerbos writes one
JSON line for every check it answers, with the principal, resource, actions, effects and
the outputs of the rules that activated. Callers tag each check with X-Ai-Spine-Source,
so enforcement (api, gateway, litellm) is counted apart from dashboard lookups and
playground simulations.
Nothing here is recorded by the AI spine itself.

Ledger: the AI spine's budget ledger (app/ledger.py, the events table). LiteLLM's Cerbos
guard reserves and settles every model call there, through the gateway or not: spend,
tokens, models answered, what Cerbos's obligations saved, and budget refusals. Cerbos does
not know prices or token counts.
"""

import json
import os
import re
import threading
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .config import settings
from .db import get_db
from .ledger import PRICING, actual_cost
from .models import ApiKey, Budget, Department, Event, Team, User
from .policy import decided_by, platform_resource, require, rule_effects

router = APIRouter(prefix="/api")

Window = Literal["1h", "24h", "7d"]
WINDOWS = {
    "1h": (timedelta(hours=1), timedelta(minutes=5)),
    "24h": (timedelta(hours=24), timedelta(hours=1)),
    "7d": (timedelta(days=7), timedelta(hours=6)),
}
# Attempts Cerbos allowed or refused. Dashboard lookups (which controls to show) and
# playground simulations are reported, but never mixed into these numbers.
ENFORCEMENT = ("api", "gateway", "litellm")
SOURCES = (*ENFORCEMENT, "dashboard", "playground")
RETAINED = 250_000  # Decisions kept in memory; older ones fall out of the window anyway.
DEFAULT_DENY = "No rule matched (default deny)"
FRACTION = re.compile(r"\.\d+")


@dataclass(frozen=True)
class Decision:
    at: datetime
    source: str
    principal_id: str
    principal_attr: dict
    kind: str
    resource_id: str
    resource_attr: dict
    action: str
    allowed: bool
    rule: str | None
    reason: str
    obligations: dict = field(default_factory=dict)


def _timestamp(value: str) -> datetime:
    # Cerbos writes RFC 3339 with nanoseconds; Python keeps microseconds.
    value = FRACTION.sub(lambda m: m.group(0)[:7], value.replace("Z", "+00:00"))
    at = datetime.fromisoformat(value)
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def parse_entry(line: str, effects: dict[str, str]) -> list[Decision]:
    """Turn one decision-log line into one Decision per resource and action."""
    try:
        entry = json.loads(line)
        check = entry["checkResources"]
        at = _timestamp(entry["timestamp"])
    except (ValueError, KeyError, TypeError):
        return []
    values = ((entry.get("metadata") or {}).get("x-ai-spine-source") or {}).get("values") or []
    source = values[0] if values else "untagged"
    decisions = []
    inputs = check.get("inputs") or []
    for index, result in enumerate(check.get("outputs") or []):
        request = inputs[index] if index < len(inputs) else {}
        if (request.get("resource") or {}).get("id") != result.get("resourceId"):
            request = next(
                (
                    i
                    for i in inputs
                    if (i.get("resource") or {}).get("id") == result.get("resourceId")
                ),
                {},
            )
        resource = request.get("resource") or {}
        principal = request.get("principal") or {}
        kind = resource.get("kind", "")
        for action, outcome in (result.get("actions") or {}).items():
            effect = outcome.get("effect", "EFFECT_DENY")
            rule, reason, obligations = decided_by(
                kind, action, effect, result.get("outputs"), effects
            )
            decisions.append(
                Decision(
                    at=at,
                    source=source,
                    principal_id=principal.get("id", ""),
                    principal_attr=principal.get("attr") or {},
                    kind=kind,
                    resource_id=result.get("resourceId", ""),
                    resource_attr=resource.get("attr") or {},
                    action=action,
                    allowed=effect == "EFFECT_ALLOW",
                    rule=rule,
                    reason=reason,
                    obligations=obligations,
                )
            )
    return decisions


class DecisionLog:
    """Reads Cerbos's decision log incrementally: each call parses only new lines.

    Cerbos rotates the file by renaming it and starting a new one, so files are tracked by
    inode: a renamed file keeps its read offset and a new file is read from the start.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.offsets: dict[int, int] = {}
        self.decisions: deque[Decision] = deque(maxlen=RETAINED)
        self.lock = threading.Lock()

    def files(self) -> list[Path]:
        pattern = f"{self.path.stem}*{self.path.suffix}"
        try:
            found = list(self.path.parent.glob(pattern))
            return sorted(found, key=lambda p: p.stat().st_mtime_ns)
        except OSError:
            return []

    def read(self) -> tuple[list[Decision], bool]:
        """All retained decisions, oldest first, and whether the log could be read at all."""
        with self.lock:
            files = self.files()
            effects = rule_effects() if files else {}
            seen = set()
            for path in files:
                try:
                    with path.open("rb") as handle:
                        inode = os.fstat(handle.fileno()).st_ino
                        seen.add(inode)
                        offset = self.offsets.get(inode, 0)
                        if offset > os.fstat(handle.fileno()).st_size:
                            offset = 0  # Truncated in place.
                        handle.seek(offset)
                        chunk = handle.read()
                except OSError:
                    continue
                end = chunk.rfind(b"\n") + 1  # Leave a half-written last line for later.
                for line in chunk[:end].splitlines():
                    if line.strip():
                        self.decisions.extend(parse_entry(line.decode("utf-8", "replace"), effects))
                self.offsets[inode] = offset + end
            self.offsets = {k: v for k, v in self.offsets.items() if k in seen}
            ordered = sorted(self.decisions, key=lambda d: d.at)
            self.decisions = deque(ordered, maxlen=RETAINED)
            return ordered, bool(files)


_logs: dict[str, DecisionLog] = {}


def decision_log() -> DecisionLog:
    path = settings().cerbos_decision_log
    if path not in _logs:
        _logs[path] = DecisionLog(path)
    return _logs[path]


# --- Aggregation ---------------------------------------------------------------------------


def _counts(items, key):
    table = defaultdict(lambda: {"allowed": 0, "denied": 0})
    for item in items:
        table[key(item)]["allowed" if item.allowed else "denied"] += 1
    return table


def _timeline(items, since, now, step):
    buckets = []
    start = since
    while start < now:
        buckets.append({"start": start.isoformat(), "allowed": 0, "denied": 0})
        start += step
    for item in items:
        index = int((item.at - since) / step)
        if 0 <= index < len(buckets):
            buckets[index]["allowed" if item.allowed else "denied"] += 1
    return buckets


def model_outcome(decision: Decision) -> str:
    """What LiteLLM did with a model call, from Cerbos's decision and its obligations.

    Mirrors infra/cerbos_guard.py: an obligation applies only when it changes the request.
    """
    if not decision.allowed:
        return "refused"
    obligations = decision.obligations
    if obligations.get("model") and obligations["model"] != decision.resource_id:
        return "downgraded"
    cap, requested = obligations.get("max_tokens"), decision.resource_attr.get("max_tokens")
    if isinstance(cap, int | float) and isinstance(requested, int | float) and cap < requested:
        return "capped"
    return "answered"


def cerbos_metrics(decisions, since, now, step, names):
    window = [d for d in decisions if since <= d.at <= now]
    real = [d for d in window if d.source in ENFORCEMENT]
    denied = sum(not d.allowed for d in real)

    by_source = Counter(d.source for d in window if d.source != "probe")
    sources = [
        {"source": s, "decisions": by_source.get(s, 0), "enforcement": s in ENFORCEMENT}
        # Untagged or unknown callers are listed too, never silently dropped.
        for s in [*SOURCES, *sorted(set(by_source) - set(SOURCES))]
    ]

    rules = Counter((d.kind, d.rule, d.allowed) for d in real)
    reasons = {(d.kind, d.rule, d.allowed): d.reason for d in real}
    top_rules = [
        {
            "kind": kind,
            "rule": rule or DEFAULT_DENY,
            "effect": "allow" if allowed else "deny",
            "count": count,
            "reason": reasons[(kind, rule, allowed)],
        }
        for (kind, rule, allowed), count in rules.most_common(12)
    ]

    kinds = _counts(real, lambda d: d.kind)
    by_kind = sorted(
        ({"kind": k, **v} for k, v in kinds.items()),
        key=lambda row: -(row["allowed"] + row["denied"]),
    )

    llm = [d for d in real if d.source == "litellm"]
    invokes = [d for d in llm if d.kind == "model" and d.action == "invoke"]
    outcomes = Counter(model_outcome(d) for d in invokes)
    by_team = defaultdict(Counter)
    by_class = defaultdict(Counter)
    for d in invokes:
        by_team[names.team(d.principal_attr.get("team_id"))][model_outcome(d)] += 1
        by_class[d.resource_attr.get("data_classification", "unknown")][model_outcome(d)] += 1
    listing = [d for d in llm if d.kind == "model" and d.action == "list"]
    tools = _counts(
        [d for d in llm if d.kind == "mcp_tool"],
        lambda d: (d.resource_attr.get("tool", d.resource_id), d.resource_attr.get("risk", "")),
    )

    per_principal = defaultdict(lambda: {"denied": 0, "total": 0, "rules": Counter()})
    for d in real:
        row = per_principal[d.principal_id]
        row["total"] += 1
        if not d.allowed:
            row["denied"] += 1
            row["rules"][(d.rule or DEFAULT_DENY, f"{d.action} {d.kind}:{d.resource_id}")] += 1
    principals = [
        {
            "id": pid,
            "name": names.principal(pid),
            "type": "API key" if pid.startswith("key:") else "Person",
            "denied": row["denied"],
            "total": row["total"],
            "top_rule": row["rules"].most_common(1)[0][0][0],
            # What was refused most often, e.g. "call mcp_tool:knowledge/add_note".
            "top_check": row["rules"].most_common(1)[0][0][1],
        }
        for pid, row in sorted(per_principal.items(), key=lambda kv: -kv[1]["denied"])
        if row["denied"]
    ][:6]

    return {
        "summary": {
            "decisions": len(real),
            "allowed": len(real) - denied,
            "denied": denied,
            "deny_rate": denied / len(real) if real else 0,
            "simulated": by_source.get("playground", 0),
            "lookups": by_source.get("dashboard", 0),
        },
        "sources": sources,
        "by_kind": by_kind,
        "top_rules": top_rules,
        "litellm": {
            "model_calls": len(invokes),
            "outcomes": {
                k: outcomes.get(k, 0) for k in ("answered", "downgraded", "capped", "refused")
            },
            "by_team": [{"team": team, **counts} for team, counts in sorted(by_team.items())],
            "by_classification": [
                {"classification": c, **counts} for c, counts in sorted(by_class.items())
            ],
            "catalog": {
                "listed": sum(d.allowed for d in listing),
                "hidden": sum(not d.allowed for d in listing),
            },
            "tools": [
                {"tool": tool, "risk": risk, **counts}
                for (tool, risk), counts in sorted(tools.items())
            ],
        },
        "principals": principals,
        "timeline": _timeline(real, since, now, step),
    }


def ledger_metrics(db: Session, since, names):
    events = db.scalars(
        select(Event)
        .where(Event.created_at >= since, Event.type.like("ledger.%"))
        .order_by(Event.created_at)
    ).all()
    completed = [e for e in events if e.type == "ledger.settled"]
    spend = sum(int(e.detail.get("cost_micros", 0)) for e in completed)
    direct = [e for e in completed if e.detail.get("entry") == "direct"]

    teams = defaultdict(lambda: {"requests": 0, "spend_micros": 0})
    models = defaultdict(lambda: {"requests": 0, "spend_micros": 0})
    saved = downgraded = capped = input_tokens = output_tokens = 0
    for e in completed:
        detail = e.detail
        cost = int(detail.get("cost_micros", 0))
        answered = detail.get("answered_model") or detail.get("model", "")
        for table, key in ((teams, names.team(e.team_id)), (models, answered)):
            table[key]["requests"] += 1
            table[key]["spend_micros"] += cost
        tokens_in, tokens_out = detail.get("input_tokens"), detail.get("output_tokens")
        if isinstance(tokens_in, int) and isinstance(tokens_out, int):
            input_tokens += tokens_in
            output_tokens += tokens_out
            requested = detail.get("model")
            if answered != requested and requested in PRICING:
                downgraded += 1
                saved += max(actual_cost(requested, tokens_in, tokens_out) - cost, 0)
        if "max_tokens" in (detail.get("obligations") or {}):
            capped += 1

    refused = [e for e in events if e.type == "ledger.refused"]
    by_scope = Counter(e.detail.get("scope") or "other" for e in refused)
    uncertain = [e for e in events if e.type == "ledger.uncertain"]
    budgets = db.scalars(select(Budget).where(Budget.limit_micros > 0)).all()
    return {
        "summary": {
            "requests": len(completed),
            "spend_micros": spend,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "downgraded": downgraded,
            "capped": capped,
            "saved_micros": saved,
            "direct_requests": len(direct),
            "direct_spend_micros": sum(int(e.detail.get("cost_micros", 0)) for e in direct),
            "refused_by_budget": len(refused),
            "refused_direct": sum(e.detail.get("entry") == "direct" for e in refused),
            "uncertain": len(uncertain),
            "uncertain_micros": sum(int(e.detail.get("reserved_micros", 0)) for e in uncertain),
        },
        "by_team": sorted(
            ({"team": k, **v} for k, v in teams.items()), key=lambda r: -r["spend_micros"]
        ),
        "by_model": sorted(
            ({"model": k, **v} for k, v in models.items()), key=lambda r: -r["spend_micros"]
        ),
        "refusals": [{"scope": scope, "count": n} for scope, n in by_scope.most_common()],
        "budgets": sorted(
            (
                {
                    "id": b.id,
                    "name": b.name,
                    "scope": b.scope,
                    "spent_micros": b.spent_micros,
                    "reserved_micros": b.reserved_micros,
                    "limit_micros": b.limit_micros,
                    "used": (b.spent_micros + b.reserved_micros) / b.limit_micros,
                }
                for b in budgets
            ),
            key=lambda r: -r["used"],
        )[:6],
    }


class Names:
    """Display names for the ids found in Cerbos's log and the budget ledger."""

    def __init__(self, db: Session):
        self.users = {u.id: u.name for u in db.scalars(select(User)).all()}
        self.teams = {t.id: t.name for t in db.scalars(select(Team)).all()}
        self.departments = {d.id: d.name for d in db.scalars(select(Department)).all()}
        self.keys = {
            f"key:{k.id}": f"{k.name} ({self.users.get(k.owner_id, k.owner_id)})"
            for k in db.scalars(select(ApiKey)).all()
        }

    def team(self, team_id):
        return self.teams.get(team_id, "Personal") if team_id else "Personal"

    def principal(self, pid):
        if pid in self.users or pid in self.keys:
            return self.users.get(pid) or self.keys[pid]
        # Cerbos's log is append-only, so it outlives keys removed by a demo reset.
        return f"Removed API key …{pid[-6:]}" if pid.startswith("key:") else pid


@router.get("/metrics")
def metrics(
    window: Window = "24h",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require(user, platform_resource(), "view_metrics")
    span, step = WINDOWS[window]
    now = datetime.now(UTC)
    since = now - span
    names = Names(db)
    decisions, available = decision_log().read()
    return {
        "window": window,
        "since": since.isoformat(),
        "now": now.isoformat(),
        "cerbos": {
            "available": available,
            "log": settings().cerbos_decision_log,
            "oldest": decisions[0].at.isoformat() if decisions else None,
            **cerbos_metrics(decisions, since, now, step, names),
        },
        "ledger": ledger_metrics(db, since, names),
    }
