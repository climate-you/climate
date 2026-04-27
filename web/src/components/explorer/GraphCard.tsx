"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";

import InfoBubble from "@/components/explorer/InfoBubble";
import styles from "@/app/page.module.css";
import {
  graphChartMode,
  sliceRowsByTimeRange,
  toChartTimestamp,
  type ChartRow,
  type GraphPayload,
  type SeriesPayload,
  type TimeRange,
} from "@/lib/explorer/chartData";
import {
  buildHotDaysOption,
  buildStackedBarOption,
  buildTimeSeriesOption,
  isMobileViewport,
} from "@/lib/explorer/chartOptions";

type GraphAnimationStep = {
  id: string;
  title?: string;
  time_range?: TimeRange;
  series_keys?: string[];
};

type GraphAnimation = {
  autoplay?: boolean;
  loop?: boolean;
  step_duration_ms?: number;
  transition_ms?: number;
  steps: GraphAnimationStep[];
};

export type GraphCardGraphPayload = GraphPayload & {
  animation?: GraphAnimation;
};

type GraphCardProps = {
  graph: GraphCardGraphPayload;
  data: ChartRow[];
  series: Record<string, SeriesPayload>;
  unit: "C" | "F";
  showTitle?: boolean;
  stepIndex: number;
  onStepIndexChange: (graphId: string, nextStepIndex: number) => void;
  available?: boolean;
  onSelectLayer?: () => void;
};

export function EChartCanvas({
  option,
  height = 420,
}: {
  option: EChartsOption;
  height?: number;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!rootRef.current) return;
    const chart = echarts.init(rootRef.current);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(rootRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.setOption(option, {
      notMerge: false,
      replaceMerge: ["series", "xAxis", "yAxis"],
      lazyUpdate: true,
    });
  }, [option]);

  return (
    <div
      ref={rootRef}
      data-echart-canvas="true"
      style={{ width: "100%", height }}
    />
  );
}

