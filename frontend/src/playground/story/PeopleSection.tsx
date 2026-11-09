import {
  Avatar,
  Badge,
  Button,
  makeStyles,
  mergeClasses,
  Spinner,
  Switch,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowReset20Regular,
  CheckmarkCircle20Filled,
  DismissCircle20Filled,
  Pin16Regular,
} from "@fluentui/react-icons";
import { useState } from "react";
import { roleName } from "../../api";
import type { User } from "../../types";
import { useBoard } from "../hooks";
import type { Board, Capability, PrincipalView, WhatIf } from "../types";
import { SectionHeader, useStoryStyles } from "./shared";

const useStyles = makeStyles({
  personas: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
    gap: tokens.spacingHorizontalS,
  },
  persona: {
    display: "flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    padding: tokens.spacingHorizontalS,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    cursor: "pointer",
    textAlign: "left",
    font: "inherit",
    color: "inherit",
    minWidth: 0,
    ":hover": { backgroundColor: tokens.colorNeutralBackground1Hover },
    ":focus-visible": { outline: `2px solid ${tokens.colorStrokeFocus2}` },
  },
  personaActive: {
    border: `2px solid ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorBrandBackground2,
  },
  personaText: { display: "flex", flexDirection: "column", minWidth: 0 },
  ellipsis: { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
  personaName: { fontWeight: tokens.fontWeightSemibold },
  personaRole: { fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground3 },
  layout: {
    display: "grid",
    gridTemplateColumns: "minmax(280px, 330px) minmax(0, 1fr)",
    gap: tokens.spacingHorizontalXL,
    alignItems: "start",
    "@media (max-width: 1000px)": { gridTemplateColumns: "minmax(0, 1fr)" },
  },
  whatIf: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXS,
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusLarge,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  whatIfOn: {
    border: `2px solid ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorBrandBackground2,
  },
  whatIfTop: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: tokens.spacingHorizontalS,
  },
  whatIfLabel: { fontWeight: tokens.fontWeightSemibold },
  hint: { fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground3 },
  looked: {
    display: "grid",
    gridTemplateColumns: "max-content minmax(0, 1fr)",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXXS,
    fontSize: tokens.fontSizeBase200,
  },
  lookedKey: { color: tokens.colorNeutralForeground3 },
  added: { color: tokens.colorPaletteGreenForeground1, fontWeight: tokens.fontWeightSemibold },
  removed: { color: tokens.colorPaletteRedForeground1, textDecorationLine: "line-through" },
  score: { display: "flex", alignItems: "baseline", gap: tokens.spacingHorizontalS, flexWrap: "wrap" },
  scoreNumber: {
    fontSize: "40px",
    lineHeight: "1",
    fontWeight: tokens.fontWeightBold,
    color: tokens.colorBrandForeground1,
  },
  scopes: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
    gap: tokens.spacingHorizontalM,
    alignItems: "start",
  },
  scope: {
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
    padding: tokens.spacingHorizontalM,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalXXS,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  scopeTitle: { margin: 0, fontWeight: tokens.fontWeightSemibold, fontSize: tokens.fontSizeBase300 },
  scopeSubtitle: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
    marginBottom: tokens.spacingVerticalXS,
  },
  item: {
    display: "grid",
    gridTemplateColumns: "20px minmax(0, 1fr)",
    gap: tokens.spacingHorizontalS,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalXS}`,
    borderRadius: tokens.borderRadiusMedium,
    border: "1px solid transparent",
    backgroundColor: "transparent",
    textAlign: "left",
    font: "inherit",
    color: "inherit",
    cursor: "pointer",
    ":hover": { backgroundColor: tokens.colorNeutralBackground1Hover },
    ":focus-visible": { outline: `2px solid ${tokens.colorStrokeFocus2}` },
  },
  changed: {
    border: `1px solid ${tokens.colorPaletteMarigoldBorder2}`,
    backgroundColor: tokens.colorPaletteMarigoldBackground1,
  },
  spotlit: { border: `1px dashed ${tokens.colorBrandStroke1}` },
  allow: { color: tokens.colorPaletteGreenForeground1 },
  deny: { color: tokens.colorNeutralForeground4 },
  label: { fontWeight: tokens.fontWeightMedium },
  denyLabel: { color: tokens.colorNeutralForeground3 },
  why: { fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground3, marginTop: "2px" },
  rule: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
  },
  spotlight: {
    display: "flex",
    gap: tokens.spacingHorizontalS,
    alignItems: "flex-start",
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorBrandBackground2,
  },
});

function CapabilityRow({ capability, spotlit }: { capability: Capability; spotlit: boolean }) {
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  const allowed = capability.effect === "allow";
  return (
    <button
      type="button"
      className={mergeClasses(styles.item, capability.changed && styles.changed, spotlit && styles.spotlit)}
      onClick={() => setOpen(!open)}
      aria-expanded={open}
    >
      {allowed ? (
        <CheckmarkCircle20Filled className={styles.allow} aria-label="Allowed" />
      ) : (
        <DismissCircle20Filled className={styles.deny} aria-label="Denied" />
      )}
      <span>
        <span className={mergeClasses(styles.label, !allowed && styles.denyLabel)}>{capability.label}</span>
        {capability.changed && (
          <>
            {" "}
            <Badge size="small" appearance="filled" color="warning">
              {allowed ? "now allowed" : "now denied"}
            </Badge>
          </>
        )}
        {(open || capability.changed || spotlit) && <div className={styles.why}>{capability.reason}</div>}
        {(open || spotlit) && (
          <div className={styles.rule}>{capability.rule ? `rule ${capability.rule}` : "default deny"}</div>
        )}
      </span>
    </button>
  );
}

function WhatIfCard({
  item,
  concept,
  onToggle,
}: {
  item: WhatIf;
  concept: string;
  onToggle: (on: boolean) => void;
}) {
  const styles = useStyles();
  return (
    <div className={mergeClasses(styles.whatIf, item.on && styles.whatIfOn)}>
      <div className={styles.whatIfTop}>
        <Badge appearance="tint" color="brand" size="small">
          {concept}
        </Badge>
        <Switch aria-label={item.label} checked={item.on} onChange={(_, data) => onToggle(!!data.checked)} />
      </div>
      <span className={styles.whatIfLabel}>{item.label}</span>
      <span className={styles.hint}>{item.hint}</span>
    </div>
  );
}

function LookedAt({ board }: { board: Board }) {
  const styles = useStyles();
  const story = useStoryStyles();
  const rows: [keyof PrincipalView, string][] = [
    ["roles", "Roles"],
    ["teams", "Teams"],
    ["admin_teams", "Admin of"],
    ["departments", "Units"],
  ];
  const show = (key: keyof PrincipalView, value: string) => (key === "roles" ? roleName(value) : value);
  return (
    <div className={story.stack}>
      <span className={story.muted}>What Cerbos looks at</span>
      <div className={styles.looked}>
        {rows.map(([key, label]) => {
          const before = board.before[key];
          const after = board.after[key];
          const values = [...new Set([...before, ...after])];
          return (
            <div key={key} style={{ display: "contents" }}>
              <span className={styles.lookedKey}>{label}</span>
              <span>
                {values.length === 0 && <span className={styles.lookedKey}>none</span>}
                {values.map((value, index) => (
                  <span key={value}>
                    {index > 0 && ", "}
                    <span
                      className={
                        !before.includes(value)
                          ? styles.added
                          : !after.includes(value)
                            ? styles.removed
                            : undefined
                      }
                    >
                      {show(key, value)}
                    </span>
                  </span>
                ))}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function PeopleSection({ personas, initial }: { personas: User[]; initial: string }) {
  const styles = useStyles();
  const story = useStoryStyles();
  const [personaId, setPersonaId] = useState(initial);
  const [selected, setSelected] = useState<string[]>([]);
  const board = useBoard(personaId, selected);
  const data = board.data?.persona.id === personaId ? board.data : undefined;
  const firstName = personas.find((p) => p.id === personaId)?.name.split(" ")[0] ?? "This person";
  const spotlit = new Set(data?.spotlights.map((s) => s.capability));
  const delta = data ? data.allowed - data.baseline_allowed : 0;

  return (
    <section className={story.section} aria-labelledby="people-title">
      <SectionHeader
        number={1}
        id="people-title"
        title="Who can do what, and why"
        description="Pick a person. Every line is a live Cerbos decision about real data in this workspace. Each person has three what-ifs chosen for them; flip one and only the decisions that depend on it change."
      />
      <nav className={styles.personas} aria-label="Choose a person">
        {personas.map((p) => (
          <button
            key={p.id}
            type="button"
            aria-pressed={p.id === personaId}
            className={mergeClasses(styles.persona, p.id === personaId && styles.personaActive)}
            onClick={() => {
              setPersonaId(p.id);
              setSelected([]);
            }}
          >
            <Avatar name={p.name} size={32} color={p.id === personaId ? "brand" : "neutral"} />
            <span className={styles.personaText}>
              <span className={mergeClasses(styles.personaName, styles.ellipsis)}>{p.name}</span>
              <span className={mergeClasses(styles.personaRole, styles.ellipsis)}>
                {p.roles.map(roleName).join(" + ")}
              </span>
            </span>
          </button>
        ))}
      </nav>
      <div className={styles.layout}>
        <div className={story.card}>
          <h3 className={story.cardTitle}>What if {firstName}…</h3>
          {data?.what_ifs.map((item) => (
            <WhatIfCard
              key={item.id}
              item={item}
              concept={data.concepts[item.concept] ?? item.concept}
              onToggle={(on) =>
                setSelected(on ? [...selected, item.id] : selected.filter((id) => id !== item.id))
              }
            />
          ))}
          {selected.length > 0 && (
            <Button appearance="subtle" icon={<ArrowReset20Regular />} onClick={() => setSelected([])}>
              Back to the real {firstName}
            </Button>
          )}
          {data && <LookedAt board={data} />}
          <p className={story.muted}>Nothing is saved: Cerbos simply receives different attributes.</p>
        </div>
        <div className={story.stack}>
          {data && (
            <div className={styles.score} aria-live="polite">
              <span className={styles.scoreNumber}>
                {data.allowed}/{data.total}
              </span>
              <span>
                things {firstName} can do
                {selected.length > 0 && (
                  <strong>
                    {" "}
                    ({delta > 0 ? `+${delta}` : delta === 0 ? "no change" : delta} with the what-ifs)
                  </strong>
                )}
              </span>
              {board.isFetching && <Spinner size="extra-tiny" label="Asking Cerbos" />}
            </div>
          )}
          {board.error && <p role="alert">{board.error.message}</p>}
          {data?.spotlights.map((spot) => {
            const capability = data.capabilities.find((c) => c.id === spot.capability);
            return (
              <div key={spot.what_if} className={styles.spotlight}>
                <Pin16Regular />
                <span>
                  <strong>
                    Still {spot.effect === "allow" ? "allowed" : "denied"}: {capability?.label}.
                  </strong>{" "}
                  {spot.reason} <span className={styles.rule}>({spot.rule ?? "default deny"})</span>
                </span>
              </div>
            );
          })}
          <div className={styles.scopes}>
            {data?.scopes.map((scope) => (
              <div key={scope.id} className={styles.scope}>
                <h4 className={styles.scopeTitle}>{scope.title}</h4>
                <span className={styles.scopeSubtitle}>{scope.subtitle}</span>
                {data.capabilities
                  .filter((c) => c.scope === scope.id)
                  .map((capability) => (
                    <CapabilityRow
                      key={capability.id}
                      capability={capability}
                      spotlit={spotlit.has(capability.id)}
                    />
                  ))}
              </div>
            ))}
          </div>
          {!data && board.isLoading && <Spinner label="Asking Cerbos" />}
          <p className={story.muted}>Select any line to see the exact Cerbos rule that decided it.</p>
        </div>
      </div>
    </section>
  );
}
