// Shared between the route's metadata (a server module) and the story
// component (a client module). It must not live in the client module: Next
// replaces a "use client" module's exports with a proxy that throws when the
// server touches them, and the thrown function's source ended up as the
// browser tab's title.
export const TITLE = "Europe's summer of heat and drought";
