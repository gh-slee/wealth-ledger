import { useEffect, useState, type FormEvent } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  ChartNoAxesCombined,
  CircleDollarSign,
  FileDown,
  History as HistoryIcon,
  Landmark,
  Layers,
  LogOut,
  Settings as SettingsIcon,
  Upload,
} from "lucide-react";
import {
  ApiError,
  clearTransport,
  download,
  mutate,
  read,
  scope,
  type Currency,
  type Locale,
  type Models,
  type Report,
} from "./lib/api";
import { useI18n } from "./lib/i18n";
import { date } from "./lib/format";
import { Button } from "./components/ui/button";
import {
  Bitcoin,
  Evidence,
  Exposure,
  History,
  Holdings,
  Overview,
} from "./components/analysis";
import { Imports } from "./components/imports";
const navigation = [
  ["overview", ChartNoAxesCombined],
  ["holdings", Landmark],
  ["exposure", Layers],
  ["history", HistoryIcon],
  ["bitcoin", CircleDollarSign],
  ["imports", Upload],
  ["reports", FileDown],
  ["settings", SettingsIcon],
] as const;
function Language() {
  const { locale, setLocale, t } = useI18n();
  return (
    <label className="language">
      <span className="sr-only">{t("language")}</span>
      <select
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        <option value="en-CA">English</option>
        <option value="zh-TW">繁體中文</option>
        <option value="zh-CN">简体中文</option>
      </select>
    </label>
  );
}
export default function App() {
  const { t, error } = useI18n();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [auth, setAuth] = useState<"checking" | "signed-in" | "signed-out">(
      "checking",
    ),
    [expired, setExpired] = useState(false),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  useEffect(() => {
    let mounted = true;
    read<Models["SessionView"]>("/auth/session")
      .then(() => {
        if (mounted) setAuth("signed-in");
      })
      .catch(() => {
        if (mounted) setAuth("signed-out");
      });
    return () => {
      mounted = false;
    };
  }, []);
  useEffect(() => {
    const ended = () => {
      setAuth("signed-out");
      setExpired(true);
      void client.cancelQueries();
      client.clear();
      navigate("/login", { replace: true });
    };
    window.addEventListener("ledger:unauthorized", ended);
    return () => window.removeEventListener("ledger:unauthorized", ended);
  }, [client, navigate]);
  useEffect(() => {
    if (auth !== "signed-in") return;
    let last = 0;
    const activity = (event: Event) => {
      if (!event.isTrusted || Date.now() - last < 60000) return;
      last = Date.now();
      void mutate("/auth/activity").catch(() => {});
    };
    window.addEventListener("pointerdown", activity);
    window.addEventListener("keydown", activity);
    return () => {
      window.removeEventListener("pointerdown", activity);
      window.removeEventListener("keydown", activity);
    };
  }, [auth]);
  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy(true);
    setFailure("");
    try {
      await mutate("/auth/login", {
        username: values.get("username"),
        password: values.get("password"),
      });
      form.reset();
      client.clear();
      setAuth("signed-in");
      setExpired(false);
      navigate("/app", { replace: true });
    } catch (reason) {
      setFailure(reason instanceof ApiError ? reason.code : "request_failed");
    } finally {
      form.reset();
      setBusy(false);
    }
  }
  async function logout() {
    setBusy(true);
    setFailure("");
    setAuth("signed-out");
    clearTransport();
    await client.cancelQueries();
    client.clear();
    navigate("/login", { replace: true });
    try {
      await mutate("/auth/logout");
    } catch (reason) {
      setFailure(reason instanceof ApiError ? reason.code : "logout_failed");
    } finally {
      clearTransport();
      setBusy(false);
    }
  }
  if (auth === "checking")
    return (
      <main className="loading-screen" aria-busy="true">
        {t("loading")}
      </main>
    );
  if (auth !== "signed-in")
    return (
      <div className="login-page">
        <header>
          <Link to="/login" className="brand">
            <BookOpen aria-hidden="true" /> Wealth Ledger
          </Link>
          <Language />
        </header>
        <main className="login-layout">
          <div className="login-intro">
            <span className="eyebrow">LOCAL-FIRST / SELF-HOSTED</span>
            <h1>{t("tagline")}</h1>
            <p>CSV → SQLite → ODS · Markdown · PDF</p>
            <div className="ledger-decoration" aria-hidden="true">
              <span>01 / OBSERVE</span>
              <span>02 / REVIEW</span>
              <span>03 / PRESERVE</span>
            </div>
          </div>
          <section className="login-panel">
            <h2>{t("login")}</h2>
            <p className="muted">{t("loginHint")}</p>
            {expired && <p role="status">{t("expired")}</p>}
            {failure && (
              <p role="alert" className="error">
                {error(failure)} <code>{failure}</code>
              </p>
            )}
            {failure === "logout_failed" && (
              <Button variant="secondary" disabled={busy} onClick={logout}>
                {t("logout")}
              </Button>
            )}
            <form onSubmit={login}>
              <label>
                {t("username")}
                <input
                  name="username"
                  autoComplete="username"
                  maxLength={64}
                  required
                  disabled={busy}
                />
              </label>
              <label>
                {t("password")}
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  maxLength={256}
                  required
                  disabled={busy}
                />
              </label>
              <Button type="submit" disabled={busy}>
                {busy ? t("loading") : t("login")}
                <ArrowUpRight aria-hidden="true" size={17} />
              </Button>
            </form>
          </section>
        </main>
      </div>
    );
  return (
    <Routes>
      <Route
        path="/app/:portfolio/:page?"
        element={<Workspace logout={logout} />}
      />
      <Route path="*" element={<Workspace logout={logout} />} />
    </Routes>
  );
}
function Workspace({ logout }: { logout: () => Promise<void> }) {
  const { portfolio, page = "overview" } = useParams();
  return (
    <PortfolioWorkspace
      key={portfolio ?? "none"}
      portfolio={portfolio}
      page={page}
      logout={logout}
    />
  );
}
function PortfolioWorkspace({
  portfolio,
  page,
  logout,
}: {
  portfolio?: string;
  page: string;
  logout: () => Promise<void>;
}) {
  const { t, locale, error } = useI18n();
  const client = useQueryClient(),
    navigate = useNavigate();
  const [currency, setCurrency] = useState<Currency>("CAD"),
    [selected, setSelected] = useState(""),
    [failure, setFailure] = useState(""),
    [creating, setCreating] = useState(false);
  const portfolios = useQuery({
    queryKey: ["portfolios"],
    queryFn: ({ signal }) =>
      read<Models["PortfolioList"]>("/portfolios", signal),
  });
  const reports = useInfiniteQuery({
    queryKey: [portfolio, "reports"],
    enabled: !!portfolio,
    initialPageParam: "",
    queryFn: ({ pageParam, signal }) =>
      read<Models["ReportList"]>(
        scope(portfolio!) +
          "/reports" +
          (pageParam ? `?cursor=${pageParam}` : ""),
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: 15000,
  });
  const editions = reports.data?.pages.flatMap((value) => value.reports) ?? [];
  const edition = selected || editions[0]?.id;
  const report = useQuery({
    queryKey: [portfolio, "report", edition, locale],
    enabled: !!portfolio && !!edition,
    queryFn: ({ signal }) =>
      read<Report>(
        scope(portfolio!) + `/reports/${edition}?locale=${locale}`,
        signal,
      ),
    staleTime: Infinity,
  });
  useEffect(() => {
    if (!portfolio && portfolios.data?.portfolios.length)
      navigate(`/app/${portfolios.data.portfolios[0].id}/overview`, {
        replace: true,
      });
  }, [portfolio, portfolios.data, navigate]);
  async function switchPortfolio(id: string) {
    clearTransport();
    await client.cancelQueries();
    client.clear();
    navigate(`/app/${id}/overview`, { replace: true });
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = new FormData(event.currentTarget).get("name");
    setFailure("");
    setCreating(true);
    try {
      const value = await mutate<Models["PortfolioView"]>("/portfolios", {
        name,
      });
      await switchPortfolio(value.id);
    } catch (reason) {
      if (reason instanceof ApiError) setFailure(reason.code);
    } finally {
      setCreating(false);
    }
  }
  const navPage = navigation.find(([key]) => key === page)?.[0] ?? "overview";
  const needsReport = !["imports", "reports", "settings"].includes(navPage);
  const data = report.data;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        {t("skip")}
      </a>
      <aside className="sidebar">
        <Link to="/app" className="brand">
          <BookOpen aria-hidden="true" /> Wealth Ledger
        </Link>
        <p className="sidebar-caption">{t("tagline")}</p>
        <label>
          {t("portfolio")}
          <select
            value={portfolio ?? ""}
            onChange={(event) => switchPortfolio(event.target.value)}
          >
            <option value="" disabled>
              —
            </option>
            {portfolios.data?.portfolios.map((value) => (
              <option key={value.id} value={value.id}>
                {value.name}
              </option>
            ))}
          </select>
        </label>
        <nav aria-label={t("nav")}>
          {navigation.map(([key, Icon]) => (
            <NavLink
              key={key}
              to={portfolio ? `/app/${portfolio}/${key}` : "/app"}
              className={
                portfolio && navPage === key ? "nav-item active" : "nav-item"
              }
            >
              <Icon size={18} aria-hidden="true" />
              {t(key)}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <details>
            <summary>{t("newPortfolio")}</summary>
            <form onSubmit={create}>
              <label>
                {t("name")}
                <input name="name" maxLength={80} required />
              </label>
              <Button type="submit" variant="secondary" disabled={creating}>
                {t("create")}
              </Button>
            </form>
          </details>
          <Language />
          <Button variant="ghost" onClick={logout}>
            <LogOut size={16} aria-hidden="true" />
            {t("logout")}
          </Button>
        </div>
      </aside>
      <main id="main" className="workbench" tabIndex={-1}>
        <header className="page-heading">
          <div>
            <span className="eyebrow">
              {portfolios.data?.portfolios.find(
                (value) => value.id === portfolio,
              )?.name ?? t("app")}
            </span>
            <h1>{t(navPage)}</h1>
          </div>
          <div className="toolbar">
            {["overview", "holdings", "history"].includes(navPage) && (
              <label>
                {t("currency")}
                <select
                  value={currency}
                  onChange={(event) =>
                    setCurrency(event.target.value as Currency)
                  }
                >
                  <option>CAD</option>
                  <option>USD</option>
                  <option>TWD</option>
                </select>
              </label>
            )}
            {needsReport && editions.length > 0 && (
              <label>
                {t("edition")}
                <select
                  value={edition}
                  onChange={(event) => setSelected(event.target.value)}
                >
                  {editions.map((value) => (
                    <option key={value.id} value={value.id}>
                      {date(value.valuation_as_of, locale)} ·{" "}
                      {date(
                        new Date(value.published_at * 1000).toISOString(),
                        locale,
                      )}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </header>
        <p className="time-note">{t("timeZone")}</p>
        {failure && (
          <p role="alert" className="error">
            {error(failure)}
          </p>
        )}
        {portfolios.isError || reports.isError || report.isError ? (
          <section className="panel error" role="alert">
            <p>
              {error(
                (
                  [portfolios.error, reports.error, report.error].find(
                    Boolean,
                  ) as ApiError
                )?.code ?? "request_failed",
              )}
            </p>
            <Button
              variant="secondary"
              onClick={() => client.invalidateQueries()}
            >
              {t("retry")}
            </Button>
          </section>
        ) : !portfolio ? (
          <section className="panel">
            <h2>{t("noPortfolios")}</h2>
            <form className="inline-form" onSubmit={create}>
              <label>
                {t("name")}
                <input name="name" required maxLength={80} />
              </label>
              <Button type="submit" disabled={creating}>
                {t("create")}
              </Button>
            </form>
          </section>
        ) : (
          <>
            {navPage === "imports" ? (
              <Imports portfolio={portfolio} />
            ) : navPage === "settings" ? (
              <Settings portfolio={portfolio} />
            ) : navPage === "reports" ? (
              <section className="panel">
                <h2>{t("reports")}</h2>
                {editions.length ? (
                  editions.map((value) => (
                    <article className="report-row" key={value.id}>
                      <div>
                        <h3>{date(value.valuation_as_of, locale)}</h3>
                        <small>
                          {t("published")}:{" "}
                          {date(
                            new Date(value.published_at * 1000).toISOString(),
                            locale,
                          )}
                        </small>
                      </div>
                      <div className="actions">
                        {value.artifacts.map((artifact) => (
                          <Button
                            key={artifact.id}
                            variant="secondary"
                            onClick={() =>
                              download(portfolio, artifact).catch((reason) =>
                                setFailure(
                                  reason instanceof ApiError
                                    ? reason.code
                                    : "request_failed",
                                ),
                              )
                            }
                          >
                            <FileDown size={16} aria-hidden="true" />
                            {artifact.filename}
                          </Button>
                        ))}
                      </div>
                    </article>
                  ))
                ) : (
                  <p>{t("noReportHint")}</p>
                )}
                {reports.hasNextPage && (
                  <Button
                    variant="secondary"
                    disabled={reports.isFetchingNextPage}
                    onClick={() => reports.fetchNextPage()}
                  >
                    {t("loadMore")}
                  </Button>
                )}
              </section>
            ) : data ? (
              <>
                <Evidence data={data} />
                {navPage === "overview" ? (
                  <Overview data={data} currency={currency} />
                ) : navPage === "holdings" ? (
                  <Holdings data={data} currency={currency} />
                ) : navPage === "exposure" ? (
                  <Exposure data={data} />
                ) : navPage === "history" ? (
                  <History data={data} currency={currency} />
                ) : (
                  <Bitcoin data={data} />
                )}
              </>
            ) : reports.isPending || reports.isFetching || report.isFetching ? (
              <p aria-live="polite">{t("loading")}</p>
            ) : (
              <section className="panel empty-state">
                <Upload aria-hidden="true" />
                <h2>{t("noReport")}</h2>
                <p>{t("noReportHint")}</p>
                <Button asChild>
                  <Link to={`/app/${portfolio}/imports`}>{t("preview")}</Link>
                </Button>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
function Settings({ portfolio }: { portfolio: string }) {
  const { t, error } = useI18n();
  const client = useQueryClient();
  const [failure, setFailure] = useState(""),
    [saved, setSaved] = useState(false),
    [busy, setBusy] = useState(false);
  const settings = useQuery({
    queryKey: [portfolio, "settings"],
    queryFn: ({ signal }) =>
      read<Models["ReportingSettings"]>(scope(portfolio) + "/settings", signal),
  });
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setFailure("");
    setSaved(false);
    try {
      await mutate(
        scope(portfolio) + "/settings",
        { locale: values.get("locale"), btc_cost_policy: values.get("policy") },
        "PUT",
      );
      await client.invalidateQueries({ queryKey: [portfolio, "settings"] });
      setSaved(true);
    } catch (reason) {
      if (reason instanceof ApiError) setFailure(reason.code);
    } finally {
      setBusy(false);
    }
  }
  async function password(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget,
      values = new FormData(form);
    setBusy(true);
    setFailure("");
    try {
      await mutate("/auth/password", {
        current_password: values.get("current"),
        new_password: values.get("new"),
      });
      clearTransport();
      window.dispatchEvent(new Event("ledger:unauthorized"));
    } catch (reason) {
      if (reason instanceof ApiError) setFailure(reason.code);
    } finally {
      form.reset();
      setBusy(false);
    }
  }
  return (
    <>
      {failure && (
        <p role="alert" className="error">
          {error(failure)} <code>{failure}</code>
        </p>
      )}
      {settings.data && (
        <section className="panel">
          <h2>{t("settings")}</h2>
          <form
            className="settings-form"
            key={JSON.stringify(settings.data)}
            onSubmit={save}
          >
            <label>
              {t("reportLanguage")}
              <select name="locale" defaultValue={settings.data.locale}>
                <option value="en-CA">English</option>
                <option value="zh-TW">繁體中文</option>
                <option value="zh-CN">简体中文</option>
              </select>
            </label>
            <label>
              {t("costPolicy")}
              <select
                name="policy"
                defaultValue={settings.data.btc_cost_policy}
              >
                <option value="actual_only">{t("policyActual")}</option>
                <option value="bull_average_proxy">{t("policyProxy")}</option>
              </select>
            </label>
            <p className="muted">{t("policyHint")}</p>
            <Button type="submit" disabled={busy}>
              {t("save")}
            </Button>
            {saved && <p role="status">{t("saved")}</p>}
          </form>
        </section>
      )}
      {settings.isError && <p role="alert">{t("failed")}</p>}
      <section className="panel">
        <h2>{t("passwordChange")}</h2>
        <p className="muted">{t("passwordHint")}</p>
        <form className="settings-form" onSubmit={password}>
          <label>
            {t("currentPassword")}
            <input
              name="current"
              type="password"
              autoComplete="current-password"
              required
              maxLength={256}
            />
          </label>
          <label>
            {t("newPassword")}
            <input
              name="new"
              type="password"
              autoComplete="new-password"
              minLength={14}
              maxLength={256}
              required
            />
          </label>
          <Button type="submit" disabled={busy}>
            {t("passwordChange")}
          </Button>
        </form>
      </section>
      <p className="muted">{t("maintenance")}</p>
    </>
  );
}
