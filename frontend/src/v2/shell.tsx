import { useEffect, useRef, useState, type MouseEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Bitcoin,
  BookOpen,
  ChartNoAxesCombined,
  House,
  Landmark,
  Layers,
  Menu,
  Plug,
  Settings,
  Upload,
  UserRound,
} from "lucide-react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { Button } from "../components/ui/button";
import type { Locale } from "../lib/api";
import { catalogs, LocaleContext, useI18n, type Message } from "../lib/i18n";
import { PageEmpty } from "./page-state";
import "./shell.css";

const destinations = [
  { path: "/app", label: "wlP0011a.home", Icon: House },
  {
    path: "/app/investments",
    label: "wlP0011a.investments",
    Icon: Landmark,
    sourceLed: true,
    child: {
      path: "/app/investments/exposures",
      label: "wlP0011a.exposures",
      Icon: Layers,
      sourceLed: true,
    },
  },
  {
    path: "/app/crypto",
    label: "wlP0011a.crypto",
    Icon: Bitcoin,
    sourceLed: true,
  },
  { path: "/app/total", label: "wlP0011a.total", Icon: ChartNoAxesCombined },
  { path: "/app/import", label: "wlP0011a.import", Icon: Upload },
  { path: "/app/sources", label: "wlP0011a.sources", Icon: Plug },
  { path: "/app/settings", label: "wlP0011a.settings", Icon: Settings },
  { path: "/app/profile", label: "wlP0011a.profile", Icon: UserRound },
] as const;

const LOCALE_KEY = "kurafolio-v2-locale";

function preferredLocale() {
  try {
    const value = localStorage.getItem(LOCALE_KEY);
    if (value && Object.hasOwn(catalogs, value)) return value as Locale;
  } catch {
    // Preference storage can be unavailable in private browsing.
  }
  return "en-CA";
}

function Language() {
  const { locale, setLocale, t } = useI18n();
  return (
    <label>
      {t("language")}
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

type NavigationHandler = (event: MouseEvent<HTMLAnchorElement>) => void;

function Navigation({ onNavigate }: { onNavigate?: NavigationHandler }) {
  const { t } = useI18n();

  function destinationLink({
    path,
    label,
    Icon,
  }: {
    path: string;
    label: Message;
    Icon: typeof House;
  }) {
    return (
      <NavLink to={path} end className="nav-item" onClick={onNavigate}>
        <Icon size={18} aria-hidden="true" />
        {t(label)}
      </NavLink>
    );
  }

  return (
    <nav aria-label={t("wlP0011a.navigation")}>
      <ul className="v2-navigation">
        {destinations.map((destination) => (
          <li key={destination.path}>
            {destinationLink(destination)}
            {"child" in destination && (
              <ul>
                <li>{destinationLink(destination.child)}</li>
              </ul>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Brand() {
  return (
    <Link to="/app" className="brand">
      <BookOpen aria-hidden="true" /> Kurafolio
    </Link>
  );
}

function ShellLayout() {
  const { t } = useI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const main = useRef<HTMLElement>(null);
  const focusDestination = useRef(false);

  function navigateFromMenu(event: MouseEvent<HTMLAnchorElement>) {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    focusDestination.current = true;
    setMenuOpen(false);
  }

  // Until WL-P0-008 provides the positions read contract, the shell has no
  // holdings to show. Source-led pages therefore always offer to enable a
  // source; the navigation keeps them reachable either way.
  function placeholder(label: Message, sourceLed: boolean) {
    return (
      <>
        <h1 tabIndex={-1}>{t(label)}</h1>
        {sourceLed ? (
          <PageEmpty
            message={t("wlP0011a.noSourceData")}
            action={
              <Button asChild>
                <Link to="/app/sources">{t("wlP0011a.enableSource")}</Link>
              </Button>
            }
          />
        ) : (
          <PageEmpty message={t("wlP0011a.placeholder")} />
        )}
      </>
    );
  }

  return (
    <div className="app-shell v2-shell">
      <a className="skip-link" href="#main">
        {t("skip")}
      </a>
      <aside className="sidebar v2-desktop-nav">
        <Brand />
        <Navigation />
        <div className="sidebar-bottom">
          <Language />
        </div>
      </aside>
      <header className="v2-mobile-bar">
        <Brand />
        <Dialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
          <Dialog.Trigger asChild>
            <Button variant="secondary">
              <Menu size={18} aria-hidden="true" />
              {t("wlP0011a.menu")}
            </Button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="dialog-overlay" />
            <Dialog.Content
              className="dialog v2-menu"
              aria-describedby={undefined}
              onCloseAutoFocus={(event) => {
                if (!focusDestination.current) return;
                focusDestination.current = false;
                const heading = main.current?.querySelector("h1");
                if (heading) {
                  event.preventDefault();
                  heading.focus();
                }
              }}
            >
              <div className="v2-menu-header">
                <Dialog.Title>{t("wlP0011a.menu")}</Dialog.Title>
                <Dialog.Close asChild>
                  <Button variant="ghost">{t("close")}</Button>
                </Dialog.Close>
              </div>
              <Navigation onNavigate={navigateFromMenu} />
              <Language />
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </header>
      <main
        ref={main}
        id="main"
        className="workbench v2-workbench"
        tabIndex={-1}
      >
        <Routes>
          <Route path="/" element={<Navigate replace to="/app" />} />
          {destinations.flatMap((destination) =>
            ("child" in destination
              ? [destination, destination.child]
              : [destination]
            ).map((page) => (
              <Route
                key={page.path}
                path={page.path}
                element={placeholder(page.label, "sourceLed" in page)}
              />
            )),
          )}
          <Route
            path="*"
            element={
              <>
                <h1 tabIndex={-1}>{t("wlP0011a.notFound")}</h1>
                <PageEmpty
                  message={t("wlP0011a.notFoundHint")}
                  action={
                    <Button variant="secondary" asChild>
                      <Link to="/app">{t("wlP0011a.backHome")}</Link>
                    </Button>
                  }
                />
              </>
            }
          />
        </Routes>
      </main>
    </div>
  );
}

export default function V2Shell() {
  const [locale, updateLocale] = useState<Locale>(preferredLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  function setLocale(value: Locale) {
    updateLocale(value);
    try {
      localStorage.setItem(LOCALE_KEY, value);
    } catch {
      // The in-memory preference still applies for this page.
    }
  }

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <ShellLayout />
    </LocaleContext.Provider>
  );
}
