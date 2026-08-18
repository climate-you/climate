"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const DEFAULT_API_PORT = 8001;

const MAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution:
        "© <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    },
  },
  layers: [
    {
      id: "osm",
      type: "raster",
      source: "osm",
      paint: { "raster-opacity": 0.55 },
    },
  ],
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ClickCell = { lat: number; lon: number; count: number };
type OriginCell = {
  country: string | null;
  lat: number | null;
  lon: number | null;
  count: number;
};
type AdminEvents = { clicks: ClickCell[]; origins: OriginCell[] };
type AdminStatus = {
  app: {
    version: string;
    tag: string | null;
    commit: string | null;
    branch: string | null;
  };
  release: string;
  analytics: {
    enabled: boolean;
    db_size_bytes: number | null;
    last_event_ts: number | null;
  };
  system: {
    disk_total_bytes: number;
    disk_used_bytes: number;
    disk_free_bytes: number;
    rss_bytes: number;
    cpu_1m_pct: number | null;
    mem_total_bytes: number | null;
    mem_available_bytes: number | null;
  };
};

type ToolCallDetail = {
  name: string;
  args: Record<string, unknown>;
  step: number;
};
type StepTiming = {
  step: number;
  model_ms: number;
  tools_ms?: number;
  error?: boolean;
  prompt_tokens?: number;
  completion_tokens?: number;
};
type ChatMessage = {
  message_id: string;
  session_id: string;
  ts: number;
  question: string;
  answer: string;
  step_count: number;
  tools_called: string[];
  tool_calls_detail: ToolCallDetail[];
  tier: string | null;
  model: string | null;
  rejected_tiers: string[];
  model_override: string | null;
  feedback: "good" | "bad" | null;
  feedback_status: string | null;
  total_ms: number | null;
  steps_timing: StepTiming[];
  error: string | null;
  opt_out?: boolean;
};
type ChatStats = {
  total_messages: number;
  total_sessions: number;
  avg_messages_per_session: number | null;
  feedback_good: number;
  feedback_bad: number;
  bad_answers_unreviewed: number;
  avg_step_count: number | null;
  avg_resp_ms: number | null;
  p95_resp_ms: number | null;
  // The same figures over model-generated answers only. Canned and templated
  // ones take no steps and report a fixed think-time rather than a measured
  // one, so they flatten whichever average they are counted in.
  avg_step_count_llm?: number | null;
  avg_resp_ms_llm?: number | null;
  p95_resp_ms_llm?: number | null;
};

type QuestionMeta = {
  id: string;
  question: string;
  scope: string;
  datasets: string[];
  follow_up_ids: string[];
  requires_location: boolean;
  location_filter: string;
};

type QuestionStat = {
  question_tree_version: string | null;
  question_id: string;
  parent_question_id: string | null;
  clicks: number;
  feedback_good: number;
  feedback_bad: number;
  last_ts: number | null;
};

type QuestionTreeAnalytics = {
  current_version: string;
  tree: {
    version: string;
    root_ids: string[];
    questions: Record<string, QuestionMeta>;
  };
  stats: QuestionStat[];
  typed: { question_tree_version: string | null; typed: number }[];
  typed_entry_points: {
    question_tree_version: string | null;
    after_question_id: string | null;
    typed: number;
    examples: string[];
  }[];
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toClickGeoJSON(
  clicks: ClickCell[],
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: "FeatureCollection",
    features: clicks.map((c) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [c.lon, c.lat] },
      properties: { count: c.count },
    })),
  };
}

function toOriginGeoJSON(
  origins: OriginCell[],
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: "FeatureCollection",
    features: origins
      .filter((o) => o.lat != null && o.lon != null)
      .map((o) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [o.lon!, o.lat!] },
        properties: { count: o.count, country: o.country ?? "" },
      })),
  };
}

function fmt(n: number): string {
  return n.toLocaleString();
}

