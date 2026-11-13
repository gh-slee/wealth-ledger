import type { Locale } from "../lib/api";
import { catalogs } from "../lib/i18n";

// V2 keeps its own remembered language so the shipped SQLite UI is unchanged.
const LOCALE_KEY = "kurafolio-v2-locale";

export function preferredLocale(): Locale {
  try {
    const value = localStorage.getItem(LOCALE_KEY);
    if (value && Object.hasOwn(catalogs, value)) return value as Locale;
  } catch {
    // Preference storage can be unavailable in private browsing.
  }
  return "en-CA";
}

export function rememberLocale(value: Locale) {
  try {
    localStorage.setItem(LOCALE_KEY, value);
  } catch {
    // The in-memory preference still applies for this page.
  }
}
