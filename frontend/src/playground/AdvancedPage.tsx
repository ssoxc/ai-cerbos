import { Button, Spinner, Tab, TabList } from "@fluentui/react-components";
import {
  ArrowLeft20Regular,
  BranchFork20Regular,
  DocumentText20Regular,
  PeopleTeam20Regular,
} from "@fluentui/react-icons";
import { useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { PageProps } from "../App";
import { Compare } from "./Compare";
import { Explore } from "./Explore";
import { useCatalog } from "./hooks";
import { PolicyEditor } from "./PolicyEditor";
import { usePlaygroundStyles } from "./styles";
import type { CheckSpec } from "./types";

type TabValue = "explore" | "compare" | "policies";
const TABS: TabValue[] = ["explore", "compare", "policies"];

/** Power-user tools: any persona against any resource, side-by-side personas, raw policy YAML. */
export function AdvancedPage({ data, notify }: PageProps) {
  const styles = usePlaygroundStyles();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const catalog = useCatalog();
  const requested = params.get("tab") as TabValue | null;
  const tab: TabValue = requested && TABS.includes(requested) ? requested : "explore";
  const clearPendingEdit = useCallback(() => undefined, []);

  const defaultSpec: CheckSpec = {
    principal: { persona_id: data.user.id },
    kind: "asset",
    resource_ids:
      catalog.data?.kinds
        .find((k) => k.kind === "asset")
        ?.resources.slice(0, 12)
        .map((r) => r.id) || [],
  };

  return (
    <div className={styles.stack}>
      <div className="page-heading">
        <div>
          <div className="eyebrow">CERBOS PLAYGROUND · ADVANCED</div>
          <h1>Every decision, in detail.</h1>
          <p>
            Ask Cerbos about any person or API key, any resource and any action, compare everyone side by
            side, or edit the policy YAML directly.
          </p>
        </div>
        <Button icon={<ArrowLeft20Regular />} onClick={() => navigate("/playground")}>
          Back to the playground
        </Button>
      </div>
      <TabList
        className={styles.tabs}
        selectedValue={tab}
        onTabSelect={(_, value) => setParams({ tab: String(value.value) }, { replace: true })}
      >
        <Tab value="explore" icon={<BranchFork20Regular />}>
          Explore
        </Tab>
        <Tab value="compare" icon={<PeopleTeam20Regular />}>
          Compare people
        </Tab>
        <Tab value="policies" icon={<DocumentText20Regular />}>
          Edit policy YAML
        </Tab>
      </TabList>
      {catalog.error && <p role="alert">{catalog.error.message}</p>}
      {!catalog.data ? (
        <Spinner label="Loading" />
      ) : tab === "explore" ? (
        <Explore catalog={catalog.data} initial={defaultSpec} />
      ) : tab === "compare" ? (
        <Compare catalog={catalog.data} />
      ) : (
        <PolicyEditor pendingEdit={null} onEditApplied={clearPendingEdit} notify={notify} />
      )}
    </div>
  );
}
