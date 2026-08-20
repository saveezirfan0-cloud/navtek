"use client";

import { useSyncExternalStore } from "react";

/**
 * Light / dark / system, chosen by the person, remembered per browser.
 *
 * The choice lives in localStorage and lands on <html data-theme="…">, which
 * the CSS keys its dark tokens off. "System" removes the attribute so the
 * prefers-color-scheme media query decides — exactly what the app did before
 * it had a toggle. A tiny inline script in the root layout applies the saved
 * choice before first paint, so there is no flash of the wrong scheme.
 */

export const THEME_KEY = "navtek-theme";
export type Theme = "light" | "dark" | "system";

// Every mounted switcher subscribes here, so the one in the profile menu and
// the one on /settings always agree — same pattern React documents for
// external stores (the store being localStorage + the <html> attribute).
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
  try {
    if (theme === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Private browsing without storage still gets the theme for this page.
  }
  listeners.forEach((listener) => listener());
}

function savedTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_KEY);
    if (value === "light" || value === "dark") return value;
  } catch {
    // fall through
  }
  return "system";
}

const OPTIONS: { value: Theme; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

/** The three-way appearance control — used in the profile menu and on
 * /settings. Purely client side: appearance is a per-browser preference. */
export default function ThemeSwitcher({ compact = false }: { compact?: boolean }) {
  // The server snapshot says "system"; the client corrects on hydration.
  const theme = useSyncExternalStore(subscribe, savedTheme, () => "system" as Theme);

  return (
    <div
      className={`theme-seg ${compact ? "compact" : ""}`}
      role="radiogroup"
      aria-label="Appearance"
    >
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={theme === option.value}
          className={`theme-opt ${theme === option.value ? "on" : ""}`}
          onClick={() => applyTheme(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
