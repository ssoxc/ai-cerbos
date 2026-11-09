import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  makeStyles,
  Spinner,
  Tab,
  TabList,
  Textarea,
  tokens,
} from "@fluentui/react-components";
import { ArrowReset20Regular, Save20Regular } from "@fluentui/react-icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { PLAYGROUND, usePolicies, useRefreshAuthorization } from "./hooks";
import { usePlaygroundStyles } from "./styles";
import type { PendingEdit, PolicyDocument, SaveResult, ValidationResult } from "./types";

const useStyles = makeStyles({
  layout: {
    display: "grid",
    gridTemplateColumns: "220px minmax(0, 1fr)",
    gap: tokens.spacingHorizontalXL,
    alignItems: "start",
    "@media (max-width: 860px)": { gridTemplateColumns: "minmax(0, 1fr)" },
  },
  list: { display: "flex", flexDirection: "column", gap: tokens.spacingVerticalXXS },
  item: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
    width: "100%",
  },
  editor: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    lineHeight: "1.55",
    minHeight: "460px",
  },
});

const policyLabel = (id: string) =>
  ({
    asset: "AI assets",
    approval: "Approvals",
    api_key: "API keys",
    budget: "Budgets",
    team: "Teams",
    department: "Operating units",
    platform: "Dashboard areas",
    audit: "Audit log",
    model: "Models (LiteLLM)",
  })[id] || id;

function Report({ result }: { result: ValidationResult & { reload_seconds?: number } }) {
  const styles = usePlaygroundStyles();
  if (!result.compile.ok) {
    return (
      <MessageBar intent="error">
        <MessageBarBody>
          <MessageBarTitle>Cerbos rejected this policy. Nothing was changed.</MessageBarTitle>
          {result.compile.errors.map((error) => (
            <div key={`${error.file}-${error.line}-${error.message}`}>
              <span className={styles.mono}>
                {error.file}
                {error.line ? `:${error.line}:${error.column}` : ""}
              </span>{" "}
              {error.message}
              {error.context && <pre className={styles.code}>{error.context}</pre>}
            </div>
          ))}
        </MessageBarBody>
      </MessageBar>
    );
  }
  return (
    <MessageBar intent={result.tests.failed ? "warning" : "success"}>
      <MessageBarBody>
        <MessageBarTitle>
          Live in {result.reload_seconds ?? "a few"} s. Policy tests: {result.tests.passed} passed
          {result.tests.failed ? `, ${result.tests.failed} now fail` : ""}.
        </MessageBarTitle>
        {result.tests.failed > 0 && (
          <>
            These tests describe the shipped behaviour, so a deliberate change makes some fail. In a real
            project you would update the tests in the same change.
            <ul>
              {result.tests.failures.slice(0, 6).map((f) => (
                <li key={`${f.test}-${f.principal}-${f.resource}-${f.action}`}>
                  {f.test}: <span className={styles.mono}>{f.principal}</span> {f.action}{" "}
                  <span className={styles.mono}>{f.resource}</span> expected{" "}
                  {f.expected.replace("EFFECT_", "")}, now {f.actual.replace("EFFECT_", "")}
                </li>
              ))}
            </ul>
          </>
        )}
      </MessageBarBody>
    </MessageBar>
  );
}

