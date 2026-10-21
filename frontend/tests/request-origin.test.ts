import { describe, expect, it } from "vitest";
import { isLocalResource } from "./browser/request-origin";

const origin = "http://localhost:8765";
describe("browser resource origin boundary", () => {
  it("accepts report images backed by same-origin memory blobs", () => {
    expect(isLocalResource(`blob:${origin}/synthetic-image-id`, origin)).toBe(
      true,
    );
  });
  it("rejects a different port even when its URL starts with the allowed origin", () => {
    expect(
      isLocalResource(
        "http://localhost:8765/report.png",
        "http://localhost:876",
      ),
    ).toBe(false);
    expect(isLocalResource("http://localhost:87650/report.png", origin)).toBe(
      false,
    );
  });
  it("accepts same-origin API/assets and inline data without allowing other origins", () => {
    for (const resource of [
      `${origin}/api/v1/example`,
      `${origin}/assets/example.js`,
      "data:image/png;base64,example",
    ])
      expect(isLocalResource(resource, origin)).toBe(true);
    for (const resource of [
      "https://external.invalid/report.png",
      "blob:https://external.invalid/image",
      "http://localhost:8766/report.png",
      "https://localhost:8765/report.png",
      "blob:null/opaque",
      "file:///synthetic.png",
      "not a URL",
    ])
      expect(isLocalResource(resource, origin)).toBe(false);
  });
});
