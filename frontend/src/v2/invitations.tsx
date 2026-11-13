import { useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Copy } from "lucide-react";
import { DataTable } from "../components/data-table";
import { Button } from "../components/ui/button";
import { date } from "../lib/format";
import { useI18n, type Message } from "../lib/i18n";
import {
  mutate,
  read,
  V2Error,
  type Invitation,
  type InvitationIssued,
  type Invitations as InvitationPage,
} from "./api";
import { invitationLink, invitationStatus, requestId } from "./identity";
import { PageEmpty, PageError, PageLoading } from "./page-state";
import "./identity.css";

type Issued = { link: string; expiresAt: string };

/**
 * Invitation management for the instance administrator. Render it only for
 * that role: members must never request the admin routes.
 */
export function InvitationManager({ userId }: { userId: string }) {
  const { t, locale } = useI18n();
  const client = useQueryClient();
  const key = useMemo(() => ["v2", userId, "invitations"], [userId]);
  // The raw link exists only in this component's memory. Leaving the page,
  // signing out or pressing Done discards it; the server never shows it again.
  const [issued, setIssued] = useState<Issued | null>(null);
  const [copied, setCopied] = useState(false);
  const [failure, setFailure] = useState<Message | null>(null);
  const [revoking, setRevoking] = useState<Invitation | null>(null);
  const linkInput = useRef<HTMLInputElement>(null);
  const issuedHeading = useRef<HTMLHeadingElement>(null);

  const list = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam, signal }) =>
      read<InvitationPage>(
        "/admin/invitations?limit=50" +
          (pageParam ? `&after=${encodeURIComponent(pageParam)}` : ""),
        signal,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_after,
  });

  const issue = useMutation({
    mutationFn: async () => {
      const id = requestId();
      try {
        return await mutate<InvitationIssued>("/admin/invitations", {
          issue_request_id: id,
        });
      } catch (error) {
        if (error instanceof V2Error && error.status < 500) throw error;
        // The response may have been lost after the server created the
        // invitation. Look it up by request ID; the link cannot be recovered.
        const found = await read<InvitationPage>(
          `/admin/invitations?issue_request_id=${id}`,
        ).catch(() => null);
        throw new V2Error(
          0,
          found?.items.length ? "link_lost" : found ? "not_created" : "unknown",
        );
      }
    },
    onMutate: () => {
      setFailure(null);
      setIssued(null);
      setCopied(false);
    },
    onSuccess: (value) => {
      setIssued({
        link: invitationLink(window.location.origin, value.invite_token),
        expiresAt: value.expires_at,
      });
    },
    onError: (error) => {
      const code = error instanceof V2Error ? error.code : "";
      setFailure(
        code === "link_lost"
          ? "wlP0011b.invite.linkLost"
          : code === "unknown"
            ? "wlP0011b.invite.uncertain"
            : code === "rate_limited"
              ? "wlP0011b.rateLimited"
              : "wlP0011b.invite.failed",
      );
    },
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  });

  const revoke = useMutation({
    mutationFn: (invitation: Invitation) =>
      mutate(`/admin/invitations/${invitation.id}/revoke`),
    onMutate: () => setFailure(null),
    onSuccess: () => setRevoking(null),
    onError: (error) => {
      setRevoking(null);
      setFailure(
        error instanceof V2Error && error.code === "invite_not_active"
          ? "wlP0011b.invite.notActive"
          : "wlP0011b.invite.revokeFailed",
      );
    },
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  });

  useEffect(() => {
    if (issued) issuedHeading.current?.focus();
  }, [issued]);

  async function copy() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.link);
      setCopied(true);
    } catch {
      // Without clipboard access, select the text so it can be copied by hand.
      linkInput.current?.select();
      setCopied(false);
    }
  }

  const columns = useMemo<ColumnDef<Invitation>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: t("wlP0011b.invite.created"),
        cell: ({ getValue }) => date(getValue<string>(), locale),
      },
      {
        accessorKey: "expires_at",
        header: t("wlP0011b.invite.expires"),
        cell: ({ getValue }) => date(getValue<string>(), locale),
      },
      {
        id: "status",
        accessorFn: (row) => t(invitationStatus(row).label),
        header: t("wlP0011b.invite.status"),
        cell: ({ row }) => {
          const status = invitationStatus(row.original);
          return (
            <span
              className={
                status.tone === "neutral"
                  ? "status"
                  : `status status-${status.tone}`
              }
            >
              {t(status.label)}
            </span>
          );
        },
      },
      {
        id: "action",
        header: () => (
          <span className="sr-only">{t("wlP0011b.invite.action")}</span>
        ),
        enableSorting: false,
        cell: ({ row }) =>
          invitationStatus(row.original).revocable ? (
            <Button
              variant="secondary"
              onClick={() => setRevoking(row.original)}
              disabled={revoke.isPending}
            >
              {t("wlP0011b.invite.revoke")}
            </Button>
          ) : null,
      },
    ],
    [t, locale, revoke.isPending],
  );

  const items = list.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <section className="v2-invitations" aria-labelledby="invitations-heading">
      <h2 id="invitations-heading">{t("wlP0011b.invite.title")}</h2>
      <p className="muted">{t("wlP0011b.invite.intro")}</p>
      <Button onClick={() => issue.mutate()} disabled={issue.isPending}>
        {issue.isPending ? t("loading") : t("wlP0011b.invite.create")}
      </Button>
      {failure && (
        <p role="alert" className="error v2-auth-alert">
          {t(failure)}
        </p>
      )}
      {issued && (
        <div className="v2-issued">
          <h3 ref={issuedHeading} tabIndex={-1}>
            {t("wlP0011b.invite.issuedTitle")}
          </h3>
          <p>{t("wlP0011b.invite.once")}</p>
          <div className="v2-field">
            <label htmlFor="invitation-link">{t("wlP0011b.invite.link")}</label>
            <div className="v2-copy-row">
              <input
                ref={linkInput}
                id="invitation-link"
                readOnly
                value={issued.link}
                aria-describedby="invitation-expiry"
                onFocus={(event) => event.currentTarget.select()}
              />
              <Button variant="secondary" onClick={copy}>
                <Copy size={16} aria-hidden="true" />
                {t("wlP0011b.invite.copy")}
              </Button>
            </div>
            <small id="invitation-expiry" className="muted">
              {t("wlP0011b.invite.expiresAt").replace(
                "{date}",
                date(issued.expiresAt, locale),
              )}
            </small>
          </div>
          <p role="status" className="muted">
            {copied ? t("wlP0011b.invite.copied") : ""}
          </p>
          <Button
            variant="ghost"
            onClick={() => {
              setIssued(null);
              setCopied(false);
            }}
          >
            {t("wlP0011b.invite.done")}
          </Button>
        </div>
      )}
      {list.isPending ? (
        <PageLoading />
      ) : list.isError ? (
        <PageError onRetry={() => void list.refetch()} />
      ) : items.length === 0 ? (
        <PageEmpty message={t("wlP0011b.invite.empty")} />
      ) : (
        <>
          <DataTable
            data={items}
            columns={columns}
            caption={t("wlP0011b.invite.title")}
          />
          {list.hasNextPage && (
            <Button
              variant="secondary"
              onClick={() => void list.fetchNextPage()}
              disabled={list.isFetchingNextPage}
            >
              {t("wlP0011b.invite.more")}
            </Button>
          )}
        </>
      )}
      <Dialog.Root
        open={revoking !== null}
        onOpenChange={(open) => {
          if (!open && !revoke.isPending) setRevoking(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog">
            <Dialog.Title>{t("wlP0011b.invite.revokeTitle")}</Dialog.Title>
            <Dialog.Description>
              {t("wlP0011b.invite.revokeBody").replace(
                "{date}",
                revoking ? date(revoking.expires_at, locale) : "",
              )}
            </Dialog.Description>
            <div className="v2-auth-actions">
              <Dialog.Close asChild>
                <Button variant="secondary" disabled={revoke.isPending}>
                  {t("wlP0011b.invite.keep")}
                </Button>
              </Dialog.Close>
              <Button
                variant="destructive"
                disabled={revoke.isPending}
                onClick={() => revoking && revoke.mutate(revoking)}
              >
                {t("wlP0011b.invite.revokeConfirm")}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