function relativeTime(ts: number): string {
  const sec = Math.floor(Date.now() / 1000) - ts;
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function fmtBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} KB`;
  return `${bytes} B`;
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n) + "…";
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms >= 10_000) return `${(ms / 1000).toFixed(0)}s`;
  if (ms >= 1_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function fmtSteps(n: number | null | undefined): string {
  return n != null ? n.toFixed(1) : "–";
}

const RESP_TIME_HINT =
  "First: every answer. Second: model-generated answers only — canned and " +
  "templated ones report a fixed 1.5s think-time, so including them measures " +
  "how often the fast paths hit rather than how long an answer takes.";

const STEP_COUNT_HINT =
  "First: every answer. Second: model-generated answers only — canned and " +
  "templated ones take no steps at all, so including them measures how often " +
  "the fast paths hit rather than how much work an answer takes.";

function tierColor(tier: string | null): string {
  if (!tier) return "#888";
  if (tier.includes("_paid")) return "#b8860b";
  if (tier.includes("_free")) return "#888";
  return "#888";
}

function buildCopyText(s: ChatMessage): string {
  const lines: string[] = [];

  lines.push(`**Question:** ${s.question}`);
  lines.push("");

  if (s.answer) {
    lines.push(`**Answer:** ${s.answer}`);
    lines.push("");
  }

  const modelParts: string[] = [];
  if (s.rejected_tiers?.length > 0)
    modelParts.push(`~~${s.rejected_tiers.join(", ")}~~ →`);
  if (s.tier) modelParts.push(s.tier);
  if (s.model) modelParts.push(`(${s.model})`);
  if (s.model_override) modelParts.push("· user-selected");
  lines.push(
    `**Model:** ${modelParts.join(" ") || "—"} | **Total:** ${fmtMs(s.total_ms)} | **Steps:** ${s.step_count}`,
  );

  if (s.feedback) lines.push(`**Feedback:** ${s.feedback}`);
  lines.push("");

  if (s.tool_calls_detail?.length > 0) {
    lines.push("**Tool calls:**");
    for (const t of s.tool_calls_detail) {
      lines.push(`- step ${t.step}: \`${t.name}\``);
      lines.push(
        `  \`\`\`json\n  ${JSON.stringify(t.args, null, 2).replace(/\n/g, "\n  ")}\n  \`\`\``,
      );
    }
    lines.push("");
  }

  if (s.steps_timing?.length > 0) {
    lines.push("**Timing:**");
    for (const t of s.steps_timing) {
      let row = `- step ${t.step}: model ${fmtMs(t.model_ms)}`;
      if (t.tools_ms != null) row += ` → tools ${fmtMs(t.tools_ms)}`;
      if (t.prompt_tokens != null)
        row += ` (${t.prompt_tokens.toLocaleString()}p + ${(t.completion_tokens ?? 0).toLocaleString()}c tokens)`;
      if (t.error) row += " ← error";
      lines.push(row);
    }
    const totalP = s.steps_timing.reduce(
      (a, t) => a + (t.prompt_tokens ?? 0),
      0,
    );
    const totalC = s.steps_timing.reduce(
      (a, t) => a + (t.completion_tokens ?? 0),
      0,
    );
    const tokenStr =
      totalP > 0
        ? ` ${totalP.toLocaleString()}p + ${totalC.toLocaleString()}c`
        : "";
    lines.push(`- total: ${fmtMs(s.total_ms)}${tokenStr}`);
    lines.push("");
  }

  if (s.error) {
    lines.push(`**Error:** ${s.error}`);
  }

  return lines.join("\n").trim();
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<"map" | "chat" | "questions">(
    "map",
  );

  // --- Map tab state ---
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [events, setEvents] = useState<AdminEvents | null>(null);
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [healthMs, setHealthMs] = useState<number | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [visibleLayers, setVisibleLayers] = useState({
    clicks: true,
    origins: true,
  });

  // --- Chat tab state ---
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatStats, setChatStats] = useState<ChatStats | null>(null);
  const [badAnswers, setBadAnswers] = useState<ChatMessage[]>([]);
  const [chatPage, setChatPage] = useState(0);
  const [chatRefreshKey, setChatRefreshKey] = useState(0);
  const [chatLoading, setChatLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [highlightedSessionId, setHighlightedSessionId] = useState<
    string | null
  >(null);
  const CHAT_PAGE_SIZE = 50;

  // --- Questions tab state ---
  const [questionTreeData, setQuestionTreeData] =
    useState<QuestionTreeAnalytics | null>(null);
  const [questionsVersion, setQuestionsVersion] = useState<string | null>(null);
  const [questionsError, setQuestionsError] = useState<string | null>(null);

  const apiBase = useMemo(() => {
    if (process.env.NEXT_PUBLIC_CLIMATE_API_BASE) {
      return process.env.NEXT_PUBLIC_CLIMATE_API_BASE.replace(/\/+$/, "");
    }
    if (typeof window === "undefined")
      return `http://localhost:${DEFAULT_API_PORT}`;
    return `http://${window.location.hostname}:${DEFAULT_API_PORT}`;
  }, []);

  const toggleLayer = useCallback((layer: "clicks" | "origins") => {
    setVisibleLayers((prev) => {
      const next = { ...prev, [layer]: !prev[layer] };
      const map = mapRef.current;
      if (map) {
        if (layer === "clicks" && map.getLayer("clicks-heat"))
          map.setLayoutProperty(
            "clicks-heat",
            "visibility",
            next.clicks ? "visible" : "none",
          );
        if (layer === "origins" && map.getLayer("origins-circle"))
          map.setLayoutProperty(
            "origins-circle",
            "visibility",
            next.origins ? "visible" : "none",
          );
      }
      return next;
    });
  }, []);

  // Fetch chat stats on mount so the badge is visible before visiting the Chat tab
  useEffect(() => {
    fetch(`${apiBase}/api/admin/chat/sessions?limit=1`)
      .then(
        (r) =>
          r.json() as Promise<{ messages: ChatMessage[]; stats: ChatStats }>,
      )
      .then((res) => setChatStats(res.stats))
      .catch(() => {});
  }, [apiBase]);

  // Fetch map/status data
  useEffect(() => {
    const t0 = performance.now();
    fetch(`${apiBase}/healthz`)
      .then((r) => {
        if (r.ok) setHealthMs(performance.now() - t0);
      })
      .catch(() => {});
    fetch(`${apiBase}/api/admin/events`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<AdminEvents>;
      })
      .then(setEvents)
      .catch((e: unknown) =>
        setEventsError(
          e instanceof Error ? e.message : "Failed to load analytics",
        ),
      );
  }, [apiBase]);

  useEffect(() => {
    const fetchStatus = () => {
      fetch(`${apiBase}/api/admin/status`)
        .then((r) => {
          if (!r.ok) return;
          return r.json() as Promise<AdminStatus>;
        })
        .then((s) => s && setStatus(s))
        .catch(() => {});
    };
    fetchStatus();
    const id = setInterval(fetchStatus, 15_000);
    return () => clearInterval(id);
  }, [apiBase]);

  // Fetch chat data when Chat tab is opened or page changes
  useEffect(() => {
    if (activeTab !== "chat") return;
    setChatLoading(true);
    const offset = chatPage * CHAT_PAGE_SIZE;
    Promise.all([
      fetch(
        `${apiBase}/api/admin/chat/sessions?limit=${CHAT_PAGE_SIZE}&offset=${offset}`,
      ).then(
        (r) =>
          r.json() as Promise<{ messages: ChatMessage[]; stats: ChatStats }>,
      ),
      fetch(`${apiBase}/api/admin/chat/bad-answers?limit=200`).then(
        (r) =>
          r.json() as Promise<{ bad_answers: ChatMessage[]; stats: ChatStats }>,
      ),
    ])
      .then(([messagesRes, badRes]) => {
        setChatMessages(messagesRes.messages);
        setChatStats(messagesRes.stats);
        setBadAnswers(
          badRes.bad_answers.filter((m) => m.feedback_status === "new"),
        );
      })
      .catch(() => {})
      .finally(() => setChatLoading(false));
  }, [apiBase, activeTab, chatPage, chatRefreshKey]);

  // Fetch question-tree analytics when the Questions tab is opened
  useEffect(() => {
    if (activeTab !== "questions") return;
    setChatLoading(true);
    setQuestionsError(null);
    fetch(`${apiBase}/api/admin/chat/question-tree`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<QuestionTreeAnalytics>;
      })
      .then((res) => {
        setQuestionTreeData(res);
        // Default to the newest revision that actually has clicks, falling
        // back to the live tree when analytics are still empty.
        setQuestionsVersion((prev) => {
          if (prev !== null) return prev;
          const withClicks = [
            ...new Set(
              res.stats
                .map((s) => s.question_tree_version)
                .filter((v): v is string => v !== null),
            ),
          ].sort();
          return withClicks[withClicks.length - 1] ?? res.current_version;
        });
      })
      .catch((e) => setQuestionsError(String(e)))
      .finally(() => setChatLoading(false));
  }, [apiBase, activeTab, chatRefreshKey]);

  // Every tree revision present in the data, newest first, plus the live one.
  const questionVersions = useMemo(() => {
    if (!questionTreeData) return [] as (string | null)[];
    const seen = new Set<string | null>([questionTreeData.current_version]);
    for (const s of questionTreeData.stats) seen.add(s.question_tree_version);
    for (const t of questionTreeData.typed) seen.add(t.question_tree_version);
    const named = [...seen]
      .filter((v): v is string => v !== null)
      .sort()
      .reverse();
    // Untracked rows (pre-versioning) sort last — they cannot be attributed.
    return seen.has(null) ? [...named, null] : named;
  }, [questionTreeData]);

  // Click counts for the selected revision. Keyed two ways: per question (the
  // total, for the flat list) and per parent→child edge, because the same
  // question hangs off several parents and "clicked from here" is the number
  // that says whether a given follow-up placement works.
  const { questionCounts, edgeCounts } = useMemo(() => {
    const byId = new Map<
      string,
      { clicks: number; good: number; bad: number }
    >();
    const byEdge = new Map<
      string,
      { clicks: number; good: number; bad: number }
    >();
    if (!questionTreeData) return { questionCounts: byId, edgeCounts: byEdge };
    for (const s of questionTreeData.stats) {
      if (s.question_tree_version !== questionsVersion) continue;
      const prev = byId.get(s.question_id) ?? { clicks: 0, good: 0, bad: 0 };
      byId.set(s.question_id, {
        clicks: prev.clicks + s.clicks,
        good: prev.good + s.feedback_good,
        bad: prev.bad + s.feedback_bad,
      });
      // parent === null means the question was clicked as a root chip.
      const edgeKey = `${s.parent_question_id ?? ""}>${s.question_id}`;
      const prevEdge = byEdge.get(edgeKey) ?? { clicks: 0, good: 0, bad: 0 };
      byEdge.set(edgeKey, {
        clicks: prevEdge.clicks + s.clicks,
        good: prevEdge.good + s.feedback_good,
        bad: prevEdge.bad + s.feedback_bad,
      });
    }
    return { questionCounts: byId, edgeCounts: byEdge };
  }, [questionTreeData, questionsVersion]);

  // Group messages by session_id, newest session first
  const groupedSessions = useMemo(() => {
    const map = new Map<string, ChatMessage[]>();
    for (const msg of chatMessages) {
      const group = map.get(msg.session_id) ?? [];
      group.push(msg);
      map.set(msg.session_id, group);
    }
    // Sort messages within each session chronologically, sessions by newest message first
    const groups = Array.from(map.entries()).map(([sid, msgs]) => ({
      session_id: sid,
      messages: msgs.sort((a, b) => a.ts - b.ts),
      latest_ts: Math.max(...msgs.map((m) => m.ts)),
    }));
    return groups.sort((a, b) => b.latest_ts - a.latest_ts);
  }, [chatMessages]);

  async function markReviewed(messageId: string) {
    await fetch(`${apiBase}/api/chat/${messageId}/reviewed`, {
      method: "POST",
    });
    setBadAnswers((prev) => prev.filter((m) => m.message_id !== messageId));
    setChatMessages((prev) =>
      prev.map((m) =>
        m.message_id === messageId ? { ...m, feedback_status: "reviewed" } : m,
      ),
    );
    if (chatStats) {
      setChatStats({
        ...chatStats,
        bad_answers_unreviewed: Math.max(
          0,
          chatStats.bad_answers_unreviewed - 1,
        ),
      });
    }
  }

  // Map setup
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [0, 20],
      zoom: 1.5,
      attributionControl: false,
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }));
    map.on("load", () => setMapReady(true));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !events) return;
    const clickGeo = toClickGeoJSON(events.clicks);
    const originGeo = toOriginGeoJSON(events.origins);
    const maxCount = Math.max(1, ...events.clicks.map((c) => c.count));
    if (map.getSource("clicks")) {
      (map.getSource("clicks") as maplibregl.GeoJSONSource).setData(clickGeo);
    } else {
      map.addSource("clicks", { type: "geojson", data: clickGeo });
      map.addLayer({
        id: "clicks-heat",
        type: "heatmap",
        source: "clicks",
        paint: {
          "heatmap-weight": [
            "interpolate",
            ["linear"],
            ["get", "count"],
            0,
            0,
            maxCount,
            1,
          ],
          "heatmap-intensity": [
            "interpolate",
            ["linear"],
            ["zoom"],
            0,
            1,
            8,
            3,
          ],
          "heatmap-color": [
            "interpolate",
            ["linear"],
            ["heatmap-density"],
            0,
            "rgba(0,0,255,0)",
            0.2,
            "rgb(0,100,255)",
            0.5,
            "rgb(0,220,160)",
            0.8,
            "rgb(255,220,0)",
            1,
            "rgb(255,80,0)",
          ],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 8, 6, 20],
          "heatmap-opacity": 0.85,
        },
      });
    }
    if (map.getSource("origins")) {
      (map.getSource("origins") as maplibregl.GeoJSONSource).setData(originGeo);
    } else {
      map.addSource("origins", { type: "geojson", data: originGeo });
      map.addLayer({
        id: "origins-circle",
        type: "circle",
        source: "origins",
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["get", "count"],
            1,
            5,
            50,
            20,
          ],
          "circle-color": "rgba(255, 160, 40, 0.7)",
          "circle-stroke-color": "rgba(255, 200, 100, 0.9)",
          "circle-stroke-width": 1,
        },
      });
      const popup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
      });
      map.on("mouseenter", "origins-circle", (e) => {
        map.getCanvas().style.cursor = "pointer";
        const feat = e.features?.[0];
        if (!feat) return;
        const country = feat.properties?.country || "Unknown";
        const count = feat.properties?.count ?? 0;
        const coords = (feat.geometry as GeoJSON.Point).coordinates.slice();
        popup
          .setLngLat([coords[0], coords[1]])
          .setHTML(
            `<strong>${country}</strong><br/>${count} session${count === 1 ? "" : "s"}`,
          )
          .addTo(map);
      });
      map.on("mouseleave", "origins-circle", () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
      });
    }
  }, [events, mapReady]);

  const totalClicks = events?.clicks.reduce((s, c) => s + c.count, 0) ?? 0;
  const totalSessions = events?.origins.reduce((s, o) => s + o.count, 0) ?? 0;
  const uniqueCountries = events
    ? new Set(events.origins.map((o) => o.country).filter(Boolean)).size
    : 0;
  const unreviewedCount = chatStats?.bad_answers_unreviewed ?? 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100dvh",
        background: "#111",
        color: "#eee",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      {/* Header + tabs */}
      <div
        style={{
          padding: "10px 20px",
          borderBottom: "1px solid #2a2a2a",
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 20,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: 0.3 }}>
          Admin Dashboard
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          <TabButton
            active={activeTab === "map"}
            onClick={() => setActiveTab("map")}
          >
            Map
          </TabButton>
          <TabButton
            active={activeTab === "chat"}
            onClick={() => setActiveTab("chat")}
          >
            Chat
            {unreviewedCount > 0 && (
              <span
                style={{
                  marginLeft: 6,
                  background: "#e53e3e",
                  color: "#fff",
                  borderRadius: 999,
                  padding: "1px 6px",
                  fontSize: 11,
                  fontWeight: 700,
                }}
              >
                {unreviewedCount}
              </span>
            )}
          </TabButton>
          <TabButton
            active={activeTab === "questions"}
            onClick={() => setActiveTab("questions")}
          >
            Questions
          </TabButton>
        </div>
        <button
          onClick={() => setChatRefreshKey((k) => k + 1)}
          disabled={chatLoading}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid #333",
            color: chatLoading ? "#444" : "#888",
            borderRadius: 6,
            padding: "4px 10px",
            fontSize: 12,
            cursor: chatLoading ? "default" : "pointer",
          }}
        >
          {chatLoading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      {/* Map tab — kept mounted so MapLibre never needs to reinitialise */}
      <div style={{ display: activeTab === "map" ? "contents" : "none" }}>
        <>
          {/* Status cards */}
          <div
            style={{
              display: "flex",
              gap: 10,
              padding: "10px 14px",
              flexShrink: 0,
              flexWrap: "wrap",
            }}
          >
            <Card title="Backend">
              <Row
                label="Health"
                value={healthMs != null ? `${healthMs.toFixed(0)} ms` : "–"}
                ok={healthMs != null ? healthMs < 500 : undefined}
              />
              {eventsError && (
                <Row label="Events" value={eventsError} ok={false} />
              )}
            </Card>
            <Card title="Version">
              <Row label="App" value={status?.app.version ?? "–"} />
              <Row label="Tag" value={status?.app.tag ?? "–"} />
              <Row label="Branch" value={status?.app.branch ?? "–"} />
              <Row
                label="Commit"
                value={status?.app.commit?.slice(0, 8) ?? "–"}
              />
              <Row label="Release" value={status?.release ?? "–"} />
            </Card>
            <Card title="System">
              <Row
                label="Disk used"
                value={
                  status
                    ? `${fmtBytes(status.system.disk_used_bytes)} / ${fmtBytes(status.system.disk_total_bytes)}`
                    : "–"
                }
              />
              <Row
                label="Disk free"
                value={status ? fmtBytes(status.system.disk_free_bytes) : "–"}
              />
              <Row
                label="RAM (process)"
                value={status ? fmtBytes(status.system.rss_bytes) : "–"}
              />
              {status?.system.mem_total_bytes != null &&
                status.system.mem_available_bytes != null && (
                  <Row
                    label="RAM (system)"
                    value={`${fmtBytes(status.system.mem_total_bytes - status.system.mem_available_bytes)} / ${fmtBytes(status.system.mem_total_bytes)}`}
                  />
                )}
              <Row
                label="CPU (1 min avg)"
                value={
                  status
                    ? status.system.cpu_1m_pct != null
                      ? `${status.system.cpu_1m_pct}%`
                      : "sampling…"
                    : "–"
                }
              />
            </Card>
            <Card title="Analytics">
              <Row
                label="Recording"
                value={
                  status
                    ? status.analytics.enabled
                      ? "enabled"
                      : "disabled"
                    : "–"
                }
                ok={status?.analytics.enabled}
              />
              <Row label="Sessions" value={events ? fmt(totalSessions) : "–"} />
              <Row label="Clicks" value={events ? fmt(totalClicks) : "–"} />
              <Row
                label="Countries"
                value={events ? fmt(uniqueCountries) : "–"}
              />
              {status?.analytics.db_size_bytes != null && (
                <Row
                  label="DB size"
                  value={fmtBytes(status.analytics.db_size_bytes)}
                />
              )}
              <Row
                label="Last event"
                value={
                  status
                    ? status.analytics.last_event_ts != null
                      ? relativeTime(status.analytics.last_event_ts)
                      : "none"
                    : "–"
                }
              />
            </Card>
          </div>

          {/* Map */}
          <div ref={mapContainerRef} style={{ flex: 1, minHeight: 0 }} />

          {/* Legend */}
          <div
            style={{
              padding: "8px 16px",
              borderTop: "1px solid #2a2a2a",
              display: "flex",
              gap: 24,
              fontSize: 12,
              color: "#aaa",
              flexShrink: 0,
            }}
          >
            <LegendItem
              color="rgba(255,220,0,0.85)"
              label="Map clicks (heatmap)"
              active={visibleLayers.clicks}
              onClick={() => toggleLayer("clicks")}
            />
            <LegendItem
              color="rgba(255,160,40,0.7)"
              label="User origins (circles)"
              circle
              active={visibleLayers.origins}
              onClick={() => toggleLayer("origins")}
            />
          </div>
        </>
      </div>

      {/* Chat tab */}
      {activeTab === "chat" && (
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: "auto",
            padding: "12px 16px",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          {/* Stats cards */}
          {chatStats && (
            <div
              style={{
                display: "flex",
                gap: 10,
                flexWrap: "wrap",
                flexShrink: 0,
              }}
            >
              <Card title="Chat activity">
                <Row label="Sessions" value={fmt(chatStats.total_sessions)} />
                <Row label="Messages" value={fmt(chatStats.total_messages)} />
                <Row
                  label="Msgs / session"
                  value={
                    chatStats.avg_messages_per_session != null
                      ? chatStats.avg_messages_per_session.toFixed(1)
                      : "–"
                  }
                />
                <Row
                  label="Avg steps (all / LLM)"
                  value={`${fmtSteps(chatStats.avg_step_count)} / ${fmtSteps(
                    chatStats.avg_step_count_llm,
                  )}`}
                  title={STEP_COUNT_HINT}
                />
                <Row
                  label="Avg resp (all / LLM)"
                  value={`${fmtMs(chatStats.avg_resp_ms)} / ${fmtMs(
                    chatStats.avg_resp_ms_llm,
                  )}`}
                  title={RESP_TIME_HINT}
                />
                <Row
                  label="p95 resp (all / LLM)"
                  value={`${fmtMs(chatStats.p95_resp_ms)} / ${fmtMs(
                    chatStats.p95_resp_ms_llm,
                  )}`}
                  title={RESP_TIME_HINT}
                />
              </Card>
              <Card title="Feedback">
                <Row label="👍 Good" value={fmt(chatStats.feedback_good)} />
                <Row label="👎 Bad" value={fmt(chatStats.feedback_bad)} />
                <Row
                  label="Unreviewed"
                  value={fmt(chatStats.bad_answers_unreviewed)}
                  ok={chatStats.bad_answers_unreviewed === 0}
                />
              </Card>
            </div>
          )}

          {/* Bad answers inbox */}
          {badAnswers.length > 0 && (
            <section>
              <SectionTitle>
                To review ({badAnswers.length} unreviewed)
              </SectionTitle>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {badAnswers.map((m) => (
                  <MessageRow
                    key={m.message_id}
                    message={m}
                    expanded={expandedId === m.message_id}
                    onToggle={() =>
                      setExpandedId(
                        expandedId === m.message_id ? null : m.message_id,
                      )
                    }
                    onMarkReviewed={() => void markReviewed(m.message_id)}
                    onViewSession={() => setHighlightedSessionId(m.session_id)}
                    highlight
                  />
                ))}
              </div>
            </section>
          )}

          {/* All sessions grouped */}
          <section style={{ flex: 1 }}>
            <SectionTitle>
              All sessions{chatLoading ? " (loading…)" : ""}
            </SectionTitle>
            {groupedSessions.length === 0 && !chatLoading && (
              <div style={{ color: "#555", fontSize: 13 }}>
                No messages recorded yet.
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {groupedSessions.map(({ session_id, messages, latest_ts }) => {
                const isHighlighted = highlightedSessionId === session_id;
                return (
                  <div
                    key={session_id}
                    style={{
                      border:
                        "1px solid " + (isHighlighted ? "#7ec8e3" : "#333"),
                      borderRadius: 8,
                      overflow: "hidden",
                      background: "#1a1a1a",
                    }}
                  >
                    <div
                      style={{
                        padding: "6px 12px",
                        background: "#1d1d1d",
                        display: "flex",
                        gap: 10,
                        fontSize: 11,
                        color: "#777",
                        alignItems: "center",
                        borderBottom: "1px solid #333",
                      }}
                    >
                      <span style={{ fontFamily: "ui-monospace, monospace" }}>
                        {session_id.slice(0, 8)}…
                      </span>
                      <span>
                        {messages.length} message
                        {messages.length !== 1 ? "s" : ""}
                      </span>
                      <span>{relativeTime(latest_ts)}</span>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 2,
                        padding: "4px 0",
                      }}
                    >
                      {messages.map((m) => (
                        <MessageRow
                          key={m.message_id}
                          message={m}
                          expanded={expandedId === m.message_id}
                          onToggle={() =>
                            setExpandedId(
                              expandedId === m.message_id ? null : m.message_id,
                            )
                          }
                          onMarkReviewed={
                            (m.feedback === "bad" || !!m.error) &&
                            m.feedback_status === "new"
                              ? () => void markReviewed(m.message_id)
                              : undefined
                          }
                          indented
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Pagination */}
            {(chatPage > 0 || chatMessages.length === CHAT_PAGE_SIZE) && (
              <div
                style={{
                  display: "flex",
                  gap: 8,
                  marginTop: 12,
                  alignItems: "center",
                }}
              >
                <button
                  onClick={() => setChatPage((p) => Math.max(0, p - 1))}
                  disabled={chatPage === 0}
                  style={paginationBtnStyle(chatPage === 0)}
                >
                  ← Prev
                </button>
                <span style={{ fontSize: 12, color: "#666" }}>
                  Page {chatPage + 1}
                </span>
                <button
                  onClick={() => setChatPage((p) => p + 1)}
                  disabled={chatMessages.length < CHAT_PAGE_SIZE}
                  style={paginationBtnStyle(
                    chatMessages.length < CHAT_PAGE_SIZE,
                  )}
                >
                  Next →
                </button>
              </div>
            )}
          </section>
        </div>
      )}

      {/* Questions tab */}
      {activeTab === "questions" && (
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: "auto",
            padding: "12px 16px",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          {questionsError && (
            <div style={{ color: "#e53e3e", fontSize: 13 }}>
              Failed to load question analytics: {questionsError}
            </div>
          )}

          {questionTreeData && (
            <QuestionTreePanel
              data={questionTreeData}
              versions={questionVersions}
              selectedVersion={questionsVersion}
              onSelectVersion={setQuestionsVersion}
              counts={questionCounts}
              edgeCounts={edgeCounts}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function QuestionTreePanel({
  data,
  versions,
  selectedVersion,
  onSelectVersion,
  counts,
  edgeCounts,
}: {
  data: QuestionTreeAnalytics;
  versions: (string | null)[];
  selectedVersion: string | null;
  onSelectVersion: (v: string | null) => void;
  counts: Map<string, { clicks: number; good: number; bad: number }>;
  edgeCounts: Map<string, { clicks: number; good: number; bad: number }>;
}) {
  // Only the revision currently on disk can be drawn as a tree — earlier
  // revisions may have had different wording, children, or questions that no
  // longer exist, so those are listed flat with their raw ids.
  const isLiveTree = selectedVersion === data.current_version;
  const questions = data.tree.questions;

  const totalClicks = [...counts.values()].reduce((a, c) => a + c.clicks, 0);
  const typedCount =
    data.typed.find((t) => t.question_tree_version === selectedVersion)
      ?.typed ?? 0;

  // Ids seen in analytics for this revision but absent from the live tree.
  const orphanIds = [
    ...new Set(
      data.stats
        .filter((s) => s.question_tree_version === selectedVersion)
        .map((s) => s.question_id),
    ),
  ]
    .filter((id) => !questions[id])
    .sort();

  const maxClicks = Math.max(1, ...[...counts.values()].map((c) => c.clicks));

  const entryPoints = data.typed_entry_points.filter(
    (e) => e.question_tree_version === selectedVersion,
  );

  // The question tree is a dense DAG, not a tree: most questions are offered
  // as a follow-up by several parents. Expanding a subtree per distinct path
  // is combinatorial — for the 37-node/132-edge tree that is millions of rows,
  // enough to kill the renderer. Each question is therefore expanded once, on
  // first encounter; later encounters render as a non-expanding reference.
  const expanded = new Set<string>();

  function renderNode(
    id: string,
    depth: number,
    path: string,
    parentId: string | null,
  ): React.ReactNode {
    const node = questions[id];
    if (!node) return null;
    // Count for this position in the tree, not the question's grand total: a
    // question offered under four parents needs to show which of those
    // placements people actually take.
    const stat = edgeCounts.get(`${parentId ?? ""}>${id}`);
    const clicks = stat?.clicks ?? 0;
    const total = counts.get(id)?.clicks ?? 0;
    const alreadyExpanded = expanded.has(id);
    if (!alreadyExpanded) expanded.add(id);
    const children = alreadyExpanded ? [] : node.follow_up_ids;

    return (
      <div key={`${path}>${id}`}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "3px 0",
            paddingLeft: depth * 18,
            borderBottom: "1px solid #1e1e1e",
            opacity: alreadyExpanded ? 0.55 : 1,
          }}
        >
          <div
            style={{
              width: 46,
              flexShrink: 0,
              textAlign: "right",
              fontVariantNumeric: "tabular-nums",
              fontSize: 12,
              fontWeight: clicks > 0 ? 700 : 400,
              color: clicks > 0 ? "#eee" : "#555",
            }}
          >
            {clicks}
          </div>
          <div
            style={{
              width: 60,
              flexShrink: 0,
              height: 6,
              background: "#222",
              borderRadius: 3,
              overflow: "hidden",
            }}
            title={`${clicks} clicks`}
          >
            <div
              style={{
                width: `${(clicks / maxClicks) * 100}%`,
                height: "100%",
                background: clicks > 0 ? "#3b82f6" : "transparent",
              }}
            />
          </div>
          <span
            style={{
              fontSize: 13,
              color: clicks > 0 ? "#ddd" : "#666",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
            title={`${node.id} · ${node.scope}`}
          >
            {depth > 0 && <span style={{ color: "#444" }}>└ </span>}
            {node.question}
            {total > clicks && (
              <span
                style={{ color: "#666", marginLeft: 6, fontSize: 11 }}
                title={`${total} clicks in total across every place this question is offered`}
              >
                ({total} total)
              </span>
            )}
            {alreadyExpanded && node.follow_up_ids.length > 0 && (
              <span style={{ color: "#555", marginLeft: 6, fontSize: 11 }}>
                ↑ shown above
              </span>
            )}
          </span>
          {stat && (stat.good > 0 || stat.bad > 0) && (
            <span style={{ fontSize: 11, color: "#666", flexShrink: 0 }}>
              {stat.good > 0 && (
                <span style={{ color: "#48bb78" }}>▲{stat.good}</span>
              )}{" "}
              {stat.bad > 0 && (
                <span style={{ color: "#e53e3e" }}>▼{stat.bad}</span>
              )}
            </span>
          )}
        </div>
        {children.map((childId) =>
          renderNode(childId, depth + 1, `${path}>${id}`, id),
        )}
      </div>
    );
  }

  return (
    <>
      <div
        style={{ display: "flex", gap: 10, flexWrap: "wrap", flexShrink: 0 }}
      >
        <Card title="Tree revision">
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {versions.map((v) => (
              <button
                key={v ?? "untracked"}
                onClick={() => onSelectVersion(v)}
                style={{
                  background: v === selectedVersion ? "#2a2a2a" : "transparent",
                  border:
                    "1px solid " + (v === selectedVersion ? "#555" : "#2a2a2a"),
                  borderRadius: 6,
                  color: v === selectedVersion ? "#eee" : "#777",
                  padding: "3px 9px",
                  fontSize: 12,
                  cursor: "pointer",
                }}
              >
                {v ?? "untracked"}
                {v === data.current_version && (
                  <span style={{ color: "#48bb78", marginLeft: 5 }}>live</span>
                )}
              </button>
            ))}
          </div>
        </Card>
        <Card title="This revision">
          <Row label="Chip clicks" value={fmt(totalClicks)} />
          <Row label="Typed questions" value={fmt(typedCount)} />
          <Row
            label="Typed share"
            value={
              totalClicks + typedCount > 0
                ? `${Math.round((typedCount / (totalClicks + typedCount)) * 100)}%`
                : "—"
            }
          />
          <Row
            label="Questions used"
            value={`${counts.size} / ${isLiveTree ? Object.keys(questions).length : "?"}`}
          />
        </Card>
      </div>

      <section>
        <SectionTitle>Where people start typing</SectionTitle>
        <div style={{ fontSize: 12, color: "#777", padding: "2px 0 8px" }}>
          The last suggestion clicked before a free-typed question. A question
          that keeps appearing here is one whose follow-ups do not cover what
          people wanted to ask next.
        </div>
        {entryPoints.length === 0 ? (
          <div style={{ fontSize: 13, color: "#666" }}>
            No free-typed questions recorded for this revision.
          </div>
        ) : (
          entryPoints.map((e) => (
            <div
              key={e.after_question_id ?? "cold-start"}
              style={{
                display: "flex",
                gap: 8,
                padding: "5px 0",
                borderBottom: "1px solid #1e1e1e",
              }}
            >
              <span
                style={{
                  width: 46,
                  flexShrink: 0,
                  textAlign: "right",
                  fontVariantNumeric: "tabular-nums",
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                {e.typed}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, color: "#ddd" }}>
                  {e.after_question_id === null ? (
                    <span style={{ color: "#a0793a" }}>
                      Typed straight away — no suggestion used
                    </span>
                  ) : (
                    (questions[e.after_question_id]?.question ??
                    e.after_question_id)
                  )}
                </div>
                {e.examples.length > 0 && (
                  <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
                    {e.examples.map((q, i) => (
                      <div key={i}>“{truncate(q, 90)}”</div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </section>

      <section>
        <SectionTitle>
          Question tree — {selectedVersion ?? "untracked"}
        </SectionTitle>
        {!isLiveTree && (
          <div style={{ fontSize: 12, color: "#a0793a", padding: "6px 0" }}>
            {selectedVersion === null
              ? "These rows predate version tracking, so they cannot be attributed to a revision. Shown as a flat list."
              : "This is not the revision currently on disk. Its wording and follow-up structure are no longer available, so questions are listed flat by id."}
          </div>
        )}

        {isLiveTree ? (
          <div style={{ marginTop: 6 }}>
            {data.tree.root_ids.map((id) => renderNode(id, 0, "", null))}
          </div>
        ) : (
          <div style={{ marginTop: 6 }}>
            {[...counts.entries()]
              .sort((a, b) => b[1].clicks - a[1].clicks)
              .map(([id, stat]) => (
                <div
                  key={id}
                  style={{
                    display: "flex",
                    gap: 8,
                    padding: "3px 0",
                    borderBottom: "1px solid #1e1e1e",
                    fontSize: 13,
                  }}
                >
                  <span
                    style={{
                      width: 46,
                      textAlign: "right",
                      fontVariantNumeric: "tabular-nums",
                      fontWeight: 700,
                    }}
                  >
                    {stat.clicks}
                  </span>
                  <span style={{ color: "#bbb" }}>
                    {questions[id]?.question ?? id}
                  </span>
                  {!questions[id] && (
                    <span style={{ color: "#555", fontSize: 11 }}>
                      (not in live tree)
                    </span>
                  )}
                </div>
              ))}
          </div>
        )}

        {isLiveTree && orphanIds.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, color: "#a0793a", marginBottom: 4 }}>
              Recorded under this revision but no longer in the tree — these ids
              were removed or renamed without the version being bumped:
            </div>
            {orphanIds.map((id) => (
              <div
                key={id}
                style={{ fontSize: 12, color: "#888", padding: "2px 0" }}
              >
                {counts.get(id)?.clicks ?? 0} · {id}
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? "#2a2a2a" : "transparent",
        border: "1px solid " + (active ? "#444" : "transparent"),
        borderRadius: 6,
        color: active ? "#eee" : "#777",
        padding: "4px 12px",
        fontSize: 13,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      {children}
    </button>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 700,
        color: "#888",
        textTransform: "uppercase",
        letterSpacing: 1,
        marginBottom: 8,
      }}
    >
      {children}
    </div>
  );
}

function MessageRow({
  message: s,
  expanded,
  onToggle,
  onMarkReviewed,
  onViewSession,
  highlight = false,
  indented = false,
}: {
  message: ChatMessage;
  expanded: boolean;
  onToggle: () => void;
  onMarkReviewed?: () => void;
  onViewSession?: () => void;
  highlight?: boolean;
  indented?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const feedbackIcon =
    s.feedback === "good" ? "👍" : s.feedback === "bad" ? "👎" : "—";
  const feedbackColor =
    s.feedback === "good" ? "#4caf50" : s.feedback === "bad" ? "#f66" : "#555";

  function handleCopy() {
    void navigator.clipboard.writeText(buildCopyText(s)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div
      style={{
        background: highlight
          ? "rgba(229,62,62,0.08)"
          : indented
            ? "transparent"
            : "#1a1a1a",
        border: indented
          ? "none"
          : "1px solid " + (highlight ? "rgba(229,62,62,0.3)" : "#2a2a2a"),
        borderRadius: indented ? 0 : 7,
        borderBottom: indented ? "1px solid #2a2a2a" : undefined,
        overflow: "hidden",
      }}
    >
      {/* Summary row */}
      <div
        onClick={onToggle}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 12px",
          cursor: "pointer",
          fontSize: 12,
          background: expanded ? "#252525" : "transparent",
          transition: "background 120ms ease",
        }}
      >
        <span style={{ color: "#777", flexShrink: 0, width: 60 }}>
          {relativeTime(s.ts)}
        </span>
        <span
          style={{
            flex: 1,
            minWidth: 0,
            color: "#ccc",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {s.error && (
            <span
              style={{ color: "#f66", marginRight: 5, fontSize: 10 }}
              title={s.error}
            >
              ⬤
            </span>
          )}
          {s.opt_out && (
            <span
              style={{ color: "#6ab0f3", marginRight: 5, fontSize: 10 }}
              title="Analytics disabled in this browser — excluded from stats and question counts"
            >
              test
            </span>
          )}
          {truncate(s.question, 80)}
        </span>
        <span
          style={{
            color: "#888",
            flexShrink: 0,
            width: 130,
            textAlign: "right",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {s.model_override && (
            <span style={{ color: "#e8a838", marginRight: 4, fontSize: 10 }}>
              user
            </span>
          )}
          <span style={{ color: tierColor(s.tier) }}>{s.tier ?? "—"}</span>
        </span>
        <span
          style={{
            color: "#888",
            flexShrink: 0,
            width: 50,
            textAlign: "right",
          }}
        >
          {s.step_count} steps
        </span>
        <span
          style={{
            color: "#888",
            flexShrink: 0,
            width: 44,
            textAlign: "right",
          }}
        >
          {fmtMs(s.total_ms)}
        </span>
        <span
          style={{
            color: feedbackColor,
            flexShrink: 0,
            width: 24,
            textAlign: "center",
          }}
        >
          {feedbackIcon}
        </span>
        <span style={{ color: "#666", flexShrink: 0 }}>
          {expanded ? "▲" : "▼"}
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div
          style={{
            padding: "0 12px 12px",
            borderTop: "1px solid #333",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <DetailSection label="Question">
            <pre style={preStyle}>{s.question}</pre>
          </DetailSection>
          <DetailSection label="Answer">
            <pre style={preStyle}>{s.answer || "—"}</pre>
          </DetailSection>
          <DetailSection label="Model selection">
            <div
              style={{
                display: "flex",
                gap: 6,
                fontSize: 12,
                fontFamily: "ui-monospace, monospace",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              {s.rejected_tiers?.map((t) => (
                <span
                  key={t}
                  style={{ color: "#555", textDecoration: "line-through" }}
                >
                  {t}
                </span>
              ))}
              {s.rejected_tiers?.length > 0 && (
                <span style={{ color: "#444" }}>→</span>
              )}
              <span style={{ color: tierColor(s.tier) }}>{s.tier ?? "—"}</span>
              {s.model && <span style={{ color: "#666" }}>({s.model})</span>}
              {s.model_override && (
                <span style={{ color: "#e8a838", fontSize: 11 }}>
                  · user-selected
                </span>
              )}
            </div>
          </DetailSection>
          {s.tool_calls_detail?.length > 0 && (
            <DetailSection label={`Tool calls (${s.tool_calls_detail.length})`}>
              {s.tool_calls_detail.map((t: ToolCallDetail, i: number) => (
                <div key={i} style={{ marginBottom: 4 }}>
                  <span
                    style={{
                      color: "#7ec8e3",
                      fontFamily: "monospace",
                      fontSize: 12,
                    }}
                  >
                    step {t.step}: {t.name}
                  </span>
                  <pre style={{ ...preStyle, marginTop: 2, color: "#888" }}>
                    {JSON.stringify(t.args, null, 2)}
                  </pre>
                </div>
              ))}
            </DetailSection>
          )}
          {s.error && (
            <DetailSection label="Error">
              <pre style={{ ...preStyle, color: "#f66" }}>{s.error}</pre>
            </DetailSection>
          )}
          {s.steps_timing?.length > 0 && (
            <DetailSection label="Timing breakdown">
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {s.steps_timing.map((t: StepTiming, i: number) => {
                  const isLast = i === s.steps_timing.length - 1;
                  const hasTools = t.tools_ms != null;
                  return (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        gap: 8,
                        fontSize: 12,
                        fontFamily: "ui-monospace, monospace",
                        alignItems: "center",
                      }}
                    >
                      <span style={{ color: "#555", width: 48, flexShrink: 0 }}>
                        step {t.step}
                      </span>
                      <span style={{ color: "#7ec8e3" }}>
                        model {fmtMs(t.model_ms)}
                      </span>
                      {hasTools && (
                        <span style={{ color: "#888" }}>
                          → tools {fmtMs(t.tools_ms)}
                        </span>
                      )}
                      {t.prompt_tokens != null && (
                        <span style={{ color: "#666", fontSize: 11 }}>
                          {t.prompt_tokens.toLocaleString()}p +{" "}
                          {(t.completion_tokens ?? 0).toLocaleString()}c
                        </span>
                      )}
                      {t.error && (
                        <span style={{ color: "#f66", fontSize: 11 }}>
                          ← error
                        </span>
                      )}
                      {isLast && !hasTools && !t.error && (
                        <span style={{ color: "#4caf50", fontSize: 11 }}>
                          ← final answer
                        </span>
                      )}
                    </div>
                  );
                })}
                {s.total_ms != null &&
                  (() => {
                    const totalP = s.steps_timing.reduce(
                      (a, t) => a + (t.prompt_tokens ?? 0),
                      0,
                    );
                    const totalC = s.steps_timing.reduce(
                      (a, t) => a + (t.completion_tokens ?? 0),
                      0,
                    );
                    return (
                      <div
                        style={{
                          marginTop: 4,
                          fontSize: 12,
                          color: "#666",
                          fontFamily: "ui-monospace, monospace",
                        }}
                      >
                        total: {fmtMs(s.total_ms)}
                        {totalP > 0 && (
                          <span style={{ marginLeft: 8 }}>
                            {totalP.toLocaleString()}p +{" "}
                            {totalC.toLocaleString()}c
                          </span>
                        )}
                      </div>
                    );
                  })()}
              </div>
            </DetailSection>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={handleCopy}
              style={{ ...reviewBtnStyle, borderColor: "#666", color: "#aaa" }}
            >
              {copied ? "✓ Copied!" : "Copy"}
            </button>
            {onMarkReviewed && (
              <button onClick={onMarkReviewed} style={reviewBtnStyle}>
                ✓ Mark as reviewed
              </button>
            )}
            {onViewSession && (
              <button
                onClick={onViewSession}
                style={{
                  ...reviewBtnStyle,
                  borderColor: "#7ec8e3",
                  color: "#7ec8e3",
                }}
              >
                View session ↓
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function DetailSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: "#777",
          textTransform: "uppercase",
          letterSpacing: 1,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

const preStyle: React.CSSProperties = {
  margin: 0,
  padding: "6px 8px",
  background: "#222",
  borderRadius: 5,
  fontSize: 12,
  lineHeight: 1.45,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  color: "#ccc",
  fontFamily: "ui-monospace, monospace",
};

const reviewBtnStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #4caf50",
  borderRadius: 6,
  color: "#4caf50",
  padding: "4px 12px",
  fontSize: 12,
  cursor: "pointer",
};

function paginationBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    background: "transparent",
    border: "1px solid " + (disabled ? "#333" : "#444"),
    borderRadius: 6,
    color: disabled ? "#444" : "#aaa",
    padding: "4px 12px",
    fontSize: 12,
    cursor: disabled ? "not-allowed" : "pointer",
  };
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: "#1a1a1a",
        border: "1px solid #333",
        borderRadius: 8,
        padding: "10px 14px",
        minWidth: 160,
        flex: "1 1 160px",
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: "#888",
          textTransform: "uppercase",
          letterSpacing: 1,
          marginBottom: 8,
        }}
      >
        {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {children}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  ok,
  title,
}: {
  label: string;
  value: string;
  ok?: boolean;
  title?: string;
}) {
  const valueColor = ok === true ? "#4caf50" : ok === false ? "#f66" : "#ddd";
  return (
    <div
      title={title}
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 8,
        fontSize: 12,
      }}
    >
      <span style={{ color: "#777" }}>{label}</span>
      <span style={{ color: valueColor, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </span>
    </div>
  );
}

function LegendItem({
  color,
  label,
  circle,
  active = true,
  onClick,
}: {
  color: string;
  label: string;
  circle?: boolean;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <span
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        cursor: onClick ? "pointer" : undefined,
        opacity: active ? 1 : 0.35,
        userSelect: "none",
      }}
    >
      <span
        style={{
          width: 12,
          height: 12,
          background: color,
          borderRadius: circle ? "50%" : 2,
          display: "inline-block",
          flexShrink: 0,
        }}
      />
      {label}
    </span>
  );
}
