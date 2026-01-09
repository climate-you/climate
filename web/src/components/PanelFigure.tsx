"use client";

import { useEffect, useMemo, useRef } from "react";

type PanelFigureProps = {
  svg: string | null;
  className?: string;

  animate?: "draw";

  /**
   * If sequence="traces", drawMs is PER TRACE.
   * Total ≈ drawMs * numTraces.
   */
  drawMs?: number;

  /** 0..1 fraction visible before triggering */
  inViewThreshold?: number;

  /** Replay each time the slide re-enters view */
  replayOnEnter?: boolean;

  /** "all" = all traces at once, "traces" = trace-by-trace */
  sequence?: "all" | "traces";

  /** CSS timing function (default: linear) */
  timingFunction?: string;

  /** Plotly annotations are usually g.annotation */
  annotationsSelector?: string;

  /** Called after final draw + annotation reveal */
  onDrawComplete?: () => void;
};

function prefersReducedMotion() {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
}

function isStrokeOnlyPath(p: SVGPathElement) {
  const style = window.getComputedStyle(p);
  const stroke = style.stroke;
  const fill = style.fill;
  const strokeWidth = parseFloat(style.strokeWidth || "0");

  const hasStroke = stroke && stroke !== "none" && strokeWidth > 0;
  const isFilled = fill && fill !== "none";
  return hasStroke && !isFilled;
}

function getTraceGroups(svgEl: SVGSVGElement) {
  return Array.from(svgEl.querySelectorAll<SVGGElement>("g.trace"));
}

function getLinePaths(traceG: SVGGElement) {
  const candidates = Array.from(traceG.querySelectorAll<SVGPathElement>("path"));
  return candidates.filter(isStrokeOnlyPath);
}

function getMarkerElements(traceG: SVGGElement) {
  // Conservative set of marker-ish elements inside a trace.
  return Array.from(
    traceG.querySelectorAll<SVGGraphicsElement>(
      "g.points path, path.point, path.scatterpts, g.points circle, g.points rect"
    )
  );
}

function hideMarkers(markers: SVGGraphicsElement[]) {
  for (const el of markers) {
    if (!el.dataset._origOpacity) {
      const o = window.getComputedStyle(el).opacity;
      el.dataset._origOpacity = o || "1";
    }
    el.style.opacity = "0";
  }
}

function showMarkers(markers: SVGGraphicsElement[]) {
  for (const el of markers) {
    el.style.transition = "opacity 250ms ease-in-out";
    el.style.opacity = el.dataset._origOpacity || "1";
  }
}

function ensureDefs(svgEl: SVGSVGElement) {
  let defs = svgEl.querySelector("defs");
  if (!defs) {
    defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    svgEl.insertBefore(defs, svgEl.firstChild);
  }
  return defs;
}

function svgBBox(svgEl: SVGSVGElement) {
  try {
    return svgEl.getBBox();
  } catch {
    // Some SVGs may throw if not fully laid out; fall back to viewBox if present
    const vb = svgEl.viewBox?.baseVal;
    if (vb && vb.width && vb.height) return { x: vb.x, y: vb.y, width: vb.width, height: vb.height };
    return { x: 0, y: 0, width: 1000, height: 1000 };
  }
}

type MaskHandle = {
  maskId: string;
  maskPath: SVGPathElement;
};

function ensureMaskForPath(svgEl: SVGSVGElement, defs: SVGDefsElement, p: SVGPathElement): MaskHandle | null {
  // Reuse mask per-path per SVG injection.
  let id = p.dataset._maskId;
  let mask = id ? svgEl.querySelector<SVGMaskElement>(`#${CSS.escape(id)}`) : null;

  if (!mask) {
    id = `m_${Math.random().toString(36).slice(2)}`;
    p.dataset._maskId = id;

    mask = document.createElementNS("http://www.w3.org/2000/svg", "mask");
    mask.setAttribute("id", id);
    mask.setAttribute("maskUnits", "userSpaceOnUse");

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("fill", "black");
    mask.appendChild(rect);

    const mp = document.createElementNS("http://www.w3.org/2000/svg", "path");
    mp.setAttribute("fill", "none");
    mp.setAttribute("stroke", "white");
    mask.appendChild(mp);

    defs.appendChild(mask);
  }

  const maskPath = mask.querySelector("path");
  const maskRect = mask.querySelector("rect");

  if (!maskPath || !maskRect) return null;

  // Size the mask to the SVG's bbox so it covers everything.
  const bb = svgBBox(svgEl);
  maskRect.setAttribute("x", String(bb.x));
  maskRect.setAttribute("y", String(bb.y));
  maskRect.setAttribute("width", String(bb.width));
  maskRect.setAttribute("height", String(bb.height));

  return { maskId: id!, maskPath: maskPath as SVGPathElement };
}

