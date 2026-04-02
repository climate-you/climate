"use client";

import React, { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import styles from "./ChatDrawer.module.css";
import {
  CHAT_EXAMPLE_QUESTIONS_GENERIC,
  CHAT_MODEL_OVERRIDE_KEY,
  CHAT_OPT_OUT_KEY,
  CHAT_PRIVACY_NOTICE,
} from "@/lib/explorer/constants";
import ChatChart, { type ChatChartPayload } from "./ChatChart";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MapContext = { lat: number; lon: number; label: string } | null;
type ModelOverride = "groq_8b" | "local" | "groq_70b" | "groq_scout" | null;
type ConversationTurn = { role: "user" | "assistant"; text: string };

const MAX_HISTORY_TURNS = 3; // keep last N user+assistant pairs

type ChatLocation = { label: string; rank?: number; lat: number; lon: number };

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  messageId?: string;
  notice?: string; // degraded-model disclaimer
  debugInfo?: string; // shown only in debug mode
  feedback?: "good" | "bad" | null;
  error?: boolean;
  loading?: boolean;
  aborted?: boolean;
  exhausted?: boolean; // daily budget exhausted — locks the input
  locations?: ChatLocation[]; // locations mentioned in this answer
  charts?: ChatChartPayload[]; // optional charts from get_metric_series calls
};

type ChatDrawerProps = {
  apiBase: string;
  mapContext: MapContext;
  unit?: "C" | "F";
  devMode?: boolean; // shows the model toggle when true
  debugMode?: boolean; // shows per-reply model/tier/timing info
  onLocations?: (locs: ChatLocation[] | null) => void;
  onPickLocation?: (lat: number, lon: number) => void;
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
    const escaped = city.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    result = result.replace(
      new RegExp(`(?<!\\[)\\b${escaped}\\b`, "gi"),
      `[${city}](#loc:${loc.lat}:${loc.lon})`,
    );
  }
  return result;
}

