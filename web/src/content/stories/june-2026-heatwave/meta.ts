// Shared between the route's metadata (a server module) and the story
// component (a client module); see the summer 2026 story's meta.ts for why
// it cannot live in the client module.
export const TITLE = "The June 2026 heatwave over Europe";

// One source for the story's dates: the byline, the route metadata, the
// structured data, the case-studies list and the sitemap all read these.
// ISO dates, Europe/London. Add an UPDATED date if the figures ever change.
export const PUBLISHED = "2026-07-19";