/**
 * Arm the line path so it is fully hidden initially using a MASK.
 * The real path remains untouched, so dashed lines stay dashed.
 */
function armHiddenWithMask(svgEl: SVGSVGElement, defs: SVGDefsElement, p: SVGPathElement) {
  const d = p.getAttribute("d");
  if (!d) return null;

  const handle = ensureMaskForPath(svgEl, defs, p);
  if (!handle) return null;

  const style = window.getComputedStyle(p);
  const strokeWidth = style.strokeWidth || "1";
  const linecap = style.strokeLinecap || "round";
  const linejoin = style.strokeLinejoin || "round";

  const mp = handle.maskPath;
  mp.style.transition = "none";

  mp.setAttribute("d", d);
  mp.setAttribute("stroke-width", strokeWidth);
  mp.setAttribute("stroke-linecap", linecap);
  mp.setAttribute("stroke-linejoin", linejoin);

  const len = p.getTotalLength?.() ?? 0;
  if (!Number.isFinite(len) || len <= 1) return null;

  mp.dataset._dashLen = String(len);
  mp.style.strokeDasharray = `${len}`;
  mp.style.strokeDashoffset = `${len}`;

  // Apply mask to the original path, hiding it until mask path reveals it.
  p.setAttribute("mask", `url(#${handle.maskId})`);

  return mp;
}

function playMaskDraw(maskPaths: SVGPathElement[], ms: number, timingFunction: string) {
  for (const mp of maskPaths) {
    const len = Number(mp.dataset._dashLen ?? "0");
    if (!Number.isFinite(len) || len <= 1) continue;

    mp.style.strokeDasharray = `${len}`;
    mp.style.strokeDashoffset = `${len}`;
    mp.style.transition = `stroke-dashoffset ${ms}ms ${timingFunction}`;
  }

  requestAnimationFrame(() => {
    for (const mp of maskPaths) {
      const len = Number(mp.dataset._dashLen ?? "0");
      if (!Number.isFinite(len) || len <= 1) continue;
      mp.style.strokeDashoffset = "0";
    }
  });
}

function isDarkMode() {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark");
}

function isWhiteish(fill: string) {
  const f = (fill || "").trim().toLowerCase();
  return (
    f === "white" ||
    f === "#fff" ||
    f === "#ffffff" ||
    f.startsWith("rgb(255, 255, 255)") ||
    f.startsWith("rgba(255, 255, 255")
  );
}

function forceTransparentFill(el: SVGGraphicsElement) {
  // Attributes
  el.setAttribute("fill", "transparent");
  el.setAttribute("fill-opacity", "0");

  // Inline style overrides (highest priority after !important CSS)
  (el.style as any).fill = "transparent";
  (el.style as any).fillOpacity = "0";

  // Remove any existing inline fill declarations Plotly put in the style attr
  const styleAttr = el.getAttribute("style") || "";
  if (styleAttr) {
    const cleaned = styleAttr
      .split(";")
      .map((s) => s.trim())
      .filter(Boolean)
      .filter((s) => {
        const k = s.split(":")[0]?.trim().toLowerCase();
        return k !== "fill" && k !== "fill-opacity";
      })
      .join("; ");
    if (cleaned) el.setAttribute("style", cleaned);
    else el.removeAttribute("style");
  }
}

