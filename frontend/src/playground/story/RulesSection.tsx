import {
  Badge,
  Button,
  MessageBar,
  MessageBarBody,
  makeStyles,
  Spinner,
  Switch,
  tokens,
} from "@fluentui/react-components";
import { DocumentText20Regular } from "@fluentui/react-icons";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { togglePreset, usePresets, useRefreshAuthorization } from "../hooks";
import type { Preset, PresetResult } from "../types";
import { SectionHeader, useStoryStyles } from "./shared";

const useStyles = makeStyles({
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
    gap: tokens.spacingHorizontalM,
  },
  preset: { justifyContent: "space-between" },
  presetOn: {
    border: `2px solid ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorBrandBackground2,
  },
  top: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: tokens.spacingHorizontalS,
  },
  title: { margin: 0, fontWeight: tokens.fontWeightSemibold, fontSize: tokens.fontSizeBase300 },
});

function PresetCard({
  preset,
  busy,
  onToggle,
}: {
  preset: Preset;
  busy: boolean;
  onToggle: (on: boolean) => void;
}) {
  const styles = useStyles();
  const story = useStoryStyles();
  return (
    <div className={`${story.card} ${styles.preset} ${preset.on ? styles.presetOn : ""}`}>
      <div className={styles.top}>
        <h3 className={styles.title}>{preset.title}</h3>
        {busy ? (
          <Spinner size="tiny" label="Applying" labelPosition="before" />
        ) : (
          <Switch
            aria-label={preset.title}
            checked={preset.on}
            disabled={!preset.available}
            onChange={(_, data) => onToggle(!!data.checked)}
          />
        )}
      </div>
      <p className={story.muted}>{preset.effect}</p>
      <div className={story.row}>
        <Badge appearance="tint" color="informative">
          {preset.policy}.yaml
        </Badge>
        <Badge appearance="outline" color={preset.affects === "litellm" ? "brand" : "subtle"}>
          {preset.affects === "litellm" ? "Changes AI traffic" : "Changes what people can do"}
        </Badge>
        {!preset.available && (
          <Badge appearance="tint" color="warning">
            edited by hand
          </Badge>
        )}
      </div>
    </div>
  );
}

export function RulesSection() {
  const styles = useStyles();
  const story = useStoryStyles();
  const navigate = useNavigate();
  const presets = usePresets();
  const refresh = useRefreshAuthorization();
  const [busy, setBusy] = useState<string | null>(null);
  const [last, setLast] = useState<{ preset: Preset; on: boolean; result: PresetResult } | null>(null);
  const toggle = useMutation({
    mutationFn: ({ preset, on }: { preset: Preset; on: boolean }) => togglePreset(preset.id, on),
    onMutate: ({ preset }) => setBusy(preset.id),
    onSuccess: async (result, { preset, on }) => {
      setLast({ preset, on, result });
      await refresh();
    },
    onSettled: () => setBusy(null),
  });

  return (
    <section className={story.section} aria-labelledby="rules-title">
      <SectionHeader
        number={2}
        id="rules-title"
        title="Change the rules, not the code"
        description="Authorization lives in Cerbos policy files, not in the application. Flip a change: Cerbos compiles it, runs the policy test suite, and hot-reloads it within seconds. The board above and the AI gateway below follow immediately, with no redeploy."
        action={
          <Button
            icon={<DocumentText20Regular />}
            onClick={() => navigate("/playground/advanced?tab=policies")}
          >
            Edit the YAML yourself
          </Button>
        }
      />
      <div className={styles.grid}>
        {presets.data?.map((preset) => (
          <PresetCard
            key={preset.id}
            preset={preset}
            busy={busy === preset.id}
            onToggle={(on) => toggle.mutate({ preset, on })}
          />
        ))}
      </div>
      {toggle.error && (
        <MessageBar intent="error">
          <MessageBarBody>{toggle.error.message}</MessageBarBody>
        </MessageBar>
      )}
      {last?.result.changed && (
        <MessageBar intent="success" aria-live="polite">
          <MessageBarBody>
            <strong>
              {last.on ? "Applied" : "Reverted"}: {last.preset.title}.
            </strong>{" "}
            Cerbos validated it and served it in {last.result.reload_seconds} s.{" "}
            {last.result.tests && last.result.tests.failed > 0
              ? `${last.result.tests.failed} ${last.result.tests.failed === 1 ? "policy test now fails, because it describes" : "policy tests now fail, because they describe"} the previous rule; in a real change you would update ${last.result.tests.failed === 1 ? "it" : "them"} in the same pull request.`
              : `All ${last.result.tests?.passed ?? ""} policy tests pass.`}{" "}
            {last.preset.affects === "litellm"
              ? "The AI traffic board in section 3 is sending its calls again."
              : "Pick Jordan or Casey above to see the difference."}
          </MessageBarBody>
        </MessageBar>
      )}
    </section>
  );
}
