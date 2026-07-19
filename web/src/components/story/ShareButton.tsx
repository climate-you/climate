"use client";

import { useState } from "react";
import styles from "./story.module.css";

type Props = {
  title: string;
  text?: string;
};

/**
 * Share the story.
 *
 * On phones this opens the OS share sheet (WhatsApp, Messages, Signal…), which
 * is where stories actually travel. Desktop browsers largely lack the Web Share
 * API, so there we fall back to copying the link. Either way it is the URL that
 * gets shared, not the image, so the link unfurls with the story's social card.
 */
export default function ShareButton({ title, text }: Props) {
  const [copied, setCopied] = useState(false);

  const onClick = async () => {
    const url = window.location.href;

    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share({ title, text, url });
        return;
      } catch (error) {
        // Dismissing the sheet is a decision, not a failure: don't then
        // silently copy something the reader chose not to share.
        if ((error as Error)?.name === "AbortError") return;
      }
    }

    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked (insecure context or denied permission).
    }
  };

  return (
    <button type="button" className={styles.shareBtn} onClick={onClick}>
      <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
        <path
          d="M12 3v12M12 3l-4 4M12 3l4 4M5 13v6a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-6"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {copied ? "Link copied" : "Share"}
    </button>
  );
}
