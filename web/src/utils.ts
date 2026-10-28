import { useEffect, useState } from "react";

export type DeviceKind = "all" | "pos" | "atm" | "kiosk" | "other";

export function deviceKind(model: string): DeviceKind {
  if (model === "all") return "all";
  const upper = model.toUpperCase();
  if (upper.includes("POS")) return "pos";
  if (upper.includes("ATM")) return "atm";
  if (upper.includes("KIOSK")) return "kiosk";
  return "other";
}

export const deviceLabel = (model: string) => (model === "all" ? "All devices" : model);

/** Chroma L2 distance (lower is closer) as a plain-language match level. A raw percentage would mislead. */
export function matchLevel(distance: number | null): { bars: 1 | 2 | 3; label: string } {
  if (distance !== null && distance <= 0.6) return { bars: 3, label: "Strong match" };
  if (distance !== null && distance <= 0.8) return { bars: 2, label: "Good match" };
  return { bars: 1, label: "Possible match" };
}

export const fileKind = (name: string) => (name.split(".").pop() ?? "file").slice(0, 4).toUpperCase();

/** 'atm_cash_dispenser_jam_runbook.md' -> 'Atm cash dispenser jam runbook'; error codes stay as they are. */
export function prettyDoc(name: string): string {
  if (/^[A-Z]{1,3}-?\d{3,5}$/.test(name)) return name;
  const base = name
    .replace(/\.[a-z0-9]{2,5}$/i, "")
    .replace(/\bhx[-_ ](atm|pos|kiosk)[-_ ](\d+)/gi, (_m, kind: string, num: string) => `HX-${kind.toUpperCase()}-${num}`)
    .replace(/[_]+/g, " ")
    .replace(/-(?!\d)/g, " ")
    .trim();
  return base.charAt(0).toUpperCase() + base.slice(1);
}

export const percent = (rate: number | null) => (rate === null ? "n/a" : `${Math.round(rate * 100)}%`);

export const formatSize =(bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export const newId =() => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const mq = matchMedia(query);
    const update = () => setMatches(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [query]);
  return matches;
}

export function useTheme(): ["light" | "dark", () => void] {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (document.documentElement.dataset.theme as "light" | "dark") || "light",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("fa-theme", theme);
    } catch {
      /* storage can be unavailable; the theme still applies for this session */
    }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}
