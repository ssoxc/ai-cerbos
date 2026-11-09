import {
  Badge,
  Button,
  Checkbox,
  Dropdown,
  Field,
  Input,
  Option,
  Select,
  Spinner,
  Switch,
} from "@fluentui/react-components";
import { ArrowReset20Regular } from "@fluentui/react-icons";
import { useMemo, useState } from "react";
import { roleName } from "../api";
import { DecisionCell, Why } from "./DecisionCell";
import { actionLabel, useCheck } from "./hooks";
import { usePlaygroundStyles } from "./styles";
import type { Attributes, AttrValue, Catalog, CheckSpec, PrincipalSpec } from "./types";

const MAX_DEFAULT_RESOURCES = 12;

type Selection = { resource: string; action: string } | null;

function same(a: string[], b: string[]) {
  return a.length === b.length && a.every((value) => b.includes(value));
}

function toggle(list: string[], value: string, on: boolean) {
  return on ? [...new Set([...list, value])] : list.filter((item) => item !== value);
}

/** Persona attributes as Cerbos sees them, editable without saving anything. */
function PersonaEditor({
  catalog,
  spec,
  onChange,
}: {
  catalog: Catalog;
  spec: PrincipalSpec;
  onChange: (spec: PrincipalSpec) => void;
}) {
  const styles = usePlaygroundStyles();
  const persona = catalog.personas.find((p) => p.id === spec.persona_id) || catalog.personas[0];
  const value = {
    roles: spec.roles ?? persona.roles,
    team_ids: spec.team_ids ?? persona.team_ids,
    admin_team_ids: spec.admin_team_ids ?? persona.admin_team_ids,
    department_ids: spec.department_ids ?? persona.department_ids,
  };
  const changed =
    !same(value.roles, persona.roles) ||
    !same(value.team_ids, persona.team_ids) ||
    !same(value.admin_team_ids, persona.admin_team_ids) ||
    !same(value.department_ids, persona.department_ids);
  const set = (field: keyof typeof value, next: string[]) => onChange({ ...spec, [field]: next });
  const group = (field: keyof typeof value, label: string, options: { id: string; name: string }[]) => (
    <fieldset className={styles.fieldset}>
      <legend className={styles.groupLabel}>{label}</legend>
      <div className={styles.checkGrid}>
        {options.map((option) => (
          <Checkbox
            key={option.id}
            label={option.name}
            checked={value[field].includes(option.id)}
            onChange={(_, data) => set(field, toggle(value[field], option.id, !!data.checked))}
          />
        ))}
      </div>
    </fieldset>
  );
  return (
    <div className={styles.stack}>
      <Field label="Persona">
        <Select
          className={styles.control}
          value={persona.id}
          onChange={(_, data) => onChange({ persona_id: data.value })}
        >
          {catalog.personas.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} · {p.roles.map(roleName).join(" + ")}
            </option>
          ))}
        </Select>
      </Field>
      <div className={styles.spread}>
        {changed ? (
          <Badge appearance="tint" color="warning">
            What-if: not saved anywhere
          </Badge>
        ) : (
          <Badge appearance="tint" color="informative">
            {persona.name}'s real attributes
          </Badge>
        )}
        {changed && (
          <Button
            size="small"
            appearance="subtle"
            icon={<ArrowReset20Regular />}
            onClick={() => onChange({ persona_id: persona.id })}
          >
            Restore
          </Button>
        )}
      </div>
      {group(
        "roles",
        "Roles",
        catalog.options.roles.map((role) => ({ id: role, name: roleName(role) })),
      )}
      {group("team_ids", "Member of teams", catalog.options.teams)}
      {group("admin_team_ids", "Administers teams", catalog.options.teams)}
      {group("department_ids", "Operating units", catalog.options.departments)}
    </div>
  );
}

