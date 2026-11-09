import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactNode } from "react";

/** Shared layout for the story page. Fluent tokens only, so it follows the app theme. */
export const useStoryStyles = makeStyles({
  page: { display: "flex", flexDirection: "column", gap: "48px" },
  section: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalL, minWidth: 0 },
  stack: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalM, minWidth: 0 },
  row: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: tokens.spacingHorizontalM },
  card: {
    backgroundColor: tokens.colorNeutralBackground1,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusXLarge,
    padding: tokens.spacingHorizontalXL,
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalM,
    minWidth: 0,
  },
  cardTitle: {
    margin: 0,
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
    lineHeight: tokens.lineHeightBase400,
  },
  muted: { margin: 0, color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  mono: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200 },
  code: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    backgroundColor: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusMedium,
    padding: tokens.spacingHorizontalM,
    margin: 0,
    overflowX: "auto",
    whiteSpace: "pre-wrap",
  },
  headerRow: { display: "flex", gap: tokens.spacingHorizontalM, alignItems: "flex-start" },
  number: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    width: "32px",
    height: "32px",
    borderRadius: tokens.borderRadiusCircular,
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    fontWeight: tokens.fontWeightBold,
  },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeHero700,
    lineHeight: tokens.lineHeightHero700,
    fontWeight: tokens.fontWeightSemibold,
  },
  description: {
    margin: `${tokens.spacingVerticalXS} 0 0`,
    color: tokens.colorNeutralForeground2,
    maxWidth: "820px",
  },
});

export function SectionHeader({
  number,
  id,
  title,
  description,
  action,
}: {
  number: number;
  id: string;
  title: string;
  description: ReactNode;
  action?: ReactNode;
}) {
  const styles = useStoryStyles();
  return (
    <div className={styles.headerRow}>
      <span className={styles.number}>{number}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h2 id={id} className={styles.title}>
          {title}
        </h2>
        <p className={styles.description}>{description}</p>
      </div>
      {action}
    </div>
  );
}

/** A compact, pill-style choice between a few options. */
export function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const styles = useChoiceStyles();
  return (
    <fieldset className={styles.fieldset}>
      <legend className={styles.legend}>{label}</legend>
      <div className={styles.options}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={option.value === value}
            className={option.value === value ? `${styles.option} ${styles.active}` : styles.option}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

const useChoiceStyles = makeStyles({
  fieldset: { border: "none", margin: 0, padding: 0, minWidth: 0 },
  legend: {
    padding: 0,
    marginBottom: tokens.spacingVerticalXS,
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground2,
  },
  options: {
    display: "inline-flex",
    flexWrap: "wrap",
    gap: "2px",
    padding: "2px",
    borderRadius: tokens.borderRadiusCircular,
    backgroundColor: tokens.colorNeutralBackground3,
  },
  option: {
    border: "none",
    borderRadius: tokens.borderRadiusCircular,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalM}`,
    backgroundColor: "transparent",
    color: tokens.colorNeutralForeground2,
    font: "inherit",
    fontSize: tokens.fontSizeBase300,
    cursor: "pointer",
    ":hover": { color: tokens.colorNeutralForeground1 },
    ":focus-visible": { outline: `2px solid ${tokens.colorStrokeFocus2}` },
  },
  active: {
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    fontWeight: tokens.fontWeightSemibold,
    boxShadow: tokens.shadow4,
  },
});
