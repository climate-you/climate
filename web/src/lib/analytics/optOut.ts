/**
 * Browser-local analytics opt-out.
 *
 * Activation: load any page with ?analytics=off in the URL; ?analytics=on
 * clears it again. The choice lives in localStorage, so it follows the browser
 * rather than the address it connects from — unlike the server-side IP
 * blocklist it survives a VPN, a new network, or a reassigned address, and
 * needs no deploy to change.
 *
 * While set, the browser sends no session or click events, marks its chat
 * messages as test traffic so they stay out of the usage reports, and sets
 * GoatCounter's own `skipgc` key so third-party counting stops too.
 */

export const ANALYTICS_OPT_OUT_KEY = "climate.analyticsDisabled";
export const ANALYTICS_OPT_OUT_PARAM = "analytics";
const GOATCOUNTER_SKIP_KEY = "skipgc";

/**
 * Reads the flag synchronously so callers can check it at event time without
 * a render pass — a hook would still report "enabled" during the first paint,
 * which is exactly when the session event fires.
 */
export function isAnalyticsDisabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(ANALYTICS_OPT_OUT_KEY) === "1";
  } catch {
    // Storage unavailable (private mode, blocked cookies): count as opted in.
    return false;
  }
}

/**
 * Inline script that applies ?analytics=off|on to localStorage.
 *
 * It runs beforeInteractive because GoatCounter reads `skipgc` as its script
 * loads: setting the key from a React effect would land after the pageview
 * had already been counted.
 */
export const ANALYTICS_OPT_OUT_BOOTSTRAP = `
(function () {
  try {
    var params = new URLSearchParams(window.location.search);
    var choice = params.get(${JSON.stringify(ANALYTICS_OPT_OUT_PARAM)});
    if (choice !== "off" && choice !== "on") return;
    if (choice === "off") {
      localStorage.setItem(${JSON.stringify(ANALYTICS_OPT_OUT_KEY)}, "1");
      localStorage.setItem(${JSON.stringify(GOATCOUNTER_SKIP_KEY)}, "t");
    } else {
      localStorage.removeItem(${JSON.stringify(ANALYTICS_OPT_OUT_KEY)});
      localStorage.removeItem(${JSON.stringify(GOATCOUNTER_SKIP_KEY)});
    }
    params.delete(${JSON.stringify(ANALYTICS_OPT_OUT_PARAM)});
    var search = params.toString();
    window.history.replaceState(
      null,
      "",
      window.location.pathname + (search ? "?" + search : "") + window.location.hash
    );
  } catch (e) {}
})();
`;