function generateUUID(): string {
  if (cryptoAvailable) {
    return crypto.randomUUID();
  }
  // Dev-only fallback for non-secure contexts (e.g. mobile via local IP)
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
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
}: ChatDrawerProps) {
  const [open, setOpen] = useState(false);
  const [conversationId] = useState(() => generateUUID());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationHistory, setConversationHistory] = useState<
    ConversationTurn[]
  >([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationExhausted, setConversationExhausted] = useState(false);
  const [optOut, setOptOut] = useState(false);
  const [modelOverride, setModelOverride] = useState<ModelOverride>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Read persisted preferences from localStorage (client-side only)
  useEffect(() => {
    setOptOut(localStorage.getItem(CHAT_OPT_OUT_KEY) === "1");
    const stored = localStorage.getItem(CHAT_MODEL_OVERRIDE_KEY);
    if (!devMode) {
      // Clear any override that may have been set during a debug session
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

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when drawer opens
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Keyboard: close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  function persistOptOut(value: boolean) {
    setOptOut(value);
    if (value) {
      localStorage.setItem(CHAT_OPT_OUT_KEY, "1");
    } else {
      localStorage.removeItem(CHAT_OPT_OUT_KEY);
    }
  }

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
  }

  function abortMessage() {
    abortControllerRef.current?.abort();
  }

  async function sendMessage(question: string) {
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
    setInput("");
    setLoading(true);
    onLocations?.(null); // clear any previous chat markers

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
    let finalAnswerText = "";

    try {
      await streamChatRequest(
        apiBase,
        {
          question,
          history:
            conversationHistory.length > 0 ? conversationHistory : undefined,
          map_context: mapContext,
          opt_out: optOut,
          session_id: conversationId,
          message_id: messageId,
          model_override: modelOverride ?? undefined,
          temperature_unit: unit,
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
          } else if (type === "notice") {
            pendingNotice = event.text as string;
          } else if (type === "answer") {
            answered = true;
            finalAnswerText = event.text as string;
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? {
                      ...m,
                      text: finalAnswerText,
                      notice: pendingNotice,
                      loading: false,
                    }
                  : m,
              ),
            );
          } else if (type === "error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.messageId === messageId
                  ? {
                      ...m,
                      text: event.message as string,
                      loading: false,
                      error: true,
                    }
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
                | Array<{ label: string; lat: number; lon: number }>
                | undefined
            )?.map((loc) => ({ ...loc, label: loc.label.replace(/\*/g, "") }));
            const answerLower = finalAnswerText.toLowerCase();
            // Extract rank from ordered list items (e.g. "1. Khartoum, Sudan — 29.6°C")
            const rankMap = new Map<string, number>();
            const orderedListRegex = /^(\d+)\.\s+(.+?)(?=[,\u2014\u2013]|$)/gm;
            let rankMatch;
            while ((rankMatch = orderedListRegex.exec(finalAnswerText)) !== null) {
              rankMap.set(rankMatch[2].replace(/\*/g, "").trim().toLowerCase(), parseInt(rankMatch[1], 10));
            }
            const filteredLocs = locs
              ?.filter((loc) => {
                const cityName = loc.label.split(",")[0].trim().toLowerCase();
                return answerLower.includes(cityName);
              })
              .map((loc) => {
                const cityName = loc.label.split(",")[0].trim().toLowerCase();
                const rank = rankMap.get(cityName);
                return rank !== undefined ? { ...loc, rank } : loc;
              });
            const locsToShow =
              filteredLocs && filteredLocs.length > 0 ? filteredLocs : locs;
            if (locsToShow && locsToShow.length > 0) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.messageId === messageId
                    ? { ...m, locations: locsToShow }
                    : m,
                ),
              );
            }
            if (locsToShow && locsToShow.length >= 1) {
              onLocations?.(locsToShow);
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
              if (rejected.length > 0)
                parts.push(`~~${rejected.join(", ")}~~ →`);
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
          }
        },
        controller.signal,
      );

      if (!answered) {
        // Stream ended without an answer event
        setMessages((prev) =>
          prev.map((m) =>
            m.messageId === messageId
              ? {
                  ...m,
                  text: "No response received.",
                  loading: false,
                  error: true,
                }
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

  async function submitFeedback(
    messageId: string,
    feedback: "good" | "bad" | null,
  ) {
    // Toggle: clicking the active state clears feedback
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
      // Feedback is best-effort; don't surface errors
    }
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  }

  const exampleQuestions = React.useMemo(() => {
    const shuffled = [...CHAT_EXAMPLE_QUESTIONS_GENERIC].sort(
      () => Math.random() - 0.5,
    );
    if (mapContext?.label) {
      const cityName = mapContext.label.split(",")[0];
      return [
        `What was the hottest year on record in ${cityName}?`,
        `How have temperatures changed in ${cityName} since 2000?`,
        `What was the annual mean temperature in ${cityName} in 2020?`,
        ...shuffled.slice(0, 2),
      ];
    }
    return shuffled.slice(0, 3);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, mapContext?.label]);

  const isEmpty = messages.length === 0;

  return (
    <>
      {/* Floating chat button */}
      <button
        type="button"
        className={`${styles.chatButton} ${open ? styles.chatButtonOpen : ""}`}
        aria-label={open ? "Close chat" : "Open climate data assistant"}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <svg
            viewBox="0 0 24 24"
            aria-hidden="true"
            className={styles.chatButtonIcon}
          >
            <path d="M6 6L18 18M18 6L6 18" />
          </svg>
        ) : (
          <svg
            viewBox="0 0 24 24"
            aria-hidden="true"
            className={styles.chatButtonIcon}
          >
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        )}
      </button>

      {/* Drawer */}
      {open && (
        <aside
          className={styles.drawer}
          role="dialog"
          aria-label="Climate data assistant"
          aria-modal="false"
        >
          {/* Header */}
          <div className={styles.drawerHeader}>
            <div className={styles.drawerTitle}>
              <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
                className={styles.drawerTitleIcon}
              >
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
              Research Terminal
            </div>

            {/* Dev model selector */}
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

            {!isEmpty && (
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
            )}

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

          {/* Messages */}
          <div className={styles.messages}>
            {isEmpty && (
              <div className={styles.emptyState}>
                <p className={styles.emptyStateHint}>
                  Ask a question about climate data, or try one of these:
                </p>
                <div className={styles.chips}>
                  {exampleQuestions.map((q) => (
                    <button
                      key={q}
                      type="button"
                      className={styles.chip}
                      onClick={() => void sendMessage(q)}
                    >
                      {q}
                    </button>
                  ))}
                </div>
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
                                          onPickLocation?.(
                                            parseFloat(lat),
                                            parseFloat(lon),
                                          );
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
                          ? linkifyCities(msg.text, msg.locations)
                          : msg.text}
                      </Markdown>
                    </div>
                  )}
                </div>

                {/* Charts from get_metric_series tool calls */}
                {msg.charts && msg.charts.length > 0 && !msg.loading && (
                  <div className={styles.charts}>
                    {msg.charts.map((chart, i) => (
                      <ChatChart key={i} chart={chart} temperatureUnit={unit} />
                    ))}
                  </div>
                )}

                {/* Feedback buttons for assistant messages */}
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
                        onClick={() =>
                          void submitFeedback(msg.messageId!, "good")
                        }
                      >
                        👍
                      </button>
                      <button
                        type="button"
                        className={`${styles.feedbackBtn} ${msg.feedback === "bad" ? styles.feedbackBtnActive : ""}`}
                        aria-label="Bad answer"
                        aria-pressed={msg.feedback === "bad"}
                        onClick={() =>
                          void submitFeedback(msg.messageId!, "bad")
                        }
                      >
                        👎
                      </button>
                    </div>
                  )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Privacy notice */}
          <div className={styles.privacyBar}>
            <span>{CHAT_PRIVACY_NOTICE}</span>
            <button
              type="button"
              className={`${styles.optOutBtn} ${optOut ? styles.optOutBtnActive : ""}`}
              onClick={() => persistOptOut(!optOut)}
            >
              {optOut ? "Opted out" : "Opt out"}
            </button>
          </div>

          {/* Input */}
          <div className={styles.inputRow}>
            <textarea
              ref={inputRef}
              className={styles.input}
              rows={1}
              placeholder={
                conversationExhausted
                  ? "Please try again later."
                  : "Ask about climate data…"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleInputKeyDown}
              disabled={loading || conversationExhausted}
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
                  <rect
                    x="7"
                    y="7"
                    width="10"
                    height="10"
                    rx="1.5"
                    fill="currentColor"
                  />
                </svg>
              </button>
            ) : (
            <button
              type="button"
              className={styles.sendBtn}
              aria-label="Send"
                disabled={!input.trim() || conversationExhausted}
              onClick={() => void sendMessage(input)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" />
              </svg>
            </button>
            )}
          </div>
        </aside>
      )}
    </>
  );
}
