"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import DownloadIcon from "@/components/story/DownloadIcon";
import { downloadSvgWithAttribution } from "@/lib/story/download";
import storyStyles from "@/components/story/story.module.css";
import s from "./summerStory.module.css";
import {
  BASE_LABEL,
  DATA,
  EUROPE,
  STORY_COUNTRIES,
  type YearTrace,
} from "./storyData";

// Every chart here is a port of the corresponding function in
// experiments/build_story_draft.py: same coordinate system, same marks, so the
// published page matches the reviewed draft.

// The Copernicus licence prescribes this wording for modified products.
const SOURCE =
  "Contains modified Copernicus Climate Change Service information 2026";

/**
 * True while the chart column is too narrow for the wide geometry.
 *
 * Scaling a 680-unit viewBox down to a phone's ~337px renders 12px type at
 * 6px, so the charts that have to fit whole switch to a narrower viewBox
 * instead, which draws close to 1:1 and keeps the type at its nominal size.
 */
function useNarrowChart(threshold = 430): [React.RefObject<HTMLDivElement | null>, boolean] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w > 0) setNarrow(w < threshold);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [threshold]);
  return [ref, narrow];
}

/** Country name to a filename-safe slug, so exports say who they are about. */
const slug = (n: string) => n.toLowerCase().replace(/\s+/g, "-");

function dayOf(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86400000;
}
const DAY_MAY1 = dayOf("2026-05-01");
const DAY_JUN1 = dayOf("2026-06-01");
const DAY_END = dayOf(DATA.wet[1]);
const DAY_WET = dayOf(DATA.wet[0]);

type EndLabel = { key: string; y: number; text: string; cls: string };

/** Nudge labels apart vertically so none sit closer than `gap`, keeping order. */
function spreadLabels(labels: EndLabel[], gap: number): EndLabel[] {
  const sorted = [...labels].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i].y - sorted[i - 1].y < gap)
      sorted[i] = { ...sorted[i], y: sorted[i - 1].y + gap };
  }
  // Pushing down can drift the whole stack; pull back up from the bottom if
  // the last label moved far from where it started, then re-check spacing.
  const drift =
    sorted[sorted.length - 1].y -
    labels.reduce((m, l) => Math.max(m, l.y), -Infinity);
  if (drift > 0) {
    for (let i = sorted.length - 1; i >= 0; i--)
      sorted[i] = { ...sorted[i], y: sorted[i].y - drift / 2 };
    for (let i = sorted.length - 2; i >= 0; i--) {
      if (sorted[i + 1].y - sorted[i].y < gap)
        sorted[i] = { ...sorted[i], y: sorted[i + 1].y - gap };
    }
  }
  return sorted;
}

type FrameProps = {
  /** Shown above the chart, and used as the exported PNG's title. */
  title: string;
  subtitle?: string;
  filename: string;
  caption: ReactNode;
  legend?: ReactNode;
  /** Controls placed between the title and the chart. */
  controls?: ReactNode;
  /** Narrowest the chart may be drawn before it scrolls, in px. */
  minWidth?: number;
  narrowOk?: boolean;
  /** Measured for charts that swap geometry when the column is narrow. */
  wrapRefExternal?: React.RefObject<HTMLDivElement | null>;
  children: ReactNode;
};

/** Chart card: title, optional controls, the SVG, legend, caption. */
function Frame({
  title,
  subtitle,
  filename,
  caption,
  legend,
  controls,
  minWidth,
  narrowOk,
  wrapRefExternal,
  children,
}: FrameProps) {
  const ownRef = useRef<HTMLDivElement | null>(null);
  const wrapRef = wrapRefExternal ?? ownRef;
  const handleDownload = () => {
    const wrap = wrapRef.current;
    const svg = wrap?.querySelector("svg");
    if (!wrap || !svg) return;
    // Exports are composited on white, so bake the light palette while the
    // styles are serialized (synchronous, never painted).
    wrap.classList.add(storyStyles.exportLight);
    try {
      downloadSvgWithAttribution(
        svg,
        { title, subtitle, sourceText: SOURCE },
        filename,
      );
    } finally {
      wrap.classList.remove(storyStyles.exportLight);
    }
  };
  return (
    <figure className={s.fig}>
      <div className={s.figHead}>
        <div>
          <h3 className={s.figTitle}>{title}</h3>
          {subtitle ? <p className={s.figSub}>{subtitle}</p> : null}
        </div>
        <DownloadIcon
          label="Download chart"
          onClick={handleDownload}
          className={s.figDl}
        />
      </div>
      {controls}
      <div
        ref={wrapRef}
        className={`${s.chartWrap}${narrowOk ? ` ${s.narrowOk}` : ""}`}
        style={
          // Explicitly against undefined: a narrow chart passes 0, which is a
          // meaningful "no floor" and must not fall through to the default.
          minWidth !== undefined
            ? ({ "--chart-min": `${minWidth}px` } as CSSProperties)
            : undefined
        }
      >
        {children}
      </div>
      {legend}
      <figcaption className={s.figcap}>{caption}</figcaption>
    </figure>
  );
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className={s.legend}>
      {items.map(([color, label]) => (
        <span key={label}>
          <i style={{ background: color }} />
          {label}
        </span>
      ))}
    </div>
  );
}

