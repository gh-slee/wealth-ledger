import { describe, expect, it } from "vitest";
import { catalogs } from "../src/lib/i18n";
import {
  invitationLink,
  invitationStatus,
  linkToken,
  passwordProblem,
  requestId,
  usernameProblem,
} from "../src/v2/identity";

const token = "A".repeat(42) + "_";

describe("V2 password rules", () => {
  it("requires 15 to 256 code points", () => {
    expect(passwordProblem("a".repeat(14))).toBe("short");
    expect(passwordProblem("a".repeat(15))).toBeNull();
    expect(passwordProblem("a".repeat(256))).toBeNull();
    expect(passwordProblem("a".repeat(257))).toBe("long");
  });

  it("counts characters the way the server does", () => {
    // Fifteen emoji are thirty UTF-16 units but fifteen code points.
    expect(passwordProblem("😀".repeat(15))).toBeNull();
    expect(passwordProblem("😀".repeat(14))).toBe("short");
    expect(passwordProblem("😀".repeat(256))).toBeNull();
  });

  it("rejects characters the server cannot store", () => {
    expect(passwordProblem("a".repeat(15) + "\0")).toBe("invalid");
    expect(passwordProblem("a".repeat(15) + "\ud800")).toBe("invalid");
    expect(passwordProblem("\udc00" + "a".repeat(15))).toBe("invalid");
  });

  it("checks the confirmation only after the password itself", () => {
    const password = "correct horse battery";
    expect(passwordProblem(password, password)).toBeNull();
    expect(passwordProblem(password, password + " ")).toBe("mismatch");
    expect(passwordProblem("short", "other")).toBe("short");
  });
});

describe("V2 username rules", () => {
  it("matches the server pattern", () => {
    expect(usernameProblem("")).toBe("required");
    expect(usernameProblem("example.user-1_a")).toBeNull();
    expect(usernameProblem("a".repeat(64))).toBeNull();
    expect(usernameProblem("a".repeat(65))).toBe("invalid");
    for (const value of ["with space", "café", "a/b", "a@b"])
      expect(usernameProblem(value)).toBe("invalid");
  });
});

describe("V2 link tokens", () => {
  it("accepts exactly one well-formed token", () => {
    expect(linkToken(`?token=${token}`)).toBe(token);
    expect(linkToken("")).toBeNull();
    expect(linkToken("?token=")).toBeNull();
    expect(linkToken(`?token=${token}x`)).toBeNull();
    expect(linkToken(`?token=${token.slice(1)}=`)).toBeNull();
    expect(linkToken(`?token=${token}&token=${token}`)).toBeNull();
  });

  it("builds a registration link the register page can read back", () => {
    const link = new URL(invitationLink("https://ledger.example", token));
    expect(link.origin + link.pathname).toBe("https://ledger.example/register");
    expect(linkToken(link.search)).toBe(token);
  });
});

describe("V2 invitation status", () => {
  it("maps every server state to a labelled, non-colour-only status", () => {
    const cases = [
      ["issued", null, "wlP0011b.status.issued", true],
      ["consumed", null, "wlP0011b.status.consumed", false],
      ["expired", null, "wlP0011b.status.expired", false],
      ["revoked", "manual", "wlP0011b.status.revoked", false],
      ["revoked", "restore", "wlP0011b.status.revokedRestore", false],
    ] as const;
    for (const [status, revocation_reason, label, revocable] of cases) {
      const value = invitationStatus({ status, revocation_reason });
      expect(value.label).toBe(label);
      expect(value.revocable).toBe(revocable);
      for (const catalog of Object.values(catalogs))
        expect(catalog[label]).toBeTruthy();
    }
  });

  it("treats an unexpected state as unknown and not revocable", () => {
    const value = invitationStatus({
      status: "paused" as never,
      revocation_reason: null,
    });
    expect(value.label).toBe("wlP0011b.status.unknown");
    expect(value.revocable).toBe(false);
  });
});

describe("V2 identity catalogs", () => {
  it("defines the same WL-P0-011B keys and placeholders in every locale", () => {
    const keys = (locale: keyof typeof catalogs) =>
      Object.keys(catalogs[locale]).filter((key) =>
        key.startsWith("wlP0011b."),
      );
    expect(keys("zh-TW")).toEqual(keys("en-CA"));
    expect(keys("zh-CN")).toEqual(keys("en-CA"));
    for (const key of keys("en-CA")) {
      const placeholders = (text: string) => text.match(/\{[a-z]+\}/g) ?? [];
      for (const catalog of Object.values(catalogs))
        expect(placeholders(catalog[key])).toEqual(
          placeholders(catalogs["en-CA"][key]),
        );
    }
  });
});

describe("V2 issue request IDs", () => {
  it("are canonical lowercase version 4 UUIDs", () => {
    const seen = new Set<string>();
    for (let index = 0; index < 50; index++) {
      const value = requestId();
      expect(value).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
      seen.add(value);
    }
    expect(seen.size).toBe(50);
  });
});