export function PolicyEditor({
  pendingEdit,
  onEditApplied,
  notify,
}: {
  pendingEdit: PendingEdit | null;
  onEditApplied: () => void;
  notify: (message: string) => void;
}) {
  const styles = usePlaygroundStyles();
  const local = useStyles();
  const refresh = useRefreshAuthorization();
  const policies = usePolicies();
  const [selectedId, setSelectedId] = useState(pendingEdit?.policy || "model");
  const [draft, setDraft] = useState<string | null>(null);
  const [view, setView] = useState<"edit" | "diff">("edit");
  const [result, setResult] = useState<(ValidationResult & { reload_seconds?: number }) | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [scenarioNote, setScenarioNote] = useState("");

  const document = useQuery({
    queryKey: [PLAYGROUND, "policy", selectedId],
    queryFn: () => api<PolicyDocument>(`/api/policies/${selectedId}`),
  });

  useEffect(() => {
    if (pendingEdit) {
      setSelectedId(pendingEdit.policy);
      setResult(null);
      setView("edit");
    }
  }, [pendingEdit]);

  // Apply a guided scenario's suggested change to the draft once its policy is loaded.
  useEffect(() => {
    if (!pendingEdit || !document.data || document.data.id !== pendingEdit.policy) return;
    if (document.data.yaml.includes(pendingEdit.find)) {
      setDraft(document.data.yaml.replace(pendingEdit.find, pendingEdit.replace));
      setScenarioNote(
        `The change for "${pendingEdit.scenario}" is in the draft below. Review it, then save.`,
      );
    } else {
      setScenarioNote(
        "This policy already differs from the scenario's starting point. Reset policies to retry.",
      );
    }
    onEditApplied();
  }, [pendingEdit, document.data, onEditApplied]);

  const text = draft ?? document.data?.yaml ?? "";
  const dirty = !!document.data && draft !== null && draft !== document.data.yaml;

  const save = useMutation({
    mutationFn: () =>
      api<SaveResult>(`/api/policies/${selectedId}`, "PUT", {
        yaml: text,
        base_sha: document.data?.sha,
      }),
    onSuccess: async (saved) => {
      setResult(saved);
      setDraft(null);
      setScenarioNote("");
      await refresh();
      notify(`${saved.document.file} is live. Every decision in the dashboard now follows it.`);
    },
    onError: (error) => {
      const body = error instanceof ApiError ? error.body : {};
      if (body.compile) setResult(body as unknown as ValidationResult);
      else setResult(null);
    },
  });

  const reset = useMutation({
    mutationFn: () => api<{ reload_seconds: number }>("/api/policies/reset", "POST"),
    onSuccess: async () => {
      setConfirmReset(false);
      setDraft(null);
      setResult(null);
      setScenarioNote("");
      await refresh();
      notify("All Cerbos policies are back to the shipped versions.");
    },
  });

  const select = (id: string) => {
    if (dirty && !window.confirm("Discard your unsaved changes to this policy?")) return;
    setSelectedId(id);
    setDraft(null);
    setResult(null);
    setScenarioNote("");
  };

  return (
    <div className={local.layout}>
      <section className={styles.panel} aria-label="Policies">
        <h2 className={styles.panelTitle}>Policies</h2>
        <div className={local.list}>
          {policies.data?.map((policy) => (
            <Button
              key={policy.id}
              appearance={policy.id === selectedId ? "secondary" : "subtle"}
              onClick={() => select(policy.id)}
              aria-current={policy.id === selectedId}
            >
              <span className={local.item}>
                <span>{policyLabel(policy.id)}</span>
                {policy.modified && (
                  <Badge size="small" appearance="tint" color="warning">
                    edited
                  </Badge>
                )}
              </span>
            </Button>
          ))}
        </div>
        <Button icon={<ArrowReset20Regular />} onClick={() => setConfirmReset(true)}>
          Reset all policies
        </Button>
      </section>
      <section className={styles.panel} aria-label="Policy editor">
        <div className={styles.spread}>
          <div>
            <h2 className={styles.panelTitle}>{document.data?.file || "Loading…"}</h2>
            <p className={`${styles.muted} ${styles.small}`}>
              Saved changes are compiled and tested by Cerbos, then hot-reloaded. No redeploy.
            </p>
          </div>
          <TabList
            className={styles.tabs}
            size="small"
            selectedValue={view}
            onTabSelect={(_, data) => setView(data.value as "edit" | "diff")}
          >
            <Tab value="edit">Edit</Tab>
            <Tab value="diff">Changes vs shipped</Tab>
          </TabList>
        </div>
        {scenarioNote && (
          <MessageBar intent="info">
            <MessageBarBody>{scenarioNote}</MessageBarBody>
          </MessageBar>
        )}
        {view === "edit" ? (
          <Field label="Policy YAML">
            <Textarea
              resize="vertical"
              value={text}
              spellCheck={false}
              textarea={{ className: local.editor, wrap: "off" }}
              onChange={(_, data) => setDraft(data.value)}
            />
          </Field>
        ) : (
          <pre className={styles.code}>
            {document.data?.diff || "No changes: this is the shipped policy."}
          </pre>
        )}
        <div className={styles.row}>
          <Button
            appearance="primary"
            icon={save.isPending ? <Spinner size="tiny" /> : <Save20Regular />}
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Validating and reloading…" : "Save and apply"}
          </Button>
          <Button disabled={!dirty || save.isPending} onClick={() => setDraft(null)}>
            Discard changes
          </Button>
        </div>
        {save.error && !result && <p role="alert">{save.error.message}</p>}
        {result && <Report result={result} />}
      </section>
      <Dialog open={confirmReset} onOpenChange={(_, data) => setConfirmReset(data.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Reset all policies?</DialogTitle>
            <DialogContent>
              Every Cerbos policy returns to the version shipped with this project. Your workspace data is not
              affected.
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setConfirmReset(false)}>Cancel</Button>
              <Button appearance="primary" disabled={reset.isPending} onClick={() => reset.mutate()}>
                {reset.isPending ? "Resetting…" : "Reset policies"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
