"use client";

import { useEffect, useMemo, useState } from "react";

type ThemePref = "system" | "light" | "dark";

function getSystemIsDark() {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ?? false;
}

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>("system");
  const systemIsDark = useMemo(getSystemIsDark, []);

  // Load stored pref
  useEffect(() => {
    const saved = window.localStorage.getItem("theme") as ThemePref | null;
    if (saved === "light" || saved === "dark" || saved === "system") setPref(saved);
  }, []);

  // Apply to <html>
  useEffect(() => {
    const root = document.documentElement;

    const apply = (isDark: boolean) => {
      root.classList.toggle("dark", isDark);
      // Helps native form controls match theme
      root.style.colorScheme = isDark ? "dark" : "light";
    };

    if (pref === "light") apply(false);
    else if (pref === "dark") apply(true);
    else apply(getSystemIsDark());

    if (pref !== "system") return;

    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply(mq.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, [pref, systemIsDark]);

  const cycle = () => {
    setPref((p) => {
      const next = p === "system" ? "light" : p === "light" ? "dark" : "system";
      window.localStorage.setItem("theme", next);
      return next;
    });
  };

  const label = pref === "system" ? "Auto" : pref === "light" ? "Light" : "Dark";

  return { themePref: pref, setThemePref: setPref, cycleTheme: cycle, themeLabel: label };
}
