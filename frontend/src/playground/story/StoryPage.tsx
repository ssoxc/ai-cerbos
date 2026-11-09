import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  makeStyles,
  Spinner,
  tokens,
} from "@fluentui/react-components";
import { ArrowReset20Regular, ArrowRight16Regular, Options20Regular } from "@fluentui/react-icons";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { PageProps } from "../../App";
import { api } from "../../api";
import { useCatalog, usePolicies, useRefreshAuthorization } from "../hooks";
import { GatewaySection } from "./GatewaySection";
import { PeopleSection } from "./PeopleSection";
import { RulesSection } from "./RulesSection";
import { useStoryStyles } from "./shared";

const useStyles = makeStyles({
  hero: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.spacingVerticalL,
    padding: "32px",
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    "@media (max-width: 640px)": { padding: "20px" },
  },
  heroTop: {
    display: "flex",
    justifyContent: "space-between",
    gap: tokens.spacingHorizontalL,
    flexWrap: "wrap",
  },
  eyebrow: {
    fontSize: tokens.fontSizeBase200,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    opacity: 0.8,
  },
  heroTitle: {
    margin: 0,
    fontSize: tokens.fontSizeHero800,
    lineHeight: tokens.lineHeightHero800,
    fontWeight: tokens.fontWeightSemibold,
  },
  heroText: {
    margin: 0,
    maxWidth: "760px",
    opacity: 0.92,
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
  },
  steps: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
    gap: tokens.spacingHorizontalM,
    margin: 0,
    padding: 0,
    listStyleType: "none",
  },
  step: {
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: "rgba(255, 255, 255, 0.12)",
    display: "flex",
    flexDirection: "column",
    gap: "2px",
  },
  stepTitle: { fontWeight: tokens.fontWeightSemibold },
  stats: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalXXL },
  stat: { display: "flex", flexDirection: "column" },
  statNumber: { fontSize: tokens.fontSizeHero700, fontWeight: tokens.fontWeightBold, lineHeight: "1.1" },
  actions: { display: "flex", gap: tokens.spacingHorizontalS, alignItems: "flex-start", flexWrap: "wrap" },
  footer: { display: "flex", justifyContent: "center" },
});

export function StoryPage({ notify }: PageProps) {
  const styles = useStyles();
  const story = useStoryStyles();
  const navigate = useNavigate();
  const catalog = useCatalog();
  const policies = usePolicies();
  const refresh = useRefreshAuthorization();
  const [confirmReset, setConfirmReset] = useState(false);
  const resetDemo = useMutation({
    mutationFn: () => api("/api/demo/reset", "POST"),
    onSuccess: async () => {
      setConfirmReset(false);
      await refresh();
      notify("The demo is back to its starting point: sample data and the shipped Cerbos policies.");
    },
  });

  return (
    <div className={story.page}>
      <header className={styles.hero}>
        <div className={styles.heroTop}>
          <div className={story.stack}>
            <span className={styles.eyebrow}>Cerbos playground</span>
            <h1 className={styles.heroTitle}>Cerbos decides. The app and LiteLLM enforce.</h1>
            <p className={styles.heroText}>
              Every permission in this product, from approving a budget to calling an AI model or an MCP tool,
              is one question to Cerbos with a named rule as the answer. Change a person or a policy and watch
              every decision follow.
            </p>
          </div>
          <div className={styles.actions}>
            <Button icon={<Options20Regular />} onClick={() => navigate("/playground/advanced")}>
              Advanced tools
            </Button>
            <Button icon={<ArrowReset20Regular />} onClick={() => setConfirmReset(true)}>
              Reset demo
            </Button>
          </div>
        </div>
        <ol className={styles.steps}>
          <li className={styles.step}>
            <span className={styles.stepTitle}>1. The app asks</span>
            <span>Who is acting, on what, and which action.</span>
          </li>
          <li className={styles.step}>
            <span className={styles.stepTitle}>2. Cerbos decides</span>
            <span>Policies as data: roles plus live attributes, with a reason.</span>
          </li>
          <li className={styles.step}>
            <span className={styles.stepTitle}>3. Everyone enforces</span>
            <span>The dashboard, the API gateway and LiteLLM follow the same answer.</span>
          </li>
        </ol>
        <div className={styles.stats}>
          <div className={styles.stat}>
            <span className={styles.statNumber}>{catalog.data?.personas.length ?? "…"}</span>
            <span>people with different scopes</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statNumber}>{policies.data?.length ?? "…"}</span>
            <span>policies, with unit tests</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statNumber}>4</span>
            <span>Cerbos checks inside LiteLLM</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statNumber}>0</span>
            <span>permission rules in the app's code</span>
          </div>
        </div>
      </header>
      {catalog.error && <p role="alert">{catalog.error.message}</p>}
      {!catalog.data ? (
        <Spinner label="Loading the playground" />
      ) : (
        <>
          <PeopleSection personas={catalog.data.personas} initial="maya" />
          <RulesSection />
          <GatewaySection catalog={catalog.data} />
          <div className={styles.footer}>
            <Button
              appearance="subtle"
              icon={<ArrowRight16Regular />}
              iconPosition="after"
              onClick={() => navigate("/playground/advanced")}
            >
              Go deeper: decision matrices, persona comparison and the policy editor
            </Button>
          </div>
        </>
      )}
      <Dialog open={confirmReset} onOpenChange={(_, value) => setConfirmReset(value.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Reset the whole demo?</DialogTitle>
            <DialogContent>
              Sample data, approvals, keys, budgets and the audit log return to their starting point, and
              every Cerbos policy returns to the shipped version. Issued keys are revoked.
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setConfirmReset(false)}>Cancel</Button>
              <Button appearance="primary" disabled={resetDemo.isPending} onClick={() => resetDemo.mutate()}>
                {resetDemo.isPending ? "Resetting…" : "Reset demo"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      {resetDemo.error && <p role="alert">{resetDemo.error.message}</p>}
    </div>
  );
}