export default function GraphCard({
  graph,
  data,
  series,
  unit,
  showTitle = true,
  stepIndex,
  onStepIndexChange,
  available = true,
  onSelectLayer,
}: GraphCardProps) {
  const chartHostRef = useRef<HTMLDivElement | null>(null);
  const [chartHeight, setChartHeight] = useState(260);
  const [colorScheme, setColorScheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setColorScheme(mq.matches ? "dark" : "light");
    const handler = (e: MediaQueryListEvent) =>
      setColorScheme(e.matches ? "dark" : "light");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  const steps = graph.animation?.steps ?? [];
  const hasAnimation = steps.length >= 2;
  const chartMaxHeight = 260;
  const chartMinAspectRatio = 1.5;
  const safeStepIndex = hasAnimation
    ? Math.max(0, Math.min(steps.length - 1, Math.trunc(stepIndex)))
    : 0;

  useEffect(() => {
    const host = chartHostRef.current;
    if (!host) return;
    const updateChartHeight = () => {
      const width = host.clientWidth;
      if (!Number.isFinite(width) || width <= 0) return;
      const nextHeight = Math.max(
        1,
        Math.min(chartMaxHeight, Math.floor(width / chartMinAspectRatio)),
      );
      setChartHeight((prev) => (prev === nextHeight ? prev : nextHeight));
    };
    updateChartHeight();
    const observer = new ResizeObserver(updateChartHeight);
    observer.observe(host);
    return () => observer.disconnect();
  }, [chartMaxHeight, chartMinAspectRatio]);

  useEffect(() => {
    if (!hasAnimation || graph.animation?.autoplay === false) return;
    const stepDuration = graph.animation?.step_duration_ms ?? 2600;
    const timer = window.setTimeout(() => {
      const nextStepIndex =
        safeStepIndex + 1 < steps.length
          ? safeStepIndex + 1
          : graph.animation?.loop === false
            ? safeStepIndex
            : 0;
      onStepIndexChange(graph.id, nextStepIndex);
    }, stepDuration);
    return () => window.clearTimeout(timer);
  }, [
    graph.animation,
    graph.id,
    hasAnimation,
    onStepIndexChange,
    safeStepIndex,
    steps.length,
  ]);

  const activeStep = hasAnimation ? steps[safeStepIndex] : null;
  const showMobileStepToggle =
    isMobileViewport() && hasAnimation && steps.length === 2;
  const mobileToggleStepIndex =
    showMobileStepToggle && safeStepIndex === 0 ? 1 : 0;
  const mobileToggleStepLabel =
    showMobileStepToggle && steps[safeStepIndex]
      ? (steps[safeStepIndex].title ?? steps[safeStepIndex].id)
      : "";
  const visibleKeys = activeStep?.series_keys?.length
    ? activeStep.series_keys
    : graph.series_keys;
  const chartMode = graphChartMode(graph, visibleKeys, series);
  const isStackedBarChart = chartMode === "stacked_bar";
  const hasGraphError =
    typeof graph.error === "string" && graph.error.trim().length > 0;
  const activeRange = activeStep?.time_range ?? graph.time_range;
  const rangedData = useMemo(
    () => sliceRowsByTimeRange(data, activeRange),
    [data, activeRange],
  );
  const filteredData = useMemo(
    () =>
      rangedData.filter((row) =>
        visibleKeys.some((key) => row[key] !== null && row[key] !== undefined),
      ),
    [rangedData, visibleKeys],
  );
  const transitionMs = graph.animation?.transition_ms ?? 900;
  const isHotDaysChart = chartMode === "hot_days_combo";
  const graphInfoText =
    typeof graph.ui?.info_text === "string" ? graph.ui.info_text : "";
  const useAllVisibleDataForSeries = graph.ui?.axis_title_mode === "date";
  const allVisibleData = useMemo(
    () =>
      data.filter((row) =>
        visibleKeys.some((key) => row[key] !== null && row[key] !== undefined),
      ),
    [data, visibleKeys],
  );
  const [xMin, xMax] = useMemo((): [number | undefined, number | undefined] => {
    const ref = filteredData.length ? filteredData : allVisibleData;
    if (!ref.length) return [undefined, undefined];
    const stamps = ref.map((row) => toChartTimestamp(row.x));
    return [Math.min(...stamps), Math.max(...stamps)];
  }, [allVisibleData, filteredData]);
  const option = useMemo(() => {
    if (isStackedBarChart) {
      return buildStackedBarOption({
        graph,
        series,
        data: filteredData,
        visibleKeys,
        transitionMs,
        unit,
      });
    }
    if (isHotDaysChart) {
      return buildHotDaysOption({
        graph,
        series,
        data: filteredData,
        visibleKeys,
        transitionMs,
        unit,
      });
    }
    return buildTimeSeriesOption({
      graph,
      series,
      data: useAllVisibleDataForSeries ? allVisibleData : filteredData,
      visibleKeys,
      transitionMs,
      unit,
      xMin,
      xMax,
    });
  }, [
    allVisibleData,
    colorScheme,
    filteredData,
    graph,
    isHotDaysChart,
    isStackedBarChart,
    useAllVisibleDataForSeries,
    series,
    transitionMs,
    unit,
    visibleKeys,
    xMax,
    xMin,
  ]);

  if (!available) {
    const isSeaGraph = graph.id.startsWith("sst_");
    const isCoralGraph = graph.id === "dhw_risk_days";
    const unavailableText = isSeaGraph
      ? "Sea surface temperature data is only available for coastal and ocean locations."
      : "Not available for this location.";
    return (
      <div className={`${styles.graphCard} ${styles.graphCardUnavailable}`}>
        {showTitle ? (
          <div className={styles.graphTitleRow}>
            <h3 className={styles.graphTitle}>{graph.title}</h3>
          </div>
        ) : null}
        {graphInfoText ? (
          <p className={styles.graphUnavailableText}>{graphInfoText}</p>
        ) : null}
        {isCoralGraph ? (
          <p className={styles.graphUnavailableText}>
            Coral reef data is only available for tropical coastal and ocean
            locations. Available locations are visible on the{" "}
            {onSelectLayer ? (
              <button
                type="button"
                className={styles.graphUnavailableLink}
                onClick={onSelectLayer}
              >
                Coral heat stress trend
              </button>
            ) : (
              "Coral heat stress trend"
            )}{" "}
            layer.
          </p>
        ) : (
          <p className={styles.graphUnavailableText}>{unavailableText}</p>
        )}
      </div>
    );
  }

  return (
    <div className={styles.graphCard}>
      {showTitle ? (
        <div className={styles.graphTitleRow}>
          <div className={styles.graphTitleLead}>
            <h3 className={styles.graphTitle}>{graph.title}</h3>
            {graphInfoText ? (
              <InfoBubble
                label="Graph title information"
                text={graphInfoText}
              />
            ) : null}
          </div>
          {hasAnimation && !hasGraphError ? (
            <div
              className={`${styles.stepButtons} ${styles.stepButtonsInline}`}
            >
              {showMobileStepToggle ? (
                <button
                  onClick={() =>
                    onStepIndexChange(graph.id, mobileToggleStepIndex)
                  }
                  className={`${styles.stepButton} ${styles.stepButtonToggle}`}
                >
                  {mobileToggleStepLabel}
                </button>
              ) : (
                steps.map((step, idx) => {
                  const active = idx === safeStepIndex;
                  return (
                    <button
                      key={`${graph.id}:${step.id}`}
                      onClick={() => onStepIndexChange(graph.id, idx)}
                      className={`${styles.stepButton} ${
                        active ? styles.stepButtonActive : ""
                      }`}
                    >
                      {step.title ?? step.id}
                    </button>
                  );
                })
              )}
            </div>
          ) : null}
        </div>
      ) : null}
      {hasAnimation && !hasGraphError && !showTitle ? (
        <div className={styles.stepButtons}>
          {showMobileStepToggle ? (
            <button
              onClick={() => onStepIndexChange(graph.id, mobileToggleStepIndex)}
              className={`${styles.stepButton} ${styles.stepButtonToggle}`}
            >
              {mobileToggleStepLabel}
            </button>
          ) : (
            steps.map((step, idx) => {
              const active = idx === safeStepIndex;
              return (
                <button
                  key={`${graph.id}:${step.id}`}
                  onClick={() => onStepIndexChange(graph.id, idx)}
                  className={`${styles.stepButton} ${
                    active ? styles.stepButtonActive : ""
                  }`}
                >
                  {step.title ?? step.id}
                </button>
              );
            })
          )}
        </div>
      ) : null}

      {!hasGraphError ? (
        <div ref={chartHostRef}>
          <EChartCanvas option={option} height={chartHeight} />
        </div>
      ) : null}

      {graph.source ? (
        <p className={styles.graphSource}>Source: {graph.source}</p>
      ) : null}
      {graph.caption ? (
        <p className={styles.graphCaption}>{graph.caption}</p>
      ) : null}
      {hasGraphError ? (
        <p className={styles.graphError}>
          Data unavailable for this location and metric.
        </p>
      ) : null}
    </div>
  );
}