function applyPlotlySvgDarkFix(svgEl: SVGSVGElement) {
  if (!isDarkMode()) return;

  // Also clear any inline background on the root svg element
  (svgEl.style as any).background = "transparent";

  // Consider all filled shapes (Plotly sometimes uses paths for backgrounds)
  const candidates = Array.from(
    svgEl.querySelectorAll<SVGGraphicsElement>("rect, path, polygon")
  );

  if (!candidates.length) return;

  // Compute areas; find max area among candidates
  let maxArea = 0;
  const items: Array<{ el: SVGGraphicsElement; area: number; fill: string; cls: string }> = [];

  for (const el of candidates) {
    // Ignore elements that obviously aren't background candidates
    // (stroked-only lines etc.)
    const style = window.getComputedStyle(el as any);
    const fill = (el.getAttribute("fill") ?? style.fill ?? "").toString();
    const cls = el.getAttribute("class") ?? "";

    if (!fill || fill === "none") continue;

    let bb: DOMRect | null = null;
    try {
      bb = (el as any).getBBox();
    } catch {
      continue;
    }

    const area = bb.width * bb.height;
    if (!Number.isFinite(area) || area <= 0) continue;

    items.push({ el, area, fill, cls });
    if (area > maxArea) maxArea = area;
  }

  if (!items.length || maxArea <= 0) return;

  const largeThresh = maxArea * 0.25;

  for (const { el, area, fill, cls } of items) {
    // Clear large white-ish backgrounds; also clear legend bg by class "bg"
    const shouldClear = (isWhiteish(fill) && area >= largeThresh) || (cls.includes("bg") && isWhiteish(fill));
    if (!shouldClear) continue;

    forceTransparentFill(el);
  }
}

