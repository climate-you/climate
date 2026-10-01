// Shared between the route's metadata (a server module) and the story
// component (a client module). It must not live in the client module: Next
// replaces a "use client" module's exports with a proxy that throws when the
// server touches them, and the thrown function's source ended up as the
// browser tab's title.
export const TITLE = "Europe's summer of heat and drought";

// One source for the story's dates: the byline, the route metadata, the
// structured data and the sitemap all read these. ISO dates, Europe/London.
export const PUBLISHED = "2026-09-29";
/** Last change to the story's figures; see the update note under the byline. */
export const UPDATED = "2026-10-01";

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** "2026-10-01" -> "1 October 2026" */
export function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}
