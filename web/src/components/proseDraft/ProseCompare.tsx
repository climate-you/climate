"use client";

// Side-by-side view for reworking a story's prose: the committed text on the
// left, the draft on the right, lined up by section, with word counts and a
// word-level diff. Development tool only; see docs/runbooks/case-study-data.md.
import { useEffect, useRef, useState } from "react";
import type { ProseSection } from "./parts";
import css from "./proseCompare.module.css";

type Op = { t: string; op: "eq" | "del" | "ins" };

/** Word-level diff (LCS over words, whitespace kept with the word before). */
function diffWords(a: string, b: string): Op[] {
  const tok = (s: string) => s.match(/\S+\s*|\s+/g) ?? [];
  const A = tok(a);
  const B = tok(b);
  const key = (w: string) => w.trim();
  const n = A.length;
  const m = B.length;
  const L = new Uint16Array((n + 1) * (m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      L[i * (m + 1) + j] =
        key(A[i]) === key(B[j])
          ? L[(i + 1) * (m + 1) + j + 1] + 1
          : Math.max(L[(i + 1) * (m + 1) + j], L[i * (m + 1) + j + 1]);
  const out: Op[] = [];
  const push = (t: string, op: Op["op"]) => {
    const last = out[out.length - 1];
    if (last && last.op === op) last.t += t;
    else out.push({ t, op });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (key(A[i]) === key(B[j])) {
      push(B[j], "eq");
      i++;
      j++;
    } else if (L[(i + 1) * (m + 1) + j] >= L[i * (m + 1) + j + 1]) {
      push(A[i++], "del");
    } else {
      push(B[j++], "ins");
    }
  }
  while (i < n) push(A[i++], "del");
  while (j < m) push(B[j++], "ins");
  return out;
}

const words = (s: string) => (s.match(/\S+/g) ?? []).length;

type Props = {
  title: string;
  /** Where the draft lives, shown so the reader knows which file to edit. */
  draftPath: string;
  left: ProseSection[];
  right: ProseSection[];
  leftLabel?: string;
  rightLabel?: string;
};

export default function ProseCompare({
  title,
  draftPath,
  left,
  right,
  leftLabel = "Committed",
  rightLabel = "Draft",
}: Props) {
  const [mode, setMode] = useState<"side" | "diff">("side");
  const [texts, setTexts] = useState<Record<string, string>>({});
  const cells = useRef(new Map<string, HTMLElement>());

  // Read the rendered text after every render, so Fast Refresh edits to the
  // draft show up in the counts and the diff without a reload.
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      const next: Record<string, string> = {};
      cells.current.forEach((el, k) => (next[k] = el.innerText));
      setTexts((prev) =>
        JSON.stringify(prev) === JSON.stringify(next) ? prev : next,
      );
    });
    return () => cancelAnimationFrame(id);
  });

  const keys = [
    ...right.map((s) => s.key),
    ...left.map((s) => s.key).filter((k) => !right.some((s) => s.key === k)),
  ];
  const byKey = (list: ProseSection[], k: string) =>
    list.find((s) => s.key === k);
  const ref = (k: string) => (el: HTMLElement | null) => {
    if (el) cells.current.set(k, el);
    else cells.current.delete(k);
  };

  const total = (side: "l" | "r") =>
    keys.reduce((sum, k) => sum + words(texts[`${side}:${k}`] ?? ""), 0);

  return (
    <main className={css.page}>
      <header className={css.top}>
        <div>
          <h1>{title}</h1>
          <p className={css.hint}>
            Left is the committed page. Right is the draft being reworked in{" "}
            <code>{draftPath}</code>. Figures are placeholders carrying their
            captions. Development only.
          </p>
        </div>
        <div className={css.toggle} role="tablist">
          <button
            className={mode === "side" ? css.on : ""}
            onClick={() => setMode("side")}
          >
            Side by side
          </button>
          <button
            className={mode === "diff" ? css.on : ""}
            onClick={() => setMode("diff")}
          >
            Changes
          </button>
        </div>
      </header>
      <div className={css.colHeads}>
        <span>
          {leftLabel} · {total("l")} words
        </span>
        <span>
          {rightLabel} · {total("r")} words
        </span>
      </div>
      {keys.map((k) => {
        const l = byKey(left, k);
        const r = byKey(right, k);
        const lt = texts[`l:${k}`] ?? "";
        const rt = texts[`r:${k}`] ?? "";
        const same = lt === rt;
        return (
          <section key={k} className={css.row}>
            <h2 className={css.secHead}>
              {r?.title ?? l?.title}
              <span className={css.count}>
                {same ? "unchanged" : `${words(lt)} → ${words(rt)} words`}
              </span>
            </h2>
            <div className={mode === "side" ? css.cols : css.measure}>
              <div className={css.cell} ref={ref(`l:${k}`)}>
                {l?.body ?? (
                  <p className={css.gone}>Not in the committed page.</p>
                )}
              </div>
              <div
                className={`${css.cell} ${same ? "" : css.changed}`}
                ref={ref(`r:${k}`)}
              >
                {r?.body ?? <p className={css.gone}>Cut from the draft.</p>}
              </div>
            </div>
            {mode === "diff" ? (
              <div className={css.diff}>
                {same ? (
                  <span className={css.gone}>No change.</span>
                ) : (
                  diffWords(lt, rt).map((o, i) =>
                    o.op === "eq" ? (
                      <span key={i}>{o.t}</span>
                    ) : o.op === "del" ? (
                      <del key={i}>{o.t}</del>
                    ) : (
                      <ins key={i}>{o.t}</ins>
                    ),
                  )
                )}
              </div>
            ) : null}
          </section>
        );
      })}
    </main>
  );
}
