import {
  useId,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type Ref,
} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { ExternalLink, FileUp, PlugZap } from "lucide-react";
import { Button } from "../components/ui/button";
import { useI18n, type Message } from "../lib/i18n";
import { mutate, read, V2Error } from "./api";
import { requestId } from "./identity";
import { PageEmpty, PageError, PageLoading } from "./page-state";
import {
  capabilityView,
  connectionLabel,
  failureMessage,
  pagePath,
  retryable,
  STALE_CODES,
  textProblem,
  type Capability,
  type CatalogItem,
  type Listing,
  type SourceCatalogPage,
  type SourceConnection,
  type SourceConnectionPage,
  type SourceRealm,
} from "./sources-model";
import "./identity.css";
import "./sources.css";

export const CONTRIBUTION_GUIDE =
  "https://github.com/gh-slee/kurafolio/blob/main/docs/parser-sdk.md";
const LABEL_MAXIMUM = 100;
const ALIAS_MAXIMUM = 160;

// One user action becomes one request with one operation ID. A retry after
// a lost response resends this exact object, so the server can recognise it.
type Action = {
  path: string;
  method: "POST" | "PUT";
  body: Record<string, unknown> & { operation_id: string };
  done: Message;
};

type Notice =
  | { kind: "done"; message: Message }
  | { kind: "stale" }
  | { kind: "failed"; message: Message; retry: Action | null };

async function readAll<T extends SourceCatalogPage | SourceConnectionPage>(
  base: "/sources" | "/source-connections",
  signal: AbortSignal,
): Promise<Listing<T["items"][number]>> {
  const items: T["items"][number][] = [];
  let page: T | null = null;
  do {
    page = await read<T>(pagePath(base, page), signal);
    items.push(...page.items);
  } while (page.next_after);
  return { items, realm: page.realm };
}

function common(revision: string, realm: SourceRealm) {
  return {
    operation_id: requestId(),
    expected_revision: revision,
    expected_realm: realm,
  };
}

/** Reject anything but a plain web link from catalog metadata. */
function safeLink(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.href
      : null;
  } catch {
    return null;
  }
}

function fill(text: string, values: Record<string, string>) {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replaceAll(`{${key}}`, value),
    text,
  );
}

function StatusTag({
  tone,
  children,
}: {
  tone: "good" | "review" | "neutral";
  children: ReactNode;
}) {
  return (
    <span className={tone === "neutral" ? "status" : `status status-${tone}`}>
      {children}
    </span>
  );
}

type Confirmation = {
  title: string;
  body: string;
  confirm: string;
  destructive?: boolean;
  action: Action;
};

/**
 * The Parser Plugin Store: official sources the operator installed, with a
 * per-user switch for each file capability and that source's connections.
 * Enabling a source or adding a connection imports nothing.
 */
