import {
  type BrandVariants,
  Button,
  type ButtonState,
  createDOMRenderer,
  createLightTheme,
  FluentProvider,
  type FluentProviderCustomStyleHooks,
  makeStyles,
  mergeClasses,
  RendererProvider,
  type Theme,
  tokens,
} from "@fluentui/react-components";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { Component, type ErrorInfo, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "@fontsource/dm-sans/400.css";
import "@fontsource/dm-sans/500.css";
import "@fontsource/dm-sans/600.css";
import "@fontsource/dm-sans/700.css";
import "./styles.css";

// Brand ramp built around the ai-cerbos green (#215c49 at step 80, which createLightTheme maps to
// colorBrandBackground/Foreground1/Stroke1). Every brand-coloured Fluent component (Avatar, Badge,
// primary Button, Tab indicator, focus underline) reads from this ramp.
const brand: BrandVariants = {
  10: "#030d0a",
  20: "#071b15",
  30: "#0c2a21",
  40: "#123a2d",
  50: "#144032",
  60: "#174536",
  70: "#194b3b",
  80: "#215c49",
  90: "#3c6e5c",
  100: "#55806f",
  110: "#6d9283",
  120: "#85a597",
  130: "#9eb8ac",
  140: "#b7cbc2",
  150: "#d1dfd8",
  160: "#ebf3ee",
};

const theme: Theme = {
  ...createLightTheme(brand),
  fontFamilyBase: '"DM Sans", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif',
  borderRadiusMedium: "6px",
};

// Fluent's atomic CSS is inserted right after this marker, ahead of styles.css. App rules then win
// specificity ties with Fluent's base styles without !important, while Fluent's own state rules
// (:hover, :focus-within, …) keep their higher specificity.
const fluentStyleAnchor = document.createElement("meta");
fluentStyleAnchor.name = "fluent-styles";
document.head.prepend(fluentStyleAnchor);
const renderer = createDOMRenderer(document, { insertionPoint: fluentStyleAnchor });

const useProviderStyles = makeStyles({
  // The page background and text colour come from styles.css (:root), not the provider surface.
  root: { backgroundColor: "transparent", color: "var(--ink)" },
});

// App-wide Button convention: labels stay on one line and every size uses the semibold weight.
const useButtonStyles = makeStyles({
  root: { whiteSpace: "nowrap", fontWeight: tokens.fontWeightSemibold },
});
function useAppButtonStyles(state: unknown) {
  const styles = useButtonStyles();
  const button = state as ButtonState;
  button.root.className = mergeClasses(button.root.className, styles.root);
}
const customStyleHooks: FluentProviderCustomStyleHooks = { useButtonStyles_unstable: useAppButtonStyles };

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 15000, refetchOnWindowFocus: true } },
});

/** Keeps a render error from blanking the whole page; offers a reload instead. */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled render error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="boot-state" role="alert">
        <h1>Something went wrong while drawing this page.</h1>
        <p>{this.state.error.message}</p>
        <Button appearance="primary" onClick={() => window.location.reload()}>
          Reload
        </Button>
      </main>
    );
  }
}

function Root() {
  const styles = useProviderStyles();
  return (
    <FluentProvider theme={theme} className={styles.root} customStyleHooks_unstable={customStyleHooks}>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </ErrorBoundary>
    </FluentProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <RendererProvider renderer={renderer} targetDocument={document}>
      <Root />
    </RendererProvider>
  </React.StrictMode>,
);
