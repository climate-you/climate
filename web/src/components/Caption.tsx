"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function normalize(md: string) {
  const text = md.replace(/\r\n/g, "\n");
  return text
    .split("\n")
    .map((line) => line.replace(/^\s+/, ""))
    .join("\n")
    .trim();
}

function splitBlocks(md: string): string[] {
  return md
    .split(/\n\s*\n/g)
    .map((b) => b.trim())
    .filter(Boolean);
}

function isPlainParagraphBlock(block: string) {
  const t = block.trim();
  return !(
    t.startsWith("#") ||
    t.startsWith("- ") ||
    t.startsWith("* ") ||
    t.match(/^\d+\.\s/) ||
    t.startsWith(">") ||
    t.startsWith("```")
  );
}

/**
 * Sentence split that tries hard to NOT cut inside:
 * - **bold**
 * - `inline code`
 *
 * This is not a full markdown parser, but it prevents the common
 * “**+1.0°C**.” / “...**word**.Next” breakage.
 */
function splitSentencesMarkdownSafe(text: string): string[] {
  const out: string[] = [];
  let start = 0;

  let inCode = false;
  let inBold = false;

  const n = text.length;

  for (let i = 0; i < n; i++) {
    const ch = text[i];

    // Toggle inline code on backticks (ignore escaped)
    if (ch === "`" && (i === 0 || text[i - 1] !== "\\")) {
      inCode = !inCode;
      continue;
    }

    // Toggle bold on ** (ignore escaped)
    if (
      ch === "*" &&
      i + 1 < n &&
      text[i + 1] === "*" &&
      (i === 0 || text[i - 1] !== "\\")
    ) {
      inBold = !inBold;
      i++; // consume the second '*'
      continue;
    }

    // Only consider punctuation as sentence boundary when not inside code/bold
    if (!inCode && !inBold && (ch === "." || ch === "!" || ch === "?")) {
      const next = i + 1 < n ? text[i + 1] : "";
      const next2 = i + 2 < n ? text[i + 2] : "";

      // Split on ". " / ".\n" / end-of-string, and also handle quotes/parens like '." '
      const looksLikeBoundary =
        next === "" ||
        next === " " ||
        next === "\n" ||
        (next === '"' && (next2 === "" || next2 === " " || next2 === "\n")) ||
        (next === ")" && (next2 === "" || next2 === " " || next2 === "\n"));

      if (looksLikeBoundary) {
        const sentence = text.slice(start, i + 1).trim();
        if (sentence) out.push(sentence);
        start = i + 1;
      }
    }
  }

  const tail = text.slice(start).trim();
  if (tail) out.push(tail);
  return out;
}

function InlineMarkdown({ md }: { md: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <>{children}</>,
      }}
    >
      {md}
    </ReactMarkdown>
  );
}

export default function Caption(props: {
  md: string;
  reveal?: "none" | "sentences";
  staggerMs?: number;
  initialDelayMs?: number;

  // New behavior: start revealing only when caption is on screen
  revealOnView?: boolean;
  // If true, leaving viewport resets to hidden (nice for scrollytelling replay)
  resetOnExit?: boolean;
}) {
  const {
    md,
    reveal = "none",
    staggerMs = 520,
    initialDelayMs = 180,
    revealOnView = true,
    resetOnExit = true,
  } = props;

  const cleaned = useMemo(() => normalize(md), [md]);
  const blocks = useMemo(() => splitBlocks(cleaned), [cleaned]);

  const items = useMemo(() => {
    const out: Array<
      | { kind: "sentence"; blockIndex: number; text: string }
      | { kind: "block"; blockIndex: number; text: string }
    > = [];

    blocks.forEach((b, i) => {
      if (reveal === "sentences" && isPlainParagraphBlock(b)) {
        const sentences = splitSentencesMarkdownSafe(b);
        sentences.forEach((s) => out.push({ kind: "sentence", blockIndex: i, text: s }));
      } else {
        out.push({ kind: "block", blockIndex: i, text: b });
      }
    });

    return out;
  }, [blocks, reveal]);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [inView, setInView] = useState(!revealOnView);

  // Track viewport visibility (so we don't “finish revealing” while off-screen)
  useEffect(() => {
    if (!revealOnView) return;

    const el = containerRef.current;
    if (!el) return;

    const obs = new IntersectionObserver(
      (entries) => {
        const e = entries[0];
        setInView(Boolean(e?.isIntersecting));
      },
      // A bit strict so it triggers when the slide is actually “on stage”
      { threshold: 0.55 }
    );

    obs.observe(el);
    return () => obs.disconnect();
  }, [revealOnView]);

  const [visibleCount, setVisibleCount] = useState(
    reveal === "none" ? Number.MAX_SAFE_INTEGER : 0
  );

  // Reset on md change
  useEffect(() => {
    if (reveal === "none") {
      setVisibleCount(Number.MAX_SAFE_INTEGER);
    } else {
      setVisibleCount(0);
    }
  }, [cleaned, reveal]);

  // Reveal progression
  useEffect(() => {
    if (reveal === "none") return;

    // If we only reveal on view, don't start until visible
    if (revealOnView && !inView) {
      if (resetOnExit) setVisibleCount(0);
      return;
    }

    let cancelled = false;
    let t: number | null = null;

    const step = (next: number) => {
      if (cancelled) return;
      setVisibleCount(next);
      if (next >= items.length) return;

      t = window.setTimeout(() => step(next + 1), staggerMs);
    };

    t = window.setTimeout(() => step(1), initialDelayMs);

    return () => {
      cancelled = true;
      if (t != null) window.clearTimeout(t);
    };
  }, [reveal, revealOnView, resetOnExit, inView, items.length, staggerMs, initialDelayMs]);

  return (
    <div
      ref={containerRef}
      className={[
        // base prose styling (tailwind-typography)
        "prose max-w-none",
        // color + dark mode
        "prose-neutral dark:prose-invert",
        // bigger, more readable story text
        "text-[16px] leading-7 sm:text-[18px] sm:leading-8 lg:text-[20px] lg:leading-9",
        // slightly roomier spacing between blocks
        "prose-p:my-4 prose-li:my-2 prose-strong:font-semibold",
      ].join(" ")}
    >
      {reveal === "none" ? (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleaned}</ReactMarkdown>
      ) : (
        <div className="space-y-5">
          {blocks.map((block, blockIdx) => {
            const blockItems = items.filter((it) => it.blockIndex === blockIdx);
            if (blockItems.length === 0) return null;

            // Non-paragraph blocks: reveal as a whole
            if (blockItems.length === 1 && blockItems[0].kind === "block") {
              const idx = items.indexOf(blockItems[0]);
              const show = idx < visibleCount;

              return (
                <div
                  key={`b-${blockIdx}`}
                  className={show ? "opacity-100 transition-opacity duration-500" : "opacity-0"}
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{blockItems[0].text}</ReactMarkdown>
                </div>
              );
            }

            // Paragraph split into sentences
            return (
              <p key={`p-${blockIdx}`} className="leading-relaxed">
                {blockItems.map((it) => {
                  const idx = items.indexOf(it);
                  const show = idx < visibleCount;

                  return (
                    <span
                      key={`s-${blockIdx}-${idx}`}
                      className={[
                        "inline transition-opacity duration-500",
                        show ? "opacity-100" : "opacity-0",
                      ].join(" ")}
                    >
                      <InlineMarkdown md={it.text} />{" "}
                    </span>
                  );
                })}
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
}
