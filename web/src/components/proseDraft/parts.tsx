// Building blocks for a prose draft page (see ProseCompare). Charts are
// stand-ins: a draft page is for the words, so each figure is a labelled box
// carrying its caption. Workflow: docs/runbooks/case-study-data.md.
import type { ReactNode } from "react";
import css from "./proseCompare.module.css";

/** One section of a story. Sections with the same key are lined up. */
export type ProseSection = { key: string; title: string; body: ReactNode };

/** A source or note marker, shown as [n]. */
export function Ref({ n }: { n: number | string }) {
  return <sup className={css.ref}>[{n}]</sup>;
}

/** The story's blue "wet" emphasis. */
export function Wet({ children }: { children: ReactNode }) {
  return <span className={css.wet}>{children}</span>;
}

/** A placeholder for a chart or map, with its caption if it has one. */
export function Fig({
  name,
  children,
}: {
  name: string;
  children?: ReactNode;
}) {
  return (
    <div className={css.fig}>
      <p className={css.figName}>Figure: {name}</p>
      {children ? <div className={css.figCap}>{children}</div> : null}
    </div>
  );
}

/** Emphasis used for a record-setting row in a draft table. */
export const recordClass = css.record;
/** Plain table styling for a draft table. */
export const tableClass = css.table;
