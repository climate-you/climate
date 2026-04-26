"use client";

import React, { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import styles from "./ChatDrawer.module.css";
import {
  CHAT_FOLLOWUP_CHIP_CAP,
  CHAT_MODEL_OVERRIDE_KEY,
  CHAT_QUESTIONS_API_PATH,
  CHAT_ROOT_CHIP_CAP,
} from "@/lib/explorer/constants";
import ChatChart, { type ChatChartPayload } from "./ChatChart";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MapContext = { lat: number; lon: number; label: string; countryCode?: string | null } | null;
type ModelOverride = "groq_8b" | "local" | "groq_70b" | "groq_scout" | null;
type ConversationTurn = { role: "user" | "assistant"; text: string };

const MAX_HISTORY_TURNS = 3;

type ChatLocation = { label: string; rank?: number; lat: number; lon: number; alt_names?: string };
type ToolCallInfo = { name: string; args: Record<string, unknown> };

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  messageId?: string;
  notice?: string;
  debugInfo?: string;
  feedback?: "good" | "bad" | null;
  error?: boolean;
  loading?: boolean;
  aborted?: boolean;
  exhausted?: boolean;
  locations?: ChatLocation[];
  charts?: ChatChartPayload[];
  toolCalls?: ToolCallInfo[];
};

type QuestionScope = "global" | "country" | "city" | "local";
type LocationFilter = "any" | "coastal" | "tropical_coastal";

interface QuestionMeta {
  id: string;
  question: string;
  scope: QuestionScope;
  datasets: string[];
  follow_up_ids: string[];
  requires_location: boolean;
  location_filter: LocationFilter;
}

interface QuestionTree {
  version: string;
  root_ids: string[];
  questions: Record<string, QuestionMeta>;
}

type ChatDrawerProps = {
  apiBase: string;
  mapContext: MapContext;
  unit?: "C" | "F";
  devMode?: boolean;
  debugMode?: boolean;
  onLocations?: (locs: ChatLocation[] | null) => void;
  onPickLocation?: (lat: number, lon: number) => void;
  onFlyToBbox?: (bbox: [number, number, number, number]) => void;
  embedded?: boolean;
  embeddedVisible?: boolean;
  onClose?: () => void;
  onSwitchToGraph?: () => void;
};

// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

