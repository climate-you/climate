// Typed view of data.json, which scripts/make_summer_2026_story_data.py
// writes from the release. Nothing in the story is typed in by hand: every
// number in the prose and every chart reads from here.
// Workflow: docs/runbooks/case-study-data.md
import raw from "./data.json";

export type RainWindow = { obs: number; exp: number; pct: number; days: number };
export type Episode = { a: string; b: string; d: number; peak: number };
export type Rank = {
  hotter: number;
  drier: number;
  n: number;
  anomaly: number;
  pct: number;
};
/** Daily values from day-of-year `d0`, one per consecutive day. */
export type YearTrace = { d0: number; v: number[] };

export type StoryData = {
  generated: string;
  dataThrough: string;
  dry: [string, string];
  wet: [string, string];
  base: [number, number];
  europe: string[];
  rain: Record<string, { dry: RainWindow; wet: RainWindow; ratio: number }>;
  days: Record<string, number>;
  /** Episode days falling inside the rainfall window, for like-for-like plots. */
  daysInDryWindow: Record<string, number>;
  episodes: Record<string, Episode[]>;
  /** [year, JJA temperature anomaly °C, JJA rainfall % of normal] */
  joint: Record<string, [number, number, number][]>;
  ranks: Record<string, Rank>;
  cum: Record<string, { obs: [string, number][]; norm: [string, number][] }>;
  monthly: { periods: string[]; names: string[]; grid: Record<string, number[]> };
  warm: [string, number][];
  europeDecades: {
    first: [number, number];
    last: [number, number];
    delta: number;
    siteBase: [number, number];
    siteRecent: [number, number];
    siteDelta: number;
  };
  /** country → year → daily maximum trace */
  spaghetti: Record<string, Record<string, YearTrace>>;
  peaks: Record<string, { date: string; value: number; aug13: number }>;
};

export const DATA = raw as unknown as StoryData;
export const EUROPE = new Set(DATA.europe);
export const BASE_LABEL = `${DATA.base[0]}–${DATA.base[1]}`;

/** Countries with a full history, in the order the story offers them. */
export const STORY_COUNTRIES = Object.keys(DATA.joint);

export function pct(name: string, window: "dry" | "wet" = "dry"): number {
  return DATA.rain[name][window].pct;
}
export function days(name: string): number {
  return DATA.days[name] ?? 0;
}
/** Whole number, for prose. */
export function n0(v: number): string {
  return Math.round(v).toString();
}
export function n1(v: number): string {
  return v.toFixed(1);
}

/** Countries whose 2026 summer was the hottest in the record. */
export function hottestOnRecord(): string[] {
  return STORY_COUNTRIES.filter((c) => DATA.ranks[c].hotter === 0);
}

/** Country names that read with a definite article in running prose. */
const TAKES_ARTICLE = new Set(["United Kingdom", "Netherlands", "United States"]);

/** "A, the B and C" */
export function listOf(names: string[]): string {
  const withArticles = names.map((n) => (TAKES_ARTICLE.has(n) ? `the ${n}` : n));
  if (withArticles.length <= 1) return withArticles[0] ?? "";
  return `${withArticles.slice(0, -1).join(", ")} and ${withArticles[withArticles.length - 1]}`;
}
