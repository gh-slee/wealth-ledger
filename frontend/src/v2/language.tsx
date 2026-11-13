import type { Locale } from "../lib/api";
import { useI18n } from "../lib/i18n";

export function Language() {
  const { locale, setLocale, t } = useI18n();
  return (
    <label>
      {t("language")}
      <select
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        <option value="en-CA">English</option>
        <option value="zh-TW">繁體中文</option>
        <option value="zh-CN">简体中文</option>
      </select>
    </label>
  );
}
