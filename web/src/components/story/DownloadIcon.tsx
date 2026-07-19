"use client";

import styles from "./story.module.css";

type Props = {
  onClick: () => void;
  label: string;
  className?: string;
};

/** Icon-only download button (down-arrow into a baseline). */
export default function DownloadIcon({ onClick, label, className }: Props) {
  return (
    <button
      type="button"
      className={`${styles.dlIcon}${className ? ` ${className}` : ""}`}
      onClick={onClick}
      title={label}
      aria-label={label}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 3v12" />
        <path d="m7 10 5 5 5-5" />
        <path d="M5 21h14" />
      </svg>
    </button>
  );
}