async function streamChatRequest(
  apiBase: string,
  payload: object,
  onEvent: (event: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${apiBase}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        try {
          onEvent(JSON.parse(line.slice(6)) as Record<string, unknown>);
        } catch {
          // ignore malformed SSE lines
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const cryptoAvailable =
  typeof crypto !== "undefined" && typeof crypto.randomUUID === "function";

function linkifyCities(text: string, locs: ChatLocation[]): string {
  let result = text;
  for (const loc of locs) {
    const city = loc.label.split(",")[0].trim();
    const variants = [city];
    if (loc.alt_names) {
      for (const alt of loc.alt_names.split(",")) {
        const t = alt.trim();
        if (t && t.toLowerCase() !== city.toLowerCase()) variants.push(t);
      }
    }
    for (const variant of variants) {
      const escaped = variant.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      result = result.replace(
        new RegExp(`(?<!\\[)\\b${escaped}\\b`, "gi"),
        `[${city}](#loc:${loc.lat}:${loc.lon})`,
      );
    }
  }
  return result;
}

function addSummaryLineLink(text: string): string {
  const match = text.match(/^([^\n]+):([ \t]*\n(?:[ \t]*\n)*[ \t]*)(?=\d+\.|- )/m);
  if (!match || match.index === undefined) return text;
  const lineContent = match[1];
  const anchorMatch = lineContent.match(
    /^(?:(?:the|a|an)\s+)?(.+?)(?:\s+(?:are|is|were|was|have been|includes?|contains?))?$/i,
  );
  const anchor = anchorMatch ? anchorMatch[1].trim() : lineContent.trim();
  const anchorIdx = lineContent.indexOf(anchor);
  const before = lineContent.slice(0, anchorIdx);
  const after = lineContent.slice(anchorIdx + anchor.length);
  const newLine = `${before}[${anchor}](#locs)${after}:${match[2]}`;
  return (
    text.slice(0, match.index) +
    newLine +
    text.slice(match.index + match[0].length)
  );
}

function generateUUID(): string {
  if (cryptoAvailable) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function describeToolCall(name: string, args: Record<string, unknown>): string {
  const metricLabel = (id: string) =>
    id.replace(/_[cf]$/, "").replace(/_/g, " ");
  switch (name) {
    case "get_metric_series": {
      const location = args.location as string | undefined;
      const metricId = args.metric_id as string | undefined;
      const metric = metricId ? metricLabel(metricId) : "data";
      return location ? `Querying ${metric} for ${location}` : `Querying ${metric}`;
    }
    case "find_extreme_location": {
      const extreme = args.extreme as string | undefined;
      const metricId = args.metric_id as string | undefined;
      const metric = metricId ? metricLabel(metricId) : "climate";
      const adj = extreme === "max" ? "highest" : extreme === "min" ? "lowest" : "extreme";
      return `Finding ${adj} ${metric} locations`;
    }
    case "find_similar_locations": {
      const ref = args.reference_location as string | undefined;
      return ref ? `Finding locations similar to ${ref}` : "Finding similar locations";
    }
    default:
      return name.replace(/_/g, " ");
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatDrawer({
  apiBase,
  mapContext,
  unit = "C",
  devMode = false,
  debugMode = false,
  onLocations,
  onPickLocation,
  onFlyToBbox,
  embedded = false,
  embeddedVisible = true,
  onClose,
  onSwitchToGraph,
}: ChatDrawerProps) {
  const [open, setOpen] = useState(false);
  const [conversationId, setConversationId] = useState(() => generateUUID());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationHistory, setConversationHistory] = useState<ConversationTurn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationExhausted, setConversationExhausted] = useState(false);
  const [modelOverride, setModelOverride] = useState<ModelOverride>(null);
  const [questionTree, setQuestionTree] = useState<QuestionTree | null>(null);
  const [chatUnavailable, setChatUnavailable] = useState(false);
  const [currentFollowUpIds, setCurrentFollowUpIds] = useState<string[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const lastAnsweredQuestionIdRef = useRef<string | null>(null);

  // Fetch question tree once on mount
  useEffect(() => {
    fetch(`${apiBase}${CHAT_QUESTIONS_API_PATH}`)
      .then((r) => {
        if (!r.ok) { setChatUnavailable(true); return undefined; }
        return r.json() as Promise<QuestionTree>;
      })
      .then((data) => { if (data) setQuestionTree(data); })
      .catch(() => setChatUnavailable(true));
  }, [apiBase]);

  // Read persisted preferences from localStorage (client-side only)
  useEffect(() => {
    const stored = localStorage.getItem(CHAT_MODEL_OVERRIDE_KEY);
    if (!devMode) {
      localStorage.removeItem(CHAT_MODEL_OVERRIDE_KEY);
    } else if (
      stored === "groq_8b" ||
      stored === "local" ||
      stored === "groq_70b" ||
      stored === "groq_scout"
    ) {
      setModelOverride(stored);
    }
  }, [devMode]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (embedded) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!embedded && open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [embedded, open]);

  useEffect(() => {
    if (embedded || !open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [embedded, open]);

  function persistModelOverride(value: ModelOverride) {
    setModelOverride(value);
    if (value) {
      localStorage.setItem(CHAT_MODEL_OVERRIDE_KEY, value);
    } else {
      localStorage.removeItem(CHAT_MODEL_OVERRIDE_KEY);
    }
  }

  function clearSession() {
    setMessages([]);
    setConversationHistory([]);
    setConversationExhausted(false);
    setConversationId(generateUUID());
    setCurrentFollowUpIds([]);
    lastAnsweredQuestionIdRef.current = null;
    onLocations?.(null);
  }

  function abortMessage() {
    abortControllerRef.current?.abort();
  }

  async function sendMessage(question: string, questionId?: string | null) {
    if (!question.trim() || loading) return;
    if (!cryptoAvailable && process.env.NODE_ENV !== "development") {
      setMessages((prev) => [
        ...prev,
        { role: "user", text: question },
        {
          role: "assistant",
          text: "This feature requires a secure connection (HTTPS).",
          error: true,
        },
      ]);
      return;
    }
    const parentQuestionId = lastAnsweredQuestionIdRef.current;
    setInput("");
    setLoading(true);
    setCurrentFollowUpIds([]);
    onLocations?.(null);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const messageId = generateUUID();
    setMessages((prev) => [
      ...prev,
      { role: "user", text: question },
      { role: "assistant", text: "", messageId, loading: true },
    ]);

    let pendingNotice: string | undefined;
    let answered = false;
    let errorReceived = false;
    let finalAnswerText = "";

    try {
      await streamChatRequest(
        apiBase,
        {
          question,
          history: conversationHistory.length > 0 ? conversationHistory : undefined,
          map_context: mapContext,
          session_id: conversationId,
          message_id: messageId,
          model_override: modelOverride ?? undefined,
          temperature_unit: unit,
          question_id: questionId ?? null,
          parent_question_id: parentQuestionId,
          question_tree_version: questionTree?.version ?? undefined,
        },
        (event) => {
          const type = event.type as string;
          if (type === "chunk") {
            finalAnswerText += event.text as string;
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? { ...m, text: finalAnswerText, loading: false }
                  : m,
              ),
            );
          } else if (type === "tool_call") {
            const tc: ToolCallInfo = {
              name: event.name as string,
              args: (event.args ?? {}) as Record<string, unknown>,
            };
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? { ...m, toolCalls: [...(m.toolCalls ?? []), tc] }
                  : m,
              ),
            );
          } else if (type === "reset") {
            finalAnswerText = "";
            pendingNotice = undefined;
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? { ...m, text: "", toolCalls: [], loading: true }
                  : m,
              ),
            );
          } else if (type === "notice") {
            pendingNotice = event.text as string;
          } else if (type === "answer") {
            answered = true;
            finalAnswerText = event.text as string;
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? { ...m, text: finalAnswerText, notice: pendingNotice, loading: false }
                  : m,
              ),
            );
          } else if (type === "error") {
            errorReceived = true;
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? { ...m, text: event.message as string, loading: false, error: true }
                  : m,
              ),
            );
          } else if (type === "done") {
            const charts = event.charts as ChatChartPayload[] | undefined;
            if (charts && charts.length > 0) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.messageId === messageId ? { ...m, charts } : m,
                ),
              );
            }
            const locs = (
              event.locations as
                | Array<{ label: string; lat: number; lon: number; alt_names?: string }>
                | undefined
            )?.map((loc) => ({ ...loc, label: loc.label.replace(/\*/g, "") }));
            const answerLower = finalAnswerText.toLowerCase();
            const rankMap = new Map<string, number>();
            const orderedListRegex = /^(\d+)\.\s+(.+?)(?=[,—–]|$)/gm;
            let rankMatch;
            while ((rankMatch = orderedListRegex.exec(finalAnswerText)) !== null) {
              rankMap.set(
                rankMatch[2].replace(/\*/g, "").trim().toLowerCase(),
                parseInt(rankMatch[1], 10),
              );
            }
            const filteredLocs = locs
              ?.filter((loc) => {
                const cityName = loc.label.split(",")[0].trim().toLowerCase();
                if (answerLower.includes(cityName)) return true;
                if (loc.alt_names) {
                  return loc.alt_names
                    .split(",")
                    .some((a) => answerLower.includes(a.trim().toLowerCase()));
                }
                return false;
              })
              .map((loc) => {
                const cityName = loc.label.split(",")[0].trim().toLowerCase();
                let rank = rankMap.get(cityName);
                if (rank === undefined && loc.alt_names) {
                  for (const alt of loc.alt_names.split(",")) {
                    rank = rankMap.get(alt.trim().toLowerCase());
                    if (rank !== undefined) break;
                  }
                }
                return rank !== undefined ? { ...loc, rank } : loc;
              });
            const locsToShow =
              filteredLocs && filteredLocs.length > 0 ? filteredLocs : locs;
            if (locsToShow && locsToShow.length > 0) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.messageId === messageId ? { ...m, locations: locsToShow } : m,
                ),
              );
            }
            if (locsToShow && locsToShow.length >= 1) {
              onLocations?.(locsToShow);
            } else if (event.fly_to_bbox) {
              const raw = event.fly_to_bbox as number[];
              if (raw.length === 4) {
                onFlyToBbox?.(raw as [number, number, number, number]);
              }
            }
            const tier = event.tier as string | null;
            const isExhausted = tier === null && !event.error;
            if (isExhausted) {
              setConversationExhausted(true);
              setMessages((prev) =>
                prev.map((m) =>
                  m.messageId === messageId ? { ...m, exhausted: true } : m,
                ),
              );
            }
            if (debugMode) {
              const model = event.model as string | null;
              const totalMs = event.total_ms as number | null;
              const rejected = (event.rejected_tiers as string[] | null) ?? [];
              const parts: string[] = [];
              if (rejected.length > 0) parts.push(`~~${rejected.join(", ")}~~ →`);
              if (tier) parts.push(tier);
              if (model) parts.push(`(${model})`);
              if (totalMs != null)
                parts.push(
                  `· ${totalMs < 1000 ? `${totalMs}ms` : `${(totalMs / 1000).toFixed(1)}s`}`,
                );
              const debugInfo = parts.join(" ");
              setMessages((prev) =>
                prev.map((m) =>
                  m.messageId === messageId ? { ...m, debugInfo } : m,
                ),
              );
            }
            // Set follow-up chips: use canned follow_up_ids if present, else root pool
            const followUpIds = (event.follow_up_ids as string[] | undefined) ?? [];
            setCurrentFollowUpIds(
              followUpIds.length > 0
                ? followUpIds
                : questionTree?.root_ids ?? [],
            );
            lastAnsweredQuestionIdRef.current = questionId ?? null;
          }
        },
        controller.signal,
      );

      if (!answered && !errorReceived) {
        setMessages((prev) =>
          prev.map((m) =>
            m.messageId === messageId
              ? { ...m, text: "No response received.", loading: false, error: true }
              : m,
          ),
        );
      } else if (finalAnswerText) {
        setConversationHistory((prev) => {
          const updated: ConversationTurn[] = [
            ...prev,
            { role: "user", text: question },
            { role: "assistant", text: finalAnswerText },
          ];
          return updated.slice(-(MAX_HISTORY_TURNS * 2));
        });
      }
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.messageId === messageId
              ? { ...m, text: "", loading: false, aborted: true }
              : m,
          ),
        );
      } else {
        setMessages((prev) =>
          prev.map((m) =>
            m.messageId === messageId
              ? {
                  ...m,
                  text: "Failed to connect to the assistant. Please try again.",
                  loading: false,
                  error: true,
                }
              : m,
          ),
        );
      }
    } finally {
      abortControllerRef.current = null;
      setLoading(false);
    }
  }

  async function submitFeedback(messageId: string, feedback: "good" | "bad" | null) {
    const current = messages.find((m) => m.messageId === messageId)?.feedback;
    const next = current === feedback ? null : feedback;
    setMessages((prev) =>
      prev.map((m) =>
        m.messageId === messageId ? { ...m, feedback: next } : m,
      ),
    );
    try {
      await fetch(`${apiBase}/api/chat/${messageId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback: next }),
      });
    } catch {
      // Feedback is best-effort
    }
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  }

  // ---------------------------------------------------------------------------
  // Question tree — chip helpers
  // ---------------------------------------------------------------------------

  const cityName = mapContext?.label?.split(",")[0]?.trim() ?? null;
  const countryName = mapContext?.countryCode
    ? (mapContext.label.split(",").pop()?.trim() ?? null)
    : null;

  function resolveChipText(node: QuestionMeta): string {
    if (!node.requires_location) return node.question;
    return node.question.replace("{location}", cityName ?? "");
  }

  function passesLocationFilter(node: QuestionMeta): boolean {
    if (node.requires_location && !mapContext) return false;
    if (node.location_filter === "tropical_coastal") {
      if (!mapContext || Math.abs(mapContext.lat) > 35) return false;
    }
    if (node.location_filter === "coastal" && !mapContext) return false;
    return true;
  }

  // Root chips: filtered + capped, grouped by scope
  const rootNodes = React.useMemo((): QuestionMeta[] => {
    if (!questionTree) return [];
    return questionTree.root_ids
      .map((id) => questionTree.questions[id])
      .filter((node): node is QuestionMeta => !!node && passesLocationFilter(node))
      .slice(0, CHAT_ROOT_CHIP_CAP);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionTree, conversationId, mapContext?.label, mapContext?.lat]);

  const groupedQuestions = React.useMemo(() => {
    const scopeOrder: QuestionScope[] = ["local", "global", "country", "city"];
    const map: Partial<Record<QuestionScope, QuestionMeta[]>> = {};
    for (const node of rootNodes) {
      if (!map[node.scope]) map[node.scope] = [];
      map[node.scope]!.push(node);
    }
    return scopeOrder
      .filter((scope) => map[scope])
      .map((scope) => ({ scope, questions: map[scope]! }));
  }, [rootNodes]);

  // Follow-up chips: filtered + capped
  const visibleFollowUpNodes = React.useMemo((): QuestionMeta[] => {
    if (!questionTree || currentFollowUpIds.length === 0) return [];
    return currentFollowUpIds
      .map((id) => questionTree.questions[id])
      .filter((node): node is QuestionMeta => !!node && passesLocationFilter(node))
      .slice(0, CHAT_FOLLOWUP_CHIP_CAP);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionTree, currentFollowUpIds, mapContext?.label, mapContext?.lat]);

  // ---------------------------------------------------------------------------
  // Dataset icon
  // ---------------------------------------------------------------------------

  function DatasetIcon({ dataset }: { dataset: string }) {
    if (dataset === "precipitation") {
      return (
        <svg className={styles.chipDatasetIcon} viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2C8.5 7.5 5 12 5 15.5a7 7 0 0 0 14 0C19 12 15.5 7.5 12 2z" />
        </svg>
      );
    }
    if (dataset === "sea_temperature" || dataset === "coral") {
      return (
        <svg className={styles.chipDatasetIcon} viewBox="0 0 24 24" aria-hidden="true">
          <path d="M2 10c2-4 4-4 6 0s4 4 6 0 4-4 6 0" />
          <path d="M2 16c2-4 4-4 6 0s4 4 6 0 4-4 6 0" />
        </svg>
      );
    }
    return (
      <svg className={styles.chipDatasetIcon} viewBox="0 0 24 24" aria-hidden="true">
        <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z" />
      </svg>
    );
  }

  // ---------------------------------------------------------------------------
  // Shared header controls
  // ---------------------------------------------------------------------------

  const headerControls = (
    <>
      <div className={styles.drawerTitle}>
        <svg viewBox="0 0 24 24" aria-hidden="true" className={styles.drawerTitleIcon}>
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        Research Terminal
      </div>

      {devMode && (
        <select
          className={styles.modelSelect}
          aria-label="Model override"
          value={modelOverride ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            persistModelOverride((v || null) as ModelOverride);
          }}
        >
          <option value="">auto</option>
          <option value="groq_8b">groq · llama 8b</option>
          <option value="local">local</option>
          <option disabled>──────────</option>
          <option value="groq_70b">groq · llama 70b</option>
          <option value="groq_scout">groq · llama 4 scout</option>
        </select>
      )}

      <button
        type="button"
        className={styles.drawerClose}
        aria-label="New conversation"
        title="New conversation"
        onClick={clearSession}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
        </svg>
      </button>
    </>
  );

  // ---------------------------------------------------------------------------
  // Messages area
  // ---------------------------------------------------------------------------

  const isEmpty = messages.length === 0;

  const messagesArea = (
    <div className={styles.messages}>
      {isEmpty && (
        <div className={styles.emptyState}>
          {chatUnavailable ? (
            <p className={styles.emptyStateError}>Research terminal not running.</p>
          ) : (
            <p className={styles.emptyStateHint}>
              Ask a question about climate data, or try one of these:
            </p>
          )}
          {!chatUnavailable && groupedQuestions.map(({ scope, questions }) => (
            <div key={scope} className={styles.chipGroup}>
              <div className={styles.chipGroupHeader}>
                {scope === "local" && cityName
                  ? countryName && countryName !== cityName
                    ? `${cityName}, ${countryName}`
                    : cityName
                  : scope.charAt(0).toUpperCase() + scope.slice(1)}
              </div>
              <div className={styles.chips}>
                {questions.map((node) => {
                  const text = resolveChipText(node);
                  return (
                    <button
                      key={node.id}
                      type="button"
                      className={styles.chip}
                      onClick={() => void sendMessage(text, node.id)}
                    >
                      <DatasetIcon dataset={node.datasets[0] ?? "temperature"} />
                      {text}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {messages.map((msg, i) => (
        <div
          key={i}
          className={`${styles.message} ${msg.role === "user" ? styles.messageUser : styles.messageAssistant}`}
        >
          {msg.debugInfo && (
            <div className={styles.debugBar}>{msg.debugInfo}</div>
          )}
          {msg.notice && (
            <div className={styles.noticeBar}>{msg.notice}</div>
          )}
          {msg.toolCalls && msg.toolCalls.length > 0 && (
            <div className={styles.toolCalls}>
              {msg.toolCalls.map((tc, j) => (
                <div key={j} className={styles.toolCallItem}>
                  <em>{describeToolCall(tc.name, tc.args)}</em>
                </div>
              ))}
            </div>
          )}
          <div
            className={`${styles.messageBubble} ${msg.error ? styles.messageBubbleError : ""}`}
          >
            {msg.loading ? (
              <span className={styles.loadingDots}>
                <span />
                <span />
                <span />
              </span>
            ) : msg.aborted ? (
              <em className={styles.abortedText}>Message was aborted.</em>
            ) : msg.exhausted ? (
              <>
                The AI assistant&apos;s daily budget is exhausted. This
                project is provided for free and is self-funded. If you
                find it useful, please consider supporting it at{" "}
                <a
                  href="https://ko-fi.com/climateyou"
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.exhaustedLink}
                >
                  ko-fi.com/climateyou
                </a>
                .
              </>
            ) : (
              <div className={styles.markdown}>
                <Markdown
                  components={
                    msg.locations && msg.locations.length > 0
                      ? {
                          a({ href, children }) {
                            if (href?.startsWith("#loc:")) {
                              const [, lat, lon] = href.split(":");
                              return (
                                <a
                                  href="#"
                                  className={styles.locationLink}
                                  onClick={(e) => {
                                    e.preventDefault();
                                    onPickLocation?.(parseFloat(lat), parseFloat(lon));
                                  }}
                                >
                                  {children}
                                </a>
                              );
                            }
                            if (href === "#locs") {
                              return (
                                <a
                                  href="#"
                                  className={styles.locationLink}
                                  onClick={(e) => {
                                    e.preventDefault();
                                    onLocations?.(msg.locations!);
                                  }}
                                >
                                  {children}
                                </a>
                              );
                            }
                            return <a href={href}>{children}</a>;
                          },
                        }
                      : undefined
                  }
                >
                  {msg.locations && msg.locations.length > 0
                    ? addSummaryLineLink(linkifyCities(msg.text, msg.locations))
                    : msg.text}
                </Markdown>
              </div>
            )}
          </div>

          {msg.charts && msg.charts.length > 0 && !msg.loading && (
            <div className={styles.charts}>
              {msg.charts.map((chart, ci) => (
                <ChatChart key={ci} chart={chart} temperatureUnit={unit} />
              ))}
            </div>
          )}

          {msg.role === "assistant" &&
            msg.messageId &&
            !msg.loading &&
            !msg.error &&
            !msg.exhausted && (
              <div className={styles.feedback}>
                <button
                  type="button"
                  className={`${styles.feedbackBtn} ${msg.feedback === "good" ? styles.feedbackBtnActive : ""}`}
                  aria-label="Good answer"
                  aria-pressed={msg.feedback === "good"}
                  onClick={() => void submitFeedback(msg.messageId!, "good")}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>
                </button>
                <button
                  type="button"
                  className={`${styles.feedbackBtn} ${msg.feedback === "bad" ? styles.feedbackBtnActive : ""}`}
                  aria-label="Bad answer"
                  aria-pressed={msg.feedback === "bad"}
                  onClick={() => void submitFeedback(msg.messageId!, "bad")}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/></svg>
                </button>
              </div>
            )}
        </div>
      ))}

      {/* Follow-up chips — shown after the last answer while not loading */}
      {!isEmpty && !loading && visibleFollowUpNodes.length > 0 && (
        <div className={styles.followUpRow}>
          <div className={styles.followUpLabel}>Continue exploring</div>
          <div className={styles.chips}>
            {visibleFollowUpNodes.map((node) => {
              const text = resolveChipText(node);
              return (
                <button
                  key={node.id}
                  type="button"
                  className={styles.chip}
                  onClick={() => void sendMessage(text, node.id)}
                >
                  <DatasetIcon dataset={node.datasets[0] ?? "temperature"} />
                  {text}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );

  // ---------------------------------------------------------------------------
  // Input row
  // ---------------------------------------------------------------------------

  const makeInputRow = (extraClass?: string) => (
    <div className={`${styles.inputRow}${extraClass ? ` ${extraClass}` : ""}`}>
      <textarea
        ref={inputRef}
        className={styles.input}
        rows={1}
        placeholder={
          chatUnavailable ? "Research terminal not running." : conversationExhausted ? "Please try again later." : "Ask about climate data…"
        }
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleInputKeyDown}
        disabled={loading || conversationExhausted || chatUnavailable}
        aria-label="Chat input"
      />
      {loading ? (
        <button
          type="button"
          className={styles.stopBtn}
          aria-label="Stop"
          onClick={abortMessage}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" />
          </svg>
        </button>
      ) : (
        <button
          type="button"
          className={styles.sendBtn}
          aria-label="Send"
          disabled={!input.trim() || conversationExhausted || chatUnavailable}
          onClick={() => void sendMessage(input)}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" />
          </svg>
        </button>
      )}
    </div>
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (embedded) {
    return (
      <div className={styles.embeddedContainer} style={embeddedVisible ? undefined : { display: "none" }}>
        <div className={styles.embeddedHeader}>
          {headerControls}
          {onClose && (
            <button
              type="button"
              className={styles.drawerClose}
              aria-label="Close panel"
              onClick={onClose}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 6L18 18M18 6L6 18" />
              </svg>
            </button>
          )}
        </div>
        {messagesArea}
        {makeInputRow(styles.embeddedInputRow)}
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        className={`${styles.chatButton} ${open ? styles.chatButtonOpen : ""}`}
        aria-label="Open climate data assistant"
        onClick={() => setOpen((v) => !v)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" className={styles.chatButtonIcon}>
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </button>

      {open && (
        <aside
          className={styles.drawer}
          role="dialog"
          aria-label="Climate data assistant"
          aria-modal="false"
        >
          <div className={styles.drawerHeader}>
            {headerControls}
            <button
              type="button"
              className={styles.drawerClose}
              aria-label="Close chat"
              onClick={() => setOpen(false)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 6L18 18M18 6L6 18" />
              </svg>
            </button>
          </div>
          {messagesArea}
          {makeInputRow()}
        </aside>
      )}
    </>
  );
}