export function SourceStore({ userId }: { userId: string }) {
  const { t } = useI18n();
  const client = useQueryClient();
  const catalogKey = ["v2", userId, "sources", "catalog"];
  const connectionsKey = ["v2", userId, "sources", "connections"];
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  const catalog = useQuery({
    queryKey: catalogKey,
    queryFn: ({ signal }) => readAll<SourceCatalogPage>("/sources", signal),
  });
  const connections = useQuery({
    queryKey: connectionsKey,
    queryFn: ({ signal }) =>
      readAll<SourceConnectionPage>("/source-connections", signal),
  });

  const run = useMutation({
    mutationFn: (action: Action) =>
      mutate(action.path, action.body, action.method),
    onMutate: () => setNotice(null),
    onSuccess: (_value, action) => {
      setConfirmation(null);
      setNotice({ kind: "done", message: action.done });
    },
    onError: (error, action) => {
      setConfirmation(null);
      if (error instanceof DOMException && error.name === "AbortError") return;
      const code = error instanceof V2Error ? error.code : "";
      if (STALE_CODES.has(code)) {
        setNotice({ kind: "stale" });
        return;
      }
      const again = retryable(error);
      setNotice({
        kind: "failed",
        message: again ? "wlP0011c.error.uncertain" : failureMessage(code),
        retry: again ? action : null,
      });
    },
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: catalogKey }),
        client.invalidateQueries({ queryKey: connectionsKey }),
      ]),
  });

  function ask(value: Confirmation) {
    opener.current = document.activeElement as HTMLElement | null;
    setConfirmation(value);
  }

  if (catalog.isPending) return <PageLoading />;
  if (catalog.isError)
    return (
      <PageError
        message={t("wlP0011c.loadFailed")}
        onRetry={() => void catalog.refetch()}
      />
    );

  const realm = catalog.data.realm;
  const sources = catalog.data.items;

  return (
    <div className="v2-sources">
      <p className="v2-sources-intro">{t("wlP0011c.intro")}</p>
      <div aria-live="polite" className="v2-sources-notice">
        {notice?.kind === "done" && (
          <p role="status" className="v2-sources-done">
            {t(notice.message)}
          </p>
        )}
      </div>
      {notice && notice.kind !== "done" && (
        <div role="alert" className="error v2-sources-alert">
          <p>
            {t(notice.kind === "stale" ? "wlP0011c.stale" : notice.message)}
          </p>
          {notice.kind === "failed" && notice.retry && (
            <Button
              variant="secondary"
              disabled={run.isPending}
              onClick={() => notice.retry && run.mutate(notice.retry)}
            >
              {t("retry")}
            </Button>
          )}
        </div>
      )}
      {sources.length === 0 ? (
        <PageEmpty message={t("wlP0011c.empty")} />
      ) : (
        <ul className="v2-source-list">
          {sources.map((source) => (
            <SourceRow
              key={source.plugin_id}
              source={source}
              realm={realm}
              busy={run.isPending}
              connections={connections}
              onRun={(action) => run.mutate(action)}
              onAsk={ask}
            />
          ))}
        </ul>
      )}
      <aside className="v2-sources-contribute" aria-labelledby="contribute">
        <h2 id="contribute">{t("wlP0011c.contributeTitle")}</h2>
        <p>{t("wlP0011c.contributeBody")}</p>
        <a href={CONTRIBUTION_GUIDE} target="_blank" rel="noreferrer">
          {t("wlP0011c.contributeLink")}
          <ExternalLink size={14} aria-hidden="true" />
          <span className="sr-only">{t("wlP0011c.newTab")}</span>
        </a>
      </aside>
      <Dialog.Root
        open={confirmation !== null}
        onOpenChange={(open) => {
          if (!open && !run.isPending) setConfirmation(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content
            className="dialog"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              const origin = opener.current;
              opener.current = null;
              if (origin?.isConnected) origin.focus();
              else document.querySelector<HTMLElement>("main h1")?.focus();
            }}
          >
            <Dialog.Title>{confirmation?.title}</Dialog.Title>
            <Dialog.Description>{confirmation?.body}</Dialog.Description>
            <div className="v2-auth-actions">
              <Dialog.Close asChild>
                <Button variant="secondary" disabled={run.isPending}>
                  {t("wlP0011c.cancel")}
                </Button>
              </Dialog.Close>
              <Button
                variant={confirmation?.destructive ? "destructive" : "default"}
                disabled={run.isPending}
                onClick={() => confirmation && run.mutate(confirmation.action)}
              >
                {run.isPending ? t("loading") : confirmation?.confirm}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

type RowProps = {
  source: CatalogItem;
  realm: SourceRealm;
  busy: boolean;
  connections: UseQueryResult<Listing<SourceConnection>>;
  onRun: (action: Action) => void;
  onAsk: (confirmation: Confirmation) => void;
};

function SourceRow({
  source,
  realm,
  busy,
  connections,
  onRun,
  onAsk,
}: RowProps) {
  const { t } = useI18n();
  const heading = useId();
  const docs = safeLink(source.docs_url);
  const file = source.capabilities.find(
    (item) => item.capability === "FILE_IMPORT",
  );
  const own =
    connections.data?.items.filter(
      (item) => item.plugin_id === source.plugin_id,
    ) ?? [];
  const showConnections =
    file !== undefined && (file.status === "ENABLED" || own.length > 0);

  return (
    <li className="v2-source" aria-labelledby={heading}>
      <header className="v2-source-header">
        <h2 id={heading}>{source.display_name}</h2>
        <p className="muted">
          {fill(t("wlP0011c.publisher"), { publisher: source.publisher_label })}
          {docs && (
            <>
              {" · "}
              <a href={docs} target="_blank" rel="noreferrer">
                {t("wlP0011c.docs")}
                <span className="sr-only">
                  {" "}
                  {fill(t("wlP0011c.docsFor"), { name: source.display_name })}
                  {t("wlP0011c.newTab")}
                </span>
              </a>
            </>
          )}
        </p>
      </header>
      <ul className="v2-capabilities">
        {source.capabilities.map((capability) => (
          <CapabilityRow
            key={capability.capability}
            source={source}
            capability={capability}
            realm={realm}
            busy={busy}
            onRun={onRun}
            onAsk={onAsk}
          />
        ))}
      </ul>
      {showConnections && file && (
        <Connections
          source={source}
          file={file}
          items={own}
          state={connections}
          busy={busy}
          onRun={onRun}
          onAsk={onAsk}
        />
      )}
    </li>
  );
}

function CapabilityRow({
  source,
  capability,
  realm,
  busy,
  onRun,
  onAsk,
}: {
  source: CatalogItem;
  capability: Capability;
  realm: SourceRealm;
  busy: boolean;
  onRun: (action: Action) => void;
  onAsk: (confirmation: Confirmation) => void;
}) {
  const { t } = useI18n();
  const view = capabilityView(capability);
  const name = t(
    capability.capability === "FILE_IMPORT" ? "wlP0011c.file" : "wlP0011c.api",
  );
  const path = `/sources/${encodeURIComponent(source.plugin_id)}/capabilities/${capability.capability}`;
  const values = {
    name: source.display_name,
    version: view.confirmVersion ?? "",
  };

  function enable(done: Message): Action {
    return {
      path,
      method: "PUT",
      done,
      body: {
        ...common(capability.enablement.revision, realm),
        enabled: true,
        installation_id: capability.active_installation_id,
      },
    };
  }

  function disable() {
    onAsk({
      title: fill(t("wlP0011c.disableTitle"), values),
      body: fill(t("wlP0011c.disableBody"), values),
      confirm: t("wlP0011c.disableConfirm"),
      destructive: true,
      action: {
        path,
        method: "PUT",
        done: "wlP0011c.disabledDone",
        body: {
          ...common(capability.enablement.revision, realm),
          enabled: false,
          installation_id: null,
        },
      },
    });
  }

  const on = capability.status === "ENABLED";
  return (
    <li className="v2-capability">
      <div className="v2-capability-name">
        {capability.capability === "FILE_IMPORT" ? (
          <FileUp size={18} aria-hidden="true" />
        ) : (
          <PlugZap size={18} aria-hidden="true" />
        )}
        <h3>{name}</h3>
        <StatusTag tone={view.tone}>{t(view.label)}</StatusTag>
      </div>
      {capability.capability === "FILE_IMPORT" && (
        <dl className="v2-capability-facts">
          <div>
            <dt>{t("wlP0011c.version")}</dt>
            <dd>{capability.package_version ?? t("wlP0011c.notInstalled")}</dd>
          </div>
          <div>
            <dt>{t("wlP0011c.formats")}</dt>
            <dd>
              {capability.format_versions.length
                ? capability.format_versions.join(", ")
                : t("wlP0011c.noFormats")}
            </dd>
          </div>
        </dl>
      )}
      {view.explanation && (
        <p className="v2-capability-note">
          {fill(t(view.explanation), values)}
        </p>
      )}
      {view.switchable && view.confirmVersion === null && (
        <button
          type="button"
          role="switch"
          aria-checked={on}
          className="v2-switch"
          disabled={busy}
          aria-label={fill(t("wlP0011c.switchLabel"), values)}
          onClick={() =>
            on ? disable() : onRun(enable("wlP0011c.enabledDone"))
          }
        >
          <span className="v2-switch-track" aria-hidden="true">
            <span className="v2-switch-thumb" />
          </span>
          <span aria-hidden="true">
            {t(on ? "wlP0011c.on" : "wlP0011c.off")}
          </span>
        </button>
      )}
      {view.confirmVersion !== null && (
        <div className="v2-auth-actions v2-capability-actions">
          <Button
            disabled={busy}
            onClick={() =>
              onAsk({
                title: fill(t("wlP0011c.confirmTitle"), values),
                body: fill(t("wlP0011c.confirmBody"), values),
                confirm: fill(t("wlP0011c.confirmAction"), values),
                action: enable("wlP0011c.confirmedDone"),
              })
            }
          >
            {fill(t("wlP0011c.reviewVersion"), values)}
          </Button>
          {capability.enablement.enabled && (
            <Button variant="secondary" disabled={busy} onClick={disable}>
              {t("wlP0011c.disableConfirm")}
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

function Connections({
  source,
  file,
  items,
  state,
  busy,
  onRun,
  onAsk,
}: {
  source: CatalogItem;
  file: Capability;
  items: SourceConnection[];
  state: RowProps["connections"];
  busy: boolean;
  onRun: (action: Action) => void;
  onAsk: (confirmation: Confirmation) => void;
}) {
  const { t } = useI18n();
  const heading = useId();
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState<SourceConnection | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const realm = state.data?.realm;
  const approved =
    file.status === "ENABLED" ? file.enablement.installation_id : null;

  function update(
    connection: SourceConnection,
    change: { enabled?: boolean; label?: string; installation?: string },
    done: Message,
  ): Action | null {
    if (!realm) return null;
    return {
      path: `/source-connections/${connection.id}`,
      method: "PUT",
      done,
      body: {
        ...common(connection.revision, realm),
        enabled: change.enabled ?? connection.enabled,
        installation_id: change.installation ?? connection.installation_id,
        display_label: change.label ?? connection.display_label,
      },
    };
  }

  return (
    <section className="v2-connections" aria-labelledby={heading}>
      <h3 id={heading}>
        {fill(t("wlP0011c.connectionsTitle"), { name: source.display_name })}
      </h3>
      <p className="muted">{t("wlP0011c.connectionsIntro")}</p>
      {state.isPending ? (
        <PageLoading />
      ) : state.isError ? (
        <PageError
          message={t("wlP0011c.connectionsFailed")}
          onRetry={() => void state.refetch()}
        />
      ) : items.length === 0 ? (
        <p className="v2-connections-empty">{t("wlP0011c.noConnections")}</p>
      ) : (
        <ul className="v2-connection-list">
          {items.map((connection) => {
            const values = { name: connection.display_label };
            const action = (
              change: Parameters<typeof update>[1],
              done: Message,
            ) => update(connection, change, done);
            return (
              <li key={connection.id} className="v2-connection">
                <div className="v2-connection-name">
                  <strong>{connection.display_label}</strong>
                  <StatusTag
                    tone={
                      connection.status === "ENABLED"
                        ? "good"
                        : connection.status === "DISABLED" ||
                            connection.status === "SOURCE_DISABLED"
                          ? "neutral"
                          : "review"
                    }
                  >
                    {t(connectionLabel(connection.status))}
                  </StatusTag>
                </div>
                {connection.parser_source_alias && (
                  <p className="muted">
                    {fill(t("wlP0011c.aliasValue"), {
                      alias: connection.parser_source_alias,
                    })}
                  </p>
                )}
                <div className="v2-connection-actions">
                  <Button
                    variant="secondary"
                    disabled={busy}
                    aria-label={fill(t("wlP0011c.renameLabel"), values)}
                    onClick={() => setRenaming(connection)}
                  >
                    {t("wlP0011c.rename")}
                  </Button>
                  {connection.status === "CONFIRMATION_REQUIRED" &&
                    approved &&
                    approved !== connection.installation_id && (
                      <Button
                        disabled={busy}
                        aria-label={fill(t("wlP0011c.rebindLabel"), values)}
                        onClick={() => {
                          const next = action(
                            { installation: approved },
                            "wlP0011c.confirmedDone",
                          );
                          if (next) onRun(next);
                        }}
                      >
                        {fill(t("wlP0011c.rebind"), {
                          version: file.package_version ?? approved,
                        })}
                      </Button>
                    )}
                  {connection.enabled ? (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      aria-label={fill(
                        t("wlP0011c.disableConnectionLabel"),
                        values,
                      )}
                      onClick={() => {
                        const next = action(
                          { enabled: false },
                          "wlP0011c.connectionDisabledDone",
                        );
                        if (next)
                          onAsk({
                            title: fill(
                              t("wlP0011c.disableConnectionTitle"),
                              values,
                            ),
                            body: t("wlP0011c.disableConnectionBody"),
                            confirm: t("wlP0011c.disableConnection"),
                            destructive: true,
                            action: next,
                          });
                      }}
                    >
                      {t("wlP0011c.disableConnection")}
                    </Button>
                  ) : (
                    <Button
                      variant="secondary"
                      disabled={busy}
                      aria-label={fill(
                        t("wlP0011c.enableConnectionLabel"),
                        values,
                      )}
                      onClick={() => {
                        const next = action(
                          { enabled: true },
                          "wlP0011c.connectionEnabledDone",
                        );
                        if (next) onRun(next);
                      }}
                    >
                      {t("wlP0011c.enableConnection")}
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {approved && realm && !adding && (
        <Button
          ref={addButton}
          variant="secondary"
          disabled={busy}
          onClick={() => setAdding(true)}
        >
          {t("wlP0011c.addConnection")}
        </Button>
      )}
      {approved && realm && adding && (
        <ConnectionForm
          source={source}
          busy={busy}
          onCancel={() => {
            setAdding(false);
            requestAnimationFrame(() => addButton.current?.focus());
          }}
          onSubmit={(label, alias) => {
            onRun({
              path: "/source-connections",
              method: "POST",
              done: "wlP0011c.connectionAddedDone",
              body: {
                ...common("0", realm),
                plugin_id: source.plugin_id,
                capability: "FILE_IMPORT",
                installation_id: approved,
                display_label: label,
                parser_source_alias: alias,
              },
            });
            setAdding(false);
          }}
        />
      )}
      <RenameDialog
        connection={renaming}
        busy={busy}
        onClose={() => setRenaming(null)}
        onSubmit={(connection, label) => {
          const next = update(connection, { label }, "wlP0011c.renamedDone");
          if (next) onRun(next);
          setRenaming(null);
        }}
      />
    </section>
  );
}

type FieldProblem = "required" | "long" | "invalid" | null;

function problemMessage(problem: FieldProblem, alias: boolean): Message | null {
  if (problem === "required") return "wlP0011c.field.required";
  if (problem === "long")
    return alias ? "wlP0011c.field.aliasLong" : "wlP0011c.field.labelLong";
  if (problem === "invalid") return "wlP0011c.field.invalid";
  return null;
}

function Field({
  id,
  label,
  hint,
  value,
  onChange,
  problem,
  inputRef,
}: {
  id: string;
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  problem: Message | null;
  inputRef?: Ref<HTMLInputElement>;
}) {
  const { t } = useI18n();
  const described = [hint && `${id}-hint`, problem && `${id}-error`]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="v2-field">
      <label htmlFor={id}>{label}</label>
      {hint && (
        <small id={`${id}-hint`} className="muted">
          {hint}
        </small>
      )}
      <input
        ref={inputRef}
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={problem ? true : undefined}
        aria-describedby={described || undefined}
      />
      {problem && (
        <p id={`${id}-error`} className="v2-field-error">
          {t(problem)}
        </p>
      )}
    </div>
  );
}

function ConnectionForm({
  source,
  busy,
  onCancel,
  onSubmit,
}: {
  source: CatalogItem;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (label: string, alias: string | null) => void;
}) {
  const { t } = useI18n();
  const id = useId();
  const [label, setLabel] = useState("");
  const [alias, setAlias] = useState("");
  const [checked, setChecked] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  const labelProblem = problemMessage(
    textProblem(label.trim(), LABEL_MAXIMUM),
    false,
  );
  const aliasText = alias.trim();
  const aliasProblem = aliasText
    ? problemMessage(textProblem(aliasText, ALIAS_MAXIMUM), true)
    : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    if (labelProblem || aliasProblem) {
      first.current?.focus();
      return;
    }
    onSubmit(label.trim(), aliasText || null);
  }

  return (
    <form className="v2-connection-form" onSubmit={submit} noValidate>
      <h4>{fill(t("wlP0011c.addTitle"), { name: source.display_name })}</h4>
      <Field
        id={`${id}-label`}
        label={t("wlP0011c.labelField")}
        hint={t("wlP0011c.labelHint")}
        value={label}
        onChange={setLabel}
        problem={checked ? labelProblem : null}
        inputRef={first}
      />
      <Field
        id={`${id}-alias`}
        label={t("wlP0011c.aliasField")}
        hint={t("wlP0011c.aliasHint")}
        value={alias}
        onChange={setAlias}
        problem={checked ? aliasProblem : null}
      />
      <div className="v2-auth-actions">
        <Button type="submit" disabled={busy}>
          {t("wlP0011c.addSubmit")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t("wlP0011c.cancel")}
        </Button>
      </div>
    </form>
  );
}

function RenameDialog({
  connection,
  busy,
  onClose,
  onSubmit,
}: {
  connection: SourceConnection | null;
  busy: boolean;
  onClose: () => void;
  onSubmit: (connection: SourceConnection, label: string) => void;
}) {
  const { t } = useI18n();
  const id = useId();
  const [label, setLabel] = useState("");
  const [checked, setChecked] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const problem = problemMessage(
    textProblem(label.trim(), LABEL_MAXIMUM),
    false,
  );

  return (
    <Dialog.Root
      open={connection !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="dialog"
          aria-describedby={undefined}
          onOpenAutoFocus={() => {
            opener.current = document.activeElement as HTMLElement | null;
            setLabel(connection?.display_label ?? "");
            setChecked(false);
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            const origin = opener.current;
            opener.current = null;
            if (origin?.isConnected) origin.focus();
            else document.querySelector<HTMLElement>("main h1")?.focus();
          }}
        >
          <Dialog.Title>{t("wlP0011c.renameTitle")}</Dialog.Title>
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              setChecked(true);
              if (!problem && connection) onSubmit(connection, label.trim());
            }}
          >
            <Field
              id={id}
              label={t("wlP0011c.labelField")}
              value={label}
              onChange={setLabel}
              problem={checked ? problem : null}
            />
            <div className="v2-auth-actions">
              <Dialog.Close asChild>
                <Button type="button" variant="secondary">
                  {t("wlP0011c.cancel")}
                </Button>
              </Dialog.Close>
              <Button type="submit" disabled={busy}>
                {t("wlP0011c.renameSubmit")}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
