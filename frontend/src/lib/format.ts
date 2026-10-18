import Decimal from "decimal.js";
import type { Currency, Locale } from "./api";
// Display rounding is exact Decimal arithmetic. Financial source strings stay intact.
export function amount(
  value: string | null | undefined,
  currency: Currency,
  locale: Locale,
): string {
  if (value == null) return "—";
  try {
    const fixed = new Decimal(value).toFixed(2);
    const negative = fixed.startsWith("-");
    const [whole, fraction] = fixed.replace(/^-/, "").split(".");
    return `${negative ? "−" : ""}${currency === "TWD" ? "NT$" : currency === "USD" ? "US$" : "CA$"}${BigInt(whole).toLocaleString(locale)}.${fraction}`;
  } catch {
    return "—";
  }
}
export function percent(value: string | null | undefined): string {
  if (value == null) return "—";
  try {
    return new Decimal(value).times(100).toFixed(2) + "%";
  } catch {
    return "—";
  }
}
export function quantity(value: string | null | undefined): string {
  if (value == null) return "—";
  try {
    return new Decimal(value).toFixed(8).replace(/\.?0+$/, "") || "0";
  } catch {
    return "—";
  }
}
export function compare(a: unknown, b: unknown): number {
  if (a == null) return b == null ? 0 : 1;
  if (b == null) return -1;
  try {
    return new Decimal(String(a)).comparedTo(new Decimal(String(b)));
  } catch {
    return String(a).localeCompare(String(b));
  }
}
export function date(value: string | null | undefined, locale: Locale): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? value
    : new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "America/Toronto",
      }).format(parsed);
}
export function chartNumber(value: unknown): number | null {
  if (value == null) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
