"use client";

export default function PanelFigure({ svg }: { svg: string }) {
  return (
    <div className="panel-figure w-full" dangerouslySetInnerHTML={{ __html: svg }} />
  );
}

/**
 * Note:
 * We scope the SVG sizing rule via the wrapper class "panel-figure",
 * so it won’t accidentally affect other SVGs on the page.
 */
export function PanelFigureStyles() {
  return (
    <style jsx>{`
      :global(.panel-figure svg) {
        width: 100% !important;
        height: auto !important;
        display: block;
      }
    `}</style>
  );
}