/** A row of mutually exclusive choices, styled like the site's step buttons. */
function Choices<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className={s.tabs} role="tablist" aria-label={label}>
      {options.map((o) => (
        <button
          key={o}
          type="button"
          role="tab"
          aria-selected={o === value}
          onClick={() => onChange(o)}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

const EU_COLOR = "var(--heat)";
const OTHER_WARM = "var(--warm)";
const OTHER_BLUE = "var(--blue)";

// ─── 02: heat episodes through the summer ───────────────────────────────────
const TIMELINE_ORDER = [
  "Italy",
  "France",
  "Spain",
  "Russia",
  "Canada",
  "United Kingdom",
  "China",
  "Japan",
  "Germany",
  "United States",
  "Portugal",
  "Greece",
];
const TIMELINE_SCOPES = ["Northern hemisphere", "Europe only"] as const;

export function HeatTimeline() {
  const [scope, setScope] =
    useState<(typeof TIMELINE_SCOPES)[number]>("Northern hemisphere");
  const rows =
    scope === "Europe only"
      ? TIMELINE_ORDER.filter((n) => EUROPE.has(n))
      : TIMELINE_ORDER;

  const [wrapRef, narrow] = useNarrowChart();
  // Narrow: a viewBox close to the rendered width, so nothing is scaled down.
  const W = narrow ? 336 : 680,
    L = narrow ? 86 : 104,
    Rt = narrow ? 8 : 14,
    T = 22;
  const H = rows.length * 22 + 42 + (T - 10);
  const pw = W - L - Rt;
  const span = DAY_END - DAY_MAY1;
  const X = (day: number) => L + ((day - DAY_MAY1) / span) * pw;
  const xw = X(DAY_WET);
  const months: [string, string][] = [
    ["2026-05-01", "May"],
    ["2026-06-01", "Jun"],
    ["2026-07-01", "Jul"],
    ["2026-08-01", "Aug"],
  ];
  // Two of the twelve names are long enough to need the full gutter; at narrow
  // width they use the forms a reader will still recognise.
  const shortName = (n: string) =>
    narrow
      ? n.replace("United Kingdom", "UK").replace("United States", "US")
      : n;
  return (
    <Frame
      title="When each country was in a heat episode"
      subtitle="Three or more consecutive days above its own local 90th percentile, May to August 2026"
      filename="summer-2026-heat-episodes.png"
      minWidth={narrow ? 0 : 430}
      wrapRefExternal={wrapRef}
      controls={
        <Choices
          options={TIMELINE_SCOPES}
          value={scope}
          onChange={setScope}
          label="Which countries to show"
        />
      }
      legend={
        scope === "Europe only" ? undefined : (
          <Legend
            items={[
              [EU_COLOR, "western Europe"],
              [OTHER_WARM, "rest of the northern hemisphere"],
            ]}
          />
        )
      }
      caption={
        <>
          Each bar is three or more consecutive days above that country&apos;s
          own {BASE_LABEL} 90th percentile <b>of daily maximum temperature</b>{" "}
          for the date, on its area-weighted national average. The blue band is
          the late-August rain.
        </>
      }
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Heat episodes through the summer, by country"
      >
        <rect
          x={xw}
          y={T}
          width={W - Rt - xw}
          height={H - 28 - T}
          fill="var(--blue)"
          opacity={0.08}
        />
        <text
          x={W - Rt - 4}
          y={T - 8}
          textAnchor="end"
          className="sc-quad sc-quad-blue"
        >
          rain returns
        </text>
        {months.map(([d, lab]) => {
          const x = X(dayOf(d));
          return (
            <g key={lab}>
              <line x1={x} x2={x} y1={T} y2={H - 28} className="sc-grid" />
              <text x={x + 4} y={H - 12} className="sc-tick">
                {lab}
              </text>
            </g>
          );
        })}
        {rows.map((n, i) => {
          const y = T + i * 22 + 3;
          const eu = EUROPE.has(n);
          return (
            <g key={n}>
              <text
                x={L - 10}
                y={y + 11}
                textAnchor="end"
                className={`sc-rowlab${eu ? " sc-rowlab-hi" : ""}`}
              >
                {shortName(n)}
              </text>
              <line
                x1={L}
                x2={W - Rt}
                y1={y + 7.5}
                y2={y + 7.5}
                className="sc-tlbase"
              />
              {(DATA.episodes[n] ?? []).map((e) => {
                const x0 = X(dayOf(e.a));
                const x1 = X(dayOf(e.b));
                return (
                  <rect
                    key={e.a}
                    x={x0}
                    y={y}
                    width={Math.max(3, x1 - x0)}
                    height={15}
                    rx={4}
                    className={eu ? "sc-ev-eu" : "sc-ev-other"}
                  >
                    <title>
                      {`${n}: ${e.a} to ${e.b}, ${e.d} days, peak ${e.peak.toFixed(1)} °C`}
                    </title>
                  </rect>
                );
              })}
            </g>
          );
        })}
      </svg>
    </Frame>
  );
}

// ─── 03: rainfall by period, % of normal ────────────────────────────────────
function cellColor(v: number): string {
  if (v < 100) {
    const t = Math.max(0, Math.min(1, (100 - v) / 65));
    return `color-mix(in oklab, var(--dry) ${Math.round(t * 82)}%, var(--paper))`;
  }
  const t = Math.max(0, Math.min(1, (v - 100) / 65));
  return `color-mix(in oklab, var(--blue) ${Math.round(t * 72)}%, var(--paper))`;
}

export function RainGrid() {
  const { periods, names, grid } = DATA.monthly;
  const cw = 118,
    ch = 34,
    L = 132,
    T = 34;
  const W = L + cw * periods.length + 16;
  const H = T + ch * names.length + 14;
  return (
    <Frame
      title="When the rain failed, country by country"
      subtitle={`Rainfall as a percentage of the ${BASE_LABEL} normal for each period`}
      filename="summer-2026-rainfall-by-period.png"
      narrowOk
      caption={
        <>
          Brown = drier than normal, blue = wetter. Iberia was already failing
          in June; Britain&apos;s drought did not begin until July.
        </>
      }
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Rainfall as a percentage of normal by country and period"
      >
        {periods.map((lab, j) => (
          <text
            key={lab}
            x={L + j * cw + cw / 2}
            y={T - 12}
            textAnchor="middle"
            className="sc-tick"
          >
            {lab}
          </text>
        ))}
        {names.map((n, i) => {
          const y = T + i * ch;
          return (
            <g key={n}>
              <text
                x={L - 10}
                y={y + 21}
                textAnchor="end"
                className="sc-rowlab sc-rowlab-hi"
              >
                {n}
              </text>
              {grid[n].map((v, j) => {
                const x = L + j * cw;
                return (
                  <g key={periods[j]}>
                    <rect
                      x={x + 1}
                      y={y + 2}
                      width={cw - 3}
                      height={ch - 5}
                      rx={3}
                      fill={cellColor(v)}
                    >
                      <title>{`${n}, ${periods[j]}: ${Math.round(v)}% of normal`}</title>
                    </rect>
                    <text
                      x={x + cw / 2}
                      y={y + 21}
                      textAnchor="middle"
                      className={`sc-cell${v < 60 || v > 140 ? " sc-cell-strong" : ""}`}
                    >
                      {Math.round(v)}%
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </Frame>
  );
}

// ─── 04: heat days against rainfall ─────────────────────────────────────────
const SCATTER_OFFSETS: Record<string, [number, number]> = {
  Italy: [10, -6],
  France: [-9, -9],
  Spain: [10, 4],
  Portugal: [10, 4],
  Germany: [11, 4],
  "United Kingdom": [-9, -9],
  Greece: [10, 4],
  "United States": [-11, 15],
  China: [10, -8],
  India: [10, 4],
  Japan: [-10, -6],
  Canada: [10, 15],
  Russia: [10, 15],
  Turkey: [10, 4],
  Mexico: [10, 4],
  Pakistan: [10, 4],
  Netherlands: [-9, 12],
};

export function HeatRainScatter() {
  const W = 680,
    H = 430,
    L = 66,
    Rt = 16,
    T = 16,
    B = 44;
  const pw = W - L - Rt,
    ph = H - T - B;
  const xmax = 50,
    ymin = 35,
    ymax = 125;
  const X = (v: number) => L + (v / xmax) * pw;
  const Y = (v: number) =>
    T + ((ymax - Math.min(Math.max(v, ymin), ymax)) / (ymax - ymin)) * ph;
  // Both axes cover 1 Jun - 15 Aug. The unrestricted May-Aug count would plot
  // heat over a wider span than the rainfall it is being compared against.
  const points = Object.entries(DATA.daysInDryWindow)
    .filter(([n]) => n in DATA.rain)
    .sort((a, b) => b[1] - a[1]);
  // Labels in the four corners of the plot box, naming the kind of summer each
  // corner describes. They are direction hints, not a classification: the only
  // line with a defined meaning is 100% of normal, and it is already drawn.
  const xmid = X(28);
  // "Dry" starts at 80% of normal, not 100%: a country at 99% is not dry, and
  // bounding the corner at the 100% line swept those in.
  const DRY_AT = 80;
  // Only the right-hand pair. The axis counts days of unusual heat, so a low
  // count means "no hotter than usual", not "cool", and labelling the left
  // corners that way would misdescribe every country on that side.
  const corners: [number, number, "start" | "end", string, string][] = [
    [W - Rt - 8, T + 14, "end", "hot and wet", "sc-quad sc-quad-blue"],
    [W - Rt - 8, H - B - 10, "end", "hot and dry", "sc-quad"],
  ];
  return (
    <Frame
      title="Heat and rain together, one dot per country"
      subtitle="Both measured over the same dates, 1 June to 15 August 2026"
      filename="summer-2026-heat-vs-rain.png"
      minWidth={470}
      legend={
        <Legend
          items={[
            [EU_COLOR, "western Europe"],
            [OTHER_BLUE, "rest of the northern hemisphere"],
          ]}
        />
      }
      caption={
        <>
          The shaded corner is more than four weeks in heat episodes on less
          than 80% of normal rain. Only Spain, France and Italy are in it.
          Russia was in heat episodes almost as long and still finished on{" "}
          {Math.round(DATA.rain.Russia.dry.pct)}% of its normal rain; Canada,
          China and Japan sit on or above the 100% line.
        </>
      }
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Heat episodes against rainfall by country"
      >
        <rect
          x={xmid}
          y={Y(DRY_AT)}
          width={X(xmax) - xmid}
          height={Y(ymin) - Y(DRY_AT)}
          fill="var(--dry)"
          opacity={0.09}
        />
        {corners.map(([x, y, anchor, text, cls]) => (
          <text key={text} x={x} y={y} textAnchor={anchor} className={cls}>
            {text}
          </text>
        ))}
        {[50, 75, 100, 125].map((v) => (
          <g key={v}>
            <line
              x1={L}
              x2={W - Rt}
              y1={Y(v)}
              y2={Y(v)}
              className={v === 100 ? "sc-baseline" : "sc-grid"}
            />
            <text x={L - 8} y={Y(v) + 4} textAnchor="end" className="sc-tick">
              {v}%
            </text>
          </g>
        ))}
        {[0, 10, 20, 30, 40].map((v) => (
          <text
            key={v}
            x={X(v)}
            y={H - B + 20}
            textAnchor="middle"
            className="sc-tick"
          >
            {v}
          </text>
        ))}
        <text x={L + pw / 2} y={H - 6} textAnchor="middle" className="sc-axlab">
          days in heat episodes, 1 Jun – 15 Aug 2026
        </text>
        <text
          transform={`translate(15,${T + ph / 2}) rotate(-90)`}
          textAnchor="middle"
          className="sc-axlab"
        >
          rainfall 1 Jun – 15 Aug, % of normal
        </text>
        {points.map(([n, d]) => {
          const r = DATA.rain[n].dry.pct;
          const eu = EUROPE.has(n);
          const cx = X(d),
            cy = Y(r);
          const [dx, dy] = SCATTER_OFFSETS[n] ?? [9, 4];
          return (
            <g key={n}>
              <circle
                cx={cx}
                cy={cy}
                r={6}
                className={`sc-pt ${eu ? "sc-pt-eu" : "sc-pt-other"}`}
              >
                <title>{`${n}: ${d} days in heat episodes, ${Math.round(r)}% of normal rainfall, 1 Jun – 15 Aug`}</title>
              </circle>
              <text
                x={cx + dx}
                y={cy + dy}
                textAnchor={dx > 0 ? "start" : "end"}
                className={`sc-ptlab${eu ? " sc-ptlab-eu" : ""}`}
              >
                {n}
              </text>
            </g>
          );
        })}
      </svg>
    </Frame>
  );
}

// ─── 05: cumulative rainfall against the normal ─────────────────────────────
// One colour per country, reused by its 2026 line, its dashed normal, and both
// end labels, so a dashed line is readable as belonging to a country.
const CUM_CLASS: Record<string, { line: string; lab: string }> = {
  Portugal: { line: "sc-line-dry", lab: "sc-endlab-dry" },
  Spain: { line: "sc-line-heat", lab: "sc-endlab-heat" },
  France: { line: "sc-line-blue", lab: "sc-endlab-blue" },
};
const CUM_COUNTRIES = Object.keys(DATA.cum);
// Sixteen lines at once is unreadable, so "All" means the three the section is
// about; every country is still available on its own.
const CUM_ALL = CUM_COUNTRIES.filter((c) => c in CUM_CLASS);
const CUM_ALL_LABEL = "SW Europe";
const CUM_OPTIONS = [CUM_ALL_LABEL, ...CUM_COUNTRIES];

function cumClass(n: string) {
  // Countries outside the trio have no colour of their own; shown alone there
  // is nothing to tell them apart from, so they take the emphasis colour.
  return CUM_CLASS[n] ?? { line: "sc-line-heat", lab: "sc-endlab-heat" };
}

export function CumulativeRain() {
  const [pick, setPick] = useState<string>(CUM_ALL_LABEL);
  const shown = pick === CUM_ALL_LABEL ? CUM_ALL : [pick];

  const W = 680,
    H = 360,
    L = 54,
    Rt = 132,
    T = 30,
    B = 40;
  const pw = W - L - Rt,
    ph = H - T - B;
  const span = DAY_END - DAY_JUN1;
  // The vertical scale stays fixed across selections so switching country does
  // not silently rescale the gap the chart is about.
  let hi = 0;
  for (const d of Object.values(DATA.cum))
    for (const [, v] of [...d.norm, ...d.obs]) hi = Math.max(hi, v);
  hi *= 1.05;
  const X = (iso: string) => L + ((dayOf(iso) - DAY_JUN1) / span) * pw;
  const Y = (v: number) => T + ((hi - v) / hi) * ph;
  const xw = X(DATA.wet[0]);
  // Greece got no August rain, so the band and its label would assert
  // something the line plainly contradicts.
  const showRainReturn = shown.some(
    (n) => DATA.rain[n] && DATA.rain[n].wet.pct >= 110,
  );
  const endLabel = `${new Date(DATA.wet[1] + "T00:00:00Z").getUTCDate()} Aug`;
  const lx = X(DATA.wet[1]) + 7;
  const single = shown.length === 1;
  const endLabels = spreadLabels(
    shown.flatMap((n) => {
      const d = DATA.cum[n];
      const k = cumClass(n);
      const lv = d.obs[d.obs.length - 1][1];
      const nv = d.norm[d.norm.length - 1][1];
      return [
        {
          key: `${n}-obs`,
          y: Y(lv),
          text: `${single ? "2026" : n} ${Math.round(lv)} mm`,
          cls: `sc-endlab ${k.lab}`,
        },
        {
          key: `${n}-norm`,
          y: Y(nv),
          text: `normal ${Math.round(nv)} mm`,
          cls: `sc-endlab sc-normlab ${k.lab}`,
        },
      ];
    }),
    13,
  );
  return (
    <Frame
      title={
        single
          ? `${pick}: how far behind normal the rain fell`
          : "How far behind normal the rain fell"
      }
      subtitle={`Cumulative rainfall since 1 June 2026, against the ${BASE_LABEL} normal for the same dates`}
      filename={`summer-2026-cumulative-rainfall${single ? `-${slug(pick)}` : ""}.png`}
      minWidth={470}
      controls={
        <Choices
          options={CUM_OPTIONS}
          value={pick}
          onChange={setPick}
          label="Country"
        />
      }
      legend={
        <div className={s.legend}>
          <span>
            <svg width="22" height="10" aria-hidden="true">
              <line
                x1="0"
                y1="5"
                x2="22"
                y2="5"
                stroke="var(--ink)"
                strokeWidth="2.2"
              />
            </svg>{" "}
            2026
          </span>
          <span>
            <svg width="22" height="10" aria-hidden="true">
              <line
                x1="0"
                y1="5"
                x2="22"
                y2="5"
                stroke="var(--ink)"
                strokeWidth="1.4"
                strokeDasharray="4 3"
                opacity="0.6"
              />
            </svg>{" "}
            {BASE_LABEL} normal
          </span>
        </div>
      }
      caption={
        <>
          The solid line is this year; the dashed line of the same colour is
          what that country would normally have accumulated by the same date.
          France never stops receiving rain, so its solid line keeps climbing;
          the point is how far below its own dashed line it stays.
        </>
      }
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Cumulative rainfall June to August 2026 against the normal"
      >
        {showRainReturn ? (
          <>
            <rect
              x={xw}
              y={T}
              width={W - Rt - xw}
              height={ph}
              fill="var(--blue)"
              opacity={0.07}
            />
            <text x={xw + 4} y={T - 10} className="sc-quad sc-quad-blue">
              rain returns
            </text>
          </>
        ) : null}
        {[50, 100, 150, 200, 250]
          .filter((v) => v <= hi)
          .map((v) => (
            <g key={v}>
              <line x1={L} x2={W - Rt} y1={Y(v)} y2={Y(v)} className="sc-grid" />
              <text x={L - 8} y={Y(v) + 4} textAnchor="end" className="sc-tick">
                {v}
              </text>
            </g>
          ))}
        {(
          [
            ["2026-06-01", "Jun"],
            ["2026-07-01", "Jul"],
            ["2026-08-01", "Aug"],
          ] as [string, string][]
        ).map(([d, lab]) => (
          <g key={lab}>
            <line x1={X(d)} x2={X(d)} y1={T} y2={H - B} className="sc-grid" />
            <text x={X(d) + 4} y={H - B + 18} className="sc-tick">
              {lab}
            </text>
          </g>
        ))}
        <text
          transform={`translate(13,${T + ph / 2}) rotate(-90)`}
          textAnchor="middle"
          className="sc-axlab"
        >
          cumulative rainfall, mm
        </text>
        {shown.map((n) => {
          const d = DATA.cum[n];
          const k = cumClass(n);
          const norm = d.norm
            .map(([t, v]) => `${X(t).toFixed(1)},${Y(v).toFixed(1)}`)
            .join(" ");
          const obs = d.obs
            .map(([t, v]) => `${X(t).toFixed(1)},${Y(v).toFixed(1)}`)
            .join(" ");
          const lv = d.obs[d.obs.length - 1][1];
          const nv = d.norm[d.norm.length - 1][1];
          return (
            <g key={n}>
              <polyline points={norm} className={`${k.line} sc-normline`}>
                <title>{`${n}: ${BASE_LABEL} normal, ${Math.round(nv)} mm by ${endLabel}`}</title>
              </polyline>
              <polyline points={obs} className={k.line}>
                <title>{`${n}: 2026, ${Math.round(lv)} mm by ${endLabel}`}</title>
              </polyline>
            </g>
          );
        })}
        {endLabels.map((l) => (
          <text key={l.key} x={lx} y={l.y + 4} className={l.cls}>
            {l.text}
          </text>
        ))}
      </svg>
    </Frame>
  );
}

// ─── 07: every summer since 1979, heat against rain ─────────────────────────
function JointSvg({ country }: { country: string }) {
  const pts = DATA.joint[country];
  const W = 680,
    H = 400,
    L = 54,
    Rt = 18,
    T = 14,
    B = 44;
  const pw = W - L - Rt,
    ph = H - T - B;
  const x0 = 30,
    x1 = 165,
    y0 = -2.6,
    y1 = 3.9;
  const X = (v: number) =>
    L + ((Math.min(Math.max(v, x0), x1) - x0) / (x1 - x0)) * pw;
  const Y = (v: number) => T + ((y1 - v) / (y1 - y0)) * ph;
  const cur = pts.find((q) => q[0] === 2026)!;
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`Every June to August since 1979 in ${country}`}
    >
      <rect
        x={L}
        y={T}
        width={X(cur[2]) - L}
        height={Y(cur[1]) - T}
        fill="var(--dry)"
        opacity={0.1}
      />
      <text x={L + 4} y={T + 16} textAnchor="start" className="sc-quad">
        hotter and drier than 2026
      </text>
      {[-2, -1, 0, 1, 2, 3].map((v) => (
        <g key={v}>
          <line
            x1={L}
            x2={W - Rt}
            y1={Y(v)}
            y2={Y(v)}
            className={v === 0 ? "sc-baseline" : "sc-grid"}
          />
          <text x={L - 8} y={Y(v) + 4} textAnchor="end" className="sc-tick">
            {v > 0 ? `+${v}` : v}
          </text>
        </g>
      ))}
      {[50, 75, 100, 125, 150].map((v) => (
        <g key={v}>
          <line
            x1={X(v)}
            x2={X(v)}
            y1={T}
            y2={H - B}
            className={v === 100 ? "sc-baseline" : "sc-grid"}
          />
          <text x={X(v)} y={H - B + 20} textAnchor="middle" className="sc-tick">
            {v}%
          </text>
        </g>
      ))}
      <text x={L + pw / 2} y={H - 6} textAnchor="middle" className="sc-axlab">
        June–August rainfall, % of {BASE_LABEL} normal
      </text>
      <text
        transform={`translate(13,${T + ph / 2}) rotate(-90)`}
        textAnchor="middle"
        className="sc-axlab"
      >
        June–August temperature anomaly, °C
      </text>
      {pts
        .filter((q) => q[0] !== 2026)
        .map(([y, ta, pr]) => (
          <circle
            key={y}
            cx={X(pr)}
            cy={Y(ta)}
            r={4}
            className={`sc-yr${y >= 2011 ? " sc-yr-recent" : ""}`}
          >
            <title>{`${y}: ${ta >= 0 ? "+" : ""}${ta.toFixed(2)} °C, ${Math.round(pr)}%`}</title>
          </circle>
        ))}
      <circle cx={X(cur[2])} cy={Y(cur[1])} r={8} className="sc-cur">
        <title>{`2026: +${cur[1].toFixed(2)} °C, ${Math.round(cur[2])}%`}</title>
      </circle>
      <text x={X(cur[2]) + 13} y={Y(cur[1]) + 4} className="sc-curlab">
        2026
      </text>
    </svg>
  );
}

export function JointHistoryPicker({ initial = "France" }: { initial?: string }) {
  const [country, setCountry] = useState(initial);
  const r = DATA.ranks[country];
  return (
    <Frame
      title={`${country}: every summer since 1979, heat against rain`}
      subtitle="One dot per June–August, with 2026 highlighted. The shaded corner is hotter and drier than 2026."
      filename={`summer-2026-history-${slug(country)}.png`}
      minWidth={470}
      controls={
        <Choices
          options={STORY_COUNTRIES}
          value={country}
          onChange={setCountry}
          label="Country"
        />
      }
      caption={
        <>
          <b>{country} 2026:</b>{" "}
          {r.hotter === 0
            ? "no summer in the record has been hotter"
            : `${r.hotter} ${r.hotter === 1 ? "summer has" : "summers have"} been hotter`}
          , and{" "}
          {r.drier === 0
            ? "none has been drier"
            : `${r.drier} ${r.drier === 1 ? "has" : "have"} been drier`}
          , out of {r.n}. It finished {r.anomaly >= 0 ? "+" : ""}
          {r.anomaly.toFixed(2)}&#8202;°C against the {BASE_LABEL} average on{" "}
          {Math.round(r.pct)}% of its normal rain.
        </>
      }
    >
      <JointSvg country={country} />
    </Frame>
  );
}

// ─── 07: daily maximum, every baseline year in grey, 2026 in red ────────────
function tracePath(
  t: YearTrace,
  X: (d: number) => number,
  Y: (v: number) => number,
): string {
  return t.v.map((v, i) => `${X(t.d0 + i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
}

function SpaghettiSvg({ country }: { country: string }) {
  const years = DATA.spaghetti[country];
  const W = 680,
    H = 320,
    L = 46,
    Rt = 14,
    T = 12,
    B = 40;
  const pw = W - L - Rt,
    ph = H - T - B;
  const d0 = 60,
    d1 = 240,
    lo = 0,
    hi = 44;
  const X = (d: number) => L + ((d - d0) / (d1 - d0)) * pw;
  const Y = (v: number) => T + ((hi - v) / (hi - lo)) * ph;
  const months: [number, string][] = [
    [60, "Mar"],
    [91, "Apr"],
    [121, "May"],
    [152, "Jun"],
    [182, "Jul"],
    [213, "Aug"],
  ];
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`Daily maximum temperature, ${country}`}
    >
      {[10, 20, 30, 40].map((v) => (
        <g key={v}>
          <line x1={L} x2={W - Rt} y1={Y(v)} y2={Y(v)} className="sc-grid" />
          <text x={L - 8} y={Y(v) + 4} textAnchor="end" className="sc-tick">
            {v}°
          </text>
        </g>
      ))}
      {months.map(([doy, lab]) => (
        <g key={lab}>
          <line x1={X(doy)} x2={X(doy)} y1={T} y2={H - B} className="sc-grid" />
          <text x={X(doy) + 4} y={H - B + 18} className="sc-tick">
            {lab}
          </text>
        </g>
      ))}
      {Object.entries(years)
        .filter(([y]) => y !== "2026")
        .map(([y, t]) => (
          <polyline key={y} points={tracePath(t, X, Y)} className="sc-past" />
        ))}
      {years["2026"] ? (
        <polyline points={tracePath(years["2026"], X, Y)} className="sc-now" />
      ) : null}
      <text x={W - Rt - 6} y={T + 16} textAnchor="end" className="sc-curlab">
        {country} 2026
      </text>
      <text x={W - Rt - 6} y={T + 32} textAnchor="end" className="sc-tick">
        {BASE_LABEL} in grey
      </text>
    </svg>
  );
}

export function SpaghettiTabs({ initial = "France" }: { initial?: string }) {
  const available = STORY_COUNTRIES.filter((c) => DATA.spaghetti[c]);
  const [active, setActive] = useState(
    available.includes(initial) ? initial : available[0],
  );
  if (!available.length) return null;
  return (
    <Frame
      title="Every day of 2026 against every day of the baseline"
      subtitle="Daily maximum temperature, area-weighted over the country, March to the end of August"
      filename={`summer-2026-daily-max-${slug(active)}.png`}
      controls={
        <Choices
          options={available}
          value={active}
          onChange={setActive}
          label="Country"
        />
      }
      caption={
        <>
          One grey line per year, {BASE_LABEL}, so the grey band is the range
          the date has run in over thirty years. Red is 2026. Where red sits
          above the band, that day was hotter than the same date in any of
          those thirty years.
        </>
      }
    >
      <SpaghettiSvg country={active} />
    </Frame>
  );
}

// ─── 08: warming rate by region ─────────────────────────────────────────────
export function WarmingBars() {
  const rows = DATA.warm;
  const [wrapRef, narrow] = useNarrowChart();
  const W = narrow ? 336 : 680,
    L = narrow ? 104 : 118,
    R = narrow ? 44 : 52,
    T = 8;
  const H = rows.length * 24 + 34;
  const pw = W - L - R,
    hi = 0.55;
  const X = (v: number) => L + (v / hi) * pw;
  return (
    <Frame
      title="Europe is warming faster than any other continent"
      subtitle={"Warming rate in °C per decade, 1979–2025, from the annual mean 2\u200Am air temperature"}
      filename="warming-rate-by-region.png"
      minWidth={narrow ? 0 : 380}
      wrapRefExternal={wrapRef}
      caption={
        <>
          Least-squares trend on the annual mean. Global aggregates are shown
          faint.
        </>
      }
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Warming rate by region"
      >
        {(narrow ? [0.2, 0.4] : [0.1, 0.2, 0.3, 0.4, 0.5]).map((v) => (
          <g key={v}>
            <line x1={X(v)} x2={X(v)} y1={T} y2={H - 24} className="sc-grid" />
            <text x={X(v)} y={H - 8} textAnchor="middle" className="sc-tick">
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        {rows.map(([n, v], i) => {
          const y = T + i * 24 + 3;
          const cls = n.startsWith("Glob")
            ? "sc-bar-ref"
            : n === "Europe"
              ? "sc-bar-eu"
              : "sc-bar-other";
          return (
            <g key={n}>
              <rect
                x={L}
                y={y}
                width={X(v) - L}
                height={14}
                rx={4}
                className={cls}
              >
                <title>{`${n}: +${v.toFixed(3)} °C/decade`}</title>
              </rect>
              <text
                x={L - 8}
                y={y + 11}
                textAnchor="end"
                className={`sc-rowlab${n === "Europe" ? " sc-rowlab-hi" : ""}`}
              >
                {narrow ? n.replace("Globe incl. ocean", "Globe + ocean") : n}
              </text>
              <text x={X(v) + 6} y={y + 11} className="sc-val">
                +{v.toFixed(3)}
              </text>
            </g>
          );
        })}
      </svg>
    </Frame>
  );
}
