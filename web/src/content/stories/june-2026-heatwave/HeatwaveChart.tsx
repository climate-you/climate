"use client";

import { useRef, useState } from "react";
import { downloadSvgWithAttribution } from "@/lib/story/download";
import DownloadIcon from "@/components/story/DownloadIcon";
import styles from "@/components/story/story.module.css";

// Daily mean anomaly across 15 European cities, June–July 2026, each day vs its
// own month's 1991–2020 norm. Values track the bar heights of the approved
// mockup; bar geometry uses the same coordinate system so the chart is pixel-
// identical while now being data-driven (hover + accessible).
type Bar = { date: string; value: number; cx: number; fill: string };

const BARS: Bar[] = [
  { date: "1 Jun", value: 1.0, cx: 48.8, fill: "rgb(254,211,133)" },
  { date: "2 Jun", value: 0.2, cx: 65.2, fill: "rgb(255,232,155)" },
  { date: "3 Jun", value: -1.0, cx: 81.6, fill: "rgb(203,216,255)" },
  { date: "4 Jun", value: -1.0, cx: 98.0, fill: "rgb(203,216,255)" },
  { date: "5 Jun", value: -2.4, cx: 114.4, fill: "rgb(179,198,255)" },
  { date: "6 Jun", value: -1.0, cx: 130.7, fill: "rgb(202,216,255)" },
  { date: "7 Jun", value: 0.1, cx: 147.1, fill: "rgb(255,233,156)" },
  { date: "8 Jun", value: 0.7, cx: 163.5, fill: "rgb(255,219,141)" },
  { date: "9 Jun", value: -1.0, cx: 179.9, fill: "rgb(202,216,255)" },
  { date: "10 Jun", value: -2.6, cx: 196.3, fill: "rgb(175,195,255)" },
  { date: "11 Jun", value: -2.3, cx: 212.7, fill: "rgb(181,200,255)" },
  { date: "12 Jun", value: 0.0, cx: 229.1, fill: "rgb(219,228,255)" },
  { date: "13 Jun", value: 2.0, cx: 245.5, fill: "rgb(254,186,107)" },
  { date: "14 Jun", value: 0.7, cx: 261.8, fill: "rgb(255,218,140)" },
  { date: "15 Jun", value: 0.5, cx: 278.2, fill: "rgb(255,224,147)" },
  { date: "16 Jun", value: 2.0, cx: 294.6, fill: "rgb(254,185,105)" },
  { date: "17 Jun", value: 4.0, cx: 311.0, fill: "rgb(250,129,57)" },
  { date: "18 Jun", value: 5.6, cx: 327.4, fill: "rgb(239,79,43)" },
  { date: "19 Jun", value: 6.9, cx: 343.8, fill: "rgb(230,40,32)" },
  { date: "20 Jun", value: 6.6, cx: 360.2, fill: "rgb(232,48,34)" },
  { date: "21 Jun", value: 7.5, cx: 376.6, fill: "rgb(224,25,29)" },
  { date: "22 Jun", value: 7.5, cx: 393.0, fill: "rgb(225,25,28)" },
  { date: "23 Jun", value: 7.6, cx: 409.3, fill: "rgb(223,24,29)" },
  { date: "24 Jun", value: 8.6, cx: 425.7, fill: "rgb(209,17,32)" },
  { date: "25 Jun", value: 8.5, cx: 442.1, fill: "rgb(211,18,31)" },
  { date: "26 Jun", value: 9.0, cx: 458.5, fill: "rgb(204,14,33)" },
  { date: "27 Jun", value: 9.0, cx: 474.9, fill: "rgb(205,14,32)" },
  { date: "28 Jun", value: 7.7, cx: 491.3, fill: "rgb(223,24,29)" },
  { date: "29 Jun", value: 5.5, cx: 507.7, fill: "rgb(240,84,44)" },
  { date: "30 Jun", value: 5.1, cx: 524.1, fill: "rgb(243,96,47)" },
  { date: "1 Jul", value: 1.4, cx: 540.4, fill: "rgb(254,201,122)" },
  { date: "2 Jul", value: 1.3, cx: 556.8, fill: "rgb(254,203,125)" },
  { date: "3 Jul", value: 1.4, cx: 573.2, fill: "rgb(254,200,121)" },
  { date: "4 Jul", value: 2.0, cx: 589.6, fill: "rgb(254,184,105)" },
  { date: "5 Jul", value: 2.3, cx: 606.0, fill: "rgb(254,176,97)" },
  { date: "6 Jul", value: 3.2, cx: 622.4, fill: "rgb(253,153,72)" },
  { date: "7 Jul", value: 4.1, cx: 638.8, fill: "rgb(250,128,56)" },
  { date: "8 Jul", value: 3.0, cx: 655.2, fill: "rgb(253,157,77)" },
  { date: "9 Jul", value: 3.3, cx: 671.5, fill: "rgb(253,152,71)" },
  { date: "10 Jul", value: 3.6, cx: 687.9, fill: "rgb(253,143,62)" },
  { date: "11 Jul", value: 3.7, cx: 704.3, fill: "rgb(252,138,60)" },
  { date: "12 Jul", value: 4.0, cx: 720.7, fill: "rgb(251,131,58)" },
  { date: "13 Jul", value: 3.9, cx: 737.1, fill: "rgb(251,133,58)" },
];

