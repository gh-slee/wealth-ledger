import type { Message } from "../lib/i18n";
import type { Invitation } from "./api";

// Client-side mirrors of the V2 identity rules in
// src/kurafolio/web_v2/schemas.py. The server stays authoritative; these
// checks only give a field-level message before a request is sent.

export const PASSWORD_MINIMUM = 15;
export const PASSWORD_MAXIMUM = 256;
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const USERNAME = /^[A-Za-z0-9_.-]{1,64}$/;

export type PasswordProblem = "short" | "long" | "invalid" | "mismatch";
export type UsernameProblem = "required" | "invalid";

/** Read a setup or invitation token from a link's query string. */
export function linkToken(search: string): string | null {
  const values = new URLSearchParams(search).getAll("token");
  return values.length === 1 && TOKEN.test(values[0]) ? values[0] : null;
}

/** Python counts code points, so a pair of UTF-16 surrogates counts once. */
export function passwordProblem(
  value: string,
  confirmation?: string,
): PasswordProblem | null {
  const points = [...value];
  if (
    value.includes("\0") ||
    points.some((point) => {
      const code = point.charCodeAt(0);
      return point.length === 1 && code >= 0xd800 && code <= 0xdfff;
    })
  )
    return "invalid";
  if (points.length < PASSWORD_MINIMUM) return "short";
  if (points.length > PASSWORD_MAXIMUM) return "long";
  if (confirmation !== undefined && confirmation !== value) return "mismatch";
  return null;
}

export function usernameProblem(username: string): UsernameProblem | null {
  if (!username) return "required";
  return USERNAME.test(username) ? null : "invalid";
}

export type InvitationStatus = {
  label: Message;
  tone: "good" | "review" | "neutral";
  revocable: boolean;
};

export function invitationStatus(
  invitation: Pick<Invitation, "status" | "revocation_reason">,
): InvitationStatus {
  switch (invitation.status) {
    case "issued":
      return { label: "wlP0011b.status.issued", tone: "good", revocable: true };
    case "consumed":
      return {
        label: "wlP0011b.status.consumed",
        tone: "neutral",
        revocable: false,
      };
    case "expired":
      return {
        label: "wlP0011b.status.expired",
        tone: "neutral",
        revocable: false,
      };
    case "revoked":
      return {
        label:
          invitation.revocation_reason === "restore"
            ? "wlP0011b.status.revokedRestore"
            : "wlP0011b.status.revoked",
        tone: "review",
        revocable: false,
      };
    default:
      return {
        label: "wlP0011b.status.unknown",
        tone: "review",
        revocable: false,
      };
  }
}

export function invitationLink(origin: string, token: string): string {
  return `${origin}/register?token=${encodeURIComponent(token)}`;
}

/** A random version 4 UUID in the canonical lowercase form the API expects. */
export function requestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4),
    hex.slice(4, 6),
    hex.slice(6, 8),
    hex.slice(8, 10),
    hex.slice(10),
  ]
    .map((part) => part.join(""))
    .join("-");
}
