import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Bitcoin,
  BookOpen,
  ChartNoAxesCombined,
  House,
  Landmark,
  Layers,
  LogOut,
  Menu,
  Plug,
  Settings,
  Upload,
  UserRound,
} from "lucide-react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { Button } from "../components/ui/button";
import type { Locale } from "../lib/api";
import { LocaleContext, useI18n, type Message } from "../lib/i18n";
import { preferredLocale, rememberLocale } from "./locale";
import { clearTransport, mutate, read, UNAUTHORIZED_EVENT, V2Error, type Me } from "./api";
import { CredentialsPage, LoginPage, type LoginState } from "./auth-pages";
import { InvitationManager } from "./invitations";
import { Language } from "./language";
import { PageEmpty, PageError, PageLoading } from "./page-state";
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

function Account({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const { t } = useI18n();
  return (
    <div className="v2-account">
      <p className="muted">
        {t("wlP0011b.signedInAs").replace("{username}", me.user.username)}
      </p>
      <Button variant="secondary" onClick={onSignOut}>
        <LogOut size={16} aria-hidden="true" />
        {t("logout")}
      </Button>
    </div>
  );
}

function ShellLayout({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const { locale, t } = useI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const main = useRef<HTMLElement>(null);
  const focusDestination = useRef(false);
  const focusAfterNavigation = useRef(false);
  const { pathname } = useLocation();

  // Announce route changes: name the document after the page heading and,
  // after a sidebar choice, move focus to that heading.
  useEffect(() => {
    const heading = main.current?.querySelector("h1");
    if (heading?.textContent)
      document.title = `${heading.textContent} · Kurafolio`;
    if (focusAfterNavigation.current) {
      focusAfterNavigation.current = false;
      heading?.focus();
    }
  }, [pathname, locale]);

  function navigateFromSidebar(event: MouseEvent<HTMLAnchorElement>) {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    if (new URL(event.currentTarget.href).pathname === pathname)
      main.current?.querySelector("h1")?.focus();
    else focusAfterNavigation.current = true;
  }

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
        <Navigation onNavigate={navigateFromSidebar} />
        <div className="sidebar-bottom">
          <Account me={me} onSignOut={onSignOut} />
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
              <Account
                me={me}
                onSignOut={() => {
                  setMenuOpen(false);
                  onSignOut();
                }}
              />
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
                element={
                  page.path === "/app/profile" &&
                  me.user.role === "instance_admin" ? (
                    <>
                      <h1 tabIndex={-1}>{t(page.label)}</h1>
                      <InvitationManager userId={me.user.id} />
                    </>
                  ) : (
                    placeholder(page.label, "sourceLed" in page)
                  )
                }
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

type Session =
  | { state: "checking" }
  | { state: "error" }
  | { state: "signed-out" }
  | { state: "signed-in"; me: Me };

function V2Routes() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [session, setSession] = useState<Session>({ state: "checking" });
  const [attempt, setAttempt] = useState(0);
  const signedIn = session.state === "signed-in";

  useEffect(() => {
    const controller = new AbortController();
    read<Me>("/me", controller.signal).then(
      (me) => setSession({ state: "signed-in", me }),
      (error) => {
        if (controller.signal.aborted) return;
        setSession({
          state:
            error instanceof V2Error && error.status === 401
              ? "signed-out"
              : "error",
        });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  // Forget everything the previous session loaded before anything else renders.
  const forget = useCallback(async () => {
    clearTransport();
    await client.cancelQueries();
    client.clear();
  }, [client]);

  useEffect(() => {
    if (!signedIn) return;
    const ended = () => {
      void forget();
      setSession({ state: "signed-out" });
      const state: LoginState = { notice: "expired" };
      navigate("/login", { replace: true, state });
    };
    window.addEventListener(UNAUTHORIZED_EVENT, ended);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, ended);
  }, [signedIn, forget, navigate]);

  // Keep an active session alive, at most once a minute.
  useEffect(() => {
    if (!signedIn) return;
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
  }, [signedIn]);

  async function endSession(): Promise<boolean> {
    let confirmed = true;
    try {
      await mutate("/auth/logout");
    } catch (error) {
      // A session the server already ended needs no further sign-out.
      confirmed = error instanceof V2Error && error.status === 401;
    }
    await forget();
    return confirmed;
  }

  // Change the session and the route in one batch, so the catch-all route
  // never redirects to sign-in without the notice.
  async function signOut() {
    const confirmed = await endSession();
    const state: LoginState = {
      notice: confirmed ? "signedOut" : "signOutFailed",
    };
    setSession({ state: "signed-out" });
    navigate("/login", { replace: true, state });
  }

  async function signOutHere() {
    await endSession();
    setSession({ state: "signed-out" });
  }

  async function signIn(me: Me) {
    await forget();
    setSession({ state: "signed-in", me });
    navigate("/app", { replace: true });
  }

  if (session.state === "checking")
    return (
      <main className="workbench">
        <PageLoading />
      </main>
    );
  if (session.state === "error")
    return (
      <main className="workbench">
        <PageError
          onRetry={() => {
            setSession({ state: "checking" });
            setAttempt((count) => count + 1);
          }}
        />
      </main>
    );
  const me = session.state === "signed-in" ? session.me : null;
  return (
    <Routes>
      <Route
        path="/login"
        element={
          me ? (
            <Navigate replace to="/app" />
          ) : (
            <LoginPage onSignedIn={signIn} onRetrySignOut={signOut} />
          )
        }
      />
      <Route
        path="/setup"
        element={
          <CredentialsPage
            kind="setup"
            me={me}
            onSignOut={signOutHere}
          />
        }
      />
      <Route
        path="/register"
        element={
          <CredentialsPage
            kind="register"
            me={me}
            onSignOut={signOutHere}
          />
        }
      />
      <Route
        path="*"
        element={
          me ? (
            <ShellLayout key={me.user.id} me={me} onSignOut={signOut} />
          ) : (
            <Navigate replace to="/login" />
          )
        }
      />
    </Routes>
  );
}

export default function V2Shell() {
  const [locale, updateLocale] = useState<Locale>(preferredLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  function setLocale(value: Locale) {
    updateLocale(value);
    rememberLocale(value);
  }

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <V2Routes />
    </LocaleContext.Provider>
  );
}
