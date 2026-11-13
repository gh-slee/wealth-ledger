import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type FormEvent,
  type ReactNode,
} from "react";
import { BookOpen, CircleAlert } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import { useI18n, type Message } from "../lib/i18n";
import { mutate, read, V2Error, type Me } from "./api";
import {
  linkToken,
  passwordProblem,
  usernameProblem,
  type PasswordProblem,
  type UsernameProblem,
} from "./identity";
import { Language } from "./language";
import "./identity.css";

export type LoginNotice =
  | "signedOut"
  | "signOutFailed"
  | "expired"
  | "setupDone"
  | "registered";
export type LoginState = { notice?: LoginNotice; username?: string };

const notices: Record<LoginNotice, Message> = {
  signedOut: "wlP0011b.notice.signedOut",
  signOutFailed: "wlP0011b.notice.signOutFailed",
  expired: "expired",
  setupDone: "wlP0011b.notice.setupDone",
  registered: "wlP0011b.notice.registered",
};

// Failures share these messages. Error codes stay out of the page.
function failureMessage(error: unknown): Message {
  if (!(error instanceof V2Error)) return "wlP0011b.failed";
  switch (error.code) {
    case "rate_limited":
    case "authentication_busy":
      return "wlP0011b.rateLimited";
    case "anonymous_session_required":
      return "wlP0011b.alreadySignedIn";
    case "invalid_input":
      return "wlP0011b.checkFields";
    default:
      return "wlP0011b.failed";
  }
}

function AuthLayout({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  useEffect(() => {
    document.title = `${title} · Kurafolio`;
  }, [title]);
  return (
    <div className="login-page v2-auth">
      <header>
        <span className="brand">
          <BookOpen aria-hidden="true" /> Kurafolio
        </span>
        <Language />
      </header>
      <main id="main" className="v2-auth-main">
        <section className="login-panel">
          <h1>{title}</h1>
          {children}
        </section>
      </main>
    </div>
  );
}

type FieldProps = {
  id: string;
  label: string;
  hint?: string;
  error?: string;
} & ComponentProps<"input">;

function Field({ id, label, hint, error, ...input }: FieldProps) {
  const described = [hint && `${id}-hint`, error && `${id}-error`]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="v2-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={described || undefined}
        {...input}
      />
      {hint && (
        <small id={`${id}-hint`} className="muted">
          {hint}
        </small>
      )}
      {error && (
        <p id={`${id}-error`} className="v2-field-error">
          <CircleAlert size={16} aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}

function Alert({ message }: { message: string }) {
  return (
    <p role="alert" className="error v2-auth-alert">
      {message}
    </p>
  );
}

export function LoginPage({
  onSignedIn,
  onRetrySignOut,
}: {
  onSignedIn: (me: Me) => void;
  onRetrySignOut: () => Promise<void>;
}) {
  const { t } = useI18n();
  const location = useLocation();
  const state = (location.state ?? {}) as LoginState;
  const [username, setUsername] = useState(state.username ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Message | null>(null);
  const passwordInput = useRef<HTMLInputElement>(null);
  const notice = state.notice && notices[state.notice];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username || !password) {
      setFailure("wlP0011b.login.required");
      return;
    }
    setBusy(true);
    setFailure(null);
    try {
      await mutate("/auth/login", { username, password });
      setPassword("");
      onSignedIn(await read<Me>("/me"));
    } catch (error) {
      setPassword("");
      setFailure(
        error instanceof V2Error &&
          ["invalid_credentials", "invalid_input"].includes(error.code)
          ? "error.invalid_credentials"
          : failureMessage(error),
      );
      setBusy(false);
      requestAnimationFrame(() => passwordInput.current?.focus());
    }
  }

  return (
    <AuthLayout title={t("login")}>
      {notice && !failure && <p role="status">{t(notice)}</p>}
      {state.notice === "signOutFailed" && (
        <Button
          variant="secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            await onRetrySignOut();
            setBusy(false);
          }}
        >
          {t("logout")}
        </Button>
      )}
      {failure && <Alert message={t(failure)} />}
      <form onSubmit={submit} noValidate>
        <Field
          id="login-username"
          label={t("username")}
          name="username"
          autoComplete="username"
          maxLength={64}
          required
          disabled={busy}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <Field
          ref={passwordInput}
          id="login-password"
          label={t("password")}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={busy}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <Button type="submit" disabled={busy}>
          {busy ? t("loading") : t("login")}
        </Button>
      </form>
      <p className="muted v2-auth-note">{t("wlP0011b.login.forgot")}</p>
    </AuthLayout>
  );
}

type Kind = "setup" | "register";
type Blocked =
  | "missing"
  | "setupRejected"
  | "setupClosed"
  | "setupRequired"
  | "signedIn";

const blockedMessages: Record<Kind, Record<Blocked, Message>> = {
  setup: {
    missing: "wlP0011b.setup.missing",
    setupRejected: "wlP0011b.setup.rejected",
    setupClosed: "wlP0011b.setup.closed",
    setupRequired: "wlP0011b.failed",
    signedIn: "wlP0011b.signedInLink",
  },
  register: {
    missing: "wlP0011b.register.missing",
    setupRejected: "wlP0011b.failed",
    setupClosed: "wlP0011b.failed",
    setupRequired: "wlP0011b.register.setupRequired",
    signedIn: "wlP0011b.signedInLink",
  },
};

