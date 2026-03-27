"use client";

import { useEffect, useState } from "react";
import { CHAT_FEATURE_FLAG_KEY } from "@/lib/explorer/constants";

/**
 * Returns true if the chat feature is enabled for this browser session.
 *
 * Activation: visit the site with ?feature=chat_bot in the URL.
 * The flag is written to localStorage and the param is stripped from the URL.
 * Once set, the chat widget remains enabled until localStorage is cleared.
 */
export function useChatFeatureFlag(): boolean {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    // Check URL param first
    const params = new URLSearchParams(window.location.search);
    if (params.get("feature") === "chat_bot") {
      localStorage.setItem(CHAT_FEATURE_FLAG_KEY, "1");
      // Strip param from URL without a full page reload
      params.delete("feature");
      const newSearch = params.toString();
      const newUrl =
        window.location.pathname + (newSearch ? `?${newSearch}` : "");
      window.history.replaceState(null, "", newUrl);
    }
    setEnabled(localStorage.getItem(CHAT_FEATURE_FLAG_KEY) === "1");
  }, []);

  return enabled;
}
