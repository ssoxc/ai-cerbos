export type MetricsWindow = "1h" | "24h" | "7d";
export type Outcome = "answered" | "downgraded" | "capped" | "refused";
type Counts = { allowed: number; denied: number };
type OutcomeCounts = Partial<Record<Outcome, number>>;

/** GET /api/metrics: two sources, kept apart (backend/app/metrics.py). */
export type Metrics = {
  window: MetricsWindow;
  since: string;
  now: string;
  /** Read from Cerbos's own decision log. */
  cerbos: {
    available: boolean;
    log: string;
    oldest: string | null;
    summary: {
      decisions: number;
      allowed: number;
      denied: number;
      deny_rate: number;
      simulated: number;
      lookups: number;
    };
    sources: { source: string; decisions: number; enforcement: boolean }[];
    by_kind: ({ kind: string } & Counts)[];
    top_rules: { kind: string; rule: string; effect: "allow" | "deny"; count: number; reason: string }[];
    litellm: {
      model_calls: number;
      outcomes: Record<Outcome, number>;
      by_team: ({ team: string } & OutcomeCounts)[];
      by_classification: ({ classification: string } & OutcomeCounts)[];
      catalog: { listed: number; hidden: number };
      tools: ({ tool: string; risk: string } & Counts)[];
    };
    principals: {
      id: string;
      name: string;
      type: string;
      denied: number;
      total: number;
      top_rule: string;
      top_check: string;
    }[];
    timeline: ({ start: string } & Counts)[];
  };
  /** Read from the AI spine's budget ledger, which LiteLLM's Cerbos hook keeps for every call. */
  ledger: {
    summary: {
      requests: number;
      spend_micros: number;
      input_tokens: number;
      output_tokens: number;
      downgraded: number;
      capped: number;
      saved_micros: number;
      direct_requests: number;
      direct_spend_micros: number;
      refused_by_budget: number;
      refused_direct: number;
      uncertain: number;
      uncertain_micros: number;
    };
    by_team: { team: string; requests: number; spend_micros: number }[];
    by_model: { model: string; requests: number; spend_micros: number }[];
    refusals: { scope: string; count: number }[];
    budgets: {
      id: string;
      name: string;
      scope: string;
      spent_micros: number;
      reserved_micros: number;
      limit_micros: number;
      used: number;
    }[];
  };
};
