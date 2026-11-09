import { Checkbox, Field, Select, Spinner } from "@fluentui/react-components";
import { useQueries } from "@tanstack/react-query";
import { useState } from "react";
import { roleName } from "../api";
import { DecisionCell, Why } from "./DecisionCell";
import { actionLabel, PLAYGROUND, runCheck } from "./hooks";
import { usePlaygroundStyles } from "./styles";
import type { Catalog, Decision } from "./types";

/** Every persona against one resource: the same request, different answers. */
export function Compare({ catalog }: { catalog: Catalog }) {
  const styles = usePlaygroundStyles();
  // People only (models and MCP tools are decided for API keys), and kinds that have data.
  const kinds = catalog.kinds.filter(
    (k) => k.kind !== "model" && k.kind !== "mcp_tool" && k.resources.length > 0,
  );
  const [kind, setKind] = useState("approval");
  const info = kinds.find((k) => k.kind === kind) || kinds[0];
  const [resourceId, setResourceId] = useState(info.resources[0]?.id || "");
  const [personaIds, setPersonaIds] = useState(catalog.personas.map((p) => p.id));
  const [selected, setSelected] = useState<{ persona: string; action: string } | null>(null);
  const resource = info.resources.find((r) => r.id === resourceId) || info.resources[0];

  const results = useQueries({
    queries: catalog.personas
      .filter((p) => personaIds.includes(p.id))
      .map((persona) => {
        const spec = {
          principal: { persona_id: persona.id },
          kind: info.kind,
          resource_ids: resource ? [resource.id] : [],
          actions: info.actions,
        };
        return {
          queryKey: [PLAYGROUND, "check", spec],
          queryFn: () => runCheck(spec),
          enabled: !!resource,
        };
      }),
  });
  const shown = catalog.personas.filter((p) => personaIds.includes(p.id));
  const decisionFor = (index: number, action: string): Decision | undefined =>
    results[index]?.data?.results[0]?.decisions[action];
  const selectedIndex = selected ? shown.findIndex((p) => p.id === selected.persona) : -1;
  const selectedDecision = selected ? decisionFor(selectedIndex, selected.action) : undefined;

  return (
    <div className={styles.stack}>
      <section className={styles.panel} aria-label="Compare personas">
        <p className={styles.muted}>
          The same resource, checked for every persona at once. Roles alone do not decide: teams, operating
          units, ownership and the resource's own state all count.
        </p>
        <div className={styles.row}>
          <Field label="Resource kind">
            <Select
              value={info.kind}
              onChange={(_, data) => {
                const next = kinds.find((k) => k.kind === data.value);
                setKind(data.value);
                setResourceId(next?.resources[0]?.id || "");
                setSelected(null);
              }}
            >
              {kinds.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.description}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Resource">
            <Select
              className={styles.wideControl}
              value={resource?.id || ""}
              onChange={(_, data) => {
                setResourceId(data.value);
                setSelected(null);
              }}
            >
              {info.resources.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </Select>
          </Field>
          {results.some((r) => r.isFetching) && <Spinner size="tiny" label="Asking Cerbos" />}
        </div>
        <fieldset className={styles.fieldset}>
          <legend className={styles.groupLabel}>Personas to compare</legend>
          <div className={styles.checkGrid}>
            {catalog.personas.map((p) => (
              <Checkbox
                key={p.id}
                label={p.name}
                checked={personaIds.includes(p.id)}
                onChange={(_, data) =>
                  setPersonaIds(data.checked ? [...personaIds, p.id] : personaIds.filter((id) => id !== p.id))
                }
              />
            ))}
          </div>
        </fieldset>
      </section>
      <section className={styles.panel} aria-label="Decisions per persona">
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.th}>Persona</th>
                {info.actions.map((action) => (
                  <th key={action} className={styles.th}>
                    {actionLabel(action)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((persona, index) => (
                <tr key={persona.id}>
                  <th scope="row" className={`${styles.td} ${styles.rowHeader}`}>
                    {persona.name}
                    <div className={`${styles.muted} ${styles.small}`}>
                      {persona.roles.map(roleName).join(" + ")}
                    </div>
                  </th>
                  {info.actions.map((action) => {
                    const decision = decisionFor(index, action);
                    return (
                      <td key={action} className={styles.td}>
                        {decision && (
                          <DecisionCell
                            decision={decision}
                            selected={selected?.persona === persona.id && selected.action === action}
                            onSelect={() => setSelected({ persona: persona.id, action })}
                          />
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selected && selectedDecision && (
          <Why
            decision={selectedDecision}
            subject={`${shown[selectedIndex]?.name} · ${actionLabel(selected.action)} · ${resource?.label}`}
          />
        )}
      </section>
    </div>
  );
}
