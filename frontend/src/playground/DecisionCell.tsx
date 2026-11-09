import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import { CheckmarkCircle16Filled, DismissCircle16Filled } from "@fluentui/react-icons";
import { usePlaygroundStyles } from "./styles";
import type { Decision, Effect } from "./types";

const useStyles = makeStyles({
  cell: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: "2px",
    width: "100%",
    minWidth: "120px",
    border: "1px solid transparent",
    borderRadius: tokens.borderRadiusMedium,
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalXS}`,
    backgroundColor: "transparent",
    color: "inherit",
    font: "inherit",
    textAlign: "left",
    cursor: "pointer",
    ":hover": { backgroundColor: tokens.colorNeutralBackground1Hover },
    ":focus-visible": { outline: `2px solid ${tokens.colorStrokeFocus2}` },
  },
  selected: {
    border: `1px solid ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorBrandBackground2,
  },
  verdict: {
    display: "inline-flex",
    alignItems: "center",
    gap: tokens.spacingHorizontalXXS,
    fontWeight: tokens.fontWeightSemibold,
  },
  allow: { color: tokens.colorPaletteGreenForeground1 },
  deny: { color: tokens.colorPaletteRedForeground1 },
  rule: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
    wordBreak: "break-word",
  },
  mismatch: { color: tokens.colorPaletteMarigoldForeground1, fontSize: tokens.fontSizeBase100 },
});

export function Verdict({ effect }: { effect: Effect }) {
  const styles = useStyles();
  return (
    <span className={mergeClasses(styles.verdict, effect === "allow" ? styles.allow : styles.deny)}>
      {effect === "allow" ? <CheckmarkCircle16Filled /> : <DismissCircle16Filled />}
      {effect === "allow" ? "Allowed" : "Denied"}
    </span>
  );
}

/** A clickable matrix cell: verdict plus the deciding rule. */
export function DecisionCell({
  decision,
  selected = false,
  expected,
  onSelect,
}: {
  decision: Decision;
  selected?: boolean;
  expected?: Effect;
  onSelect?: () => void;
}) {
  const styles = useStyles();
  return (
    <button
      type="button"
      className={mergeClasses(styles.cell, selected && styles.selected)}
      onClick={onSelect}
      aria-pressed={selected}
      title={decision.reason}
    >
      <Verdict effect={decision.effect} />
      <span className={styles.rule}>{decision.rule ?? "default deny"}</span>
      {expected && expected !== decision.effect && (
        <span className={styles.mismatch}>Expected {expected === "allow" ? "allowed" : "denied"}</span>
      )}
    </button>
  );
}

/** The full explanation of one decision. */
export function Why({ decision, subject }: { decision: Decision; subject: string }) {
  const shared = usePlaygroundStyles();
  return (
    <div className={shared.why} aria-live="polite">
      <div className={shared.row}>
        <Verdict effect={decision.effect} />
        <span className={shared.muted}>{subject}</span>
      </div>
      <p style={{ margin: 0 }}>{decision.reason}</p>
      <span className={mergeClasses(shared.mono, shared.muted)}>
        {decision.rule
          ? `Rule ${decision.rule} in ${decision.policy || "the resource policy"}`
          : `No rule matched in ${decision.policy || "any policy"}; Cerbos denies by default.`}
      </span>
    </div>
  );
}