export default function PanelFigure({
  svg,
  className,
  animate,
  drawMs = 2400,
  inViewThreshold = 0.6,
  replayOnEnter = false,
  sequence = "traces",
  timingFunction = "linear",
  annotationsSelector = "g.annotation",
  onDrawComplete,
}: PanelFigureProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);

  const hasPlayedRef = useRef(false);
  const lastSvgRef = useRef<string | null>(null);
  const timeoutsRef = useRef<number[]>([]);

  const reduced = useMemo(() => prefersReducedMotion(), []);

  // Inject SVG (+ apply dark background fix immediately)
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    host.innerHTML = svg || "";

    const svgEl = host.querySelector("svg") as SVGSVGElement | null;
    if (svgEl) applyPlotlySvgDarkFix(svgEl);

    if (svg && lastSvgRef.current !== svg) {
      lastSvgRef.current = svg;
      hasPlayedRef.current = false;
    }
  }, [svg]);

  // Re-apply dark SVG fix when theme toggles (so you don't need to reload SVG)
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const obs = new MutationObserver(() => {
      const svgEl = host.querySelector("svg") as SVGSVGElement | null;
      if (!svgEl) return;
      applyPlotlySvgDarkFix(svgEl);
    });

    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  // Pre-arm on inject: hide markers + hide annotations + arm masks so nothing "leaks"
  useEffect(() => {
    if (animate !== "draw") return;
    if (!svg) return;
    if (reduced) return;

    const host = hostRef.current;
    if (!host) return;

    const svgEl = host.querySelector("svg") as SVGSVGElement | null;
    if (!svgEl) return;

    const defs = ensureDefs(svgEl);

    const traces = getTraceGroups(svgEl);
    if (!traces.length) return;

    // Hide annotations initially (min/max etc.)
    const annotations = Array.from(svgEl.querySelectorAll<SVGGElement>(annotationsSelector));
    for (const a of annotations) {
      a.style.transition = "none";
      a.style.opacity = "0";
    }

    // Hide markers + arm masks (this also prevents seeing a “single dash” before start)
    for (const t of traces) {
      const markers = getMarkerElements(t);
      if (markers.length) hideMarkers(markers);

      const linePaths = getLinePaths(t);
      for (const p of linePaths) {
        armHiddenWithMask(svgEl, defs, p);
      }
    }

    // Flush
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    svgEl.getBoundingClientRect();
  }, [svg, animate, reduced, annotationsSelector]);

  // Animate when visible
  useEffect(() => {
    if (animate !== "draw") return;
    if (!svg) return;
    if (reduced) return;

    const host = hostRef.current;
    if (!host) return;

    const svgEl = host.querySelector("svg") as SVGSVGElement | null;
    if (!svgEl) return;

    const defs = ensureDefs(svgEl);
    const traces = getTraceGroups(svgEl);
    if (!traces.length) return;

    const annotations = Array.from(svgEl.querySelectorAll<SVGGElement>(annotationsSelector));

    const clearTimers = () => {
      for (const t of timeoutsRef.current) window.clearTimeout(t);
      timeoutsRef.current = [];
    };

    const showAnnotations = () => {
      for (const a of annotations) {
        a.style.transition = "opacity 350ms ease-in-out";
        a.style.opacity = "1";
      }
    };

    const hideAnnotations = () => {
      for (const a of annotations) {
        a.style.transition = "none";
        a.style.opacity = "0";
      }
    };

    const run = () => {
      if (!replayOnEnter && hasPlayedRef.current) return;
      clearTimers();

      // Re-arm everything so replay starts from the beginning
      hideAnnotations();

      // For each trace, build its mask paths list and hide markers
      const traceMaskPaths: SVGPathElement[][] = [];
      const traceMarkers: SVGGraphicsElement[][] = [];

      for (const t of traces) {
        const markers = getMarkerElements(t);
        if (markers.length) hideMarkers(markers);
        traceMarkers.push(markers);

        const linePaths = getLinePaths(t);
        const mps: SVGPathElement[] = [];
        for (const p of linePaths) {
          const mp = armHiddenWithMask(svgEl, defs, p);
          if (mp) mps.push(mp);
        }
        traceMaskPaths.push(mps);
      }

      // Flush armed state
      // eslint-disable-next-line @typescript-eslint/no-unused-expressions
      svgEl.getBoundingClientRect();

      if (sequence === "all") {
        // Draw all traces at once
        const all = traceMaskPaths.flat().filter(Boolean);
        playMaskDraw(all, drawMs, timingFunction);

        timeoutsRef.current.push(
          window.setTimeout(() => {
            // reveal markers + annotations at end
            for (const markers of traceMarkers) showMarkers(markers);
            showAnnotations();
            hasPlayedRef.current = true;
            onDrawComplete?.();
          }, drawMs + 100)
        );
        return;
      }

      // sequence === "traces"
      let acc = 0;

      traces.forEach((_, i) => {
        const mps = traceMaskPaths[i] || [];
        const markers = traceMarkers[i] || [];

        timeoutsRef.current.push(
          window.setTimeout(() => {
            if (mps.length) playMaskDraw(mps, drawMs, timingFunction);

            // Show markers for this trace at the end of its draw
            window.setTimeout(() => {
              if (markers.length) showMarkers(markers);
            }, drawMs + 60);
          }, acc)
        );

        acc += drawMs + 140;
      });

      timeoutsRef.current.push(
        window.setTimeout(() => {
          showAnnotations();
          hasPlayedRef.current = true;
          onDrawComplete?.();
        }, acc + 80)
      );
    };

    const obs = new IntersectionObserver(
      (entries) => {
        const e = entries[0];
        if (!e) return;

        if (e.isIntersecting && e.intersectionRatio >= inViewThreshold) {
          run();
        } else if (replayOnEnter) {
          hasPlayedRef.current = false;
          clearTimers();
        }
      },
      { threshold: [0, inViewThreshold, 1] }
    );

    obs.observe(host);
    return () => {
      clearTimers();
      obs.disconnect();
    };
  }, [
    animate,
    svg,
    reduced,
    drawMs,
    inViewThreshold,
    replayOnEnter,
    sequence,
    timingFunction,
    annotationsSelector,
    onDrawComplete,
  ]);

  return <div ref={hostRef} className={["panel-figure w-full", className].filter(Boolean).join(" ")} />;
}

export function PanelFigureStyles() {
  return (
    <style jsx>{`
      :global(.panel-figure svg) {
        width: 100% !important;
        height: auto !important;
        display: block;
      }

      /* Dark-mode overrides for Plotly-exported SVGs */
      :global(.dark .panel-figure svg .xtick text),
      :global(.dark .panel-figure svg .ytick text),
      :global(.dark .panel-figure svg .gtitle),
      :global(.dark .panel-figure svg .legend text) {
        fill: #e5e5e5 !important;
      }

      :global(.dark .panel-figure svg .gridlayer path),
      :global(.dark .panel-figure svg .zerolinelayer path),
      :global(.dark .panel-figure svg .xlines-above path),
      :global(.dark .panel-figure svg .ylines-above path) {
        stroke: #3a3a3a !important;
      }

      :global(.dark .panel-figure svg .xaxislayer-above path),
      :global(.dark .panel-figure svg .yaxislayer-above path) {
        stroke: #666666 !important;
      }
    `}</style>
  );
}
