import { lazy, StrictMode, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import "@fontsource/atkinson-hyperlegible/latin-400.css";
import "@fontsource/atkinson-hyperlegible/latin-700.css";
import "@fontsource/ibm-plex-sans-condensed/latin-600.css";
import App from "./App";
import { LocaleContext } from "./lib/i18n";
import { detectBackendVersion } from "./v2/backend-version";
import { PageError, PageLoading } from "./v2/page-state";
import type { Locale } from "./lib/api";
import "./styles.css";
import { ThemeProvider } from "./lib/theme";
const V2Shell = lazy(() => import("./v2/shell"));

const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: 10000,
      refetchOnWindowFocus: true,
      gcTime: 60000,
    },
    mutations: { retry: false, gcTime: 0 },
  },
});
function Application() {
  const [backend, setBackend] = useState<"pending" | "v1" | "v2" | "error">(
    "pending",
  );
  const [attempt, setAttempt] = useState(0);
  // Session and portfolio changes clear the query cache. The startup decision
  // must survive those clears without remounting the active shell.
  useEffect(() => {
    const controller = new AbortController();
    void detectBackendVersion(controller.signal).then(
      (version) => {
        if (!controller.signal.aborted) setBackend(version);
      },
      () => {
        if (!controller.signal.aborted) setBackend("error");
      },
    );
    return () => controller.abort();
  }, [attempt]);
  const loading = (
    <main className="workbench">
      <PageLoading />
    </main>
  );
  if (backend === "pending") return loading;
  if (backend === "error") {
    return (
      <main className="workbench">
        <PageError
          onRetry={() => {
            setBackend("pending");
            setAttempt((count) => count + 1);
          }}
        />
      </main>
    );
  }
  return backend === "v2" ? (
    <Suspense fallback={loading}>
      <V2Shell />
    </Suspense>
  ) : (
    <App />
  );
}

function Root() {
  const [locale, setLocale] = useState<Locale>("en-CA");
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <QueryClientProvider client={client}>
        <BrowserRouter>
          <Application />
        </BrowserRouter>
      </QueryClientProvider>
    </LocaleContext.Provider>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <Root />
    </ThemeProvider>
  </StrictMode>,
);
