"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function normalize(md: string) {
  const text = md.replace(/\r\n/g, "\n");
  const lines = text.split("\n");

  // Compute common leading indent across non-empty lines
  let minIndent = Infinity;
  for (const line of lines) {
    if (!line.trim()) continue;
    const m = line.match(/^(\s+)/);
    if (!m) {
      minIndent = 0;
      break;
    }
    minIndent = Math.min(minIndent, m[1].length);
  }

  const dedented =
    minIndent && minIndent !== Infinity
      ? lines
          .map((l) =>
            l.startsWith(" ".repeat(minIndent)) ? l.slice(minIndent) : l,
          )
          .join("\n")
      : lines.join("\n");

  return dedented.trim();
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
  let inEm = false; // <-- NEW: track emphasis (_..._ or *...*)

  const n = text.length;

  const isEscaped = (i: number) => i > 0 && text[i - 1] === "\\";
  const isEmBoundary = (prev: string, next: string) => {
    // A lightweight heuristic: allow emphasis toggles when marker is at a "word boundary"
    // e.g. start of string or preceded by whitespace/punct, and followed by non-whitespace.
    const prevOk = prev === "" || /\s|[([{"'“‘]/.test(prev);
    const nextOk = next !== "" && !/\s/.test(next);
    return prevOk && nextOk;
  };

  for (let i = 0; i < n; i++) {
    const ch = text[i];

    // Toggle inline code on backticks (ignore escaped)
    if (ch === "`" && !isEscaped(i)) {
      inCode = !inCode;
      continue;
    }

    // Toggle bold on ** (ignore escaped)
    if (ch === "*" && i + 1 < n && text[i + 1] === "*" && !isEscaped(i)) {
      inBold = !inBold;
      i++; // consume second '*'
      continue;
    }

    // Toggle emphasis on _..._ or *...* (ignore escaped).
    // We only do this when NOT in code/bold, and when marker is at a plausible boundary.
    if (!inCode && !inBold && !isEscaped(i) && (ch === "_" || ch === "*")) {
      // For '*' italics, ensure it's not part of '**' (already handled above)
      if (ch === "*" && i + 1 < n && text[i + 1] === "*") {
        // skip; handled by bold toggling
      } else {
        const prev = i > 0 ? text[i - 1] : "";
        const next = i + 1 < n ? text[i + 1] : "";
        if (isEmBoundary(prev, next)) {
          inEm = !inEm;
          continue;
        }
      }
    }

    // Only split on punctuation when not inside code/bold/emphasis
    if (
      !inCode &&
      !inBold &&
      !inEm &&
      (ch === "." || ch === "!" || ch === "?")
    ) {
      const next = i + 1 < n ? text[i + 1] : "";
      const next2 = i + 2 < n ? text[i + 2] : "";

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
        sentences.forEach((s) =>
          out.push({ kind: "sentence", blockIndex: i, text: s }),
        );
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
      { threshold: 0.55 },
    );

    obs.observe(el);
    return () => obs.disconnect();
  }, [revealOnView]);

  const [visibleCount, setVisibleCount] = useState(
    reveal === "none" ? Number.MAX_SAFE_INTEGER : 0,
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
  }, [
    reveal,
    revealOnView,
    resetOnExit,
    inView,
    items.length,
    staggerMs,
    initialDelayMs,
  ]);

  return (
    <div
      ref={containerRef}
      className={[
        // Support for lists
        "caption-md",
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
                  className={
                    show
                      ? "opacity-100 transition-opacity duration-500"
                      : "opacity-0"
                  }
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {blockItems[0].text}
                  </ReactMarkdown>
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
      <style jsx>{`
        :global(.caption-md ul) {
          list-style: disc !important;
          padding-left: 1.4rem !important;
          margin: 0.75rem 0 !important;
        }
        :global(.caption-md ol) {
          list-style: decimal !important;
          padding-left: 1.4rem !important;
          margin: 0.75rem 0 !important;
        }
        :global(.caption-md li) {
          margin: 0.25rem 0 !important;
        }
      `}</style>
    </div>
  );
}