const VB_W = 760;
const VB_H = 300;
// Y axis spans -5…+10 °C over the plot box (y 26 → 268, i.e. 242px / 15 °C).
const Y0 = 187.3; // zero-anomaly line
const PX_PER_C = 16.133; // vertical scale
const BAR_W = 13.1;

function yFor(value: number) {
  return Y0 - value * PX_PER_C;
}

function fmt(value: number) {
  const rounded = Math.round(value * 10) / 10;
  return `${rounded >= 0 ? "+" : ""}${rounded.toFixed(1)}°C`;
}

type Props = { title: string; sourceText: string };

export default function HeatwaveChart({ title, sourceText }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  const handleDownload = () => {
    if (svgRef.current)
      downloadSvgWithAttribution(
        svgRef.current,
        { title, sourceText },
        "europe-heat-2026-daily-anomaly.png",
      );
  };

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * VB_W;
    // nearest bar by centre x
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < BARS.length; i++) {
      const d = Math.abs(BARS[i].cx - vbX);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    setHover(best);
  };

  const hovered = hover !== null ? BARS[hover] : null;
  // Tooltip position as % of the chart box (SVG scales to full width).
  const tipLeft = hovered ? (hovered.cx / VB_W) * 100 : 0;
  const tipTop = hovered
    ? (Math.min(yFor(hovered.value), Y0) / VB_H) * 100
    : 0;

  return (
    <div className={styles.chart}>
      <DownloadIcon
        label="Download chart"
        onClick={handleDownload}
        className={styles.chartDl}
      />
      <div className={styles.chartPlot}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        role="img"
        aria-label="Daily European temperature anomaly, June to July 2026"
        preserveAspectRatio="xMidYMid meet"
        className="curve"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {/* episode bands */}
        <rect x="302.8" y="26" width="229.4" height="242" className="cw-bandbg" />
        <text x="417.5" y="38" textAnchor="middle" className="cw-band">
          First episode
        </text>
        <rect
          x="565"
          y="26"
          width="181"
          height="242"
          className="cw-bandbg cw-bandbg-alt"
        />
        <text x="655.5" y="38" textAnchor="middle" className="cw-band">
          Second episode
        </text>

        {/* gridlines + y axis */}
        <line x1="40" y1="268" x2="746" y2="268" className="cw-grid" />
        <text x="34" y="272" textAnchor="end" className="cw-ax">
          -5
        </text>
        <line x1="40" y1="187.3" x2="746" y2="187.3" className="cw-grid cw-zero" />
        <text x="34" y="191.3" textAnchor="end" className="cw-ax">
          +0
        </text>
        <line x1="40" y1="106.6" x2="746" y2="106.6" className="cw-grid" />
        <line x1="40" y1="26" x2="746" y2="26" className="cw-grid" />
        <text x="34" y="30" textAnchor="end" className="cw-ax">
          +10
        </text>

        {/* bars */}
        {BARS.map((b, i) => {
          const yv = yFor(b.value);
          const top = Math.min(yv, Y0);
          const height = Math.max(0.2, Math.abs(yv - Y0));
          return (
            <rect
              key={b.date}
              x={b.cx - BAR_W / 2}
              y={top}
              width={BAR_W}
              height={height}
              fill={b.fill}
              opacity={hover === null || hover === i ? 1 : 0.5}
            />
          );
        })}

        {/* hover marker */}
        {hovered && (
          <rect
            x={hovered.cx - BAR_W / 2 - 1.2}
            y={Math.min(yFor(hovered.value), Y0) - 1.2}
            width={BAR_W + 2.4}
            height={Math.max(0.2, Math.abs(yFor(hovered.value) - Y0)) + 2.4}
            fill="none"
            stroke="var(--ink)"
            strokeWidth={1.2}
          />
        )}

        {/* peak annotation */}
        <line x1="458.5" y1="42.1" x2="458.5" y2="23" className="cw-peakline" />
        <text x="458.5" y="18" textAnchor="middle" className="cw-peak">
          +9.0°C · 26 Jun
        </text>

        {/* x axis */}
        <text x="48.8" y="290" textAnchor="middle" className="cw-ax">
          1 Jun
        </text>
        <text x="278.2" y="290" textAnchor="middle" className="cw-ax">
          15 Jun
        </text>
        <text x="540.4" y="290" textAnchor="middle" className="cw-ax">
          1 Jul
        </text>
        <text x="737.1" y="290" textAnchor="middle" className="cw-ax">
          13 Jul
        </text>
      </svg>

      {hovered && (
        <div
          className={styles.chartTip}
          style={{ left: `${tipLeft}%`, top: `${tipTop}%` }}
        >
          <span className={styles.chartTipVal}>{fmt(hovered.value)}</span>
          <span className={styles.chartTipDate}>{hovered.date}</span>
        </div>
      )}
      </div>
    </div>
  );
}
