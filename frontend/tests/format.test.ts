import { describe, expect, it } from "vitest";
import {
  amount,
  chartNumber,
  compare,
  percent,
  quantity,
} from "../src/lib/format";
import { catalogs } from "../src/lib/i18n";
describe("Financial presentation", () => {
  it("keeps unknown different from zero and preserves exact money digits", () => {
    expect(amount(null, "CAD", "en-CA")).toBe("—");
    expect(amount("0", "CAD", "en-CA")).toContain("0.00");
    expect(amount("9007199254740993.12", "CAD", "en-CA")).toContain(
      "9,007,199,254,740,993.12",
    );
    expect(quantity("0.00000001")).toBe("0.00000001");
    expect(quantity("0")).toBe("0");
    expect(percent(null)).toBe("—");
    expect(percent("0.123456")).toBe("12.35%");
  });
  it("sorts decimal strings exactly and leaves chart gaps unknown", () => {
    expect(compare("9007199254740993", "9007199254740992")).toBe(1);
    expect(chartNumber(null)).toBeNull();
    expect(chartNumber("0")).toBe(0);
  });
  it("keeps all three locale keys identical", () => {
    const keys = Object.keys(catalogs["en-CA"]).sort();
    for (const catalog of Object.values(catalogs))
      expect(Object.keys(catalog).sort()).toEqual(keys);
  });
});
