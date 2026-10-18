import { afterEach, describe, expect, it, vi } from "vitest";
import { clearTransport, read, mutate } from "../src/lib/api";
afterEach(() => {
  clearTransport();
  vi.unstubAllGlobals();
});
describe("in-flight context isolation", () => {
  it("rejects a response body that finishes after a portfolio switch", async () => {
    let finish!: (value: unknown) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      }),
    );
    const request = read("/synthetic");
    await vi.waitFor(() => expect(finish).toBeDefined());
    clearTransport();
    finish({ privateValue: "old portfolio" });
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });
  it("does not let a late old 401 log out a newer context", async () => {
    const dispatch = vi.fn();
    vi.stubGlobal("window", { dispatchEvent: dispatch });
    let finish!: (value: unknown) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      }),
    );
    const request = read("/synthetic");
    await vi.waitFor(() => expect(finish).toBeDefined());
    clearTransport();
    finish({ error: { code: "authentication_required" } });
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(dispatch).not.toHaveBeenCalled();
  });
  it("cannot submit after a switch while waiting for CSRF bootstrap", async () => {
    let finish!: (value: unknown) => void;
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    });
    vi.stubGlobal("fetch", fetch);
    const request = mutate("/synthetic", { name: "old context" });
    await vi.waitFor(() => expect(finish).toBeDefined());
    clearTransport();
    finish({ csrf_token: "example-placeholder" });
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