const usernameMessages: Record<UsernameProblem, Message> = {
  required: "wlP0011b.username.required",
  invalid: "wlP0011b.username.invalid",
};
const passwordMessages: Record<PasswordProblem, Message> = {
  short: "wlP0011b.password.short",
  long: "wlP0011b.password.long",
  invalid: "wlP0011b.password.invalid",
  mismatch: "wlP0011b.password.mismatch",
};

type Problems = {
  username?: Message;
  newPassword?: Message;
  confirmation?: Message;
};

/**
 * First setup and invitation registration share one form. The link token is
 * read once, then removed from the address bar so it does not stay in the
 * browser history.
 */
export function CredentialsPage({
  kind,
  me,
  onSignOut,
}: {
  kind: Kind;
  me: Me | null;
  onSignOut: () => Promise<void>;
}) {
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [token] = useState(() => linkToken(location.search));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [problems, setProblems] = useState<Problems>({});
  const [blocked, setBlocked] = useState<Blocked | null>(null);
  const [failure, setFailure] = useState<Message | null>(null);
  const [busy, setBusy] = useState(false);
  const fields = {
    username: useRef<HTMLInputElement>(null),
    newPassword: useRef<HTMLInputElement>(null),
    confirmation: useRef<HTMLInputElement>(null),
  };

  useEffect(() => {
    if (location.search)
      navigate(location.pathname, { replace: true, state: location.state });
  }, [location.pathname, location.search, location.state, navigate]);

  const title = t(
    kind === "setup" ? "wlP0011b.setup.title" : "wlP0011b.register.title",
  );
  const shown: Blocked | null = !token
    ? "missing"
    : me
      ? "signedIn"
      : blocked;

  if (shown) {
    const message = t(blockedMessages[kind][shown]).replace(
      "{username}",
      me?.user.username ?? "",
    );
    return (
      <AuthLayout title={title}>
        <p role={shown === "missing" ? undefined : "alert"}>{message}</p>
        <div className="v2-auth-actions">
          {shown === "signedIn" ? (
            <>
              <Button
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  await onSignOut();
                  setBusy(false);
                }}
              >
                {t("logout")}
              </Button>
              <Button variant="secondary" asChild>
                <Link to="/app">{t("wlP0011a.backHome")}</Link>
              </Button>
            </>
          ) : (
            <Button variant="secondary" asChild>
              <Link to="/login">{t("wlP0011b.goToSignIn")}</Link>
            </Button>
          )}
        </div>
      </AuthLayout>
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const usernameIssue = usernameProblem(username);
    const passwordIssue = passwordProblem(password);
    const next: Problems = {
      username: usernameIssue ? usernameMessages[usernameIssue] : undefined,
      newPassword: passwordIssue ? passwordMessages[passwordIssue] : undefined,
      confirmation:
        !passwordIssue && passwordProblem(password, confirmation) === "mismatch"
          ? passwordMessages.mismatch
          : undefined,
    };
    setProblems(next);
    setFailure(null);
    const first = (["username", "newPassword", "confirmation"] as const).find(
      (field) => next[field],
    );
    if (first) {
      fields[first].current?.focus();
      return;
    }
    setBusy(true);
    try {
      await mutate(kind === "setup" ? "/auth/setup" : "/auth/register", {
        [kind === "setup" ? "setup_token" : "invite_token"]: token,
        username,
        password,
      });
      setPassword("");
      setConfirmation("");
      const state: LoginState = {
        notice: kind === "setup" ? "setupDone" : "registered",
        username,
      };
      navigate("/login", { replace: true, state });
    } catch (error) {
      setBusy(false);
      const code = error instanceof V2Error ? error.code : "";
      if (code === "setup_rejected") setBlocked("setupRejected");
      else if (code === "setup_closed") setBlocked("setupClosed");
      else if (code === "setup_required") setBlocked("setupRequired");
      else if (code === "registration_rejected")
        setFailure("wlP0011b.register.rejected");
      else setFailure(failureMessage(error));
    }
  }

  return (
    <AuthLayout title={title}>
      <p className="muted">
        {t(
          kind === "setup" ? "wlP0011b.setup.intro" : "wlP0011b.register.intro",
        )}
      </p>
      {failure && <Alert message={t(failure)} />}
      <form onSubmit={submit} noValidate>
        <Field
          ref={fields.username}
          id={`${kind}-username`}
          label={t("username")}
          hint={t("wlP0011b.username.hint")}
          error={problems.username && t(problems.username)}
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          maxLength={64}
          required
          disabled={busy}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <Field
          ref={fields.newPassword}
          id={`${kind}-password`}
          label={t("password")}
          hint={t("wlP0011b.password.hint")}
          error={problems.newPassword && t(problems.newPassword)}
          name="password"
          type="password"
          autoComplete="new-password"
          required
          disabled={busy}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <Field
          ref={fields.confirmation}
          id={`${kind}-confirmation`}
          label={t("wlP0011b.password.confirm")}
          error={problems.confirmation && t(problems.confirmation)}
          name="confirmation"
          type="password"
          autoComplete="new-password"
          required
          disabled={busy}
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
        />
        <Button type="submit" disabled={busy}>
          {busy
            ? t("loading")
            : t(
                kind === "setup"
                  ? "wlP0011b.setup.submit"
                  : "wlP0011b.register.submit",
              )}
        </Button>
      </form>
    </AuthLayout>
  );
}
