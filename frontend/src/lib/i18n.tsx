import { createContext, useContext } from "react";
import en from "../locales/en-CA.json";
import tw from "../locales/zh-TW.json";
import cn from "../locales/zh-CN.json";
import type { Locale } from "./api";
export const catalogs: Record<Locale, Record<string, string>> = {
  "en-CA": en,
  "zh-TW": tw,
  "zh-CN": cn,
};
export type Message = keyof typeof en;
export const LocaleContext = createContext<{
  locale: Locale;
  setLocale: (locale: Locale) => void;
}>({ locale: "en-CA", setLocale: () => {} });
export function useI18n() {
  const context = useContext(LocaleContext);
  const table = catalogs[context.locale];
  return {
    ...context,
    t: (key: Message) => table[key],
    label: (key: string) => table["status." + key] ?? table.unknown,
    error: (code: string) => table["error." + code] ?? table.failed,
  };
}
