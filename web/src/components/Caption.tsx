// web/src/components/Caption.tsx
"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function normalize(md: string) {
  const text = md.replace(/\r\n/g, "\n");

  // Remove leading spaces on each line (prevents accidental code blocks)
  // This is safe for our captions, since we don't rely on indentation for code/list formatting yet.
  return text
    .split("\n")
    .map((line) => line.replace(/^\s+/, "")) // strip all leading whitespace
    .join("\n")
    .trim();
}

export default function Caption({ md }: { md: string }) {
  const cleaned = normalize(md);

  return (
    <div className="prose prose-neutral max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleaned}</ReactMarkdown>
    </div>
  );
}
