import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
  type ReactNode,
} from "react";

export type Theme = "system" | "light" | "dark";
export const THEME_KEY = "wealth-ledger-theme";
export const validTheme = (value: string | null): Theme =>
  value === "light" || value === "dark" ? value : "system";
const ThemeContext = createContext<{
  theme: Theme;
  resolved: "light" | "dark";
  setTheme: (theme: Theme) => void;
}>({ theme: "system", resolved: "light", setTheme: () => {} });
export const useTheme = () => useContext(ThemeContext);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, update] = useState<Theme>(() => {
    try {
      return validTheme(localStorage.getItem(THEME_KEY));
    } catch {
      return "system";
    }
  });
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );
  const resolved = theme === "system" ? (systemDark ? "dark" : "light") : theme;
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const changed = () => setSystemDark(media.matches);
    media.addEventListener("change", changed);
    changed();
    return () => media.removeEventListener("change", changed);
  }, []);
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);
  function setTheme(value: Theme) {
    update(value);
    // Only a nonfinancial enum is persisted; portfolio/session/query data never is.
    try {
      if (value === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, value);
    } catch {
      /* Private browsing can disable preference storage. */
    }
  }
  return (
    <ThemeContext.Provider value={{ theme, resolved, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