/** For model checks the principal is an API key, exactly as LiteLLM's guard sends it. */
function KeyEditor({
  catalog,
  spec,
  onChange,
}: {
  catalog: Catalog;
  spec: PrincipalSpec;
  onChange: (spec: PrincipalSpec) => void;
}) {
  const styles = usePlaygroundStyles();
  const key = catalog.demo_keys.find((k) => k.owner === spec.key_owner) || catalog.demo_keys[0];
  const team = spec.team_id ?? String(key.principal.attr.team_id ?? "");
  return (
    <div className={styles.stack}>
      <p className={styles.muted}>
        Inside LiteLLM, Cerbos sees the API key itself, with the owner, team, department and agent recorded
        when the key was issued.
      </p>
      <Field label="API key">
        <Select
          className={styles.control}
          value={key.owner}
          onChange={(_, data) => onChange({ key_owner: data.value })}
        >
          {catalog.demo_keys.map((k) => (
            <option key={k.owner} value={k.owner}>
              {k.name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Key's team (what-if)">
        <Select
          className={styles.control}
          value={team}
          onChange={(_, data) => onChange({ ...spec, team_id: data.value })}
        >
          <option value="">No team</option>
          {catalog.options.teams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </Select>
      </Field>
      <p className={styles.muted}>
        Owner {key.owner === "alex" ? "Alex Rivera" : "Sam Taylor"} · agent{" "}
        {String(key.principal.attr.asset_id)} · role api_key
      </p>
    </div>
  );
}

function AttributeInput({
  name,
  original,
  value,
  onChange,
}: {
  name: string;
  original: AttrValue;
  value: AttrValue;
  onChange: (value: AttrValue) => void;
}) {
  if (typeof original === "boolean") {
    return <Switch label={name} checked={!!value} onChange={(_, data) => onChange(data.checked)} />;
  }
  if (Array.isArray(original)) {
    return (
      <Field label={name} hint="Comma-separated ids">
        <Input
          value={(value as string[]).join(", ")}
          onChange={(_, data) =>
            onChange(
              data.value
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            )
          }
        />
      </Field>
    );
  }
  if (typeof original === "number") {
    return (
      <Field label={name}>
        <Input
          type="number"
          value={String(value ?? "")}
          onChange={(_, data) => onChange(Number(data.value))}
        />
      </Field>
    );
  }
  return (
    <Field label={name}>
      <Input value={String(value ?? "")} onChange={(_, data) => onChange(data.value)} />
    </Field>
  );
}

export function Explore({
  catalog,
  initial,
}: {
  catalog: Catalog;
  /** A starting point, for example from a guided scenario. */
  initial: CheckSpec;
}) {
  const styles = usePlaygroundStyles();
  const [kind, setKind] = useState(initial.kind);
  const [principal, setPrincipal] = useState<PrincipalSpec>(initial.principal);
  const kindInfo = catalog.kinds.find((k) => k.kind === kind) || catalog.kinds[0];
  const [resourceIds, setResourceIds] = useState<string[]>(initial.resource_ids);
  const [overrides, setOverrides] = useState<Attributes>(initial.resource_overrides || {});
  const [actions, setActions] = useState<string[]>(initial.actions || kindInfo.actions);
  const [selection, setSelection] = useState<Selection>(null);

  // Inside LiteLLM, models and MCP tools are decided for the API key, not for a person.
  const keyMode = kind === "model" || kind === "mcp_tool";
  const effectivePrincipal: PrincipalSpec = keyMode
    ? principal.key_owner
      ? principal
      : { key_owner: catalog.demo_keys[0]?.owner }
    : principal.persona_id
      ? principal
      : { persona_id: catalog.personas[0]?.id };
  const single =
    resourceIds.length === 1 ? kindInfo.resources.find((r) => r.id === resourceIds[0]) : undefined;

  const spec = useMemo<CheckSpec | null>(
    () =>
      resourceIds.length
        ? {
            principal: effectivePrincipal,
            kind,
            resource_ids: resourceIds,
            resource_overrides: single ? overrides : {},
            actions: actions.length ? actions : kindInfo.actions,
          }
        : null,
    [effectivePrincipal, kind, resourceIds, overrides, single, actions, kindInfo.actions],
  );
  const check = useCheck(spec);

  const changeKind = (next: string) => {
    const info = catalog.kinds.find((k) => k.kind === next);
    if (!info) return;
    setKind(next);
    setResourceIds(info.resources.slice(0, MAX_DEFAULT_RESOURCES).map((r) => r.id));
    setActions(info.actions);
    setOverrides({});
    setSelection(null);
  };

  const selectedResult = selection && check.data?.results.find((r) => r.id === selection.resource);
  const selectedDecision = selectedResult?.decisions[selection?.action || ""];

  return (
    <div className={styles.twoColumns}>
      <section className={styles.panel} aria-label="Who is asking">
        <h2 className={styles.panelTitle}>Who is asking</h2>
        {keyMode ? (
          <KeyEditor catalog={catalog} spec={effectivePrincipal} onChange={setPrincipal} />
        ) : (
          <PersonaEditor catalog={catalog} spec={effectivePrincipal} onChange={setPrincipal} />
        )}
      </section>
      <div className={styles.stack}>
        <section className={styles.panel} aria-label="What they want to do">
          <h2 className={styles.panelTitle}>What they want to do</h2>
          <div className={styles.row}>
            <Field label="Resource kind">
              <Select value={kind} onChange={(_, data) => changeKind(data.value)}>
                {catalog.kinds.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {k.description}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Resources">
              <Dropdown
                multiselect
                placeholder="Choose resources"
                selectedOptions={resourceIds}
                value={`${resourceIds.length} of ${kindInfo.resources.length} selected`}
                onOptionSelect={(_, data) => {
                  setResourceIds(data.selectedOptions);
                  setOverrides({});
                  setSelection(null);
                }}
              >
                {kindInfo.resources.map((r) => (
                  <Option key={r.id} value={r.id}>
                    {r.label}
                  </Option>
                ))}
              </Dropdown>
            </Field>
            <Field label="Actions">
              <Dropdown
                multiselect
                selectedOptions={actions}
                value={`${actions.length} of ${kindInfo.actions.length} actions`}
                onOptionSelect={(_, data) => setActions(data.selectedOptions)}
              >
                {kindInfo.actions.map((action) => (
                  <Option key={action} value={action}>
                    {actionLabel(action)}
                  </Option>
                ))}
              </Dropdown>
            </Field>
          </div>
          {single ? (
            <details>
              <summary>
                What-if: change {single.label}'s attributes
                {Object.keys(overrides).length > 0 && ` (${Object.keys(overrides).length} changed)`}
              </summary>
              <div className={styles.checkGrid} style={{ marginTop: 8, gap: 8 }}>
                {Object.entries(single.attr).map(([name, original]) => (
                  <AttributeInput
                    key={name}
                    name={name}
                    original={original}
                    value={name in overrides ? overrides[name] : original}
                    onChange={(value) => setOverrides({ ...overrides, [name]: value })}
                  />
                ))}
              </div>
              {Object.keys(overrides).length > 0 && (
                <Button appearance="subtle" icon={<ArrowReset20Regular />} onClick={() => setOverrides({})}>
                  Restore real attributes
                </Button>
              )}
            </details>
          ) : (
            <p className={styles.muted}>Select a single resource to change its attributes.</p>
          )}
        </section>
        <section className={styles.panel} aria-label="Cerbos decisions">
          <div className={styles.spread}>
            <h2 className={styles.panelTitle}>Cerbos decides</h2>
            {check.isFetching && <Spinner size="tiny" label="Asking Cerbos" />}
          </div>
          {check.error && <p role="alert">{check.error.message}</p>}
          {check.data && (
            <>
              <p className={styles.muted}>
                Asking as{" "}
                <strong>
                  {keyMode
                    ? `${catalog.demo_keys.find((k) => k.owner === effectivePrincipal.key_owner)?.name ?? "an API key"}`
                    : (catalog.personas.find((p) => p.id === check.data.principal.id)?.name ??
                      check.data.principal.id)}
                </strong>{" "}
                with roles {check.data.principal.roles.map(roleName).join(", ") || "none"}. Select a cell to
                see why.
              </p>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th className={styles.th}>Resource</th>
                      {check.data.actions.map((action) => (
                        <th key={action} className={styles.th}>
                          {actionLabel(action)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {check.data.results.map((result) => (
                      <tr key={result.id}>
                        <th scope="row" className={`${styles.td} ${styles.rowHeader}`}>
                          {result.label}
                        </th>
                        {check.data.actions.map((action) => (
                          <td key={action} className={styles.td}>
                            {result.decisions[action] && (
                              <DecisionCell
                                decision={result.decisions[action]}
                                selected={selection?.resource === result.id && selection.action === action}
                                onSelect={() => setSelection({ resource: result.id, action })}
                              />
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedDecision && selectedResult && (
                <Why
                  decision={selectedDecision}
                  subject={`${actionLabel(selection?.action || "")} · ${selectedResult.label}`}
                />
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
